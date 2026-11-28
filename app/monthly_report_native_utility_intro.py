"""Source-only utility intro decorations, separate from plain-empty authority.

This closed envelope is intentionally not a generic source-page classifier.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

from app.monthly_report_native_art_scope import W
from app.monthly_report_native_interior_tail import _signature


@dataclass(frozen=True)
class UtilityDecorationReceipt:
    scope_sha256: str
    # Original source position or None, plus observed live/support/heading bits.
    roots: tuple
    activities: tuple = ()


def decoration_receipt(scope, body, pages):
    return UtilityDecorationReceipt(scope.sha256, tuple(
        (pages.source_positions.get(n), n in pages.live, n in pages.support,
         n in pages.headings) for n in body), tuple(
        (pages.source_word_sections[pages.owner[n]] if n in pages.owner else None,
         pages.source_positions.get(n), n in pages.live, n in pages.support,
         n in pages.headings)
        for n in pages.live | pages.support | pages.headings))


def _decoration_plain(node, *, boundary=False, label=False):
    from app.monthly_report_native_utility_prune import _plain
    clone = deepcopy(node)
    # A direct numeric run-spacing leaf is source formatting, not content.
    # Validate before removing it from this local grammar-check copy only.
    for pr in clone.iter(W+'rPr'):
        spacings = pr.findall(W+'spacing')
        if len(spacings) > 1:
            return False
        for spacing in spacings:
            if (len(spacing) or set(spacing.attrib) != {W+'val'}
                    or not re.fullmatch(r'-?[0-9]{1,5}', spacing.get(W+'val', ''))
                    or (spacing.text or '').strip() or (spacing.tail or '').strip()):
                return False
            pr.remove(spacing)
    if label:
        for name, parent in (('pageBreakBefore', W+'pPr'), ('lastRenderedPageBreak', W+'r')):
            markers = list(clone.iter(W+name))
            if len(markers) > 1:
                return False
            for marker in markers:
                container = marker.getparent()
                if (marker.attrib or len(marker) or (marker.text or '').strip()
                        or (marker.tail or '').strip() or container.tag != parent
                        or (container.getparent() is not clone)):
                    return False
                container.remove(marker)
    return _plain(clone, boundary=boundary)


def intro_envelope(roots, start, draft):
    """Return exact expected roots and source support IDs, never output-derived."""
    from app.monthly_report_import import _text
    from app.monthly_report_native_layout import _MONTH, _set_text
    from app.monthly_report_native_rate_label import _label
    from app.monthly_report_native_utility_prune import _empty_signature
    expected, labels, months = [], [], []
    for offset, node in enumerate(roots):
        position = start + offset + 1
        text = _text(node)
        label = re.fullmatch(r'(Client Utility Rate Analysis)(?:\s+Author:.*)?', text, re.I)
        month = re.fullmatch(_MONTH, text)
        if not _decoration_plain(node, boundary=offset == len(roots)-1, label=bool(label)):
            return None
        clone = deepcopy(node)
        if label:
            _set_text(clone, label[1]); labels.append(position)
            expected.append(_signature(clone))
        elif month:
            _set_text(clone, draft.period.label); months.append(position)
            expected.append(_signature(clone))
        elif _label(node):
            # The existing source-only Rate trend path clears directly.
            # Predict that path rather than normalizing output into permission.
            for text_node in clone.iter(W+'t'):
                text_node.text = ''
            expected.append(_signature(clone))
        else:
            expected.append(_empty_signature(node))
    if len(labels) != 1 or len(months) != 1:
        return None
    return tuple(expected), tuple(sorted(labels + months))
