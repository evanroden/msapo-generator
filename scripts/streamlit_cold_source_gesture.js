/* Keep a pressed native source-warning button under the pointer while native
 * lazy widgets hydrate above it. This runs in the entry, before BidiComponent.
 * It never activates a control, consumes an event, or retains a report action.
 */
(() => {
  let pressed = null;
  const stop = () => {
    if (!pressed) return;
    pressed.resize.disconnect();
    cancelAnimationFrame(pressed.frame);
    pressed = null;
  };
  const current = state => {
    const {button, marker, workspace, main, identity, sourceId} = state;
    return !document.hidden && button.isConnected && marker.isConnected && workspace.isConnected &&
      main.isConnected && !button.disabled && !button.closest('[inert], [data-stale="true"]') &&
      marker.dataset.reportIdentity === identity && marker.dataset.sourceId === sourceId &&
      workspace.querySelector('.enfra-source-correction-owner')?.dataset.reportIdentity === identity &&
      !workspace.dataset.epcMode && document.querySelectorAll('.st-key-epc_workspace_monthly').length === 1;
  };
  const adjust = () => {
    const state = pressed;
    if (!state) return;
    if (!current(state) || Math.abs(state.main.scrollTop - state.scrollTop) > 1) {
      stop(); return;
    }
    const rect = state.button.getBoundingClientRect();
    if (!rect.width || !rect.height || Math.abs(rect.x - state.x) > 1) { stop(); return; }
    const delta = rect.y - state.y;
    if (Math.abs(delta) > 0.5) {
      state.main.scrollTo({top: state.main.scrollTop + delta, left: state.main.scrollLeft, behavior: 'instant'});
      state.scrollTop = state.main.scrollTop;
      if (Math.abs(state.button.getBoundingClientRect().y - state.y) > 1) stop();
    }
  };
  const frame = () => {
    adjust();
    if (pressed) pressed.frame = requestAnimationFrame(frame);
  };
  document.addEventListener('pointerdown', event => {
    stop();
    if (!event.isTrusted || !event.isPrimary || event.button !== 0 || event.pointerType !== 'mouse') return;
    const button = event.target.closest?.('button');
    const group = button?.closest('[class*="st-key-monthly_source_warning_"]');
    const marker = group?.querySelector('.enfra-source-warning');
    const workspace = document.querySelector('.st-key-epc_workspace_monthly');
    const main = button?.closest('[data-testid="stMain"]');
    const block = main?.querySelector('[data-testid="stMainBlockContainer"]');
    const identity = marker?.dataset.reportIdentity;
    const sourceId = marker?.dataset.sourceId;
    if (!button || !marker || !workspace || !main || !block || (!/^[a-f0-9]{24}$/.test(identity || '') || !/^[a-f0-9]{64}$/.test(sourceId || ''))) return;
    const rect = button.getBoundingClientRect();
    const state = {button, marker, workspace, main, identity, sourceId, x:rect.x, y:rect.y,
      pointerId:event.pointerId, pointerX:event.clientX, pointerY:event.clientY,
      scrollTop:main.scrollTop, frame:0, resize:new ResizeObserver(adjust)};
    if (!current(state)) { state.resize.disconnect(); return; }
    pressed = state;
    state.resize.observe(block);
    state.resize.observe(button);
    state.frame = requestAnimationFrame(frame);
  }, {capture:true, passive:true});
  document.addEventListener('pointermove', event => {
    if (pressed && (event.pointerId !== pressed.pointerId ||
        Math.hypot(event.clientX - pressed.pointerX, event.clientY - pressed.pointerY) > 4)) stop();
  }, {capture:true, passive:true});
  for (const type of ['pointerup', 'pointercancel', 'wheel', 'keydown'])
    document.addEventListener(type, stop, {capture:true, passive:true});
  for (const type of ['blur', 'pagehide']) window.addEventListener(type, stop);
  document.addEventListener('visibilitychange', stop);
})();
