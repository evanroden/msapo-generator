"""Reference prerequisites use the real wrapper and like-for-like native boxes."""
from pathlib import Path
import json
import re
import subprocess

from lxml import etree
import pytest
import streamlit

from scripts.patch_streamlit_frontend import INDEX_BUNDLE
from scripts.workspace_training_reference import (
    NATIVE_INPUT_HORIZONTAL_PADDING, OBSERVED_INPUT_CONTENT_WIDTH, REFERENCE_COLUMNS_CSS,
    REFERENCE_FORM_READY,
)


def select(root, selector):
    """Small class/testid/combinator adapter; this is not a browser CSS test."""
    tokens = re.findall(r'\.[\w-]+|\[data-testid="[\w-]+"\]|>', selector)
    expression = "."
    axis = "/descendant-or-self::"  # The keyed container is the root.
    for token in tokens:
        if token == ">":
            axis = "/child::"
            continue
        if token.startswith("."):
            predicate = "contains(concat(' ',normalize-space(@class),' '),' " + token[1:] + " ')"
        else:
            predicate = "@data-testid='" + token.split('"')[1] + "'"
        expression += axis + "*[" + predicate + "]"
        axis = "/descendant::"
    return root.xpath(expression)


def test_reference_column_rules_reach_horizontal_block_through_actual_locked_layout_wrapper():
    source = (Path(streamlit.__file__).parent / "static" / "static" / "js" / INDEX_BUNDLE).read_text()
    start = source.index("Mp=e=>{") + len("Mp=")
    renderer = source[start:source.index(",Np=", start)]
    code = r'''
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
// Execute the actual locked BlockNode renderer's ordinary flex-container
// branch. React factories/hooks only return its element tree; no DOM or
// browser scheduling is modeled here.
const scope={K:{useContext:()=>({scriptRunState:'notRunning'})},on:{},Ap:[],jp:[],
 ac:()=>({}),Zs:()=>({}),V:()=>false,Zu:()=>false,Yu:()=>true,ed:value=>value,
 l:(tag,props)=>({tag,props}),Op:'Op',nd:()=>true,kp:'kp',Of:'div',$u:value=>value};
const render=new Function('scope','with(scope){return ('+source+')}')(scope);
const result=render({node:{deltaBlock:{type:'flexContainer',id:'horizontal-row'},isEmpty:false}});
assert.equal(result.props['data-testid'],'stLayoutWrapper');
assert.equal(result.props.children.tag,'kp');
process.stdout.write(JSON.stringify(result));
'''
    result = subprocess.run(["node", "-e", code, json.dumps(renderer)], check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    root = etree.Element("div", {"class": "st-key-native_training_reference_columns"})
    wrapper = etree.SubElement(root, rendered["tag"], {"data-testid": rendered["props"]["data-testid"]})
    horizontal = etree.SubElement(wrapper, "div", {"data-testid": "stHorizontalBlock"})
    columns = [etree.SubElement(horizontal, "div", {"data-testid": "stColumn"}) for _ in range(2)]
    selectors = re.findall(r'^\s*(\.[^\n{]+)\s*\{', REFERENCE_COLUMNS_CSS, re.MULTILINE)
    assert select(root, selectors[0]) == [horizontal]
    assert select(root, selectors[1]) == columns
    # The old direct-child rule cannot cross the actual framework wrapper,
    # so native zero-gap columns kept their wider initial calculation.
    old = selectors[0].replace("columns [", "columns > [", 1)
    assert select(root, old) == []


@pytest.mark.parametrize("engine,reference_input_content,reference_input_border", [
    ("chromium", 365.109375, 373.109375),
    ("playwright-webkit", 361.953125, 369.953125),
])
def test_observed_reference_input_matches_original_input_not_wider_trigger(
        engine, reference_input_content, reference_input_border):
    # Exact original87 RO INPUT content boxes and ac62 INPUT boxes are separate
    # from original trigger/dropdown widths403.765625/400.59375.
    assert reference_input_border - reference_input_content == NATIVE_INPUT_HORIZONTAL_PADDING
    expected_input_border = OBSERVED_INPUT_CONTENT_WIDTH[engine] + NATIVE_INPUT_HORIZONTAL_PADDING
    assert abs(reference_input_border - expected_input_border) > 1
    # Applying the intended12px gutter reduces this left column by its native
    # 1.12:1 share. Subpixel layout rounding is the only modeled tolerance.
    corrected_content = reference_input_content - 12 * 1.12 / 2.12
    assert corrected_content == pytest.approx(OBSERVED_INPUT_CONTENT_WIDTH[engine], abs=.02)


def test_reference_waits_for_actual_native_expander_finish_before_positioning():
    source = (Path(streamlit.__file__).parent / "static" / "static" / "js" / INDEX_BUNDLE).read_text()
    start = source.index("function ku(")
    native = source[start:source.index("var Au=10", start)]
    code = r'''
const assert=require('node:assert/strict');
const data=JSON.parse(process.argv[1]);
const ready=new Function('return ('+data.ready+')')();
const handlers={};const animation={playState:'running',
 addEventListener(type,callback){handlers[type]=callback},cancel(){this.playState='idle'}};
const content={hasAttribute(){return false}};
const details={open:true,style:{height:'40px',overflow:'hidden'},scrollTop:0,
 clientHeight:40,scrollHeight:540,querySelector(){return content},getAnimations(){return [animation]},
 animate(frames,options){assert.deepEqual(frames,{height:['40px','540px']});
   assert.equal(options.duration,500);return animation}};
const input={isConnected:true,closest(){return details}};
const animate=new Function('Eu','Du','Ou','setTimeout','clearTimeout',data.native+';return ku')(
 500,'cubic-bezier(0.23, 1, 0.32, 1)',1000,()=>1,()=>{});
animate(details,40,540);
// The input can already be visible while the native details clips its form.
assert.equal(ready(input),false);
details.clientHeight=540;assert.equal(ready(input),false);
animation.playState='finished';assert.equal(ready(input),false);
// Execute the actual locked framework completion listener: it clears the
// temporary height and overflow. No test code cancels or finishes animation.
handlers.finish();assert.equal(ready(input),true);
// The recorded intermediate native scroll also fails the prerequisite.
details.scrollTop=192;assert.equal(ready(input),false);
details.scrollTop=0;assert.equal(ready(input),true);
details.open=false;assert.equal(ready(input),false);
details.open=true;input.isConnected=false;assert.equal(ready(input),false);
'''
    subprocess.run(["node", "-e", code, json.dumps({"native": native, "ready": REFERENCE_FORM_READY})],
                   check=True, capture_output=True, text=True)


def test_reference_readiness_is_read_only_and_does_not_rescue_selection_or_change_full_journey():
    source = (Path(__file__).parents[1] / "scripts" / "qa_monthly_training_date.py").read_text()
    reference = source.split("def exercise_participant_reference(", 1)[1].split("def exercise(", 1)[0]
    assert reference.index("page.wait_for_function(REFERENCE_FORM_READY") < reference.index("before = field.bounding_box()")
    assert reference.count("enter_topic_and_participant(page, original_input=original_input)") == 1
    assert "timeout=5000" in reference
    assert "REFERENCE_FORM_READY" not in source.split("def exercise(", 1)[1]
    for mutation in ("scrollTo(", "scrollIntoView(", ".finish(", ".cancel(", ".focus(", ".click("):
        assert mutation not in REFERENCE_FORM_READY


def test_participant_passive_evidence_distinguishes_opening_scroll_and_native_pointer():
    source = (Path(__file__).parents[1] / "scripts" / "qa_monthly_training_date.py").read_text()
    observer = source.split('observation["before_topic"] = field.evaluate("""', 1)[1].split('""")', 1)[0]
    code = r'''
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
const listeners=new Map(),observed=[];
let mutation,scroll,clock=10;
const content={hasAttribute:name=>name==='inert'};
const details={open:true,style:{height:'40px',overflow:'hidden'},scrollTop:192,
 clientHeight:348,scrollHeight:540,querySelector:()=>content,
 getAnimations:()=>[{playState:'running',currentTime:120}],contains:()=>true};
const input={isConnected:true,value:'',tagName:'INPUT',scrollTop:0,scrollLeft:0,
 closest:selector=>selector==='details'?details:null,
 getAttribute:name=>({'aria-expanded':'true','aria-controls':'options','data-testid':'native-input'}[name]),
 getBoundingClientRect:()=>({x:419,y:588,width:366.765625,height:28}),
 addEventListener(type,handler,options){assert.equal(options.passive,true);listeners.set(type,handler)},
 removeEventListener(type,handler){assert.equal(listeners.get(type),handler);listeners.delete(type)}};
const document={activeElement:input,getElementById:id=>id==='options'?{querySelectorAll:()=>[{},{}]}:null};
const window={addEventListener(type,handler,options){assert.equal(type,'scroll');
 assert.equal(options.passive,true);scroll=handler},removeEventListener(type,handler){
 assert.equal(type,'scroll');assert.equal(handler,scroll);scroll=null}};
class MutationObserver{
 constructor(callback){mutation=callback}
 observe(node,options){observed.push([node,options.attributeFilter])}
 disconnect(){mutation=null}
}
const before=JSON.stringify(details);
const bind=new Function('document','window','MutationObserver','performance','return ('+source+')')(
 document,window,MutationObserver,{now:()=>++clock});
const initial=bind(input);
assert.equal(JSON.stringify(details),before,'observation must not finish or alter native opening');
assert.equal(initial.expander.scrollTop,192);
assert.deepEqual(initial.expander.animations,[{playState:'running',currentTime:120}]);
assert.equal(initial.expander.contentInert,true);assert.equal(initial.popup.options,2);
assert.ok(observed.some(([node,attrs])=>node===details&&attrs.includes('style')));
assert.ok(observed.some(([node,attrs])=>node===content&&attrs.includes('inert')));
listeners.get('pointerdown')({target:input,isTrusted:true,timeStamp:15});
details.scrollTop=167;
scroll({target:details,isTrusted:true,timeStamp:16});
details.style.height='';details.style.overflow='';
mutation([{attributeName:'style'}]);
const events=window.__enfraTrainingParticipantEvidence.events;
assert.deepEqual(events.map(e=>e.type),['bound-original-input','pointerdown','ancestor-scroll','attributes:style']);
assert.equal(events[1].eventTestId,'native-input');assert.equal(events[1].trusted,true);
assert.equal(events[2].expander.scrollTop,167);assert.equal(events[2].eventTime,16);
assert.equal(events[3].expander.height,'');assert.equal(events[3].expander.overflow,'');
window.__enfraTrainingParticipantDispose();
assert.equal(listeners.size,0);assert.equal(scroll,null);assert.equal(mutation,null);
'''
    subprocess.run(["node", "-e", code, json.dumps(observer)],
                   check=True, capture_output=True, text=True)
