"""A scrollable preview that requests only visible pages, without remote scripts."""
from base64 import b64encode
from functools import lru_cache

import streamlit as st
from streamlit.runtime import Runtime


CSS = """
.report-preview { font:13px system-ui,sans-serif; color:#40524a; width:100%; height:var(--epc-preview-height,min(78dvh,780px)); display:flex; flex-direction:column; min-height:180px; }
.report-preview-header { min-height:28px; display:flex; align-items:center; gap:8px; padding:2px 8px; }
.report-preview-status { flex:1; min-width:0; line-height:22px; }
.report-preview-position { white-space:nowrap; font-variant-numeric:tabular-nums; }
.report-preview-retry { font:inherit; min-height:36px; padding:4px 10px; background:white; color:#18382b; border:1px solid #557f7f; border-radius:4px; }
.report-preview-retry[hidden] { display:none; }
.report-preview-retry:focus-visible, .report-preview-scroll:focus-visible { outline:3px solid #557f7f; outline-offset:2px; }
.report-preview-scroll { flex:1; min-height:0; overflow:auto; background:#edf1ef; padding:12px; box-sizing:border-box; }
.report-preview figure { margin:0 0 16px; }
.report-preview-page { width:100%; background:white; position:relative; box-shadow:0 1px 6px #18382b26; }
.report-preview-page img { position:absolute; inset:0; display:block; width:100%; height:100%; }
.report-preview-placeholder { position:absolute; inset:20px; color:#64746d; text-align:center; }
.report-preview figcaption { text-align:center; padding-top:7px; }
"""
HTML = '<div class="report-preview"><div class="report-preview-header"><span class="report-preview-status" role="status" aria-live="polite"></span><span class="report-preview-position" aria-label="Visible page"></span><button type="button" class="report-preview-retry" data-action="retry-request" hidden>Retry preview</button></div><div class="report-preview-scroll" tabindex="0" aria-label="Report preview — scroll to read all pages"></div></div>'
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
    let pollTimer = null;
    let ackTimer = null;
    const scroll = panel.querySelector('.report-preview-scroll');
    const status = panel.querySelector('.report-preview-status');
    const state = panel._previewState || (panel._previewState = {visible:false, sent:'', page:0});
    // A browser send is not proof that its callback survived a competing
    // rerender. Reconcile with the server's applied view on every invocation.
    // Reading position remains client state; only this bounded request retries.
    const ack = data.acknowledgedViewport;
    const applied = ack ? JSON.stringify({visible:ack.visible,pages:ack.pages,dpi:ack.dpi,generation:ack.generation}) : null;
    if (applied) state.sent = applied;
    const host = parentElement.host || parentElement;
    const app = host.closest('[data-testid="stApp"]');
    let editGate = null;
    let onEditorReceipt = null;
    function frameworkBusy() {
        // Locked-version adapter: Streamlit exposes this state on its real
        // app root. A preview event must not replace a pending editing rerun.
        const run = app?.getAttribute('data-test-script-state');
        // An unblurred editor may keep its own old preview until the edit
        // is acknowledged. Other visible section previews must still load;
        // native change/click triggering a full Streamlit rerun blocks ALL.
        const guarded = editGate?.pending && (editGate.blockAll ||
            !editGate.scopePair || editGate.scopePair === pair);
        return Boolean(guarded || (run && run !== 'notRunning'));
    }
    // The preview can mount before the layout adapter's first animation
    // frame adds its classes. Bind stable app-owned container keys now so
    // later active-section changes reach even an initially offscreen viewer.
    const workspace = host.closest('[class*="st-key-epc_workspace_"]') || host.closest('.epc-workspace');
    const pair = host.closest('[class*="st-key-epc_pair_"]') || host.closest('.epc-workspace-pair');
    // Browser native changes can queue a complete Streamlit editor rerun before
    // data-test-script-state becomes 'running'. A preview fragment sent in this
    // interval can overtake that edit; an interleaved full/fragment response
    // was observed to reuse a ForwardMsg hash already evicted by WebKit.
    // Coordinate VIEW requests only: do not inspect widget values, clone a
    // widget, send business state, or alter any form submission.
    const gates = window.__enfraPreviewNativeEditGates ||
        (window.__enfraPreviewNativeEditGates = new WeakMap());
    if (app && workspace) {
        editGate = gates.get(app);
        if (!editGate || editGate.workspace !== workspace) {
            const gate = {workspace, pending:false, before:'', blockAll:false,
                scopePair:null, refs:0, listeners:new Set()};
            const releaseAfterFullRender = () => {
                if (!gate.pending) return;
                const finished = workspace.dataset.epcFullRender;
                if (finished && finished !== gate.before &&
                        app.getAttribute('data-test-script-state') === 'notRunning') {
                    gate.pending = false;
                    gate.blockAll = false;
                    gate.scopePair = null;
                    for (const listener of gate.listeners) listener();
                }
            };
            const awaitNativeEdit = (inputTarget = null) => {
                const current = workspace.dataset.epcFullRender;
                if (!current) return;
                const withinPair = inputTarget?.closest?.('[class*="st-key-epc_pair_"]') ||
                    inputTarget?.closest?.('.epc-workspace-pair') || null;
                if (!gate.pending) gate.before = current;
                gate.pending = true;
                // Native change/choice is about to start a full editor rerun:
                // no preview fragment in any section may compete with it.
                // Mere typing has no completed editor request yet; hold only
                // the affected pair so visible adjacent sections can render.
                gate.blockAll = gate.blockAll || !withinPair;
                gate.scopePair = gate.blockAll ? null : withinPair;
            };
            const nativeChange = event => {
                const target = event.target;
                if (!target?.matches?.('input,textarea,select') ||
                        target.closest?.('.report-preview')) return;
                awaitNativeEdit();
            };
            // Streamlit's checkbox/toggle label can synchronously request its
            // full editor rerun before a native input "change" bubbles to this
            // adapter (observed with WebKit split-receipt editing). Capture
            // only deliberate checkbox/radio label activation before React
            // handles the click; never block on ordinary input focus, scroll,
            // preview Retry, file pickers, or browser-native zoom.
            const nativeChoiceClick = event => {
                const target = event.target;
                // The reference pane's Streamlit Retry button belongs to its
                // preview fragment. No full-editor receipt follows that action,
                // so treating it as an editor commit would strand every viewer.
                if (!target?.closest || target.closest('.report-preview') ||
                        target.closest('[class*="st-key-epc_reference_"]') ||
                        target.closest('.epc-workspace-reference')) return;
                const label = target.closest('label');
                const button = target.closest('[data-testid="stButton"] button');
                if (label?.querySelector('input[type="checkbox"], input[type="radio"]') ||
                        (button && !button.disabled)) awaitNativeEdit();
            };
            // Ctrl/Command+Enter commits without blur/change. Tab/Shift+Tab
            // moves focus/scroll before its change/blur handlers can protect
            // the deferred commit. Hold neighboring fragments at keydown for
            // these native apply gestures. Only an existing edit opens this
            // hold; ordinary Enter/IME/focus are still local input.
            const nativeEditorCommit = event => {
                const target = event.target;
                const applyKey = (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) ||
                    (event.key === 'Tab' && !event.ctrlKey && !event.metaKey && !event.altKey);
                if (!gate.pending || event.isComposing || !applyKey ||
                        !target?.matches?.('textarea') || target.closest?.('.report-preview')) return;
                const withinPair = target.closest?.('[class*="st-key-epc_pair_"]') ||
                    target.closest?.('.epc-workspace-pair');
                if (withinPair && (gate.blockAll || gate.scopePair === withinPair)) awaitNativeEdit();
            };
            // Text remains unacknowledged while the operator types.
            // A geometry change can otherwise dispatch view fragments before
            // blur/on_change commits the native text area. Capture only its
            // input EVENT (not any text) and defer disposable view updates
            // until the distinct completed editor render acknowledges it.
            // Ordinary focus, viewer controls and non-editor fields do not
            // open this gate; it does not submit or alter business data.
            const nativeEditorInput = event => {
                const target = event.target;
                const preparer = target?.matches?.('input[aria-label="Prepared by"]');
                if ((!preparer && !target?.matches?.('textarea')) || target.closest?.('.report-preview')) return;
                if (!preparer && !target.closest?.('[class*="st-key-epc_edit_"]') &&
                        !target.closest?.('.epc-workspace-editor')) return;
                // Attribution is outside the section pairs and controls saved
                // contact/artwork access throughout the report. Its delayed
                // native blur commit needs a full render, just like a section
                // text edit; a queued preview fragment must not absorb it.
                awaitNativeEdit(preparer ? null : target);
            };
            app.addEventListener('input', nativeEditorInput, true);
            app.addEventListener('change', nativeChange, true);
            app.addEventListener('click', nativeChoiceClick, true);
            app.addEventListener('keydown', nativeEditorCommit, true);
            const observer = new MutationObserver(releaseAfterFullRender);
            observer.observe(workspace, {attributes:true,attributeFilter:['data-epc-full-render']});
            observer.observe(app, {attributes:true,attributeFilter:['data-test-script-state']});
            gate.dispose = () => {app.removeEventListener('input',nativeEditorInput,true);app.removeEventListener('change',nativeChange,true);app.removeEventListener('click',nativeChoiceClick,true);app.removeEventListener('keydown',nativeEditorCommit,true);observer.disconnect();};
            editGate = gate;
            gates.set(app, gate);
        }
        editGate.refs++;
        onEditorReceipt = () => {if (active) changed();};
        editGate.listeners.add(onEditorReceipt);
    }
    const positionLabel = panel.querySelector('.report-preview-position');
    // Only actual view-request failures have a recovery button. Page navigation,
    // fit/zoom and enlargement toolbars are intentionally absent in all workflows.
    const retryRequest = panel.querySelector('[data-action="retry-request"]');
    retryRequest.hidden = !state.requestFailed;
    retryRequest.onclick = () => {
        state.requestAttempts=0; state.requestFailed=false; state.sent=''; retryRequest.hidden=true;
        status.textContent=data.status || ''; send();
    };
    // Only reading position is retained; no report text goes into browser storage.
    const views = window.__enfraPreviewViews || (window.__enfraPreviewViews = new Map());
    const viewKey = data.viewScope;
    if (state.scope !== viewKey) {
        const retained = views.get(viewKey) || {page:0,offset:0};
        Object.assign(state, retained, {scope:viewKey, restore:true});
    }
    const pagesKnown = Boolean(data.sizes && data.sizes.length);
    const sizes = pagesKnown ? data.sizes : [[612,792]];
    const layout = JSON.stringify([data.generation, sizes, data.ready, data.stale]);
    status.textContent = state.requestFailed ? 'Preview request interrupted — retry.' : (data.status || '');
    if (state.layout !== layout) {
        const position = scroll.scrollTop;
        // An evicted/preparing ticket is not a one-page document. Keep the
        // user's anchor until actual pagination is available again.
        if (pagesKnown) state.page = Math.min(state.page, sizes.length - 1);
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
            // A rapid compact -> book transition can receive the outgoing
            // hidden-view response after this same page is visible again.
            // Keep its already decoded image until the current view returns.
            // There is no second image cache: at most the selected old page
            // survives, and only when it fits beside fewer than two supplied
            // images. A generation/layout change already replaces this DOM.
            const retain = index === state.page && visibleNow() && supplied.size < 2;
            if (image && !retain) image.remove();
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
        if (!scroll.clientWidth || !scroll.clientHeight) {
            state.restore = true;
            return;
        }
        const dimensions = scroll.clientWidth + 'x' + scroll.clientHeight;
        if (state.dimensions !== dimensions) state.restore = true;
        state.dimensions = dimensions;
        // All pages are stacked at the actual pane width, maintaining each
        // page's native aspect ratio; no layout-dependent zoom state survives.
        const width = Math.max(1, scroll.clientWidth - 24);
        scroll.querySelectorAll('figure').forEach(figure => {
            figure.style.width = width + 'px';
            figure.style.marginInline = 'auto';
        });
        if (state.restore && pagesKnown) {
            const figure = scroll.querySelector('figure[data-index="'+state.page+'"]');
            if (figure) scroll.scrollTop = figure.offsetTop - scroll.offsetTop + (state.offset || 0);
            state.restore = false;
        }
    }
    function remember() {
        if (!active) return;
        const figure = scroll.querySelector('figure[data-index="'+state.page+'"]');
        // Hidden/zero-size references and temporary placeholder pagination
        // cannot overwrite the last usable reading position.
        if (!state.restore && pagesKnown && scroll.clientWidth && scroll.clientHeight && figure)
            state.offset = scroll.scrollTop - (figure.offsetTop-scroll.offsetTop);
        views.delete(viewKey); views.set(viewKey,{page:state.page,offset:state.offset});
        while (views.size > 64) views.delete(views.keys().next().value);
        positionLabel.textContent = pagesKnown ? (state.page+1)+' / '+sizes.length : '—';
    }
    function permitted() {
        return !workspace || workspace.dataset.epcMode !== 'tabletop' || pair?.dataset.epcActive === 'true';
    }
    function visibleNow() {
        if (document.hidden || !permitted()) return false;
        if (workspace?.dataset.epcMode !== 'tabletop') return state.visible;
        // The intended fixed upper surface is outside the lower scroll root.
        // WebKit's IntersectionObserver may clip it to that ancestor despite
        // its viewport-fixed placement. Measure only the active reference;
        // inactive/hidden references have no positive rendered rectangle.
        const bounds = panel.getBoundingClientRect(), view = window.visualViewport;
        const left = view?.offsetLeft || 0, top = view?.offsetTop || 0;
        const right = left + (view?.width || window.innerWidth);
        const bottom = top + (view?.height || window.innerHeight);
        return bounds.width > 0 && bounds.height > 0 && bounds.right > left &&
            bounds.left < right && bounds.bottom > top && bounds.top < bottom;
    }
    function pollWhenPending() {
        if (pollTimer !== null) clearTimeout(pollTimer);
        pollTimer = null;
        if (!active || frameworkBusy() || !data.pending || !visibleNow()) return;
        pollTimer = setTimeout(() => {
            pollTimer = null;
            if (!active || frameworkBusy() || !visibleNow()) return;
            state.pollSequence = (state.pollSequence || 0) + 1;
            setStateValue('poll', {generation:data.generation, sequence:state.pollSequence});
            // Keep a bounded heartbeat if a busy session defers this event.
            // Re-render cleanup disposes this invocation's timer first.
            pollWhenPending();
        }, 2000);
    }
    function send() {
        if (!active) return;
        timer = null;
        if (frameworkBusy()) return; // app-state observer resumes after editing
        const bounds = scroll.getBoundingClientRect();
        const figures = Array.from(scroll.querySelectorAll('figure'));
        const visible = figures.map(figure => {
            const rect = figure.getBoundingClientRect();
            return {index:Number(figure.dataset.index), height:Math.max(0,Math.min(rect.bottom,bounds.bottom)-Math.max(rect.top,bounds.top))};
        }).filter(page => page.height > 0);
        const shown = visible.slice(0,2).map(page => page.index);
        // A clamped final page can leave a sliver of the preceding caption visible
        // when scrolling clamps at the end. Keep the dominant page selected.
        if (pagesKnown && !state.restore && scroll.clientWidth && scroll.clientHeight && visible.length)
            state.page = visible.reduce((best,page) => page.height > best.height ? page : best).index;
        remember();
        const pixels = Math.max(1, scroll.clientWidth) * Math.min(window.devicePixelRatio || 1, 2);
        const dpi = pixels > 1100 ? 150 : pixels > 850 ? 120 : 96;
        const value = {visible:visibleNow(), pages:pagesKnown && shown.length ? shown : [state.page], dpi, generation:data.generation};
        const serialized = JSON.stringify(value);
        if (state.requestSignature !== serialized || serialized === applied) {
            state.requestSignature=serialized; state.requestAttempts=0; state.requestFailed=false;
            retryRequest.hidden=true; status.textContent=data.status || '';
            if (ackTimer !== null) clearTimeout(ackTimer);
            ackTimer=null;
        }
        if (serialized !== state.sent) {
            // A stale server acknowledgment can invoke this component again.
            // Enforce the budget at transmission, not only in the timer: a
            // rerender or observer must not acquire extra automatic attempts.
            if (state.requestAttempts >= 3) {
                interrupted();
                return;
            }
            state.sent = serialized;
            // A distinct receipt lets Streamlit deliver a retried state value
            // even when an interrupted callback already stored its old value.
            state.requestSequence = (state.requestSequence || 0) + 1;
            state.requestAttempts = (state.requestAttempts || 0) + 1;
            setStateValue('viewport', {...value, requestId:state.requestSequence});
        }
        // Different visible fragments can update together. A coalesced event
        // may receive no rerender at all, so checking only the next invocation
        // is insufficient. Retry this idempotent view request at most twice;
        // then offer explicit recovery. Never retry report edits or generation.
        if (applied && serialized !== applied && !state.requestFailed && ackTimer === null && !document.hidden) {
            ackTimer=setTimeout(() => {
                ackTimer=null;
                if (!active || document.hidden || frameworkBusy()) return;
                if (state.requestAttempts >= 3) {
                    interrupted();
                    return;
                }
                state.sent=''; send();
            }, 2000);
        }
        pollWhenPending();
    }
    function interrupted() {
        state.requestFailed=true;
        if (visibleNow()) {
            status.textContent='Preview request interrupted — retry.';
            retryRequest.hidden=false;
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
    document.addEventListener('visibilitychange', changed);
    const activeObserver = new MutationObserver(changed);
    if (pair) activeObserver.observe(pair,{attributes:true,attributeFilter:['data-epc-active']});
    const appObserver = app ? new MutationObserver(() => {
        if (!frameworkBusy()) changed();
    }) : null;
    appObserver?.observe(app,{attributes:true,attributeFilter:['data-test-script-state']});
    sizePages(); remember(); changed();
    function cleanup() {
        if (!active) return;
        // A source switch may unmount before the scroll debounce acknowledges.
        remember();
        active = false;
        observer.disconnect();
        activeObserver.disconnect();
        appObserver?.disconnect();
        if (editGate && onEditorReceipt) {
            editGate.listeners.delete(onEditorReceipt);
            if (--editGate.refs === 0) {editGate.dispose();gates.delete(app);}
        }
        workspace?.removeEventListener('epc-workspace-layout', layoutChanged);
        document.removeEventListener('visibilitychange', changed);
        resize.disconnect();
        scroll.removeEventListener('scroll', changed);
        if (timer !== null) clearTimeout(timer);
        timer = null;
        if (pollTimer !== null) clearTimeout(pollTimer);
        pollTimer = null;
        if (ackTimer !== null) clearTimeout(ackTimer);
        ackTimer = null;
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
    if 'requestId' in value and (type(value['requestId']) is not int or not 1 <= value['requestId'] <= 2**53 - 1):
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


def render_view(*, key, generation, title, ticket=None, images=(), status='', stale=False, on_change, view_scope=None, pending=False, on_poll=None, acknowledged_viewport=None):
    view = _preview_component(Runtime.instance())
    applied = acknowledged_viewport or {'visible': False, 'pages': (0,), 'dpi': 96}
    return view(key=key, data={
        'generation': generation, 'title': title, 'viewScope': str(view_scope or key), 'ready': ticket is not None and not stale, 'stale': bool(stale),
        'sizes': ticket.sizes if ticket else (), 'status': status, 'pending': bool(pending),
        'acknowledgedViewport': {'visible': bool(applied['visible']), 'pages': list(applied['pages']),
                                 'dpi': applied['dpi'], 'generation': generation},
        'pages': [{'index': index, 'image': b64encode(raw).decode('ascii')} for index, raw in images],
    }, default={'viewport': None, 'poll': None}, on_viewport_change=on_change,
        on_poll_change=on_poll or (lambda: None), height='content')
