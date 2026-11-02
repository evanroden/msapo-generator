/* Display-only access to an exact, already mounted native caption editor. */
globalThis.ENFRAPictureCorrections = {
    resolve(app, link, identity) {
        const href = link?.getAttribute('href') || '';
        if (!link?.isConnected || !app.contains(link) || !/^#report-correction-[a-f0-9]{64}$/.test(href) ||
            link.dataset.reportIdentity !== identity || link.closest('[data-stale="true"]')) return null;
        const matches = [...app.querySelectorAll('.enfra-picture-correction')].filter(node =>
            node.id === href.slice(1) && node.dataset.reportIdentity === identity &&
            node.isConnected && !node.closest('[data-stale="true"]'));
        if (matches.length !== 1) return null;
        const marker = matches[0];
        const selectors = {input:' input', textarea:' textarea', combobox:' [role=\"combobox\"]', checkbox:' input[type=\"checkbox\"]', button:' button', radio:' input[type=\"radio\"]:checked'};
        const fieldSelector = selectors[marker.dataset.fieldKind || 'textarea'];
        if (!fieldSelector) return null;
        const fields = app.querySelectorAll('.st-key-' + CSS.escape(marker.dataset.fieldKey) + fieldSelector);
        if (fields.length !== 1 || !fields[0].isConnected || fields[0].disabled ||
            fields[0].closest('[data-stale="true"]')) return null;
        return {marker, field:fields[0]};
    },
    unavailable(link) {
        let status = link.parentElement.querySelector('.enfra-correction-status');
        if (!status) {
            status = document.createElement('span'); status.className = 'enfra-correction-status';
            status.setAttribute('role', 'status'); link.parentElement.append(status);
        }
        status.textContent = ' This item changed or is not available here. Review the current warnings and open its section.';
    },
    reveal(app, link, identity, current) {
        const target = this.resolve(app, link, identity);
        if (!target) {this.unavailable(link);return;}
        const {marker,field} = target;
        const parents = [];
        for (let node = field.parentElement; node; node = node.parentElement)
            if (node.tagName === 'DETAILS') parents.unshift(node);
        for (const details of parents) {
            const body = details.querySelector(':scope > [data-testid="stExpanderDetails"]');
            if (!details.open || body?.hasAttribute('inert')) details.querySelector(':scope > summary')?.click();
        }
        const animations = parents.flatMap(node => node.getAnimations?.({subtree:true}) || []).filter(
            animation => animation.playState === 'running' &&
            animation.effect?.getComputedTiming?.().endTime !== Infinity);
        // Only the native disclosure animation is awaited; no guessed delay,
        // value read/write, submission, remount, or scrolling retry.
        Promise.allSettled(animations.map(animation => animation.finished)).then(() => {
            const exact = this.resolve(app, link, identity);
            if (!current() || exact?.marker !== marker || exact?.field !== field) return;
            if (field.closest('[inert]') || !field.getClientRects().length) {this.unavailable(link);return;}
            let back = marker.parentElement.querySelector('.enfra-correction-return');
            if (!back) {
                back = document.createElement('a');back.className = 'enfra-correction-return';
                back.href = '#report-review';back.textContent = 'Return to Review';marker.parentElement.append(back);
            }
            back.hidden = false;
            // A server-accepted manager page and this still-current native
            // field now own Return. A warning click alone is not acceptance.
            if (marker.dataset.navigationOwner === 'exact-manager-page')
                app.dispatchEvent(new CustomEvent('enfra-exact-correction-ready', {detail:{link,marker,field,back}}));
            field.focus({preventScroll:true});field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
        });
    }
};
