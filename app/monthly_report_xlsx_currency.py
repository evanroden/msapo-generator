"""Keep explicit currency evidence beside stored XLSX numbers, without rendering.

This is not an Excel display formatter: values are never rounded or scaled.
Only the applicable number-format section can supply a monetary marker.
"""

from decimal import Decimal, InvalidOperation
from datetime import date, time, timedelta
import math
import operator
import re

from openpyxl.styles.numbers import BUILTIN_FORMATS, BUILTIN_FORMATS_MAX_SIZE, is_date_format

from app.monthly_report_content_policy import _CURRENCIES, _CURRENCY_SYMBOLS
from app.monthly_report_directory import _format_sections


_TOKENS = re.compile(r'"[^"]*"|\\.|_.|\*.|\[[^]]*\]|.', re.S)
_CURRENCY = re.compile(rf"{_CURRENCY_SYMBOLS}|\b(?:{_CURRENCIES}|dollars?)\b", re.I)
_CONDITION = re.compile(
    r"\[\s*(<=|>=|<>|=|<|>)\s*"
    r"([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?)\s*\]")
_COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
            ">=": operator.ge, "=": operator.eq, "<>": operator.ne}
_REVIEW = ("Workbook currency number format needs review. Use a standard currency "
           "format or export CSV with explicit currency text.")


def _marker(tokens):
    literal = []
    for token in tokens:
        if token.startswith('"'):
            literal.append(token[1:-1])
        elif token.startswith(("\\", "*")):
            # Fill repeats a visible glyph. One copy retains its meaning.
            literal.append(token[1:])
        elif token.startswith("_"):
            literal.append(" ")  # Width reservation does not display its glyph.
        elif token.startswith("["):
            # [$-409] is locale-only; [$$-409] and [$USD-409] carry currency.
            currency = re.fullmatch(r"\$([^-\]]*)(?:-[^\]]+)?", token[1:-1])
            if currency:
                literal.append(currency[1])
        else:
            literal.append(" " if token in "0#?" else token)
    found = _CURRENCY.search("".join(literal))
    return found[0] if found else ""


def _condition(tokens):
    candidates = [token for token in tokens
                  if token.startswith("[") and token[1:-1].lstrip()[:1] in ("<", ">", "=")]
    if not candidates:
        return None
    match = _CONDITION.fullmatch(candidates[0])
    if len(candidates) != 1 or not match:
        raise ValueError(_REVIEW)
    try:
        threshold = Decimal(match[2])
    except InvalidOperation as exc:
        raise ValueError(_REVIEW) from exc
    if not threshold.is_finite():
        raise ValueError(_REVIEW)
    return match[1], threshold


def _numeric_sections(number_format):
    sections = [tuple(_TOKENS.findall(section)) for section in _format_sections(number_format)]
    # A fourth section is text; a genuine trailing @ can also form a shorter
    # text section. Quoted/escaped @ tokens remain ordinary numeric literals.
    if len(sections) == 4 or (sections and "@" in sections[-1]
                             and not any(token in ("0", "#", "?") for token in sections[-1])):
        sections.pop()
    return sections


def _pattern(tokens):
    return "".join(token for token in tokens if not token.startswith(('"', "\\", "_", "*")))


def preserve_currency_number_types(workbook):
    """Keep false date-style detection from converting/rounding monetary numbers.

    openpyxl splits a format at its first semicolon before removing quoted
    literals. A valid '"USD;"0' is consequently mistaken for a date. Correct
    only currency-bearing false positives in this disposable reader, using
    its own date detector after the existing quote-aware section lexer.
    """
    for index in tuple(workbook._date_formats):
        number = workbook._cell_styles[index].numFmtId
        code = (BUILTIN_FORMATS.get(number, "") if number < BUILTIN_FORMATS_MAX_SIZE
                else workbook._number_formats[number - BUILTIN_FORMATS_MAX_SIZE])
        sections = _numeric_sections(code)
        if not sections:
            continue
        if any(_marker(tokens) for tokens in sections) and not is_date_format(_pattern(sections[0])):
            workbook._date_formats.discard(index)


def currency_evidence_value(value, number_format):
    """Preserve the stored number and only its active, explicit currency marker."""
    if not number_format:
        return value
    if type(value) not in (int, float):
        # A genuine date section can coexist with a monetary numeric section.
        # Once the reader has converted a value to a date/time, reversing that
        # conversion would lose stored precision. Require a clearer source.
        if isinstance(value, (date, time, timedelta)) and any(
                _marker(tokens) and not is_date_format(_pattern(tokens))
                for tokens in _numeric_sections(number_format)):
            raise ValueError(_REVIEW)
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return value
    # openpyxl exposes built-in dollar accounting 44 as one mixed numeric/@
    # string. All three numeric cases carry dollars; do not treat it as text.
    if number_format == BUILTIN_FORMATS[44]:
        return f"{value} $"
    sections = _numeric_sections(number_format)
    if not sections or not any(_marker(tokens) for tokens in sections):
        return value
    if len(sections) > 3 or any(
            token in ('"', "\\", "_", "*", "[", "@") for tokens in sections for token in tokens):
        raise ValueError(_REVIEW)
    conditions = [_condition(tokens) for tokens in sections]
    if any(conditions):
        # First/second numeric conditions override sign selection. An omitted
        # condition is a fallback, not an unconditional first-section match.
        if conditions[0] is None or (len(conditions) > 2 and conditions[2] is not None):
            raise ValueError(_REVIEW)
        number = Decimal(str(value))
        selected = next((i for i, condition in enumerate(conditions[:2])
                         if condition and _COMPARE[condition[0]](number, condition[1])), None)
        if selected is None:
            selected = 2 if len(conditions) > 1 and conditions[1] else 1
            if selected >= len(sections) or conditions[selected] is not None:
                raise ValueError(_REVIEW)
    else:
        selected = 1 if value < 0 and len(sections) > 1 else (
            2 if value == 0 and len(sections) > 2 else 0)
    marker = _marker(sections[selected])
    return f"{value} {marker}" if marker else value
