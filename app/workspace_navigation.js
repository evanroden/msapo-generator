/* Native sequential navigation and legacy section selector. The existing layout adapter owns scheduling. */
globalThis.ENFRAWorkspaceNavigation = {
    // Entering the editor from report setup replaces the whole page, yet the
    // scroll root keeps the setup review's offset. Python sends this request
    // once for that deliberate entry; edits, previews and reloads never do,
    // so they keep the reader's position.
    land(state, request) {
        const [nonce, section] = request || [];
        if (!nonce || state.landing === nonce) return;
        globalThis.ENFRAWorkspaceNavigation.cancelIntent(state);
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
    // One accepted sequential intent, never a queue or a replayed DOM event.
    cancelIntent(state) {
        const intent = state.navigationIntent;
        if (intent && state.navigationRequest === intent.target) state.navigationRequest = null;
        state.navigationIntent = null;
    },
    // The control the reader last activated, kept as the nearest keyed
    // native element's class at that moment; the element itself may be
    // re-rendered before a request arrives. Only a press, or Enter/Space on
    // a control, activates. Tab, any other key or wheel scrolling means the
    // reader has moved on, even while that control still has focus.
    noteInput(state, event) {
        if (!event.isTrusted) return;
        const intent = state.navigationIntent;
        const button = event.target?.closest?.('button');
        const command = (event.type === 'pointerdown' && event.button === 0 ||
            event.type === 'keydown' && ['Enter',' '].includes(event.key)) &&
            !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey &&
            button && [intent?.back,intent?.next].includes(button) && !button.disabled &&
            button.isConnected && !button.closest?.('[data-stale="true"]');
        if (!command) {
            state.navigationInputSerial = (state.navigationInputSerial || 0) + 1;
            globalThis.ENFRAWorkspaceNavigation.cancelIntent(state);
        }
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
        let entries = [], signature = '', established = null;
        let restore = null, correction = null, correctionSerial = 0, disposed = false;
        const identity = state.identity, lease = {};
        state.navigationController = lease;
        const current = node => node?.isConnected === true && !node.closest?.('[data-stale="true"]');
        const owns = () => !disposed && state.navigationController === lease && state.identity === identity &&
            [root,app,scrollport,nav].every(current);
        const connected = node => node?.isConnected === true;
        const sameNodes = (a,b) => Boolean(a && b && a.length === b.length &&
            a.every((item,index) => item.id === b[index].id && item.target === b[index].target && item.marker === b[index].marker));
        const ownedNodes = () => {
            if (!owns() || !app.contains(root) || !app.contains(nav) || ![select,reviewButton,backButton,nextButton,progress].filter(Boolean).every(current) ||
                nav.querySelector('.epc-section-selector') !== select ||
                nav.querySelector('.epc-review-shortcut') !== reviewButton ||
                nav.querySelector('.epc-section-back') !== backButton ||
                nav.querySelector('.epc-section-next') !== nextButton ||
                nav.querySelector('.epc-section-progress') !== progress) return null;
            const nodes = Array.from(root.querySelectorAll('[data-epc-pair]')).map(marker => ({
                id:marker.dataset.epcPair,marker,
                target:marker.closest('.st-key-epc_pair_' + CSS.escape(marker.dataset.epcPair))}));
            const reviews = Array.from(app.querySelectorAll('#report-review'));
            if (reviews.length > 1) return null;
            if (reviews.length) nodes.push({id:'report_review',target:reviews[0],marker:null});
            if (!nodes.length || new Set(nodes.map(item=>item.id)).size !== nodes.length ||
                new Set(nodes.map(item=>item.target)).size !== nodes.length ||
                nodes.length !== entries.length || nodes.some((item,index) =>
                    item.id !== entries[index].id || item.target !== entries[index].target ||
                    !connected(item.target) || item.marker && !connected(item.marker) ||
                    (item.marker ? !root.contains(item.target) : !app.contains(item.target)))) return null;
            return nodes;
        };
        const canHandoff = next => Boolean(identity && next.identity === identity && next.root === root &&
            next.app === app && next.scrollport === scrollport && next.nav === nav &&
            app.contains(root) && app.contains(nav) && sameNodes(established,ownedNodes()) &&
            established.some(item=>item.id===state.navigationActive));
        const cancelIntent = () => globalThis.ENFRAWorkspaceNavigation.cancelIntent(state);
        const pendingIntent = () => {
            const intent = state.navigationIntent;
            if (!intent) return null;
            if (intent.owner !== lease || intent.identity !== identity || intent.origin !== state.navigationActive ||
                intent.back !== backButton || intent.next !== nextButton ||
                intent.input !== (state.navigationInputSerial || 0) || state.navigationRequest !== intent.target ||
                !sameNodes(intent.nodes,ownedNodes())) {cancelIntent();return null;}
            return intent;
        };
        const fresh = node => Boolean(node && current(node.target) && (!node.marker || current(node.marker)) &&
            !node.target.querySelector?.('[data-stale="true"]') &&
            current(node.target.querySelector?.('h1,h2,h3,h4') || node.target));
        const readyIntent = intent => Boolean(intent && fresh(intent.nodes.find(item=>item.id===intent.origin)) &&
            fresh(intent.nodes.find(item=>item.id===intent.target)));
        const box = node => node.getBoundingClientRect();
        const owner = () => state.ownsScroll ? root : scrollport;
        // The container keeps one height whether or not its selector is
        // pinned for Review, so toggling Review never resizes previews.
        const height = () => box(nav).height;
        const capture = entry => entry ? {id:entry.id, scroll:owner().scrollTop,
            offset:box(entry.target).top-box(owner()).top} : null;
        const selectEntry = entry => {
            if (entry.outside) {
                if (!state.reviewNavigation)
                    state.navigationReturn = capture(entries.find(item => item.id === state.navigationActive));
                state.reviewNavigation = true;
            } else state.reviewNavigation = false;
            state.explicitReview = Boolean(entry.outside);
        };
        const navigate = id => {
            if (!owns()) return;
            cancelIntent();correction = null;correctionSerial++;
            const entry = entries.find(item => item.id === id);
            if (!entry || !current(entry.target)) return;
            selectEntry(entry);
            state.navigationRequest = entry.id;state.navigationActive = entry.id;
            schedule();
        };
        // Layout has already translated this editor into its new scroll root.
        // Transfer that anchor, not the old root's current-section history;
        // fractional pixels at the reading line must not select its predecessor.
        // An explicit Back/Next/Review request still wins in update().
        const reanchor = id => {
            if (state.navigationRequest) return;
            const entry=entries.find(item=>item.id===id && !item.outside && item.target.isConnected);
            if (!entry) return;
            state.navigationActive=id;
            state.navigationJump={id,scroll:owner().scrollTop};
        };
        const choose = () => navigate(select.value);
        const openReview = () => navigate('report_review');
        const step = delta => {
            const control = delta < 0 ? backButton : nextButton;
            const nodes = ownedNodes();
            const index = entries.findIndex(item => item.id === state.navigationActive);
            const target = entries[index + delta];
            if (!sameNodes(established,nodes) || !control || control.disabled || index < 0 || !target) return;
            // Origin remains the section actually reached. Repeated commands
            // coalesce; an opposite command replaces from that same origin.
            correction = null;correctionSerial++;
            state.navigationIntent = {owner:lease,identity,origin:state.navigationActive,target:target.id,
                nodes,input:state.navigationInputSerial || 0,back:backButton,next:nextButton};
            state.navigationRequest = target.id;
            schedule();
        };
        const back = () => step(-1), nextSection = () => step(1);
        // Review corrections still reach their section directly, even when
        // Review temporarily releases a confined editor's scroll ownership.
        // Only the Monthly sequential toolbar owns these local anchors.
        const correctSection = event => {
            if (!backButton || event.defaultPrevented || event.button !== 0 ||
                event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
            const link = event.target?.closest?.('a');
            const href = link?.getAttribute('href') || '';
            if (href === '#report-review' && link?.classList?.contains('enfra-correction-return')) {
                event.preventDefault();navigate('report_review');return;
            }
            if (link?.classList?.contains('enfra-picture-correction-link')) {
                const adapter = globalThis.ENFRAPictureCorrections;
                if (!adapter || !app.contains(link)) return;
                event.preventDefault();
                const target = adapter.resolve(app, link, state.identity);
                const entry = target && entries.find(item => item.target.contains(target.marker));
                if (!entry) {adapter.unavailable(link);return;}
                navigate(entry.id);
                correction = {link, serial:correctionSerial};
                return;
            }
            const match = /^#report-section-([a-z_]+)$/.exec(href);
            if (!match || !app.contains(link)) return;
            const id = 'monthly_' + match[1];
            if (!entries.some(item => item.id === id && item.target.isConnected)) return;
            event.preventDefault();
            navigate(id);
        };
        const cancelCorrection = () => {correction = null; correctionSerial++;};
        app.addEventListener?.('pointerdown', cancelCorrection);
        app.addEventListener?.('keydown', cancelCorrection);
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
            // A validated server page request arrives only after the previous
            // owner committed its delivered inputs. Reuse ordinary navigation;
            // this marker never submits a field or selects a different source.
            if (backButton && globalThis.ENFRAPictureCorrections) {
                const requests = [...app.querySelectorAll('.enfra-page-correction-request')].filter(link =>
                    link.isConnected && link.dataset.reportIdentity === state.identity &&
                    !link.closest('[data-stale="true"]'));
                const consumed = state.exactPageNavigationTokens || (state.exactPageNavigationTokens = new Set());
                if (requests.length === 1) {
                    const link = requests[0], token = link.dataset.token;
                    const target = token && !consumed.has(token) &&
                        globalThis.ENFRAPictureCorrections.resolve(app, link, state.identity);
                    const entry = target && entries.find(item => item.target.contains(target.marker));
                    if (entry) {
                        consumed.add(token);
                        navigate(entry.id);
                        correction = {link, serial:correctionSerial};
                    }
                }
            }

            const next = JSON.stringify(entries.map(({id,title}) => [id,title]));
            if (select && next !== signature) {
                const selected = select.value;
                select.replaceChildren(...entries.map(({id,title}) => {
                    const option = document.createElement('option'); option.value=id; option.textContent=title; return option;
                }));
                if (entries.some(item => item.id === selected)) select.value=selected;
                select.disabled = !entries.length; signature=next; select._epcNavigationSignature=next;
            }
            const intent = pendingIntent();
            const nodes = ownedNodes();
            // Transient stale content is admissible only after this exact
            // report/controller has observed these same owners fully fresh.
            if (nodes?.every(fresh)) established = nodes;
            if (readyIntent(intent)) selectEntry(entries.find(item=>item.id===intent.target));
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
            const intent = pendingIntent();
            let request = entries.find(item => item.id === state.navigationRequest);
            if (intent && !readyIntent(intent)) request = null;
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
                state.navigationIntent=null;
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
            let active=state.navigationIntent?.origin || (jump && Math.abs(owner().scrollTop-jump.scroll)<=1 ? jump.id : null);
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
            if (correction) {
                const pending = correction;correction = null;
                globalThis.ENFRAPictureCorrections.reveal(app, pending.link, state.identity,
                    () => pending.serial === correctionSerial);
            }
            state.navigationActive=active;
            // Never change a menu's highlighted option while it has focus.
            if (select && document.activeElement!==select && active && select.value!==active) select.value=active;
            const index = entries.findIndex(item => item.id === active);
            const sequentialReady = sameNodes(established,ownedNodes());
            if (backButton) backButton.disabled = !sequentialReady || index <= 0;
            if (nextButton) {
                nextButton.disabled = !sequentialReady || index < 0 || index >= entries.length - 1;
                const label = entries[index + 1]?.outside ? 'Review' : 'Next';
                if (nextButton.textContent !== label) nextButton.textContent = label;
            }
            if (progress && index >= 0) {
                const text = `${index + 1} of ${entries.length} · ${entries[index].title}`;
                if (progress.textContent !== text) progress.textContent = text;
                if (progress.dataset.section !== active) progress.dataset.section = active;
            }
        };
        return {prepare,update,height,reanchor,canHandoff,
            resume(nextSchedule) {
                if (!owns() || typeof nextSchedule !== 'function') return false;
                cancelCorrection();schedule = nextSchedule;
                // The new layout installed its source-review owner first,
                // as on a cold mount. Preserve delegated Return precedence;
                // the native toolbar handlers stay continuously attached.
                app.removeEventListener?.('pointerdown',cancelCorrection);
                app.removeEventListener?.('keydown',cancelCorrection);
                app.removeEventListener?.('click',correctSection);
                app.addEventListener?.('pointerdown',cancelCorrection);
                app.addEventListener?.('keydown',cancelCorrection);
                app.addEventListener?.('click',correctSection);
                return true;
            },
            dispose(){
            if (state.navigationIntent?.owner === lease) cancelIntent();
            disposed = true;
            if (state.navigationController === lease) delete state.navigationController;
            cancelCorrection();
            app.removeEventListener?.('pointerdown',cancelCorrection);
            app.removeEventListener?.('keydown',cancelCorrection);
            app.removeEventListener?.('click',correctSection);
            if(select?.onchange===choose)select.onchange=null;
            if(reviewButton?.onclick===openReview)reviewButton.onclick=null;
            if(backButton?.onclick===back)backButton.onclick=null;
            if(nextButton?.onclick===nextSection)nextButton.onclick=null;
        }};
    }
};
