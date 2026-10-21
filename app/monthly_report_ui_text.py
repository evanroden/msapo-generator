"""Display saved/imported values literally in Markdown-capable UI controls."""

import re
from string import punctuation


_ESCAPES = str.maketrans({character: "\\" + character for character in punctuation})
_AUTOLINK_BOUNDARY = re.compile(r"https?(?=://)|www(?=\.)|(?=@)", re.IGNORECASE)


def literal(value):
    """Escape presentation only; callers retain the original identity/value."""
    # GFM detects bare links again after backslash escapes have been decoded.
    # A display-only WORD JOINER breaks URL/email recognition without changing
    # visible text. Never use this encoded label as a stored value or widget key.
    display = _AUTOLINK_BOUNDARY.sub(lambda match: match.group() + "\u2060", str(value))
    return display.translate(_ESCAPES)
