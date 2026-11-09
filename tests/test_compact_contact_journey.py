"""Hosted harness contracts; AppTest remains distinct from native browser proof."""
from html import unescape
import json
from pathlib import Path
import re

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_about_logo_refresh_journey import app_test_process
from scripts.qa_compact_contact_journey import validate_outputs

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'cd' * 16


def receipt(app):
    raw = next(re.search(r'data-enfra-contact-receipt="([^"]+)"', element.proto.body).group(1)
               for element in app.get('html') if 'data-enfra-contact-receipt=' in element.proto.body)
    return json.loads(unescape(raw))


def test_fixture_requires_marked_isolated_storage(monkeypatch,tmp_path):
    from scripts.workspace_contact_observations import setup
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    with pytest.raises((ValueError,OSError)):
        setup(tmp_path,TOKEN)
    assert not (tmp_path / 'monthly_reports').exists()


@pytest.mark.parametrize('check', ['initial-schema', 'concurrent-directory-refresh'])
def test_contact_fixture_uses_canonical_directory_schema(monkeypatch, tmp_path, check):
    from dataclasses import asdict, replace
    from app import monthly_report_directory as directory
    from app import monthly_report_library as library
    from app import monthly_report_qa_fixture as fixture
    from app import monthly_report_testing as testing
    from scripts.workspace_contact_observations import setup

    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    monkeypatch.setenv('EPC_MONTHLY_CONTACT_TASK', '1')
    (tmp_path / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        setup(tmp_path, TOKEN)
        saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        draft = saved.draft
        contact = next(b for b in draft.blocks if b.key == 'contact_matrix')
        spec = next(b for s in draft.sections for b in s.blocks if b.key == 'contact_matrix')
        if check == 'initial-schema':
            assert spec == directory.CONTACT_SPEC
        previous = directory.load_directory(fixture.CONTRACT)
        north = previous.sites[0]
        changed = replace(north.contacts[0], phone='202-555-0176')
        sites = (replace(north, contacts=(changed, *north.contacts[1:])), *previous.sites[1:])
        directory.save_directory(fixture.CONTRACT, sites, expected_revision=previous.revision,
                                 actor=fixture.ACTOR, confirmed=True)
        # Reproduce a committed shared write arriving before the old working
        # copy has received its acknowledgment, without any browser timing.
        refreshed = directory.refresh_directory_contacts(draft)
        current = next(b for b in refreshed.blocks if b.key == 'contact_matrix')
        assert current.rows != contact.rows
        assert current.rows[0][3] == '202-555-0176'
        def unrelated(value):
            return replace(value, blocks=tuple(b for b in value.blocks
                           if b.key not in {'contact_matrix', 'subcontractor_matrix'}))
        assert asdict(unrelated(refreshed)) == asdict(unrelated(draft))
        assert unrelated(refreshed).fingerprint == unrelated(draft).fingerprint
        assert next(b for b in refreshed.blocks if b.key == 'subcontractor_matrix') == next(
            b for b in draft.blocks if b.key == 'subcontractor_matrix')
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD) == saved
    assert not (tmp_path / 'monthly_reports').exists()


