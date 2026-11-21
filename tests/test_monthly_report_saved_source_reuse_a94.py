"""A94: saved-source reuse uses only same-owner immutable originals.

These fixtures are invented. They do not establish served/native-browser or
AUTH01/02/03 acceptance, and do not invoke paid extraction.
"""
from dataclasses import replace
from hashlib import sha256

import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_source_recovery as recovery
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, default_sections, synthetic_profiles,
)
from app.monthly_report_saved_source_reuse import (
    SavedSourceChoice, reuse_saved_source, saved_source_choices,
)
from app.monthly_report_source_details import detail_problems


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def saved_draft(profile, period, records):
    return ReportDraft(profile, period, "Synthetic Editor", default_sections(), (),
                       synthetic=True, sources=tuple(records))


def save(profile, period, records, *, revision=0):
    return library.save_snapshot(saved_draft(profile, period, records),
                                 expected_revision=revision,
                                 entered_editor="Synthetic Editor")


def make_source(profile, name, raw, *, date="2026-09-15", facility=None):
    content, _ = sources.ingest(profile, name, raw)
    original = replace(
        content.source, classification="Vendor service", service_date=date,
        facility=profile.facilities[0].key if facility is None else facility,
        selected_pages=(1,), captions=((1, "Operator-reviewed synthetic caption"),),
    )
    return replace(original, client_page_reviews=((1, page_fingerprint(original, 1)),))


def test_catalog_reuse_preserves_exact_hash_page_reviews_and_report_reload(profile):
    first = make_source(profile, "same-name.txt", b"Synthetic inspected first AHU.")
    second = make_source(profile, "same-name.txt", b"Synthetic inspected different AHU.")
    assert first.sha256 != second.sha256
    month = ReportPeriod(2026, 9)
    save(profile, month, (first, second))
    choices = saved_source_choices(profile)
    assert len(choices) == 2
    assert all("same-name.txt" in item.label for item in choices)
    assert all(profile.contract in item.label and month.label in item.label
               and profile.facilities[0].title in item.label for item in choices)
    assert len(set(item.source.sha256 for item in choices)) == 2
    reused = reuse_saved_source(profile, choices[0])
    assert reused.source == choices[0].source
    assert reused.source.sha256 == sha256(sources.source_bytes(profile, reused.source)).hexdigest()
    assert reused.source.captions == choices[0].source.captions
    assert reused.source.client_page_reviews == choices[0].source.client_page_reviews

    # It is the same original, not a second copy or a new source identity.
    source_dir = library._profile_path(profile.contract, profile.key) / "sources"
    originals_before = sorted(p.name for p in source_dir.glob("*.txt"))
    saved_next = save(profile, ReportPeriod(2026, 10), (reused.source,))
    reopened = library.load_snapshot(profile.contract, profile.key, ReportPeriod(2026, 10))
    restored, missing = recovery.restore_sources(profile, reopened.draft.sources)
    assert reopened == saved_next and missing == ()
    assert restored[0].source == reused.source
    assert sorted(p.name for p in source_dir.glob("*.txt")) == originals_before
    assert len(saved_source_choices(profile)) == 2, "Newer saved duplicate hash appears only once"
    assert len(saved_source_choices(profile, exclude_ids=(first.id, second.id))) == 0


def test_wrong_site_and_other_report_profile_are_not_offered_or_reused(profile):
    period = ReportPeriod(2026, 9)
    foreign = make_source(profile, "wrong-site.txt", b"Synthetic different-site entry.",
                          facility="Not a site in this report")
    save(profile, period, (foreign,))
    assert saved_source_choices(profile) == ()
    forged = SavedSourceChoice(period, foreign, "forged")
    with pytest.raises(ValueError, match="site review"):
        reuse_saved_source(profile, forged)

    other = replace(profile, key="unrelated-synthetic-site",
                    facilities=(Facility("different-facility", "Different Facility"),),
                    title="Different source owner")
    other_source = make_source(other, "other-owner.txt", b"Other profile source.")
    save(other, period, (other_source,))
    assert saved_source_choices(profile) == (), "A shared contract is not cross-site permission"


def test_prior_month_carries_exact_identity_but_needs_source_date_correction(profile):
    prior = ReportPeriod(2026, 8)
    target = ReportPeriod(2026, 9)
    source = make_source(profile, "older.txt", b"Prior month synthetic service.",
                         date="2026-08-15")
    save(profile, prior, (source,))
    choices = saved_source_choices(profile)
    assert len(choices) == 1 and prior.label in choices[0].label
    reused = reuse_saved_source(profile, choices[0])
    draft = saved_draft(profile, target, (reused.source,))
    assert "date outside this report month" in detail_problems(
        reused.source, profile, target, in_report=True, draft=draft)
    assert reused.source.service_date == "2026-08-15", "Never silently relabel old evidence"


