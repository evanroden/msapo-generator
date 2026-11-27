"""Actual native-field acceptance for simulated enlarged root text, not device settings."""
from pathlib import Path
from playwright.sync_api import expect


def exercise_larger_text(page, field, *, output: Path, name: str):
    original_view = dict(page.viewport_size)
    original_font = page.evaluate('document.documentElement.style.fontSize')
    original_value = field.input_value()
    field.scroll_into_view_if_needed()
    field.focus()
    field.evaluate('n=>{n.setSelectionRange?.(0,Math.min(3,n.value.length));window.__epcTextAcceptanceField=n;}')
    before = field.evaluate('n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd})')
    rows = []
    try:
        page.set_viewport_size({'width':669,'height':885})
        for index, scale in enumerate((1,1.5,2,1)):
            page.evaluate('scale=>{document.documentElement.style.fontSize=(16*scale)+"px";window.dispatchEvent(new Event("resize"));}',scale)
            expected = 'wide' if scale == 1 else 'compact'
            expect(page.locator('.epc-workspace')).to_have_attribute('data-epc-mode',expected)
            # Font reflow may complete after the first resolver pass. Wait on
            # final geometry, not a timer or a test-only scroll into view.
            field.evaluate('''async n=>{
                for(let frame=0;frame<30;frame++){
                    const b=n.getBoundingClientRect();
                    if(frame>=4 && b.top>=0 && b.bottom<=innerHeight-4)return;
                    await new Promise(r=>requestAnimationFrame(r));
                }
                throw new Error('Enlarged text left the active field outside the viewport');
            }''')
            record = field.evaluate('''n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd,
                same:n===window.__epcTextAcceptanceField,focused:document.activeElement===n,
                font:parseFloat(getComputedStyle(document.querySelector('.epc-workspace')).fontSize),
                overflow:document.documentElement.scrollWidth>innerWidth+2,
                rect:n.getBoundingClientRect().toJSON()})''')
            rows.append({'scale':scale,**record})
            assert abs(record['font']-16*scale)<1,record
            assert not record['overflow'] and record['same'] and record['focused'],record
            assert {key:record[key]for key in before}==before,record
            page.screenshot(path=str(output/f'{name}-larger-text-{index}-{scale}.png'))
        return rows
    except Exception:
        page.screenshot(path=str(output/f'{name}-larger-text-failure.png'))
        raise
    finally:
        page.evaluate('font=>{document.documentElement.style.fontSize=font;delete window.__epcTextAcceptanceField;window.dispatchEvent(new Event("resize"));}',original_font)
        page.set_viewport_size(original_view)
        assert field.input_value()==original_value
