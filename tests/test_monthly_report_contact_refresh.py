"""Refresh proved directory copies, not edits or historical snapshot bytes."""
from dataclasses import replace

import pytest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, default_sections
from app.monthly_report_setup import new_month_draft


@pytest.fixture
def state_and_draft(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    sites = tuple(directory.DirectorySite(key, title, contacts=(
        directory.DirectoryContact('Facilities Director', 'Old ' + key, email=key + '@example.invalid'),))
        for key, title in (('north', 'Synthetic North'), ('south', 'Synthetic South')))
    first = directory.save_directory('Synthetic Contact Contract', sites,
                                     expected_revision=0, actor='Synthetic Editor', confirmed=True)
    profile = ReportProfile(first.contract, 'north-report', 'North report', (Facility('north', 'Synthetic North'),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(), ())
    draft = directory.apply_defaults(draft)
    second = directory.save_directory(first.contract, (
        replace(sites[0], contacts=(directory.DirectoryContact('Facilities Director', 'New north', email='new@example.invalid'),)),
        sites[1]), expected_revision=1, actor='Synthetic Editor', confirmed=True)
    return first, second, draft


def refresh(draft):
    return directory.refresh_directory_contacts(draft)


def test_directory_update_is_reused_in_rolled_forward_working_copy(state_and_draft):
    first, second, draft = state_and_draft
    result = refresh(new_month_draft(draft, ReportPeriod(2026, 10)))
    block = next(b for b in result.blocks if b.key == 'contact_matrix')
    assert block.rows == directory.contact_block(second, draft.profile.facilities)[0].rows
    assert block.source == 'Library'
    assert block.references[0].endswith(':2')
    assert not any(r.startswith('report-period:') for r in block.references)
    assert 'south' not in str(block.rows)


def test_refresh_never_rewrites_historical_snapshot_bytes(state_and_draft):
    first, second, draft = state_and_draft
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    snapshot_files = {p: p.read_bytes() for p in library._root().rglob('*.json')}
    result = refresh(saved.draft)
    assert result != saved.draft
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved
    assert all(p.read_bytes() == value for p, value in snapshot_files.items())
    assert directory.load_directory(first.contract).sites[1] == first.sites[1]


@pytest.mark.parametrize('kind', ['manual', 'omitted', 'unlinked', 'mixed', 'unnamed', 'schema'])
def test_manual_or_unproved_contacts_are_not_replaced(state_and_draft, kind):
    first, second, draft = state_and_draft
    old = next(b for b in draft.blocks if b.key == 'contact_matrix')
    if kind == 'manual':
        old = replace(old, rows=(('Synthetic North', 'Director', 'Unpublished edit', '', ''),))
    elif kind == 'omitted':
        old = replace(old, source='Omit')
    elif kind == 'unlinked':
        old = replace(old, references=())
    elif kind == 'mixed':
        old = replace(old, references=(*old.references, 'docx:unrelated-source'))
    elif kind == 'unnamed':
        draft = replace(draft, prepared_by='')
    elif kind == 'schema':
        draft = replace(draft, sections=tuple(replace(s, blocks=tuple(
            replace(b, columns=tuple(reversed(b.columns))) if b.key == 'contact_matrix' else b
            for b in s.blocks)) for s in draft.sections))
    draft = replace(draft, blocks=tuple(old if b.key == old.key else b for b in draft.blocks))
    assert refresh(draft) == draft


def test_missing_provenance_history_is_not_guessed(state_and_draft):
    first, second, draft = state_and_draft
    path = directory._path(first.contract) / 'history' / '00000001.json'
    path.unlink()
    assert refresh(draft) == draft


def test_retired_site_binding_is_never_reassigned_by_name(state_and_draft):
    first, second, draft = state_and_draft
    directory.save_directory(first.contract, (
        replace(second.sites[0], active=False), second.sites[1]),
        expected_revision=2, actor='Synthetic Editor', confirmed=True)
    assert refresh(draft) == draft


def test_explicit_shared_contact_deletion_removes_stale_person(state_and_draft):
    first, second, draft = state_and_draft
    latest = directory.save_directory(first.contract, (
        replace(second.sites[0], contacts=()), second.sites[1]),
        expected_revision=2, actor='Synthetic Editor', confirmed=True)
    block = next(b for b in refresh(draft).blocks if b.key == 'contact_matrix')
    assert block.rows == ()
    assert block.references[0].endswith(':3')


def test_foreign_contract_directory_reference_cannot_refresh(state_and_draft):
    _, second, draft = state_and_draft
    old = next(b for b in draft.blocks if b.key == 'contact_matrix')
    old = replace(old, references=(f'directory:{library._contract_directory("Foreign Contract")}:1', *old.references[1:]))
    draft = replace(draft, blocks=tuple(old if b.key == old.key else b for b in draft.blocks))
    assert refresh(draft) == draft
