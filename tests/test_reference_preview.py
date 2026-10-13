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
