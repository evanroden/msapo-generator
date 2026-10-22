"""Real admin widgets in disposable logo-recovery storage, synthetic PNGs only.

Default hosted acceptance uses Chromium and WebKit; --chromium-only is an
explicit local convenience and reports only that engine. Never visits Render.
"""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse, quote
import urllib.request

from PIL import Image
from playwright.sync_api import expect, sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"test-artifacts"/"single-logo-admin"
URL="http://127.0.0.1:8520"
ROUTE=URL+"/?workflow=monthly&monthly_qa=logo-recovery&monthly_admin=logos"
REPORT={"synthetic_only":True,"physical_device":False,"browsers":{}}



def idle(page):
    expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")


def actor_value(page, value):
    actor = page.get_by_role("textbox", name="Logo editor name", exact=True)
    expect(actor).to_be_visible(); actor.fill(value); actor.press("Tab")
    expect(page.get_by_text("QA logo editor: " + value, exact=True)).to_be_visible()
    idle(page)


def check_native(page, label, timeout=30000):
    """Click the real visible native label, never its concealed input hitbox."""
    checkbox = page.get_by_role("checkbox", name=label, exact=True)
    expect(checkbox).to_be_visible(timeout=timeout)
    expect(checkbox).to_be_enabled(timeout=timeout)
    if not checkbox.is_checked():
        target = checkbox.locator("xpath=ancestor::label[1]")
        expect(target).to_be_visible(timeout=timeout)
        target.click(timeout=timeout)
    expect(checkbox).to_be_checked(timeout=timeout)


def native_negative_controls(context):
    # Separate data-document controls, never a mutation of the application DOM.
    # An overlay and a disabled native control must still reject this pointer path.
    guard = context.new_page()
    outcomes = {}
    try:
        for kind in ("ordinary", "overlay", "disabled"):
            disabled = " disabled" if kind == "disabled" else ""
            overlay = '<div style="position:fixed;inset:0;z-index:99;background:#ddd">Blocked pointer</div>' if kind == "overlay" else ""
            html = '<label style="display:block;padding:30px"><input type="checkbox" aria-label="Synthetic guard"' + disabled + '>Synthetic guard</label>' + overlay
            guard.goto("data:text/html," + quote(html))
            rejected = False
            try:
                check_native(guard, "Synthetic guard", timeout=1000)
            except (AssertionError, PlaywrightTimeoutError):
                rejected = True
            assert rejected == (kind != "ordinary")
            assert guard.get_by_role("checkbox", name="Synthetic guard").is_checked() == (kind == "ordinary")
            outcomes[kind] = "passed"
    finally:
        guard.close()
    return outcomes

def revision(page, value):
    expect(page.get_by_text("QA shared-logo revision: "+str(value),exact=True)).to_be_visible()
    expect(page.get_by_text("QA healthy logo unchanged: true",exact=True)).to_be_visible()
    expect(page.get_by_text("QA original histories unchanged: true",exact=True)).to_be_visible()


def open_panel(page,label):
    panel=page.locator('[data-testid="stExpander"]').filter(has=page.get_by_text(label,exact=True))
    expect(panel).to_have_count(1)
    summary=panel.locator("summary")
    if panel.locator("details").get_attribute("open") is None:
        summary.click()
    return panel


def choose(page,label,value):
    control=page.get_by_role("combobox",name=label,exact=True)
    idle(page)
    expect(control).to_be_visible(); control.click()
    page.get_by_role("option",name=value,exact=True).click()


