"""Original source viewing stays bounded, private and free of reading calls."""
from hashlib import sha256

import fitz
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
