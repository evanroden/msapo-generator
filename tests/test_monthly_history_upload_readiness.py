"""Exercise the real History upload helper's ordering without launching a browser."""
import ast
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from PIL import Image, ImageDraw
import pytest


def upload_helper(namespace):
    source = Path(__file__).resolve().parents[1] / "scripts/qa_monthly_history.py"
    tree = ast.parse(source.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"photo", "add_photo"}]
    namespace.update(Image=Image, ImageDraw=ImageDraw, BytesIO=BytesIO)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["add_photo"]


def run_upload(number, blocked=None):
    page, activity, intake, uploader, file_input, add = (Mock() for _ in range(6))
    page.locator.side_effect = lambda selector: activity if selector == ".st-key-epc_pair_monthly_activity" else Mock()
    activity.get_by_test_id.side_effect = lambda name: {"stExpander": intake, "stFileUploader": uploader}[name]
    intake.filter.return_value = intake
    intake.evaluate.return_value = True
    uploader.filter.return_value = uploader
    uploader.locator.return_value = file_input
    activity.get_by_role.return_value = add
    expected = [f"synthetic-history-photo-{index}.png" for index in range(1, number + 1)]
    seen, events = [], []
    spinner_complete = False
    server_ready = False

    def selected(payload):
        assert payload["name"] == expected[-1]
        assert payload["mimeType"] == "image/png"
        assert payload["buffer"].startswith(b"\x89PNG\r\n\x1a\n")
        events.append("selected")
    file_input.set_input_files.side_effect = selected
    uploader.get_by_title.side_effect = lambda title, exact: ("title", title, exact)
    uploader.get_by_test_id.side_effect = lambda name: ("testid", name)

    def expectation(locator):
        assertion = Mock()
        def visible(**kwargs):
            assert events[0] == "selected"
            assert locator[0] == "title" and locator[2] is True
            assert locator[1] in expected
            if blocked == "missing chip" and locator[1] == expected[-1]:
                raise AssertionError("missing chip")
            seen.append(locator[1])
        def count(value, **kwargs):
            nonlocal spinner_complete
            assert locator == ("testid", "stFileChipIconSpinner") and value == 0
            assert seen == expected
            if blocked == "pending upload":
                raise AssertionError("pending upload")
            spinner_complete = True
            events.append("native upload complete")
        assertion.to_be_visible.side_effect = visible
        assertion.to_have_count.side_effect = count
        return assertion

    def state(actual_page, identity, **wanted):
        nonlocal server_ready
        assert actual_page is page and identity == "isolated-scope"
        if "after" in wanted:
            assert wanted == {"after": 10} and seen == expected and spinner_complete
            if blocked == "stale receipt":
                raise AssertionError("stale receipt")
            server_ready = True
            events.append("fresh durable idle receipt")
            return {"sequence": 11}
        assert wanted == {"photos": number} and add.click.call_count == 1
        events.append("exact committed photo receipt")
        return {"photos": number}

    def click():
        assert seen == expected and spinner_complete and server_ready, "native inputs not ready"
        events.append("single Add click")
    add.click.side_effect = click
    helper = upload_helper({"expect": expectation, "receipt": lambda actual_page: {"sequence": 10},
                            "await_state": state})
    if blocked:
        with pytest.raises(AssertionError, match=blocked):
            helper(page, number, "isolated-scope")
        assert add.click.call_count == 0
    else:
        assert helper(page, number, "isolated-scope") == {"photos": number}
        assert events == ["selected", "native upload complete", "fresh durable idle receipt",
                          "single Add click", "exact committed photo receipt"]
        assert add.click.call_count == 1


@pytest.mark.parametrize("number", [1, 2])
def test_add_waits_for_all_native_files_and_fresh_server_receipt(number):
    run_upload(number)


@pytest.mark.parametrize("blocked", ["missing chip", "pending upload", "stale receipt"])
def test_incomplete_upload_never_delivers_the_first_add_gesture(blocked):
    run_upload(2, blocked)
