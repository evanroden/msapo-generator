"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { resolveDisplayContext: resolve, selectActiveSection: select } = require("../app/workspace_geometry.js");

const box = (x, y, width, height) => ({ x, y, width, height });
const base = (extra = {}) => ({ layout: { width: 1440, height: 1000 },
  visual: { ...box(0, 0, 1440, 1000), scale: 1 }, app: box(0, 0, 1440, 1000),
  scrollport: box(0, 0, 1440, 1000), posture: "unknown", segments: null, ...extra });
const inside = (outer, inner) => {
  assert.ok(inner.x >= outer.x && inner.y >= outer.y);
  assert.ok(inner.x + inner.width <= outer.x + outer.width + 1e-8);
  assert.ok(inner.y + inner.height <= outer.y + outer.height + 1e-8);
};

test("unavailable APIs use working dimensions and preserve unknown posture", () => {
  const result = resolve(base());
  assert.equal(result.mode, "wide");
  assert.equal(result.posture, "unknown");
  assert.equal(result.measuredGap, null);
  assert.equal(result.preview.x - result.editor.width, 12);
  assert.ok(result.editor.width > result.preview.width);
  assert.equal(resolve(base({ app: box(0, 0, 390, 844) })).mode, "compact");
});

test("wide cutoff uses both minimum panes and clearance, independent of orientation", () => {
  assert.equal(resolve(base({ app: box(0, 0, 692, 950) })).mode, "wide");
  assert.equal(resolve(base({ app: box(0, 0, 691, 950) })).mode, "compact");
  assert.equal(resolve(base({ app: box(0, 0, 1200, 239) })).mode, "compact");
  assert.equal(resolve(base({ app: box(0, 0, 692, 950), clearance: 0 })).clearance, 0);
});

test("asymmetric noncentral book keeps actual widths and gap separate from clearance", () => {
  const result = resolve(base({ segments: [box(510, 0, 930, 1000), box(0, 0, 490, 1000)], posture: "folded" }));
  assert.equal(result.mode, "book");
  assert.deepEqual(result.editor, box(0, 0, 484, 1000));
  assert.deepEqual(result.preview, box(516, 0, 924, 1000));
  assert.equal(result.measuredGap, 20);
  assert.equal(result.clearance, 12);
  assert.equal(result.preview.x - result.editor.width, 32);
});

test("continuous label does not erase zero-width crease clearance", () => {
  const result = resolve(base({ segments: [box(0, 0, 600, 1000), box(600, 0, 840, 1000)], posture: "continuous" }));
  assert.equal(result.mode, "book");
  assert.equal(result.measuredGap, 0);
  assert.equal(result.preview.x - result.editor.width, 12);
  assert.equal(result.posture, "continuous");
});

test("visual, app, scrollport and safe edges intersect once without scaling twice", () => {
  const result = resolve(base({ visual: { ...box(100, 80, 1100, 700), scale: 1.5 },
    app: box(160, 100, 1200, 780), scrollport: box(150, 145, 1050, 650),
    safe: { top: 20, right: 30, bottom: 40, left: 10 },
    segments: [box(0, 0, 650, 1000), box(670, 0, 770, 1000)] }));
  assert.deepEqual(result.bounds, box(160, 145, 1010, 595));
  assert.deepEqual(result.editor, box(160, 145, 484, 595));
  assert.deepEqual(result.preview, box(676, 145, 494, 595));
  assert.equal(result.mode, "book");
  inside(result.bounds, result.editor);
  inside(result.bounds, result.preview);
});

test("stacked asymmetric segments put same editor below actual top preview", () => {
  const result = resolve(base({ segments: [box(0, 0, 1440, 390), box(0, 430, 1440, 570)] }));
  assert.equal(result.mode, "tabletop");
  assert.deepEqual(result.preview, box(0, 0, 1440, 384));
  assert.deepEqual(result.editor, box(0, 436, 1440, 564));
  assert.equal(result.measuredGap, 40);
  assert.equal(result.posture, "unknown");
});

