"""Synthetic direct EML/MSG attachment isolation, parent identity and privacy.

No client source bytes. The MSG case substitutes only the OLE stream reader;
the EML batch and stored/reloaded original bytes use the real parsers.
"""
from dataclasses import asdict, replace
from email.message import EmailMessage
from hashlib import sha256
from io import BytesIO
import json
import logging
import sys
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_source_status import source_manager_status


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def _picture():
    stream = BytesIO()
    Image.new("RGB", (4, 4), (30, 50, 70)).save(stream, "PNG")
    return stream.getvalue()


def _mail():
    message = EmailMessage()
    message["From"] = "do-not-export@example.invalid"
    message["Subject"] = "Synthetic bundle"
    message.set_content(
        "<html><body><p>Scheduled synthetic maintenance is pending.</p>"
        "<script>PRIVATE_BODY_CANARY</script></body></html>", subtype="html")
    one = b"Asset,Status\nV-001,Pending\n"
    two = b"Asset,Status\nV-002,Reviewed\n"
    message.add_attachment(one, maintype="text", subtype="csv", filename="vendor.csv")
    message.add_attachment(b"not a PNG", maintype="image", subtype="png", filename="duplicate.png")
    message.add_attachment(two, maintype="text", subtype="csv", filename="vendor.csv")
    message.add_attachment(_picture(), maintype="image", subtype="png",
                           filename="inline.png", disposition="inline", cid="<synthetic>")
    nested = EmailMessage()
    nested.set_content("Private forwarded text.")
    compressed = BytesIO()
    with ZipFile(compressed, "w", compression=ZIP_DEFLATED) as zipped:
        zipped.writestr("bounded-synthetic-content.txt", b"Z" * 200_000)
    nested.add_attachment(compressed.getvalue(), maintype="application", subtype="zip",
                          filename="explosive.zip")
    message.add_attachment(nested, subtype="rfc822", filename="forwarded.eml")
    return message.as_bytes(), one, two


def test_good_bad_good_email_children_have_durable_parent_links_and_safe_body(profile, caplog):
    caplog.set_level(logging.DEBUG)
    raw, first, second = _mail()
    contents, messages = sources.ingest_batch(profile, (("bundle.eml", raw),))
    assert len(contents) == 4
    parent_hash = sha256(raw).hexdigest()
    parent = next(item for item in contents if item.source.sha256 == parent_hash)
    assert sources.source_bytes(profile, parent.source) == raw
    children = [item for item in contents if item.source.sha256 != parent_hash]
    assert [item.source.filename for item in children] == [
        "vendor.csv", "vendor.csv", "inline.png"]
    assert [item.source.attachment_parent_sha256 for item in children] == [parent_hash] * 3
    assert [item.source.attachment_index for item in children] == [1, 3, 4]
    assert len({item.source.sha256 for item in contents}) == 4
    assert sources.source_bytes(profile, children[0].source) == first
    assert sources.source_bytes(profile, children[1].source) == second
    assert sources.source_bytes(profile, children[2].source) == _picture()
    assert any("duplicate.png" in msg and "attachment 2 of bundle.eml" in msg
               and "Not read" in msg for msg in messages)
    assert not any("explosive.zip" in msg for msg in messages)
    assert not sources._path(profile, sha256(b"not a PNG").hexdigest(), ".png").exists()
    assert "Nested email retained" in " ".join(parent.source.notices)
    assert "Scheduled synthetic maintenance is pending" in parent.source.page_texts[0]
    assert "do-not-export@example.invalid" not in parent.source.page_texts[0]
    assert "PRIVATE_BODY_CANARY" not in parent.source.page_texts[0]
    assert "PRIVATE_BODY_CANARY" not in caplog.text
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 9)),
                    sources=tuple(item.source for item in contents))
    status = source_manager_status(draft, contents)
    child_status = [entry for entry in status if entry.source_id != parent_hash]
    assert ["Attachment 1 of bundle.eml", "Attachment 3 of bundle.eml",
            "Attachment 4 of bundle.eml"] == [
        entry.summary.split(" · ")[0] for entry in child_status]
    assert all("PRIVATE_BODY_CANARY" not in entry.summary for entry in status)
    # Full draft/source metadata is serializable without changing content hashes.
    loaded = library.draft_from_dict(asdict(draft))
    assert loaded.sources == draft.sources
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor="Synthetic Operator")
    assert library.load_snapshot(profile.contract, profile.key, ReportPeriod(2026, 9)) == saved
    assert saved.draft.sources == draft.sources


def test_duplicate_bytes_are_not_substituted_and_reimport_keeps_human_edits(profile):
    message = EmailMessage()
    message.set_content("Synthetic control.")
    payload = b"Asset,Status\nV-001,Pending\n"
    for _ in range(2):
        message.add_attachment(payload, maintype="text", subtype="csv", filename="same.csv")
    initial, messages = sources.ingest_batch(profile, (("duplicates.eml", message.as_bytes()),))
    assert len(initial) == 2
    assert any("Duplicate skipped: same.csv (attachment 2 of duplicates.eml)" in m
               for m in messages)
    child = initial[1]
    assert child.source.attachment_index == 1
    assert sources.source_bytes(profile, child.source) == payload
    edited = replace(child, source=replace(child.source, classification="CMMS export"))
    rerun, notes = sources.ingest_batch(profile, (("duplicates.eml", message.as_bytes()),),
                                        (initial[0], edited))
    assert rerun == (initial[0], edited)
    assert notes == ("Duplicate skipped: duplicates.eml",)


