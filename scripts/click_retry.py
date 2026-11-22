"""Click again only when a harmless click's result never appeared.

Kept free of Playwright imports so its unit tests run in the ordinary test
environment, which installs no browser packages.
"""

ATTEMPTS = 3


def click_until_shown(click, shown, *, attempts=ATTEMPTS, report=print):
    """Click, wait for the result, and click again only if it never appeared.

    Only for a control whose repeat changes nothing, such as the issue
    gallery's Preview button, which sets the page to preview. Under the
    0.5-CPU container a rerun can move the button between pointer down and
    pointer up, and the click is lost: the button stays on screen, unclicked
    (21 Nov, capped Chromium on main 8a6cd19b and on #955). `shown()` waits
    for the result and returns whether it appeared. Returns the clicks taken;
    a result that never appears still fails.
    """
    for attempt in range(1, attempts + 1):
        click()
        if shown():
            return attempt
        if attempt < attempts:
            report(f"RETRY click: its result did not appear after click {attempt}")
    raise AssertionError(f"The result did not appear after {attempts} clicks.")
