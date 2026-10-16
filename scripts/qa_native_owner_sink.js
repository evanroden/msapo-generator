/* Bounded observations for the separately served diagnostic client only.
 * No global native replacement, layout measurement, scheduling or DOM writes.
 */
(() => {
  "use strict";
  if (location.origin !== "http://127.0.0.1:8529") return;
  const key = "__enfraNativeOwnerObservation";
  if (Object.prototype.hasOwnProperty.call(globalThis, key)) return;
  const state = {schema: "enfra-native-owner-observation-v1", origin: location.origin,
    timeOrigin: performance.timeOrigin, registrationLimit: 64, callbackLimit: 512,
    registrations: [], callbacks: [], totalRegistrations: 0, totalCallbacks: 0,
    droppedRegistrations: 0, droppedCallbacks: 0, droppedTargets: 0, diagnosticErrors: 0,
    firstError: null, installed: false};
  const targets = new WeakMap();
  let nextTarget = 0, sequence = 0;
  const token = value => typeof value === "string" ? value.slice(0, 128) : "";
  const context = () => {
    const app = document.querySelector('[data-testid="stApp"]');
    const workspace = document.querySelector('[data-epc-full-render]');
    return {scriptState: token(app?.getAttribute("data-test-script-state")),
      fullRender: token(workspace?.getAttribute("data-epc-full-render")),
      mode: token(workspace?.getAttribute("data-epc-mode"))};
  };
  const target = node => {
    if (!node || (typeof node !== "object" && typeof node !== "function")) return null;
    let id = targets.get(node);
    if (!id) {
      if (nextTarget >= 128) {state.droppedTargets++; return null;}
      id = ++nextTarget; targets.set(node, id);
    }
    return {target: id, tag: token(node.tagName), id: token(node.id),
      testid: token(node.getAttribute?.("data-testid") || node.closest?.("[data-testid]")?.getAttribute("data-testid"))};
  };
  const push = row => {
    state.totalCallbacks++;
    if (state.callbacks.length === state.callbackLimit) {state.callbacks.shift(); state.droppedCallbacks++;}
    state.callbacks.push(row);
  };
  const sink = {
    state,
    register(owner, nodes, box, stack) {
      try {
        const id = ++state.totalRegistrations;
        if (state.registrations.length >= state.registrationLimit) {state.droppedRegistrations++; return 0;}
        state.registrations.push({observer: id, owner: token(owner), at: performance.now(),
          box: token(box), targets: (Array.isArray(nodes) ? nodes : [nodes]).filter(Boolean).slice(0, 2).map(target),
          stack: typeof stack === "string" ? stack.split("\n").slice(0, 6)
            .map(line => line.replace(/https?:\/\/[^/\s)]+/g, "<origin>").slice(0, 240)).join("\n") : "",
          ...context()});
        return id;
      } catch {state.diagnosticErrors++; return 0;}
    },
    start(observer, entries) {
      try {
        push({sequence: ++sequence, observer, phase: "start", at: performance.now(),
          entryCount: entries.length, entries: Array.prototype.slice.call(entries, 0, 3).map(entry => {
            const box = entry.contentRect;
            return {...target(entry.target), width: Number.isFinite(box?.width) ? box.width : null,
              height: Number.isFinite(box?.height) ? box.height : null};
          }), ...context()});
      } catch {state.diagnosticErrors++;}
    },
    end(observer) {
      try {push({sequence: ++sequence, observer, phase: "end", at: performance.now(), ...context()});}
      catch {state.diagnosticErrors++;}
    }
  };
  Object.defineProperty(globalThis, key, {value: Object.freeze(sink)});
  // Preserve the bounded owner window at the first native error, even when the
  // unchanged journey continues to its terminal strict error assertion.
  // This listener never cancels, filters or classifies any error.
  window.addEventListener("error", event => {
    try {
      if (!state.firstError) state.firstError = {at: performance.now(),
        message: token(event.message), registrations: state.registrations.slice(),
        callbacks: state.callbacks.slice(), droppedRegistrations: state.droppedRegistrations,
        droppedCallbacks: state.droppedCallbacks, droppedTargets: state.droppedTargets};
    } catch {state.diagnosticErrors++;}
  }, {capture: true, passive: true});
  state.installed = true;
})();
