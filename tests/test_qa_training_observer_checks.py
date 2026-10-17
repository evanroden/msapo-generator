"""Native errors stay terminal even when the final page and pageerror are clean."""
from copy import deepcopy

import pytest

from scripts.qa_training_observer_checks import require_no_native_window_errors


def document(stage, *errors):
    return {"stage": stage, "evidence": {"installation": "installed", "errors": list(errors)}}


@pytest.mark.parametrize("documents", [
    [],
    [{"stage": "final", "evidence": None}],
    [{"stage": "final", "evidence": {"errors": []}}],
    [{"stage": "final", "evidence": {"installation": "native-feature-branch-would-change", "errors": []}}],
    [{"stage": "final", "evidence": {"installation": "installed"}}],
    [document("final"), {"stage": "earlier", "error": "Capture failed"}],
])
def test_missing_native_instrumentation_cannot_pass_as_error_free(documents):
    with pytest.raises(AssertionError, match="instrumentation"):
        require_no_native_window_errors(documents)


def test_earlier_native_error_is_not_erased_by_clean_reload_or_empty_pageerror():
    observed = [
        document("before-added-session-reload", {
            "at": 6609.1, "message": "ResizeObserver loop completed with undelivered notifications.",
            "nativeEvents": [],
        }),
        document("before-removed-session-reload"),
        document("final"),
    ]
    retained = deepcopy(observed)
    pageerror = []
    assert not pageerror
    with pytest.raises(AssertionError, match="before-added-session-reload.*ResizeObserver"):
        require_no_native_window_errors(observed)
    assert observed == retained


def test_final_document_native_error_is_also_terminal_without_message_whitelist():
    with pytest.raises(AssertionError, match="Unrelated native error"):
        require_no_native_window_errors([
            document("before-added-session-reload"),
            document("final", {"message": "Unrelated native error"}),
        ])


def test_clean_native_documents_do_not_invent_a_failure():
    require_no_native_window_errors([
        document("before-added-session-reload"),
        document("before-removed-session-reload"),
        document("final"),
    ])