def test_invalid_direct_email_child_does_not_block_following_siblings(profile):
    message = EmailMessage()
    message.set_content("Synthetic email.")
    message.add_attachment(b"", maintype="text", subtype="plain", filename="empty.txt")
    message.add_attachment(b"Asset,Status\nA,Reviewed\n", maintype="text",
                           subtype="csv", filename="good.csv")
    message.add_attachment(b"ZIP bytes", maintype="application", subtype="zip",
                           filename="unsupported.zip")
    result, failures = sources.ingest_batch(profile, (("outer.eml", message.as_bytes()),))
    assert {item.source.filename for item in result} == {"outer.eml", "good.csv"}
    assert any("empty.txt" in x and "attachment 1 of outer.eml" in x for x in failures)
    assert any("unsupported.zip" in x and "attachment 3 of outer.eml" in x for x in failures)


def test_malformed_mime_transfer_encoding_keeps_later_good_attachment(profile):
    message = EmailMessage()
    message.set_content("No implied completed work.")
    message.add_attachment(b"bad", maintype="text", subtype="plain", filename="bad.txt")
    message.get_payload()[-1].set_payload("%%%invalid-base64%%%")
    message.add_attachment(b"Asset,Status\nV-009,Pending\n",
                           maintype="text", subtype="csv", filename="valid.csv")
    rows, errors = sources.ingest_batch(profile, (("malformed.eml", message.as_bytes()),))
    assert [item.source.filename for item in rows] == ["malformed.eml", "valid.csv"]
    assert any("bad.txt (attachment 1 of malformed.eml)" in error for error in errors)
    assert any("Email attachment 1 has invalid MIME encoding" in note
               for note in rows[0].source.notices)
    assert rows[1].source.attachment_index == 2


def test_legacy_fingerprint_excludes_absent_attachment_fields(profile):
    source, _ = sources.ingest(profile, "prior.txt", b"Unchanged synthetic prior text.")
    record = asdict(source.source)
    for name in ("scope_review", "pdf_text_blocks", "financial_source_review",
                 "financial_page_reviews", "attachment_parent_sha256", "attachment_index"):
        if not record.get(name):
            record.pop(name, None)
    expected = sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert source.source.fingerprint == expected


def test_msg_property_failure_is_isolated_to_one_child(profile, monkeypatch):
    """Mocked CFB directory: genuine bytes are exercised by test_monthly_report_sources."""
    blobs = {
        ("__substg1.0_0037001F",): "Synthetic MSG bundle".encode("utf-16-le"),
        ("__substg1.0_1000001F",): "Scheduled synthetic job is pending.".encode("utf-16-le"),
        ("__substg1.0_0C1A001F",): "private-msg-sender@example.invalid".encode("utf-16-le"),
    }
    for n, payload in enumerate((b"Asset,Status\nA,Reviewed\n", b"broken",
                                 b"Asset,Status\nB,Reviewed\n")):
        folder = f"__attach_version1.0_#{n:08x}"
        blobs[(folder, "__substg1.0_3707001F")] = f"vendor-{n}.csv".encode("utf-16-le")
        blobs[(folder, "__substg1.0_37010102")] = payload

    class FakeOle:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def listdir(self):
            return [list(p) for p in blobs]

        def exists(self, path):
            return tuple(path) in blobs

        def get_size(self, path):
            if tuple(path) == ("__attach_version1.0_#00000001", "__substg1.0_37010102"):
                return sources.MAX_FILE_BYTES + 1
            return len(blobs[tuple(path)])

        def openstream(self, path):
            return BytesIO(blobs[tuple(path)])

    monkeypatch.setitem(sys.modules, "olefile", SimpleNamespace(OleFileIO=FakeOle, DEFECT_INCORRECT=1))
    raw = b"Synthetic mocked CFB adapter"
    items, errors = sources.ingest_batch(profile, (("envelope.msg", raw),))
    assert any("vendor-1.csv (attachment 2 of envelope.msg)" in err and "Not read" in err
               for err in errors)
    assert [item.source.filename for item in items] == [
        "envelope.msg", "vendor-0.csv", "vendor-2.csv"]
    assert [item.source.attachment_index for item in items[1:]] == [1, 3]
    assert all(item.source.attachment_parent_sha256 == sha256(raw).hexdigest()
               for item in items[1:])
    assert any("MSG attachment 2" in note for note in items[0].source.notices)
    assert "pending" in items[0].source.page_texts[0]
    assert "private-msg-sender@example.invalid" not in items[0].source.page_texts[0]
