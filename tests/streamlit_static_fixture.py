"""Build a native-entry test input from either supported installed frontend."""
from functools import lru_cache
from types import SimpleNamespace

from scripts import patch_streamlit_frontend as frontend


def pristine_html(installed):
    html = (installed / "index.html").read_bytes()
    return _known_original_html(installed, html)


@lru_cache(maxsize=2)
def _known_original_html(installed, html):
    # Validate the selected derivative and its entire immutable graph before
    # reversing its known names in this disposable fixture only. The installed
    # files stay patched; unknown or corrupt publications still fail loudly.
    # Keep installed crawler branding: it is independent of the native module
    # graph and legitimately differs from the wheel's unbranded HTML.
    _, checked, name, _, selected, publications = frontend._validated_publications(installed, "1.61.1")
    assert checked == html
    native = {key: key for publication in publications for key in publication.names}
    original = frontend._publication_html(html, name, SimpleNamespace(names=native), publications)
    assert frontend._SCRIPT.findall(original) == [frontend.INDEX_BUNDLE.encode()]
    if selected:
        assert frontend._publication_html(original, frontend.INDEX_BUNDLE, selected, publications) == html
    return original
