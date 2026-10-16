"use strict";
const assert = require("node:assert/strict");
const sources = JSON.parse(process.argv[2]);

for (const sabotage of [false, true]) {
  for (const observed of [false, true]) {
    const effects = [], calls = [], notes = [], marker = new Error("original callback failure");
    let callback, originalCalls = 0;
    class Native {
      constructor(fn) {callback = fn; calls.push(["construct"]);}
      observe(...args) {calls.push(["observe", ...args]);}
      unobserve(...args) {calls.push(["unobserve", ...args]);}
    }
    const sink = {register: (...args) => {notes.push(["register", ...args]); return 7;},
      start: (...args) => {notes.push(["start", ...args]); if (sabotage) throw Error("bad sink");},
      end: (...args) => {notes.push(["end", ...args]); if (sabotage) throw Error("bad sink");}};
    const global = {__enfraNativeOwnerObservation: sink};
    const window = {ResizeObserver: Native};
    const make = new Function("u", "Ze", "Yt", "window", "globalThis",
      '"use strict";' + (observed ? sources.observedXt : sources.xt) + ";return Xt;");
    const xt = make({useEffect: fn => effects.push(fn)}, fn => fn, () => true, window, global);
    const node = {}, onResize = () => {originalCalls++; if (originalCalls === 2) throw marker;};
    xt({ref: {current: node}, box: "border-box", onResize, enfraOwner: "actual-test-owner"});
    const cleanup = effects[0]();
    assert.equal(window.ResizeObserver, Native);
    assert.equal(callback.call({native: true}, []), undefined);
    assert.equal(originalCalls, 0);
    assert.equal(callback.call({native: true}, [{}]), undefined);
    assert.equal(originalCalls, 1);
    assert.throws(() => callback([{}]), error => error === marker);
    assert.equal(originalCalls, 2);
    cleanup();
    assert.deepEqual(calls, [["construct"], ["observe", node, {box: "border-box"}], ["unobserve", node]]);
    if (observed) {
      assert.equal(notes[0][0], "register"); assert.equal(notes[0][1], "actual-test-owner");
      assert.equal(notes.filter(row => row[0] === "start").length, 3);
      assert.equal(notes.filter(row => row[0] === "end").length, 3);
    } else assert.equal(notes.length, 0);
  }
}

function floating(code, elementResize, animationFrame, sabotage) {
  const calls = [], notes = [], frames = [];
  let observer, count = 0;
  const marker = new Error("original floating update failure"), reference = {}, surface = {};
  class Native {
    constructor(fn) {this.callback = fn; observer = this; calls.push(["construct"]);}
    observe(node) {calls.push(["observe", node]);}
    unobserve(node) {calls.push(["unobserve", node]);}
    disconnect() {calls.push(["disconnect"]);}
  }
  const sink = {register: (...args) => {notes.push(["register", ...args]); return 9;},
    start: (...args) => {notes.push(["start", ...args]); if (sabotage) throw Error("sink failure");},
    end: (...args) => {notes.push(["end", ...args]); if (sabotage) throw Error("sink failure");}};
  const make = new Function("Mt", "O", "nn", "X", "tn", "ResizeObserver", "requestAnimationFrame", "cancelAnimationFrame", "globalThis",
    '"use strict";' + code + ";return rn;");
  const raf = fn => {frames.push(fn); return frames.length;}, cancel = id => calls.push(["cancel", id]);
  const rn = make(node => node, () => [], () => {throw Error("unexpected layoutShift");}, () => ({}), () => true,
    Native, raf, cancel, {__enfraNativeOwnerObservation: sink});
  const cleanup = rn(reference, surface, () => {calls.push(["update"]); count++; if (count === 3) throw marker;},
    {ancestorScroll: false, ancestorResize: false, layoutShift: false, elementResize, animationFrame});
  if (observer) {
    observer.callback([{target: reference, contentRect: {width: 442, height: 38}}]);
    assert.throws(() => observer.callback([{target: surface}]), error => error === marker);
  }
  cleanup();
  return {calls, notes, reference, surface, frames};
}
for (const flag of [false, true]) for (const frame of [false, true]) for (const sabotage of [false, true]) {
  const baseline = floating(sources.rn, flag, frame, sabotage);
  const annotated = floating(sources.observedRn, flag, frame, sabotage);
  const simplify = x => x.calls.map(row => [row[0], ...row.slice(1).map(value => value === x.reference ? "ref" : value === x.surface ? "surface" : value)]);
  assert.deepEqual(simplify(annotated), simplify(baseline));
  assert.equal(annotated.frames.length, baseline.frames.length);
  const registrations = annotated.notes.filter(row => row[0] === "register");
  assert.equal(registrations.length, flag ? 1 : 0);
  if (flag) assert.deepEqual(registrations[0][2].filter(Boolean), frame ? [annotated.surface] : [annotated.reference, annotated.surface]);
}
