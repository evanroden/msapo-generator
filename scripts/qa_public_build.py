"""Observe the public exact-build marker through the ordinary About disclosure."""

import re


def running_code_marker(page, *, timeout=16000):
    """Support prior visible footers and the current quiet About disclosure.

    Opening About is read-only UI navigation. No route, session, report action,
    rendering rule or access boundary is changed to obtain the running SHA.
    """
    marker = page.get_by_text(re.compile(r"^Running code:")).first
    marker.wait_for(state="attached", timeout=timeout)
    if not marker.is_visible():
        about = page.get_by_test_id("stExpander").filter(
            has=page.get_by_text("About", exact=True)).first
        about.locator("summary").click(timeout=timeout)
    marker.wait_for(state="visible", timeout=timeout)
    return marker
