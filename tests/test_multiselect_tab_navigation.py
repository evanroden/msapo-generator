"""Execute the locked native keyboard handler; browser acceptance is separate."""
import json
from pathlib import Path
import subprocess

import streamlit

from scripts.streamlit_combobox_close import COMBOBOX_BUNDLE, repair_combobox_close


def native_callbacks(raw):
    source = raw.decode()
    start = source.index('T=n=>{if(!n.nativeEvent.isComposing)switch(n.key){case`Enter`:case`Tab`:')
    keyboard = source[start + 2:source.index(',E=i=>', start)]
    start = source.index('q=()=>{F.isOpen')
    return {"keyboard": keyboard, "commit": source[start + 2:source.index(',ae=', start)]}


def test_tab_navigates_without_selecting_the_next_unrequested_option():
    raw = (Path(streamlit.__file__).parent / 'static/static/js' / COMBOBOX_BUNDLE).read_bytes()
    payload = {"before": native_callbacks(raw), "after": native_callbacks(repair_combobox_close(raw))}
    run = subprocess.run(['node', str(Path(__file__).with_name('multiselect_tab_navigation_test.cjs')),
                          json.dumps(payload)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr


def test_exact_tab_boundary_retains_the_prior_close_and_resize_repairs():
    import pytest
    from scripts.streamlit_combobox_close import TAB_ORIGINAL, TAB_REPAIRED, CLOSE_REPAIRED
    from scripts.streamlit_virtualizer_resize import VIRTUALIZER_REPAIRED
    raw = (Path(streamlit.__file__).parent / 'static/static/js' / COMBOBOX_BUNDLE).read_bytes()
    previous = repair_combobox_close(raw, virtualizer_resize=True, tab_navigation=False)
    repaired = repair_combobox_close(raw, virtualizer_resize=True)
    assert repaired.count(TAB_REPAIRED) == repaired.count(CLOSE_REPAIRED) == 1
    assert repaired.count(VIRTUALIZER_REPAIRED) == 1
    assert repaired.replace(TAB_REPAIRED, TAB_ORIGINAL, 1) == previous
    for changed in (raw + b' ', repaired, previous):
        with pytest.raises(RuntimeError, match='Unexpected locked ComboBox'):
            repair_combobox_close(changed)


# Disposable pinned wheel copy; never patch installed assets or production.
from test_streamlit_frontend_compat import bundle


def test_previous_live_generation_remains_exact_and_upgrades_without_losing_assets(bundle):
    from scripts import patch_streamlit_frontend as compat
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    previous = compat._publication(sources, members, True, tab_navigation=False)
    assert previous.generation == '7c1460cd65ff509bd13be1c257859262d81879cf70cc151a79d3b486ef5e987c'
    assert previous.names[compat.INDEX_BUNDLE] == 'index.enfra-frontend-7cb501c020cd.js'
    for name, raw in previous.payloads.items():
        (scripts / previous.names[name]).write_bytes(raw)
    (root / 'index.html').write_bytes(compat._publication_html(
        (root / 'index.html').read_bytes(), compat.INDEX_BUNDLE, previous, (previous,)))
    receipt = compat.selected_frontend(root)
    assert receipt['instant_expander'] and receipt['selection_safe_close']
    assert receipt['tab_navigation'] is False
    current = compat.patch_bundle(root, installed_version='1.61.1')
    assert current['tab_navigation'] and current['scalar_date']
    assert current['entry'] != previous.names[compat.INDEX_BUNDLE]
    assert compat.selected_frontend(root)['tab_navigation'] is True
    assert compat.patch_bundle(root, installed_version='1.61.1')['already_patched']
    for name, raw in previous.payloads.items():
        assert (scripts / previous.names[name]).read_bytes() == raw


def test_tab_only_changes_trigger_existing_native_browser_workflows():
    import re
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    sections = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    required = {'scripts/streamlit_combobox_close.py', 'tests/test_multiselect_tab_navigation.py',
                'tests/multiselect_tab_navigation_test.cjs'}
    for event in ('push', 'pull_request'):
        assert required <= set(re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
