"""Actual Chromium/WebKit capital native row, persistence and Word/PDF journey."""
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "native-capital-rows"
PORT = 8546
URL = f"http://127.0.0.1:{PORT}"
NAME = "data-native-capital-receipt"
MARKER = "CAP-NATIVE-ROW-301"

def settled(page, *, key=None, primary=None, imported=None, contains=None,
            saved=False, revision=None):
    # A previous receipt can still be visible immediately after a native
    # click. Require the expected authoritative transition, not merely idle.
    # NOTE: use loose `!= null` below, not `!== null`. Playwright drops
    # None-valued keys from the arg passed to wait_for_function, so an
    # unset optional arrives as `undefined`, not `null`; `!== null` would
    # treat "no check requested" as a check that can never pass.
    page.wait_for_function("""args => {
      const node=document.querySelector('[' + args.name + ']');
      if (!node || document.querySelector('[data-testid=stApp]')
          ?.getAttribute('data-test-script-state')!=='notRunning') return false;
      const data=JSON.parse(node.getAttribute(args.name));
      if (args.key) {
        const block=data.working?.[args.key];
        if (!block) return false;
        if (args.primary != null && block.rows.length !== args.primary) return false;
        if (args.imported != null &&
            block.extra?.[0]?.rows.length !== args.imported) return false;
        if (args.contains && !JSON.stringify(block).includes(args.contains)) return false;
      }
      if (args.saved && JSON.stringify(data.working)!==JSON.stringify(data.saved)) return false;
      if (args.revision != null && data.revision!==args.revision) return false;
      return true;
    }""", arg={"name": NAME, "key":key,"primary":primary,
               "imported":imported,"contains":contains,"saved":saved,
               "revision":revision}, timeout=35000)
    assert page.get_by_test_id("stException").count() == 0
    return json.loads(page.locator("[" + NAME + "]").get_attribute(NAME))

def inspect_files(word, pdf):
    from docx import Document
    import pymupdf
    doc=Document(BytesIO(word))
    tables=[tuple(tuple(cell.text for cell in row.cells) for row in table.rows)
            for table in doc.tables]
    table=next(t for t in tables if any(MARKER in row for row in t))
    assert table[0] == ("Asset", "Decision", "Decision", "")
    assert ("CAP-001", "[Pump](https://example.invalid) **Review**",
            MARKER, "Unnamed value") in table
    flat="\n".join(cell for table in tables for row in table for cell in row)
    assert flat.count(MARKER) == 1 and "Second unnamed" in flat
    with pymupdf.open(stream=pdf, filetype="pdf") as output:
        text=" ".join(" ".join(page.get_text().split()) for page in output)
        assert text.count(MARKER) == 1 and "CAP-002" in text
        pages=len(output)
    return {"docx_sha256": sha256(word).hexdigest(),
            "pdf_sha256": sha256(pdf).hexdigest(), "pages": pages}

