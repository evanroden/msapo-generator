import json
from pathlib import Path
import os
import subprocess
import sys
import pytest
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_water_widget_delivery import WaterWidgetDelivery
from scripts.qa_widget_delivery import WidgetDelivery


@pytest.mark.parametrize('water', [False, True])
def test_oversized_and_filtered_frames_count_without_retaining_contents(water):
    rows = []
    observer = WaterWidgetDelivery(rows.append) if water else WidgetDelivery(lambda kind, row: rows.append(row))
    send = lambda raw: observer.message('received', raw, *(() if water else (1,)))
    huge = b'private-synthetic-placeholder' * 200_000
    reference = ForwardMsg(ref_hash='unrelated-not-retained').SerializeToString()
    finished = ForwardMsg(script_finished=0).SerializeToString()
    send(huge); send(reference); send(finished)
    totals = rows[-1]['wire_totals']['received']
    assert totals == dict(frames=3, bytes=len(huge)+len(reference)+len(finished), maximum=len(huge), references=1)
    assert 'private-synthetic-placeholder' not in json.dumps(rows)
    assert 'unrelated-not-retained' not in json.dumps(rows)
    snapshot = dict(totals)
    send(finished)
    assert totals == snapshot


def test_existing_standalone_harness_imports_without_repository_package(tmp_path):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    code = f"""
import sys
sys.path.insert(0, {str(scripts)!r})
from qa_widget_delivery import WidgetDelivery
from qa_water_widget_delivery import WaterWidgetDelivery
assert WidgetDelivery(lambda *args: None).wire_totals.snapshot()['received']['bytes'] == 0
assert WaterWidgetDelivery(lambda *args: None).wire_totals.snapshot()['received']['bytes'] == 0
"""
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
