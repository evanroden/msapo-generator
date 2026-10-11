"""Bound only confirmed design photographs in disposable PDF files."""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import pytest
from PIL import Image

from app.monthly_report_pdf_image_budget import (
    compact_native_photos_for_pdf, release_transient_word_memory,
)


def jpeg(w=2400, h=1600, *, tint=60):
    img = Image.effect_noise((w, h), 30).convert("RGB")
    img.paste((tint, 90, 130), (0, 0, 100, 100))
    out = BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def data(tmp_path, *, wide=False):
    allowed = jpeg(4000, 800) if wide else jpeg(tint=60)
    user_upload = jpeg(tint=140)
    master = tmp_path / "synthetic-master.docx"
    with ZipFile(master, "w") as z:
        z.writestr("word/media/old.jpg", allowed)
    word = BytesIO()
    with ZipFile(word, "w") as z:
        z.writestr("word/media/old.jpg", allowed)
        z.writestr("word/media/new-upload.jpg", user_upload)
        z.writestr("word/document.xml", "Q-TEST-731 | Pending | 45 gpm")
    return master, word.getvalue(), allowed, user_upload


def test_exact_pinned_photo_only_and_editable_word_unmodified(tmp_path):
    master, word, original_photo, new_upload = data(tmp_path)
    before = sha256(word).hexdigest()
    pdf_copy = compact_native_photos_for_pdf(word, pinned_source=master)
    assert sha256(word).hexdigest() == before
    assert pdf_copy != word
    with ZipFile(BytesIO(pdf_copy)) as z:
        with Image.open(BytesIO(z.read("word/media/old.jpg"))) as photo:
            assert max(photo.size) == 1400
            assert abs((photo.width / photo.height) - 1.5) < 0.002  # integer pixel rounding
        assert z.read("word/media/new-upload.jpg") == new_upload
        assert z.read("word/document.xml") == b"Q-TEST-731 | Pending | 45 gpm"


def test_very_wide_diagram_retains_original_resolution(tmp_path):
    master, word, _, _ = data(tmp_path, wide=True)
    assert compact_native_photos_for_pdf(word, pinned_source=master) == word


def test_unrecognized_photo_never_touched_and_max_dimension_bounded(tmp_path):
    master, _, _, user_photo = data(tmp_path)
    raw = BytesIO()
    with ZipFile(raw, "w") as z:
        z.writestr("word/media/new-upload.jpg", user_photo)
    assert compact_native_photos_for_pdf(raw.getvalue(), pinned_source=master) == raw.getvalue()
    with pytest.raises(ValueError, match="photograph dimension"):
        compact_native_photos_for_pdf(raw.getvalue(), pinned_source=master, max_edge=100)


def test_optional_os_memory_trim_does_not_change_report():
    release_transient_word_memory()


def test_generated_docx_stays_native_while_pdf_copy_is_compacted(monkeypatch, tmp_path):
    from app import monthly_report_docx as engine, monthly_report_designs as designs
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_model import ReportDraft, ReportPeriod, ReportProfile, Facility

    master, word, *_ = data(tmp_path)
    profile = ReportProfile("Synthetic Contract", "p", "Synthetic Site",
                            (Facility("s", "Synthetic Site"),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", (), ())
    monkeypatch.setattr(engine, "assemble_docx", lambda *args, **kwargs: word)
    monkeypatch.setattr(engine, "rendering_docx", lambda raw, **kwargs: raw)
    monkeypatch.setattr(designs, "render_profile_for", lambda *_: None)
    monkeypatch.setattr(designs, "source_for", lambda *_: master)
    monkeypatch.setattr(engine.pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(engine, "report_filename", lambda draft, ext: "synthetic." + ext)
    seen = {}

    def convert(path, **kwargs):
        with ZipFile(path) as z:
            with Image.open(BytesIO(z.read("word/media/old.jpg"))) as img:
                seen["edge"] = max(img.size)
        pdf = tmp_path / "synthetic.pdf"
        pdf.write_bytes(b"%PDF-synthetic")
        return pdf

    monkeypatch.setattr(jobs, "convert_to_pdf", convert)
    result = engine._generate_report(draft)
    assert result.docx == word
    assert result.pdf == b"%PDF-synthetic"
    assert seen["edge"] == 1400
