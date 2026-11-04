// Execute the actual QA installer against bounded synthetic events and geometry.
// No browser, layout engine, product guard, or native pointer delivery is simulated.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const installers = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const caseName = process.argv[3];
const REPORT = 'a'.repeat(24), SOURCE = 'c'.repeat(64);
const fixtures = [];

function fixture() {
    const config = {time: 0, hidden: false, visibility: 'visible', offset: 400,
        main: {scrollTop: 100, scrollLeft: 0, scrollHeight: 1600, clientHeight: 600},
        button: {connected: true, disabled: false, stale: false, inert: false},
        marker: {connected: true, reportIdentity: REPORT, sourceId: SOURCE},
        workspace: {connected: true, mode: undefined, identity: undefined},
        owner: {connected: true, reportIdentity: REPORT}, workspaceCount: 1, ownerCount: 1};
    const frames = new Map(), observers = [], attempted = [], buses = {document: new Map(), window: new Map(), main: new Map()};
    let sequence = 0;
    const deny = operation => { attempted.push(operation); throw Error('passive observer: ' + operation); };
    const readonly = value => new Proxy(value, {set: () => deny('DOM write'),
        deleteProperty: () => deny('DOM delete'), defineProperty: () => deny('DOM property mutation')});
    const all = [], nodes = {};
    function matches(node, selector) {
        if (selector === 'a,button') return ['button', 'return'].includes(node.kind);
        if (selector === 'button') return node.kind === 'button' || node.kind === 'outside';
        if (selector.includes('monthly_source_warning_')) return node.kind === 'warning';
        if (selector.includes('epc_workspace_monthly')) return ['workspace', 'extraWorkspace'].includes(node.kind);
        if (selector === '.enfra-source-warning') return node.kind === 'marker';
        if (selector === '.enfra-source-correction-owner') return ['owner', 'extraOwner'].includes(node.kind);
        if (selector.includes('stMainBlockContainer')) return node.kind === 'block';
        if (selector.includes('stMain')) return node.kind === 'main';
        if (selector === '[data-stale="true"]') return node.kind === 'button' && config.button.stale;
        if (selector === '[inert]') return node.kind === 'button' && config.button.inert;
        if (selector.includes('stSkeleton')) return false;
        throw Error('Unexpected observer selector: ' + selector);
    }
    const descends = (node, parent) => {
        for (let cursor = node.parentElement; cursor; cursor = cursor.parentElement)
            if (cursor === parent) return true;
        return false;
    };
    const enabled = node => (node.kind !== 'extraWorkspace' || config.workspaceCount > 1) &&
        (node.kind !== 'extraOwner' || config.ownerCount > 1);
    const query = (parent, selector) => all.filter(node => enabled(node) &&
        (!parent || descends(node, parent)) && matches(node, selector));
    function node(kind, parent, tag = 'DIV') {
        const value = {kind, tagName: tag, nodeType: 1,
            get parentElement() {return nodes[parent] || null;},
            get isConnected() {return config[kind]?.connected ?? true;},
            get disabled() {return config[kind]?.disabled ?? false;},
            get dataset() {
                if (kind === 'marker') return readonly(config.marker);
                if (kind === 'owner') return readonly(config.owner);
                if (kind === 'workspace') return readonly({epcMode: config.workspace.mode});
                return readonly({});
            },
            get _epcWorkspace() {return config.workspace.identity ? readonly({identity: config.workspace.identity}) : undefined;},
            get textContent() {return kind === 'button' ? 'Correct date' : '';},
            get scrollTop() {return kind === 'main' ? config.main.scrollTop : 0;},
            get scrollLeft() {return kind === 'main' ? config.main.scrollLeft : 0;},
            get scrollHeight() {return kind === 'main' ? config.main.scrollHeight : 0;},
            get clientHeight() {return kind === 'main' ? config.main.clientHeight : 0;},
            get value() {return deny('field value read');},
            get checked() {return deny('field checked read');},
            get selectedOptions() {return deny('field selection read');},
            style: readonly({}), classList: readonly({contains: name => kind === 'return' && name === 'enfra-source-review-return',
                add: () => deny('class mutation'), remove: () => deny('class mutation')}),
            closest(selector) {for (let cursor = this; cursor; cursor = cursor.parentElement) if (matches(cursor, selector)) return cursor; return null;},
            contains(other) {assert.equal(typeof other?.nodeType, 'number', 'Node.contains requires a Node target'); return other === this || descends(other, this);},
            addEventListener(...args) {return listenerMethods(kind).addEventListener(...args);},
            removeEventListener(...args) {return listenerMethods(kind).removeEventListener(...args);},
            querySelectorAll(selector) {return query(this, selector);},
            querySelector(selector) {return query(this, selector)[0] || null;},
            getAttribute(name) {if (name === 'value') return deny('field attribute read'); return name === 'href' ? '#review' : null;},
            getBoundingClientRect() {return {x: 20, y: config.offset - config.main.scrollTop, width: 100, height: 40};},
            click: () => deny('click'), focus: () => deny('focus'), scrollTo: () => deny('scroll'),
            scrollIntoView: () => deny('scroll'), dispatchEvent: () => deny('dispatch'),
            setAttribute: () => deny('attribute mutation'), remove: () => deny('node removal'),
            appendChild: () => deny('node insertion'), setPointerCapture: () => deny('pointer capture')};
        const result = readonly(value); all.push(result); nodes[kind] = result; return result;
    }
    node('html', null, 'HTML'); node('main', 'html'); node('block', 'main');
    node('warning', 'block'); node('marker', 'warning'); node('button', 'warning', 'BUTTON');
    node('span', 'button', 'SPAN'); node('outside', 'block', 'BUTTON'); node('return', 'block', 'A');
    node('workspace', 'block'); node('extraWorkspace', 'block');
    node('owner', 'workspace'); node('extraOwner', 'workspace');
    const listenerMethods = surface => ({
        addEventListener(type, callback, options) {
            assert.equal(options.capture, true); assert.equal(options.passive, true);
            if (!buses[surface].has(type)) buses[surface].set(type, new Set());
            buses[surface].get(type).add(callback);
        },
        removeEventListener(type, callback) {buses[surface].get(type)?.delete(callback);},
    });
    const document = readonly({...listenerMethods('document'), nodeType: 9,
        get hidden() {return config.hidden;}, get visibilityState() {return config.visibility;},
        activeElement: nodes.button, scrollingElement: nodes.html,
        querySelectorAll: selector => query(null, selector),
        querySelector: selector => query(null, selector)[0] || null,
        createElement: () => deny('create node')});
    const window = {...listenerMethods('window'), scrollTo: () => deny('window scroll')};
    class ResizeObserver {
        constructor(callback) {this.callback = callback; this.live = true; this.targets = new Set(); observers.push(this);}
        observe(target) {this.targets.add(target);}
        disconnect() {this.live = false; this.targets.clear();}
    }
    const context = vm.createContext({document, window, ResizeObserver,
        performance: {now: () => config.time}, getComputedStyle: () => ({overflowY: 'auto'}),
        requestAnimationFrame: callback => {frames.set(++sequence, callback); return sequence;},
        cancelAnimationFrame: id => frames.delete(id)});
    const install = () => {for (const source of installers) vm.runInContext('(' + source + ')()', context);};
    const fire = (type, fields = {}, surface = 'document') => {
        config.time++;
        const pointer = type.startsWith('pointer') || type === 'click';
        const event = {type, isTrusted: true,
            target: surface === 'window' ? window : type === 'visibilitychange' ? document : nodes.span,
            ...(pointer ? {isPrimary: true, button: 0, pointerType: 'mouse', pointerId: 7, clientX: 40, clientY: 320} : {}),
            preventDefault: () => deny('prevent event'), stopPropagation: () => deny('stop event'),
            stopImmediatePropagation: () => deny('stop event'), ...fields};
        for (const callback of [...(buses[surface].get(type) || [])])
            if (buses[surface].get(type).has(callback)) callback(event);
    };
    const frame = () => {config.time += 16; for (const [id, callback] of [...frames]) {frames.delete(id); callback(config.time);}};
    const resize = () => {config.time++; for (const observer of observers) if (observer.live)
        observer.callback([...observer.targets].map(target => ({target})), observer);};
    install();
    const result = {config, nodes, document, window, frames, observers, attempted, install, fire, frame, resize,
        record: () => window.__sourceColdGestureObservations,
        last: () => window.__sourceColdGestureObservations.samples.at(-1),
        live: () => observers.filter(observer => observer.live).length,
        listenerCount: surface => [...buses[surface].values()].reduce((sum, callbacks) => sum + callbacks.size, 0)};
    fixtures.push(result); return result;
}

