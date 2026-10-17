/* Passive diagnostics for the existing, isolated Training CI server only.
 * Native observer scheduling, methods, callback args/this and errors survive.
 * No layout is requested: sizes come from the delivered entry.contentRect.
 */
(() => {
    'use strict';
    if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1' || location.port !== '8535') return;
    const descriptor = Object.getOwnPropertyDescriptor(window, 'ResizeObserver');
    const Native = window.ResizeObserver;
    if (!descriptor || !('value' in descriptor) || typeof Native !== 'function' ||
        (!descriptor.configurable && !descriptor.writable)) return;
    const evidence = {timeOrigin: performance.timeOrigin, origins: [], callbacks: [], errors: [],
        observers: 0, droppedOrigins: 0, droppedCallbacks: 0, droppedErrors: 0, diagnosticErrors: 0};
    window.__enfraTrainingObserverEvidence = evidence;
    const origins = new Map();
    const push = (key, value, limit) => {
        if (evidence[key].length === limit) {evidence[key].shift(); evidence['dropped' + key[0].toUpperCase() + key.slice(1)]++;}
        evidence[key].push(value);
    };
    const targetInfo = entry => {
        const target = entry.target, box = entry.contentRect;
        const testid = target?.getAttribute?.('data-testid') || target?.closest?.('[data-testid]')?.getAttribute('data-testid') || '';
        const token = value => /^[a-zA-Z0-9_-]{1,64}$/.test(value || '') ? value : '';
        return {tag: token(target?.tagName), testid: token(testid),
            width: Number.isFinite(box?.width) ? box.width : null,
            height: Number.isFinite(box?.height) ? box.height : null};
    };
    const Wrapped = new Proxy(Native, {
        construct(target, args, newTarget) {
            if (typeof args[0] !== 'function') return Reflect.construct(target, args, newTarget);
            const callback = args[0], id = ++evidence.observers;
            let origin = 0, owner = 'unknown';
            try {
                const source = Function.prototype.toString.call(callback);
                owner = source.includes('sizePages()') ? 'report-preview' :
                    source.includes('requestAnimationFrame(measure)') ? 'workspace-layout' : 'framework';
                const stack = String(new Error().stack || '').split('\n').slice(1, 6)
                    .map(line => line.replace(/https?:\/\/[^/\s)]+/g, '<origin>').slice(0, 240)).join('\n');
                const name = String(callback.name || '').slice(0, 40), key = owner + '|' + name + '|' + stack;
                if (origins.has(key)) origin = origins.get(key);
                else if (origins.size < 64) {
                    origin = origins.size + 1; origins.set(key, origin);
                    evidence.origins.push({id: origin, owner, name, stack});
                } else evidence.droppedOrigins++;
            } catch (_) {evidence.diagnosticErrors++;}
            function observed(...values) {
                try {
                    const entries = values[0];
                    push('callbacks', {at: performance.now(), observer: id, origin, owner,
                        entryCount: entries.length, entries: Array.prototype.slice.call(entries, 0, 3).map(targetInfo)}, 96);
                } catch (_) {evidence.diagnosticErrors++;}
                // The original callback runs immediately in the same native delivery.
                // In particular, its exception is neither caught nor filtered.
                return Reflect.apply(callback, this, values);
            }
            return Reflect.construct(target, [observed, ...args.slice(1)], newTarget);
        }
    });
    evidence.nativeBranchBefore = Native.toString().includes('[native code]');
    evidence.nativeBranchAfter = Wrapped.toString().includes('[native code]');
    if (evidence.nativeBranchBefore !== evidence.nativeBranchAfter) {
        evidence.installation = 'native-feature-branch-would-change';
        return;
    }
    Object.defineProperty(window, 'ResizeObserver', {...descriptor, value: Wrapped});
    evidence.installation = 'installed';
    window.addEventListener('error', event => {
        try {
            push('errors', {at: performance.now(), message: String(event.message || '').slice(0, 500),
                nativeEvents: (window.__enfraTrainingDateEvents || []).slice(-8)}, 8);
        } catch (_) {evidence.diagnosticErrors++;}
    }, {passive: true});
})();
