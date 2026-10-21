"""Real browser acceptance of owned image-load/consent surface (synthetic only)."""
from base64 import b64encode
from io import BytesIO
from pathlib import Path
import shutil
import os
import pytest
from PIL import Image


def test_browser_decode_error_retry_keyboard_and_reopen_gate():
    if os.environ.get('EPC_REQUIRE_PICTURE_BROWSER') == '1':
        import playwright.sync_api as playwright
    else:
        playwright=pytest.importorskip('playwright.sync_api')
    from app.monthly_report_picture_group import HTML, CSS
    source=Path('app/monthly_report_picture_group.js').read_text()
    out=BytesIO();Image.new('RGB',(20,20),'blue').save(out,format='PNG')
    encoded=b64encode(out.getvalue()).decode()
    data={'identity':'synthetic-manifest','nonce':'first','pictures':[
        {'title':f'Synthetic picture {i}', 'context':'Selected synthetic site', 'mime':'image/png','image':encoded} for i in range(6)]}
    with playwright.sync_playwright() as p:
        executable=shutil.which('chromium')
        try: browser=p.chromium.launch(executable_path=executable,headless=True)
        except playwright.Error as exc:
            if os.environ.get('EPC_REQUIRE_PICTURE_BROWSER') == '1': raise
            pytest.skip('Browser unavailable: '+str(exc).splitlines()[0])
        page=browser.new_page(viewport={'width':420,'height':800})
        page.set_content('<style>'+CSS+'</style>'+HTML)
        page.evaluate('''() => {
            window.events=[];window.releases=[];
            const decode=HTMLImageElement.prototype.decode;
            HTMLImageElement.prototype.decode=function(){return decode.call(this).then(()=>new Promise(r=>window.releases.push(r)));};
        }''')
        page.evaluate('''({source,data}) => {
            window.render=new Function('return '+source.replace('export default ',''))();
            window.data=data;
            window.cleanup=window.render({parentElement:document.body,data,setStateValue:(k,v)=>window.events.push(v)});
        }''', {'source':source,'data':data})
        button=page.get_by_role('button',name='Confirm these 6 pictures are ready (except those left for correction)',exact=True)
        page.wait_for_function('window.releases.length===6')
        assert button.is_disabled() # Loaded URL alone is not decoded-image proof.
        page.evaluate('window.releases.splice(0).forEach(r=>r())')
        playwright.expect(button).to_be_enabled()
        page.locator('img').nth(2).evaluate('img=>img.onerror()')
        assert button.is_disabled()
        retry=page.get_by_role('button',name='Retry loading this picture')
        retry.click()
        page.wait_for_function('window.releases.length===1')
        assert button.is_disabled()
        page.evaluate('window.releases.splice(0).forEach(r=>r())')
        playwright.expect(button).to_be_enabled()
        page.get_by_role('checkbox').nth(1).check()
        button.focus();page.keyboard.press('Enter')
        assert page.evaluate('window.events.length')==1
        event=page.evaluate('window.events[0]')
        assert event=={'identity':'synthetic-manifest','nonce':'first','loaded':[True]*6,'left':[False,True,False,False,False,False]}
        assert button.is_disabled()
        page.keyboard.press('Enter')
        assert page.evaluate('window.events.length')==1
        page.evaluate('''() => {window.data={...window.data,nonce:'second'};
            window.cleanup=window.render({parentElement:document.body,data:window.data,setStateValue:(k,v)=>window.events.push(v)});}''')
        assert button.is_disabled()
        page.wait_for_function('window.releases.length===6')
        page.evaluate('window.cleanup();window.releases.splice(0).forEach(r=>r())')
        assert button.is_disabled()
        assert page.evaluate('window.events.length')==1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()
