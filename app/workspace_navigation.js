/* Native sequential navigation and legacy section selector. The existing layout adapter owns scheduling. */
globalThis.ENFRAWorkspaceNavigation = {
    // Entering the editor from report setup replaces the whole page, yet the
    // scroll root keeps the setup review's offset. Python sends this request
    // once for that deliberate entry; edits, previews and reloads never do,
    // so they keep the reader's position.
    land(state, request) {
        const [nonce, section] = request || [];
        if (!nonce || state.landing === nonce) return;
        state.landing = nonce;
        state.landingRequest = section;
        state.navigationRequest = section;
        state.navigationReturn = null;
        state.reviewNavigation = false;
        state.explicitReview = false;
    },
    // A landing waits for its section to render. Once the reader acts
    // first, it must not scroll or take focus from them (an open menu
    // would close under their click).
    cancelLanding(state) {
        if (state.landingRequest && state.navigationRequest === state.landingRequest) state.navigationRequest = null;
        state.landingRequest = null;
    },
    // The control the reader last activated, kept as the nearest keyed
    // native element's class at that moment; the element itself may be
    // re-rendered before a request arrives. Only a press, or Enter/Space on
    // a control, activates. Tab, any other key or wheel scrolling means the
    // reader has moved on, even while that control still has focus.
    noteInput(state, event) {
        if (!event.isTrusted) return;
        // Chromium may change scrollTop while late previews mount, without a
        // reader scrolling. That must not turn Review's first Back into a
        // second step. A real scroll gesture hands control back to geometry.
        const editable = event.target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"]');
        const spaceActivation = event.key === ' ' &&
            event.target?.closest?.('button, [role="button"], summary');
        const scrollKey = event.type === 'keydown' && !editable && !spaceActivation &&
            ['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key);
        const scrollTarget = event.type === 'pointerdown' &&
            event.target?.matches?.('[data-testid="stMain"], .epc-workspace') ? event.target : null;
        const bounds = scrollTarget?.getBoundingClientRect();
        // Native scrollbar gutters are outside the element's client box;
        // clicking ordinary blank page content is not a scroll gesture.
        const scrollbar = bounds && (
            event.clientX >= bounds.left + scrollTarget.clientLeft + scrollTarget.clientWidth && event.clientX < bounds.right ||
            event.clientY >= bounds.top + scrollTarget.clientTop + scrollTarget.clientHeight && event.clientY < bounds.bottom);
        let vertical = 0;
        if (event.type === 'wheel' && !event.ctrlKey && !event.metaKey)
            vertical = event.deltaY || 0;
        if (event.type === 'touchstart')
            state.reviewTouch = event.touches?.length === 1 ? {x:event.touches[0].clientX,y:event.touches[0].clientY} : null;
        if (event.type === 'touchmove') {
            const prior=state.reviewTouch, touch=event.touches?.length===1 ? event.touches[0] : null;
            if (prior && touch) {
                const dx=prior.x-touch.clientX, dy=prior.y-touch.clientY;
                if (Math.abs(dy)>Math.abs(dx)) vertical=dy;
            }
            state.reviewTouch=touch ? {x:touch.clientX,y:touch.clientY} : null;
        }
        if (event.type === 'touchend' || event.type === 'touchcancel') state.reviewTouch=null;
        // A nested editor/list can consume the gesture without moving the
        // page. At its boundary normal scroll chaining may reach the page;
        // overscroll containment deliberately prevents that handoff.
        if (vertical) for (let node=event.target; node; node=node.parentElement) {
            if (node.matches?.('[data-testid="stMain"], .epc-workspace')) break;
            if (!(node.scrollHeight>node.clientHeight)) continue;
            const style=getComputedStyle(node);
            if (!/auto|scroll/.test(style.overflowY)) continue;
            const consumes=vertical<0 ? node.scrollTop>0 : node.scrollTop<node.scrollHeight-node.clientHeight;
            if (consumes || /contain|none/.test(style.overscrollBehaviorY)) {vertical=0;break;}
        }
        if (vertical || scrollKey || scrollbar) state.explicitReview = false;
        // A stationary touch tap still belongs to its preceding pointerdown
        // (including native Add-row focus provenance). Movement/cancel ends it.
        if (event.type === 'touchstart' || event.type === 'touchend') return;
        const activation = event.type === 'pointerdown' ||
            event.type === 'keydown' && (event.key === 'Enter' || event.key === ' ');
        const keyed = activation ? event.target?.closest?.('[class*="st-key-"]') : null;
        state.lastInputKey = keyed ? Array.from(keyed.classList).find(name => name.startsWith('st-key-')) || null : null;
    },
    // A native Add action may move focus into its new row once. Python
    // renders a hidden marker after that row's fields, so the field exists
    // when the marker does, and the adapter's existing DOM observer consumes
    // it. Focus moves only if the reader's latest input was that same Add
    // control; anything they did since keeps their place.
    focusEntries(state, root) {
        const consumed = state.entryFocus || (state.entryFocus = new Set());
        for (const marker of root.querySelectorAll('[data-enfra-entry-focus]')) {
            const {enfraEntryFocus: nonce, enfraEntryField: field, enfraEntryOrigin: origin} = marker.dataset;
            if (!nonce || consumed.has(nonce)) continue;
            consumed.add(nonce);
            if (marker.closest('[data-stale="true"]') || state.lastInputKey !== 'st-key-' + origin) continue;
            const target = root.querySelector('.st-key-' + CSS.escape(field))?.querySelector('textarea, input');
            if (!target || target.disabled) continue;
            state.lastInputKey = null;
            target.focus({preventScroll: true});
            target.scrollIntoView({block: 'nearest', inline: 'nearest'});
        }
    },
    // This adapter's own layout writes can resize content above the reader:
    // the first wide layout reserves preview space beside every section.
    // WebKit keeps the scroll offset, and Chromium's anchoring can miss it,
    // so a control moves out from under a resting pointer and a click lands
    // elsewhere. Remember what the reader is looking at before those writes:
    // the element under the pointer, else the one at the reading line below
    // the selector. Framework reruns, previews and navigation are not
    // compensated; the anchor is taken after them and kept before navigation.
    readingAnchor({state, scrollport, app, nav}) {
        if (state.ownsScroll) return null;
        const port = scrollport.getBoundingClientRect();
        const top = Math.max(port.top, nav ? nav.getBoundingClientRect().bottom : port.top);
        const usable = node => {
            // Never the selector, a preview, or this adapter's own controls
            // (a mode change can hide or move them).
            if (!node || !scrollport.contains(node) || nav?.contains(node) ||
                node.closest?.('[class*="st-key-epc_preview_slot_"]') ||
                node.closest?.('.epc-preview-controls')) return false;
            const box = node.getBoundingClientRect();
            return box.height < port.height && box.bottom > top && box.top < port.bottom;
        };
        const hovered = Array.from(document.querySelectorAll(':hover')).pop();
        const box = app.getBoundingClientRect();
        const node = usable(hovered) ? hovered : document.elementFromPoint(box.left + 24, top + (port.bottom - top) / 3);
        return usable(node) ? {node, top: node.getBoundingClientRect().top} : null;
    },
    keepAnchor(anchor, scrollport) {
        if (!anchor?.node.isConnected) return;
        const box = anchor.node.getBoundingClientRect();
        // An anchor the new layout hides lost its box; it did not move.
        if (!box.width && !box.height) return;
        const shift = box.top - anchor.top;
        if (Math.abs(shift) >= 1) scrollport.scrollTop += shift;
    },
    create({root, app, scrollport, nav, state, geometry, schedule}) {
        if (!nav) return null;
        let select = null, reviewButton = null, backButton = null, nextButton = null, progress = null;
        let entries = [], signature = '';
        let restore = null;
        const box = node => node.getBoundingClientRect();
        const owner = () => state.ownsScroll ? root : scrollport;
        // The container keeps one height whether or not its selector is
        // pinned for Review, so toggling Review never resizes previews.
        const height = () => box(nav).height;
        const capture = entry => entry ? {id:entry.id, scroll:owner().scrollTop,
            offset:box(entry.target).top-box(owner()).top} : null;
        const navigate = id => {
            const entry = entries.find(item => item.id === id);
            if (!entry?.target.isConnected) return;
            if (entry.outside) {
                if (!state.reviewNavigation)
                    state.navigationReturn = capture(entries.find(item => item.id === state.navigationActive));
                state.reviewNavigation = true;
            } else if (!entry.outside) state.reviewNavigation = false;
            state.explicitReview = Boolean(entry.outside);
            state.navigationRequest = entry.id; state.navigationActive = entry.id;
            schedule();
        };
        const choose = () => navigate(select.value);
        const openReview = () => navigate('report_review');
        const step = delta => {
            const index = entries.findIndex(item => item.id === state.navigationActive);
            const target = entries[index + delta];
            if (index >= 0 && target) navigate(target.id);
        };
        const back = () => step(-1), nextSection = () => step(1);
        // Review corrections still reach their section directly, even when
        // Review temporarily releases a confined editor's scroll ownership.
        // Only the Monthly sequential toolbar owns these local anchors.
        const correctSection = event => {
            if (!backButton || event.defaultPrevented || event.button !== 0 ||
                event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
            const link = event.target?.closest?.('a');
            const match = /^#report-section-([a-z_]+)$/.exec(link?.getAttribute('href') || '');
            if (!match || !app.contains(link)) return;
            const id = 'monthly_' + match[1];
            if (!entries.some(item => item.id === id && item.target.isConnected)) return;
            event.preventDefault();
            navigate(id);
        };
        app.addEventListener?.('click', correctSection);
        const prepare = (context, sample, pairs) => {
            const current = nav.querySelector('.epc-section-selector');
            if (current !== select) {
                if (select?.onchange === choose) select.onchange = null;
                select = current;
                signature = select?._epcNavigationSignature || '';
                if (select) select.onchange = choose;
            }
            entries = pairs.map(({id,pair,title}) => ({id, target:pair, title}));
            const review = app.querySelector('#report-review');
            if (review) entries.push({id:'report_review', target:review, title:'Review and download', outside:true});
            const shortcut = nav.querySelector('.epc-review-shortcut');
            if (shortcut !== reviewButton) {
                if (reviewButton?.onclick === openReview) reviewButton.onclick = null;
                reviewButton = shortcut;
                if (reviewButton) reviewButton.onclick = openReview;
            }
            if (reviewButton) reviewButton.disabled = !review;
            const previous = nav.querySelector('.epc-section-back');
            const following = nav.querySelector('.epc-section-next');
            if (backButton !== previous) {
                if (backButton?.onclick === back) backButton.onclick = null;
                backButton = previous;
                if (backButton) backButton.onclick = back;
            }
            if (nextButton !== following) {
                if (nextButton?.onclick === nextSection) nextButton.onclick = null;
                nextButton = following;
                if (nextButton) nextButton.onclick = nextSection;
            }
            progress = nav.querySelector('.epc-section-progress');
            const next = JSON.stringify(entries.map(({id,title}) => [id,title]));
            if (select && next !== signature) {
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
            if (state.reviewNavigation && !state.explicitReview && !state.navigationRequest && review &&
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
            if (!entries.length) return;
            const top=Math.max(sample.chromeBottom,sample.scrollport.y,sample.visual?.y||0)+height()+12;
            let request = entries.find(item => item.id === state.navigationRequest);
            if (request && state.landingRequest === request.id) {
                // The page may become interactive before this adapter mounts.
                // A reader already in a control (an open menu, a field) keeps
                // it; the landing never takes their focus or scroll.
                const focused = document.activeElement;
                if (focused && focused !== document.body && focused !== document.documentElement) {
                    state.navigationRequest = null; request = null;
                }
                state.landingRequest = null;
            }
            if (request) {
                const entry=request; state.navigationRequest=null; state.landingRequest=null;
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
            if (select && document.activeElement!==select && active && select.value!==active) select.value=active;
            const index = entries.findIndex(item => item.id === active);
            if (backButton) backButton.disabled = index <= 0;
            if (nextButton) {
                nextButton.disabled = index < 0 || index >= entries.length - 1;
                const label = entries[index + 1]?.outside ? 'Review' : 'Next';
                if (nextButton.textContent !== label) nextButton.textContent = label;
            }
            if (progress && index >= 0) {
                const text = `${index + 1} of ${entries.length} · ${entries[index].title}`;
                if (progress.textContent !== text) progress.textContent = text;
                if (progress.dataset.section !== active) progress.dataset.section = active;
            }
        };
        return {prepare,update,height,dispose(){
            app.removeEventListener?.('click',correctSection);
            if(select?.onchange===choose)select.onchange=null;
            if(reviewButton?.onclick===openReview)reviewButton.onclick=null;
            if(backButton?.onclick===back)backButton.onclick=null;
            if(nextButton?.onclick===nextSection)nextButton.onclick=null;
        }};
    }
};
