"""Cold status hydration reserves its own exact, wrapping native text."""
from html import unescape
import json
import re

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_save_status as status


APP = '''
import streamlit as st
from app.monthly_report_save_status import SaveStatus
value = SaveStatus(st.session_state.get("prefix", "synthetic_status"),
                   recovery_available=st.session_state.get("recovery", True))
action = st.session_state.get("action")
if action == "saved":
    value.browser_saved("2026-10-17T22:45:01+00:00")
elif action == "invalid_time":
    value.browser_saved("not a timestamp")
elif action == "shared":
    value.shared_saved(1234567890)
elif action == "failed":
    value.failed()
'''


def _run(**state):
    app = AppTest.from_string(APP)
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _styles(app):
    return [item.proto.body for item in app.get("html")]


def _status_markup(app):
    found = [item.value for item in app.markdown if 'class="enfra-browser-save-status"' in item.value]
    assert len(found) == 1
    return found[0]


def _lines(markup):
    return tuple(unescape(value) for value in re.search(r'>(.*?)</p>$', markup).group(1).split('<br>'))


def _css_content(style, pseudo):
    match = re.search(r'::' + pseudo + r'\{content:((?:"(?:[^"\\]|\\.)*"));', style)
    assert match, style
    return json.loads(match.group(1))


@pytest.mark.parametrize("state", [
    {}, {"recovery": False}, {"action": "saved"}, {"action": "invalid_time"},
    {"action": "shared"}, {"action": "failed"},
])
def test_loading_reservation_tracks_exact_current_status_including_longest_messages(state):
    app = _run(**state)
    styles = _styles(app)
    assert styles, "Cold native Markdown must reserve its status before raw HTML hydrates."
    style = styles[-1]
    scope, message = _lines(_status_markup(app))
    assert _css_content(style, "before") == scope
    assert _css_content(style, "after") == message
    assert '.st-key-synthetic_status_browser_save_status [data-testid="stMarkdownContainer"] > [data-testid="stSkeleton"]' in style
    assert 'height:auto;' in style
    assert 'font-size:.875rem;line-height:1.5;' in style
    assert 'display:block;visibility:hidden;white-space:normal;' in style
    assert 'word-break:break-word;' in style
    assert 'overflow-wrap:break-word;' in style
    assert 'height:42px' not in style and 'height:2.625rem' not in style
    assert 'scroll' not in style and '<script' not in style
    assert 'role="status" aria-live="polite"' in _status_markup(app)
    assert len(styles) == (2 if state.get("action") else 1)
    assert all(not item.proto.unsafe_allow_javascript for item in app.get("html"))


def test_reserved_and_real_typography_have_the_same_two_line_arithmetic_at_text_scales():
    app = _run(action="saved")
    style, markup = _styles(app)[-1], _status_markup(app)
    assert 'font-size:.875rem;line-height:1.5;' in style
    assert 'font-size:.875rem;line-height:1.5;' in markup
    # This is a source-bound box-model check, not a substitute for browser QA.
    # Neither reservation fixes the width or clips additional wrapped lines.
    for root_px in (16, 20, 24, 32):
        assert 2 * .875 * 1.5 * root_px == 2.625 * root_px
    assert 'width:' not in style and 'max-height:' not in style and 'overflow:hidden' not in style


def test_reservation_uses_event_container_and_leaves_one_markdown_status_path():
    from streamlit.delta_generator import DeltaGenerator
    original = DeltaGenerator._enqueue
    paths = []
    def observed(self, delta_type, element_proto, *args, **kwargs):
        result = original(self, delta_type, element_proto, *args, **kwargs)
        if delta_type in {"html", "markdown"}:
            paths.append((delta_type, tuple(result._cursor.delta_path), getattr(element_proto, "body", "")))
        return result
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(DeltaGenerator, "_enqueue", observed)
        app = _run(action="saved")
    markdown_paths = {path for kind, path, body in paths if kind == "markdown" and 'enfra-browser-save-status' in body}
    html_paths = {path for kind, path, body in paths if kind == "html"}
    assert len(markdown_paths) == 1 and html_paths
    assert all(path[0] != next(iter(markdown_paths))[0] for path in html_paths)
    assert _status_markup(app).endswith('Browser draft<br>Last saved · 22:45 UTC</p>')


def test_css_key_and_text_cannot_escape_the_reservation(monkeypatch):
    captured = []
    monkeypatch.setattr(status.st, 'html', captured.append)
    status._reserve_status(' bad</style> key ', '</style><script>bad</script>', 'quoted " \\ & < >\n\t')
    style, = captured
    assert '.st-key-bad--style--key ' in style
    assert style.count('</style>') == 1
    assert '<script>' not in style
    assert r'\3c ' in style and r'\3e ' in style and r'\26 ' in style
    assert r'\"' in style and r'\\' in style
    assert r'\a ' in style and r'\9 ' in style


def test_other_streamlit_version_keeps_status_but_requires_fresh_geometry_review(monkeypatch):
    monkeypatch.setattr(status.st, '__version__', 'future-unreviewed')
    app = _run(action="saved")
    assert not _styles(app)
    assert 'Last saved · 22:45 UTC' in _status_markup(app)
