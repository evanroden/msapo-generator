"""Native image review retains its caption, controls and owner across reruns."""
import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_caption_adapter_is_owned_by_the_same_native_image_after_rerun():
    app = AppTest.from_file(str(ROOT / "tests/fixtures/workspaces/import_picture_alt_app.py")).run()
    assert not app.exception
    before = [entry.proto.json for entry in app.get("bidi_component")]
    assert len(before) == 2 and all("monthly_import_picture_" in value for value in before)
    assert len(app.get("image")) == 3
    app.button[0].click().run()
    assert not app.exception
    assert [entry.proto.json for entry in app.get("bidi_component")] == before
    assert len(app.get("image")) == 3


def test_display_only_description_adapter():
    result = subprocess.run(["node", "--test", "tests/import_picture_accessibility_test.cjs"],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_caption_update_uses_the_visible_checkbox_label():
    driver = (ROOT / "scripts/qa_import_picture_alt.py").read_text()
    # Streamlit intentionally clips the accessible input to 1px. Keep the
    # ordinary label pointer gesture and checked-state receipt before asserting
    # the updated image name; never force a click on the hidden input.
    start = driver.index('checkbox = page.get_by_role("checkbox", name="Use updated caption", exact=True)')
    end = driver.index('expect(first).to_have_attribute("alt", "Updated synthetic pump inspection · Image-only")')
    gesture = driver[start:end]
    required = (
        'expect(checkbox).to_have_count(1)',
        'expect(checkbox).not_to_be_checked()',
        'label = checkbox.locator("xpath=ancestor::label")',
        'expect(label).to_have_count(1)',
        'expect(label.get_by_role("checkbox")).to_have_count(1)',
        'expect(label).to_be_visible()',
        'label.click()',
        'expect(checkbox).to_be_checked()',
    )
    positions = [gesture.index(item) for item in required]
    assert positions == sorted(positions)
    assert gesture.count('.click(') == 1
    for forbidden in ('.check(', 'force=', '.evaluate(', '.dispatch_event(', '.press(', 'sleep(', 'wait_for_timeout('):
        assert forbidden not in gesture


@pytest.mark.parametrize(("address", "allowed"), [
    ("http://127.0.0.1:8561/_stcore/health", True),
    ("http://127.0.0.1:8561/media/synthetic.jpg", True),
    ("blob:http://127.0.0.1:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0", True),
    ("blob:http://127.0.0.1:8561/not-a-uuid", False),
    ("blob:http://127.0.0.1:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0?x=1", False),
    ("blob:http://127.0.0.1:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0#fragment", False),
    ("blob:http://127.0.0.1:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0;params", False),
    ("blob:http://127.0.0.1:8561//d7d4c664-daf7-45cc-a084-ee86312a68c0", False),
    ("blob:http://127.0.0.1:8562/d7d4c664-daf7-45cc-a084-ee86312a68c0", False),
    ("blob:https://127.0.0.1:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0", False),
    ("blob:http://example.com:8561/d7d4c664-daf7-45cc-a084-ee86312a68c0", False),
    ("http://127.0.0.1:8562/", False),
    ("https://127.0.0.1:8561/", False),
    ("http://user:password@127.0.0.1:8561/", False),
    ("http://127.0.0.1:invalid/", False),
    ("http://127.0.0.1.evil:8561/", False),
    ("https://example.com/", False),
    ("data:text/javascript,export default 1", False),
    ("file:///tmp/synthetic.js", False),
])
def test_actual_browser_guard_allows_only_its_server_and_native_blob_modules(address, allowed):
    from scripts.qa_workflow_shell_width import local_url

    # Exercise the actual registered route callback independently of a browser
    # install. No copied allow-list can conceal a different hosted guard.
    driver = ROOT / "scripts/qa_import_picture_alt.py"
    parsed = ast.parse(driver.read_text())
    guard = next(node for node in ast.walk(parsed)
                 if isinstance(node, ast.FunctionDef) and node.name == "guard")
    port = next(node.value for node in parsed.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "PORT" for target in node.targets))
    namespace = dict(urlparse=urlparse, local_url=local_url, PORT=ast.literal_eval(port), external=[])
    exec(compile(ast.Module(body=[guard], type_ignores=[]), str(driver), "exec"), namespace)
    decisions = []
    route = SimpleNamespace(request=SimpleNamespace(url=address),
                            continue_=lambda: decisions.append("allow"),
                            abort=lambda: decisions.append("reject"))
    namespace["guard"](route)
    assert decisions == ["allow" if allowed else "reject"]
    assert namespace["external"] == ([] if allowed else [address])


def _picture_job(text):
    from test_ci_native_test_budget import parse_jobs, validate_workflow

    # Existing native jobs retain their original steps and aggregate deadlines.
    validate_workflow(text)
    chunks = parse_jobs(text)["import-picture-alt"]
    job = "".join(chunks)
    assert "    timeout-minutes: 30\n" in chunks[0]
    assert "    if:" not in chunks[0] and "continue-on-error" not in job
    assert "needs:" not in chunks[0]
    setup = next(step for step in chunks if "name: Install locked app" in step)
    for command in ("python -m pip install -r requirements-dev.lock",
                    "python scripts/patch_streamlit_frontend.py",
                    "python -m pip install playwright==1.58.0",
                    "python -m playwright install --with-deps chromium webkit"):
        assert command in setup
    assert "timeout-minutes: 20" in setup
    assert job.count("scripts/ci_native_test_budget.py --minutes 5") == 1
    assert job.count("python scripts/qa_import_picture_alt.py") == 1
    run = next(step for step in chunks if "python scripts/qa_import_picture_alt.py" in step)
    assert "timeout-minutes: 6" in run
    assert run.split("<<'NATIVE_TEST'\n", 1)[1].strip() == (
        "python scripts/qa_import_picture_alt.py\n          NATIVE_TEST")
    upload = next(step for step in chunks if "upload-artifact" in step)
    for value in ("if: always()", "timeout-minutes: 3",
                  "path: test-artifacts/import-picture-alt/", "retention-days: 7"):
        assert value in upload


def test_picture_descriptions_have_an_independent_mandatory_browser_budget():
    text = (ROOT / ".github/workflows/adaptive-workspaces.yml").read_text()
    _picture_job(text)
    assert text.count("python scripts/qa_import_picture_alt.py") == 1
    driver = (ROOT / "scripts/qa_import_picture_alt.py").read_text()
    assert '("chromium", playwright.chromium)' in driver
    assert '("webkit", playwright.webkit)' in driver


@pytest.mark.parametrize(("old", "new"), [
    ("--minutes 5", "--minutes 10"),
    ("timeout-minutes: 6", "timeout-minutes: 11"),
    ("chromium webkit", "chromium"),
    ("python scripts/qa_import_picture_alt.py", "true"),
    ("if: always()", "if: success()"),
])
def test_picture_job_rejects_lost_coverage_or_changed_deadline(old, new):
    text = (ROOT / ".github/workflows/adaptive-workspaces.yml").read_text()
    before, picture = text.split("  import-picture-alt:\n", 1)
    picture, after = picture.split("  synthetic-progress-photos:\n", 1)
    assert old in picture
    with pytest.raises((AssertionError, StopIteration)):
        _picture_job(before + "  import-picture-alt:\n" + picture.replace(old, new)
                     + "  synthetic-progress-photos:\n" + after)