def test_guided_contact_fixture_receipts_and_real_native_outputs(monkeypatch,tmp_path,app_test_process):
    if not app_test_process:
        return
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE','1')
    monkeypatch.setenv('EPC_MONTHLY_DOM_APPTEST','1')
    monkeypatch.setenv('EPC_MONTHLY_CONTACT_TASK','1')
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    from app import monthly_report_section_preview_ui as preview
    monkeypatch.setattr(preview,'render_section_preview',lambda *args,**kwargs: None)
    app = AppTest.from_file(str(ROOT/'tests/fixtures/workspaces/monthly_app.py'),default_timeout=45)
    app.session_state['_monthly_dom_app_test_token'] = TOKEN
    app.run()
    assert not app.exception
    next(b for b in app.button if b.label=='Create synthetic compact contact report').click().run()
    assert not app.exception
    baseline = receipt(app)
    assert baseline['working'] == baseline['durable']
    unrelated_payload = baseline['working']['unrelated_payload']
    assert unrelated_payload['synthetic'] is True
    assert not {'contact_matrix', 'subcontractor_matrix'} & {b['key'] for b in unrelated_payload['blocks']}
    assert baseline['working']['contacts']['source'] == 'Library'
    assert len(baseline['working']['vendors']['extra_tables'][0]['rows']) == 3
    app.run()
    assert receipt(app)['working'] == baseline['working']
    next(b for b in app.button if b.label=='Edit contacts').click().run()
    next(b for b in app.button if b.label=='Add contact').click().run()
    for label,value in [('Facility','Demo North'),('Role','Engineer'),('Name','Synthetic Added North'),('Phone','202-555-0174')]:
        next(w for w in app.text_input if w.label==label).set_value(value).run()
        assert not app.exception
    state = receipt(app)
    assert state['working'] == state['durable']
    assert state['directory']['sites'][0]['contacts'][-1]['phone'] == '202-555-0174'
    assert state['working']['vendors'] == baseline['working']['vendors']
    assert state['working']['unrelated_payload'] == unrelated_payload
    assert state['saved_unchanged'] and state['original_unchanged']
    next(b for b in app.button if b.label=='Close editing').click().run()
    next(b for b in app.button if b.label=='Fail next synthetic shared save before commit').click().run()
    next(b for b in app.button if b.label=='Edit contact').click().run()
    next(w for w in app.text_input if w.label=='Phone').set_value('202-555-0175')
    next(b for b in app.button if b.label=='Remove contact').click().run()
    failed = receipt(app)
    assert len(failed['attempts']) == len(state['attempts']) + 1
    assert failed['directory']['revision'] == state['directory']['revision']
    next(b for b in app.button if b.label=='Retry shared contact correction').click().run()
    final = receipt(app)
    assert final['directory']['revision'] == state['directory']['revision'] + 1
    assert len(final['attempts']) == len(state['attempts']) + 2
    assert final['working']['contacts']['source'] == 'Library'
    # The after-commit fault is a separate native control, not a retry replay.
    next(b for b in app.button if b.label=='Fail next synthetic shared save after commit').click().run()
    next(b for b in app.button if b.label=='Edit contact').click().run()
    next(w for w in app.text_input if w.label=='Phone').set_value('202-555-0176')
    next(b for b in app.button if b.label=='Remove contact').click().run()
    after_commit = receipt(app)
    assert not app.exception
    assert after_commit['working'] == after_commit['durable']
    assert after_commit['attempts'] == [*final['attempts'], {'mode': 'after'}]
    assert after_commit['fault'] == {'mode': '', 'armed': 2, 'consumed': 2}
    assert after_commit['directory']['revision'] == final['directory']['revision'] + 1
    assert after_commit['directory']['sites'][0]['contacts'][0]['phone'] == '202-555-0176'
    assert after_commit['working']['contacts']['rows'][0][3] == '202-555-0176'
    assert len(after_commit['working']['contacts']['rows']) == len(final['working']['contacts']['rows'])
    assert after_commit['working']['contacts']['source'] == 'Library'
    assert after_commit['working']['unrelated_payload'] == unrelated_payload
    assert after_commit['working']['vendors'] == baseline['working']['vendors']
    assert after_commit['saved_unchanged'] and after_commit['original_unchanged']
    next(b for b in app.button if b.label=='Render synthetic native contact outputs').click().run()
    assert not app.exception
    word,pdf = app.session_state['_contact_native_outputs']
    result = validate_outputs(word,pdf,receipt(app)['working']['contacts']['rows'])
    assert result['pdf_pages'] >= 1
    with pytest.raises(AssertionError):
        validate_outputs(word,pdf,[("Wrong site","Wrong role","Wrong name","Wrong phone","")])
    assert not (tmp_path/'monthly_reports').exists()


