"""A scrollable preview that requests only visible pages, without remote scripts."""
from base64 import b64encode

import streamlit as st


CSS = """
.report-preview { font:13px system-ui,sans-serif; color:#40524a; width:100%; }
.report-preview-status { min-height:22px; line-height:22px; padding:0 8px; }
.report-preview-scroll { height:730px; overflow:auto; background:#edf1ef; padding:12px; box-sizing:border-box; }
.report-preview figure { margin:0 0 16px; }
.report-preview-page { width:100%; background:white; position:relative; box-shadow:0 1px 6px #18382b26; }
.report-preview-page img { position:absolute; inset:0; display:block; width:100%; height:100%; }
.report-preview-placeholder { position:absolute; inset:20px; color:#64746d; text-align:center; }
.report-preview figcaption { text-align:center; padding-top:7px; }
"""
HTML = '<div class="report-preview"><div class="report-preview-status" role="status"></div><div class="report-preview-scroll" tabindex="0" aria-label="Report section preview"></div></div>'
JS = r"""
export default function(component) {
    const {parentElement, data, setStateValue} = component;
    const panel = parentElement.querySelector('.report-preview');
    const scroll = panel.querySelector('.report-preview-scroll');
    const status = panel.querySelector('.report-preview-status');
    const state = panel._previewState || (panel._previewState = {visible:false, sent:'', timer:null});
    const sizes = data.sizes && data.sizes.length ? data.sizes : [[612,792]];
    const layout = JSON.stringify([data.generation, sizes]);
    status.textContent = data.status || '';
    if (state.layout !== layout) {
        const position = scroll.scrollTop;
        scroll.replaceChildren();
        sizes.forEach((size, index) => {
            const figure = document.createElement('figure');
            figure.dataset.index = String(index);
            const page = document.createElement('div');
            page.className = 'report-preview-page';
            page.style.aspectRatio = String(size[0]) + ' / ' + String(size[1]);
            const placeholder = document.createElement('div');
            placeholder.className = 'report-preview-placeholder';
            placeholder.textContent = data.ready ? 'Page ' + (index + 1) + ' · loads as you scroll' : 'Preview updates when this section is in view.';
            page.append(placeholder);
            const caption = document.createElement('figcaption');
            caption.textContent = data.ready ? 'Page ' + (index + 1) + ' of ' + sizes.length : 'Draft layout';
            figure.append(page, caption);
            scroll.append(figure);
        });
        scroll.scrollTop = position;
        state.layout = layout;
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
    function send() {
        state.timer = null;
        const bounds = scroll.getBoundingClientRect();
        const figures = Array.from(scroll.querySelectorAll('figure'));
        const shown = figures.filter(figure => {
            const rect = figure.getBoundingClientRect();
            return rect.bottom > bounds.top && rect.top < bounds.bottom;
        }).slice(0,2).map(figure => Number(figure.dataset.index));
        const pixels = Math.max(1, scroll.clientWidth) * Math.min(window.devicePixelRatio || 1, 2);
        const dpi = pixels > 1100 ? 150 : pixels > 850 ? 120 : 96;
        const value = {visible:state.visible, pages:shown.length ? shown : [0], dpi, generation:data.generation};
        const serialized = JSON.stringify(value);
        if (serialized !== state.sent) {
            state.sent = serialized;
            setStateValue('viewport', value);
        }
    }
    function changed() {
        if (state.timer !== null) clearTimeout(state.timer);
        state.timer = setTimeout(send, 120);
    }
    const observer = new IntersectionObserver(entries => {
        const visible = entries.some(entry => entry.isIntersecting);
        if (state.visible !== visible || !state.sent) {
            state.visible = visible;
            changed();
        }
    }, {rootMargin:'120px 0px', threshold:0.01});
    observer.observe(panel);
    const resize = new ResizeObserver(changed);
    resize.observe(scroll);
    scroll.addEventListener('scroll', changed, {passive:true});
    changed();
    return () => {
        observer.disconnect();
        resize.disconnect();
        scroll.removeEventListener('scroll', changed);
        if (state.timer !== null) clearTimeout(state.timer);
        state.timer = null;
    };
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


def render_view(*, key, generation, title, ticket=None, images=(), status='', on_change):
    view = st.components.v2.component('report_preview_surface', html=HTML, css=CSS, js=JS)
    return view(key=key, data={
        'generation': generation, 'title': title, 'ready': ticket is not None,
        'sizes': ticket.sizes if ticket else (), 'status': status,
        'pages': [{'index': index, 'image': b64encode(raw).decode('ascii')} for index, raw in images],
    }, default={'viewport': None}, on_viewport_change=on_change, height=760)
