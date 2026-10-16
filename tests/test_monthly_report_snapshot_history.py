"""History inspection reads completed scoped versions and never changes the head."""

from dataclasses import replace
import json

import pytest

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


@pytest.fixture
def draft(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))


def test_immutable_versions_are_scoped_paged_and_inspectable_without_a_write(draft):
    first = library.save_snapshot(draft, expected_revision=0, entered_editor="First editor")
    second = library.save_snapshot(replace(draft, prepared_by="Second preparer"), expected_revision=1,
                                   entered_editor="Second editor")
    other_month = replace(draft, period=ReportPeriod(2026, 10))
    library.save_snapshot(other_month, expected_revision=0, entered_editor="October editor")
    other_profile = replace(draft, profile=replace(draft.profile, key="other-scope"))
    library.save_snapshot(other_profile, expected_revision=0, entered_editor="Other site")
    args = draft.profile.contract, draft.profile.key, draft.period
    latest, older = library.snapshot_history(*args, limit=1)
    assert [(v.revision, v.entered_editor) for v in latest] == [(2, "Second editor")]
    assert older
    earlier, older = library.snapshot_history(*args, before_revision=2, limit=1)
    assert [(v.revision, v.entered_editor) for v in earlier] == [(1, "First editor")]
    assert not older
    assert library.load_snapshot_version(*args, 1) == first
    assert library.load_snapshot(*args) == second
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, other_month.period).draft == other_month


def test_unpublished_history_from_failed_head_publication_is_not_a_saved_version(draft, monkeypatch):
    args = draft.profile.contract, draft.profile.key, draft.period
    saved = library.save_snapshot(draft, expected_revision=0)
    original = library._atomic_write

    def fail_head(path, raw):
        if path.name == draft.period.key + ".json":
            raise OSError("Synthetic head publication failed")
        return original(path, raw)

    monkeypatch.setattr(library, "_atomic_write", fail_head)
    with pytest.raises(OSError):
        library.save_snapshot(replace(draft, prepared_by="Unpublished"), expected_revision=1)
    versions, older = library.snapshot_history(*args)
    assert [v.revision for v in versions] == [1] and not older
    with pytest.raises(library.LibraryError, match="not been published"):
        library.load_snapshot_version(*args, 2)
    assert library.load_snapshot(*args) == saved


@pytest.mark.parametrize("change", ["scope", "month", "revision"])
def test_wrong_history_identity_fails_explicitly_and_preserves_head(draft, change):
    saved = library.save_snapshot(draft, expected_revision=0)
    args = draft.profile.contract, draft.profile.key, draft.period
    path = (library._profile_path(*args[:2], snapshots=True) / "history"
            / f"{draft.period.key}-00000001.json")
    payload = json.loads(path.read_bytes())
    if change == "scope":
        payload["draft"]["profile"]["key"] = "different-site"
    elif change == "month":
        payload["draft"]["period"]["month"] = 10
    else:
        payload["revision"] = 2
    path.write_text(json.dumps(payload))
    with pytest.raises(library.LibraryError, match="does not match"):
        library.snapshot_history(*args)
    assert library.load_snapshot(*args) == saved


def test_missing_current_history_is_not_reported_as_no_saved_versions(draft):
    library.save_snapshot(draft, expected_revision=0)
    args = draft.profile.contract, draft.profile.key, draft.period
    path = (library._profile_path(*args[:2], snapshots=True) / "history"
            / f"{draft.period.key}-00000001.json")
    path.unlink()
    with pytest.raises(library.LibraryError, match="history version is unavailable"):
        library.snapshot_history(*args)


def test_missing_older_published_history_is_explicit_instead_of_an_empty_page(draft):
    for revision in range(3):
        library.save_snapshot(draft, expected_revision=revision)
    args = draft.profile.contract, draft.profile.key, draft.period
    path = (library._profile_path(*args[:2], snapshots=True) / "history"
            / f"{draft.period.key}-00000001.json")
    path.unlink()
    with pytest.raises(library.LibraryError, match="published report history versions are unavailable"):
        library.snapshot_history(*args, before_revision=2)


def test_history_metadata_reads_head_once_and_each_displayed_version_once(draft, monkeypatch):
    for revision in range(4):
        library.save_snapshot(draft, expected_revision=revision)
    calls = []
    original = library._read

    def observed(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(library, "_read", observed)
    versions, older = library.snapshot_history(draft.profile.contract, draft.profile.key, draft.period,
                                              limit=3)
    assert len(calls) == 4 and [v.revision for v in versions] == [4, 3, 2] and older


@pytest.mark.parametrize("revision", [True, 0, -1, "1", "../other"])
def test_version_selector_rejects_invalid_revision_without_path_access(draft, revision):
    with pytest.raises(library.LibraryError, match="Invalid saved report version"):
        library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, revision)
