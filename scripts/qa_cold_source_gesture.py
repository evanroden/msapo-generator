"""Deterministic synthetic geometry control, separate from the real app journey.

Resize only an invented placeholder between real pointer down/up. This proves
native hit testing, not actual application hydration. The unchanged cold app
journey in qa_source_corrections remains the production integration gate.
"""
from pathlib import Path

HTML = '''<style>body{margin:0}main{height:600px;overflow:auto;overflow-anchor:none}
#placeholder{height:900px}button{height:40px}#tail{height:800px}</style>
<main data-testid="stMain"><div data-testid="stMainBlockContainer">
<div class="st-key-epc_workspace_monthly"><span class="enfra-source-correction-owner"
data-report-identity="aaaaaaaaaaaaaaaaaaaaaaaa"></span><div id="placeholder"></div></div>
<div class="st-key-monthly_source_warning_synthetic"><span class="enfra-source-warning" data-source-id="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
data-report-identity="aaaaaaaaaaaaaaaaaaaaaaaa"></span>
<button onclick="window.nativeActions=(window.nativeActions||0)+1">Correct date</button></div>
<div id="tail"></div></div></main>'''


def prove_native_gesture(browser):
    source = Path(__file__).with_name('streamlit_cold_source_gesture.js').read_text()
    records = []
    for repaired in (False, True):
        context = browser.new_context(viewport={'width': 900, 'height': 700})
        context.route('**/*', lambda route: route.abort())
        page = context.new_page()
        try:
            page.set_content(HTML)
            if repaired:
                page.add_script_tag(content=source)
            button = page.get_by_role('button', name='Correct date', exact=True)
            button.scroll_into_view_if_needed()
            initial = button.bounding_box()
            page.mouse.move(initial['x'] + 20, initial['y'] + 20)
            page.mouse.down()
            # Model the observed 218px native hydration expansion, not a click.
            page.evaluate("document.getElementById('placeholder').style.height='1118px'")
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            expanded = button.bounding_box()
            page.mouse.up()
            actions = page.evaluate('window.nativeActions || 0')
            assert actions == int(repaired), (repaired, initial, expanded, actions)
            assert abs(expanded['y'] - initial['y'] - (0 if repaired else 218)) < 1
            # Once released, the guard must not keep controlling scroll.
            page.evaluate("document.getElementById('placeholder').style.height='1218px'")
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            assert abs(button.bounding_box()['y'] - expanded['y'] - 100) < 1
            assert page.evaluate('window.nativeActions || 0') == actions
            records.append({'repaired': repaired, 'initial_y': initial['y'],
                            'expanded_y': expanded['y'], 'native_actions': actions,
                            'released_without_scroll_ownership': True})
        finally:
            context.close()
    return records
