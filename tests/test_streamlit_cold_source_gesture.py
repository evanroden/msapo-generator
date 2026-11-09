"""Bounded native geometry guard and immutable entry delivery, without a browser."""
import json
from pathlib import Path
import subprocess

import pytest

from scripts import patch_streamlit_frontend as compat
from test_streamlit_frontend_compat import bundle, files


def test_native_geometry_guard_and_cancellation_contract():
    run = subprocess.run(['node', 'tests/cold_source_gesture_test.cjs',
                          'scripts/streamlit_cold_source_gesture.js'], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)['passed'] == 31


@pytest.mark.parametrize('scalar_date', [False, True])
def test_only_early_guard_is_added_to_previous_entry_and_upgrade_keeps_old_bytes(bundle, scalar_date):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, scalar_date, cold_source_gesture=False)
    new = compat._publication(sources, members, scalar_date)
    guard = Path('scripts/streamlit_cold_source_gesture.js').read_bytes()
    def normalized(p, key):
        raw = p.payloads[key]
        for native, selected in p.names.items():
            raw = raw.replace(selected.encode(), native.encode())
        return raw
    for name in sources:
        expected = normalized(old, name)
        if name == compat.INDEX_BUNDLE:
            expected += b'\n;' + guard
        assert normalized(new, name) == expected
    for name, raw in old.payloads.items():
        (scripts / old.names[name]).write_bytes(raw)
    (root / 'index.html').write_bytes(compat._publication_html(
        (root / 'index.html').read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    before = files(root)
    assert not compat.selected_frontend(root)['cold_source_gesture']
    receipt = compat.patch_bundle(root, installed_version='1.61.1')
    assert receipt['cold_source_gesture'] and receipt['entry'] == new.names[compat.INDEX_BUNDLE]
    assert compat.selected_frontend(root)['cold_source_gesture']
    for name, raw in before.items():
        if name != 'index.html':
            assert (root / name).read_bytes() == raw
    after = files(root)
    assert compat.patch_bundle(root, installed_version='1.61.1')['already_patched']
    assert files(root) == after
