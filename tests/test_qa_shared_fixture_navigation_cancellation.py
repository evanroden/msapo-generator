"""A canceled old image during an explicit WebKit reload is not a live app error.

The strict exception never suppresses a current visible preview failure or a
browser error during import/edit/generation. Report contents and journal checks
still run to completion independently of this classification.
"""

import pytest

from scripts.qa_shared_fixture_testing import _navigation_decode_cancel


def test_only_the_identical_webkit_decode_cancel_during_our_primary_reload_is_separate():
    assert _navigation_decode_cancel(
        "playwright-webkit", "primary", "manual-edit: browser reload", True,
        "EncodingError: Loading was canceled.")
    assert _navigation_decode_cancel(
        "playwright-webkit", "primary", "reentry: browser reload", True,
        "EncodingError: Loading was canceled.")


@pytest.mark.parametrize(("engine", "role", "stage", "in_reload", "message"), [
    ("chromium", "primary", "manual-edit: browser reload", True, "EncodingError: Loading was canceled."),
    ("playwright-webkit", "coworker", "manual-edit: browser reload", True, "EncodingError: Loading was canceled."),
    ("playwright-webkit", "primary", "manual-edit: browser reload", False, "EncodingError: Loading was canceled."),
    ("playwright-webkit", "primary", "enter ordered editor", True, "EncodingError: Loading was canceled."),
    ("playwright-webkit", "primary", "manual-edit: loaded and idle", True, "EncodingError: Loading was canceled."),
    ("playwright-webkit", "primary", "manual-edit: browser reload", True, "TypeError: Failed to fetch"),
    ("playwright-webkit", "primary", "manual-edit: browser reload", True, "EncodingError: Failed to decode image."),
    ("playwright-webkit", "primary", "manual-edit: browser reload", True, "EncodingError: Loading was canceled by a server error."),
])
def test_real_application_errors_and_non_navigation_activity_still_fail(
        engine, role, stage, in_reload, message):
    assert not _navigation_decode_cancel(engine, role, stage, in_reload, message)
