"""Local actual-PO DOM checks. Segment injection is simulation, never hardware proof."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "po-adaptive"
URL = "http://127.0.0.1:8519"
REPORT = {"synthetic_only": True, "native_hardware": False, "checks": [], "geometry": {}}


def check(name, value, detail=None):
    REPORT["checks"].append({"name": name, "passed": bool(value), "detail": detail})
    if not value:
        raise AssertionError(name + ": " + str(detail))


def settle(page, mode):
    page.wait_for_function("mode => document.querySelector('.epc-workspace')?.dataset.epcMode === mode", arg=mode)
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def inject(page, segments):
    page.evaluate("""segments => {
        Object.defineProperty(window, 'viewport', {configurable:true,value:{segments}});
        window.dispatchEvent(new Event('resize'));
    }""", segments)


def geometry(page):
    return page.locator(".epc-workspace").evaluate("""root => ({
        mode:root.dataset.epcMode,root:root.getBoundingClientRect().toJSON(),
        pairs:[...root.querySelectorAll('.epc-workspace-pair')].map(pair=>({
            id:pair.querySelector('[data-epc-pair]').dataset.epcPair, active:pair.dataset.epcActive,
            pair:pair.getBoundingClientRect().toJSON(),
            preview:pair.querySelector('.epc-workspace-reference').getBoundingClientRect().toJSON(),
            top:parseFloat(getComputedStyle(pair.querySelector('.epc-workspace-reference')).top)
        }))})""")


def capture(page, browser, name):
    observed = geometry(page)
    REPORT["geometry"][browser + "-" + name] = observed
    page.screenshot(path=str(OUT / (browser + "-" + name + ".png")))
    return observed


def exercise(engine, name):
    browser = engine.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":900})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(URL) else route.abort())
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_selector(".st-key-epc_pair_purchase_review")
    settle(page, "wide")
    for label in ("Review scope, inclusions, and exclusions", "Change a value the tool already filled"):
        page.get_by_text(label, exact=True).click()
    review = page.locator(".st-key-epc_pair_purchase_review")
    package = page.locator(".st-key-epc_pair_purchase_package")
    scope = page.get_by_label("Scope of Work", exact=True)
    review.locator('img[alt^="Original quote — page "]').first.wait_for()
    check(name + " exactly one authoritative scope editor", scope.count() == 1)
    page.locator('[data-testid="stMain"]').evaluate("node => {node.scrollTop=650}")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    wide = capture(page, name, "wide-source")
    check(name + " source pins within long review", abs(wide["pairs"][0]["preview"]["top"] - wide["pairs"][0]["top"]) <= 3, wide["pairs"][0])
    scope.click()
    scope.fill("Synthetic typing without blur; preserve this through book and tabletop.")
    scope.evaluate("node=>node.setSelectionRange(10,16)")
    before = scope.evaluate("node=>({text:node.value,start:node.selectionStart,end:node.selectionEnd})")
    inject(page, [{"x":0,"y":0,"width":650,"height":900},{"x":690,"y":0,"width":750,"height":900}])
    settle(page, "book")
    book = capture(page, name, "book")
    check(name + " asymmetric book clearance", book["pairs"][0]["preview"]["left"] >= 693, book["pairs"][0])
    inject(page, [{"x":0,"y":0,"width":1440,"height":380},{"x":0,"y":410,"width":1440,"height":490}])
    settle(page, "tabletop")
    table = capture(page, name, "tabletop-review")
    active = [pair for pair in table["pairs"] if pair["active"] == "true"]
    check(name + " one upper matching source", len(active) == 1 and active[0]["id"] == "purchase_review" and active[0]["preview"]["bottom"] <= 383, active)
    check(name + " lower work surface", table["root"]["top"] >= 413 and table["root"]["bottom"] <= 903, table["root"])
    after = scope.evaluate("node=>({text:node.value,start:node.selectionStart,end:node.selectionEnd})")
    check(name + " exact unblurred value and selection retained", before == after, after)
    check(name + " focus retained", scope.evaluate("node=>node===document.activeElement"))
    inject(page, None); settle(page, "wide")
    requester = page.get_by_label("Your name (Requester / Asset Manager) *", exact=True)
    requester.fill("Synthetic Browser Reviewer"); requester.press("Tab")
    page.get_by_role("button", name="Generate both files and Smartsheet link", exact=True).click()
    page.get_by_text("Synthetic generation count: 1", exact=True).wait_for()
    package.locator('img[alt^="Generated MSAPO — page "]').first.wait_for()
    package.get_by_label("Compare original quote", exact=True).check()
    package.locator('img[alt^="Original quote — page "]').first.wait_for()
    package.get_by_label("Compare original quote", exact=True).uncheck()
    package.locator('img[alt^="Generated MSAPO — page "]').first.wait_for()
    check(name + " view comparison never generates", page.get_by_text("Synthetic generation count: 1", exact=True).count() == 1)
    inject(page, [{"x":0,"y":0,"width":1440,"height":380},{"x":0,"y":410,"width":1440,"height":490}])
    settle(page, "tabletop")
    page.locator(".epc-workspace").evaluate("""root=>{
       const pair=root.querySelector('.st-key-epc_pair_purchase_package');
       root.scrollTop+=pair.getBoundingClientRect().top-root.getBoundingClientRect().top+70;
    }""")
    page.wait_for_function("document.querySelector('.st-key-epc_pair_purchase_package').dataset.epcActive==='true'")
    capture(page, name, "tabletop-package")
    inject(page, None); settle(page, "wide")
    page.set_viewport_size({"width":390,"height":844}); settle(page, "compact")
    check(name + " compact reflow", page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+2"))
    package.get_by_role("button", name="View preview", exact=True).click()
    check(name + " local preview opens", package.locator(".epc-workspace-reference").is_visible())
    package.get_by_role("button", name="Back to editing", exact=True).click()
    check(name + " local editing return", package.locator(".epc-workspace-reference").is_hidden())
    capture(page, name, "compact")
    check(name + " no browser errors", not errors, errors)
    browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="po-adaptive-synthetic-") as temp:
        env = dict(os.environ, **{k:v for k,v in dotenv_values(ROOT / ".env.example").items() if v is not None})
        env.update(EPC_DATA_DIR=temp, ANTHROPIC_API_KEY="test-key-not-used", SMARTSHEET_API_MODE="disabled")
        log = (OUT / "streamlit.log").open("w")
        process = subprocess.Popen([sys.executable,"-m","streamlit","run","tests/fixtures/workspaces/po_app.py","--server.address","127.0.0.1","--server.port","8519","--server.headless","true","--browser.gatherUsageStats","false"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError("Synthetic PO app stopped")
                try:
                    with urllib.request.urlopen(URL + "/_stcore/health", timeout=1) as response:
                        if response.status == 200: break
                except OSError: pass
                time.sleep(.1)
            with sync_playwright() as p:
                exercise(p.chromium, "chromium")
                exercise(p.webkit, "playwright-webkit")
        finally:
            process.terminate(); process.wait(timeout=15); log.close()
            (OUT / "geometry-and-results.json").write_text(json.dumps(REPORT, indent=2))


if __name__ == "__main__": main()
