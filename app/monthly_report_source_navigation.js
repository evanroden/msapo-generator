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
            const button=event.target?.closest?.('button');
            const warning=button?.closest?.('[class*="st-key-monthly_source_warning_"]')?.querySelector?.('.enfra-source-warning');
            const reviewTarget=app.querySelector('#report-review');
            if(warning&&reviewTarget) {
                // Let the native callback select/open the source and commit
                // any delivered edits. Only remember presentation context.
                state.sourceReviewReturn={source:warning.dataset.sourceId,link:button,
                    linkTop:button.getBoundingClientRect().top,reviewTop:reviewTarget.getBoundingClientRect().top};
                returnLinks();return;
            }
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
            const field = labels.map(label => boundary.querySelector('input[aria-label="'+label+'"]')).find(Boolean);
            if (!field || field.disabled) return;
            event.preventDefault();
            state.sourceReviewReturn = {source:match[1], link,
                linkTop:link.getBoundingClientRect().top, reviewTop:review.getBoundingClientRect().top};
            // Open outer disclosures before the exact source form. Changing a
            // native details disclosure is presentation, not source acceptance.
            const parents=[];
            for(let p=boundary.parentElement;p;p=p.parentElement) if(p.tagName==='DETAILS') parents.unshift(p);
            [...parents,...boundary.querySelectorAll('details')].forEach(details => {details.open=true;});
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
        const request=app.querySelector('.enfra-source-review-target');
        if(request?.dataset?.token&&request.dataset.token!==state.sourceReviewFocusToken) {
            const marker=document.getElementById('source-details-'+request.dataset.sourceId);
            const boundary=marker?.closest('[class*="st-key-source_detail_editor_"]');
            const labels=request.dataset.field==='site'?['Source sites','Source facility']:['Source date'];
            const field=labels.map(label=>boundary?.querySelector('input[aria-label="'+label+'"]')).find(Boolean);
            if(field&&!field.disabled) {
                state.sourceReviewFocusToken=request.dataset.token;
                boundary.querySelectorAll('details').forEach(details=>{details.open=true;});
                later(()=>{if(field.isConnected){field.focus({preventScroll:true});field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});}},boundary);
            }
        }
        return () => {disposed=true;if(frame!==null)cancelAnimationFrame(frame);app.removeEventListener('click',click);};
    },
};
