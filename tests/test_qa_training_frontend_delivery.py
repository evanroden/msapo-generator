"""Real pinned expectations and bounded naturally requested Training responses."""
from types import SimpleNamespace

import pytest

from scripts import patch_streamlit_frontend as compat
from scripts.qa_training_frontend_delivery import TrainingFrontendDelivery
from test_streamlit_frontend_compat import bundle


def response(name, raw, calls):
    def body():
        calls.append(name)
        return raw
    return SimpleNamespace(url="http://127.0.0.1:8535/static/js/" + name,
        status=200, headers={"content-length": str(len(raw))}, body=body)


def test_training_observes_exact_primary_and_overlay_once_without_requests(bundle):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)
    delivery = TrainingFrontendDelivery(root)
    callbacks, calls = {}, []
    page = SimpleNamespace(on=lambda event, callback: callbacks.update({event: callback}))
    delivery.attach(page)
    assert set(callbacks) == {"response"}  # No fetch or synthetic event API.
    # The locked native HTML genuinely preloads this unrelated index module;
    # it must not consume the first-primary slot or trigger a body read.
    assert b"index.esm.BsMvI3hp.js" in (root / "index.html").read_bytes()
    callbacks["response"](response("index.esm.BsMvI3hp.js", b"unrelated vendor preload", calls))
    assert delivery.receipts == {"primary": [], "overlay": [], "combobox": []} and not calls
    with pytest.raises(AssertionError, match="exact pinned"):
        delivery.require()
    for name, raw in delivery.expected.values():
        asset = response(name, raw, calls)
        callbacks["response"](asset)
        callbacks["response"](asset)  # A reload cannot overwrite first evidence.
    delivery.require()
    assert calls == [expected[0] for expected in delivery.expected.values()]
    assert delivery.receipts["primary"][0]["full_scope_predicate_count"] == 1
    assert delivery.receipts["overlay"][0]["resize_hold_count"] == 1


@pytest.mark.parametrize("wrong_kind", ["primary", "overlay", "combobox"])
def test_training_cannot_replace_wrong_first_delivery_with_later_correct_body(bundle, wrong_kind):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1", scalar_date=True)
    delivery = TrainingFrontendDelivery(root)
    calls = []
    name, raw = delivery.expected[wrong_kind]
    delivery.observe(response(name, b" " + raw[1:], calls))
    delivery.observe(response(name, raw, calls))
    others = [item for kind, item in delivery.expected.items() if kind != wrong_kind]
    for other, other_raw in others:
        delivery.observe(response(other, other_raw, calls))
    with pytest.raises(AssertionError, match=wrong_kind + " asset"):
        delivery.require()
    assert calls == [name, *[item[0] for item in others]]
    assert not delivery.receipts[wrong_kind][0]["matches"]


def test_prior_committed_close_generation_is_preserved_but_not_accepted_as_current(bundle):
    from scripts.qa_training_frontend_delivery import _expected_combobox
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, True, selection_safe_close=False)
    assert old.names[compat.INDEX_BUNDLE] == "index.enfra-frontend-21a39a02dec4.js"
    for native, raw in old.payloads.items():
        (scripts / old.names[native]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    assert compat.selected_frontend(root)["selection_safe_close"] is False
    with pytest.raises(RuntimeError, match="lacks selection-safe"):
        _expected_combobox(root)
    new = compat.patch_bundle(root, installed_version="1.61.1")
    assert new["selection_safe_close"] and new["scalar_date"]
    for native, raw in old.payloads.items():
        assert (scripts / old.names[native]).read_bytes() == raw
