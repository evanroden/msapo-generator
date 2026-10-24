// Execute the exact pinned React Aria scroll-dismissal hook. This is a
// deterministic DOM/event model, not a claim about a historical browser cause.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const [beforePath, afterPath, scenario] = process.argv.slice(2);
function hook(path) {
  const source = fs.readFileSync(path, 'utf8');
  const start = source.indexOf('function Jt(e)');
  const end = source.indexOf('function Yt()', start);
  assert.ok(start >= 0 && end > start, 'known native hook boundary');
  const latestStart = source.indexOf('function Ze('), latestEnd = source.indexOf('var Qe=', latestStart);
  assert.ok(latestStart >= 0 && latestEnd > latestStart);
  return source.slice(latestStart, latestEnd) + source.slice(start, end);
}
function mount(source, {disabled = false, fallback = false} = {}) {
  class Node {
    constructor(parent = null) { this.parentNode = parent; this.scrollTop = 0; this.scrollLeft = 0; }
    contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  }
  class HTMLInputElement extends Node {}
  class HTMLTextAreaElement extends Node {}
  const document = new Node(), root = new Node(document), outer = new Node(root);
  const pane = new Node(outer), input = new HTMLInputElement(pane), textarea = new HTMLTextAreaElement(pane);
  const unrelated = new Node(root), window = {}, handlers = new Set();
  document.scrollingElement = root; document.defaultView = window;
  root.scrollTop = 120; pane.scrollTop = 400;
  for (const node of [root, outer, pane, input, textarea, unrelated]) node.ownerDocument = document;
  const registrations = [], removals = [];
  window.addEventListener = (kind, fn, capture) => {
    assert.equal(kind, 'scroll'); assert.equal(capture, true);
    registrations.push(fn); handlers.add(fn);
  };
  window.removeEventListener = (kind, fn, capture) => {
    assert.equal(kind, 'scroll'); assert.equal(capture, true);
    removals.push(fn); handlers.delete(fn);
  };
  let cleanup, closes = 0;
  const onClose = () => closes++;
  const qt = new WeakMap([[input, onClose]]);
  const native = new Function('u', 'Xe', 'z', 'Node', 'HTMLInputElement', 'HTMLTextAreaElement',
    'L', 'window', 'document', 'qt', `${source};return Jt;`)(
    {useEffect: fn => { cleanup = fn(); }, useRef: value => ({current: value}), useCallback: fn => fn},
    fn => fn(), event => event.target,
    Node, HTMLInputElement, HTMLTextAreaElement, (parent, child) => parent.contains(child),
    window, document, qt);
  native({triggerRef: {current: input}, isOpen: !disabled, onClose: fallback ? undefined : onClose});
  return {root, outer, pane, input, textarea, unrelated, window, document, registrations, removals,
    emit(target) { for (const fn of [...handlers]) fn({target}); },
    cleanup() { cleanup?.(); }, get closes() { return closes; }};
}
function run(source, fixed) {
  const h = mount(source, {disabled: scenario === 'closed', fallback: scenario === 'fallback'});
  const target = {ancestor: h.pane, document: h.document, window: h.window}[scenario];
  if (target) {
    // The scroll position changed before opening. Its queued event arrives
    // afterwards, with no further movement since the listener was registered.
    h.emit(target);
    assert.equal(h.closes, fixed ? 0 : 1, 'a queued pre-opening scroll must not close the newly opened menu');
  } else if (scenario === 'later-scroll' || scenario === 'fallback') {
    h.pane.scrollTop = 42; h.emit(h.pane);
    assert.equal(h.closes, 1, 'real later ancestor scrolling still dismisses');
  } else if (scenario === 'later-document-scroll') {
    h.root.scrollLeft = 9; h.emit(h.document);
    assert.equal(h.closes, 1, 'real document scrolling still dismisses');
  } else if (scenario === 'input-and-unrelated') {
    h.input.scrollLeft = 12; h.emit(h.input);
    h.textarea.scrollTop = 12; h.emit(h.textarea);
    h.unrelated.scrollTop = 12; h.emit(h.unrelated);
    assert.equal(h.closes, 0, 'native input and unrelated scrolling do not dismiss');
  } else if (scenario === 'closed') {
    assert.equal(h.registrations.length, 0); h.emit(h.pane); assert.equal(h.closes, 0);
  } else if (scenario === 'cleanup') {
    assert.equal(h.registrations.length, 1); h.cleanup();
    assert.deepEqual(h.removals, h.registrations);
    h.pane.scrollTop = 99; h.emit(h.pane); assert.equal(h.closes, 0);
  } else throw new Error(`Unknown scenario ${scenario}`);
  h.cleanup();
}
run(hook(beforePath), false);
run(hook(afterPath), true);
console.log(`native scroll dismissal: ${scenario} passed`);
