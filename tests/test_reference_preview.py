"""Original source viewing stays bounded, private and free of reading calls."""
from hashlib import sha256
from types import SimpleNamespace

import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import reference_preview
from app.monthly_report_preview_store import PreviewStore


def pdf_bytes(pages=3):
    with fitz.open() as doc:
        for i in range(pages):
            doc.new_page().insert_text((72,72),f'Synthetic source page {i+1}')
        return doc.tobytes()


def test_pdf_original_bytes_are_preserved_and_two_pages_requested(monkeypatch,tmp_path):
    raw=pdf_bytes(4)
    assert reference_preview.reference_pdf(raw,'receipt.pdf') is raw
    store=PreviewStore()
    monkeypatch.setattr(reference_preview,'STORE',store)
    app=AppTest.from_string('''
import streamlit as st
from app.reference_preview import render_reference
from tests.test_reference_preview import pdf_bytes
raw=st.session_state.setdefault('raw',pdf_bytes(4))
render_reference(key='synthetic_receipt',owner_scope='draft-a',title='Original receipt',raw=raw,filename='receipt.pdf')
''').run()
    assert not app.exception
    assert store.stats()['pdf_entries']==0 # Offscreen creates no source copy/raster.
    # Component visibility is the only request; no reading/generation action.
    entry=next(iter(app.session_state['_workspace_reference_owners'].values()))['entries']['synthetic_receipt']
    entry['view']={'visible':True,'pages':(1,2),'dpi':96}
    app.run()
    assert not app.exception
    assert store.stats()['pdf_entries']==1
    assert store.stats()['raster_entries']==2
    assert entry['ticket'].pages==4
    store.close()


def test_two_reference_owners_cannot_read_each_others_tickets(monkeypatch):
    store=PreviewStore()
    monkeypatch.setattr(reference_preview,'STORE',store)
    states={}
    monkeypatch.setattr(reference_preview.st,'session_state',states)
    first=reference_preview._owner('synthetic-draft-a')
    second=reference_preview._owner('synthetic-draft-b')
    from types import SimpleNamespace
    ticket=store.put(first['owner'],SimpleNamespace(pdf=pdf_bytes()))
    assert not store.available(second['owner'],ticket)
    assert store.pages(second['owner'],ticket,(0,),dpi=96) is None
    store.close()


def test_image_normalization_yields_to_foreground_and_preserves_original(monkeypatch):
    from io import BytesIO
    from contextlib import contextmanager
    from PIL import Image
    from app import monthly_report_render_jobs as jobs
    raw_buffer=BytesIO()
    Image.new('RGB',(30,40),'white').save(raw_buffer,format='PNG')
    raw=raw_buffer.getvalue()
    original=sha256(raw).hexdigest()
    entered=[]
    @contextmanager
    def slot(**kwargs):
        entered.append(kwargs)
        yield
    monkeypatch.setattr(jobs,'work_slot',slot)
    rendered=reference_preview.reference_pdf(raw,'synthetic.png')
    assert entered==[{'preview':True}]
    assert sha256(raw).hexdigest()==original
    with fitz.open(stream=rendered,filetype='pdf') as doc:
        assert len(doc)==1
    @contextmanager
    def busy(**kwargs):
        raise jobs.RenderBusy('synthetic foreground export has priority')
        yield
    monkeypatch.setattr(jobs,'work_slot',busy)
    import pytest
    with pytest.raises(jobs.RenderBusy):
        reference_preview.reference_pdf(raw,'synthetic.png')


def test_same_bytes_after_scope_reset_reject_prior_viewport_generation(monkeypatch):
    import json
    from app.monthly_report_preview_view import viewport
    store=PreviewStore()
    monkeypatch.setattr(reference_preview,'STORE',store)
    app=AppTest.from_string("""
import streamlit as st
from app.reference_preview import render_reference
from tests.test_reference_preview import pdf_bytes
scope=st.selectbox('Synthetic owner generation',('before-reset','after-reset'))
raw=st.session_state.setdefault('raw',pdf_bytes(4))
render_reference(key='same_source',owner_scope=scope,title='Original source',raw=raw,filename='source.pdf')
""").run()
    old=json.loads(app.get('bidi_component')[0].proto.json)['generation']
    app.selectbox[0].set_value('after-reset').run()
    new=json.loads(app.get('bidi_component')[0].proto.json)['generation']
    assert old != new
    assert viewport({'visible':True,'pages':[0],'dpi':96,'generation':old},new) is None
    assert store.stats()['pdf_entries']==0
    store.close()


