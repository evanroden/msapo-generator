/*
 * Pure display geometry for the first-party workspace adapter.
 *
 * Every rectangle is expressed in layout-viewport CSS pixels. visual.x/y are
 * VisualViewport offsets; its width/height are already CSS pixels. scale is
 * diagnostic only: multiplying these coordinates by it would apply zoom twice.
 * Safe-area insets are applied once, to the visible viewport before intersection.
 * clearance is a chosen TOTAL extra gutter, independent of a measured hinge gap.
 * This file has no DOM, timers, storage, network, or framework dependencies.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ENFRAWorkspaceGeometry = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const positive = (value, fallback) => finite(value) && value > 0 ? value : fallback;
  const nonnegative = (value, fallback = 0) => finite(value) && value >= 0 ? value : fallback;

  function rect(value) {
    if (!value || typeof value !== "object") return null;
    const { x, y, width, height } = value;
    if (![x, y, width, height].every(finite) || width <= 0 || height <= 0) return null;
    if (!finite(x + width) || !finite(y + height)) return null;
    return { x, y, width, height };
  }

  function intersect(a, b) {
    if (!a || !b) return null;
    const x = Math.max(a.x, b.x);
    const y = Math.max(a.y, b.y);
    return rect({ x, y, width: Math.min(a.x + a.width, b.x + b.width) - x,
      height: Math.min(a.y + a.height, b.y + b.height) - y });
  }

  function inset(value, top, right, bottom, left) {
    if (!value) return null;
    return rect({ x: value.x + left, y: value.y + top,
      width: value.width - left - right, height: value.height - top - bottom });
  }

  /**
   * Resolve measured geometry without inferring a device, angle, or keyboard.
   * Missing optional app/scrollport/visual rectangles use the layout viewport;
   * explicitly invalid rectangles fail closed to a nonvisible compact result.
   * Segments are used only when exactly one, or a supported pair, are valid.
   * The adapter may use reason/topology/posture for diagnostics, not approval.
   */
  function resolveDisplayContext(snapshot = {}) {
    if (!snapshot || typeof snapshot !== "object") snapshot = {};
    const clearance = nonnegative(snapshot.clearance, 12);
    const minEditor = positive(snapshot.minEditor, 360);
    const minPreview = positive(snapshot.minPreview, 320);
    const minHeight = positive(snapshot.minHeight, 240);
    const posture = ["continuous", "folded"].includes(snapshot.posture) ? snapshot.posture : "unknown";
    const base = { mode: "compact", bounds: null, editor: null, preview: null,
      measuredGap: null, clearance, posture, topology: "unknown", reason: "invalid-layout" };
    const layout = rect({ x: 0, y: 0, width: snapshot.layout?.width, height: snapshot.layout?.height });
    if (!layout) return base;
    const visual = snapshot.visual == null ? layout : rect(snapshot.visual);
    const app = snapshot.app == null ? layout : rect(snapshot.app);
    const scrollport = snapshot.scrollport == null ? layout : rect(snapshot.scrollport);
    if (!visual || !app || !scrollport) return { ...base, reason: "invalid-working-geometry" };
    const safe = snapshot.safe || {};
    const visible = inset(visual, nonnegative(safe.top), nonnegative(safe.right),
      nonnegative(safe.bottom), nonnegative(safe.left));
    const bounds = intersect(intersect(intersect(layout, visible), app), scrollport);
    if (!bounds) return { ...base, reason: "no-visible-workspace" };

    function dimensionFallback(reason, working = bounds, details = {}) {
      if (!working) return { ...base, bounds, reason: "no-visible-segment", ...details };
      const result = { ...base, bounds, editor: working, reason, ...details };
      if (working.width < minEditor + minPreview + clearance || working.height < minHeight) return result;
      const available = working.width - clearance;
      const editorWidth = Math.min(available - minPreview, Math.max(minEditor, available * 0.56));
      return { ...result, mode: "wide",
        editor: { ...working, width: editorWidth },
        preview: { ...working, x: working.x + editorWidth + clearance, width: available - editorWidth } };
    }

    if (snapshot.hidden === true) return { ...base, bounds, reason: "document-hidden" };
    const rawSegments = snapshot.segments;
    if (rawSegments == null) return dimensionFallback("segments-unavailable");
    if (!Array.isArray(rawSegments)) return dimensionFallback("segments-malformed");
    if (rawSegments.length === 0) return dimensionFallback("segments-empty");
    if (rawSegments.length > 2) return dimensionFallback("segments-unsupported-count");
    // Visit every bounded index: Array#map skips holes, allowing an empty
    // measured segment to hide the editor or throw during pair classification.
    const segments = Array.from({ length: rawSegments.length }, (_, index) => rect(rawSegments[index]));
    if (segments.some((segment) => !segment)) return dimensionFallback("segments-malformed");
    if (segments.length === 1) {
      return dimensionFallback("single-segment", intersect(bounds, segments[0]), { topology: "single" });
    }

    const byX = [...segments].sort((a, b) => a.x - b.x);
    const byY = [...segments].sort((a, b) => a.y - b.y);
    const xGap = byX[1].x - (byX[0].x + byX[0].width);
    const yGap = byY[1].y - (byY[0].y + byY[0].height);
    const overlapY = Math.min(byX[0].y + byX[0].height, byX[1].y + byX[1].height) - Math.max(byX[0].y, byX[1].y);
    const overlapX = Math.min(byY[0].x + byY[0].width, byY[1].x + byY[1].width) - Math.max(byY[0].x, byY[1].x);
    // Finite endpoints can still overflow when subtracted. Do not publish an
    // infinite gap/topology or pass it into display styles and observers.
    if (![xGap, yGap, overlapY, overlapX].every(finite)) return dimensionFallback("segments-malformed");
    const book = xGap >= 0 && overlapY > 0;
    const tabletop = yGap >= 0 && overlapX > 0;
    if (!book && !tabletop) return dimensionFallback("segments-unsupported-topology");

    const topology = book ? "side-by-side" : "stacked";
    const measuredGap = book ? xGap : yGap;
    // Clear only the actual inner edges before clipping to visible/app bounds.
    // Clipping first would add a false gutter at a keyboard or window edge.
    const first = book ? inset(byX[0], 0, clearance / 2, 0, 0) : inset(byY[0], 0, 0, clearance / 2, 0);
    const second = book ? inset(byX[1], 0, 0, 0, clearance / 2) : inset(byY[1], clearance / 2, 0, 0, 0);
    const firstVisible = intersect(first, bounds);
    const secondVisible = intersect(second, bounds);
    const editor = book ? firstVisible : secondVisible;
    const preview = book ? secondVisible : firstVisible;
    const details = { topology, measuredGap };
    if (editor && preview && editor.width >= minEditor && preview.width >= minPreview &&
        editor.height >= minHeight && preview.height >= minHeight &&
        (book ? overlapY >= minHeight : overlapX >= Math.max(minEditor, minPreview))) {
      return { ...base, bounds, mode: book ? "book" : "tabletop", editor, preview,
        ...details, reason: book ? "usable-side-by-side-segments" : "usable-stacked-segments" };
    }
    // A known crease must not become the middle of a generic wide fallback.
    // Keep one usable segment when viewport reduction makes paired work unfit.
    const choices = [editor, preview].filter(Boolean).sort((a, b) =>
      Number(b.width >= minEditor && b.height >= minHeight) - Number(a.width >= minEditor && a.height >= minHeight) ||
      (b.width * b.height) - (a.width * a.height));
    return { ...base, bounds, editor: choices[0] || null, ...details,
      reason: choices.length ? "segments-insufficient-space" : "no-visible-segment" };
  }

  /**
   * Select the section at a viewport-coordinate reading line. Rectangles use
   * {id, top, bottom}, or {id, y, height}. No scroll direction or timer is needed:
   * retain the previous section inside a +/- hysteresis band at the boundary.
   * Pass previousId=null for an explicit jump that must take effect immediately.
   */
  function selectActiveSection(rects, previousId, viewportTop, hysteresis = 24) {
    const seen = new Set();
    const sections = (Array.isArray(rects) ? rects : []).map((value, index) => {
      if (!value || value.id == null || seen.has(value.id)) return null;
      const top = finite(value.top) ? value.top : value.y;
      const bottom = finite(value.bottom) ? value.bottom : top + value.height;
      if (!finite(top) || !finite(bottom) || bottom <= top) return null;
      seen.add(value.id);
      return { id: value.id, top, bottom, index };
    }).filter(Boolean).sort((a, b) => a.top - b.top || a.index - b.index);
    if (!sections.length) return null;
    const previousIndex = sections.findIndex((section) => section.id === previousId);
    if (!finite(viewportTop)) return previousIndex >= 0 ? previousId : null;
    let candidateIndex = 0;
    for (let index = 1; index < sections.length; index += 1) {
      if (sections[index].top > viewportTop) break;
      candidateIndex = index;
    }
    if (previousIndex < 0 || previousIndex === candidateIndex) return sections[candidateIndex].id;
    const band = nonnegative(hysteresis, 24);
    if (candidateIndex > previousIndex && viewportTop < sections[candidateIndex].top + band) return previousId;
    if (candidateIndex < previousIndex && viewportTop > sections[previousIndex].top - band) return previousId;
    return sections[candidateIndex].id;
  }

  return Object.freeze({ resolveDisplayContext, selectActiveSection });
});
