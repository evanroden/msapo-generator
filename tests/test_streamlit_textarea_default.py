"""Execute pinned textarea initialization before passive effects can run."""
from pathlib import Path
import json
import subprocess
import pytest
import streamlit
from scripts.streamlit_textarea_default import TEXTAREA_BUNDLE, ORIGINAL, REPAIRED, repair_textarea_default


def native():
    return (Path(streamlit.__file__).parent / 'static/static/js' / TEXTAREA_BUNDLE).read_bytes()


def test_native_initializer_preserves_first_focus_clear_and_saved_precedence():
    raw=native();fixed=repair_textarea_default(raw)
    source=raw.decode();helpers=source[source.index('w=(e,t)=>'):source.index(',ee=')]
    code=r'''
const assert=require('node:assert/strict'),d=JSON.parse(process.argv[1]);
const init=(source,stored,proto)=>new Function('i','t','const '+d.helpers+';return ('+source+')()')({getStringValue:()=>stored},proto);
assert.equal(init(d.before,undefined,{default:'Inspect pump'}),null);
assert.equal(init(d.after,undefined,{default:'Inspect pump'}),'Inspect pump');
assert.equal(init(d.after,undefined,{default:'old',value:'current',setValue:true}),'current');
for(const stored of ['', 'delivered edit', '東京\nsecond line'])assert.equal(init(d.after,stored,{default:'old',value:'server',setValue:true}),stored);
assert.equal(init(d.after,undefined,{default:'',value:'ignored'}),'');
assert.equal(init(d.after,undefined,{}),null);
'''
    def expression(value):
        s=value.decode();start=s.index('()=>w(i,t)');end=s.index(',[V,H]',start)
        return s[start:end-1]
    result=subprocess.run(['node','-e',code,json.dumps({'helpers':helpers,'before':expression(raw),'after':expression(fixed)})],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_only_initializer_changes_and_source_drift_is_rejected():
    raw=native();fixed=repair_textarea_default(raw)
    assert fixed.count(REPAIRED)==1
    assert fixed.replace(REPAIRED,ORIGINAL,1)==raw
    for altered in [raw+b' ',fixed,raw.replace(ORIGINAL,b'')]:
        with pytest.raises(RuntimeError,match='Unexpected locked textarea'):
            repair_textarea_default(altered)


def test_prior_immutable_frontend_upgrades_without_overwriting_assets(tmp_path):
    import shutil
    from scripts import patch_streamlit_frontend as compat
    root=Path(streamlit.__file__).parent/'static'
    sources,members=compat._locked_sources(root/'static/js')
    old=compat._publication(sources,members,True,textarea_default=False)
    current=compat._publication(sources,members,True)
    assert not old.textarea_default and current.textarea_default
    assert old.names[compat.INDEX_BUNDLE]!=current.names[compat.INDEX_BUNDLE]
    assert ORIGINAL in old.payloads[TEXTAREA_BUNDLE]
    assert REPAIRED in current.payloads[TEXTAREA_BUNDLE]
    assert old.payloads[TEXTAREA_BUNDLE].replace(old.names['WidgetLabel.B3OAjMbS.js'].encode(),b'WidgetLabel.B3OAjMbS.js').replace(old.names['WidgetLabelHelpIcon.DPIlnvoY.js'].encode(),b'WidgetLabelHelpIcon.DPIlnvoY.js')==native()
    # Both recipes retain the exact pinned import graph and native controls.
    assert set(old.payloads)==set(current.payloads)
    assert compat._publication(sources,members,True,textarea_default=False).payloads==old.payloads
