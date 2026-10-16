(() => {
  "use strict";
  if (location.origin !== "http://127.0.0.1:8529") return;
  const key = "__enfraFreshNativeErrors";
  if (Object.prototype.hasOwnProperty.call(window, key)) return;
  const state = {schema: "enfra-fresh-native-errors-v1", installed: false,
    origin: location.origin, limit: 16, total: 0, overflow: 0, errors: []};
  Object.defineProperty(window, key, {value: state});
  const text = value => {
    try { return String(value); }
    catch { return "[unprintable native error]"; }
  };
  const record = (kind, event) => {
    state.total++;
    if (state.errors.length >= state.limit) {
      state.overflow++;
      return;
    }
    const message = text(kind === "error"
      ? (event.message ?? event.error ?? "Resource error") : event.reason);
    state.errors.push({kind, message: message.slice(0, 1000),
      message_truncated: message.length > 1000, at: performance.now(),
      filename: typeof event.filename === "string" ? event.filename.slice(0, 300) : "",
      target: typeof event.target?.tagName === "string" ? event.target.tagName : ""});
  };
  window.addEventListener("error", event => record("error", event), {capture: true, passive: true});
  window.addEventListener("unhandledrejection", event => record("unhandledrejection", event),
    {capture: true, passive: true});
  state.installed = true;
})();
