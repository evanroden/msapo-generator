export default function(component) {
    const {data} = component;
    const root = document.querySelector('.st-key-epc_workspace_' + CSS.escape(data.workflow));
    if (!root) return;
    const geometry = globalThis.ENFRAWorkspaceGeometry;
    if (!geometry) return;
    const scrollport = root.closest('[data-testid="stMain"]');
    const app = root.closest('[data-testid="stMainBlockContainer"]');
    if (!scrollport || !app) return; // locked-version adapter fails to normal flow
    const state = root._epcWorkspace || (root._epcWorkspace = {});
    if (state.cleanup) state.cleanup();
    if (state.identity !== data.identity) {
        state.identity = data.identity;
        state.active = null;
        state.mode = null;
    }
    let frame = null, focusFrame = null, disposed = false, pairs = [], lastGeometry = '';
    const subscriptions = [];
    root.classList.add('epc-workspace');
    // This stamp changes only on a real top-level Python workspace render.
    // Layout measurement, preview fragments and viewport changes do not change
    // it. The reference viewer uses this as an acknowledgment of native edits.
    root.dataset.epcFullRender = data.fullRender || '';
    const nav = data.navigationKey ? document.querySelector('.st-key-' + CSS.escape(data.navigationKey)) : null;
    const chrome = document.querySelector('[data-testid="stHeader"]');
    // An empty span can change the hash without giving a keyboard user the
    // prerequisite field. Handle only this owned Monthly correction link and
    // only when its unique native field exists. No value, input event, business
    // state or framework node is changed; modifier-click keeps browser behavior.
    function focusPreparedBy(event) {
        if (data.workflow !== 'monthly' || event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
        const link = event.target?.closest?.('a[href="#report-prepared-by"]');
        if (!link || !root.contains(link) || !app.querySelector('#report-prepared-by')) return;
        const fields = app.querySelectorAll('input[aria-label="Prepared by"]');
        if (fields.length !== 1 || fields[0].disabled || !fields[0].getClientRects().length) return;
        event.preventDefault();
        const field = fields[0];
        const url = new URL(window.location.href);
        url.hash = 'report-prepared-by';
        window.history.replaceState(window.history.state, '', url);
        if (focusFrame !== null) cancelAnimationFrame(focusFrame);
        focusFrame = requestAnimationFrame(() => {
            focusFrame = null;
            if (disposed || !field.isConnected) return;
            field.focus({preventScroll:true});
            field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
        });
    }
    root.addEventListener('click', focusPreparedBy);
    subscriptions.push(() => root.removeEventListener('click', focusPreparedBy));
    const safe = document.createElement('div');
    safe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)';
    root.append(safe);
    const rect = node => {
        const r = node.getBoundingClientRect();
        return {x:r.x, y:r.y, width:r.width, height:r.height};
    };
    function listen(target, type, listener = schedule) {
        if (!target?.addEventListener) return;
        target.addEventListener(type, listener, {passive:true});
        subscriptions.push(() => target.removeEventListener(type, listener));
    }
    function addControls(pair, reference, title, row) {
        // Keep the action under its own heading/errors, immediately before
        // the working row. Prepending it to the pair made it read as the prior
        // section's action on narrow screens. Move only our own control group.
        let before = row;
        while (before?.parentElement && before.parentElement !== pair) before = before.parentElement;
        if (before?.parentElement !== pair) return;
        let open = pair.querySelector('.epc-compact-open');
        if (!open) {
            const controls = document.createElement('div');
            controls.className = 'epc-preview-controls';
            open = document.createElement('button');
            open.type = 'button'; open.className = 'epc-compact-open';
            open.textContent = 'View preview'; open.setAttribute('aria-expanded', 'false');
            controls.append(open); pair.insertBefore(controls, before);
        } else if (open.parentElement.nextElementSibling !== before) {
            const focused = document.activeElement === open;
            pair.insertBefore(open.parentElement, before);
            if (focused) open.focus({preventScroll:true});
        }
        open.onclick = () => {
            state.returnFocus = document.activeElement;
            pair.dataset.epcPreviewOpen = 'true'; open.setAttribute('aria-expanded', 'true');
            reference.scrollIntoView({block:'start'}); reference.focus({preventScroll:true});
            schedule();
        };
        // A Streamlit fragment may replace reference children while the pair's
        // existing Open control survives. Restore each app-owned node on its
        // own surface instead of mistaking the pair control for complete setup.
        let titleNode = reference.querySelector('.epc-context-title');
        if (!titleNode) {
            titleNode = document.createElement('div');
            titleNode.className = 'epc-context-title';
            reference.prepend(titleNode);
        }
        if (titleNode.textContent !== title) titleNode.textContent = title;
        let back = reference.querySelector('.epc-compact-back');
        if (!back) {
            back = document.createElement('button');
            back.type = 'button'; back.className = 'epc-compact-back'; back.textContent = 'Back to editing';
            const backControls = document.createElement('div');
            backControls.className = 'epc-preview-controls'; backControls.append(back);
            reference.prepend(backControls);
        }
        back.onclick = () => {
            pair.dataset.epcPreviewOpen = 'false'; open.setAttribute('aria-expanded', 'false');
            if (state.returnFocus?.isConnected) state.returnFocus.focus({preventScroll:true});
            pair.scrollIntoView({block:'start'}); schedule();
        };
    }
    function discover() {
        pairs = Array.from(root.querySelectorAll('[data-epc-pair]')).map(marker => {
            const id = marker.dataset.epcPair;
            const pair = marker.closest('.st-key-epc_pair_' + CSS.escape(id));
            const editor = pair?.querySelector('.st-key-epc_edit_' + CSS.escape(id));
            const reference = pair?.querySelector('.st-key-epc_reference_' + CSS.escape(id));
            const editColumn = editor?.closest('[data-testid="stColumn"]');
            const refColumn = reference?.closest('[data-testid="stColumn"]');
            const row = editColumn?.parentElement;
            if (!pair || !reference || !editor || !row || row !== refColumn?.parentElement || row.dataset.testid !== 'stHorizontalBlock') return null;
            pair.classList.add('epc-workspace-pair');
            editor.classList.add('epc-workspace-editor');
            reference.classList.add('epc-workspace-reference');
            reference.setAttribute('tabindex','-1');
            reference.setAttribute('role','region');
            reference.setAttribute('aria-label', (marker.dataset.epcTitle || 'Section') + ' preview');
            editColumn.classList.add('epc-editor-column');
            refColumn.classList.add('epc-reference-column');
            row.classList.add('epc-workspace-row');
            let track = reference.parentElement;
            while (track && track !== refColumn) {
                track.classList.add('epc-reference-track'); track=track.parentElement;
            }
            addControls(pair, reference, marker.dataset.epcTitle || 'Section preview', row);
            return {id, pair, reference};
        }).filter(Boolean);
    }
    function snapshot() {
        const visual = window.visualViewport;
        const outer = rect(scrollport), block = rect(app), style = getComputedStyle(app), insets = getComputedStyle(safe);
        const header = chrome?.getBoundingClientRect();
        const chromeBottom = header && header.width > 0 && header.bottom > outer.y &&
            header.left < block.x + block.width && header.right > block.x ? header.bottom : outer.y;
        const workingTop = Math.max(outer.y, chromeBottom);
        const left = parseFloat(style.paddingLeft) || 0, right = parseFloat(style.paddingRight) || 0;
        const textScale = Math.max(1,(parseFloat(getComputedStyle(root).fontSize)||16)/16);
        let segments = null, posture = 'unknown';
        try { segments = window.viewport?.segments ? Array.from(window.viewport.segments, r => ({x:r.x,y:r.y,width:r.width,height:r.height})) : null; } catch (_) {}
        try { posture = navigator.devicePosture?.type || 'unknown'; } catch (_) {}
        return {layout:{width:document.documentElement.clientWidth, height:window.innerHeight},
            visual:visual ? {x:visual.offsetLeft,y:visual.offsetTop,width:visual.width,height:visual.height,scale:visual.scale} : null,
            app:{x:block.x + left,y:workingTop,width:Math.max(0,block.width-left-right),height:Math.max(0,outer.y+outer.height-workingTop)},
            chromeBottom,
            scrollport:outer, segments, posture, minEditor:360*textScale,minPreview:320*textScale,minHeight:240*textScale,
            safe:{top:parseFloat(insets.paddingTop)||0,right:parseFloat(insets.paddingRight)||0,bottom:parseFloat(insets.paddingBottom)||0,left:parseFloat(insets.paddingLeft)||0}};
    }
    function css(name, number) {root.style.setProperty('--epc-' + name, Math.round(number * 100)/100 + 'px');}
    function updateActive(context) {
        if (context.mode !== 'tabletop') {
            pairs.forEach(({pair}) => {delete pair.dataset.epcActive;});
            return;
        }
        const list = pairs.map(({id,pair}) => ({id, ...rect(pair)}));
        state.active = geometry.selectActiveSection(list, state.active, context.editor.y + 32, 24);
        pairs.forEach(({id,pair}) => {pair.dataset.epcActive = String(id === state.active);});
    }
    function measure() {
        frame = null;
        if (disposed || !root.isConnected || document.hidden) return;
        discover();
        const sample = snapshot();
        const context = geometry.resolveDisplayContext(sample);
        // Do not place a fixed reference through transformed framework ancestors.
        if (context.mode === 'tabletop') {
            let ancestor = root.parentElement;
            while (ancestor && ancestor !== document.body) {
                const style = getComputedStyle(ancestor);
                if (style.transform !== 'none' || style.filter !== 'none' || style.perspective !== 'none') {
                    context.mode = 'compact'; context.reason = 'transformed-ancestor'; break;
                }
                ancestor = ancestor.parentElement;
            }
        }
        const confined = context.mode === 'compact' && context.reason === 'segments-insufficient-space' && context.editor;
        const ownsScroll = context.mode === 'tabletop' || Boolean(confined);
        const ownedScrollBefore = state.ownsScroll;
        const previous = state.mode;
        const activeBefore = previous && previous !== context.mode ? pairs.find(p => p.id === state.active) || pairs.find(p => p.pair.getBoundingClientRect().bottom > sample.scrollport.y + 120) : null;
        if (!ownedScrollBefore && ownsScroll) state.outerScroll = scrollport.scrollTop;
        root.dataset.epcMode = context.mode;
        root.dataset.epcReason = context.reason || '';
        root.dataset.epcConfined = String(Boolean(confined));
        scrollport.classList.toggle('epc-workspace-scroll-owner', ownsScroll);
        if (context.editor) {
            css('editor-left',context.editor.x); css('editor-top',context.editor.y);
            css('editor-width',context.editor.width); css('editor-height',context.editor.height);
        }
        if (context.editor && context.preview) {
            css('editor-left',context.editor.x); css('editor-top',context.editor.y);
            css('editor-width',context.editor.width); css('editor-height',context.editor.height);
            css('reference-left',context.preview.x); css('reference-top',context.preview.y);
            css('reference-width',context.preview.width); css('reference-height',context.preview.height);
            css('column-gap',Math.max(0,context.preview.x-context.editor.x-context.editor.width));
        }
        const enlargement = (context.mode === 'book' || context.mode === 'tabletop') ? context.preview : (confined ? context.editor : context.bounds);
        if (enlargement) {
            const inset = Math.min(8,enlargement.width/8,enlargement.height/8);
            css('enlarge-left',enlargement.x+inset); css('enlarge-top',enlargement.y+inset);
            css('enlarge-width',Math.max(1,enlargement.width-2*inset));
            css('enlarge-height',Math.max(1,enlargement.height-2*inset));
        }
        const navStyle = nav ? getComputedStyle(nav) : null;
        const navTop = navStyle?.position === 'sticky' ? parseFloat(navStyle.top)||0 : 0;
        const top = Math.max(sample.visual?.y || 0, sample.scrollport.y, sample.chromeBottom, navTop) + (nav ? nav.getBoundingClientRect().height : 0) + 12;
        css('preview-top',top);
        const bottom = Math.min(sample.scrollport.y+sample.scrollport.height, (sample.visual?.y||0)+(sample.visual?.height||sample.layout.height));
        css('preview-height',context.mode === 'tabletop' && context.preview ? Math.max(120,context.preview.height-24) : Math.max(180,bottom-top-16));
        pairs.forEach(({reference}) => {
            const surface = Array.from(reference.querySelectorAll('*')).map(node => node.shadowRoot?.querySelector('.report-preview')).find(Boolean);
            if (!surface) return;
            const overhead = Math.max(0,surface.getBoundingClientRect().top-reference.getBoundingClientRect().top);
            const available = context.mode === 'tabletop' && context.preview ? context.preview.height : bottom-top;
            reference.style.setProperty('--epc-preview-height', Math.max(180,available-overhead-16)+'px');
        });
        if (previous !== context.mode && activeBefore) {
            // Same DOM/editor remains; only translate the meaningful scroll anchor.
            if (ownsScroll) root.scrollTop += activeBefore.pair.getBoundingClientRect().top - context.editor.y;
            else if (ownedScrollBefore) scrollport.scrollTop = state.outerScroll || 0;
        }
        state.mode = context.mode;
        state.ownsScroll = ownsScroll;
        updateActive(context);
        const signature = JSON.stringify([context.mode,context.editor,context.preview,top]);
        if (signature !== lastGeometry) {
            lastGeometry = signature;
            root.dispatchEvent(new CustomEvent('epc-workspace-layout',{bubbles:true,detail:{mode:context.mode}}));
        }
        // Diagnostic DOM attributes contain only layout, never report content.
    }
    function schedule() {if (!disposed && frame === null) frame = requestAnimationFrame(measure);}
    const resize = new ResizeObserver(schedule);
    resize.observe(app); resize.observe(scrollport); if (nav) resize.observe(nav);
    if (chrome) resize.observe(chrome);
    const mutation = new MutationObserver(schedule);
    mutation.observe(root, {childList:true,subtree:true});
    listen(window,'resize'); listen(window,'orientationchange');
    listen(window.visualViewport,'resize'); listen(window.visualViewport,'scroll');
    listen(window.screen?.orientation,'change');
    try {listen(navigator.devicePosture,'change');} catch (_) {}
    ['(horizontal-viewport-segments: 2)','(vertical-viewport-segments: 2)','(prefers-reduced-motion: reduce)','(any-pointer: coarse)'].forEach(query => listen(window.matchMedia(query),'change'));
    listen(document,'visibilitychange'); listen(root,'scroll'); listen(scrollport,'scroll');
    schedule();
    const cleanup = () => {
        if (disposed) return;
        disposed = true;
        if (frame !== null) cancelAnimationFrame(frame);
        if (focusFrame !== null) cancelAnimationFrame(focusFrame);
        resize.disconnect(); mutation.disconnect(); subscriptions.forEach(remove => remove());
        safe.remove(); scrollport.classList.remove('epc-workspace-scroll-owner');
    };
    state.cleanup = cleanup;
    return cleanup;
}
