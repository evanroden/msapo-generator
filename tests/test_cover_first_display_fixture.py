"""Fail-closed standing-cover fixture controls; no browser or external data."""
import json
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_testing as testing, monthly_report_library as library
from scripts.workspace_cover_first_display import MODES, setup, profile

@pytest.mark.parametrize('mode', MODES)
def test_standing_setup_is_scoped_and_never_creates_an_old_report(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    token = 'd'*32
    with testing.isolated(token):
        testing.data_dir(tmp_path)
        setup(tmp_path, token, mode)
        p = profile()
        state = library.load_profile(p.contract, p.key)
        assert bool(state.block('cover_photo')) == (mode != 'absent-photo')
        assert library.load_imported_draft(p.contract, p.key) is None
        with pytest.raises(ValueError, match='cannot be replaced'):
            setup(tmp_path, token, mode)
    assert not (tmp_path/'monthly_reports').exists()


def test_standing_setup_rejects_missing_marker_and_live_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError):
        setup(tmp_path, 'd'*32, 'square')
    assert not (tmp_path/'monthly_reports').exists()

@pytest.mark.parametrize('mode', ['wide-tall', 'absent-photo'])
def test_actual_fixture_entry_and_reload_use_no_saved_or_imported_report(tmp_path, mode):
    import os, subprocess, sys
    from pathlib import Path
    script = r'''
import json,sys
from html import unescape
from pathlib import Path
from streamlit.testing.v1 import AppTest
from app import monthly_report_section_preview_ui as preview
preview.render_section_preview=lambda *a,**kw: None
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py', default_timeout=30)
app.session_state['_monthly_dom_app_test_token']='d'*32
app.query_params['cover_mode']=sys.argv[1]
app.run()
assert not app.exception,[x.message for x in app.exception]
next(b for b in app.button if b.label=='Create synthetic standing cover').click().run()
assert not app.exception,[x.message for x in app.exception]
def receipt():
    import re
    text=next(x.proto.body for x in app.get('html') if 'data-enfra-standing-cover=' in x.proto.body)
    return json.loads(unescape(re.search('data-enfra-standing-cover="([^"]+)"',text)[1]))
before=receipt();app.run();assert not app.exception
assert receipt()==before
assert before['photo_present']==(sys.argv[1]!='absent-photo')
assert not before['saved_report'] and not before['imported_report']
'''
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'EPC_DATA_DIR': str(tmp_path), 'EPC_MONTHLY_DOM_FIXTURE':'1',
           'EPC_MONTHLY_COVER_FIRST_TASK':'1', 'EPC_MONTHLY_DOM_APPTEST':'1',
           'ANTHROPIC_API_KEY':'', 'SMARTSHEET_API_MODE':'disabled'}
    result = subprocess.run([sys.executable,'-c',script,mode],cwd=root,env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0, result.stdout+result.stderr


def test_pixel_geometry_accepts_round_and_rejects_stretched_or_missing_art(tmp_path):
    from PIL import Image, ImageDraw
    from scripts.qa_cover_first_display import circle_geometry
    from scripts.workspace_cover_first_display import COLORS
    path=tmp_path/'synthetic-preview.png'
    image=Image.new('RGB',(300,120),'white')
    draw=ImageDraw.Draw(image)
    for index,role in enumerate(COLORS):
        x=20+index*90
        draw.ellipse((x,20,x+50,70),fill=COLORS[role])
    image.save(path)
    assert set(circle_geometry(path,list(COLORS)))==set(COLORS)
    with pytest.raises(AssertionError, match='unexpectedly rendered'):
        circle_geometry(path, ['brand_logo','client_logo'], absent_roles=['cover_photo'])
    image.resize((600,120)).save(path)
    with pytest.raises(AssertionError): circle_geometry(path,list(COLORS))
    Image.new('RGB',(300,120),'white').save(path)
    with pytest.raises(AssertionError): circle_geometry(path,list(COLORS))
    assert circle_geometry(path, [], absent_roles=['cover_photo']) == {}

@pytest.mark.parametrize('mode', MODES)
def test_standing_master_actual_cover_docx_has_exact_roles_and_proportions(tmp_path, monkeypatch, mode):
    from io import BytesIO
    from hashlib import sha256
    from docx import Document
    from docx.oxml.ns import qn
    from PIL import Image
    from app.monthly_report_guided import _initial_draft
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_preview import section_preview_docx
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE','1')
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    with testing.isolated('d'*32):
        testing.data_dir(tmp_path); setup(tmp_path,'d'*32,mode)
        p=profile(); state=library.load_profile(p.contract,p.key)
        draft=_initial_draft(state,ReportPeriod(2026,10),'Synthetic Editor')
        assert draft.profile.template.startswith('enfra_master:')
        load=lambda ref: library.read_asset(p.contract,p.key,ref)
        raw=section_preview_docx(draft,'cover',load)
        document=Document(BytesIO(raw))
        expected={sha256(load(block.asset_hashes[0])).hexdigest():block.key
                  for block in draft.blocks if block.key in ('brand_logo','client_logo','cover_photo') and block.asset_hashes}
        found=[]
        for pic in document.element.iter(qn('pic:pic')):
            blip=next(pic.iter(qn('a:blip')))
            image=document.part.related_parts[blip.get(qn('r:embed'))].blob
            role=expected[sha256(image).hexdigest()]; found.append(role)
            width,height=Image.open(BytesIO(image)).size
            rect=pic.find(qn('pic:blipFill')).find(qn('a:srcRect'))
            crop={k:float(rect.get(k,'0'))/100000 if rect is not None else 0 for k in ('l','r','t','b')}
            extent=pic.find(qn('pic:spPr')).find(qn('a:xfrm')).find(qn('a:ext'))
            effective=(width*(1-crop['l']-crop['r']))/(height*(1-crop['t']-crop['b']))
            assert effective==pytest.approx(int(extent.get('cx'))/int(extent.get('cy')),rel=.001)
        assert sorted(found)==sorted(expected.values())
        assert ('cover_photo' in found)==(mode!='absent-photo')
