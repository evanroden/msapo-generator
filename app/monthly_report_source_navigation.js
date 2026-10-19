// Display-only navigation between final review and the one native source form.
// It never reads/writes input values or submits an edit. The caller disposes it
// with its workspace; only a same-report reading anchor survives a full rerun.
globalThis.ENFRASourceReviewNavigation = {
    install(app, state) {
        let disposed = false, frame = null;
        function returnLinks() {
            app.querySelectorAll('.enfra-source-review-return').forEach(link => {
                link.hidden = link.dataset.sourceId !== state.sourceReviewReturn?.source;
            });
        }
        function owner(node) {
            for (let p = node.parentElement; p; p = p.parentElement)
                if (p.scrollHeight > p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY)) return p;
            return document.scrollingElement;
        }
        function later(fn, boundary) {
            const animations = boundary?.getAnimations?.({subtree:true}) || [];
            Promise.allSettled(animations.filter(a => a.playState === 'running').map(a => a.finished)).then(() => {
                if (!disposed) frame = requestAnimationFrame(() => {frame=null;if (!disposed) fn();});
            });
        }
        function click(event) {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
            const link = event.target?.closest?.('a');
            if (!link || !app.contains(link)) return;
            if (link.classList.contains('enfra-source-review-return')) {
                const prior = state.sourceReviewReturn;
                const review = app.querySelector('#report-review');
                if (!prior || !review) return;
                event.preventDefault();
                const original = prior.link?.isConnected ? prior.link : review;
                const scroll = owner(original);
                const top = original === review ? prior.reviewTop : prior.linkTop;
                original.setAttribute('tabindex', '-1');
                original.focus({preventScroll:true});
                scroll.scrollTop += original.getBoundingClientRect().top - top;
                state.sourceReviewReturn = null;
                returnLinks();
                return;
            }
            const match = /^#source-details-(.+)--(site|date)$/.exec(link.getAttribute('href') || '');
            if (!match) return;
            const marker = document.getElementById('source-details-' + match[1]);
            const boundary = marker?.closest('[class*="st-key-source_detail_editor_"]');
            const review = app.querySelector('#report-review');
            if (!boundary || !review) return; // Keep the native anchor fallback.
            const labels = match[2] === 'site' ? ['Source sites', 'Source facility'] : ['Source date'];
            let field = labels.map(label => boundary.querySelector('input[aria-label="'+label+'"]')).find(Boolean);
            if (!field && match[2] === 'date') {
                // The native scalar date input announces "Select a date."
                // Its visible widget label identifies this source's field.
                const widget = [...boundary.querySelectorAll('[data-testid="stDateInput"]')].find(
                    node => node.querySelector('label')?.textContent.trim() === 'Source date');
                field = widget?.querySelector('input');
            }
            if (!field || field.disabled) return;
            event.preventDefault();
            state.sourceReviewReturn = {source:match[1], link,
                linkTop:link.getBoundingClientRect().top, reviewTop:review.getBoundingClientRect().top};
            // Activate the native summary so Streamlit updates the body's
            // inert state as well as details.open. Setting open alone makes
            // the form visible while leaving its inputs unable to take focus.
            // Opening the disclosure never submits or accepts source details.
            const parents=[];
            for(let p=boundary.parentElement;p;p=p.parentElement) if(p.tagName==='DETAILS') parents.unshift(p);
            [...parents,...boundary.querySelectorAll('details')].forEach(details => {
                if (!details.open) details.querySelector(':scope > summary')?.click();
            });
            returnLinks();
            later(() => {
                if (!field.isConnected) return;
                field.focus({preventScroll:true});
                field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
            }, boundary);
        }
        app.addEventListener('click', click);
        // A valid correction can remove its warning and form. The keyed return
        // location stays mounted; reveal it again after that ordinary rerun.
        returnLinks();
        return () => {disposed=true;if(frame!==null)cancelAnimationFrame(frame);app.removeEventListener('click',click);};
    },
};
