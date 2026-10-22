"""Pure readiness controls; native mounted-image assertions remain in hosted CI."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/qa_monthly_adaptive.py'


def test_selected_page_readiness_rejects_divider_and_unsettled_output():
    tree = ast.parse(SOURCE.read_text())
    constants = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {'DEEP', 'CURRENT_IMAGE_READY'}
    }
    predicate = 'wanted => {' + constants['DEEP'] + constants['CURRENT_IMAGE_READY'] + '}'
    script = r'''
const assert=require('node:assert/strict');
const ready=PREDICATE;
let status='Current · 5 pages', position='2 / 5', present=true;
let selected=[], divider=[{complete:true,naturalWidth:816}];
const pair={querySelectorAll(selector) {
 if(selector==='*') return [];
 if(selector==='.report-preview-status') return [{textContent:status}];
 if(selector==='.report-preview-position') return [{textContent:position}];
 if(selector==='.report-preview img') return divider.concat(selected);
 if(selector==='.report-preview figure[data-index="1"] img') return selected;
 throw Error('unexpected selector: '+selector);
}};
global.document={querySelector(selector){assert.equal(selector,'.activity');return present?pair:null;}};
const wanted={selector:'.activity',selected_page:2};
assert.equal(ready(wanted),false,'decoded divider cannot satisfy selected content');
selected=[{complete:false,naturalWidth:0}];
assert.equal(ready(wanted),false,'mounted but undecoded selected image');
selected=[{complete:true,naturalWidth:0}];
assert.equal(ready(wanted),false,'broken completed image');
selected=[{complete:true,naturalWidth:816}];
assert.equal(ready(wanted),true,'current selected decoded page');
position='1 / 5';assert.equal(ready(wanted),false,'old divider position');
position='20 / 25';assert.equal(ready(wanted),false,'prefix is not selected page');
position='2 / 5';status='Updating preview…';
assert.equal(ready(wanted),false,'old decoded image with new output pending');
status='Current · 5 pages';present=false;assert.equal(ready(wanted),false);
present=true;selected=[];
assert.equal(ready({...wanted,selected_page:null}),true,'unchanged generic readiness');
'''.replace('PREDICATE', predicate)
    subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)


def test_initial_activity_capture_requires_selected_page_without_weakening_gates():
    source = SOURCE.read_text()
    assert 'actual = current_image(page, ACTIVITY, selected_page=2)\n        baseline = capture' in source
    assert 'image.wait_for(state="visible", timeout=45000)' in source
    assert 'expect(image).to_have_js_property("complete", True, timeout=20000)' in source
    assert 'timeout=20000)\n    return pair' in source
    assert 'bool(activity["surface"]) and any(i["loaded"] for i in activity["images"])' in source
    assert 'activity["page"].startswith("2 /")' in source
