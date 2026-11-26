"""The site follows system appearance; document bytes are not recolored."""
import tomllib
from pathlib import Path
from scripts.patch_streamlit_metadata import patch_index
ROOT=Path(__file__).resolve().parents[1]
def test_native_variants_have_no_fixed_base():
 theme=tomllib.loads((ROOT/'.streamlit/config.toml').read_text())['theme']
 assert 'base' not in theme
 assert 'backgroundColor' not in theme
 assert theme['light']['backgroundColor']=='#FFFFFF'
 assert theme['dark']['backgroundColor']=='#111E1A'
 assert theme['dark']['textColor']=='#EDF5F0'
def test_native_override_reset_is_before_framework_and_idempotent(tmp_path):
 p=tmp_path/'index.html'
 p.write_text('<html><head><meta charset="utf-8"><title>Streamlit</title><script type="module" src="./static/js/index.js"></script></head><body></body></html>')
 patch_index(p)
 once=p.read_text()
 assert once.index('process-control-system-appearance')<once.index('type="module"')
 assert 'stActiveTheme-' in once and "JSON.stringify('System')" in once
 patch_index(p)
 assert p.read_text()==once
 assert once.count('id="process-control-system-appearance"')==1
def test_custom_surfaces_and_paper_are_distinct():
 from app.monthly_report_preview_view import CSS
 shell=(ROOT/'app/workflow_shell.css').read_text()
 assert '@media (prefers-color-scheme: dark)' in shell
 assert '.report-preview-page { width:100%; background:white;' in CSS
 assert '@media (prefers-color-scheme:dark)' in CSS
 assert 'filter:invert' not in shell.replace(' ','')
