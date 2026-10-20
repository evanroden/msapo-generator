/* Opt-in, local-only observations of two controls in the separate logo sample.
 * Never changes a control, focus, event, or Python/application state. */
export default function(component) {
    const panel = component.parentElement.querySelector('[data-input-observations]');
    if (!panel) return;
    const checkboxName = 'Restore this collection as a new shared version';
    const events = [];
    const ids = new WeakMap();
    let nextId = 1, disposed = false;
    const frames = new Set();
    function id(node) {
        if (!node) return null;
        if (!ids.has(node)) ids.set(node, nextId++);
        return ids.get(node);
    }
    function checkbox() {
        return document.querySelector('input[type="checkbox"][aria-label="' + checkboxName + '"]');
    }
    function control(node) {
        if (!(node instanceof Element)) return null;
        const field = checkbox();
        if (field && (node === field || field.closest('label')?.contains(node))) return 'restore-confirmation';
        if (node.closest('[role="combobox"][aria-label="Saved collection"]')) return 'saved-collection';
        return null;
    }
    function state() {
        const field = checkbox();
        return {input: id(field), connected: !!field?.isConnected, checked: !!field?.checked,
            disabled: !!field?.disabled, focusedControl: control(document.activeElement),
            focusedTag: document.activeElement?.tagName || null};
    }
    function append(entry) {
        if (disposed) return;
        events.push({sequence: events.length ? events[events.length - 1].sequence + 1 : 1,
            ...entry, state: state()});
        if (events.length > 80) events.shift();
        panel.textContent = JSON.stringify(events, null, 2);
    }
    function observe(event) {
        const target = control(event.target);
        if (!target) return;
        // Only allowlisted control identities, event mechanics and booleans.
        // No keys, text, option values, actor names or unrelated fields.
        const receipt = {type: event.type, control: target, targetTag: event.target.tagName,
            trusted: event.isTrusted, pointerType: event.pointerType || null,
            button: event.button ?? null, buttons: event.buttons ?? null,
            detail: event.detail ?? null, width: event.width ?? null, height: event.height ?? null,
            defaultPrevented: event.defaultPrevented};
        append(receipt);
        queueMicrotask(() => append({type: event.type + ':settled',
            control: target, defaultPrevented: event.defaultPrevented}));
        const frame = requestAnimationFrame(() => {
            frames.delete(frame);
            append({type: event.type + ':frame', control: target});
        });
        frames.add(frame);
    }
    const types = ['pointerdown', 'pointerup', 'pointercancel', 'mousedown', 'mouseup',
        'click', 'keydown', 'keyup', 'focus', 'blur', 'input', 'change'];
    const options = {capture: true, passive: true};
    types.forEach(type => document.addEventListener(type, observe, options));
    append({type: 'observation-started'});
    return () => {
        disposed = true;
        types.forEach(type => document.removeEventListener(type, observe, options));
        frames.forEach(cancelAnimationFrame);
    };
}
