const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const ORIGIN = 'http://127.0.0.1:8529';

function environment(origin) {
    const listeners = [], calls = {error: 0, rejection: 0, prevent: 0, stop: 0, forbidden: 0};
    let clock = 100;
    const forbid = () => {calls.forbidden++; throw Error('Collector must not schedule or create observers');};
    const originalResizeObserver = function NativeResizeObserver() {forbid();};
    const originalError = () => {calls.error++; return false;};
    const originalRejection = () => {calls.rejection++; return false;};
    const window = {
        location: {origin}, performance: {now: () => clock++},
        onerror: originalError, onunhandledrejection: originalRejection,
        ResizeObserver: originalResizeObserver, MutationObserver: forbid, IntersectionObserver: forbid,
        requestAnimationFrame: forbid, cancelAnimationFrame: forbid, setTimeout: forbid, setInterval: forbid,
        dispatchEvent: forbid,
        addEventListener: (kind, callback, options) => listeners.push({kind, callback, options}),
    };
    const context = vm.createContext({window, location: window.location, performance: window.performance,
        ResizeObserver: originalResizeObserver, MutationObserver: forbid, IntersectionObserver: forbid,
        requestAnimationFrame: forbid, cancelAnimationFrame: forbid, setTimeout: forbid, setInterval: forbid,
        console});
    const install = () => vm.runInContext(source, context, {timeout: 1000});
    function emit(kind, fields = {}) {
        const event = {type: kind, defaultPrevented: false,
            preventDefault() {calls.prevent++; this.defaultPrevented = true;},
            stopPropagation() {calls.stop++;}, stopImmediatePropagation() {calls.stop++;}, ...fields};
        for (const listener of listeners) if (listener.kind === kind) listener.callback(event);
        assert.equal(event.defaultPrevented, false);
        assert.equal(calls.prevent, 0); assert.equal(calls.stop, 0);
        // Native dispatch/default handlers are an adapter here; the collector
        // must leave the existing handler identity and return value intact.
        assert.equal(window.onerror, originalError);
        assert.equal(window.onunhandledrejection, originalRejection);
        assert.equal(kind === 'error' ? window.onerror() : window.onunhandledrejection(), false);
        return event;
    }
    return {window, listeners, calls, install, emit, originalResizeObserver};
}

for (const origin of ['http://localhost:8529', 'http://127.0.0.1:8535', 'https://127.0.0.1:8529',
                      'http://127.0.0.1:85290', 'http://127.0.0.2:8529', 'null']) {
    const test = environment(origin); test.install();
    assert.equal(Object.hasOwn(test.window, '__enfraFreshNativeErrors'), false, origin);
    assert.equal(test.listeners.length, 0, origin);
    assert.equal(test.calls.forbidden, 0, origin);
}

const clean = environment(ORIGIN); clean.install();
const descriptor = Object.getOwnPropertyDescriptor(clean.window, '__enfraFreshNativeErrors');
assert(descriptor && descriptor.writable === false, 'Collector is one own nonwrite property');
assert.equal(clean.window.ResizeObserver, clean.originalResizeObserver, 'Native observer API is unchanged');
assert.equal(clean.listeners.length, 2);
assert.deepEqual(clean.listeners.map(row => row.kind).sort(), ['error', 'unhandledrejection']);
for (const row of clean.listeners) {
    assert.equal(row.options.capture, true); assert.equal(row.options.passive, true);
}
const cleanSnapshot = JSON.parse(JSON.stringify(clean.window.__enfraFreshNativeErrors));
assert.equal(cleanSnapshot.schema, 'enfra-fresh-native-errors-v1');
assert.equal(cleanSnapshot.installed, true); assert.equal(cleanSnapshot.origin, ORIGIN);
assert.equal(cleanSnapshot.limit, 16); assert.equal(cleanSnapshot.total, 0);
assert.equal(cleanSnapshot.overflow, 0); assert.deepEqual(cleanSnapshot.errors, []);
const sameCollector = clean.window.__enfraFreshNativeErrors;
clean.emit('error', {message: 'ResizeObserver loop completed with undelivered notifications.',
                    filename: '', lineno: 0, colno: 0, error: null});
const first = JSON.parse(JSON.stringify(sameCollector));
assert.equal(first.total, 1); assert.equal(first.errors.length, 1);
assert.match(first.errors[0].message, /ResizeObserver loop/);
assert.equal(first.errors[0].kind, 'error');
assert(Number.isFinite(first.errors[0].at));
clean.install();
assert.equal(clean.window.__enfraFreshNativeErrors, sameCollector, 'Reinstall cannot replace first evidence');
assert.equal(clean.listeners.length, 2, 'Reinstall cannot duplicate listeners');
assert.equal(sameCollector.total, 1, 'Reinstall cannot clear an earlier error');
clean.emit('unhandledrejection', {reason: new Error('unhandled native rejection')});
clean.emit('error', {target: {tagName: 'IMG', currentSrc: ORIGIN + '/missing-source.png',
                            src: ORIGIN + '/missing-source.png'}, error: null});
assert.equal(sameCollector.total, 3, 'Resource errors and rejections are unfiltered');
assert.equal(sameCollector.errors.length, 3);
assert.equal(sameCollector.errors[1].kind, 'unhandledrejection');
assert.match(sameCollector.errors[1].message, /unhandled native rejection/);
assert.equal(sameCollector.errors[2].kind, 'error');
assert.equal(clean.calls.error, 2); assert.equal(clean.calls.rejection, 1);
assert.equal(clean.calls.forbidden, 0);

const bounded = environment(ORIGIN); bounded.install();
for (let n = 0; n < 20; n++) bounded.emit('error', {message: 'native-window-error-' + n});
const retained = JSON.parse(JSON.stringify(bounded.window.__enfraFreshNativeErrors));
assert.equal(retained.total, 20); assert.equal(retained.overflow, 4);
assert.equal(retained.errors.length, 16);
assert.deepEqual(retained.errors.map(row => row.message), Array.from({length: 16}, (_, n) => 'native-window-error-' + n));
assert.equal(bounded.calls.error, 20); assert.equal(bounded.calls.forbidden, 0);

console.log(JSON.stringify({scope: 'actual collector source in VM with native-window event adapters; no browser',
    clean: cleanSnapshot, ro_only: first, page_errors: [], bounded: retained,
    mixed: JSON.parse(JSON.stringify(sameCollector)),
    exact_origin_guards: true, duplicate_install_idempotent: true, existing_default_handlers_preserved: true,
    no_prevent_default_or_observer_timer_event_api_use: true}));
