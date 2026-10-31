export default function(component) {
    const root = document.querySelector('.st-key-' + CSS.escape(component.data.owner));
    if (!root) return;
    const descriptions = new WeakMap();
    function describe() {
        if (!root.isConnected) return;
        for (const container of root.querySelectorAll('[data-testid="stImageContainer"]')) {
            const caption = container.querySelector('[data-testid="stImageCaption"]');
            const image = container.querySelector('img');
            // Scope each description to its own native image; do not invent
            // a purpose for a missing caption or borrow another card's text.
            const text = caption?.textContent?.trim();
            if (!image) continue;
            const previous = descriptions.get(image), current = image.getAttribute('alt');
            if (text) {
                const original = previous && current === previous.applied ? previous.original : current;
                descriptions.set(image, {original, applied:text});
                if (current !== text) image.setAttribute('alt', text);
            } else if (previous) {
                if (current === previous.applied) {
                    if (previous.original === null) image.removeAttribute('alt');
                    else image.setAttribute('alt', previous.original);
                }
                descriptions.delete(image);
            }
        }
    }
    const observer = new MutationObserver(describe);
    observer.observe(root, {subtree:true, childList:true, characterData:true,
                            attributes:true, attributeFilter:['alt']});
    describe();
    return () => observer.disconnect();
}
