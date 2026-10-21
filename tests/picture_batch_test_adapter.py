"""AppTest-only frontend emulator; browser decode gates have separate JS tests."""
import streamlit as st
from contextlib import contextmanager
from app import monthly_report_picture_batch_ui as batch


@contextmanager
def install():
    def render(prefix, envelope, pictures):
        key=prefix+'_test_picture_component_'+envelope['nonce']
        keys=[]
        def submit():
            st.session_state[key]={'submission': {'identity':envelope['identity'], 'nonce':envelope['nonce'],
                'loaded':[True]*len(pictures), 'left':[st.session_state[k] for k in keys]}}
            batch._queue_component(prefix,envelope,key)
        with st.form(key+'_form'):
            for n,(raw,title,context) in enumerate(pictures):
                st.image(raw); st.caption(title+' '+context)
                choice=key+'_left_'+str(n);keys.append(choice)
                st.checkbox('Leave for correction',key=choice)
            st.form_submit_button(f'Confirm these {len(pictures)} pictures are ready (except those left for correction)',on_click=submit)
    previous = batch._render_group
    batch._render_group=render
    try:
        yield
    finally:
        batch._render_group=previous
