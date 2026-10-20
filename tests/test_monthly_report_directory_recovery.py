"""Recover only reviewed historical directory data; retain damaged originals."""
from dataclasses import asdict, replace
import hashlib
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_library as library
from app import monthly_report_testing as testing


@pytest.fixture
def damaged(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    site = directory.DirectorySite("synthetic-site", "Synthetic Site")
    healthy = directory.save_directory("Synthetic Healthy Recovery Control", (site,),
        expected_revision=0, actor="Synthetic Editor", confirmed=True)
    prior = directory.save_directory("Synthetic Damaged Recovery", (site,),
        expected_revision=0, actor="Synthetic Editor", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Director", "Synthetic Person", "202-555-0100"),))
    path = directory._path(prior.contract)
    original = (path / "manifest.json").read_bytes()
    broken = b'{"schema":1,"synthetic-damaged":'
    library._atomic_write(path / "manifest.json", broken)
    return healthy, prior, path, original, broken


def test_admin_can_review_and_recover_unreadable_directory(damaged):
    healthy, prior, path, original, broken = damaged
    app = AppTest.from_string('''
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
''', default_timeout=30).run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not app.exception
    inspect = [b for b in app.button if b.label == "Inspect recovery history"]
    assert len(inspect) == 1, "Damaged directory history has no reachable recovery action"
    inspect[0].click().run()
    assert not app.exception
    assert any(prior.contract in t.value for t in app.text)
    checkbox = next(c for c in app.checkbox if c.label == "Recover this reviewed version as a new directory revision")
    checkbox.check().run()
    next(b for b in app.button if b.label == "Recover directory").click().run()
    assert not app.exception
    assert any("Recovered" in s.value for s in app.success)
    assert directory.load_directory(prior.contract).revision == 2
    assert directory.load_directory(healthy.contract) == healthy
    assert (path / "history" / "00000001.json").read_bytes() == original
    assert (path / "recovery" / (hashlib.sha256(broken).hexdigest() + ".bin")).read_bytes() == broken

from contextlib import contextmanager
from app import monthly_report_directory_recovery as recovery
from app import monthly_report_directory_recovery_sample as sample


def files(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


def test_recovery_restores_all_reviewed_fields_and_preserves_files(damaged):
    healthy, prior, path, original, broken = damaged
    prior = replace(prior, archived=True, source_sha256='a'*64, source_sheet='Synthetic Sources',
                    sites=(replace(prior.sites[0], aliases=('Confirmed alias',), active=False),))
    original = library._json({'schema': 1, **asdict(prior)})
    library._atomic_write(path/'history'/'00000001.json', original)
    review = recovery.inspect_recovery(path.name)
    restored = recovery.recover_directory(review, 1, actor='Recovery Reviewer', confirmed=True)
    assert replace(restored, revision=1, actor=prior.actor, updated_at=prior.updated_at, action=prior.action) == prior
    assert restored.revision == 2 and restored.actor == 'Recovery Reviewer'
    assert directory.load_directory(prior.contract) is None  # Archive remains intentional.
    assert directory.load_directory(prior.contract, include_archived=True) == restored
    assert directory.load_directory(healthy.contract) == healthy
    assert (path/'history'/'00000001.json').read_bytes() == original
    assert (path/'recovery'/(review.damaged_sha256+'.bin')).read_bytes() == broken
    after = files(path)
    with pytest.raises(library.RevisionConflict, match='can now be read'):
        recovery.recover_directory(review, 1, actor='Other Reviewer', confirmed=True)
    assert files(path) == after


@pytest.mark.parametrize('mutation', ['head', 'history', 'new-history', 'readable-head'])
def test_changed_review_never_overwrites_current_data(damaged, mutation):
    _, _, path, original, _ = damaged
    review = recovery.inspect_recovery(path.name)
    target = {'head': path/'manifest.json', 'history': path/'history'/'00000001.json',
              'new-history': path/'history'/'00000002.json', 'readable-head': path/'manifest.json'}[mutation]
    library._atomic_write(target, original if mutation == 'readable-head' else b'changed after review')
    before = files(path)
    with pytest.raises(library.LibraryError):
        recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
    assert files(path) == before


def test_change_after_lock_acquisition_is_rechecked(damaged, monkeypatch):
    _, _, path, _, _ = damaged
    review = recovery.inspect_recovery(path.name)
    locked = library._locked
    @contextmanager
    def concurrent_update(lock):
        with locked(lock):
            library._atomic_write(path/'manifest.json', b'damaged by concurrent writer')
            yield
    monkeypatch.setattr(library, '_locked', concurrent_update)
    with pytest.raises(library.RevisionConflict, match='changed after review'):
        recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
    assert (path/'manifest.json').read_bytes() == b'damaged by concurrent writer'
    assert not (path/'recovery').exists()


@pytest.mark.parametrize('where', ['manifest.json', 'history/00000002.json', 'recovery'])
def test_interrupted_recovery_retains_original_and_can_retry(damaged, monkeypatch, where):
    _, _, path, original, broken = damaged
    review = recovery.inspect_recovery(path.name)
    write = library._atomic_write
    def fail(target, raw):
        if (where == 'recovery' and target.parent.name == 'recovery') or str(target.relative_to(path)) == where:
            raise OSError('simulated disk failure')
        return write(target, raw)
    monkeypatch.setattr(library, '_atomic_write', fail)
    with pytest.raises(OSError, match='simulated'):
        recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
    assert (path/'manifest.json').read_bytes() == broken
    assert (path/'history'/'00000001.json').read_bytes() == original
    monkeypatch.setattr(library, '_atomic_write', write)
    revised = recovery.inspect_recovery(path.name)
    restored = recovery.recover_directory(revised, 1, actor='Reviewer', confirmed=True)
    assert restored.revision == (3 if where == 'manifest.json' else 2)
    assert (path/'recovery'/(review.damaged_sha256+'.bin')).read_bytes() == broken


def test_unreadable_later_history_is_retained_and_its_revision_reserved(damaged):
    _, _, path, _, _ = damaged
    library._atomic_write(path/'history'/'00000007.json', b'damaged earlier save')
    review = recovery.inspect_recovery(path.name)
    assert review.unavailable_versions == (7,)
    assert recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True).revision == 8
    assert (path/'history'/'00000007.json').read_bytes() == b'damaged earlier save'


@pytest.mark.parametrize('location', ['manifest.json', 'history/00000002.json'])
def test_foreign_identity_fails_closed(damaged, location):
    healthy, _, path, _, _ = damaged
    raw = library._json({'schema': 1, **asdict(healthy), 'revision': 2})
    library._atomic_write(path/location, raw)
    before = files(path)
    with pytest.raises(library.LibraryError, match='different contract'):
        recovery.inspect_recovery(path.name)
    assert files(path) == before


@pytest.mark.parametrize('invalid', ['role', 'revision', 'ambiguous', 'empty', 'sha'])
def test_unusable_history_cannot_be_restored(damaged, invalid):
    _, prior, path, _, _ = damaged
    state = prior
    if invalid == 'role': state = replace(prior, contract_contacts=(directory.DirectoryContact(''),))
    if invalid == 'revision': state = replace(prior, revision=2)
    if invalid == 'ambiguous': state = replace(prior, sites=(prior.sites[0], replace(prior.sites[0], key='other')))
    if invalid == 'empty': state = replace(prior, sites=(), contract_contacts=())
    if invalid == 'sha': state = replace(prior, source_sha256='invalid')
    library._atomic_write(path/'history'/'00000001.json', library._json({'schema': 1, **asdict(state)}))
    before = files(path)
    with pytest.raises(library.LibraryError, match='No readable, valid'):
        recovery.inspect_recovery(path.name)
    assert files(path) == before


@pytest.mark.parametrize('actor,confirmed,revision', [('', True, 1), ('Reviewer', False, 1), ('x'*161, True, 1),
                                                   ('Reviewer', True, True), ('Reviewer', True, 9)])
def test_confirmation_and_reviewed_selection_required(damaged, actor, confirmed, revision):
    _, _, path, _, _ = damaged
    review = recovery.inspect_recovery(path.name)
    before = files(path)
    with pytest.raises(ValueError):
        recovery.recover_directory(review, revision, actor=actor, confirmed=confirmed)
    assert files(path) == before


def test_bounded_reads_and_history_count(damaged, monkeypatch):
    _, _, path, _, broken = damaged
    monkeypatch.setattr(recovery, 'MAX_RECOVERY_BYTES', len(broken) + 1)
    with pytest.raises(library.LibraryError, match='budget'):
        recovery.inspect_recovery(path.name)
    monkeypatch.setattr(recovery, 'MAX_HISTORY_FILES', 0)
    with pytest.raises(library.LibraryError, match='limit'):
        recovery.inspect_recovery(path.name)


@pytest.mark.parametrize('location', ['manifest.json', 'history/00000001.json', 'history', 'recovery'])
def test_links_are_never_followed(damaged, tmp_path, location):
    _, _, path, _, _ = damaged
    target = path/location
    foreign = tmp_path/'foreign'
    foreign.write_bytes(b'foreign bytes stay private')
    if target.is_file(): target.unlink()
    if target.is_dir():
        target.rename(path/'original-history')
    target.symlink_to(foreign)
    with pytest.raises(library.LibraryError, match='Linked|ordinary'):
        recovery.inspect_recovery(path.name)
    assert foreign.read_bytes() == b'foreign bytes stay private'


def test_cross_namespace_or_reset_review_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with testing.isolated('a'*32):
        receipt = sample.create_sample()
        key = library._contract_directory(receipt['contract'])
        review = recovery.inspect_recovery(key)
        original_files = files(library._root())
        testing.reset(tmp_path)
    # Recreate the exact same bytes at the same paths, but with a new lease.
    with testing.isolated('a'*32):
        root = library._root()
        for name, raw in original_files.items(): library._atomic_write(root/name, raw)
        with pytest.raises(library.RevisionConflict, match='changed after review'):
            recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
        before = files(root)
    with testing.isolated('b'*32):
        root = library._root()
        for name, raw in original_files.items(): library._atomic_write(root/name, raw)
        with pytest.raises(library.RevisionConflict, match='changed after review'):
            recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
        assert files(root) == before


def test_sample_never_changes_existing_data_or_redamages_recovered_record(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    live = directory.save_directory('Live control', (directory.DirectorySite('live', 'Live site'),),
                                    expected_revision=0, actor='Live Editor', confirmed=True)
    live_files = files(library._root())
    with pytest.raises(ValueError, match='isolated'): sample.create_sample()
    with testing.isolated('a'*32):
        old = directory.save_directory('Existing synthetic control', (directory.DirectorySite('old', 'Old site'),),
                                       expected_revision=0, actor='Editor', confirmed=True)
        receipt = sample.create_sample()
        assert sample.create_sample() == receipt
        _, checks = sample.check_sample()
        assert sum(checks.values()) == 2
        review = recovery.inspect_recovery(library._contract_directory(receipt['contract']))
        recovery.recover_directory(review, 1, actor='Reviewer', confirmed=True)
        before = files(library._root())
        assert sample.create_sample() == receipt
        assert all(sample.check_sample()[1].values())
        assert files(library._root()) == before
        assert directory.load_directory(old.contract) == old
    assert files(library._root()) == live_files
    assert directory.load_directory(live.contract) == live


@pytest.mark.parametrize('mode,visible', [('live',False), ('fixtures',False), ('isolated',True)])
def test_sample_controls_only_in_isolated_admin(tmp_path, monkeypatch, mode, visible):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('a'*32)
''', default_timeout=30)
    app.query_params['monthly_admin'] = 'directory'
    if mode != 'live': app.query_params['monthly_qa'] = mode
    app.run()
    assert not app.exception
    assert bool([b for b in app.button if b.label == 'Create damaged-directory sample']) == visible
    assert not [b for b in app.button if b.label == 'Inspect recovery history']  # Attribution gate.


def test_deeply_nested_bad_history_is_contained(damaged):
    _, _, path, _, _ = damaged
    raw = b'[' * 2000 + b'0' + b']' * 2000
    library._atomic_write(path/'history'/'00000002.json', raw)
    review = recovery.inspect_recovery(path.name)
    assert review.unavailable_versions == (2,) and review.next_revision == 3


def test_missing_history_preserves_damaged_head(damaged):
    _, _, path, _, broken = damaged
    (path/'history'/'00000001.json').unlink()
    with pytest.raises(library.LibraryError, match='No saved directory history'):
        recovery.inspect_recovery(path.name)
    assert (path/'manifest.json').read_bytes() == broken


def test_interrupted_sample_is_never_reseeded(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with testing.isolated('a'*32):
        write = library._atomic_write
        def fail(path, raw):
            if path.name == 'manifest.json': raise OSError('simulated interruption')
            return write(path, raw)
        monkeypatch.setattr(library, '_atomic_write', fail)
        with pytest.raises(OSError): sample.create_sample()
        before = files(library._root())
        monkeypatch.setattr(library, '_atomic_write', write)
        with pytest.raises(ValueError, match='interrupted'): sample.create_sample()
        assert files(library._root()) == before
