"""Owned browser surface: image decode and explicit consent in one event."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote
import streamlit as st
from streamlit import config
from streamlit.runtime import Runtime

HTML = '<section class="picture-review" aria-label="Picture review"></section>'
CSS = '''
.picture-review{font:inherit;color:inherit;width:100%}
.picture-review figure{margin:0 0 1.5rem}
.picture-review img{display:block;max-width:100%;height:auto}
.picture-review p,.picture-review h4{overflow-wrap:anywhere}
.picture-review button{max-width:100%;font:inherit;padding:.6rem 1rem;min-height:44px;border:1px solid #668477;border-radius:6px;background:white;color:#18382b;cursor:pointer}
.picture-review button:disabled{opacity:.5;cursor:default}
.picture-review label{display:block;padding:.6rem 0}
.picture-review input{margin-right:.5rem}
.picture-review :focus-visible{outline:3px solid #397f75;outline-offset:3px}
.picture-review [role=status]{padding:.5rem 0}'''

@lru_cache(maxsize=2)
def _component(runtime):
    return st.components.v2.component('report_picture_group', html=HTML, css=CSS,
        js=Path(__file__).with_suffix('.js').read_text())


def _media_url(raw, mime, coordinate):
    # Use the ordinary image manager without image_to_url's resize/reencoding.
    # Re-register on every render so native full/fragment session lifetime owns it.
    # Native large-media IDs use sampled hashing; bind the full bytes as well,
    # otherwise an unsampled change can resolve to an older stored image.
    url = Runtime.instance().media_file_mgr.add(raw, mime, coordinate,
                                              file_name=sha256(raw).hexdigest())
    if not re.fullmatch(r'/media/[a-f0-9]{32}\.(?:png|jpe?g)', url):
        raise ValueError('Picture media could not be registered safely.')
    base = config.get_option('server.baseUrlPath').strip('/')
    return ('/' + quote(base, safe='/') if base else '') + url


def render_group(*, key, envelope, pictures, on_change, media_scope):
    return _component(Runtime.instance())(key=key, data={
        'identity': envelope['identity'], 'nonce': envelope['nonce'],
        'pictures': [{'url': _media_url(raw, 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg',
                                     f'picture-review:{media_scope}:{index}'),
                      'title': title, 'context': context}
                     for index, (raw, title, context) in enumerate(pictures)],
    }, default={'submission': None}, on_submission_change=on_change, height='content')
