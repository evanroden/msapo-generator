"""A scrollable preview that requests only visible pages, without remote scripts."""
from base64 import b64encode
from functools import lru_cache

import streamlit as st
from streamlit.runtime import Runtime


CSS = """
.report-preview { font:13px system-ui,sans-serif; color:#40524a; width:100%; height:var(--epc-preview-height,min(78dvh,780px)); display:flex; flex-direction:column; min-height:180px; }
.report-preview-status { min-height:22px; line-height:22px; padding:0 8px; }
.report-preview-scroll { flex:1; min-height:0; overflow:auto; background:#edf1ef; padding:12px; box-sizing:border-box; }
.report-preview-tools {display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px;}
.report-preview-tools button, .report-preview-tools select {font:inherit; min-height:36px; background:white; color:#18382b; border:1px solid #557f7f; border-radius:4px;}
.report-preview-tools button:focus-visible,.report-preview-scroll:focus-visible{outline:3px solid #557f7f;outline-offset:2px;}
.report-preview[data-enlarged="true"] {position:fixed;left:var(--epc-enlarge-left,12px);top:var(--epc-enlarge-top,12px);width:var(--epc-enlarge-width,calc(100dvw - 24px));height:var(--epc-enlarge-height,calc(100dvh - 24px));box-sizing:border-box;z-index:1000;background:white;padding:8px;box-shadow:0 4px 20px #0006;}
.report-preview figure { margin:0 0 16px; }
.report-preview-page { width:100%; background:white; position:relative; box-shadow:0 1px 6px #18382b26; }
.report-preview-page img { position:absolute; inset:0; display:block; width:100%; height:100%; }
.report-preview-placeholder { position:absolute; inset:20px; color:#64746d; text-align:center; }
.report-preview figcaption { text-align:center; padding-top:7px; }
"""
HTML = '<div class="report-preview"><div class="report-preview-status" role="status" aria-live="polite"></div><div class="report-preview-tools"><button type="button" data-action="previous" aria-label="Previous preview page">Previous</button><span class="report-preview-position"></span><button type="button" data-action="next" aria-label="Next preview page">Next</button><select aria-label="Preview zoom"><option value="width">Fit width</option><option value="page">Fit page</option><option value="1.25">125%</option><option value="1.5">150%</option></select><button type="button" data-action="enlarge">Enlarge</button></div><div class="report-preview-scroll" tabindex="0" aria-label="Report section preview"></div></div>'
JS = r"""
export default function(component) {
    const {parentElement, data, setStateValue} = component;
    const panel = parentElement.querySelector('.report-preview');
    // V2 may invoke the render function again on the same mounted element.
    // Dispose that invocation before its page DOM changes. The framework's
    // later unmount cleanup remains idempotent and cannot cancel a new timer.
    panel._previewCleanup?.();
    let active = true;
    let timer = null;
    const scroll = panel.querySelector('.report-preview-scroll');
    const status = panel.querySelector('.report-preview-status');
    const state = panel._previewState || (panel._previewState = {visible:false, sent:'', page:0, zoom:'width'});
    const workspace = (parentElement.host || parentElement).closest('.epc-workspace');
    const pair = (parentElement.host || parentElement).closest('.epc-workspace-pair');
    const zoom = panel.querySelector('select');
    const positionLabel = panel.querySelector('.report-preview-position');
    const previousButton = panel.querySelector('[data-action="previous"]');
    const nextButton = panel.querySelector('[data-action="next"]');
    const enlargeButton = panel.querySelector('[data-action="enlarge"]');
    // Only reading position is retained; no report text goes into browser storage.
    const views = window.__enfraPreviewViews || (window.__enfraPreviewViews = new Map());
    const viewKey = data.viewScope;
    if (state.scope !== viewKey) {
        const retained = views.get(viewKey) || {page:0,zoom:'width',offset:0};
        Object.assign(state, retained, {scope:viewKey, restore:true});
    }
    zoom.value = state.zoom;
    const sizes = data.sizes && data.sizes.length ? data.sizes : [[612,792]];
    const layout = JSON.stringify([data.generation, sizes, data.ready, data.stale]);
    status.textContent = data.status || '';
    if (state.layout !== layout) {
        const position = scroll.scrollTop;
        state.page = Math.min(state.page, sizes.length - 1);
        scroll.replaceChildren();
        sizes.forEach((size, index) => {
            const figure = document.createElement('figure');
            figure.dataset.index = String(index);
            const page = document.createElement('div');
            page.className = 'report-preview-page';
            page.style.aspectRatio = String(size[0]) + ' / ' + String(size[1]);
            const placeholder = document.createElement('div');
            placeholder.className = 'report-preview-placeholder';
            placeholder.textContent = data.ready ? 'Page ' + (index + 1) + ' · loads as you scroll' : (data.stale ? 'Older preview — changes not shown' : (data.status ? '' : 'Preview loads when this section is in view.'));
            page.append(placeholder);
            const caption = document.createElement('figcaption');
            caption.textContent = data.ready ? 'Page ' + (index + 1) + ' of ' + sizes.length : (data.stale ? 'Older preview · page ' + (index + 1) + ' of ' + sizes.length : '');
            figure.append(page, caption);
            scroll.append(figure);
        });
        scroll.scrollTop = position;
        state.layout = layout;
        state.restore = true;
    }
    const supplied = new Map((data.pages || []).map(page => [page.index, page]));
    scroll.querySelectorAll('figure').forEach(figure => {
        const index = Number(figure.dataset.index);
        const page = figure.querySelector('.report-preview-page');
        const wanted = supplied.get(index);
        let image = page.querySelector('img');
        if (!wanted) {
            if (image) image.remove();
            return;
        }
        if (!image) {
            image = document.createElement('img');
            image.alt = data.title + ' — page ' + (index + 1);
            page.append(image);
        }
        const src = 'data:image/jpeg;base64,' + wanted.image;
        if (image.getAttribute('src') !== src) image.setAttribute('src', src);
    });
    function sizePages() {
        if (!active) return;
        const available = Math.max(100,scroll.clientHeight-46);
        scroll.querySelectorAll('figure').forEach((figure,index) => {
            const ratio = sizes[index][0]/sizes[index][1];
            const width = state.zoom === 'page' ? Math.min(scroll.clientWidth-24,available*ratio) :
                (scroll.clientWidth-24)*(Number(state.zoom)||1);
            figure.style.width = Math.max(80,width)+'px';
            figure.style.marginInline = 'auto';
        });
        if (state.restore) {
            const figure = scroll.querySelector('figure[data-index="'+state.page+'"]');
            if (figure) scroll.scrollTop = figure.offsetTop - scroll.offsetTop + (state.offset || 0);
            state.restore = false;
        }
    }
    function remember() {
        if (!active) return;
        const figure = scroll.querySelector('figure[data-index="'+state.page+'"]');
        state.offset = figure ? scroll.scrollTop - (figure.offsetTop-scroll.offsetTop) : 0;
        views.delete(viewKey); views.set(viewKey,{page:state.page,zoom:state.zoom,offset:state.offset});
        while (views.size > 64) views.delete(views.keys().next().value);
        positionLabel.textContent = (state.page+1)+' / '+sizes.length;
        previousButton.disabled = state.page <= 0;
        nextButton.disabled = state.page >= sizes.length-1;
    }
    function movePage(index) {
        if (!active) return;
        state.page = Math.max(0,Math.min(sizes.length-1,index)); state.offset=0; state.restore=true;
        sizePages(); remember(); changed();
    }
    previousButton.onclick = () => movePage(state.page-1);
    nextButton.onclick = () => movePage(state.page+1);
    zoom.onchange = () => {state.zoom=zoom.value;state.offset=0;state.restore=true;sizePages();remember();changed();};
    enlargeButton.onclick = () => {
        if (!state.enlarged) {
            const prior=window.__enfraEnlargedPreview;
            if (prior && prior!==panel && prior.isConnected) prior.querySelector('[data-action="enlarge"]')?.click();
            window.__enfraEnlargedPreview=panel;
            remember();
            state.enlargeReturn={page:state.page,zoom:state.zoom,offset:state.offset};
            state.enlarged=true;
        } else {
            state.enlarged=false;
            if (window.__enfraEnlargedPreview===panel) window.__enfraEnlargedPreview=null;
            if (state.enlargeReturn) Object.assign(state,state.enlargeReturn);
            state.page=Math.min(state.page,sizes.length-1);
            zoom.value=state.zoom;
        }
        panel.dataset.enlarged=String(state.enlarged);
        enlargeButton.textContent=state.enlarged?'Close enlargement':'Enlarge';
        state.restore=true; sizePages(); remember(); changed();
    };
    function escape(event) {if (event.key==='Escape' && !event.isComposing && state.enlarged) enlargeButton.click();}
    document.addEventListener('keydown',escape);
    function send() {
        if (!active) return;
        timer = null;
        const bounds = scroll.getBoundingClientRect();
        const figures = Array.from(scroll.querySelectorAll('figure'));
        const shown = figures.filter(figure => {
            const rect = figure.getBoundingClientRect();
            return rect.bottom > bounds.top && rect.top < bounds.bottom;
        }).slice(0,2).map(figure => Number(figure.dataset.index));
        if (shown.length) state.page = shown[0];
        remember();
        const pixels = Math.max(1, scroll.clientWidth) * Math.min(window.devicePixelRatio || 1, 2);
        const dpi = pixels > 1100 ? 150 : pixels > 850 ? 120 : 96;
        const permitted = !workspace || workspace.dataset.epcMode !== 'tabletop' || pair?.dataset.epcActive === 'true';
        const value = {visible:state.visible && permitted, pages:shown.length ? shown : [0], dpi, generation:data.generation};
        const serialized = JSON.stringify(value);
        if (serialized !== state.sent) {
            state.sent = serialized;
            setStateValue('viewport', value);
        }
    }
    function changed() {
        if (!active) return;
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(send, 120);
    }
    const observer = new IntersectionObserver(entries => {
        if (!active) return;
        const visible = entries.some(entry => entry.isIntersecting);
        if (state.visible !== visible || !state.sent) {
            state.visible = visible;
            changed();
        }
    }, {rootMargin:'120px 0px', threshold:0.01});
    observer.observe(panel);
    const resize = new ResizeObserver(() => {sizePages(); changed();});
    resize.observe(scroll);
    scroll.addEventListener('scroll', changed, {passive:true});
    function layoutChanged() {sizePages();changed();}
    workspace?.addEventListener('epc-workspace-layout', layoutChanged);
    const activeObserver = new MutationObserver(changed);
    if (pair) activeObserver.observe(pair,{attributes:true,attributeFilter:['data-epc-active']});
    sizePages(); remember(); changed();
    function cleanup() {
        if (!active) return;
        active = false;
        observer.disconnect();
        activeObserver.disconnect();
        workspace?.removeEventListener('epc-workspace-layout', layoutChanged);
        document.removeEventListener('keydown',escape);
        resize.disconnect();
        scroll.removeEventListener('scroll', changed);
        if (timer !== null) clearTimeout(timer);
        timer = null;
        if (panel._previewCleanup === cleanup) panel._previewCleanup = null;
    }
    panel._previewCleanup = cleanup;
    return cleanup;
}
"""