@pytest.fixture
def retained_reference_callbacks(monkeypatch):
    """Capture fragment closures; keep real bounded storage and viewport checks.

    A fragment retained by Streamlit can run after its originating full render
    has been replaced. Calling that exact old closure, rather than rendering a
    new app, exercises the stale work which a normal AppTest rerun cannot reach.
    """
    store = PreviewStore()
    state, fragments, rendered, work = {}, [], [], []
    monkeypatch.setattr(reference_preview, 'STORE', store)
    monkeypatch.setattr(reference_preview.st, 'session_state', state)

    def fragment(function):
        fragments.append(function)
        return function

    monkeypatch.setattr(reference_preview.st, 'fragment', fragment)
    monkeypatch.setattr(reference_preview, 'render_view', lambda **kwargs: rendered.append(kwargs))
    original_pdf = reference_preview.reference_pdf
    original_pages = store.pages

    def normalized(raw, filename):
        work.append(('normalize', sha256(raw).hexdigest()))
        return original_pdf(raw, filename)

    def pages(*args, **kwargs):
        work.append(('raster', args[1].token if hasattr(args[1], 'token') else args[0]))
        return original_pages(*args, **kwargs)

    monkeypatch.setattr(reference_preview, 'reference_pdf', normalized)
    monkeypatch.setattr(store, 'pages', pages)

    def render(owner_scope, raw):
        reference_preview.render_reference(key='source', owner_scope=owner_scope,
                                           title='Synthetic original', raw=raw, filename='source.pdf')
        owner = reference_preview._owner(owner_scope)
        return SimpleNamespace(owner=owner, entry=owner['entries']['source'],
                               surface=fragments[-1], view=rendered[-1])

    def request(target, *, indexes=(0,), visible=True):
        state['workspace_reference_source'] = {'viewport': {
            'generation': target.view['generation'], 'visible': visible,
            'pages': list(indexes), 'dpi': 96,
        }}
        target.view['on_change']()

    yield SimpleNamespace(store=store, state=state, rendered=rendered, work=work,
                          render=render, request=request)
    store.close()


def test_discarded_scope_rejects_retained_fragment_and_callback_even_after_same_scope_reentry(
    retained_reference_callbacks,
):
    harness = retained_reference_callbacks
    raw = pdf_bytes(3)
    old = harness.render('synthetic-draft-a', raw)
    harness.request(old)
    old.surface()
    old_ticket = old.entry['ticket']
    other = harness.render('synthetic-draft-b', raw)
    harness.request(other)
    other.surface()
    other_ticket = other.entry['ticket']
    assert harness.store.stats()['pdf_entries'] == 2

    reference_preview.discard_reference_scope('synthetic-draft-a')
    assert not harness.store.available(old.owner['owner'], old_ticket)
    assert harness.store.available(other.owner['owner'], other_ticket)
    old_view = dict(old.entry['view'])
    count_work, count_rendered = len(harness.work), len(harness.rendered)
    harness.request(old, indexes=(1, 2))  # Valid old generation, obsolete owner.
    old.surface()
    assert old.entry['view'] == old_view
    assert len(harness.work) == count_work
    assert len(harness.rendered) == count_rendered
    assert harness.store.stats()['pdf_entries'] == 1

    replacement = harness.render('synthetic-draft-a', raw)
    assert replacement.owner is not old.owner
    assert replacement.view['generation'] != old.view['generation']
    count_work, count_rendered = len(harness.work), len(harness.rendered)
    harness.request(old, indexes=(2,))
    old.surface()
    assert 'view' not in replacement.entry
    assert len(harness.work) == count_work
    assert len(harness.rendered) == count_rendered
    harness.request(replacement, indexes=(1,))
    replacement.surface()
    assert replacement.entry['view']['pages'] == (1,)
    assert harness.store.available(replacement.owner['owner'], replacement.entry['ticket'])
    assert harness.store.available(other.owner['owner'], other_ticket)
    assert harness.store.stats()['pdf_entries'] == 2


def test_replaced_content_rejects_retained_fragment_and_callback_without_recreating_old_ticket(
    retained_reference_callbacks,
):
    harness = retained_reference_callbacks
    old = harness.render('synthetic-draft', pdf_bytes(3))
    harness.request(old)
    old.surface()
    old_ticket = old.entry['ticket']
    replacement = harness.render('synthetic-draft', pdf_bytes(2))
    assert replacement.owner is old.owner
    assert replacement.entry is not old.entry
    assert not harness.store.available(old.owner['owner'], old_ticket)
    assert replacement.view['generation'] != old.view['generation']
    old_view = dict(old.entry['view'])
    count_work, count_rendered = len(harness.work), len(harness.rendered)
    harness.request(old, indexes=(1, 2))
    old.surface()
    assert old.entry['view'] == old_view
    assert 'view' not in replacement.entry
    assert len(harness.work) == count_work
    assert len(harness.rendered) == count_rendered
    assert harness.store.stats()['pdf_entries'] == 0

    harness.request(replacement, indexes=(1,))
    replacement.surface()
    replacement_ticket = replacement.entry['ticket']
    assert replacement_ticket.pages == 2
    count_work, count_rendered = len(harness.work), len(harness.rendered)
    old.surface()
    assert len(harness.work) == count_work
    assert len(harness.rendered) == count_rendered
    assert replacement.entry['ticket'] is replacement_ticket
    assert harness.store.available(replacement.owner['owner'], replacement_ticket)
    assert harness.store.stats()['pdf_entries'] == 1


def test_scope_reset_during_ticket_creation_discards_late_result(
    retained_reference_callbacks, monkeypatch,
):
    harness = retained_reference_callbacks
    old = harness.render('synthetic-draft', pdf_bytes(2))
    harness.request(old)
    original_put = harness.store.put
    late = []

    def put_then_reset(*args, **kwargs):
        ticket = original_put(*args, **kwargs)
        late.append(ticket)
        reference_preview.discard_reference_scope('synthetic-draft')
        return ticket

    monkeypatch.setattr(harness.store, 'put', put_then_reset)
    count_rendered = len(harness.rendered)
    old.surface()
    assert len(late) == 1
    assert old.entry['ticket'] is None
    assert not harness.store.available(old.owner['owner'], late[0])
    assert harness.store.stats()['pdf_entries'] == 0
    assert not any(kind == 'raster' for kind, _identity in harness.work)
    assert len(harness.rendered) == count_rendered
    count_work = len(harness.work)
    old.surface()
    assert len(harness.work) == count_work
    assert len(late) == 1
