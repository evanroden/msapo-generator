"""Match the pinned native controls while their loading placeholders are visible."""
import hashlib
import json
import re

import streamlit as st


def _selector(key):
    return ".st-key-" + re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())


def reserve_text_area(key, height):
    if st.__version__ != "1.61.1" or type(height) is not int or height < 68:
        return
    st.html(f'<style>{_selector(key)} > [data-testid="stSkeleton"]'
            '{height:' + str(height) + 'px;}</style>')


def reserve_empty_uploader(key, label):
    if st.__version__ != "1.61.1" or st.session_state.get(key):
        return
    selector = _selector(key)
    skeleton = selector + ' > [data-testid="stSkeleton"]'
    container = "enfra-upload-" + hashlib.sha256(key.encode()).hexdigest()[:16]
    # CSS text supplies the same wrapping height as the native label. It stays
    # inside Streamlit's aria-hidden skeleton and never becomes a second input.
    caption = json.dumps(label, ensure_ascii=False)
    for char, escaped in (("<", r"\3c "), (">", r"\3e "), ("&", r"\26 ")):
        caption = caption.replace(char, escaped)
    st.html(
        '<style>' + selector + ':has(> [data-testid="stSkeleton"])'
        '{container-type:inline-size;container-name:' + container + ';}'
        + skeleton + '{height:auto;}'
        + skeleton + '::before{content:' + caption + ';display:block;visibility:hidden;'
        'font-size:.875rem;line-height:1.5rem;margin-bottom:.25rem;white-space:normal;}'
        + skeleton + '::after{content:"";display:block;height:4.25rem;}'
        # The pinned empty dropzone stacks its button and size hint below 23rem:
        # padding1.5rem + button2.5rem + gap.75rem + hint1.4rem.
        + '@container ' + container + ' (width < 23rem){'
        + skeleton + '::after{height:6.15rem;}}</style>'
    )