def test_ci_runs_native_contact_journey_and_retains_first_failure_evidence():
    source = (ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    assert 'python scripts/qa_compact_contact_journey.py' in source
    assert 'test-artifacts/compact-contact-journey/' in source
    script = (ROOT/'scripts/qa_compact_contact_journey.py').read_text()
    assert "record['result'] = 'failed'" in script
    assert 'first-failure.png' in script
    assert 'page.expect_download' in script
    assert 'force=True' not in script
    assert 'dispatchEvent' not in script
    assert 'expected.every((v,i) => row[i]===v)' in script
    assert 'expected_contact[index] = value' in script
    assert "current['node'] == native['node']" in script
    assert 'trusted:e.isTrusted' in script
    assert "event['trusted'] is True" in script
    assert "record['pre_reload_native_events'] = native_events" in script


def test_fault_seam_revalidates_namespace_before_any_attempt(monkeypatch, tmp_path):
    from app import monthly_report_testing as testing, monthly_report_library as library
    from app import monthly_report_directory as directory
    from scripts.workspace_contact_observations import install_fault_seam, _folder
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    monkeypatch.setenv('EPC_MONTHLY_CONTACT_TASK', '1')
    marker = tmp_path / 'monthly-dom-synthetic-only.marker'
    marker.write_text('synthetic-monthly-dom-v1')
    calls = []
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', lambda *a, **kw: calls.append(a))
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        folder = _folder(tmp_path, TOKEN)
        folder.mkdir(parents=True)
        (folder / 'setup.json').write_text('{}')
        (folder / 'attempts.json').write_text('[]')
        install_fault_seam(tmp_path, TOKEN)
    with pytest.raises(AssertionError):
        directory.automatically_keep_directory_contact_edits(None, None)
    with testing.isolated('ef' * 16):
        testing.data_dir(tmp_path)
        with pytest.raises(AssertionError):
            directory.automatically_keep_directory_contact_edits(None, None)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        marker.write_text('not-a-synthetic-marker')
        with pytest.raises(ValueError):
            directory.automatically_keep_directory_contact_edits(None, None)
    assert calls == []
    assert (folder / 'attempts.json').read_text() == '[]'
    assert not (tmp_path / 'monthly_reports').exists()


def test_output_check_reads_a_phone_the_pdf_wrapped_after_its_hyphen():
    """A narrow PDF cell may break 202-555-0199 after a hyphen (seen on CI)."""
    from io import BytesIO
    from docx import Document
    import pymupdf
    rows = [("Demo North", "Engineer", "Synthetic Person North", "202-555-0199", "")]
    document = Document()
    table = document.add_table(rows=2, cols=5)
    for cell, value in zip(table.rows[0].cells, ("Facility", "Role", "Name", "Phone", "Email")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, rows[0]):
        cell.text = value
    word = BytesIO()
    document.save(word)
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Demo North Engineer Synthetic Person North 202-555-")
        page.insert_text((72, 88), "0199")
        wrapped = pdf.tobytes()
    validate_outputs(word.getvalue(), wrapped, rows)
    with pytest.raises(AssertionError):
        validate_outputs(word.getvalue(), wrapped, [(*rows[0][:3], "202-555-0198", "")])


class FakeContactSocket:
    def __init__(self, url='ws://127.0.0.1:8520/_stcore/stream'):
        self.url = url
        self.sent = []
        self.closed = None
        self.server = None

    def connect_to_server(self):
        self.server = FakeContactSocket()
        return self.server

    def on_message(self, callback):
        self.receive = callback

    def send(self, raw):
        self.sent.append(raw)

    def close(self, **kwargs):
        self.closed = kwargs


@pytest.mark.parametrize('url', ['ws://example.com:8520/', 'ws://127.0.0.1:8521/',
                                 'wss://127.0.0.1:8520/', 'ws://user@127.0.0.1:8520/'])
def test_contact_gate_rejects_nonfixture_destinations(url):
    from scripts.qa_compact_contact_journey import ContactDeliveryGate
    rejected = []
    socket = FakeContactSocket(url)
    ContactDeliveryGate(rejected).route(socket)
    assert rejected == [url] and socket.server is None
    assert socket.closed['code'] == 1008


def test_contact_gate_preserves_frames_and_outgoing_messages():
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from scripts.qa_compact_contact_journey import ContactDeliveryGate
    gate, socket = ContactDeliveryGate([]), FakeContactSocket()
    gate.route(socket)
    socket.server.receive(b'initial')
    assert socket.sent == [b'initial']
    gate.hold()
    fragment = ForwardMsg(script_finished=ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY).SerializeToString()
    socket.server.receive(fragment)
    assert not gate.finished
    finished = ForwardMsg(script_finished=ForwardMsg.FINISHED_SUCCESSFULLY).SerializeToString()
    for raw in (b'first', finished, b'last'):
        socket.server.receive(raw)
    socket.receive(b'native-widget-message')
    assert socket.server.sent == [b'native-widget-message']
    assert gate.finished and socket.sent == [b'initial']
    assert gate.release() == 4
    assert socket.sent == [b'initial', fragment, b'first', finished, b'last']
    assert gate.frames == [] and not gate.holding


def test_contact_gate_buffer_is_bounded():
    from scripts.qa_compact_contact_journey import ContactDeliveryGate
    gate, socket = ContactDeliveryGate([]), FakeContactSocket()
    gate.route(socket)
    gate.hold()
    gate.buffered_bytes = 32 * 1024 * 1024
    with pytest.raises(AssertionError):
        socket.server.receive(b'x')


def held_press_evidence():
    import copy
    before = {'node':7,'connected':True,'visible':True,'disabled':False,
              'rect':{'x':10,'y':20,'width':100,'height':30}}
    return {'before':before,'after':copy.deepcopy(before),'release_hit_owned':True,
            'events':[{'type':kind,'trusted':True,'node':7,'label':'Edit contact'}
                      for kind in ('pointerdown','pointerup','click')]}


def test_contact_held_press_accepts_only_stable_native_delivery():
    from scripts.qa_compact_contact_journey import validate_held_contact_press
    validate_held_contact_press(held_press_evidence())


@pytest.mark.parametrize('mutation', ['remount','move','disabled','disconnected','hidden',
                                     'wrong-hit','untrusted','missing-up','missing-click'])
def test_contact_held_press_rejects_lost_or_moved_activation(mutation):
    from scripts.qa_compact_contact_journey import validate_held_contact_press
    value = held_press_evidence()
    if mutation == 'remount': value['after']['node'] = 8
    elif mutation == 'move': value['after']['rect']['y'] += 3
    elif mutation == 'disabled': value['after']['disabled'] = True
    elif mutation == 'disconnected': value['after']['connected'] = False
    elif mutation == 'hidden': value['after']['visible'] = False
    elif mutation == 'wrong-hit': value['release_hit_owned'] = False
    elif mutation == 'untrusted': value['events'][-1]['trusted'] = False
    elif mutation == 'missing-up': value['events'].pop(1)
    else: value['events'].pop()
    with pytest.raises(AssertionError):
        validate_held_contact_press(value)


def test_contact_runner_retains_ordinary_and_additional_held_case(monkeypatch):
    from scripts import qa_compact_contact_journey as qa
    calls = []
    def task(browser, name, *, held_recovery):
        calls.append((name, held_recovery))
        if not held_recovery:
            raise AssertionError('preserved first failure')
    monkeypatch.setattr(qa, 'browser_task', task)
    with pytest.raises(AssertionError, match='preserved first failure'):
        qa.browser_cases(None, 'webkit')
    assert calls == [('webkit', False), ('webkit-held-recovery', True)]


def test_failed_capture_retains_synthetic_payload_before_strict_assertions():
    script = (ROOT/'scripts/qa_compact_contact_journey.py').read_text()
    capture = script.split('    def capture(', 1)[1].split('    def outputs(', 1)[0]
    saved = "record['failed_capture'] = {'stage': stage, 'receipt': state}"
    check = "assert state['working']['unrelated'] == baseline['working']['unrelated']"
    assert capture.index(saved) < capture.index(check)
    assert capture.index(check) < capture.index("record.pop('failed_capture', None)")
    fixture = (ROOT/'scripts/workspace_contact_observations.py').read_text()
    snapshot = fixture.split('def snapshot(', 1)[1].split('def render(', 1)[0]
    assert snapshot.index('_folder(base, token)') < snapshot.index("'unrelated_payload': asdict(unrelated)")


def test_native_phone_entry_accepts_ready_first_focus_and_exact_replacement():
    from scripts.qa_compact_contact_journey import validate_native_phone_entry
    events = [dict(type=kind, node=7, trusted=True, connected=True, value=value)
              for kind, value in [('focusin', 'old'), ('beforeinput', 'old'), ('input', 'new')]]
    validate_native_phone_entry(events, 'old', 'new')


@pytest.mark.parametrize('failure', ['empty-focus', 'concatenation', 'remount', 'untrusted', 'disconnected'])
def test_native_phone_entry_rejects_hydration_or_delivery_corruption(failure):
    from scripts.qa_compact_contact_journey import validate_native_phone_entry
    events = [dict(type=kind, node=7, trusted=True, connected=True, value=value)
              for kind, value in [('focusin', 'old'), ('beforeinput', 'old'), ('input', 'new')]]
    if failure == 'empty-focus': events[0]['value'] = ''
    elif failure == 'concatenation': events[-1]['value'] = 'oldnew'
    elif failure == 'remount': events[-1]['node'] = 8
    elif failure == 'untrusted': events[-1]['trusted'] = False
    else: events[-1]['connected'] = False
    with pytest.raises(AssertionError):
        validate_native_phone_entry(events, 'old', 'new')
