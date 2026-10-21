"""Production-reachable fault sample cannot damage existing workspaces."""
from contextlib import nullcontext
from io import BytesIO

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from app import monthly_report_logo_recovery_sample as sample, monthly_report_testing as testing
from app.monthly_report_ui import shared_fixture_run_token
from test_monthly_report_branding import collection

APP = '''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('a'*32)
'''


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    return tmp_path


@pytest.mark.parametrize('context', [nullcontext, lambda: testing.isolated('a'*32)])
def test_sample_rejects_live_and_ordinary_isolated_context(storage, context):
    with context(), pytest.raises(ValueError, match='separate test area'):
        sample.create_sample()
    assert not list(storage.rglob('sample.json'))


@pytest.mark.parametrize('token', ['', 'a', '../outside', None, 'g'*32])
def test_sample_rejects_invalid_browser_identity(storage, token):
    with pytest.raises(ValueError, match='device identity'), sample.sample_scope(token):
        pass


def test_fault_is_real_and_restore_preserves_all_originals_and_siblings(storage):
    with sample.sample_scope('a'*32):
        receipt = sample.create_sample()
        current = branding.load_branding()
        assert current.revision == 2
        raw = branding._path().joinpath('assets', receipt['damaged_asset']).read_bytes()
        with Image.open(BytesIO(raw)) as image:
            image.verify()  # This is the legacy verifier's actual blind spot.
        with Image.open(BytesIO(raw)) as image, pytest.raises(OSError):
            image.load()
        with pytest.raises(branding.LogoArtworkError):
            branding.read_logo(current.logos[0])
        branding.read_logo(current.logos[1])
        before = files(library._root())
        checks = sample.check_sample()[1]
        assert not checks.pop('Recovered as revision 3')
        assert all(checks.values())
        restored = branding.restore_branding(1, expected_revision=2, actor='Synthetic Reviewer', confirmed=True)
        assert restored.revision == 3
        assert all(sample.check_sample()[1].values())
        after = files(library._root())
        assert all(after[path] == raw for path, raw in before.items() if path != 'branding/manifest.json')
        assert sample.create_sample() == receipt
        assert files(library._root()) == after
        with pytest.raises(library.RevisionConflict):
            branding.restore_branding(1, expected_revision=2, actor='Stale Reviewer', confirmed=True)
        assert files(library._root()) == after


def test_sample_namespace_does_not_change_live_existing_qa_or_shared_fixtures(storage):
    roots = []
    logos, assets = collection()
    for context in (nullcontext(), testing.isolated('a'*32), testing.isolated(shared_fixture_run_token('a'*32))):
        with context:
            branding.save_branding(logos, assets, expected_revision=0, actor='Existing synthetic editor', confirmed=True)
            root = library._root()
            roots.append((root, files(root)))
    with sample.sample_scope('a'*32):
        assert library._root() not in [root for root, _ in roots]
        sample.create_sample()
        branding.restore_branding(1, expected_revision=2, actor='Synthetic Reviewer', confirmed=True)
        assert all(sample.check_sample()[1].values())
    for root, before in roots:
        assert files(root) == before
    with sample.sample_scope('b'*32):
        assert branding.load_branding() is None


def test_existing_collection_in_sample_area_is_never_replaced(storage):
    with sample.sample_scope('a'*32):
        logos, assets = collection()
        branding.save_branding(logos, assets, expected_revision=0, actor='Earlier editor', confirmed=True)
        before = files(branding._path())
        with pytest.raises(ValueError, match='Existing logo records'):
            sample.create_sample()
        assert files(branding._path()) == before
        assert not sample._path().exists()


def test_interrupted_sample_cannot_be_reseeded(storage, monkeypatch):
    with sample.sample_scope('a'*32):
        write = library._atomic_write
        def fail(path, raw):
            if path.name == '00000002.json':
                raise OSError('simulated interruption')
            return write(path, raw)
        monkeypatch.setattr(library, '_atomic_write', fail)
        with pytest.raises(OSError, match='simulated'):
            sample.create_sample()
        before = files(library._root())
        monkeypatch.setattr(library, '_atomic_write', write)
        with pytest.raises(ValueError, match='interrupted'):
            sample.create_sample()
        assert files(library._root()) == before


