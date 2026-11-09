const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function setup() {
    let focused=0, scrolled=0, clicked=0, mutations=0;
    const statusParent={children:[],querySelector(selector){return this.children.find(c=>'.'+c.className===selector)||null},append(node){this.children.push(node)}};
    const link={isConnected:true,dataset:{reportIdentity:'report'},getAttribute:()=> '#report-correction-'+'a'.repeat(64),closest:()=>null,parentElement:statusParent};
    const details={tagName:'DETAILS',open:false,parentElement:null,getAnimations:()=>[],querySelector(selector){return selector.includes('summary')?{click(){clicked++;details.open=true}}:null}};
    const field={isConnected:true,disabled:false,parentElement:details,closest:()=>null,getClientRects:()=>[{}],focus(){focused++},scrollIntoView(){scrolled++}};
    Object.defineProperty(field,'value',{get(){throw Error('must not read input')},set(){mutations++;throw Error('must not write input')}});
    const marker={id:'report-correction-'+'a'.repeat(64),isConnected:true,dataset:{reportIdentity:'report',fieldKey:'exact-caption'},closest:()=>null,parentElement:statusParent};
    let markers=[marker],fields=[field];
    const app={contains:node=>node.isConnected,querySelectorAll:selector=>selector==='.enfra-picture-correction'?markers:fields};
    const document={createElement:()=>({setAttribute(){}})};
    const context={document,CSS:{escape:x=>x},Promise};vm.runInNewContext(fs.readFileSync('app/monthly_report_correction_navigation.js','utf8'),context);
    return {adapter:context.ENFRAPictureCorrections,app,link,marker,field,details,statusParent,
        markers:values=>markers=values,fields:values=>fields=values,
        counts:()=>({focused,scrolled,clicked,mutations})};
}
test('opens only exact caption through native disclosure and never touches input values',async()=>{
    const h=setup();h.adapter.reveal(h.app,h.link,'report',()=>true);await Promise.resolve();await Promise.resolve();
    assert.deepEqual(h.counts(),{focused:1,scrolled:1,clicked:1,mutations:0});
    assert.equal(h.statusParent.children[0].href,'#report-review');
    assert.equal(h.statusParent.children[0].textContent,'Return to Review');
});
for(const state of ['missing','duplicate','other-report','retired-link','retired-marker','disabled-field','duplicate-field']) {
    test(state+' cannot redirect to another caption',()=>{
        const h=setup();
        if(state==='missing')h.markers([]);
        if(state==='duplicate')h.markers([h.marker,h.marker]);
        if(state==='other-report')h.marker.dataset.reportIdentity='other';
        if(state==='retired-link')h.link.isConnected=false;
        if(state==='retired-marker')h.marker.isConnected=false;
        if(state==='disabled-field')h.field.disabled=true;
        if(state==='duplicate-field')h.fields([h.field,h.field]);
        assert.equal(h.adapter.resolve(h.app,h.link,'report'),null);
        h.adapter.reveal(h.app,h.link,'report',()=>true);
        assert.equal(h.counts().focused,0);
        assert.match(h.statusParent.children[0].textContent,/changed or is not available/);
    });
}
test('new human action cancels focus after disclosure animation',async()=>{
    const h=setup();let finish;const animation=new Promise(resolve=>finish=resolve);
    h.details.getAnimations=()=>[{playState:'running',effect:{getComputedTiming:()=>({endTime:200})},finished:animation}];
    let current=true;h.adapter.reveal(h.app,h.link,'report',()=>current);current=false;finish();
    await animation;await Promise.resolve();await Promise.resolve();
    assert.equal(h.counts().focused,0);
});
test('replacement of exact marker while disclosure opens cancels focus',async()=>{
    const h=setup();h.adapter.reveal(h.app,h.link,'report',()=>true);h.markers([{...h.marker}]);
    await Promise.resolve();await Promise.resolve();assert.equal(h.counts().focused,0);
});

for (const [kind,selector] of Object.entries({textarea:' textarea',input:' input',
    combobox:' [role="combobox"]',checkbox:' input[type="checkbox"]',
    button:' button',radio:' input[type="radio"]:checked'})) {
    test('exact native '+kind+' selector is bounded to the named existing field', async()=>{
        const h=setup();h.marker.dataset.fieldKind=kind;
        h.app.querySelectorAll = query => query === '.enfra-picture-correction' ? [h.marker] :
            query === '.st-key-exact-caption'+selector ? [h.field] : [];
        h.adapter.reveal(h.app,h.link,'report',()=>true);
        await Promise.resolve();await Promise.resolve();
        assert.deepEqual(h.counts(),{focused:1,scrolled:1,clicked:1,mutations:0});
    });
}
test('unrecognized field kind cannot broaden selection or substitute a field',()=>{
    const h=setup();h.marker.dataset.fieldKind='textarea, input';
    assert.equal(h.adapter.resolve(h.app,h.link,'report'),null);
    assert.equal(h.counts().mutations,0);
});

for (const state of ['enabled','disabled','retired']) {
    test('month-confirmation button focus is never an implicit confirmation: '+state, async()=>{
        const h=setup();h.marker.dataset.fieldKind='button';
        h.field.click=()=>{throw Error('must not activate confirmation')};
        if(state==='disabled')h.field.disabled=true;
        if(state==='retired')h.field.isConnected=false;
        h.app.querySelectorAll=query=>query==='.enfra-picture-correction'?[h.marker]:
            query==='.st-key-exact-caption button'?[h.field]:[];
        h.adapter.reveal(h.app,h.link,'report',()=>true);
        await Promise.resolve();await Promise.resolve();
        assert.equal(h.counts().focused,state==='enabled'?1:0);
        assert.equal(h.counts().mutations,0);
        if(state!=='enabled')assert.match(h.statusParent.children[0].textContent,/changed or is not available/);
    });
}

for (const state of ['enabled','disabled','retired']) {
    test('financial attestation checkbox focus never checks or activates it: '+state, async()=>{
        const h=setup();h.marker.dataset.fieldKind='checkbox';
        h.field.click=()=>{throw Error('navigation must never attest')};
        Object.defineProperty(h.field,'checked',{
            get(){throw Error('navigation must not inspect consent')},
            set(){throw Error('navigation must never change consent')}
        });
        if(state==='disabled')h.field.disabled=true;
        if(state==='retired')h.field.isConnected=false;
        h.app.querySelectorAll=query=>query==='.enfra-picture-correction'?[h.marker]:
            query==='.st-key-exact-caption input[type="checkbox"]'?[h.field]:[];
        h.adapter.reveal(h.app,h.link,'report',()=>true);
        await Promise.resolve();await Promise.resolve();
        assert.equal(h.counts().focused,state==='enabled'?1:0);
        assert.equal(h.counts().mutations,0);
    });
}
