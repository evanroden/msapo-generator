"""Conflicting native site labels cannot lend one site's identity to all work."""
from dataclasses import asdict, replace
from datetime import date
from io import BytesIO
import os
from pathlib import Path
import tempfile

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, SectionSpec
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_details import correct_source_details, detail_problems
from app.monthly_report_source_recovery import restore_sources

PROFILE = ReportProfile("Synthetic Site Contract", "north", "Synthetic North",
                        (Facility("north", "Synthetic North", ("North Campus",)),))
PERIOD = ReportPeriod(2026, 9)


def source_bytes(labels, suffix, *, extra=""):
    text = "Service report\nVendor: Synthetic Mechanical\nService date: 2026-09-04\n"
    text += "\n\n".join(f"{heading}: {value}\nInspected pump P-{n}." for n, (heading, value) in enumerate(labels))
    text += "\n" + extra
    if suffix == ".txt":
        return text.encode()
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.fixture
def portable_ingest(monkeypatch, tmp_path):
    # Real ingest/extraction/suggestion/integrity readers, temporary path/writer
    # only. Warm cache and real saved storage stay on enabled Linux tests below.
    def write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    monkeypatch.setattr(sources, "_path", lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", write)
    def read(labels, suffix, *, extra="", profile=PROFILE):
        raw = source_bytes(labels, suffix, extra=extra)
        content, attachments = sources.ingest(profile, "synthetic-maintenance report" + suffix, raw)
        assert not attachments and sources.source_bytes(profile, content.source) == raw
        return content, raw
    return read


def report(content, *, manual=None):
    block = structured.native_update((content,), "activity_summary")
    if manual is not None:
        block = replace(block, text=manual)
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor",
        (SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),)),),
        (block,), sources=(content.source,), synthetic=True)


def site_blockers(draft):
    return [check for check in preflight(draft) if check.code == "source_facility" and check.blocking]


def template(tmp_path):
    path = tmp_path / "synthetic-design.docx"
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Old placeholder")
    doc.save(path)
    return path


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
@pytest.mark.parametrize("labels", [
    (("Site", "Synthetic North"), ("Site", "Foreign South")),
    (("Site", "Foreign South"), ("Site", "Synthetic North")),
    (("Facility", "Synthetic North"), ("Building", "Foreign South")),
    (("Site", "North Campus"), ("Facility", "Unknown Place")),
    (("Site", "Unknown One"), ("Site", "Unknown Two")),
])
def test_distinct_explicit_sites_stay_unknown_and_block_public_output(portable_ingest, suffix, labels):
    content, raw = portable_ingest(labels, suffix, extra="Mention of Synthetic North cannot resolve conflicting labels.")
    before = asdict(content)
    assert content.source.facility == ""
    assert content.source.vendor == "Synthetic Mechanical" and content.source.service_date == "2026-09-04"
    draft = report(content)
    assert "P-0" in draft.blocks[0].text and "P-1" in draft.blocks[0].text
    assert "site unknown" in detail_problems(content.source, PROFILE, PERIOD, in_report=True, draft=draft)
    assert site_blockers(draft)
    with pytest.raises(ValueError, match="Establish the site scope"):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    assert asdict(content) == before and sources.source_bytes(PROFILE, content.source) == raw


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
@pytest.mark.parametrize("labels, expected", [
    ((("Site", "Synthetic North"),), "Synthetic North"),
    ((("Site", "Synthetic North"), ("Site", "Synthetic North")), "Synthetic North"),
    ((("Site", "Synthetic North"), ("Facility", "synthetic north")), "Synthetic North"),
    ((("Site", "Synthetic North"), ("Building", "North Campus"), ("Facility", "north")), "Synthetic North"),
    ((("Site", "North Campus"), ("Facility", "Synthetic North")), "North Campus"),
    ((("Site", "Foreign South"), ("Facility", "foreign south")), "Foreign South"),
])
def test_single_repeated_or_known_alias_identity_preserves_original_label(portable_ingest, suffix, labels, expected):
    content, raw = portable_ingest(labels, suffix)
    assert content.source.facility == expected
    assert sources.source_bytes(PROFILE, content.source) == raw
    assert bool(site_blockers(report(content))) == (expected == "Foreign South")


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
@pytest.mark.parametrize("extra, expected", [("Inspected pump at North Campus.", "Synthetic North"),
                                             ("Inspected an unlabeled pump.", "")])
def test_no_explicit_label_keeps_existing_unlabeled_inference(portable_ingest, suffix, extra, expected):
    content, _ = portable_ingest((), suffix, extra=extra)
    assert content.source.facility == expected


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_whitespace_only_label_retains_no_value_fallback(portable_ingest, suffix):
    content, _ = portable_ingest((("Site", "   "),), suffix, extra="Inspected equipment at North Campus.")
    assert content.source.facility == "Synthetic North"


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_repeated_unknown_label_ignores_case_and_spacing_only(portable_ingest, suffix):
    content, _ = portable_ingest((("Site", "Unlisted   Campus"), ("Facility", "unlisted campus")), suffix)
    # Word's existing inspector normalizes run whitespace before suggestions.
    assert content.source.facility == ("Unlisted   Campus" if suffix == ".txt" else "Unlisted Campus")
    assert site_blockers(report(content))


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_alias_colliding_with_another_site_key_does_not_establish_equivalence(portable_ingest, suffix):
    profile = ReportProfile("Synthetic Site Contract", "combined", "Combined",
        (Facility("north", "Synthetic North", ("shared",)), Facility("shared", "Synthetic South")), scope_type="multi_site")
    content, _ = portable_ingest((("Site", "shared"), ("Facility", "north")), suffix, profile=profile)
    assert content.source.facility == ""


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_source_details_offer_unknown_then_keep_explicit_manual_correction(portable_ingest, suffix):
    content, raw = portable_ingest((("Site", "Synthetic North"), ("Site", "Foreign South")), suffix)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state['source'] = render_source_details(st.session_state['source'], st.session_state['profile'], 'source-label', field)
