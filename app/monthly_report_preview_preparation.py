"""Choose one bounded next-section PDF preparation behind visible work.

This does not claim raster-image readiness. Page decoding keeps its separate
shared cache budget and viewport admission.
"""


def next_preparation(order, visible, registered):
    """Prepare only the immediate included successor to the last visible pane."""
    positions = [index for index, key in enumerate(order) if visible.get(key)]
    if not positions:
        return ()
    following = max(positions) + 1
    if following >= len(order):
        return ()
    key = order[following]
    return (key,) if key in registered else ()


def eligible(state, key):
    return (state.get('visible', {}).get(key, 'visible' not in state)
            or key in state.get('preparing', ()))


def refresh_preparation(state):
    """Reconcile one successor without changing request identities or budgets."""
    selected = next_preparation(state.get('preparation_order', ()),
                                state.get('visible', {}), state.get('requests', {}))
    # Never spend a speculative conversion while visible work is missing,
    # stale, failed or still inside its edit debounce.
    visible_ready = not any(not state.get('cache', {}).get(key)
           or state['cache'][key].get('fingerprint') != state.get('wanted', {}).get(key)
           or state['cache'][key].get('error')
           for key, visible in state.get('visible', {}).items() if visible)
    state['preparing'] = selected
    for key in tuple(state.get('queue', {})):
        if not eligible(state, key) or (not visible_ready and key in selected):
            del state['queue'][key]
    # An unchanged successor already in flight may finish during a current
    # edit. Only admitting new speculative work waits for visible readiness.
    if not visible_ready:
        return
    for key in selected:
        if key in state.get('cache', {}):
            continue
        running = state.get('running')
        if (running and running[:2] == (key, state.get('wanted', {}).get(key))
                and state.get('running_generation', 0)
                    == state.get('generations', {}).get(key, 0)):
            continue
        state['queue'][key] = state['requests'][key]
