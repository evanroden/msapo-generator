/* One native section selector. The existing layout adapter owns scheduling. */
globalThis.ENFRAWorkspaceNavigation = {
    // Entering the editor from report setup replaces the whole page, yet the
    // scroll root keeps the setup review's offset. Python sends this request
    // once for that deliberate entry; edits, previews and reloads never do,
    // so they keep the reader's position.
    land(state, request) {
        const [nonce, section] = request || [];
        if (!nonce || state.landing === nonce) return;
        state.landing = nonce;
        state.navigationRequest = section;
        state.navigationReturn = null;
        state.reviewNavigation = false;
    },
    create({root, app, scrollport, nav, state, geometry, schedule}) {
        if (!nav) return null;
        let select = null, entries = [], signature = '';
        let restore = null;
        const box = node => node.getBoundingClientRect();
        const owner = () => state.ownsScroll ? root : scrollport;
        // The container keeps one height whether or not its selector is
        // pinned for Review, so toggling Review never resizes previews.
        const height = () => box(nav).height;
        const capture = entry => entry ? {id:entry.id, scroll:owner().scrollTop,
            offset:box(entry.target).top-box(owner()).top} : null;
        const choose = () => {
            const entry = entries.find(item => item.id === select.value);
            if (!entry?.target.isConnected) return;
            if (entry.outside) {
                state.navigationReturn = capture(entries.find(item => item.id === state.navigationActive));
                state.reviewNavigation = true;
            } else if (!entry.outside) state.reviewNavigation = false;
            state.navigationRequest = entry.id; state.navigationActive = entry.id;
            schedule();
        };
        const prepare = (context, sample, pairs) => {
            const current = nav.querySelector('.epc-section-selector');
            if (!current) return context;
            if (current !== select) {select = current; signature = select._epcNavigationSignature || ''; select.onchange = choose;}
            entries = pairs.map(({id,pair,title}) => ({id, target:pair, title}));
            const review = app.querySelector('#report-review');
            if (review) entries.push({id:'report_review', target:review, title:'Review and download', outside:true});
            const next = JSON.stringify(entries.map(({id,title}) => [id,title]));
            if (next !== signature) {
                const selected = select.value;
                select.replaceChildren(...entries.map(({id,title}) => {
                    const option = document.createElement('option'); option.value=id; option.textContent=title; return option;
                }));
                if (entries.some(item => item.id === selected)) select.value=selected;
                select.disabled = !entries.length; signature=next; select._epcNavigationSignature=next;
            }
            // Normal page scrolling can reach Review without a menu action.
            // Keep the same selector reachable once that heading crosses its
            // reading line, or once the editor ends above it: a short final
            // Review cannot scroll that far, yet the sticky selector leaves
            // with the editor. This changes display only, without moving
            // focus or scroll. Confined editors still use the deliberate
            // Review choice to leave their working scroll root.
            const line=Math.max(sample.chromeBottom,sample.scrollport.y)+height()+12;
            if (!state.reviewNavigation && !state.navigationRequest && !state.ownsScroll &&
                review && (box(review).top <= line || box(root).bottom <= line)) {
                state.reviewNavigation=true;
                state.reviewScrollTop=scrollport.scrollTop;
                state.navigationReturn=null;
                state.navigationActive='report_review';
                state.navigationJump=null;
            }
            // Reverse scrolling from review returns to the actual visible
            // section, preserving its paragraph offset when scroll ownership
            // changes back to the measured tabletop/confined layout.
            // The editor's end precedes Review, so it is the return boundary.
            if (state.reviewNavigation && !state.navigationRequest && review &&
                scrollport.scrollTop < (state.reviewScrollTop ?? scrollport.scrollTop)-1 &&
                box(root).bottom > Math.max(sample.chromeBottom, sample.scrollport.y)+height()+48) {
                const id=geometry.selectActiveSection(entries.filter(item=>!item.outside).map(item=>({id:item.id,top:box(item.target).top,bottom:box(item.target).bottom})),null,line,0);
                restore=capture(entries.find(item=>item.id===id));
                state.reviewNavigation=false;
            }
            root.dataset.epcReviewOpen=String(Boolean(state.reviewNavigation));
            if (state.reviewNavigation && (context.mode==='tabletop' || context.reason==='segments-insufficient-space'))
                return {...context,mode:'compact',reason:'review-navigation',editor:null,preview:null};
            return context;
        };
        const update = (context, sample) => {
            if (!select) return;
            const top=Math.max(sample.chromeBottom,sample.scrollport.y,sample.visual?.y||0)+height()+12;
            const request = entries.find(item => item.id === state.navigationRequest);
            if (request) {
                const entry=request; state.navigationRequest=null;
                if (!entry.outside && state.navigationReturn?.id===entry.id) {
                    restore=state.navigationReturn; state.navigationReturn=null;
                } else if (entry.target.isConnected) {
                    owner().scrollTop+=box(entry.target).top-(state.ownsScroll?box(root).top+height()+12:top);
                }
                const focus=entry.target.querySelector?.('h1,h2,h3,h4') || entry.target;
                if (focus.isConnected) {focus.setAttribute('tabindex','-1');focus.focus({preventScroll:true});}
                state.navigationJump={id:entry.id,scroll:owner().scrollTop};
                if (state.reviewNavigation) state.reviewScrollTop=scrollport.scrollTop;
            }
            const restored = entries.find(item => item.id === restore?.id);
            if (restored?.target.isConnected) {
                owner().scrollTop=restore.scroll;
                owner().scrollTop+=box(restored.target).top-box(owner()).top-restore.offset;
                state.navigationJump={id:restored.id,scroll:owner().scrollTop};
                restore=null;
            }
            const jump=state.navigationJump;
            let active=jump && Math.abs(owner().scrollTop-jump.scroll)<=1 ? jump.id : null;
            if (!active && state.reviewNavigation && entries.some(item => item.outside)) active='report_review';
            if (!active) {
                state.navigationJump=null;
                const line=state.ownsScroll?box(root).top+height()+12:top;
                // Review stays in ordinary page flow outside a fixed working
                // root. Its rectangle cannot identify that root's current
                // editor; selecting it explicitly still exits to Review.
                const visibleEntries=state.ownsScroll ? entries.filter(item=>!item.outside) : entries;
                active=geometry.selectActiveSection(visibleEntries.map(item=>({id:item.id,top:box(item.target).top,bottom:box(item.target).bottom})),state.navigationActive,line,12);
            }
            state.navigationActive=active;
            // Never change a menu's highlighted option while it has focus.
            if (document.activeElement!==select && active && select.value!==active) select.value=active;
        };
        return {prepare,update,height,dispose(){if(select?.onchange===choose)select.onchange=null;}};
    }
};
