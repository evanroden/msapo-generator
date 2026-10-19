"""Static vector acceptance agrees across inspection and page preservation."""
from io import BytesIO
import struct
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app.monthly_report_word_pages import safe_section_docx
from tests.test_monthly_report_native_metafiles import vector_fixture


def test_passive_page_uses_the_existing_static_metafile_validator(tmp_path, monkeypatch):
    source, _, _, emf = vector_fixture(tmp_path, monkeypatch)
    original = source.read_bytes()
    package = safe_section_docx(source, (1,))
    with ZipFile(BytesIO(package)) as archive:
        assert archive.read("word/media/image1.emf") == emf
        assert b"image/x-emf" in archive.read("[Content_Types].xml")
        assert b'TargetMode="External"' not in b"".join(archive.read(n) for n in archive.namelist() if n.endswith(".rels"))
    assert source.read_bytes() == original


@pytest.mark.parametrize("mutation", ["escape", "truncated", "oversized_dimensions"])
def test_nonstatic_or_malformed_metafile_stays_unresolved(tmp_path, monkeypatch, mutation):
    source, _, _, emf = vector_fixture(tmp_path, monkeypatch)
    data = bytearray(emf)
    if mutation == "escape":
        struct.pack_into("<I", data, 88, 105)
    elif mutation == "truncated":
        data.pop()
    else:
        struct.pack_into("<iiii", data, 8, 0, 0, 300000, 300000)
        struct.pack_into("<iiii", data, 24, 0, 0, 7620000, 7620000)
    with ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/media/image1.emf"] = bytes(data)
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for name, raw in parts.items():
            archive.writestr(name, raw)
    with pytest.raises(ValueError, match="static|picture format"):
        safe_section_docx(source, (1,))
