"""Preserve Training geometry when the framework's 6px scrollbar style lands."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright
from app.monthly_report_training_ui import _session_summary_html
OUT=Path('test-artifacts/training-scrollbar-geometry')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    results=[]
    rows=(('Synthetic safety refresher','2026-09-25','In person','4','1'),)
    html=_session_summary_html(rows)
    baseline=html.replace('[data-enfra-training-summary]::-webkit-scrollbar{height:6px;width:6px}','')
    with sync_playwright() as p:
        for engine in ('chromium','webkit'):
            browser=getattr(p,engine).launch()
            for label,markup in (('baseline',baseline),('fixed',html)):
                page=browser.new_page(viewport={'width':545,'height':870})
                page.set_content('<style>body{font:16px sans-serif}.column{width:455px}</style><div class="column">'+markup+'<button>Edit request</button></div>')
                button=page.get_by_role('button',name='Edit request')
                before=button.bounding_box()
                page.add_style_tag(content='::-webkit-scrollbar{background:transparent;border-radius:99px;height:6px;width:6px}')
                # WebKit defers a changed scrollbar's layout until a later reflow.
                # Reconstruct it only in this isolated baseline/fix micro-fixture.
                # The full native acceptance journey gets no such mutation.
                page.locator('.column').evaluate("n=>{const s=n.querySelector('[data-enfra-training-summary]');s.style.overflowX='hidden';s.getBoundingClientRect();s.style.overflowX='auto';s.getBoundingClientRect()}")
                page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                after=button.bounding_box()
                results.append(dict(engine=engine,mode=label,before=before,after=after))
                page.screenshot(path=str(OUT/f'{engine}-{label}.png'))
                if label=='fixed':assert before==after
                elif engine=='webkit':assert after['y']-before['y']==6
                page.close()
            browser.close()
    (OUT/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
