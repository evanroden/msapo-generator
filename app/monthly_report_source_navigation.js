// Display-only navigation between final review and the one native source form.
// It never reads/writes input values or submits an edit. The caller disposes it
// with its workspace; only a same-report reading anchor survives a full rerun.
globalThis.ENFRASourceReviewNavigation = {
    install(app, state) {
        let disposed = false, frame = null, controlsFrame = null, nativeToken = null, pageFrame = null, cancelPending = () => {};
        const loadingText = 'Loading correction controls…';
        const workspaceSelector = '[class*="st-key-epc_workspace_monthly"]';
        const reportIdentity = state.identity;
        function correctionWorkspace(node, source, kind) {
            if (!node?.isConnected || !app.contains(node) || node.closest('[data-stale="true"]')) return null;
            const enclosing = node.closest(workspaceSelector);
            if (enclosing) return enclosing;
            // Final review is a stable sibling after the workspace. Its
            // server-owned exact-source marker must identify this report;
            // an arbitrary matching href elsewhere in the app is not enough.
            const group = node.closest('[class*="st-key-source_correction_"]');
            if (!group?.isConnected || group.closest('[data-stale="true"]')) return null;
            const markers = group.querySelectorAll('.enfra-source-correction');
            if (markers.length !== 1 || !markers[0].isConnected ||
                markers[0].closest('[data-stale="true"]') ||
                markers[0].dataset.reportIdentity !== reportIdentity ||
                markers[0].dataset.sourceId !== source || markers[0].dataset.kind !== kind) return null;
            const exact = [...app.querySelectorAll('.enfra-source-correction')].filter(
                marker => marker.dataset.sourceId === source && marker.dataset.kind === kind);
            if (exact.length !== 1 || exact[0] !== markers[0]) return null;
            const workspaces = app.querySelectorAll(workspaceSelector);
            if (workspaces.length !== 1 || workspaces[0]._epcWorkspace !== state) return null;
            return workspaces[0];
        }
        function sourceBoundary(source, workspace) {
            if (!reportIdentity || state.identity !== reportIdentity ||
                !workspace || workspace._epcWorkspace !== state || !workspace.dataset.epcMode ||
                !app.contains(workspace) || workspace.closest('[data-stale="true"]')) return null;
            // A resumed report's fixed source forms are siblings before its
            // workspace. Match one current exact-source marker; never select
            // the first duplicate or another report's otherwise valid form.
            const markers = [...app.querySelectorAll('[id^="source-details-"]')].filter(
                marker => marker.id === 'source-details-' + source);
            if (markers.length !== 1 || !markers[0].isConnected ||
                markers[0].closest('[data-stale="true"]')) return null;
            const boundary = markers[0].closest('[class*="st-key-source_detail_editor_"]');
            if (!boundary?.isConnected || !app.contains(boundary) ||
                boundary.closest('[data-stale="true"]')) return null;
            const enclosing = boundary.closest(workspaceSelector);
            if (enclosing) return enclosing === workspace ? boundary : null;
            const group = boundary.closest('[class*="_source_metadata_corrections"],[class*="_source_manager_panel"]');
            const owners = group?.querySelectorAll('.enfra-source-correction-owner');
            if (owners?.length !== 1 || !owners[0].isConnected ||
                owners[0].dataset.reportIdentity !== reportIdentity ||
                owners[0].closest('[data-stale="true"]')) return null;
            return boundary;
        }
        function syncControls(retiring = false) {
            // The standard alert is already readable while the v2 adapter or
            // native field is a skeleton. Never advertise an inert anchor.
            // Show our link beside the final status; keep the framework's
            // status, alert, source form and all business inputs in their nodes.
            app.querySelectorAll('.enfra-source-correction').forEach(marker => {
                const container = marker.closest('[class*="st-key-source_correction_"]');
                const alert = container?.querySelector('[data-testid="stAlert"]');
                if (!alert) return;
                const loading = [...alert.querySelectorAll('strong')].reverse().find(
                    node => node.textContent === loadingText);
                if (!loading) return;
                const current = alert.querySelector('a[data-enfra-correction-link]');
                const source = marker.dataset.sourceId, kind = marker.dataset.kind;
                const workspace = correctionWorkspace(marker, source, kind);
                const boundary = sourceBoundary(source, workspace);
                const field = boundary && fieldFor(boundary, kind);
                const ready = !retiring && !disposed && ['site', 'date'].includes(kind) &&
                    workspace?._epcWorkspace === state && Boolean(workspace.dataset.epcMode) &&
                    Boolean(boundary) &&
                    !boundary.closest('[data-stale="true"]') &&
                    field?.isConnected && !field.disabled && !field.closest('[data-stale="true"]');
                if (ready && !current) {
                    const link = document.createElement('a');
                    link.textContent = marker.dataset.label;
                    link.setAttribute('href', '#source-details-' + source + '--' + kind);
                    link.setAttribute('data-enfra-correction-link', '');
                    loading.after(link);
                } else if (!ready && current) current.remove();
                // Retain the framework's status node, too. Removing it would
                // make a later ordinary Markdown reconciliation unsafe.
                loading.hidden = Boolean(ready);
            });
        }
        function controlsChanged() {
            if (disposed || controlsFrame !== null) return;
            controlsFrame = requestAnimationFrame(() => {controlsFrame = null;syncControls();nativeRequests();});
        }
        function returnLinks() {
            app.querySelectorAll('.enfra-source-review-return').forEach(link => {
                link.hidden = link.dataset.sourceId !== state.sourceReviewReturn?.source;
                link.textContent = state.sourceReviewReturn?.target === 'report-section-water'
                    ? 'Return to report pages' : 'Return to review';
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
        function focusWhenReady(boundary, kind, source, workspace, link, focused = () => {},
                                currentWorkspace = () => correctionWorkspace(link, source, kind)) {
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
                if (currentWorkspace() !== workspace ||
                    sourceBoundary(source, workspace) !== boundary) {stop();return;}
                const field = fieldFor(boundary, kind);
                if (field?.closest('[data-stale="true"]')) {stop();return;}
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
                focused();
            }
            cancelPending = stop;
            observer.observe(boundary, {subtree:true, childList:true, attributes:true,
                attributeFilter:['inert','open','disabled','style','data-stale']});
            app.addEventListener('pointerdown', stop, true);
            app.addEventListener('keydown', stop, true);
            deadline = setTimeout(stop, 5000);
            schedule();
        }
        function openDisclosures(boundary) {
            const parents=[];
            for(let p=boundary.parentElement;p;p=p.parentElement) if(p.tagName==='DETAILS') parents.unshift(p);
            [...parents,...boundary.querySelectorAll('details')].forEach(details => {
                // During native closing animation open remains true while
                // the direct Streamlit body is already inert. Reopen through
                // that same native transition; never remove inert ourselves.
                const body = details.querySelector(':scope > [data-testid="stExpanderDetails"]');
                if (!details.open || body?.hasAttribute('inert'))
                    details.querySelector(':scope > summary')?.click();
            });
        }
        function requestWorkspace(request) {
            if (!request?.isConnected || !app.contains(request) ||
                request.closest('[data-stale="true"]') || state.identity !== reportIdentity) return null;
            const enclosing = request.closest(workspaceSelector);
            if (enclosing) return enclosing._epcWorkspace === state && enclosing.dataset.epcMode ? enclosing : null;
            const group = request.closest('[class*="_source_manager_panel"]');
            const owners = group?.querySelectorAll('.enfra-source-correction-owner');
            if (owners?.length !== 1 || !owners[0].isConnected ||
                owners[0].dataset.reportIdentity !== reportIdentity ||
                owners[0].closest('[data-stale="true"]')) return null;
            const workspaces = app.querySelectorAll(workspaceSelector);
            return workspaces.length === 1 && workspaces[0]._epcWorkspace === state &&
                workspaces[0].dataset.epcMode ? workspaces[0] : null;
        }
        function nativeRequests() {
            const request = app.querySelector('.enfra-source-review-target');
            const workspace = requestWorkspace(request);
            const token = request?.dataset.token;
            if (workspace && token && token !== state.sourceReviewFocusToken && token !== nativeToken &&
                ['site', 'date'].includes(request.dataset.field)) {
                const boundary = sourceBoundary(request.dataset.sourceId, workspace);
                if (boundary) {
                    nativeToken = token;
                    openDisclosures(boundary);
                    focusWhenReady(boundary, request.dataset.field, request.dataset.sourceId, workspace, request,
                        () => {state.sourceReviewFocusToken = token;}, () => requestWorkspace(request));
                }
            }
            const pageRequest = app.querySelector('.enfra-report-page-target');
            const pageWorkspace = requestWorkspace(pageRequest);
            const pageToken = pageRequest?.dataset.token;
            const context = pageWorkspace && document.getElementById('source-page-context-' + pageRequest.dataset.sourceId);
            const ownsPage = () => context?.isConnected && app.contains(context) &&
                !context.closest('[data-stale="true"]') && context.closest(workspaceSelector) === pageWorkspace;
            if (ownsPage() && pageToken && pageToken !== state.sourcePageFocusToken && pageFrame === null) {
                pageFrame = requestAnimationFrame(() => {
                    pageFrame = null;
                    if (disposed || !ownsPage() || requestWorkspace(pageRequest) !== pageWorkspace ||
                        document.getElementById('source-page-context-' + pageRequest.dataset.sourceId) !== context) return;
                    state.sourcePageFocusToken = pageToken;
                    context.setAttribute('tabindex', '-1');context.focus({preventScroll:true});
                    context.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
                });
            }
        }
        function click(event) {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
            const button=event.target?.closest?.('button');
            const pageContext=button?.closest?.('[class*="st-key-monthly_source_page_correction_"]')?.querySelector?.('.enfra-source-page-correction');
            if(pageContext?.dataset?.returnTarget==='report-section-water') {
                const section=app.querySelector('#report-section-water');
                if(section) {
                    state.sourceReviewReturn={source:pageContext.dataset.sourceId,target:'report-section-water',
                        anchor:'source-page-context-'+pageContext.dataset.sourceId,link:button,
                        linkTop:button.getBoundingClientRect().top,reviewTop:section.getBoundingClientRect().top};
                    returnLinks();return;
                }
            }
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
                const review = app.querySelector('#'+(prior?.target || 'report-review'));
                if (!prior || !review) return;
                event.preventDefault();
                cancelPending();
                const original = prior.link?.isConnected ? prior.link : (prior.anchor ? document.getElementById(prior.anchor) : null) || review;
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
            event.preventDefault();
            const workspace = correctionWorkspace(link, match[1], match[2]);
            const boundary = sourceBoundary(match[1], workspace);
            const review = app.querySelector('#report-review');
            if (!boundary || !review) return;
            const field = fieldFor(boundary, match[2]);
            if (field?.disabled || field?.closest('[data-stale="true"]')) return;
            state.sourceReviewReturn = {source:match[1], link,
                linkTop:link.getBoundingClientRect().top, reviewTop:review.getBoundingClientRect().top};
            // Activate the native summary so Streamlit updates the body's
            // inert state as well as details.open. Setting open alone makes
            // the form visible while leaving its inputs unable to take focus.
            // Opening the disclosure never submits or accepts source details.
            openDisclosures(boundary);
            returnLinks();
            // Cold native fields can still be skeletons at this point. Open
            // the real panel now and hand focus over once its input exists.
            focusWhenReady(boundary, match[2], match[1], workspace, link);
        }
        app.addEventListener('click', click);
        // This display-only observer also sees newly streamed warnings and
        // lazy native controls. It does not wait for unrelated/offscreen
        // previews, read values, submit, or use a timer as readiness proof.
        const controlsObserver = new MutationObserver(controlsChanged);
        controlsObserver.observe(app, {subtree:true, childList:true, attributes:true,
            attributeFilter:['disabled','data-stale','data-epc-mode','data-report-identity','data-source-id','data-kind','id']});
        controlsChanged();
        // A valid correction can remove its warning and form. The keyed return
        // location stays mounted; reveal it again after that ordinary rerun.
        returnLinks();
        nativeRequests();
        return () => {
            disposed=true;cancelPending();controlsObserver.disconnect();
            if (pageFrame !== null) cancelAnimationFrame(pageFrame);
            if (controlsFrame !== null) cancelAnimationFrame(controlsFrame);
            syncControls(true);
            app.removeEventListener('click',click);
        };
    },
};
