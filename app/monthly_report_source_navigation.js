// Display-only navigation between final review and the one native source form.
// It never reads/writes input values or submits an edit. The caller disposes it
// with its workspace; only a same-report reading anchor survives a full rerun.
globalThis.ENFRASourceReviewNavigation = {
    install(app, state) {
        let disposed = false, frame = null, cancelPending = () => {};
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
        function fieldFor(boundary, kind) {
            const labels = kind === 'site' ? ['Source sites', 'Source facility'] : ['Source date'];
            const field = labels.map(label => boundary.querySelector('input[aria-label="'+label+'"]')).find(Boolean);
            if (field || kind !== 'date') return field;
            // The scalar input announces "Select a date." Its visible widget
            // label identifies this source's date without changing semantics.
            const widget = [...boundary.querySelectorAll('[data-testid="stDateInput"]')].find(
                node => node.querySelector('label')?.textContent.trim() === 'Source date');
            return widget?.querySelector('input');
        }
        function focusWhenReady(boundary, kind) {
            cancelPending();
            let active = true, waiting = false, deadline = null;
            const observer = new MutationObserver(schedule);
            function stop() {
                if (!active) return;
                active = false;
                observer.disconnect();
                if (deadline !== null) clearTimeout(deadline);
                if (frame !== null) {cancelAnimationFrame(frame);frame = null;}
                app.removeEventListener('pointerdown', stop, true);
                app.removeEventListener('keydown', stop, true);
            }
            function schedule() {
                if (!active || disposed || frame !== null) return;
                frame = requestAnimationFrame(() => {frame = null;attempt();});
            }
            function attempt() {
                if (!active || disposed) return;
                if (!boundary.isConnected) {stop();return;}
                const field = fieldFor(boundary, kind);
                if (!field || field.disabled || !field.isConnected || field.closest('[inert]')) return;
                // Wait for native opening animation, never an endless loading
                // shimmer elsewhere in this panel. No observer survives 5s.
                const animations = (boundary.getAnimations?.({subtree:true}) || []).filter(
                    animation => animation.playState === 'running' &&
                    animation.effect?.getComputedTiming?.().endTime !== Infinity);
                if (animations.length) {
                    if (!waiting) {
                        waiting = true;
                        Promise.allSettled(animations.map(animation => animation.finished)).then(() => {
                            waiting = false;schedule();
                        });
                    }
                    return;
                }
                stop();
                field.focus({preventScroll:true});
                field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
            }
            cancelPending = stop;
            observer.observe(boundary, {subtree:true, childList:true, attributes:true,
                attributeFilter:['inert','open','disabled','style']});
            app.addEventListener('pointerdown', stop, true);
            app.addEventListener('keydown', stop, true);
            deadline = setTimeout(stop, 5000);
            schedule();
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
                cancelPending();
                const original = prior.link?.isConnected ? prior.link : review;
                const scroll = owner(original);
                const top = original === review ? prior.reviewTop : prior.linkTop;
                // Retire our own affordance before measuring the destination.
                // Its removal can change the warning's document position;
                // restoring first leaves WebKit one line above that position.
                state.sourceReviewReturn = null;
                returnLinks();
                original.setAttribute('tabindex', '-1');
                original.focus({preventScroll:true});
                scroll.scrollTop += original.getBoundingClientRect().top - top;
                return;
            }
            const match = /^#source-details-(.+)--(site|date)$/.exec(link.getAttribute('href') || '');
            if (!match) return;
            const marker = document.getElementById('source-details-' + match[1]);
            const boundary = marker?.closest('[class*="st-key-source_detail_editor_"]');
            const review = app.querySelector('#report-review');
            if (!boundary || !review) return; // Keep the native anchor fallback.
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
            // Cold native fields can still be skeletons at this point. Open
            // the real panel now and hand focus over once its input exists.
            focusWhenReady(boundary, match[2]);
        }
        app.addEventListener('click', click);
        // A valid correction can remove its warning and form. The keyed return
        // location stays mounted; reveal it again after that ordinary rerun.
        returnLinks();
        return () => {disposed=true;cancelPending();app.removeEventListener('click',click);};
    },
};