test("zero-gap tabletop preserves gutter with off-center boundary and app offsets", () => {
  const result = resolve(base({ app: box(100, 50, 1100, 950),
    segments: [box(0, 0, 1440, 350), box(0, 350, 1440, 650)] }));
  assert.equal(result.mode, "tabletop");
  assert.deepEqual(result.preview, box(100, 50, 1100, 294));
  assert.deepEqual(result.editor, box(100, 356, 1100, 644));
  assert.equal(result.measuredGap, 0);
});

test("reduced visual height conservatively leaves unusable paired presentation", () => {
  const snapshot = base({ posture: "folded", visual: { ...box(0, 0, 1440, 680), scale: 1 },
    segments: [box(0, 0, 1440, 500), box(0, 520, 1440, 480)] });
  const result = resolve(snapshot);
  assert.equal(result.mode, "compact");
  assert.equal(result.reason, "segments-insufficient-space");
  assert.deepEqual(result.editor, box(0, 0, 1440, 494));
  assert.equal(result.preview, null);
  assert.equal(result.posture, "folded");
  assert.equal(resolve({ ...snapshot, visual: { ...box(0, 0, 1440, 1000), scale: 1 } }).mode, "tabletop");
});

test("pan/viewport clipping does not invent a gutter at its non-hinge edge", () => {
  const result = resolve(base({ visual: { ...box(700, 0, 740, 1000), scale: 1 },
    segments: [box(0, 0, 600, 1000), box(620, 0, 820, 1000)] }));
  assert.equal(result.mode, "compact");
  assert.deepEqual(result.editor, box(700, 0, 740, 1000));
  assert.equal(result.measuredGap, 20);
});

test("one valid segment supports ordinary two columns within its own measured area", () => {
  const result = resolve(base({ segments: [box(100, 50, 900, 800)] }));
  assert.equal(result.mode, "wide");
  assert.equal(result.topology, "single");
  inside(box(100, 50, 900, 800), result.editor);
  inside(box(100, 50, 900, 800), result.preview);
});

test("missing, empty, malformed and unexpected API values have named dimension fallback", () => {
  for (const [segments, reason] of [
    [null, "segments-unavailable"], [[], "segments-empty"], [{}, "segments-malformed"],
    [[box(0, 0, NaN, 1000)], "segments-malformed"],
    [[box(0, 0, Infinity, 1000)], "segments-malformed"],
    [[box(0, 0, 0, 1000)], "segments-malformed"],
    [[box(0, 0, -10, 1000)], "segments-malformed"],
    [[box("0", 0, 1440, 1000)], "segments-malformed"],
    [[box(0, 0, 500, 1000), box(500, 0, 500, 1000), box(1000, 0, 440, 1000)], "segments-unsupported-count"],
  ]) {
    const result = resolve(base({ segments }));
    assert.equal(result.reason, reason);
    assert.equal(result.mode, "wide");
    assert.equal(result.topology, "unknown");
  }
});

test("overlapping and diagonal segments do not become book or tabletop", () => {
  for (const segments of [
    [box(0, 0, 800, 1000), box(600, 0, 840, 1000)],
    [box(0, 0, 600, 400), box(700, 500, 740, 500)],
  ]) {
    const result = resolve(base({ segments }));
    assert.equal(result.reason, "segments-unsupported-topology");
    assert.equal(result.mode, "wide");
  }
});

test("hidden, invalid, disjoint and safe-inset-consumed viewports produce no fake panes", () => {
  for (const snapshot of [
    {}, base({ hidden: true }), base({ layout: { width: 0, height: 1000 } }),
    base({ app: box(0, 0, 0, 1000) }), base({ visual: box(0, 0, 1440, NaN) }),
    base({ scrollport: box(2000, 0, 100, 100) }), base({ safe: { top: 1100 } }),
  ]) {
    const result = resolve(snapshot);
    assert.equal(result.mode, "compact");
    assert.equal(result.editor, null);
    assert.equal(result.preview, null);
  }
});

