"""Execute the actual pinned initializer and verify immutable client upgrades."""
from pathlib import Path
import json
import re
import subprocess

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat
from scripts.streamlit_text_input_default import (
    TEXT_INPUT_BUNDLE, ORIGINAL, REPAIRED, repair_text_input_default,
)
from test_streamlit_frontend_compat import bundle, files


def native():
    return (Path(streamlit.__file__).parent / "static/static/js" / TEXT_INPUT_BUNDLE).read_bytes()


def initializer(raw):
    source = raw.decode()
    start = source.index("()=>k(i,t)")
    end = source.index(",{width:", start)
    return source[start:end - 1]  # Remove useState's closing parenthesis.


def test_actual_native_initializer_has_saved_text_before_effects_or_focus():
    raw = native()
    repaired = repair_text_input_default(raw)
    source = raw.decode()
    helpers = source[source.index("function k("):source.index("function M(")]
    code = r'''
const assert=require('node:assert/strict'), data=JSON.parse(process.argv[1]);
const initial=(source,stored,proto)=>new Function('i','t',data.helpers+';return ('+source+')()')
 ({getStringValue:()=>stored},proto);
assert.equal(initial(data.before,undefined,{default:'555-0100'}),null);
assert.equal(initial(data.after,undefined,{default:'555-0100'}),'555-0100');
assert.equal(initial(data.after,undefined,{default:'old',value:'current',setValue:true}),'current');
for (const stored of ['', 'delivered edit', '東京 555-0100']) {
 assert.equal(initial(data.after,stored,{default:'old',value:'server',setValue:true}),stored);
}
assert.equal(initial(data.after,undefined,{default:'',value:'ignored'}),'');
assert.equal(initial(data.after,undefined,{default:'saved',value:'ignored',setValue:false}),'saved');
assert.equal(initial(data.after,undefined,{}),null);
'''
    run = subprocess.run(["node", "-e", code, json.dumps({
        "before": initializer(raw), "after": initializer(repaired), "helpers": helpers,
    })], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr


def test_only_first_state_initializer_changes_and_unknown_bytes_are_rejected():
    raw = native()
    repaired = repair_text_input_default(raw)
    assert repaired.count(REPAIRED) == 1
    assert repaired.replace(REPAIRED, ORIGINAL, 1) == raw
    # All native event handlers, UI state synchronization and form submission
    # stay byte-for-byte identical; blank edits still have precedence.
    for altered in (raw + b" ", repaired, raw.replace(ORIGINAL, b"")):
        with pytest.raises(RuntimeError, match="Unexpected locked text-input"):
            repair_text_input_default(altered)


@pytest.mark.parametrize("scalar_date", [False, True])
def test_existing_tab_navigation_generation_upgrades_without_losing_edits_or_assets(bundle, scalar_date):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, scalar_date, text_input_default=False)
    for name, raw in old.payloads.items():
        (scripts / old.names[name]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    before = files(root)
    assert not compat.selected_frontend(root)["text_input_default"]
    new = compat.patch_bundle(root, installed_version="1.61.1")
    assert new["text_input_default"] and new["tab_navigation"]
    assert new["scalar_date"] is scalar_date
    assert new["entry"] != old.names[compat.INDEX_BUNDLE]
    *_, selected, _ = compat._validated_publications(root, "1.61.1")
    assert REPAIRED in selected.payloads[TEXT_INPUT_BUNDLE]
    for name, raw in before.items():
        if name != "index.html":
            assert (root / name).read_bytes() == raw
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]


def test_text_input_only_changes_trigger_native_contact_browser_workflow():
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    sections = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    for event in ('push', 'pull_request'):
        assert {'scripts/streamlit_text_input_default.py', 'tests/test_streamlit_text_input_default.py'} <= set(
            re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
