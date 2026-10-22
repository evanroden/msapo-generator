/* Passive, bounded geometry evidence around the existing native Add click.
 * No widget text/values, timers, observers, scroll, focus, or business events.
 */
(() => {
    const records = [], ids = new WeakMap();
    const labels = new Set(['Add these photos','Remove photo','Done editing photos']);
    let sequence = 0, action = null;
    const identity = node => {
        if (!node) return null;
        if (!ids.has(node)) ids.set(node, ++sequence);
        return ids.get(node);
    };
    const bounds = node => {
        if (!node?.isConnected) return null;
        const r = node.getBoundingClientRect();
        return {x:r.x,y:r.y,width:r.width,height:r.height};
    };
    const capture = event => {
        const target = event.target?.closest?.('button');
        if (event.type === 'pointerdown') {
            action = labels.has(target?.textContent?.trim()) &&
                target.closest('.st-key-epc_pair_monthly_activity') ? target : null;
        }
        if (!action || records.length >= 96) return;
        const status = document.querySelector('.enfra-browser-save-status');
        records.push({type:event.type,time:performance.now(),trusted:event.isTrusted,
            action:identity(action),target:identity(target),connected:action.isConnected,
            button:bounds(action),status:bounds(status),saveState:status?.dataset.saveState || null,
            scroll:document.querySelector('[data-testid="stMain"]')?.scrollTop,
            point:{x:event.clientX,y:event.clientY}});
    };
    for (const type of ['pointerdown','mousedown','pointerup','mouseup','click'])
        document.addEventListener(type,capture,true);
    window.__enfraPhotoActionObservations = () => records.map(item => ({...item}));
})();