def review(page,raw):
    panel=open_panel(page,"Replace this shared logo")
    upload=panel.locator('input[type="file"]')
    expect(upload).to_have_count(1)
    upload.set_input_files({"name":"synthetic-approved.png","mimeType":"image/png","buffer":raw})
    note=page.get_by_role("textbox",name="Artwork source and approval",exact=True)
    expect(note).to_be_visible()
    note.fill("Synthetic owner-provided transparent variant approved for testing.")
    note.press("Tab")
    expect(page.get_by_text("QA source note: Synthetic owner-provided transparent variant approved for testing.", exact=True)).to_be_visible()
    idle(page)
    confirm=page.get_by_role("checkbox",name="I reviewed this replacement and approve this shared logo change",exact=True)
    expect(confirm).to_be_visible(); expect(confirm).not_to_be_checked()
    return confirm


def restore(page):
    actor=page.get_by_role("textbox",name="Logo editor name",exact=True)
    expect(actor).to_be_visible()
    if not actor.input_value():
        actor_value(page, "Synthetic restore reviewer")
    panel=open_panel(page,"Logo history and restore")
    choose(page,"Saved collection","1")
    expect(page.get_by_text("QA selected history: 1", exact=True)).to_be_visible()
    idle(page)
    confirm=page.get_by_role("checkbox",name="Restore this collection as a new shared version",exact=True)
    expect(confirm).to_be_visible(); check_native(page, "Restore this collection as a new shared version")
    button=page.get_by_role("button",name="Restore logo collection",exact=True)
    expect(button).to_be_enabled(); button.click()


def approve_review(page):
    check_native(page, "I reviewed this replacement and approve this shared logo change")
    # Prove the server accepted this confirmation before testing invalidation.
    expect(page.get_by_role("button", name="Replace selected logo", exact=True)).to_be_enabled()
    idle(page)