def viewport(value, generation, pages=150):
    """Browser messages select bounded pages, never paths or another user's file."""
    if not isinstance(value, dict) or value.get('generation') != generation:
        return None
    indexes = value.get('pages', ())
    if (type(value.get('visible')) is not bool or not isinstance(indexes, (tuple, list))
            or not 1 <= len(indexes) <= 2
            or any(type(index) is not int or not 0 <= index < pages for index in indexes)
            or value.get('dpi') not in (96, 120, 150)):
        return None
    return {'visible': value['visible'], 'pages': tuple(dict.fromkeys(indexes)), 'dpi': value['dpi']}


@lru_cache(maxsize=2)
def _preview_component(runtime):
    return st.components.v2.component('report_preview_surface', html=HTML, css=CSS, js=JS)


def render_view(*, key, generation, title, ticket=None, images=(), status='', stale=False, on_change, view_scope=None):
    view = _preview_component(Runtime.instance())
    return view(key=key, data={
        'generation': generation, 'title': title, 'viewScope': str(view_scope or key), 'ready': ticket is not None and not stale, 'stale': bool(stale),
        'sizes': ticket.sizes if ticket else (), 'status': status,
        'pages': [{'index': index, 'image': b64encode(raw).decode('ascii')} for index, raw in images],
    }, default={'viewport': None}, on_viewport_change=on_change, height='content')
