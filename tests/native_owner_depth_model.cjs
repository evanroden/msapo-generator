"use strict";
const assert = require("node:assert/strict");
const source = JSON.parse(process.argv[2]);

// These targets begin after the original popup's stable initial deliveries.
// Widths are content-box values from the retained diagnostic, and the2px
// popup/trigger border is independently visible in its inline-style snapshots.
// Depths19/4 are present in after@call529's explicit serialized DOM ancestry.
function scenario({phase = "before-gather", popupDepth = 4, otherPopupObservers = true,
                   changed = true, matchTriggerWidth = true, repaired = false} = {}) {
  const observers = [], frames = [], pending = [], later = [], writes = [], events = [];
  let owner = "", threshold = 0;
  const trigger = {name: "trigger", depth: 19, width: 474, height: 38};
  const input = {name: "input", depth: 20, width: 426, height: 22};
  const popup = {name: "popup", depth: popupDepth, width: 474, height: 300};
  const list = {name: "list", depth: popupDepth + 1, width: 468, height: 300};
  const style = new Proxy({width: "476px"}, {set(target, key, value) {
    writes.push({property: key, value, threshold});
    target[key] = value;
    if (key === "width") {popup.width = parseFloat(value) - 2; list.width = popup.width - 6;}
    return true;
  }});
  const floating = {style};
  // Real rn sees the same popup object as all independently registered owners.
  Object.assign(popup, floating);
  class Native {
    constructor(callback) {this.callback = callback; this.owner = owner; this.targets = new Map(); observers.push(this);}
    observe(target) {this.targets.set(target, {width: target.width, height: target.height}); events.push([this.owner, "observe", target.name]);}
    unobserve(target) {this.targets.delete(target); events.push([this.owner, "unobserve", target.name]);}
    disconnect() {this.targets.clear();}
  }
  const xt = new Function("u", "Ze", "Yt", "window", '"use strict";' + source.xt + ";return Xt;")(
    {useEffect: fn => fn()}, fn => fn, () => true, {ResizeObserver: Native});
  const watch = (name, target, callback) => {owner = name; xt({ref: {current: target}, onResize: callback});};
  const ariaValues = {combo: null, popover: null};
  const combo = new Function("f", "p", "d", "M", "return (" + source.combo + ");")(
    {current: {getBoundingClientRect: () => ({left: 0, right: input.width})}}, {current: null},
    {current: {getBoundingClientRect: () => ({left: input.width, right: trigger.width + 2})}},
    value => {ariaValues.combo = value;});
  const popover = new Function("i", "A", "return (" + source.popover + ");")(
    {triggerRef: {current: {getBoundingClientRect: () => ({width: trigger.width + 2})}}},
    value => {ariaValues.popover = value;});
  watch("aria-combobox", input, combo);
  watch("aria-trigger-position", trigger, () => frames.push(() => {}));
  watch("aria-trigger-width", trigger, popover);
  if (otherPopupObservers) {
    // Same native Xt registrations as the already-patched position/list paths.
    // Their callbacks stay deferred; skipped observations cannot invoke them.
    watch("aria-popup-position", popup, () => frames.push(() => {}));
    watch("aria-list-size", list, () => frames.push(() => {}));
  }
  const rn = new Function("Mt", "O", "nn", "X", "tn", "ResizeObserver", "requestAnimationFrame", "cancelAnimationFrame",
    '"use strict";' + (repaired ? source.rnRepaired : source.rn) + ";return rn;")(
    value => value, () => [], () => () => {}, () => ({}), () => true, Native,
    fn => {frames.push(fn); return frames.length;}, () => {});
  const vr = new Function("gr", "rn", "_r", "_n", "yn", "vn", "bn",
    '"use strict";' + source.vr + ";return vr;")(
    value => value, rn, [], () => ({kind: "offset"}), () => ({}), () => ({}), value => ({kind: "size", ...value}));
  const config = vr({open: true, matchTriggerWidth, flipOptions: false, shiftOptions: false});
  const middleware = config.middleware.find(value => value.kind === "size");
  // Controlled timing seam at the asynchronous computePosition/size middleware
  // boundary. The actual vr apply function is unchanged; there is no claim
  // that Node's controlled checkpoint measures WebKit's rendering checkpoint.
  const update = () => {
    const apply = () => middleware?.apply({rects: {reference: {width: trigger.width + 2}}, elements: {floating: popup}});
    if (phase === "before-gather") pending.push(apply);
    else later.push(apply);
  };
  owner = "floating-auto-update";
  const cleanup = rn(trigger, popup, update, {ancestorScroll: false, ancestorResize: false, layoutShift: false});
  // Settle the existing initial update before the one external resize.
  while (pending.length) pending.shift()();
  while (later.length) later.shift()();
  writes.length = 0;
  if (changed) {trigger.width = 653.5; input.width = 605.5;}
  const active = [];
  for (const observer of observers) {
    const entries = [...observer.targets].filter(([target, last]) => target.width !== last.width || target.height !== last.height)
      .map(([target]) => ({target, contentRect: {width: target.width, height: target.height}}));
    if (entries.length) active.push({observer, entries});
  }
  threshold = active.length ? Math.min(...active.flatMap(value => value.entries.map(entry => entry.target.depth))) : 0;
  for (const {observer, entries} of active) {
    for (const {target} of entries) observer.targets.set(target, {width: target.width, height: target.height});
    observer.callback(entries, observer);
  }
  while (pending.length) pending.shift()();
  // CSSWG gather-active-at-depth distinguishes skipped from deliverable sizes.
  // No artificial loop/error is thrown; these are the model's explicit outputs.
  const skipped = [], deliverable = [];
  for (const observer of observers) for (const [target, last] of observer.targets) {
    if (target.width === last.width && target.height === last.height) continue;
    (target.depth > threshold ? deliverable : skipped).push({owner: observer.owner, target: target.name, depth: target.depth});
  }
  const beforeNextCycle = {popup: popup.width, list: list.width};
  // A later frame is a new observer cycle, with no inherited deep threshold.
  threshold = 0;
  while (frames.length) frames.shift()();
  while (pending.length) pending.shift()();
  while (later.length) later.shift()();
  const compose = new Function("l", "m", "_", "O", "return (" + source.popoverStyle + ");");
  const composed = compose({style: {position: "fixed", top: 0, left: 0}}, null,
    {style: {transform: "translate(16px,474px)"}}, ariaValues.popover);
  assert.equal(composed.width, undefined, "The actual Popover style merge does not consume the width variable");
  if (changed) assert.equal(composed["--trigger-width"], "655.5px");
  // rn unobserves only its own floating target. Other observers keep their own
  // independent subscriptions; the API does not remove those registrations.
  const floatingObserver = observers.find(value => value.owner === "floating-auto-update");
  if (changed) assert.equal(floatingObserver.targets.has(popup), true);
  if (otherPopupObservers) assert.equal(observers.find(value => value.owner === "aria-popup-position").targets.has(popup), true);
  const result = {options: {phase, popupDepth, otherPopupObservers, changed, matchTriggerWidth, repaired},
    threshold, ariaWidthState: ariaValues, directWidthWrites: writes, skipped, deliverable,
    skipErrorCondition: skipped.length > 0, beforeNextCycle,
    popupAfterDelayedCommit: popup.width, rnScopedUnobserve: events.filter(value => value[1] === "unobserve")};
  cleanup();
  return result;
}