test("resolver is repeatable and does not mutate snapshots", () => {
  const snapshot = base({ segments: [box(0, 0, 600, 1000), box(620, 0, 820, 1000)] });
  const original = structuredClone(snapshot);
  const first = resolve(snapshot);
  for (let index = 0; index < 50; index += 1) assert.deepEqual(resolve(snapshot), first);
  assert.deepEqual(snapshot, original);
});

const sections = [{ id: "a", top: 0, bottom: 500 }, { id: "b", top: 500, bottom: 950 },
  { id: "c", top: 950, bottom: 1500 }];
test("active selection uses reading line with forward and reverse boundary hysteresis", () => {
  assert.equal(select(sections, null, 500), "b");
  assert.equal(select(sections, "a", 500), "a");
  assert.equal(select(sections, "a", 523), "a");
  assert.equal(select(sections, "a", 524), "b");
  assert.equal(select(sections, "b", 499), "b");
  assert.equal(select(sections, "b", 477), "b");
  assert.equal(select(sections, "b", 476), "a");
  assert.equal(select(sections, "a", 1000), "c");
  assert.equal(select(sections, "c", 50), "a");
});

test("selection handles measured lower-pane origin, explicit jump and removed sections", () => {
  const offset = sections.map((value) => ({ ...value, top: value.top + 430, bottom: value.bottom + 430 }));
  assert.equal(select(offset, "a", 950), "a");
  assert.equal(select(offset, "a", 954), "b");
  assert.equal(select(offset, null, 930), "b");
  assert.equal(select(offset, "deleted", 1400), "c");
  assert.equal(select(offset, null, 0), "a");
  assert.equal(select(offset, null, 9999), "c");
});

test("selection ignores invalid/empty rectangles and accepts y/height measurements", () => {
  const values = [{ id: "bad", top: NaN, bottom: 10 }, { id: "zero", top: 10, bottom: 10 },
    { id: "b", y: 500, height: 300 }, { id: "a", y: 0, height: 500 },
    { id: "b", top: 2000, bottom: 2500 }];
  assert.equal(select(values, null, 600), "b");
  assert.equal(select(values, null, 200), "a");
  assert.equal(select(values, "a", NaN), "a");
  assert.equal(select(values, "missing", NaN), null);
  assert.equal(select([], "a", 0), null);
  assert.equal(select(null, "a", 0), null);
  assert.equal(select(sections, "a", 500, 0), "b");
});

// ADP-A07: malformed segment observations must not crash or remove a usable
// ordinary workspace. These are API fault-injection cases, not physical-device
// claims. Keep each case independent so a first failure cannot hide its tail.
for (const [name, segments] of [
  ["one hole", new Array(1)],
  ["two holes", new Array(2)],
  ["missing first segment", [, box(620, 0, 820, 1000)]],
  ["missing second segment", [box(0, 0, 600, 1000), ,]],
  ["overflowing horizontal gap", [box(-1e308, 0, 1e307, 1000), box(1e308, 0, 1e307, 1000)]],
  ["overflowing vertical gap", [box(0, -1e308, 1440, 1e307), box(0, 1e308, 1440, 1e307)]],
]) {
  test(`malformed segment fallback: ${name}`, () => {
    const snapshot = base({ segments });
    const original = structuredClone(snapshot);
    const result = resolve(snapshot);
    assert.equal(result.reason, "segments-malformed");
    assert.equal(result.mode, "wide");
    assert.equal(result.topology, "unknown");
    assert.equal(result.posture, "unknown");
    assert.equal(result.measuredGap, null);
    for (const key of ["bounds", "editor", "preview"]) {
      assert.ok(result[key], key);
      for (const value of Object.values(result[key])) assert.ok(Number.isFinite(value), key);
      inside(result.bounds, result[key]);
    }
    assert.deepEqual(resolve(snapshot), result);
    assert.deepEqual(snapshot, original);
  });
}
