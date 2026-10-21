/* Passive, bounded observations of the existing synthetic Training form.
 * No focus, input, scroll, dispatch, timing or widget-state mutation. */
(() => {
  const expected = 'Synthetic Person North';
  const original = document.querySelector('input[aria-label="Participants"]');
  if (!original) throw new Error('Synthetic Training participant input is absent.');
  const form = original.closest('[data-testid="stForm"]');
  if (!form) throw new Error('Synthetic Training form is absent.');
  const nodes = new WeakMap(), ownedPopups = new WeakSet(), events = []; let sequence = 0, dropped = 0;
  const identity = node => {
    if (!node) return null;
    if (!nodes.has(node)) nodes.set(node, ++sequence);
    return nodes.get(node);
  };
  const read = () => {
    const input = document.querySelector('input[aria-label="Participants"]');
    const current = input?.closest('[data-testid="stForm"]');
    const container = input?.closest('[data-testid="stMultiSelect"]');
    const date = current?.querySelector('[data-testid="stDateInputField"]');
    return {at:performance.now(), originalConnected:original.isConnected,
      participantNode:identity(input), dateNode:identity(date), formNode:identity(current),
      selected:Array.from(container?.querySelectorAll('[data-tag]') || [], node =>
        node.textContent.trim() === expected ? 'expected-participant' : 'other-participant'),
      filterLength:input?.value.length ?? null, expanded:input?.getAttribute('aria-expanded') ?? null,
      date:date && /^\d{4}\/\d{2}\/\d{2}$/.test(date.value) ? date.value : null,
      dateLength:date?.value.length ?? null,
      fullRender:document.querySelector('.epc-workspace')?.dataset.epcFullRender || null,
      scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') || null};
  };
  const targetInfo = target => {
    const control = target?.closest?.('button,[role="button"],[role="option"],[data-tag],input');
    const option = target?.closest?.('[role="option"]');
    const label = control?.getAttribute('aria-label') || '';
    return {tag:target?.tagName || null, role:target?.getAttribute?.('role') || null,
      controlNode:identity(control), withinParticipant:Boolean(target?.closest?.('[data-testid="stMultiSelect"]')),
      participantOption:option ? (option.textContent.trim() === expected ? 'expected-participant' : 'other-participant') : null,
      field:target?.closest?.('[data-testid="stTextInput"],[data-testid="stDateInput"],[data-testid="stSelectbox"],[data-testid="stMultiSelect"]')?.dataset.testid || null,
      removeExpected:label === 'Remove ' + expected, clearAll:label === 'Clear all', clearDate:label === 'Clear value'};
  };
  let last = '';
  const record = (type, event = null) => {
    const state = read();
    const signature = JSON.stringify({...state, at:0});
    if (type === 'mutation' && signature === last) return;
    last = signature;
    events.push({type, ...state, ...(event ? {...targetInfo(event.target), trusted:event.isTrusted,
      pointerType:event.pointerType || null, pressure:event.pressure ?? null,
      width:event.width ?? null, height:event.height ?? null, detail:event.detail ?? null,
      button:event.button ?? null, buttons:event.buttons ?? null,
      defaultPreventedAtCapture:event.defaultPrevented ?? null,
      key:event.type === 'keydown' ? (/^(Tab|Enter|Escape|Backspace|Delete|Control|Meta|Shift|Alt|Arrow\w+|Home|End|[aA])$/.test(event.key) ? event.key : 'character') : null} : {})});
    if (events.length > 120) {events.shift(); dropped++;}
  };
  const ownsPopup = target => {
    const popup = target?.closest?.('[role="listbox"]');
    if (!popup) return false;
    const input = document.querySelector('input[aria-label="Participants"]');
    if (popup.id && popup.id === input?.getAttribute('aria-controls')) ownedPopups.add(popup);
    // Retain ownership through pointerup/click if selection just closed the
    // popup and cleared aria-controls. Retain only the popup's identity.
    return ownedPopups.has(popup);
  };
  const handler = event => {
    if (form.contains(event.target) || ownsPopup(event.target)) record(event.type, event);
  };
  const types = ['pointerdown','pointerup','click','keydown','focus','blur','input','change'];
  types.forEach(type => document.addEventListener(type, handler, {capture:true, passive:true}));
  const observer = new MutationObserver(() => record('mutation'));
  observer.observe(form, {childList:true, subtree:true, attributes:true, attributeFilter:['aria-expanded','aria-controls']});
  record('installed');
  window.__enfraTrainingFormObservation = {
    capture:() => ({state:read(), events:events.splice(0), dropped}),
    dispose:() => {observer.disconnect(); types.forEach(type => document.removeEventListener(type, handler, true));}
  };
})();
