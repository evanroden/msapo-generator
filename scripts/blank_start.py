"""Detect and recover a blank first page in browser journeys, on the record.

Kept free of Playwright imports so its unit tests run in the ordinary test
environment, which installs no browser packages.
"""
import time

# The Streamlit front end mounts this root before its session connects. A
# page that stays without it is a blank start: the server answered its health
# check but the browser never ran the app's front end.
APP_ROOT = '[data-testid="stApp"]'
BLANK_START_SECONDS = 30


def open_app(page, url, diagnostics, *, clock=time.perf_counter):
    """Open the app; reload once, on the record, if the front end never mounts.

    Returns (reloads, started). started is the clock reading taken just before
    the navigation that produced the page in use, so a recovered sample is timed
    from its reload exactly as a normal sample is timed from its first load. A
    second blank start is not retried: the journey's next wait fails.
    """
    started = clock()
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.locator(APP_ROOT).wait_for(state="attached", timeout=BLANK_START_SECONDS * 1000)
        return 0, started
    except Exception:
        diagnostics["blank_starts"].append({
            "ready_state": page.evaluate("() => document.readyState"),
            "body_children": page.evaluate("() => document.body ? document.body.children.length : -1"),
            "aborted_requests": list(diagnostics["aborted_requests"]),
            "failed_requests": list(diagnostics["failed_requests"]),
            "page_errors": list(diagnostics["page_errors"]),
            "console_errors": list(diagnostics["console_errors"])})
        started = clock()
        page.reload(wait_until="domcontentloaded")
        return 1, started
