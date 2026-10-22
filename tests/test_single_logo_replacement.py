from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_branding_replace import (
    OWNER_VARIANT_PREFIX, prepare_replacement, replace_selected_logo,
)


def image(color):
    stream=BytesIO(); Image.new("RGBA",(90,30),color).save(stream,"PNG")
    return stream.getvalue()


@pytest.fixture
def catalog(tmp_path,monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR",str(tmp_path))
    raw=image("green"); ref=library.asset_reference(raw,"png")
    logos=tuple(branding.BrandLogo(key,title,contracts,ref,
        "https://example.invalid/brand", "https://example.invalid/old.png", "2026-10-07", "Original reviewed artwork")
        for key,title,contracts in (("enfra","Synthetic company",()),
            ("client-a","Synthetic client A",("Synthetic contract A",)),
            ("client-b","Synthetic client B",("Synthetic contract B",))))
    state=branding.save_branding(logos,{ref:raw},expected_revision=0,
        actor="Synthetic original reviewer",confirmed=True)
    return state,raw,image((0,40,20,0))


def reviewed(state,raw,key="enfra",actor="Synthetic reviewer"):
    logo=next(v for v in state.logos if v.key==key)
    return prepare_replacement(logo,state.revision,raw,actor=actor,
        checked_on="2026-10-22",source_note="Approved transparent variant from owner-provided design.")


def save(review,raw,**changes):
    args=dict(expected_revision=review.revision,actor=review.actor,checked_on=review.replacement.checked_on,
        source_note=review.replacement.source_note.removeprefix(OWNER_VARIANT_PREFIX),
        review_token=review.token,confirmed=True)
    key=changes.pop("key",review.original.key)
    return replace_selected_logo(key,raw,**(args|changes))


@pytest.mark.parametrize("key",["enfra","client-a","client-b"])
def test_single_change_preserves_all_scopes_assets_and_history(catalog,key):
    state,old,raw=catalog; review=reviewed(state,raw,key)
    before={p.name:p.read_bytes() for p in (branding._path()/"assets").iterdir()}
    updated=save(review,raw)
    assert updated.revision==2 and updated.action=="replace-logo:"+key
    assert branding.load_branding(1)==state
    for original in state.logos:
        new=next(v for v in updated.logos if v.key==original.key)
        if original.key!=key: assert new==original
        else:
            assert (new.key,new.title,new.contracts,new.source_url)==(original.key,original.title,original.contracts,original.source_url)
            assert branding.read_logo(new)==raw
            assert new.source_note.startswith(OWNER_VARIANT_PREFIX)
            assert new.asset_url==new.source_url
    for name,data in before.items(): assert (branding._path()/"assets"/name).read_bytes()==data
    assert branding.read_logo(state.logos[0])==old


@pytest.mark.parametrize("change",[
    {"key":"client-a"},{"actor":"Different reviewer"},{"checked_on":"2026-10-23"},
    {"source_note":"Different source"},{"review_token":"0"*64},{"confirmed":False},
    {"expected_revision":0},{"key":"missing"},{"review_token":"ñ"},
])
def test_stale_cross_record_or_changed_review_cannot_save(catalog,change):
    state,_,raw=catalog; review=reviewed(state,raw)
    with pytest.raises(ValueError): save(review,raw,**change)
    assert branding.load_branding()==state


def test_different_bytes_invalidate_confirmation(catalog):
    state,_,raw=catalog; review=reviewed(state,raw)
    with pytest.raises(ValueError,match="review changed"):
        save(review,image("blue"))
    assert branding.load_branding()==state


def test_repeat_old_save_rejects_and_cannot_overwrite_new_revision(catalog):
    state,_,raw=catalog; review=reviewed(state,raw)
    updated=save(review,raw)
    with pytest.raises(library.RevisionConflict): save(review,raw)
    assert branding.load_branding()==updated


def test_concurrent_catalog_edit_is_rejected_under_existing_atomic_lock(catalog,monkeypatch):
    state,_,raw=catalog; review=reviewed(state,raw)
    original=branding.save_branding
    external=[]
    def raced(*args,**kwargs):
        external.append(original(state.logos,{},expected_revision=1,actor="Concurrent reviewer",confirmed=True))
        return original(*args,**kwargs)
    monkeypatch.setattr(branding,"save_branding",raced)
    with pytest.raises(library.RevisionConflict): save(review,raw)
    assert branding.load_branding()==external[0]
    assert branding.load_branding().logos==state.logos


@pytest.mark.parametrize("raw",[b"",b"not png",b"<svg></svg>"])
def test_invalid_image_never_changes_catalog(catalog,raw):
    state,_,_=catalog
    with pytest.raises(ValueError): reviewed(state,raw)
    assert branding.load_branding()==state


def app_with_upload(monkeypatch,raw):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    original=st.file_uploader
    source={"raw":raw}
    def upload(label,*args,**kwargs):
        if label=="Owner-provided approved logo (PNG)":
            return SimpleNamespace(getvalue=lambda:source["raw"])
        return original(label,*args,**kwargs)
    monkeypatch.setattr(st,"file_uploader",upload)
    app=AppTest.from_string('''
from app.monthly_report_branding_ui import render_branding
from app.monthly_report_ui import _field
render_branding(_field)
''',default_timeout=30).run()
    app.text_input("report_branding_actor").set_value("Synthetic reviewer").run()
    next(x for x in app.text_area if x.label=="Artwork source and approval").set_value("Owner-provided approved transparent design.").run()
    return app,source


@pytest.mark.parametrize("change",["actor","note","date","bytes","selected"])
def test_ui_confirmation_is_bound_to_every_displayed_review_input(catalog,monkeypatch,change):
    state,_,raw=catalog; app,source=app_with_upload(monkeypatch,raw)
    assert not app.exception
    confirm=next(c for c in app.checkbox if c.label.startswith("I reviewed this replacement"))
    confirm.check().run()
    old_key=confirm.key
    if change=="actor": app.text_input("report_branding_actor").set_value("Other reviewer").run()
    elif change=="note": next(x for x in app.text_area if x.label=="Artwork source and approval").set_value("Changed owner evidence").run()
    elif change=="date":
        from datetime import date
        next(x for x in app.date_input if x.label=="Artwork reviewed on").set_value(date(2026,10,23)).run()
    elif change=="bytes": source["raw"]=image("blue"); app.run()
    else: app.selectbox("report_branding_preview_").set_value("client-a").run()
    assert not app.exception
    active=[c for c in app.checkbox if c.label.startswith("I reviewed this replacement")]
    assert not active or (not active[0].value and active[0].key!=old_key)
    assert branding.load_branding()==state


def test_ui_save_requires_review_and_changes_only_selected_record(catalog,monkeypatch):
    state,_,raw=catalog; app,_=app_with_upload(monkeypatch,raw)
    save_button=next(b for b in app.button if b.label=="Replace selected logo")
    assert save_button.disabled
    next(c for c in app.checkbox if c.label.startswith("I reviewed this replacement")).check().run()
    next(b for b in app.button if b.label=="Replace selected logo").click().run()
    assert not app.exception and branding.load_branding().revision==2
    assert branding.load_branding().logos[1:]==state.logos[1:]
    assert any("owner-provided artwork" in c.value for c in app.caption)
    assert not any(x.label=="Artwork source" for x in app.get("link_button"))
    app.run()
    assert branding.load_branding().revision==2


def test_owner_provided_offer_does_not_claim_official_source_was_rechecked(catalog):
    from streamlit.testing.v1 import AppTest
    state,_,raw=catalog
    save(reviewed(state,raw),raw)
    app=AppTest.from_string('''
from app.monthly_report_branding_ui import offer_logo
from app.monthly_report_model import ResolvedBlock
offer_logo(ResolvedBlock("brand_logo", "Omit"), "Synthetic contract A", "test", {})
''').run()
    assert not app.exception
    assert any("owner-provided artwork reviewed" in c.value for c in app.caption)
    assert not any("official source checked" in c.value for c in app.caption)


def test_empty_upload_does_not_hide_existing_history_controls(catalog,monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    state,_,_=catalog
    original=st.file_uploader
    def upload(label,*args,**kwargs):
        if label=="Owner-provided approved logo (PNG)": return SimpleNamespace(getvalue=lambda:b"")
        return original(label,*args,**kwargs)
    monkeypatch.setattr(st,"file_uploader",upload)
    app=AppTest.from_string('''
from app.monthly_report_branding_ui import render_branding
from app.monthly_report_ui import _field
render_branding(_field)
''').run()
    assert not app.exception and app.error
    assert app.selectbox("report_branding_history")
    assert branding.load_branding()==state


def test_hosted_native_acceptance_requires_both_engines_inside_shared_budget():
    from pathlib import Path
    workflow=Path('.github/workflows/adaptive-workspaces.yml').read_text()
    name='      - name: Shared logo single-record replacement, stale review and restore\n'
    step=workflow.split(name,1)[1].split('      - name:',1)[0]
    assert "if: ${{ !cancelled() }}" in step
    assert "ci_native_test_budget.py --minutes 25" in step
    assert "python scripts/qa_single_logo_admin.py\n" in step
    assert "chromium-only" not in step
    assert "test-artifacts/single-logo-admin/" in workflow


@pytest.mark.parametrize("damage",["missing","corrupt"])
def test_failed_retained_asset_validation_installs_nothing(catalog,damage):
    state,_,raw=catalog; review=reviewed(state,raw)
    path=branding._path()/"assets"/state.logos[1].asset
    path.unlink()
    if damage=="corrupt": path.write_bytes(b"synthetic damaged bytes")
    before={str(p.relative_to(library._root())):p.read_bytes()
            for p in library._root().rglob('*') if p.is_file() and p.name!='.write-lock'}
    with pytest.raises((ValueError,OSError)): save(review,raw)
    after={str(p.relative_to(library._root())):p.read_bytes()
           for p in library._root().rglob('*') if p.is_file() and p.name!='.write-lock'}
    assert after==before
    assert branding.load_branding()==state


@pytest.mark.parametrize("zone", ["America/New_York", "Pacific/Honolulu", None])
def test_review_date_uses_operator_timezone_and_fallback(catalog, monkeypatch, zone):
    from datetime import date
    from app import config
    import streamlit as st
    seen = []
    monkeypatch.setattr(type(st.context), "timezone", property(lambda self: zone))
    def today(browser_timezone=None):
        seen.append(browser_timezone)
        return date(2026, 10, 21)
    monkeypatch.setattr(config, "operator_today", today)
    _, _, raw = catalog
    app, _ = app_with_upload(monkeypatch, raw)
    assert not app.exception and seen and set(seen) == {zone}
    assert next(d for d in app.date_input if d.label == "Artwork reviewed on").value == date(2026, 10, 21)


def test_cleared_review_date_contains_error_and_preserves_history(catalog, monkeypatch):
    state, _, raw = catalog
    app, _ = app_with_upload(monkeypatch, raw)
    confirmation = next(c for c in app.checkbox if c.label.startswith("I reviewed this replacement"))
    confirmation.check().run()
    next(d for d in app.date_input if d.label == "Artwork reviewed on").set_value(None).run()
    assert not app.exception
    assert any("Enter the date" in c.value for c in app.caption)
    assert not any(b.label == "Replace selected logo" for b in app.button)
    assert app.selectbox("report_branding_history")
    assert branding.load_branding() == state


@pytest.mark.parametrize("changed", [
    {"revision": 4}, {"asset": "unexpected.png"}, {"healthy": False}, {"history": False},
])
def test_native_catalog_receipt_rejects_wrong_revision_asset_or_invariant(changed):
    from scripts.qa_single_logo_admin import validate_catalog_state
    state = {"revision": 5, "asset": "expected.png", "healthy": True, "history": True}
    assert validate_catalog_state(state, 5, "expected.png") == state
    with pytest.raises(AssertionError):
        validate_catalog_state({**state, **changed}, 5, "expected.png")
