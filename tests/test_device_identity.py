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


def test_bootstrap_actually_renders_instead_of_raising():
    """The cookie iframe must survive a real Streamlit run.

    This is the load-bearing test for ALL device-scoped memory. ensure_device_cookie
    previously passed height=0 to st.iframe, which Streamlit rejects with
    StreamlitInvalidHeightError. The caller wrapped the call in a non-blocking
    try/except, so the failure was invisible: the bootstrap iframe never
    rendered, the cookie was never created, device_token() always returned "",
    and requester recall (purchase orders) plus profile and employee-number
    recall (expense reports) were silently inert for the whole deployment.

    Asserting on the arguments would not have caught it -- only executing the
    call inside a Streamlit script run does.
    """
    from streamlit.testing.v1 import AppTest

    def script():  # pragma: no cover - executed inside AppTest's runtime
        import streamlit as st

        from app.device_identity import ensure_device_cookie

        try:
            ensure_device_cookie()
            st.text("bootstrap-ok")
        except Exception as exc:  # noqa: BLE001 - surfaced as text for the assert
            st.text(f"bootstrap-failed: {type(exc).__name__}: {exc}")

    app = AppTest.from_function(script, default_timeout=30).run()
    rendered = [element.value for element in app.text]

    assert "bootstrap-ok" in rendered, rendered


def test_bootstrap_requests_a_positive_iframe_height():
    """Pin the specific regression: height must be a positive integer.

    Checks executable lines only -- the explanatory comment in that function
    legitimately mentions the old value.
    """
    source = inspect.getsource(identity_module.ensure_device_cookie)
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )

    assert "height=0" not in code
    assert "height=1" in code
