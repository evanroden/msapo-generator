"""Synthetic DOM admission tests; native cold-layout acceptance still runs in CI."""
import ast
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def expression():
    tree = ast.parse((ROOT / "scripts/qa_monthly_adaptive.py").read_text())
    deep = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "DEEP" for target in node.targets))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "scroll_pair")
    call = function.body[0].value
    assert next(ast.literal_eval(k.value) for k in call.keywords if k.arg == "timeout") == 20000
    return eval(compile(ast.Expression(call.args[0]), "<scroll-pair>", "eval"), {"DEEP": deep})


def observe(options=None):
    script = r"""
const config=JSON.parse(process.argv[1]);
const classes=(...names)=>({contains:name=>names.includes(name)});
const box=(width=500,height=200)=>({x:0,y:5000,top:5000,bottom:5000+height,width,height});
const mode=config.mode||'compact',opened=config.opened===true;
let writes=0,position=600,inner=71;
const root={dataset:{epcMode:mode,epcConfined:String(!!config.confined)},
 classList:classes('epc-workspace'),getBoundingClientRect:()=>({top:40}),
 get scrollTop(){return inner;},set scrollTop(value){writes++;inner=value;}};
const scroll={get scrollTop(){return position;},set scrollTop(value){writes++;position=value;}};
const row={classList:classes(config.rowClass===false?'native-row':'epc-workspace-row'),
 dataset:{testid:'stHorizontalBlock'},getBoundingClientRect:()=>box(),
 style:{display:config.grid===false?'flex':'grid',gridTemplateColumns:
   config.wrongColumns?'250px 250px':(['compact','tabletop'].includes(mode)?'500px':'250px 250px')}};
const editColumn={parentElement:row,getBoundingClientRect:()=>box(config.wrongWidth?250:500),
 classList:classes('epc-editor-column')};
const refColumn={parentElement:config.differentRow?{}:row,
 getBoundingClientRect:()=>box(),getClientRects:()=>[box()],
 classList:classes('epc-reference-column'),
 style:{display:mode==='compact'&&!opened&&!config.referenceExposed?'none':'block'}};
const input={value:'Unsubmitted native text',selectionStart:4,selectionEnd:9};
const editor={closest:selector=>config.columnClass===false?null:editColumn,
 getBoundingClientRect:()=>box(),getClientRects:()=>config.editorHidden?[]:[box()]};
const reference={closest:()=>refColumn,
 getClientRects:()=>refColumn.style.display==='none'?[]:[box()],getBoundingClientRect:()=>box(),
 style:{visibility:'visible'}};
const surface={getClientRects:()=>config.surfaceHidden?[]:[box()],getBoundingClientRect:()=>box(500,300)};
const pair={dataset:{epcPreviewOpen:String(opened)},
 classList:classes(config.enhanced===false?'native-pair':'epc-workspace-pair'),
 closest:()=>root,getBoundingClientRect:()=>box(),
 querySelector:selector=>selector==='.epc-workspace-editor'?(config.editorMissing?null:editor):
   selector==='.epc-workspace-reference'?(config.referenceMissing?null:reference):null,
 querySelectorAll:selector=>selector==='.report-preview'?[surface]:[]};
const document={querySelector:selector=>selector==='.wanted'?pair:scroll,activeElement:input};
const getComputedStyle=node=>node.style||{};
const predicate=eval('('+process.argv[2]+')');
const ready=predicate({selector:'.wanted',inset:90,preview:!!config.preview});
console.log(JSON.stringify({ready,writes,position,inner,input,focused:document.activeElement===input}));
"""
    result = subprocess.run(["node", "-e", script, json.dumps(options or {}), expression()],
                            capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


@pytest.mark.parametrize("options", [
    {"enhanced": False}, {"rowClass": False}, {"grid": False},
    {"columnClass": False}, {"differentRow": True}, {"wrongColumns": True},
    {"wrongWidth": True}, {"referenceExposed": True}, {"editorHidden": True},
    {"editorMissing": True}, {"referenceMissing": True},
    {"preview": True}, {"preview": True, "opened": True, "surfaceHidden": True},
])
def test_mode_receipt_without_requested_surface_readiness_cannot_scroll(options):
    result = observe(options)
    assert result["ready"] is False
    assert result["writes"] == 0


@pytest.mark.parametrize("options,owned", [
    ({}, False), ({"mode": "wide"}, False), ({"mode": "book"}, False),
    ({"mode": "tabletop"}, True), ({"confined": True}, True),
    ({"preview": True, "opened": True}, False),
])
def test_ready_surface_uses_exactly_one_correct_scroll_without_editing_native_input(options, owned):
    result = observe(options)
    assert result["ready"] is True and result["writes"] == 1
    assert result["position"] == (600 if owned else 5510)
    assert result["inner"] == (4941 if owned else 71)
    assert result["focused"] is True
    assert result["input"] == {"value": "Unsubmitted native text", "selectionStart": 4, "selectionEnd": 9}
