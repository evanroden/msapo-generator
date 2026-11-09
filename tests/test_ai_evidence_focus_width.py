"""Locked native CSS and ownership contracts; hosted click geometry is separate."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from lxml import etree
import pytest
import streamlit
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ('.st-key-epc_workspace_monthly [class*="_linked_"][class*="_facts_"] '
            '[data-testid="stMultiSelect"] input[role="combobox"][aria-label^="Evidence for paragraph "]')


def reservation():
    css = re.sub(r'/\*.*?\*/', '', (ROOT / 'app/workspace_initial.css').read_text(), flags=re.S)
    rules = [(selector.strip(), body.strip()) for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)
             if '_facts_' in selector]
    assert rules == [(SELECTOR, 'min-width:3rem;')]
    return rules[0]


def test_evidence_minimum_is_present_before_adapter_and_not_focus_conditional():
    selector, body = reservation()
    assert ':focus' not in selector and '!important' not in body
    source = (ROOT / 'app/workspace_layout.py').read_text()
    assert source.index("(_ASSETS / 'workspace_initial.css').read_text()") < source.index('_adapter(Runtime.instance())')


@pytest.mark.parametrize('workspace,key,widget,tag,role,label,expected', [
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 2', True),
    ('monthly', 'report_linked_training_summary_facts_def', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 1', True),
    ('expense', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 2', False),
    ('', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_other_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_linked_activity_summary_pages_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stSelectbox', 'input', 'combobox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'textarea', 'combobox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'textbox', 'Evidence for paragraph 2', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Pages to read for facts', False),
    ('monthly', 'report_linked_activity_summary_facts_abc', 'stMultiSelect', 'input', 'combobox', 'Evidence for paragraph', False),
])
def test_reservation_is_limited_to_canonical_monthly_paragraph_evidence(
        workspace, key, widget, tag, role, label, expected):
    # The rule's exact constrained selector is checked above; XPath applies its
    # equivalent ownership predicates to varied native-shaped markup. This is
    # not represented as a real browser selector/layout engine test.
    reservation()
    root = etree.Element('main')
    owner = etree.SubElement(root, 'div', {'class': 'st-key-epc_workspace_' + workspace})
    keyed = etree.SubElement(owner, 'div', {'class': 'st-key-' + key})
    native = etree.SubElement(keyed, 'div', {'data-testid': widget})
    field = etree.SubElement(native, tag, {'role': role, 'aria-label': label})
    matched = root.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " st-key-epc_workspace_monthly ")]'
        '//*[contains(@class,"_linked_") and contains(@class,"_facts_")]'
        '//*[@data-testid="stMultiSelect"]//input[@role="combobox" and starts-with(@aria-label,"Evidence for paragraph ")]')
    assert (field in matched) is expected


def test_real_linked_paragraph_renderer_supplies_the_owned_key_and_label():
    from test_monthly_report_ai_correction_targets import fixture
    app = AppTest.from_string('''
import streamlit as st
from app.workspace_layout import workspace
from app.monthly_report_ai_ui import edit_linked_paragraphs
from app.monthly_report_ui import _field
draft=st.session_state.draft
with workspace('monthly','synthetic-evidence-width'):
    edit_linked_paragraphs(draft,{b.key:b for b in draft.blocks},'ai_width',_field)
''', default_timeout=15)
    app.session_state.draft = fixture()
    app.run()
    assert not app.exception
    assert app.multiselect
    for widget in app.multiselect:
        assert widget.label.startswith('Evidence for paragraph ')
        assert re.fullmatch(r'ai_width_linked_[a-z_]+_facts_[a-f0-9]+', widget.key)
        assert widget.value == list(app.session_state.draft.blocks[0].ai_paragraphs[0].fact_ids)
    assert reservation()[0] in app.get('html')[0].proto.body


def test_reservation_matches_the_actual_locked_native_focused_minimum():
    from scripts.patch_streamlit_frontend import MANIFEST_PATH
    name = 'Multiselect.Bh_0JsCR.js'
    raw = (Path(streamlit.__file__).parent / 'static/static/js' / name).read_bytes()
    manifest = json.loads(MANIFEST_PATH.read_text())['members'][name]
    assert sha256(raw).hexdigest() == manifest['sha256']
    # Execute only the real pinned pure style factory, not a synthetic browser
    # or rewritten style. The native control stays wholly unchanged.
    source = raw.decode()
    factory = re.search(r'(\(\{theme:e,\$typingDisabled:t,\$hasValues:n\}\)=>\(\{.*?\}\))\),F=i', source)
    assert factory, 'Review this boundary if the locked native input style changes.'
    script = '''const style = ''' + factory[1] + ''';
const unused=new Proxy({}, {get:(_,name)=>String(name)});
const theme={sizes:unused,spacing:{sm:'0.5rem',threeXS:'0.125rem'},fontSizes:unused,
lineHeights:unused,fontWeights:unused,colors:unused};
const native=style({theme,$typingDisabled:false,$hasValues:true});
console.log(JSON.stringify({blurred:native.minWidth,focused:native['&:focus'].minWidth}));'''
    result = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, check=True)
    native = json.loads(result.stdout)
    assert native == {'blurred': '0.5rem', 'focused': '3rem'}
    _, body = reservation()
    minimum = body.removeprefix('min-width:').removesuffix(';')
    assert minimum == native['focused']
    # An input fits an illustrative 1rem remainder only while blurred under the
    # original style. Equal minima remove that focus-dependent wrap condition;
    # actual pointer hit geometry is still asserted in the hosted warning gate.
    rem = lambda value: float(value.removesuffix('rem'))
    assert rem(native['blurred']) <= 1 < rem(native['focused'])
    assert rem(minimum) > 1 and rem(minimum) == rem(native['focused'])
