export default function(component) {
    const {parentElement, data, setStateValue} = component;
    const root = parentElement.querySelector('.picture-review');
    root._cleanup?.();
    root.replaceChildren();
    let active = true, sent = false;
    const images = [], choices = [], loaded = [];
    const status = document.createElement('div');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.textContent = `Confirm these ${data.pictures.length} pictures are ready (except those left for correction)`;
    confirm.disabled = true;
    const ready = () => active && !sent && images.length === data.pictures.length &&
        images.length > 0 && images.every((img, n) => loaded[n] && img.complete && img.naturalWidth > 0);
    function refresh() {
        confirm.disabled = !ready();
        status.textContent = ready() ? 'All pictures loaded. Inspect every picture before confirming.' :
            sent ? 'Saving picture decisions…' : 'Waiting for every picture to load. Confirmation stays disabled until all are readable.';
    }
    data.pictures.forEach((picture, n) => {
        const figure = document.createElement('figure');
        const title = document.createElement('h4'); title.textContent = picture.title;
        const context = document.createElement('p'); context.textContent = picture.context;
        const img = document.createElement('img'); img.alt = picture.title;
        const error = document.createElement('p'); error.setAttribute('role', 'alert');
        const retry = document.createElement('button'); retry.type = 'button';
        retry.textContent = 'Retry loading this picture'; retry.hidden = true;
        let attempt = 0;
        images.push(img); loaded.push(false);
        function failed() {
            loaded[n] = false; error.textContent = 'This picture could not load. Retry, or use the correction controls below.';
            retry.hidden = false; refresh();
        }
        function load() {
            const current = ++attempt;
            loaded[n] = false; retry.hidden = true; error.textContent = ''; refresh();
            img.onload = async () => {
                try {
                    await img.decode();
                    if (!active || current !== attempt) return;
                    if (!img.complete || !img.naturalWidth) throw new Error('Unreadable image');
                    loaded[n] = true; refresh();
                } catch (_) { if (active && current === attempt) failed(); }
            };
            img.onerror = () => { if (active && current === attempt) failed(); };
            img.src = `data:${picture.mime};base64,${picture.image}`;
        }
        retry.onclick = load;
        const label = document.createElement('label');
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
        checkbox.setAttribute('aria-label', `Leave ${picture.title} for correction`);
        label.append(checkbox, document.createTextNode('Leave for correction'));
        choices.push(checkbox);
        figure.append(title, context, img, error, retry, label); root.append(figure);
        load();
    });
    confirm.onclick = () => {
        if (!ready()) return;
        sent = true; confirm.disabled = true;
        choices.forEach(c => { c.disabled = true; });
        setStateValue('submission', {identity: data.identity, nonce: data.nonce,
            loaded: loaded.slice(), left: choices.map(c => c.checked)});
        refresh();
    };
    root.append(status, confirm); refresh();
    function cleanup() {
        active = false; confirm.disabled = true;
        images.forEach(img => { img.onload = null; img.onerror = null; });
        if (root._cleanup === cleanup) root._cleanup = null;
    }
    root._cleanup = cleanup;
    return cleanup;
}
