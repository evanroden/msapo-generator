"""A section in view does not establish a mounted, visible compact preview."""
import ast
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def scroll_expression():
    tree = ast.parse((ROOT / "scripts/qa_monthly_adaptive.py").read_text())
    deep = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "DEEP" for target in node.targets))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "scroll_pair")
    call = next(node.value for node in function.body if isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "wait_for_function")
    return eval(compile(ast.Expression(call.args[0]), "<scroll expression>", "eval"),
                {"__builtins__": {}, "DEEP": ast.literal_eval(deep)})


def run_scroll(**options):
    js = """const options=JSON.parse(process.argv[1]);
const scroll={scrollTop:0,getBoundingClientRect:()=>({top:options.rootTop||0})};
const root=options.mounted===false?null:{...scroll,
  dataset:{epcMode:options.mode??'compact',epcConfined:String(Boolean(options.confined))}};
const classes=name=>({contains:value=>value===name});
const row={classList:classes('epc-workspace-row'),getBoundingClientRect:()=>({width:600})};
const editColumn={parentElement:row,getBoundingClientRect:()=>({width:600})};
const refColumn={parentElement:row};
const editor={closest:()=>editColumn,getClientRects:()=>[{}],
  getBoundingClientRect:()=>({width:600})};
const reference={closest:()=>refColumn,getClientRects:()=>options.open===false?[]:[{}]};
const getComputedStyle=node=>node===row?
  {display:'grid',gridTemplateColumns:['compact','tabletop'].includes(root?.dataset.epcMode)?'600px':'600px 600px'}:
  {display:options.open===false?'none':'block'};
const surface=options.surface===false?null:{
  getClientRects:()=>options.hidden?[]:[{}],getBoundingClientRect:()=>({top:980})};
const shadow={querySelectorAll:selector=>selector==='.report-preview'&&surface?[surface]:[]};
const pair={dataset:{epcPreviewOpen:options.open===false?'false':'true'},
  classList:classes('epc-workspace-pair'),
  querySelector:selector=>selector==='.epc-workspace-editor'?editor:
    selector==='.epc-workspace-reference'?reference:null,
  closest:()=>root,getBoundingClientRect:()=>({top:options.pairTop??90}),
  querySelectorAll:selector=>options.shadow?(selector==='*'?[{shadowRoot:shadow}]:[]):
    (selector==='.report-preview'&&surface?[surface]:[])};
const document={querySelector:selector=>selector==='.water'?pair:scroll};
const predicate=eval('('+process.argv[2]+')');
const result=predicate({selector:'.water',inset:90,preview:options.preview!==false});
console.log(JSON.stringify({result,mainScroll:scroll.scrollTop,rootScroll:root?.scrollTop||0}));"""
    process = subprocess.run(["node", "-e", js, json.dumps(options), scroll_expression()],
                             text=True, capture_output=True, check=True, timeout=5)
    return json.loads(process.stdout)


def test_reload_waits_for_the_workspace_enhancement_without_a_null_probe():
    assert run_scroll(mounted=False) == {"result": False, "mainScroll": 0, "rootScroll": 0}
    assert run_scroll(mode="") == {"result": False, "mainScroll": 0, "rootScroll": 0}
    assert run_scroll(mode="unmounted") == {"result": False, "mainScroll": 0, "rootScroll": 0}


def test_compact_preview_scrolls_the_actual_surface_below_the_editor():
    assert run_scroll() == {"result": True, "mainScroll": 890, "rootScroll": 0}
    assert run_scroll(shadow=True) == {"result": True, "mainScroll": 890, "rootScroll": 0}
    assert run_scroll(preview=False) == {"result": True, "mainScroll": 0, "rootScroll": 0}


def test_compact_preview_requires_an_open_mounted_rendered_surface():
    for options in ({"open": False}, {"surface": False}, {"hidden": True}):
        assert run_scroll(**options) == {"result": False, "mainScroll": 0, "rootScroll": 0}


def test_confined_compact_uses_the_real_workspace_scroll_owner():
    assert run_scroll(confined=True, rootTop=40) == {
        "result": True, "mainScroll": 0, "rootScroll": 850}


def test_wide_and_book_keep_section_scrolling_in_the_main_owner():
    for mode in ("wide", "book"):
        assert run_scroll(mode=mode, pairTop=1400) == {
            "result": True, "mainScroll": 1310, "rootScroll": 0}


def test_tabletop_keeps_the_real_lower_workspace_scroll_owner():
    assert run_scroll(mode="tabletop", pairTop=1400, rootTop=40) == {
        "result": True, "mainScroll": 0, "rootScroll": 1270}