''')
    app.session_state["source"], app.session_state["profile"] = content.source, PROFILE
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    assert content.source.facility == "", "Opening review must not falsely establish the first listed site"
    next(w for w in app.button if w.label == "Use these source details").click().run()
    assert not app.exception
    manual = app.session_state["source"]
    assert manual.facility == "north" and manual.scope_review
    assert not site_blockers(report(replace(content, source=manual)))
    app.run()
    assert app.session_state["source"] == manual
    assert manual.page_texts == content.source.page_texts and sources.source_bytes(PROFILE, manual) == raw


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_new_ambiguity_does_not_rewrite_existing_manual_work_or_native_word(portable_ingest, suffix, tmp_path):
    content, raw = portable_ingest((("Site", "Synthetic North"), ("Site", "Foreign South")), suffix)
    corrected = replace(content, source=correct_source_details(content.source, PROFILE, date(2026, 9, 4), "north"))
    draft = report(corrected, manual="Operator verified the target-site pump only.")
    current = structured.native_update((content,), "activity_summary", draft.blocks[0])
    assert current == draft.blocks[0]
    path = template(tmp_path)
    before = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(draft, path, section_key="activity")))
    text = "\n".join(p.text for p in output.paragraphs)
    assert draft.blocks[0].text in text and "P-1" not in text
    assert path.read_bytes() == before and sources.source_bytes(PROFILE, corrected.source) == raw


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
@pytest.mark.parametrize("conflicting", [True, False])
def test_public_storage_legacy_original_cache_clears_only_conflicts_without_rewrite(suffix, conflicting, monkeypatch, tmp_path):
    """Real cache guards/readers stay enabled; requires Linux fcntl."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    labels = (("Site", "Synthetic North"), ("Facility", "Foreign South" if conflicting else "North Campus"))
    raw = source_bytes(labels, suffix)
    content, _ = sources.ingest(PROFILE, "synthetic-maintenance report" + suffix, raw)
    cache = sources._path(PROFILE, content.source.sha256, ".json")
    record = library._read(cache)
    record["source"]["facility"] = "Synthetic North"  # Valid prior first-label extraction.
    cache.write_bytes(library._json(record))
    cache_bytes = cache.read_bytes()
    original = sources._path(PROFILE, content.source.sha256, suffix)
    original_stat = original.stat()
    monkeypatch.setattr(sources, "suggest_facts", lambda *a: pytest.fail("A valid original cache must not reparse other metadata"))
    cached, attachments = sources.ingest(PROFILE, "synthetic-maintenance report" + suffix, raw)
    assert not attachments and cached.source.facility == ("" if conflicting else "Synthetic North")
    assert replace(cached.source, facility=content.source.facility) == content.source
    assert cached.tables == content.tables and cached.image_items == content.image_items
    assert cache.read_bytes() == cache_bytes and original.read_bytes() == raw
    assert (original.stat().st_ino, original.stat().st_mtime_ns) == (original_stat.st_ino, original_stat.st_mtime_ns)


def test_public_storage_restore_keeps_old_and_manual_sources_history_and_word(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = source_bytes((("Site", "Synthetic North"), ("Site", "Foreign South")), ".txt")
    content, _ = sources.ingest(PROFILE, "synthetic-maintenance report.txt", raw)
    old_source = replace(content.source, facility="Synthetic North")
    old = replace(report(replace(content, source=old_source), manual="Historical reviewed wording."), period=ReportPeriod(2026, 8))
    historical = library.save_snapshot(old, expected_revision=0, entered_editor="Synthetic Editor")
    reviewed = replace(content.source, vendor="Reviewed vendor", actions="", captions=((1, "Retained caption"),))
    reviewed = correct_source_details(reviewed, PROFILE, date(2026, 9, 4), "north")
    current = report(replace(content, source=reviewed), manual="Current manually verified target work.")
    saved = library.save_snapshot(current, expected_revision=0, entered_editor="Synthetic Editor")
    for original_source in (old_source, reviewed):
        restored, missing = restore_sources(PROFILE, (original_source,))
        assert not missing and restored[0].source == original_source
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    assert reopened == current and library.load_snapshot(PROFILE.contract, PROFILE.key, old.period) == historical
    assert not site_blockers(reopened)
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    output = Document(BytesIO(build_native_docx(reopened, template(tmp_path), section_key="activity")))
    assert current.blocks[0].text in "\n".join(p.text for p in output.paragraphs)
    assert sources.source_bytes(PROFILE, reviewed) == raw


def test_public_storage_guided_upload_requires_source_site_decision(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft
    app, profile = setup_app(monkeypatch, tmp_path)
    raw = source_bytes((("Site", profile.facilities[0].title), ("Site", "Foreign South")), ".txt")
    original = st.file_uploader
    def uploaded(label, *args, **kwargs):
        native = original(label, *args, **kwargs)
        if label != "Add source files":
            return native
        stream = BytesIO(raw)
        stream.name = "synthetic-maintenance report.txt"
        return [stream]
    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception and len(app.get("file_uploader")) >= 1
    current = draft(app)
    assert len(current.sources) == 1 and current.sources[0].facility == ""
    assert next(w for w in app.selectbox if w.label == "Source facility").value == ""
    assert site_blockers(current) and "P-1" in activity(app).text
    with pytest.raises(ValueError, match="Establish the site scope"):
        assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    assert sources.source_bytes(profile, current.sources[0]) == raw
