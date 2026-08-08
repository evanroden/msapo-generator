import inspect

import app.device_identity as identity_module
from app.device_identity import COOKIE_NAME, cookie_bootstrap_html, device_token


def test_device_token_accepts_only_the_expected_opaque_cookie():
    token = "0123456789abcdef0123456789abcdef"
    assert device_token({COOKIE_NAME: token}) == token
    assert device_token({COOKIE_NAME: token.upper()}) == token
    assert device_token({COOKIE_NAME: "too-short"}) == ""
    assert device_token({COOKIE_NAME: "g" * 32}) == ""
    assert device_token(None) == ""


def test_cookie_bootstrap_contains_no_requester_or_po_data():
    html = cookie_bootstrap_html()
    assert COOKIE_NAME in html
    assert "getRandomValues" in html
    assert "SameSite=Lax" in html
    assert "requester" not in html.lower()
    assert "vendor" not in html.lower()


def test_cookie_bootstrap_can_avoid_reloading_an_active_mobile_workflow():
    assert "const reloadParent = true;" in cookie_bootstrap_html()
    assert (
        "const reloadParent = false;"
        in cookie_bootstrap_html(reload_parent=False)
    )


def test_cookie_bootstrap_uses_the_supported_streamlit_iframe_api():
    source = inspect.getsource(identity_module)

    assert "st.iframe(" in source
    assert "components.html(" not in source
    assert "tab_index=-1" in source
