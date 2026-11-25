"""Native hit-target acceptance on synthetic workflow forms only."""
from pathlib import Path


TARGETS = '''() => {
 const visible=n=>n.getClientRects().length&&!n.closest('[inert]')&&getComputedStyle(n).visibility!=='hidden'&&!n.disabled;
 const nodes=[...document.querySelectorAll('[data-testid="stMain"] button,[data-testid="stMain"] summary,[data-testid="stMain"] input:not([type="hidden"]):not([type="file"]),[data-testid="stMain"] select')];
 const seen=new Set(), rows=[];
 for(let n of nodes){
  if(!visible(n))continue;
  if(n.matches('input[type="checkbox"],input[type="radio"]'))n=n.closest('label')||n;
  if(!visible(n)||seen.has(n))continue;
  seen.add(n);
  const r=n.getBoundingClientRect();
  rows.push({label:(n.getAttribute('aria-label')||n.innerText||n.querySelector('input')?.getAttribute('aria-label')||n.tagName).slice(0,100),width:r.width,height:r.height});
 }
 return {overflow:document.documentElement.scrollWidth>innerWidth+2,rows};
}'''


def exercise_touch_targets(page, *, output: Path, name: str):
    original = dict(page.viewport_size)
    rows = []
    try:
        for width in (320,390,669):
            page.set_viewport_size({'width':width,'height':885})
            page.wait_for_function('''()=>document.querySelector('.epc-workspace')?.dataset.epcMode==='compact'||innerWidth===669''')
            # Native CSS media rules apply synchronously after layout flush.
            result = page.evaluate(TARGETS)
            assert result['rows'], result
            small = [r for r in result['rows'] if r['width']<43.5 or r['height']<43.5]
            assert not small, {'width':width,'small':small}
            assert not result['overflow'], result
            rows.append({'width':width,**result})
        page.screenshot(path=str(output/f'{name}-native-touch-targets.png'))
        return rows
    finally:
        page.set_viewport_size(original)