const cases = {};
cases.admission = () => {
    const h = fixture(), record = h.record();
    assert.ok(record, 'cold input evidence must be installed');
    assert.equal(record.sampleLimit, 128); assert.equal(record.samples.length, 0);
    h.fire('pointerdown', {target: h.nodes.outside}); assert.equal(record.samples.length, 0);
    h.fire('pointerdown'); const sample = h.last();
    assert.equal(sample.type, 'pointerdown'); assert.equal(typeof sample.time, 'number');
    for (const [key, expected] of Object.entries({isTrusted: true, isPrimary: true, button: 0,
        pointerType: 'mouse', pointerId: 7, clientX: 40, clientY: 320, key: null,
        targetTag: 'SPAN', targetInButton: true})) assert.equal(sample.event[key], expected, key);
    assert.equal(sample.document.hidden, false); assert.equal(sample.document.visibility, 'visible');
    assert.equal(sample.button.connected, true); assert.equal(sample.button.disabled, false);
    assert.equal(sample.button.stale, false); assert.equal(sample.button.inert, false);
    assert.deepEqual(JSON.parse(JSON.stringify(sample.button.rect)), {x: 20, y: 300, width: 100, height: 40});
    assert.equal(sample.marker.reportIdentity, REPORT); assert.equal(sample.marker.sourceId, SOURCE);
    assert.equal(sample.marker.connected, true); assert.equal(sample.workspace.count, 1);
    assert.equal(sample.workspace.connected, true); assert.equal(sample.workspace.mode, null);
    assert.equal(sample.workspace.identity, null); assert.equal(sample.workspace.ownerCount, 1);
    assert.equal(sample.workspace.owner.reportIdentity, REPORT); assert.equal(sample.workspace.owner.connected, true);
    assert.equal(sample.main.connected, true); assert.equal(sample.main.blockConnected, true);
    for (const [key, value] of Object.entries(h.config.main)) assert.equal(sample.main[key], value);
    h.fire('pointerup'); h.fire('click');
    const navigation = h.window.__sourceCorrectionNavigationObservations;
    assert.deepEqual(Array.from(navigation, entry => entry.type), ['pointerdown', 'pointerup', 'click']);
    assert.equal(navigation[0].source, '#source-details-' + SOURCE + '--date');
    assert.equal(navigation[0].node, navigation[2].node);
};
cases['input-flags'] = () => {
    for (const fields of [{isTrusted: false}, {isPrimary: false}, {button: 2}, {pointerType: 'touch'}, {pointerType: 'pen'}]) {
        const h = fixture(); h.fire('pointerdown', fields);
        assert.equal(h.record().samples.length, 1, 'rejected input still needs diagnostic evidence');
        for (const [key, value] of Object.entries(fields)) assert.equal(h.last().event[key], value);
    }
};
cases['intermediate-geometry'] = () => {
    const h = fixture(); h.fire('pointerdown');
    h.config.offset += 218; h.config.main.scrollHeight += 218; h.resize();
    assert.equal(h.last().type, 'resize'); assert.equal(h.last().button.rect.y, 518);
    assert.equal(h.last().main.scrollHeight - h.last().main.clientHeight, 1218);
    h.frame(); assert.equal(h.last().type, 'animation-frame'); assert.equal(h.last().event, null);
    assert.equal(h.last().button.rect.y, 518);
    h.config.main.scrollTop += 30; h.fire('scroll', {target: h.nodes.main}, 'main');
    assert.equal(h.last().type, 'scroll'); assert.equal(h.last().button.rect.y, 488);
    assert.equal(h.last().main.scrollTop, 130);
    assert.equal(h.record().samples[0].button.rect.y, 300, 'earlier evidence must remain immutable');
    assert.equal(h.config.offset, 618); assert.equal(h.config.main.scrollTop, 130);
};
cases['unrelated-pointer'] = () => {
    const h = fixture(); h.fire('pointerdown');
    for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'])
        h.fire(type, {pointerId: 9, isPrimary: false, target: h.nodes.outside});
    assert.equal(h.record().stopReason, null); assert.equal(h.live(), 1);
    assert.equal(h.record().samples[0].event.pointerId, 7);
    const other = h.record().samples.find(sample => sample.event?.pointerId === 9);
    assert.ok(other); assert.equal(other.event.targetInButton, false); assert.equal(other.event.isPrimary, false);
    h.fire('pointerup', {target: h.nodes.outside}); assert.equal(h.record().stopReason, 'pointerup');
};
cases['before-gesture'] = () => {
    for (const type of ['wheel', 'keydown', 'visibilitychange', 'blur']) {
        const h = fixture(); h.fire(type, {}, type === 'blur' ? 'window' : 'document');
        assert.equal(h.record().samples.length, 0); assert.equal(h.record().stopReason, null);
        h.fire('pointerdown'); assert.equal(h.record().samples[0].type, 'pointerdown');
        assert.equal(h.live(), 1);
    }
};
for (const type of ['pointerup', 'pointercancel', 'wheel', 'keydown', 'blur', 'pagehide', 'visibilitychange']) {
    cases[type] = () => {
        const h = fixture(); h.fire('pointerdown');
        if (type === 'visibilitychange') {h.config.hidden = true; h.config.visibility = 'hidden';}
        h.fire(type, type === 'keydown' ? {key: 'Escape'} : {}, ['blur', 'pagehide'].includes(type) ? 'window' : 'document');
        assert.equal(h.last().type, type); assert.equal(h.record().stopReason, type);
        if (type === 'visibilitychange') {assert.equal(h.last().document.hidden, true); assert.equal(h.last().document.visibility, 'hidden');}
        if (type === 'keydown') assert.equal(h.last().event.key, 'Escape');
        assert.equal(h.live(), 0); assert.equal(h.frames.size, 0);
        assert.equal(h.listenerCount('document'), 6, 'only the original navigation listeners remain');
        assert.equal(h.listenerCount('main'), 0); assert.equal(h.listenerCount('window'), 0);
        const length = h.record().samples.length;
        h.fire('pointerdown'); h.fire('scroll', {target: h.nodes.main}, 'main'); h.resize(); h.frame();
        assert.equal(h.record().samples.length, length, 'completed first gesture cannot reacquire');
    };
}
cases['identity-changes'] = () => {
    const h = fixture(); h.fire('pointerdown');
    h.config.marker.reportIdentity = 'b'.repeat(24); h.config.marker.sourceId = 'd'.repeat(64);
    h.config.workspace.mode = 'wide'; h.config.workspace.identity = 'e'.repeat(24);
    h.config.owner.reportIdentity = 'f'.repeat(24); h.frame();
    assert.equal(h.last().marker.reportIdentity, h.config.marker.reportIdentity);
    assert.equal(h.last().marker.sourceId, h.config.marker.sourceId);
    assert.equal(h.last().workspace.mode, 'wide'); assert.equal(h.last().workspace.identity, h.config.workspace.identity);
    assert.equal(h.last().workspace.owner.reportIdentity, h.config.owner.reportIdentity);
    h.config.button.disabled = true; h.config.button.stale = true; h.config.button.inert = true;
    h.config.button.connected = false; h.config.marker.connected = false; h.frame();
    for (const key of ['disabled', 'stale', 'inert']) assert.equal(h.last().button[key], true);
    assert.equal(h.last().button.connected, false); assert.equal(h.last().marker.connected, false);
    h.config.workspaceCount = 2; h.config.ownerCount = 2; h.frame();
    assert.equal(h.last().workspace.count, 2); assert.equal(h.last().workspace.ownerCount, 2);
    assert.equal(h.record().stopReason, null);
    assert.equal(h.record().samples[0].marker.reportIdentity, REPORT);
};
cases['sample-limit'] = () => {
    const h = fixture(); h.fire('pointerdown');
    for (let i = 0; i < 140; i++) h.frame();
    assert.equal(h.record().samples.length, 128); assert.equal(h.record().truncated, true);
    assert.equal(h.record().stopReason, 'sample-limit'); assert.equal(h.live(), 0); assert.equal(h.frames.size, 0);
    assert.equal(h.listenerCount('document'), 6); assert.equal(h.listenerCount('main'), 0); assert.equal(h.listenerCount('window'), 0);
    assert.equal(h.record().samples[0].type, 'pointerdown'); h.resize(); h.fire('pointerup');
    assert.equal(h.record().samples.length, 128);
};
cases.reinstall = () => {
    const h = fixture(); h.fire('pointerdown'); const first = h.record();
    h.install(); assert.strictEqual(h.record(), first); assert.equal(h.live(), 1); assert.equal(h.frames.size, 1);
    h.frame(); h.fire('pointerup'); const length = first.samples.length;
    h.install(); h.fire('pointerdown'); h.frame();
    assert.strictEqual(h.record(), first); assert.equal(first.samples.length, length); assert.equal(h.live(), 0);
};
cases['passive-traps'] = () => {
    const h = fixture();
    for (const operation of [() => h.nodes.button.value, () => h.nodes.button.click(),
        () => h.nodes.main.scrollTo({top: 0}), () => {h.nodes.main.scrollTop = 0;},
        () => h.nodes.button.setAttribute('disabled', ''), () => h.nodes.button.style.top = '0',
        () => Object.defineProperty(h.nodes.button, 'newProperty', {value: 'mutation'})])
        assert.throws(operation, /passive observer:/);
    h.attempted.length = 0;
    h.fire('pointerdown'); h.resize(); h.frame(); h.fire('pointerup'); h.fire('click');
};

assert.ok(cases[caseName], 'Unknown case: ' + caseName);
cases[caseName]();
for (const h of fixtures) assert.deepEqual(h.attempted, [], 'observer attempted a prohibited effect');
console.log(JSON.stringify({case: caseName, passed: true}));