def test_missing_original_or_changed_snapshot_cannot_reuse_stale_selection(profile):
    period = ReportPeriod(2026, 9)
    original = make_source(profile, "source.txt", b"Synthetic retained original.")
    save(profile, period, (original,))
    choice = saved_source_choices(profile)[0]
    path = sources._path(profile, original.sha256, original.suffix)
    raw = path.read_bytes()
    path.unlink()
    with pytest.raises(ValueError, match="unavailable"):
        reuse_saved_source(profile, choice)
    assert library.load_snapshot(profile.contract, profile.key, period).draft.sources == (original,)
    path.write_bytes(raw)
    revised = replace(original, findings="A later reviewed finding")
    save(profile, period, (revised,), revision=1)
    with pytest.raises(ValueError, match="changed"):
        reuse_saved_source(profile, choice)
    assert reuse_saved_source(profile, saved_source_choices(profile)[0]).source == revised


def test_malformed_saved_catalog_fails_closed_without_changing_original(profile):
    period = ReportPeriod(2026, 9)
    source = make_source(profile, "preserved.txt", b"Synthetic preserved original.")
    save(profile, period, (source,))
    original = sources.source_bytes(profile, source)
    path = library._profile_path(profile.contract, profile.key, snapshots=True) / "2026-09.json"
    path.write_text("{not JSON")
    with pytest.raises(library.LibraryError, match="could not be read"):
        saved_source_choices(profile)
    assert sources.source_bytes(profile, source) == original


def test_catalog_does_not_read_original_or_ai_and_reuse_reads_only_on_click(profile, monkeypatch):
    period = ReportPeriod(2026, 9)
    source = make_source(profile, "inspect.txt", b"Synthetic inspected rooftop unit.")
    save(profile, period, (source,))
    with monkeypatch.context() as guard:
        guard.setattr(recovery, "source_bytes", lambda *_, **__: pytest.fail("Catalog read source bytes"))
        guard.setattr(recovery, "ingest", lambda *_, **__: pytest.fail("Catalog re-ingested"))
        guard.setattr(sources, "source_bytes", lambda *_, **__: pytest.fail("Catalog opened original"))
        catalog = saved_source_choices(profile)
        assert len(catalog) == 1
        assert saved_source_choices(profile) == catalog
    counts = {"source_reads": 0, "native_ingests": 0}
    read = recovery.source_bytes
    ingest = recovery.ingest

    def spy_read(*args, **kwargs):
        counts["source_reads"] += 1
        return read(*args, **kwargs)

    def spy_ingest(*args, **kwargs):
        counts["native_ingests"] += 1
        return ingest(*args, **kwargs)

    monkeypatch.setattr(recovery, "source_bytes", spy_read)
    monkeypatch.setattr(recovery, "ingest", spy_ingest)
    content = reuse_saved_source(profile, catalog[0])
    assert content.source == source
    assert counts == {"source_reads": 1, "native_ingests": 1}
    saved_source_choices(profile)
    assert counts == {"source_reads": 1, "native_ingests": 1}


def test_native_guided_add_area_exposes_direct_reuse_without_second_review_path(
    profile, monkeypatch, tmp_path,
):
    from test_monthly_report_ui import monthly
    from test_monthly_report_upload_ui import current_draft
    from app.contracts import RRH_CONTRACT

    app = monthly(monkeypatch, tmp_path)
    actual = library.list_profiles(RRH_CONTRACT)[0]
    source = make_source(actual, "saved-direct.txt", b"Synthetic completed service 2026-08-15.",
                         date="2026-08-15")
    save(actual, ReportPeriod(2026, 8), (source,))
    app.run()
    assert not app.exception
    assert sum(item.label == "Add source files" for item in app.get("file_uploader")) == 1
    saved_picker = next(item for item in app.selectbox if item.label == "Saved source")
    assert source.sha256 in saved_picker.value
    assert any("Already uploaded" in item.value for item in app.markdown)
    actions = [item for item in app.button if item.label == "Reuse saved source"]
    assert len(actions) == 1
    actions[0].click().run()
    assert not app.exception
    draft = current_draft(app)
    assert sum(item.sha256 == source.sha256 for item in draft.sources) == 1
    evidence = next(value for key, value in app.session_state.filtered_state.items()
                    if key.endswith("_evidence") and isinstance(value, tuple) and value)
    assert any(content.source == source for content in evidence)
    assert sum(item.label == "Source date" for item in app.date_input) >= 1
    assert sum(item.label == "Reuse saved source" for item in app.button) == 0
    app.run()
    assert not app.exception
    assert sum(item.sha256 == source.sha256 for item in current_draft(app).sources) == 1