def exercise(browser, name):
    from playwright.sync_api import expect
    path=OUT/name
    path.mkdir(parents=True, exist_ok=True)
    context=browser.new_context(viewport={"width":1280,"height":900},accept_downloads=True)
    context.add_cookies([{"name":"epc_device_id","value":secrets.token_hex(16),"url":URL}])
    report={"browser":name,"physical_device":False,"passed":False,"external":[],"page_errors":[]}
    def route(request):
        if urlparse(request.request.url).hostname in {"localhost","127.0.0.1"}:
            request.continue_()
        else:
            report["external"].append(request.request.url)
            request.abort()
    context.route("**/*",route)
    context.tracing.start(screenshots=True,snapshots=True)
    page=context.new_page()
    page.on("pageerror",lambda error:report["page_errors"].append(str(error)))
    try:
        page.goto(URL,wait_until="domcontentloaded")
        initial=settled(page, key="capital_renewal", primary=1, imported=2)
        assert len(initial["working"]["capital_renewal"]["rows"]) == 1
        capital=page.locator(".st-key-native_capital_renewal")
        end=page.locator(".st-key-native_end_of_life")
        assert capital.locator('[data-testid="stDataFrame"]').count()==0
        assert capital.locator('a[href="https://example.invalid"]').count()==0
        assert "Priority: High" in capital.inner_text()
        assert "Expected replacement timing: 2030" in end.inner_text()
        # Clear the final primary row and switch directly to an imported card.
        capital.get_by_role("button",name="Edit capital item",exact=True).last.click()
        capital.get_by_role("textbox",name="Facility",exact=True).fill("")
        capital.get_by_role("textbox",name="Priority",exact=True).fill("")
        capital.get_by_role("textbox",name="Recommendation",exact=True).fill("")
        # The last cleared field only submits on blur. Tab out and wait for
        # the row to drop first; switching editors immediately can capture
        # the row before the final clear arrives and the row survives.
        page.keyboard.press("Tab")
        settled(page, key="capital_renewal", primary=0, imported=2)
        capital.get_by_role("button",name="Edit capital item",exact=True).first.click()
        decisions=capital.get_by_role("textbox",name="Decision",exact=True)
        expect(decisions).to_have_count(2)
        decisions.nth(1).fill(MARKER)
        capital.get_by_role("button",name="Close editing",exact=True).click()
        state=settled(page, key="capital_renewal", primary=0, imported=2, contains=MARKER)["working"]["capital_renewal"]
        assert state["rows"] == []
        assert state["extra"][0]["columns"] == ["Asset","Decision","Decision",""]
        assert state["extra"][0]["rows"][0][2] == MARKER
        assert state["extra"][0]["reference"] == "synthetic-capital-table"
        # A separate rerender must not switch the imported editor back to grid.
        capital.get_by_role("button",name="Edit capital item",exact=True).first.click()
        expect(capital.get_by_role("textbox",name="Decision",exact=True).nth(1)).to_have_value(MARKER)
        capital.get_by_role("button",name="Close editing",exact=True).click()
        # Remove/Undo retains only the removed imported sibling.
        capital.get_by_role("button",name="Remove capital item",exact=True).last.click()
        assert len(settled(page, key="capital_renewal", imported=1)["working"]["capital_renewal"]["extra"][0]["rows"]) == 1
        capital.get_by_role("button",name="Undo last removal",exact=True).click()
        recovered=settled(page, key="capital_renewal", imported=2, contains=MARKER)["working"]["capital_renewal"]
        assert len(recovered["extra"][0]["rows"]) == 2
        assert recovered["extra"][0]["rows"][0][2] == MARKER
        # Existing replacement schema with type=date still accepts a year.
        end.get_by_role("button",name="Edit replacement item",exact=True).last.click()
        timing=end.get_by_role("textbox",name="Expected replacement timing",exact=True)
        assert timing.get_attribute("type") == "text"
        timing.fill("2029")
        end.get_by_role("button",name="Close editing",exact=True).click()
        assert settled(page, key="end_of_life", contains='"2029"')["working"]["end_of_life"]["rows"][0][-1] == "2029"
        page.get_by_role("button",name="Save synthetic report",exact=True).click()
        saved=settled(page, key="capital_renewal", primary=0, imported=2, contains=MARKER, saved=True, revision=1)
        assert saved["working"] == saved["saved"] and saved["revision"] == 1
        page.screenshot(path=str(path/"desktop-saved.png"),full_page=True)
        page.set_viewport_size({"width":545,"height":757})
        page.reload(wait_until="domcontentloaded")
        reopened=settled(page, key="capital_renewal", primary=0, imported=2, contains=MARKER, saved=True, revision=1)
        assert reopened["working"] == saved["working"]
        capital=page.locator(".st-key-native_capital_renewal")
        capital.get_by_role("button",name="Edit capital item",exact=True).first.click()
        expect(capital.get_by_role("textbox",name="Decision",exact=True).nth(1)).to_have_value(MARKER)
        capital.get_by_role("button",name="Close editing",exact=True).click()
        page.screenshot(path=str(path/"narrow-reopen.png"),full_page=True)
        page.get_by_role("button",name="Generate synthetic Word and PDF",exact=True).click()
        files={}
        for kind,extension in (("Word","docx"),("PDF","pdf")):
            button=page.get_by_role("button",name="Download synthetic "+kind,exact=True)
            expect(button).to_be_visible(timeout=90000)
            with page.expect_download(timeout=90000) as event:button.click()
            target=path/("capital."+extension)
            event.value.save_as(target)
            files[extension]=target.read_bytes()
        report["output"]=inspect_files(files["docx"],files["pdf"])
        assert not report["page_errors"] and not report["external"]
        report["passed"]=True
    except Exception as error:
        report["failure"]={"message":str(error)[:2000],"traceback":traceback.format_exc()[-5000:]}
        try:
            page.screenshot(path=str(path/"first-failure.png"),full_page=True)
            (path/"first-failure.html").write_text(page.content())
        except Exception:pass
        raise
    finally:
        (path/"result.json").write_text(json.dumps(report,indent=2))
        context.tracing.stop(path=str(path/"trace.zip"))
        context.close()

def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-capital-synthetic-") as root:
        base=Path(root)
        (base/"monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
        env=dict(os.environ,EPC_DATA_DIR=str(base),EPC_MONTHLY_DOM_FIXTURE="1",
                 EPC_NATIVE_CAPITAL_FIXTURE="1",ANTHROPIC_API_KEY="",
                 SMARTSHEET_API_MODE="disabled",STREAMLIT_GLOBAL_DEVELOPMENT_MODE="false")
        with (OUT/"streamlit.log").open("w") as log:
            process=subprocess.Popen([sys.executable,"-m","streamlit","run",
                "scripts/fixtures/native_capital_rows_app.py",
                "--server.address","127.0.0.1","--server.port",str(PORT),
                "--server.headless","true","--browser.gatherUsageStats","false"],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError("Native fixture server exited")
                    try:
                        with urlopen(URL+"/_stcore/health",timeout=1) as res:
                            if res.status == 200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError("Native fixture server did not become healthy")
                failures=[]
                with sync_playwright() as playwright:
                    for engine in ("chromium","webkit"):
                        browser=getattr(playwright,engine).launch(headless=True)
                        try:exercise(browser,engine)
                        except Exception as error:failures.append(engine+": "+str(error))
                        finally:browser.close()
                if failures:raise AssertionError("; ".join(failures))
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    print("PASS native capital cards Chromium/WebKit, save/reopen and real DOCX/PDF")

if __name__=="__main__":main()
