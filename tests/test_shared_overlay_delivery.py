"""Expected immutable publication and one naturally requested native response."""
from types import SimpleNamespace

import pytest

from scripts import patch_streamlit_frontend as compat
from scripts.qa_shared_fixture_testing import (
    _expected_frontend, _expected_overlay, _expected_virtualizer,
    _overlay_response_receipt, _virtualizer_response_receipt,
)
from test_streamlit_frontend_compat import bundle, previous_overlay


def test_expected_overlay_is_pinned_and_actual_response_is_read_once(bundle):
    root, scripts = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    expected = _expected_overlay(root)
    calls = []
    raw = (scripts / expected[0]).read_bytes()
    response = SimpleNamespace(url="http://127.0.0.1:8521/static/js/" + expected[0],
        status=200, headers={"content-length": str(len(raw))},
        body=lambda: calls.append("read") or raw)
    receipt = _overlay_response_receipt(response, expected)
    assert receipt["matches"] and receipt["resize_hold_count"] == 1
    assert receipt["original_resize_hook_count"] == 0 and calls == ["read"]


def test_same_size_changed_response_is_rejected_and_oversized_body_is_not_read(bundle):
    root, scripts = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    expected = _expected_overlay(root)
    raw = expected[1]
    response = SimpleNamespace(url="http://127.0.0.1:8521/static/js/" + expected[0],
        status=200, headers={"content-length": str(len(raw))}, body=lambda: raw[:-1] + b"x")
    assert not _overlay_response_receipt(response, expected)["matches"]
    def forbidden_read():
        raise AssertionError("An oversized response must not be read.")
    response.headers = {"content-length": str(2 * 1024 * 1024)}
    response.body = forbidden_read
    assert not _overlay_response_receipt(response, expected)["matches"]


@pytest.mark.parametrize("kind,expected", [("entry", _expected_frontend), ("overlay_bundle", _expected_overlay),
                                          ("virtualizer_bundle", _expected_virtualizer)])
def test_expected_asset_cannot_adopt_changed_bytes_after_pinned_validation(bundle, monkeypatch, kind, expected):
    root, scripts = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    selected = compat.selected_frontend
    def changed_after_validation(*args, **kwargs):
        receipt = selected(*args, **kwargs)
        path = scripts / receipt[kind]
        raw = path.read_bytes()
        path.write_bytes(b" " + raw[1:])
        return receipt
    monkeypatch.setattr(compat, "selected_frontend", changed_after_validation)
    with pytest.raises(RuntimeError, match="changed after validation"):
        expected(root)


def test_expected_virtualizer_body_matches_the_pinned_repair(bundle):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    expected = _expected_virtualizer(root)
    calls = []
    name, raw = expected
    response = SimpleNamespace(url="http://127.0.0.1:8529/static/js/" + name,
        status=200, headers={"content-length": str(len(raw))}, body=lambda: calls.append("read") or raw)
    receipt = _virtualizer_response_receipt(response, expected)
    assert receipt["matches"] and receipt["resize_hold_count"] == 1
    assert receipt["original_resize_hook_count"] == 0 and calls == ["read"]


def test_expected_virtualizer_rejects_valid_prior_overlay_only_publication(bundle):
    root, _ = bundle
    previous_overlay(bundle, True)
    assert compat.selected_frontend(root)["virtualizer_resize"] is False
    with pytest.raises(RuntimeError, match="lacks virtual-list"):
        _expected_virtualizer(root)


@pytest.mark.parametrize("queued_scroll", [False, True])
def test_current_overlay_gate_rejects_valid_prior_publication_without_scroll_repair(bundle, queued_scroll):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, True, queued_scroll=queued_scroll,
                              latest_scroll_close=False)
    assert old.names[compat.INDEX_BUNDLE] == ("index.enfra-frontend-4cf97569e258.js" if queued_scroll
                                            else "index.enfra-frontend-25142a252245.js")
    for native, raw in old.payloads.items():
        (scripts / old.names[native]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    assert compat.selected_frontend(root)["queued_scroll"] is queued_scroll
    with pytest.raises(RuntimeError, match="lacks committed scroll-close" if queued_scroll else "lacks queued-scroll"):
        _expected_overlay(root)