def test_changed_collection_prevents_fault_injection(storage, monkeypatch):
    with sample.sample_scope('a'*32):
        save = sample.directory.save_directory
        def concurrent(*args, **kwargs):
            result = save(*args, **kwargs)
            current = branding.load_branding()
            branding.save_branding(current.logos, {}, expected_revision=current.revision, actor='Concurrent editor', confirmed=True)
            return result
        monkeypatch.setattr(sample.directory, 'save_directory', concurrent)
        with pytest.raises(library.RevisionConflict, match='changed'):
            sample.create_sample()
        for logo in branding.load_branding().logos:
            branding.read_logo(logo)
        assert branding.load_branding().actor == 'Concurrent editor'


@pytest.mark.parametrize('child', ['qa_logo_recovery', 'branding'])
def test_sample_refuses_linked_storage(storage, child):
    outside = storage / 'outside'
    outside.mkdir()
    with sample.sample_scope('a'*32):
        library._root().mkdir(parents=True, exist_ok=True)
        (library._root() / child).symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match='Linked|outside its isolated storage'):
            sample.create_sample()
    assert not list(outside.iterdir())


def test_reset_invalidates_running_sample_lease(storage):
    with sample.sample_scope('a'*32):
        sample.create_sample()
        testing.reset(storage)
        with pytest.raises(OSError, match='reset'):
            sample.create_sample()


@pytest.mark.parametrize('mode', [None, 'isolated', 'fixtures'])
def test_fault_creation_not_exposed_in_other_admin_modes(storage, mode):
    app = AppTest.from_string(APP, default_timeout=30)
    app.query_params['monthly_admin'] = 'logos'
    if mode:
        app.query_params['monthly_qa'] = mode
    app.run()
    assert not app.exception and not app.error
    assert not [b for b in app.button if b.label == 'Create stored-logo recovery sample']


def test_native_routes_keep_sample_namespace_and_recover_through_existing_controls(storage):
    app = AppTest.from_string(APP, default_timeout=30)
    app.query_params['monthly_qa'] = 'logo-recovery'
    app.run()
    assert not app.exception and not app.error
    app.button('report_logo_sample_create').click().run()
    assert not app.exception and not app.error
    assert any('saved contract logo could not be read' in w.value for w in app.warning)
    next(b for b in app.button if b.label == 'Synthetic healthy logo').click().run()
    assert not app.exception and not app.error
    assert any(c.label == 'Synthetic Logo Site' for c in app.checkbox)
    app.button('report_change_contract_button').click().run()
    next(b for b in app.button if b.label == 'Synthetic recovery logo').click().run()
    assert any(c.label == 'Synthetic Logo Site' for c in app.checkbox)
    assert any('saved contract logo could not be read' in w.value for w in app.warning)
    review_link = next(link for link in app.get('link_button') if link.label == 'Review shared logos')
    assert 'monthly_qa=logo-recovery' in review_link.url
    app.query_params['monthly_admin'] = 'logos'
    app.run()
    assert not app.exception and not app.error
    assert any('This saved logo could not be read' in w.value for w in app.warning)
    app.text_input('report_branding_actor').set_value('Synthetic Reviewer').run()
    app.selectbox('report_branding_history').set_value(1).run()
    next(c for c in app.checkbox if c.label == 'Restore this collection as a new shared version').check().run()
    app.button('report_branding_restore').click().run()
    assert not app.exception and not app.error
    app.button('report_logo_sample_check').click().run()
    assert len(app.success) == 6
    assert not any('not yet verified' in w.value for w in app.warning)
    with sample.sample_scope('a'*32):
        assert all(sample.check_sample()[1].values())
    with testing.isolated('a'*32):
        assert branding.load_branding() is None


def test_mode_switch_drops_old_widget_state_without_changing_old_storage(storage):
    app = AppTest.from_string(APP, default_timeout=30)
    app.query_params.update({'monthly_qa': 'isolated', 'monthly_admin': 'logos'})
    app.run()
    app.text_input('report_branding_actor').set_value('Original workspace editor').run()
    with testing.isolated('a'*32):
        root = library._root()
        before = files(root)
    app.query_params['monthly_qa'] = 'logo-recovery'
    app.run()
    assert not app.exception and not app.error
    assert app.text_input('report_branding_actor').value == ''
    assert files(root) == before
    assert any('ISOLATED LOGO RECOVERY TESTING' in w.value for w in app.warning)


def test_logo_recovery_route_is_explicitly_separate(storage):
    app = AppTest.from_string(APP, default_timeout=30)
    app.query_params.update({'monthly_qa': 'logo-recovery', 'monthly_admin': 'logos'})
    app.run()
    assert not app.exception and not app.error
    assert any('ISOLATED LOGO RECOVERY TESTING' in w.value for w in app.warning), 'Recovery route must not silently fall back to live storage'
    assert app.button('report_logo_sample_create')
