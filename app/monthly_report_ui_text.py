"""Display saved/imported values literally in Markdown-capable UI controls."""

from string import punctuation


_ESCAPES = str.maketrans({character: "\\" + character for character in punctuation})


def literal(value):
    """Escape presentation only; callers retain the original identity/value."""
    return str(value).translate(_ESCAPES)
