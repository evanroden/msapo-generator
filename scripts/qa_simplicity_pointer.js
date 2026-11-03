(() => {
  if (location.origin !== 'http://127.0.0.1:8543') return;
  const rows = [];
  window.__enfraSimplicityPointer = rows;
  for (const type of ['pointerdown', 'pointerup', 'click']) {
    document.addEventListener(type, event => {
      try {
        if (rows.length >= 192) return;
        const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Add totals to summary');
        if (!button) return;
        const r = button.getBoundingClientRect();
        const node = document.querySelector('[data-monthly-simplicity-receipt]');
        const receipt = node ? JSON.parse(node.getAttribute('data-monthly-simplicity-receipt')) : null;
        rows.push({type, at: Date.now(), receipt:receipt ? {fingerprint:receipt.fingerprint,sources:receipt.sources}:null, x:event.clientX, y:event.clientY,
          targetIsButton: event.target === button || button.contains(event.target),
          targetTag: event.target?.tagName || null, connected:button.isConnected,
          rect:{x:r.x,y:r.y,width:r.width,height:r.height}, scroll:[scrollX,scrollY],
          scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
          panelVisible:[...document.querySelectorAll('div[class*="_source_manager_panel"]')].map(p=>getComputedStyle(p).display !== 'none')});
      } catch (_) {}
    }, true);
  }
})();
