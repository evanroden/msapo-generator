/* One native RFI Add action may focus its acknowledged new request field.
 *
 * This adapter follows the locked Streamlit 1.61.1 keyed widget wrappers.
 * The Python row editor emits an inert origin marker and a fresh row nonce;
 * only a trusted native click arms the matching one-shot consumer. It never
 * reads or changes a value, submits an event, moves/clones a framework node,
 * or focuses an old draft simply because it appeared after reload.
 *
 * Remove when Streamlit offers a version-bound focus request for a native
 * newly added row, retaining pointer/keyboard, cancellation, delayed delivery,
 * same-node/caret and real RFI reload/output acceptance.
 */
(function(scope) {
    function install(root, state) {
        const identity = state.identity;
        if (!state.entryFocus || state.entryFocus.identity !== identity)
            state.entryFocus = {identity, pending:null, lastConsumed:null};
        const memory = state.entryFocus;
        let disposed = false, frame = null, observer = null;
        const listeners = [];
        const current = () => !disposed && root.isConnected && root._epcWorkspace === state && state.identity === identity;
        const owned = node => Boolean(node?.isConnected && root.contains(node) &&
            !node.closest('[data-stale="true"],[inert]'));
        const editorOf = node => node?.closest('.st-key-epc_edit_monthly_rfi');
        const single = values => values.length === 1 ? values[0] : null;
        function nativeButton(origin) {
            return single(Array.from(root.querySelectorAll('.st-key-' + CSS.escape(origin) + ' button'))
                .filter(owned));
        }
        function stopWatching() {
            if (observer) {observer.disconnect(); observer = null;}
            if (frame !== null) {cancelAnimationFrame(frame); frame = null;}
        }
        function cancel() {memory.pending = null; stopWatching();}
        function tryFocus() {
            frame = null;
            const intent = memory.pending;
            if (!intent) {stopWatching(); return;}
            if (!current() || document.hidden || intent.identity !== identity) {cancel(); return;}
            const editor = single(Array.from(root.querySelectorAll('.st-key-epc_edit_monthly_rfi')).filter(owned));
            if (!editor) return;
            const matches = Array.from(editor.querySelectorAll('[data-epc-entry-focus]')).filter(marker =>
                owned(marker) && marker.dataset.epcOriginKey === intent.origin &&
                marker.dataset.epcEntryFocus && !intent.before.has(marker.dataset.epcEntryFocus) &&
                !(memory.lastConsumed?.origin === intent.origin && memory.lastConsumed.token === marker.dataset.epcEntryFocus));
            const marker = single(matches);
            if (!marker?.dataset.epcFieldKey) return;
            const field = single(Array.from(root.querySelectorAll('.st-key-' + CSS.escape(marker.dataset.epcFieldKey) +
                ' input:not([type="hidden"]),.st-key-' + CSS.escape(marker.dataset.epcFieldKey) + ' textarea'))
                .filter(node => owned(node) && editorOf(node) === editor && !node.disabled && node.getClientRects().length));
            if (!field) return;
            const active = document.activeElement;
            // A replacement can briefly leave focus on the document body.
            // A newly chosen control is a cancellation, not a focus target.
            if (active && active !== document.body && active !== document.documentElement &&
                active !== intent.active && active !== nativeButton(intent.origin)) {cancel(); return;}
            memory.lastConsumed = {origin:intent.origin, token:marker.dataset.epcEntryFocus};
            cancel(); // Consume before focusin/scroll, so neither can re-enter.
            field.focus({preventScroll:true});
            if (document.activeElement === field)
                field.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
        }
        function schedule() {
            if (current() && memory.pending && frame === null) frame = requestAnimationFrame(tryFocus);
        }
        function watch() {
            if (!observer && memory.pending && current()) {
                observer = new MutationObserver(schedule);
                observer.observe(root, {childList:true,subtree:true,attributes:true,
                    attributeFilter:['data-stale','inert','disabled','data-epc-entry-focus','data-epc-field-key','data-epc-origin-key']});
            }
            schedule();
        }
        function click(event) {
            if (!current() || event.isTrusted !== true || event.defaultPrevented ||
                event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
            const button = event.target?.closest?.('button');
            const editor = editorOf(button);
            if (!owned(button) || !editor || button.disabled || button.getAttribute('aria-disabled') === 'true') return;
            const origins = Array.from(editor.querySelectorAll('[data-epc-entry-origin]')).filter(marker =>
                owned(marker) && marker.dataset.epcEntryOrigin && nativeButton(marker.dataset.epcEntryOrigin) === button);
            const origin = single(origins)?.dataset.epcEntryOrigin;
            if (!origin) return;
            const before = new Set(Array.from(editor.querySelectorAll('[data-epc-entry-focus]'))
                .map(marker => marker.dataset.epcEntryFocus).filter(Boolean));
            memory.pending = {identity,origin,before,active:document.activeElement};
            watch();
        }
        function moved(event) {
            if (memory.pending && event.isTrusted !== false) cancel();
        }
        function focusMoved(event) {
            if (!memory.pending) return;
            if (event.target !== nativeButton(memory.pending.origin)) cancel();
        }
        function visibility() {if (document.hidden) cancel();}
        function listen(target, type, callback) {
            target.addEventListener(type, callback, true);
            listeners.push(() => target.removeEventListener(type, callback, true));
        }
        listen(root, 'click', click);
        // A trusted assistive-technology activation may deliver click without
        // pointerdown or keydown. Document capture cancels the former intent
        // before this root's native Add capture can arm its own new one.
        // Paste, dictation and IME can deliver input while the previously
        // focused field stays active, without another key or pointer event.
        for (const type of ['pointerdown','keydown','click','wheel','touchstart',
            'beforeinput','input','compositionstart','compositionupdate','compositionend']) listen(document, type, moved);
        listen(document, 'focusin', focusMoved);
        listen(document, 'visibilitychange', visibility);
        listen(window, 'pagehide', cancel);
        // A top-level rerender reinstalls this display adapter before the new
        // row arrives. Preserve only this report's captured intent across that
        // synchronous handoff, then stop watching as soon as it is resolved.
        if (document.hidden) cancel(); else watch();
        return () => {
            if (disposed) return;
            disposed = true;
            stopWatching();
            listeners.forEach(remove => remove());
        };
    }
    scope.ENFRAEntryFocus = Object.freeze({install});
})(globalThis);
