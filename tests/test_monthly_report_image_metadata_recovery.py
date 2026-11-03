"""Real PNG/JPEG EXIF failures stay within the rejected upload's boundary."""

from dataclasses import asdict, replace
from email.message import EmailMessage
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_draft, synthetic_profiles


FORMATS = ((".png", "PNG"), (".jpg", "JPEG"))
RECOVERY = "Image structure or metadata could not be read."
FIRST = b"Inspected synthetic pump P-61; bearing temperature was 76 F."
LAST = b"Inspected synthetic valve V-62; the isolation label remained legible."


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def image_bytes(format_name, *, malformed=False, orientation=None):
    output = BytesIO()
    options = {"dpi": (72, 72)}
    if malformed:
        # Valid bounded raster, but the EXIF TIFF header is unreadable. JPEG
        # needs explicit JFIF density so Pillow defers EXIF until orientation.
        options["exif"] = b"Exif\x00\x00invalid!"
    elif orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        options["exif"] = exif
    Image.new("RGB", (12, 8), (17, 93, 160)).save(output, format_name, **options)
    return output.getvalue()


@pytest.mark.parametrize(("suffix", "format_name"), FORMATS)
def test_real_unreadable_exif_has_recoverable_image_ingest_error(profile, suffix, format_name):
    raw = image_bytes(format_name, malformed=True)
    assert len(raw) < 1000
    with Image.open(BytesIO(raw)) as image:
        image.load()
        assert image.size == (12, 8)
    with pytest.raises(ValueError, match=RECOVERY) as rejected:
        sources.ingest(profile, "bad-metadata" + suffix, raw)
    assert isinstance(rejected.value.__cause__, SyntaxError)
    assert "Export a fresh PNG or JPEG copy" in str(rejected.value)
    assert "invalid!" not in str(rejected.value)


@pytest.mark.parametrize(("suffix", "format_name"), FORMATS)
def test_bad_metadata_keeps_both_siblings_and_allows_fresh_image_retry(profile, suffix, format_name):
    raw = image_bytes(format_name, malformed=True)
    filename = "bad-metadata" + suffix
    contents, notices = sources.ingest_batch(profile, (
        ("first.txt", FIRST), (filename, raw), ("last.txt", LAST),
    ))
    assert tuple(item.source.filename for item in contents) == ("first.txt", "last.txt")
    assert tuple(sources.source_bytes(profile, item.source) for item in contents) == (FIRST, LAST)
    assert len(notices) == 1 and notices[0].startswith("Not read: " + filename + ".")
    assert RECOVERY in notices[0] and "invalid!" not in notices[0]
    digest = sha256(raw).hexdigest()
    assert not sources._path(profile, digest, suffix).exists()
    assert not sources._path(profile, digest, ".json").exists()

    corrected = image_bytes(format_name)
    retried, notices = sources.ingest_batch(profile, ((filename, corrected),), contents)
    assert not notices and retried[:2] == contents
    assert sources.source_bytes(profile, retried[-1].source) == corrected
    assert sources.page_image(profile, retried[-1], 1, preview=True).width == 12
    repeated, notices = sources.ingest_batch(profile, ((filename, corrected),), retried)
    assert repeated == retried and notices == ("Duplicate skipped: " + filename,)


@pytest.mark.parametrize("retained", ("original", "orphan-cache"))
def test_rejection_preserves_preexisting_original_or_extraction_cache(profile, retained):
    raw = image_bytes("PNG", malformed=True)
    digest = sha256(raw).hexdigest()
    original = sources._path(profile, digest, ".png")
    cache = sources._path(profile, digest, ".json")
    if retained == "original":
        protected, before = original, raw
    else:
        # A retained cache with a missing original must not be removed when
        # replacing that original fails validation. It is not read in this path.
        prior = sources.SourceContent(ReportSource(
            digest, "prior-image.png", digest, ".png", page_texts=("",), needs_vision=(1,),
        ))
        protected, before = cache, library._json({"schema": 1, **asdict(prior)})
    library._atomic_write(protected, before)
    contents, notices = sources.ingest_batch(profile, (("bad-metadata.png", raw), ("last.txt", LAST)))
    assert len(contents) == len(notices) == 1 and RECOVERY in notices[0]
    assert sources.source_bytes(profile, contents[0].source) == LAST
    assert protected.read_bytes() == before
    assert original.exists() == (retained == "original")
    assert cache.exists() == (retained == "orphan-cache")


