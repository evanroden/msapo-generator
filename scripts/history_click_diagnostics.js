/* Passive synthetic QA only. No labels, values, URLs, HTML or raw identities. */
(() => {
  let active = null, last = null;
  function stop() {
    if (!active) return last;
    const current = active;
    current.data.stopped = true;
    active = null;
    if (current.frame !== null) cancelAnimationFrame(current.frame);
    for (const type of ['pointerdown', 'pointerup', 'pointercancel', 'click'])
      document.removeEventListener(type, current.listener, true);
    last = current.data;
    return last;
  }
  function start(node, observation) {
    stop();
    const app = node.closest('[data-testid="stApp"]');
    const owner = node.closest('[class*="_history_open"]');
    const key = [...(owner?.classList || [])].find(name => name.startsWith('st-key-') && name.endsWith('_history_open'));
    const ids = new WeakMap(); let ordinal = 0;
    const id = element => {
      if (!element || typeof element !== 'object') return 0;
      if (!ids.has(element)) ids.set(element, ++ordinal);
      return ids.get(element);
    };
    const number = value => Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
    const rect = element => {
      if (!element?.isConnected) return null;
      const value = element.getBoundingClientRect();
      return [value.x, value.y, value.width, value.height].map(number);
    };
    const currentSummary = () => key ? app?.querySelector('.' + CSS.escape(key) + ' summary') : node;
    const data = {samples: [], events: [], truncated: false, stopped: false};
    observation.diagnostic = data;
    const current = {data, frame: null, bytes: 0, listener: null};
    active = current;
    function finish() { data.stopped = true; stop(); }
    function append(kind, value) {
      const size = JSON.stringify(value).length;
      if (data[kind].length >= (kind === 'events' ? 32 : 128) || current.bytes + size > 65536) {
        data.truncated = true; finish(); return;
      }
      current.bytes += size;
      data[kind].push(value);
    }
    const begun = performance.now();
    const time = () => number(performance.now() - begun);
    current.listener = event => {
      if (!event.isTrusted || active !== current) return;
      const summary = currentSummary(), target = event.target;
      const pair = target?.closest?.('.epc-workspace-pair');
      const pairs = [...(app?.querySelectorAll('.epc-workspace-pair') || [])].slice(0, 32);
      const category = summary?.contains(target) ? 'history' : target?.closest?.('summary') ? 'summary' :
        target?.closest?.('button') ? 'button' : target?.closest?.('input,textarea,select') ? 'input' : 'other';
      append('events', {time: time(), type: event.type, trusted: true, category,
        target: id(target), summary: id(summary), sameSummary: summary === node,
        pair: pairs.indexOf(pair), x: number(event.clientX), y: number(event.clientY),
        rect: rect(summary)});
    };
    for (const type of ['pointerdown', 'pointerup', 'pointercancel', 'click'])
      document.addEventListener(type, current.listener, {capture: true, passive: true});
    function sample() {
      if (active !== current) return;
      current.frame = null;
      const summary = currentSummary();
      const port = app?.querySelector('[data-testid="stMain"]');
      const pairs = [...(app?.querySelectorAll('.epc-workspace-pair') || [])].slice(0, 32);
      append('samples', {time: time(), summary: id(summary), sameSummary: summary === node,
        rect: rect(summary), scrollTop: number(port?.scrollTop),
        pairs: pairs.map((pair, index) => [index, ...(rect(pair) || []),
          pair.querySelectorAll('[data-testid="stSkeleton"]').length])});
      if (active === current) current.frame = requestAnimationFrame(sample);
    }
    sample();
  }
  window.__enfraHistoryClickProbe = {start, stop: () => {
    if (active) active.data.stopped = true;
    return stop();
  }, last: () => active?.data || last};
})();
