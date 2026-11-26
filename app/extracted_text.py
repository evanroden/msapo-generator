"""Display-equivalent normalization for text read from uploaded Word and PDF files.

Only characters that render the same as (or invisibly beside) a plainer form are
changed, so a search, a heading match or an AI reading sees what the reader of
the original sees. Apply the same function to every string that is later
compared or hashed against extracted text, so offsets and digests still agree.
"""

# Presentation-form ligatures (U+FB00..FB06). Some PDF producers map a single
# ligature glyph to these code points, so "efficient" would not match "eﬃcient".
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_TABLE = str.maketrans({
    **_LIGATURES,
    "‑": "-",   # non-breaking hyphen renders as an ordinary hyphen
    "​": "",    # zero-width space (invisible optional break)
    "﻿": "",    # zero-width no-break space / stray byte-order mark
    "": "•",  # Symbol-font bullet left in the private-use area
})


def normalize_extracted_text(text: str) -> str:
    """Return ``text`` with display-equivalent characters made plain."""
    return text.translate(_TABLE) if text else text


# Word w:sym characters name a glyph in a symbol font, not a Unicode character.
# Adobe Symbol encoding (the subset with an unambiguous Unicode equivalent).
_SYMBOL = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&",
    0x27: "∋", 0x28: "(", 0x29: ")", 0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−",
    0x2E: ".", 0x2F: "/", **{c: chr(c) for c in range(0x30, 0x3A)}, 0x3A: ":", 0x3B: ";",
    0x3C: "<", 0x3D: "=", 0x3E: ">", 0x3F: "?", 0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ",
    0x47: "Γ", 0x48: "Η", 0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ",
    0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ",
    0x53: "Σ", 0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ",
    0x59: "Ψ", 0x5A: "Ζ", 0x5B: "[", 0x5C: "∴", 0x5D: "]", 0x5E: "⊥", 0x5F: "_",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ",
    0x67: "γ", 0x68: "η", 0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ",
    0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π", 0x71: "θ", 0x72: "ρ",
    0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ",
    0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|", 0x7D: "}", 0x7E: "∼",
    0xA0: "€", 0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞",
    0xA6: "ƒ", 0xA7: "♣", 0xA8: "♦", 0xA9: "♥", 0xAA: "♠", 0xAB: "↔",
    0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xB0: "°", 0xB1: "±",
    0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•",
    0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…", 0xC0: "ℵ",
    0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xC9: "⊃",
    0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉",
    0xD0: "∠", 0xD1: "∇", 0xD2: "®", 0xD3: "©", 0xD4: "™", 0xD5: "∏",
    0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔",
    0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓", 0xE0: "◊", 0xE5: "∑",
    0xF2: "∫",
}
# Only the check marks, boxes and bullets that Word inserts for status columns
# and checklists; other dingbats have no reliable text equivalent.
_WINGDINGS = {0x6C: "●", 0x6E: "■", 0x6F: "□", 0x71: "❑", 0xA7: "▪",
              0xA8: "☐", 0xD8: "➢", 0xFB: "✗", 0xFC: "✓", 0xFD: "☒",
              0xFE: "☑"}
_WINGDINGS_2 = {0x4F: "✗", 0x50: "✓", 0x52: "☑", 0x54: "☒", 0xA3: "☐"}
_SYMBOL_FONTS = {"symbol": _SYMBOL, "wingdings": _WINGDINGS, "wingdings 2": _WINGDINGS_2}
# Picture fonts whose codes are glyph slots, not letters: an unmapped code in one
# of these must stay a symbol, never become the ASCII letter at that code.
_GLYPH_FONTS = {"webdings", "wingdings 3", "zapf dingbats", "itc zapf dingbats",
                "marlett", "mt extra", "bookshelf symbol 7", "ms reference specialty",
                "ms outlook", "segoe mdl2 assets", "holomdl2 assets"}


def _is_glyph_font(name: str) -> bool:
    return (name in _GLYPH_FONTS or "dings" in name or "symbol" in name
            or name.endswith(" assets"))


def word_symbol_text(font: str, char: str) -> str:
    """Unicode text for a Word ``w:sym`` (font, hex code), or "" when unknown.

    Symbol fonts address glyphs either directly (``00B0``) or through the
    private-use offset Word writes (``F0B0``). An ordinary text font's code is
    already Unicode. Unknown dingbats stay empty instead of becoming garbage.
    """
    try:
        code = int(char or "", 16)
    except ValueError:
        return ""
    name = (font or "").strip().casefold()
    table = _SYMBOL_FONTS.get(name)
    if table is not None:
        return table.get(code - 0xF000 if code >= 0xF000 else code, "")
    if _is_glyph_font(name):
        return ""
    if 0x20 <= code < 0xD800 and not 0x7F <= code < 0xA0:
        return chr(code)
    return ""
