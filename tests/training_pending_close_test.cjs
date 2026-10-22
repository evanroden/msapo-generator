// Execute the exact native selection/state/close/scroll callbacks across the
// pending-effect-before-selected-commit window. This is a causal negative
// control, not proof of the precise callback timing in an archived browser.
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

function model(path, fixed) {
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
  const initial = scenario === 'precommit-existing' ? ['Synthetic Person South'] : [];
  const expected = [...initial, 'Synthetic Person North'];
  const state = {filter: 'Synthetic Person North', selected: [], closes: 0, writes: []};
  const k = {current: true}, K = {current: []}, O = {current: state.filter};
  const T = value => { state.filter = value; };
  const Pe = new Function('k', 'T', `return ${native.opened}`)(k, T);
  const settings = {getStateFromWidgetMgr: () => initial, getDefaultState: () => initial,
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
    const value = x.map(value => value === 'Synthetic Person North' ? '0' : '1');
    const close = new Function('o', 'i', 'h', 'e', 'C', 'b', 'T', 'v', 'V', 'z',
      'H', 'y', 'ne', `${fixed ? native.repairedClose : native.close};return K;`)(
      'multiple', true, value, {inputValue: state.filter, onChange: change}, null,
      {getItem: () => undefined}, state.filter, value, () => {},
      () => { state.closes++; Pe(false); }, {current: value}, () => {}, () => {});
    overlay.render(() => Jt({triggerRef, isOpen: open, onClose: onClose === undefined ? close : onClose}));
    widget.commit(); overlay.commit();
  }
  function effects() { widget.effects(); overlay.effects(); }
  return {state, initial, expected, render, effects, select() { change([scenario === 'precommit-custom' ? '__creatable__' : '0']); },
    scroll() { pane.scrollTop++; for (const fn of [...listeners]) fn({target: pane}); },
    stop() { overlay.unmount(); assert.equal(listeners.size, 0); }};
}

function run(path, fixed) {
  const h = model(path, fixed);
  h.render(); h.effects();
  h.select();
  // onChange queues the widget value, but clears the filter immediately.
  h.render();
  assert.deepEqual(h.state.selected, h.initial);
  assert.equal(h.state.filter, '');
  if (scenario === 'before-effect') {
    h.scroll();
    h.effects(); h.render(); h.effects(); h.render();
    assert.deepEqual(h.state.selected, h.expected);
  } else {
    h.effects(); // selection is applied, but selected render has not committed
    if (scenario === 'after-commit') h.render();
    h.scroll(); // same latest committed callback still contains empty value
    assert.equal(h.state.closes, 1, 'real scroll closes the popup, never delayed');
    if (scenario === 'after-commit') h.effects();
    h.render();
    assert.deepEqual(h.state.selected, h.expected);
    h.effects(); h.render(); h.effects(); h.render();
    assert.deepEqual(h.state.selected,
      fixed || scenario === 'after-commit' ? h.expected : h.initial,
      'close must not replay a selection older than the pending widget state');
    assert.deepEqual(h.state.writes.at(-1), h.state.selected);
  }

  h.stop();
}
run(beforePath, false);
run(afterPath, true);
console.log(`native Training pending close: ${scenario} passed`);