def exercise(engine,name,executable=None):
    options={"headless":True}
    if executable and name=="chromium": options["executable_path"]=executable
    browser=engine.launch(**options)
    context=browser.new_context(viewport={"width":1365,"height":900})
    context.add_cookies([{"name":"epc_device_id","value":secrets.token_hex(16),"url":URL}])
    errors=[]; external=[]
    def route(request):
        parsed=urlparse(request.request.url)
        if parsed.scheme in {"data","blob"} or (parsed.hostname=="127.0.0.1" and parsed.port==8520): request.continue_()
        else: external.append(parsed.hostname); request.abort()
    context.route("**/*",route)
    page=context.new_page(); page.set_default_timeout(30000)
    page.on("pageerror",lambda error:errors.append(str(error)))
    record={"errors":errors,"external":external,"stage":"create sample"}
    REPORT["browsers"][name]=record
    out=OUT/name;out.mkdir(parents=True,exist_ok=True)
    stream=BytesIO(); Image.new("RGBA",(240,80),(20,70,40,80)).save(stream,"PNG");raw=stream.getvalue()
    try:
        record["native_pointer_controls"] = native_negative_controls(context)
        page.goto(ROUTE)
        open_panel(page,"Stored-logo recovery sample (synthetic only)")
        page.get_by_role("button",name="Create stored-logo recovery sample",exact=True).click()
        revision(page,2)
        actor=page.get_by_role("textbox",name="Logo editor name",exact=True)
        actor_value(page, "Synthetic browser reviewer")
        record["stage"]="restore readable history"
        restore(page); revision(page,3)
        baseline=page.get_by_text(re.compile(r"^QA selected logo asset: ")).text_content()
        record["stage"]="review and invalidate changed actor"
        confirm=review(page,raw);approve_review(page)
        actor_value(page, "Changed synthetic reviewer")
        expect(confirm).not_to_be_checked()
        approve_review(page)
        note=page.get_by_role("textbox",name="Artwork source and approval",exact=True)
        note.fill("Changed synthetic approval note.");note.press("Tab")
        expect(page.get_by_text("QA source note: Changed synthetic approval note.", exact=True)).to_be_visible()
        idle(page)
        expect(confirm).not_to_be_checked()
        approve_review(page)
        record["stage"]="switch reviewed record"
        choose(page,"Logo to inspect","Synthetic healthy logo")
        expect(page.get_by_text("QA inspected logo: synthetic-control",exact=True)).to_be_visible()
        expect(page.get_by_role("button",name="Replace selected logo",exact=True)).to_have_count(0)
        revision(page,3)
        choose(page,"Logo to inspect","Synthetic recovery logo")
        expect(page.get_by_text("QA inspected logo: synthetic-recovery",exact=True)).to_be_visible()
        record["stage"]="review and save once despite duplicate click"
        confirm=review(page,raw);approve_review(page)
        save=page.get_by_role("button",name="Replace selected logo",exact=True)
        expect(save).to_be_enabled()
        page.screenshot(path=str(out/"before-save.png"),full_page=True)
        save.dblclick()
        revision(page,4)
        replacement=page.get_by_text(re.compile(r"^QA selected logo asset: ")).text_content()
        assert replacement!=baseline
        page.reload();revision(page,4)
        record["stage"]="stale second-tab save after another tab restores"
        stale=context.new_page();stale.set_default_timeout(30000);stale.goto(ROUTE);revision(stale,4)
        old_actor=stale.get_by_role("textbox",name="Logo editor name",exact=True)
        actor_value(stale, "Stale synthetic reviewer")
        stale_confirm=review(stale,raw);approve_review(stale)
        old_save=stale.get_by_role("button",name="Replace selected logo",exact=True)
        expect(old_save).to_be_enabled()
        restore(page);revision(page,5)
        assert page.get_by_text(re.compile(r"^QA selected logo asset: ")).text_content()==baseline
        old_save.click();revision(stale,5)
        assert stale.get_by_text(re.compile(r"^QA selected logo asset: ")).text_content()==baseline
        page.reload();revision(page,5)
        assert page.get_by_text(re.compile(r"^QA selected logo asset: ")).text_content()==baseline
        page.screenshot(path=str(out/"restored-after-stale-save.png"),full_page=True)
        assert not errors and not external
        record.update(result="passed",revision=5)
    except Exception as exc:
        record.update(result="failed",error=type(exc).__name__+": "+str(exc)[:2000])
        page.screenshot(path=str(out/"first-failure.png"),full_page=True)
        raise
    finally:
        (out/"receipt.json").write_text(json.dumps(record,indent=2))
        context.close();browser.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--chromium-only",action="store_true")
    parser.add_argument("--chromium-executable");args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    failures=[]
    with tempfile.TemporaryDirectory(prefix="logo-admin-synthetic-") as temp:
        (Path(temp)/"monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
        env=dict(os.environ,EPC_DATA_DIR=temp,EPC_MONTHLY_DOM_FIXTURE="1",EPC_MONTHLY_LOGO_ADMIN_TASK="1",
            ANTHROPIC_API_KEY="",SMARTSHEET_API_MODE="disabled",PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST",None)
        with (OUT/"streamlit.log").open("w") as log:
            process=subprocess.Popen([sys.executable,"-m","streamlit","run","tests/fixtures/workspaces/monthly_app.py",
                "--server.address","127.0.0.1","--server.port","8520","--server.headless","true","--browser.gatherUsageStats","false"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None: raise RuntimeError("Synthetic server stopped")
                    try:
                        with urllib.request.urlopen(URL+"/_stcore/health",timeout=1) as response:
                            if response.status==200: break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError("Synthetic server not ready")
                with sync_playwright() as playwright:
                    engines=[(playwright.chromium,"chromium")]
                    if not args.chromium_only: engines.append((playwright.webkit,"playwright-webkit"))
                    for engine,name in engines:
                        try: exercise(engine,name,args.chromium_executable)
                        except Exception as exc: failures.append(name+": "+str(exc)[:300])
            finally:
                process.terminate()
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
                REPORT.update(failures=failures,local_chromium_only=args.chromium_only)
                (OUT/"results.json").write_text(json.dumps(REPORT,indent=2))
    if failures: raise AssertionError("Native single-logo admin failed: "+"; ".join(failures))


if __name__=="__main__": main()
