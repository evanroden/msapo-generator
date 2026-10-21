from pathlib import Path
import subprocess


def test_owned_browser_image_decode_and_submit_lifetime():
    result=subprocess.run(['node','--test','tests/picture_group_load_gate_test.cjs'],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_production_v2_component_registers_in_real_streamlit_runtime():
    import sys
    script="""
import sys
sys.path.insert(0,'tests')
from streamlit.testing.v1 import AppTest
app=AppTest.from_string("from test_monthly_report_picture_batch import sample\\nfrom app.monthly_report_picture_batch_ui import review_picture_batch\\ndraft,assets=sample()\\nreview_picture_batch(draft,assets,'real_component',lambda k,v:k,incarnation='epoch')").run()
assert not app.exception,[e.message for e in app.exception]
"""
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
