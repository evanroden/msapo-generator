"""A18 synthetic AUTH01/02/03: reviewed upload -> shared reload -> real native exports.

This suite runs the ordinary Starting Report AppTest route with generated DOCX
bytes, not a prefilled report or a fake inspector. It is NOT served-browser,
authentic customer, physical-device, or native Microsoft Word acceptance.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from app import monthly_report_library as library
from app.monthly_report_docx import generate_report
from app.monthly_report_model import OrgChartNode, ReportPeriod, ResolvedBlock, synthetic_profiles
from tests.conftest import requires_libreoffice
from tests.test_monthly_report_start_import import report_file, save_start, start_app


PERIOD = ReportPeriod(2026, 9)
SCENARIOS = (
    # Prior-month, same site: standing contact schema may survive, August work
    # must never be presented as September completion.
    ("AUTH01", "August 2026", False,
     "August 2026 completed synthetic pump overhaul.", False),
    # Same-contract, different site: only the schema may cross the boundary.
    ("AUTH02", "September 2026", True,
     "September 2026 South-only synthetic inspection completed.", False),
    # Correct month, intentionally unfinished: pending work is not completion.
    ("AUTH03", "September 2026", False,
     "September 2026 synthetic inspection observed; bearing replacement remains pending.", True),
)


def _activity(draft):
    return next((b for b in draft.blocks if b.key == "activity_summary"), None)


def _edited(draft, value):
    block = _activity(draft) or ResolvedBlock("activity_summary", "This month")
    return replace(draft, blocks=tuple(
        b for b in draft.blocks if b.key != "activity_summary"
    ) + (replace(block, text=value),))


def _reviewed_export_ready(draft):
    """An operator must complete the required sections; never bypass preflight."""
    from app.monthly_report_checks import preflight

    required = {
        "org_chart": "Synthetic QA reviewed organization context for this invented facility.",
        "equipment_issues": "Synthetic QA reviewed equipment issue context for this invented facility.",
        "training_summary": "Synthetic QA reviewed training evidence for this invented facility.",
    }
    # This is the observed failure-before (required-block gate), deliberately
    # retained. Importing a source alone never authorizes a finished export.
    outstanding = {check.block_key for check in preflight(draft) if check.code == "required"}
    assert set(required).issubset(outstanding)
    updated = list(draft.blocks)
    for key, text in required.items():
        existing = next((i for i, item in enumerate(updated) if item.key == key), None)
        if existing is None:
            updated.append(ResolvedBlock(key, "This month", text=text))
        else:
            updated[existing] = replace(updated[existing], text=text)
    org_index = next((i for i, item in enumerate(updated) if item.key == "org_chart"), None)
    if org_index is not None:
        updated[org_index] = replace(updated[org_index], org_nodes=(OrgChartNode("lead", "Synthetic Lead", "Lead"),))
    ready = replace(draft, blocks=tuple(updated))
    assert not [c for c in preflight(ready) if c.blocking], (
        "Synthetic reviewer fixture must resolve the actual preflight, not waive it.")
    return ready


def _native_words(raw):
    document = Document(BytesIO(raw))
    values = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            values.extend(cell.text for cell in row.cells)
    return " ".join(" ".join(values).split())


@pytest.mark.parametrize("scenario,source_month,foreign_site,source_fact,should_import", SCENARIOS)
def test_synthetic_auth_starting_upload_scope_and_durable_clear_reentry(
        monkeypatch, tmp_path, scenario, source_month, foreign_site,
        source_fact, should_import):
    profile = synthetic_profiles()[0]
    north, south = synthetic_profiles()[1].facilities
    source_title = south.title if foreign_site else north.title
    path = report_file(tmp_path, title=source_title, month=source_month,
                       activity=(source_fact,), contact=True)
    immutable = path.read_bytes()
    digest = sha256(immutable).hexdigest()

    # Real Start importer/inspector/persistence code, but an AppTest-injected
    # uploaded BytesIO and disposable data root, NOT a served UI upload.
    app = start_app(monkeypatch, tmp_path, path,
                    known_sites=(north, south) if foreign_site else None)
    imported = save_start(app)
    assert imported.period == PERIOD
    assert imported.profile.contract == profile.contract
    assert imported.profile.key == profile.key
    assert imported.profile.facilities == (north,)
    assert sha256(library.imported_original(profile.contract, profile.key).read_bytes()).hexdigest() == digest
    assert sha256(path.read_bytes()).hexdigest() == digest
    initial = _activity(imported)
    assert (source_fact in (initial.text if initial else "")) == should_import
    assert (source_fact in " ".join(str(b) for b in imported.blocks)) == should_import
    if foreign_site:
        assert not any(south.title in str(b) for b in imported.blocks)
        assert all(not (b.text or b.rows or b.asset_hashes
                        or any(table.rows for table in b.extra_tables))
                   for b in imported.blocks)

    first = library.save_snapshot(imported, expected_revision=0, entered_editor="Synthetic QA reviewer")
    assert first.revision == 1
    # A deliberate clear may never be undone by unmodified source replay or
    # by reading saved history in another session.
    cleared = _edited(first.draft, "")
    second = library.save_snapshot(cleared, expected_revision=1,
                                   entered_editor="Synthetic QA reviewer")
    assert second.revision == 2
    reloaded_clear = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert reloaded_clear.revision == 2
    assert _activity(reloaded_clear.draft).text == ""
    assert library.load_snapshot_version(profile.contract, profile.key, PERIOD, 1).draft == first.draft

    reviewer_fact = f"A18{scenario}REENTERED: synthetic reviewer-confirmed September outcome."
    revised = _edited(reloaded_clear.draft, reviewer_fact)
    third = library.save_snapshot(revised, expected_revision=2,
                                  entered_editor="Synthetic QA reviewer")
    assert third.revision == 3
    reloaded = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert reloaded.draft == third.draft
    assert reloaded.draft.profile == imported.profile
    assert _activity(reloaded.draft).text == reviewer_fact
    assert source_fact not in _activity(reloaded.draft).text
    assert library.imported_original(profile.contract, profile.key).read_bytes() == immutable
    assert sha256(path.read_bytes()).hexdigest() == digest
    assert len(library.snapshot_history(profile.contract, profile.key, PERIOD)[0]) == 3


@requires_libreoffice
@pytest.mark.parametrize("scenario,source_month,foreign_site,source_fact,should_import", SCENARIOS)
def test_synthetic_auth_real_word_pdf_from_persisted_reviewed_start(
        monkeypatch, tmp_path, scenario, source_month, foreign_site,
        source_fact, should_import):
    profile = synthetic_profiles()[0]
    north, south = synthetic_profiles()[1].facilities
    # The imported synthetic DOCX is also this report's native page design.
    # Unlike a generic short Starting sample, its layout must have every
    # required edited section before the real native renderer can place it.
    path = report_file(tmp_path, title=south.title if foreign_site else north.title,
                       month=source_month, activity=(source_fact,), contact=True)
    source = Document(path)
    for title in ("8 Equipment Performance Issues", "11 Training Summary"):
        source.add_heading(title, level=1)
    for paragraph in source.paragraphs:
        if paragraph.style.name == "Heading 1":
            paragraph.paragraph_format.page_break_before = True
    source.save(path)
    from app.monthly_report_import import inspect_docx
    assert {"organization", "activity", "issues", "training"} <= {
        item.section for item in inspect_docx(path).items
        if item.part == "word/document.xml"
    }
    original = path.read_bytes()
    imported = save_start(start_app(monkeypatch, tmp_path, path,
                                    known_sites=(north, south) if foreign_site else None))
    # Report state is saved and loaded before the actual renderer is invoked.
    # The reviewer supplies a current-period fact, never retitles old or
    # foreign-site source work as completed.
    reviewer_fact = f"A18{scenario}REVIEWED synthetic September report fact."
    revised = _reviewed_export_ready(_edited(imported, reviewer_fact))
    library.save_snapshot(revised, expected_revision=0,
                          entered_editor="Synthetic QA reviewer")
    reopened = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert reopened and reopened.draft == revised
    package = generate_report(reopened.draft,
                              acknowledged_fingerprint=reopened.draft.fingerprint)
    assert package.docx.startswith(b"PK") and package.pdf.startswith(b"%PDF-"), package.pdf_error
    word = _native_words(package.docx)
    with pymupdf.open(stream=package.pdf, filetype="pdf") as pdf:
        assert len(pdf) >= 4
        pdf_text = " ".join(" ".join(page.get_text() for page in pdf).split())
    for exported in (word, pdf_text):
        assert reviewer_fact in exported
        assert source_fact not in exported
        assert south.title not in exported
        assert "12,345.67" not in exported
    assert library.imported_original(profile.contract, profile.key).read_bytes() == original
    assert sha256(path.read_bytes()).digest() == sha256(original).digest()
