"""Scope proof does not demand repeat page approval or site correction."""
from dataclasses import asdict, replace
from datetime import date

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles
from app.monthly_report_source_details import correct_source_details, detail_problems
from app.monthly_report_source_scope import MULTIPLE_FACILITIES, included_scope_valid
from app.monthly_report_source_status import source_manager_status
from test_monthly_report_sources import pdf_bytes


def test_scope_only_correction_retains_exact_reviewed_page_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[1]
    raw = pdf_bytes(1)
    content, _ = sources.ingest(profile, "synthetic-combined-utility.pdf", raw)
    source = replace(content.source, classification="Utility results", service_date="2026-09-04",
                     facility="", captions=((1, "Reviewed utility page"),))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    content = replace(content, source=source)
    pages, = sources.prepare_pages(profile, (content,), ((source.id, "utility_analysis"),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
        (SectionSpec("scorecards", "3", "Scorecards", (BlockSpec("utility_analysis", "image_page"),)),),
        (pages,), sources=(source,), synthetic=True)
    assert not included_scope_valid(draft, source)
    corrected = correct_source_details(source, profile, date(2026, 9, 4), MULTIPLE_FACILITIES,
                                       chosen_facilities=tuple(site.key for site in profile.facilities))
    assert corrected.fingerprint != source.fingerprint and corrected.facility == source.facility
    accepted = replace(draft, sources=(corrected,))
    status, = source_manager_status(accepted, (replace(content, source=corrected),))
    assert status.resolved and not status.needs_correction and status.pages == 1
    assert accepted.blocks == draft.blocks, "The scope decision must not rewrite page bytes or fabricate a review."
    restored = library.draft_from_dict(asdict(accepted))
    assert source_manager_status(restored, (replace(content, source=restored.sources[0]),)) == (status,)
    word = assemble_docx(accepted, acknowledged_fingerprint=accepted.fingerprint,
                         asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref))
    assert word.startswith(b"PK") and sources.source_bytes(profile, corrected) == raw
    for changes in ({"vendor": "Changed metadata"}, {"captions": ((1, "Changed caption"),)},
                    {"page_texts": ("Changed native page text",)}):
        changed = replace(corrected, **changes)
        value, = source_manager_status(replace(accepted, sources=(changed,)), (replace(content, source=changed),))
        assert not value.resolved and value.needs_correction
    # Even a valid scope cannot turn a raw stale page identity into current
    # provenance, nor let a current marker mask two different page revisions.
    stale = pages.references[0].rsplit(":", 1)[0] + ":unverified-revision"
    for block in (replace(pages, asset_provenance=(), references=(stale,)),
                  replace(pages, references=(*pages.references, stale),
                    asset_provenance=tuple((asset, (*refs, stale)) for asset, refs in pages.asset_provenance))):
        value, = source_manager_status(replace(accepted, blocks=(block,)), (replace(content, source=corrected),))
        assert not value.resolved and value.needs_correction


def test_accepted_row_scoped_totals_do_not_offer_an_unknown_site_correction(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_workorder_upload_ui import _upload
    app = monthly(monkeypatch, tmp_path)
    raw = b"Work Order,Date,Status,Facility\n001,2026-09-04,Completed,north\n"
    _upload(monkeypatch, raw)
    app.run()
    next(button for button in app.button if button.label == "Add totals to summary").click().run()
    assert not app.exception
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith("_draft") and isinstance(value, ReportDraft))
    source, = draft.sources
    assert source.facility == "" and included_scope_valid(draft, source)
    assert not any("site unknown" in expander.label for expander in app.expander)
    assert "site unknown" not in detail_problems(source, draft.profile, draft.period, in_report=True, draft=draft)
    changed = replace(source, page_texts=("Changed extraction",))
    assert "site unknown" in detail_problems(changed, draft.profile, draft.period, in_report=True,
                                             draft=replace(draft, sources=(changed,)))
    other_period = replace(draft, period=ReportPeriod(2026, 10))
    assert "site unknown" in detail_problems(source, draft.profile, other_period.period,
                                             in_report=True, draft=other_period)
