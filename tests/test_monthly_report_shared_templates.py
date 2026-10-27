"""Invented template bytes only; genuine originals and hashes stay outside Git."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import stat
import struct
import tomllib
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from docx import Document
import pytest

from app import monthly_report_shared_templates as templates
from app.monthly_report_fixture_vault import VaultIntegrityError, VaultQuotaExceeded
from app.monthly_report_shared_source_bundles import SharedSourceBundles, SharedSyntheticEvidenceBundles


def invented_template(*, text="Synthetic report template", extra=None, omit=None):
    document = Document()
    document.add_heading(text, 0)
    stream = BytesIO()
    document.save(stream)
    if not extra and not omit:
        return stream.getvalue()
    output = BytesIO()
    with ZipFile(stream) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            if member.filename != omit:
                target.writestr(member, source.read(member))
        if extra:
            target.writestr(*extra)
    return output.getvalue()


def test_template_survives_new_reader_and_duplicate_upload_without_other_scope_changes(tmp_path):
    raw = invented_template()
    shelf = templates.SharedReportTemplates(tmp_path)
    receipt = shelf.upload(raw, "Synthetic monthly template (2).docx")
    assert receipt.archive_size == len(raw)
    assert receipt.archive_sha256 == sha256(raw).hexdigest()
    assert receipt.source_files[0].filename == "Synthetic monthly template (2).docx"
    assert shelf.upload(raw, "Renamed copy.docx") == receipt
    fresh_reader = templates.SharedReportTemplates(tmp_path)
    assert fresh_reader.list() == (receipt,)
    assert fresh_reader.download(receipt.bundle_id) == raw
    assert SharedSourceBundles(tmp_path).list() == ()
    assert SharedSyntheticEvidenceBundles(tmp_path).list() == ()
    assert {path.name for path in tmp_path.iterdir()} == {templates._BUCKET}


@pytest.mark.parametrize("filename", ["../bad.docx", "\\bad.docx", "bad.docm", "bad.docx\n", "bad/part.docx", "bad.docx.exe"])
def test_invalid_filename_never_creates_storage(tmp_path, filename):
    with pytest.raises(ValueError, match="filename"):
        templates.SharedReportTemplates(tmp_path).upload(invented_template(), filename)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("extra", ["../outside", "/absolute", "word/../outside", "word\\outside", "word//outside", "word/drive:part"])
def test_unsafe_member_names_never_create_storage(tmp_path, extra):
    with pytest.raises(ValueError, match="Unsafe"):
        templates.SharedReportTemplates(tmp_path).upload(invented_template(extra=(extra, b"data")), "Synthetic.docx")
    assert not tuple(tmp_path.iterdir())


def test_missing_duplicate_symlink_and_bad_crc_are_rejected(tmp_path):
    shelf = templates.SharedReportTemplates(tmp_path)
    with pytest.raises(ValueError, match="complete DOCX"):
        shelf.upload(invented_template(omit="word/document.xml"), "Synthetic.docx")
    with pytest.warns(UserWarning, match="Duplicate"):
        duplicate = invented_template(extra=("word/document.xml", b"duplicate"))
    with pytest.raises(ValueError, match="unique"):
        shelf.upload(duplicate, "Synthetic.docx")
    link = ZipInfo("word/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="Unsafe"):
        shelf.upload(invented_template(extra=(link, b"outside")), "Synthetic.docx")
    raw = bytearray(invented_template())
    with ZipFile(BytesIO(raw)) as package:
        member = package.getinfo("word/document.xml")
        position = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
    raw[position + member.compress_size // 2] ^= 1
    with pytest.raises(ValueError, match="integrity"):
        shelf.upload(bytes(raw), "Synthetic.docx")
    assert not tuple(tmp_path.iterdir())


def test_count_and_expansion_bounds_precede_storage(tmp_path, monkeypatch):
    raw = invented_template()
    forged = bytearray(raw)
    offset = forged.rfind(b"PK\x05\x06")
    struct.pack_into("<H", forged, offset + 10, 6000)
    with pytest.raises(ValueError, match="index"):
        templates.SharedReportTemplates(tmp_path).upload(bytes(forged), "Synthetic.docx")
    monkeypatch.setattr(templates, "MAX_EXPANDED_BYTES", len(raw))
    with pytest.raises(ValueError, match="oversized"):
        templates.SharedReportTemplates(tmp_path).upload(raw, "Synthetic.docx")
    assert not tuple(tmp_path.iterdir())


def test_exact_upload_bound_and_shelf_quota_preserve_prior_original(tmp_path):
    raw = invented_template()
    with pytest.raises(VaultQuotaExceeded, match="upload limit"):
        templates.SharedReportTemplates(tmp_path, max_template_bytes=len(raw)-1).upload(raw, "Synthetic.docx")
    shelf = templates.SharedReportTemplates(tmp_path, max_template_bytes=len(raw),
                                           max_shelf_bytes=len(raw) + 64 * 1024)
    receipt = shelf.upload(raw, "Synthetic.docx")
    other = invented_template(text="Another synthetic report")
    # A fresh store with the same bounded shelf permits the second file size,
    # but refuses aggregate occupancy without changing the first original.
    shelf = templates.SharedReportTemplates(tmp_path, max_template_bytes=max(len(raw), len(other)),
                                           max_shelf_bytes=len(raw) + 64 * 1024)
    with pytest.raises(VaultQuotaExceeded, match="full"):
        shelf.upload(other, "Another.docx")
    assert shelf.download(receipt.bundle_id) == raw


@pytest.mark.parametrize("change", ["bytes", "link", "receipt"])
def test_corrupt_or_replaced_storage_cannot_be_downloaded(tmp_path, change):
    raw = invented_template()
    shelf = templates.SharedReportTemplates(tmp_path)
    receipt = shelf.upload(raw, "Synthetic.docx")
    directory = tmp_path / templates._BUCKET / receipt.bundle_id
    original = directory / (receipt.archive_sha256 + ".docx")
    if change == "bytes":
        original.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    elif change == "link":
        outside = tmp_path / "outside.docx"
        outside.write_bytes(raw)
        original.unlink()
        original.symlink_to(outside)
    else:
        path = directory / "receipt.json"
        data = json.loads(path.read_bytes())
        data["source_files"][0]["sha256"] = "f" * 64
        path.write_bytes(templates.storage._json_bytes(data))
    with pytest.raises((VaultIntegrityError, OSError)):
        shelf.download(receipt.bundle_id)
    assert original.exists()


def test_storage_limit_server_and_external_agent_limit_agree_above_200_mib():
    from scripts.qa_render_archive_redeploy_readonly import SHELVES
    config_path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
    config = tomllib.loads(config_path.read_text())
    assert templates.MAX_TEMPLATE_MIB == 512
    assert config["server"]["maxUploadSize"] == templates.MAX_TEMPLATE_MIB
    assert SHELVES["templates"]["max_size"] == templates.MAX_TEMPLATE_BYTES
    assert templates.MAX_SHELF_BYTES >= templates.MAX_TEMPLATE_BYTES