@pytest.mark.parametrize("manual", ("  Keep the human inspection note.\n\nNo automatic replacement.\n", ""))
def test_reviewed_sources_manual_text_and_history_survive_rejection_and_reopen(profile, manual):
    accepted, _ = sources.ingest(profile, "existing.txt", FIRST)
    reviewed = replace(accepted, source=replace(
        accepted.source, vendor="Reviewed synthetic vendor", findings="Keep this correction.",
    ))
    period = ReportPeriod(2026, 10)
    draft = synthetic_draft(profile, period)
    draft = replace(draft, sources=(reviewed.source,), blocks=tuple(
        replace(block, text=manual) if block.key == "demo_activity" else block for block in draft.blocks
    ))
    first = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Reviewer")
    history_path = (library._profile_path(profile.contract, profile.key, snapshots=True)
                    / "history" / f"{period.key}-00000001.json")
    history_bytes = history_path.read_bytes()

    other_profile = replace(profile, contract="Independent Synthetic Contract")
    other_content, _ = sources.ingest(other_profile, "independent.txt", b"Independent accepted work.")
    other_draft = replace(synthetic_draft(other_profile, period), sources=(other_content.source,))
    other_saved = library.save_snapshot(other_draft, expected_revision=0)

    contents, notices = sources.ingest_batch(profile, (
        ("bad-metadata.jpg", image_bytes("JPEG", malformed=True)), ("new.txt", LAST),
    ), (reviewed,))
    assert len(notices) == 1 and RECOVERY in notices[0]
    assert contents[0] == reviewed and sources.source_bytes(profile, contents[0].source) == FIRST
    updated = replace(draft, sources=tuple(item.source for item in contents))
    second = library.save_snapshot(updated, expected_revision=1, entered_editor="Synthetic Reviewer")
    reopened = library.load_snapshot(profile.contract, profile.key, period)
    assert reopened == second
    assert next(block.text for block in reopened.draft.blocks if block.key == "demo_activity") == manual
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == first
    assert history_path.read_bytes() == history_bytes
    versions, more = library.snapshot_history(profile.contract, profile.key, period)
    assert tuple(version.revision for version in versions) == (2, 1) and not more
    assert library.load_snapshot(other_profile.contract, other_profile.key, period) == other_saved
    assert library.load_snapshot_version(other_profile.contract, other_profile.key, period, 1) == other_saved
    assert sources.source_bytes(other_profile, other_content.source) == b"Independent accepted work."


@pytest.mark.parametrize(("suffix", "format_name"), FORMATS)
def test_valid_exif_orientation_and_original_bytes_are_preserved(profile, suffix, format_name):
    raw = image_bytes(format_name, orientation=6)
    contents, notices = sources.ingest_batch(profile, (("rotated" + suffix, raw),))
    assert len(contents) == 1 and not notices
    preview = sources.page_image(profile, contents[0], 1, preview=True)
    assert (preview.width, preview.height) == (8, 12)
    assert sources.source_bytes(profile, contents[0].source) == raw


def test_bad_image_attachment_does_not_abandon_email_or_other_direct_attachments(profile):
    message = EmailMessage()
    message["Subject"] = "Synthetic service report"
    message.set_content("Findings: Synthetic inspection complete.")
    message.add_attachment(FIRST, maintype="text", subtype="plain", filename="first.txt")
    message.add_attachment(image_bytes("PNG", malformed=True), maintype="image", subtype="png",
                           filename="bad-metadata.png")
    message.add_attachment(LAST, maintype="text", subtype="plain", filename="last.txt")
    raw = message.as_bytes()
    contents, notices = sources.ingest_batch(profile, (("service.eml", raw),))
    assert tuple(item.source.filename for item in contents) == ("service.eml", "first.txt", "last.txt")
    assert tuple(sources.source_bytes(profile, item.source) for item in contents) == (raw, FIRST, LAST)
    assert len(notices) == 1 and "Not read: bad-metadata.png." in notices[0] and RECOVERY in notices[0]


def test_later_product_syntax_error_is_not_disguised_as_a_bad_image(profile, monkeypatch):
    def programming_error(*args, **kwargs):
        raise SyntaxError("Synthetic product fault after image validation")
    monkeypatch.setattr(sources, "suggest_facts", programming_error)
    with pytest.raises(SyntaxError, match="product fault after image validation"):
        sources.ingest_batch(profile, (("valid.png", image_bytes("PNG")),))
