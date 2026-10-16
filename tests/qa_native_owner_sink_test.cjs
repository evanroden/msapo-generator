"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("scripts/qa_native_owner_sink.js", "utf8");

function setup(origin = "http://127.0.0.1:8529") {
  const listeners = [];
  let time = 0, render = "", mode = "";
  const Native = function ResizeObserver() {};
  const state = {location: {origin}, performance: {timeOrigin: 1000, now: () => ++time},
    document: {querySelector: selector => selector.includes("stApp")
      ? {getAttribute: () => "notRunning"}
      : {getAttribute: name => name === "data-epc-full-render" ? render : mode}},
    ResizeObserver: Native, window: {ResizeObserver: Native, addEventListener: (...args) => listeners.push(args)}};
  vm.createContext(state); vm.runInContext(source, state);
  return {state, sink: state.__enfraNativeOwnerObservation, Native, listeners,
    markers: (r, m) => {render = r; mode = m;}};
}
function node(id = "native-month") {
  return {tagName: "INPUT", id, getAttribute: () => "stSelectbox", closest: () => null,
    getBoundingClientRect: () => {throw Error("forbidden layout read");},
    get offsetWidth() {throw Error("forbidden dimension read");}};
}

test("delivered contentRect and current markers identify widths without layout/native changes", () => {
  const h = setup(), n = node(), s = h.sink;
  assert.equal(h.state.ResizeObserver, h.Native); assert.equal(h.state.window.ResizeObserver, h.Native);
  const id = s.register("aria-combobox-input-width", n, "border-box", "Error\nat http://127.0.0.1:8529/static/js/file.js:1:12");
  s.start(id, [{target: n, contentRect: {width: 442, height: 38}}]); s.end(id);
  h.markers("new-full-render", "wide");
  s.start(id, [{target: n, contentRect: {width: 621.5, height: 38}}]); s.end(id);
  assert.deepEqual(Array.from(s.state.callbacks.filter(x => x.phase === "start"), x => x.entries[0].width), [442, 621.5]);
  assert.equal(s.state.callbacks[0].fullRender, "");
  assert.equal(s.state.callbacks[2].fullRender, "new-full-render");
  assert.equal(s.state.callbacks[2].mode, "wide");
  assert.equal(s.state.registrations[0].targets[0].target, s.state.callbacks[0].entries[0].target);
  assert.match(s.state.registrations[0].stack, /<origin>\/static\/js\/file.js/);
  assert.equal(s.state.diagnosticErrors, 0);
  assert.equal(h.listeners.length, 1); assert.equal(h.listeners[0][0], "error");
  assert.equal(h.listeners[0][2].passive, true);
});

test("bounded buffers retain a first error window, count overflow and never suppress errors", () => {
  const h = setup(), s = h.sink, n = node();
  const id = s.register("floating-auto-update", [null, n], undefined, "x".repeat(5000));
  for (let i = 0; i < 2; i++) {s.start(id, [{target: n, contentRect: {width: i, height: 38}}]); s.end(id);}
  let prevented = false;
  h.listeners[0][1]({message: "original native error", preventDefault: () => {prevented = true;}});
  const first = s.state.firstError;
  for (let i = 0; i < 600; i++) {s.register("owner", n, undefined, "stack"); s.start(id, Array(8).fill({target: n, contentRect: {width: i, height: 38}})); s.end(id);}
  h.listeners[0][1]({message: "later error"});
  assert.equal(s.state.registrations.length, 64); assert.equal(s.state.callbacks.length, 512);
  assert.equal(s.state.firstError, first); assert.equal(first.callbacks.length, 4);
  assert.equal(first.message, "original native error"); assert.equal(prevented, false);
  assert.ok(s.state.droppedRegistrations > 0 && s.state.droppedCallbacks > 0);
  assert.equal(s.state.callbacks.find(x => x.phase === "start").entries.length, 3);
  assert.equal(s.state.registrations[0].targets.length, 1);
});

test("wrong origin has no installation and a failed target observation is explicit", () => {
  const wrong = setup("http://127.0.0.1:8535");
  assert.equal(wrong.sink, undefined); assert.equal(wrong.listeners.length, 0);
  const h = setup();
  const id = h.sink.register("owner", {get tagName() {throw Error("broken target");}}, null, "stack");
  assert.equal(id, 0); assert.equal(h.sink.state.diagnosticErrors, 1);
});