const cases = {
  currentCycleWidthCommit: scenario(),
  repairedCurrentCycle: scenario({repaired: true}),
  unchangedWidth: scenario({changed: false}),
  noOtherPopupObserver: scenario({otherPopupObservers: false}),
  nextCycleWidthCommit: scenario({phase: "after-gather"}),
  deeperPopup: scenario({popupDepth: 25}),
  actualMiddlewareDisabled: scenario({matchTriggerWidth: false}),
};
assert.equal(cases.currentCycleWidthCommit.skipErrorCondition, true);
assert.deepEqual(cases.currentCycleWidthCommit.skipped.map(value => value.owner), ["aria-popup-position", "aria-list-size"]);
assert.equal(cases.currentCycleWidthCommit.directWidthWrites[0].value, "655.5px");
assert.equal(cases.currentCycleWidthCommit.beforeNextCycle.popup, 653.5);
for (const name of ["unchangedWidth", "noOtherPopupObserver", "nextCycleWidthCommit", "deeperPopup", "actualMiddlewareDisabled"])
  assert.equal(cases[name].skipErrorCondition, false, name);
assert.equal(cases.nextCycleWidthCommit.beforeNextCycle.popup, 474);
assert.equal(cases.nextCycleWidthCommit.popupAfterDelayedCommit, 653.5);
assert.equal(cases.repairedCurrentCycle.skipErrorCondition, false);
assert.equal(cases.repairedCurrentCycle.beforeNextCycle.popup, 474);
assert.equal(cases.repairedCurrentCycle.popupAfterDelayedCommit, 653.5);
assert.equal(cases.repairedCurrentCycle.directWidthWrites.length, 1);
assert.equal(cases.repairedCurrentCycle.directWidthWrites[0].threshold, 0);
assert.equal(cases.actualMiddlewareDisabled.ariaWidthState.combo, "655.5px");
assert.equal(cases.actualMiddlewareDisabled.ariaWidthState.popover, "655.5px");
assert.equal(cases.actualMiddlewareDisabled.popupAfterDelayedCommit, 474);
process.stdout.write(JSON.stringify({cases, result: "conditional cross-observer resize feedback class reproduced"}));
