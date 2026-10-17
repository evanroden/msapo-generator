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
