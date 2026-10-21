// Execute the shipped selection, widget-state and scroll callbacks with the
// commit/passive-effect boundary made explicit. This proves a reachable stale
// callback race; it does not identify the cause of an archived browser failure.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const [sourcePath, beforePath, afterPath, scenario] = process.argv.slice(2);
const native = JSON.parse(fs.readFileSync(sourcePath, 'utf8'));

function hooks() {
  let cursor = 0;
  const slots = [], passive = [], insertion = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const effect = queue => (fn, deps) => {
    const index = cursor++, previous = slots[index];
    if (previous && same(previous.deps, deps)) return;
    const next = {deps, cleanup: previous?.cleanup}; slots[index] = next;
    queue.push(() => { next.cleanup?.(); next.cleanup = fn(); });
  };
  const api = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = {value: typeof initial === 'function' ? initial() : initial,
        set(value) { slots[index].value = typeof value === 'function' ? value(slots[index].value) : value; }};
      return [slots[index].value, slots[index].set];
    },
    useRef(value) { const index = cursor++; return slots[index] ?? (slots[index] = {current: value}); },
    useCallback(fn, deps) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) slots[index] = {deps, fn};
      return slots[index].fn;
    },
    useEffect: effect(passive), useInsertionEffect: effect(insertion),
  };
  return {api, render(fn) { cursor = 0; return fn(); },
    commit() { while (insertion.length) insertion.shift()(); },
    effects() { while (passive.length) passive.shift()(); },
    unmount() { for (const slot of slots) slot?.cleanup?.(); }};
}

function model(path) {
  const source = fs.readFileSync(path, 'utf8');
  const start = source.indexOf('function Jt(e)'), end = source.indexOf('function Yt()', start);
  assert.ok(start >= 0 && end > start);
  class Node {
    constructor(parent = null) { this.parentNode = parent; this.scrollLeft = 0; this.scrollTop = 0; }
    contains(child) { for (let n = child; n; n = n.parentNode) if (n === this) return true; return false; }
  }
  class HTMLInputElement extends Node {}
  class HTMLTextAreaElement extends Node {}
  const document = new Node(), pane = new Node(document), input = new HTMLInputElement(pane);
  document.scrollingElement = pane;
  const listeners = new Set(), window = {
    addEventListener(type, fn) { assert.equal(type, 'scroll'); listeners.add(fn); },
    removeEventListener(type, fn) { assert.equal(type, 'scroll'); listeners.delete(fn); },
  };
  const widget = hooks(), overlay = hooks(), triggerRef = {current: input}, qt = new WeakMap();
  const Jt = new Function('u', 'Xe', 'z', 'Node', 'HTMLInputElement', 'HTMLTextAreaElement',
    'L', 'window', 'document', 'qt', `${native.latest};${source.slice(start, end)};return Jt;`)(
    overlay.api, overlay.api.useInsertionEffect, e => e.target, Node, HTMLInputElement,
    HTMLTextAreaElement, (parent, child) => parent.contains(child), window, document, qt);
  const stateHook = new Function('i', 'n', 'r', `${native.widget};return o;`)(
    widget.api, value => value == null, () => {});
  const state = {filter: 'Synthetic Person North', selected: [], closes: 0, writes: []};
  const k = {current: true}, K = {current: []}, O = {current: state.filter};
  const T = value => { state.filter = value; };
  const Pe = new Function('k', 'T', `return ${native.opened}`)(k, T);
  const settings = {getStateFromWidgetMgr: () => [], getDefaultState: () => [],
    updateWidgetMgrState: (_element, _manager, pending) => state.writes.push([...pending.value]),
    element: {}, widgetMgr: {}};
  let change;
  function render({open = k.current, onClose} = {}) {
    const [x, S] = widget.render(() => stateHook(settings));
    state.selected = x;
    K.current = x.includes('Synthetic Person North') ? [] :
      [{id: '0', value: 'Synthetic Person North'}];
    change = new Function('k', 'K', 'O', 't', 'x', 'S', 'T', `return ${native.change}`)(
      k, K, O, {maxSelections: 0}, x, S, T);
    // These are the native controlled, multiple-selection, custom-value props
    // used by Training. The collection is empty after the sole option is chosen.
    const value = x.length ? ['0'] : [];
    const close = new Function('o', 'i', 'h', 'e', 'C', 'b', 'T', 'v', 'V', 'z',
      'H', 'y', 'ne', `${native.close};return K;`)(
      'multiple', true, value, {inputValue: state.filter, onChange: change}, null,
      {getItem: () => undefined}, state.filter, value, () => {},
      () => { state.closes++; Pe(false); }, {current: value}, () => {}, () => {});
    overlay.render(() => Jt({triggerRef, isOpen: open, onClose: onClose === undefined ? close : onClose}));
    widget.commit(); overlay.commit();
  }
  function effects() { widget.effects(); overlay.effects(); }
  return {state, render, effects, select() { change(['0']); },
    scroll() { pane.scrollTop++; for (const fn of [...listeners]) fn({target: pane}); },
    stop() { overlay.unmount(); assert.equal(listeners.size, 0); }};
}

function run(path, fixed) {
  const h = model(path);
  h.render(); h.effects();
  h.select();
  // onChange queues the widget value, but clears the filter immediately.
  h.render();
  assert.deepEqual(h.state.selected, []);
  assert.equal(h.state.filter, '');
  h.effects(); // applies the selection and installs this render's close handler
  h.render(); // selected tag commits before the replacement passive listener
  assert.deepEqual(h.state.selected, ['Synthetic Person North']);
  if (scenario === 'selection') {
    h.scroll();
    assert.equal(h.state.closes, 1, 'real later ancestor movement still closes');
    h.effects(); h.render(); h.effects(); h.render();
    assert.deepEqual(h.state.selected, fixed ? ['Synthetic Person North'] : [],
      'scroll must not replay the preceding render\'s empty selection');
    assert.deepEqual(h.state.writes.at(-1), h.state.selected);
  } else if (scenario === 'closed' || scenario === 'null-close') {
    h.effects();
    h.render(scenario === 'closed' ? {open: false} : {onClose: null});
    h.scroll();
    assert.equal(h.state.closes, fixed ? 0 : 1, 'committed closed/null state applies before passive cleanup');
    h.effects();
  } else throw new Error(`Unknown scenario ${scenario}`);
  h.stop();
}
run(beforePath, false);
run(afterPath, true);
console.log(`native Training commit/scroll: ${scenario} passed`);
