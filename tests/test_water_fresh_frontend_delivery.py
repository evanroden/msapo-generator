"""Fresh task verifies natural main/overlay/virtual-list delivery without fetching."""
from types import SimpleNamespace

import pytest

from scripts import patch_streamlit_frontend as compat
from scripts.qa_shared_fixture_testing import _expected_frontend, _expected_overlay, _expected_virtualizer
from scripts.qa_water_fresh_page_journey import observe_frontend_delivery, require_frontend_delivery
from test_streamlit_frontend_compat import bundle


def response(name, raw, reads):
    return SimpleNamespace(url="http://127.0.0.1:8529/static/js/" + name, status=200,
        headers={"content-length": str(len(raw))}, body=lambda: reads.append(name) or raw)


def test_fresh_task_checks_only_three_pinned_natural_responses_once(bundle):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    callbacks, record, reads = {}, {}, []
    page = SimpleNamespace(on=lambda kind, callback: callbacks.update({kind: callback}))
    observe_frontend_delivery(page, record, static_dir=root)
    assert set(callbacks) == {"response"}  # No request/event/layout API is used.
    callbacks["response"](response("index.esm.BsMvI3hp.js", b"native vendor preload", reads))
    assert not reads
    with pytest.raises(AssertionError, match="exact pinned"):
        require_frontend_delivery(record)
    for expected in (_expected_frontend, _expected_overlay, _expected_virtualizer):
        name, raw = expected(root)
        item = response(name, raw, reads)
        callbacks["response"](item)
        callbacks["response"](item)
    require_frontend_delivery(record)
    assert len(reads) == 3 and len(set(reads)) == 3


def test_first_wrong_virtualizer_delivery_is_not_replaced_by_later_correct_body(bundle):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    callbacks, record, reads = {}, {}, []
    page = SimpleNamespace(on=lambda kind, callback: callbacks.update({kind: callback}))
    observe_frontend_delivery(page, record, static_dir=root)
    for expected in (_expected_frontend, _expected_overlay):
        name, raw = expected(root)
        callbacks["response"](response(name, raw, reads))
    name, raw = _expected_virtualizer(root)
    callbacks["response"](response(name, b" " + raw[1:], reads))
    callbacks["response"](response(name, raw, reads))
    with pytest.raises(AssertionError, match="virtualizer asset"):
        require_frontend_delivery(record)
    assert reads.count(name) == 1
