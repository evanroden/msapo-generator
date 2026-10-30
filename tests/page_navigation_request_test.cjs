const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');
function harness() {
    const state={mode:'wide',ownsScroll:false,identity:'report'};
    const rect=(top,height)=>({top,bottom:top+height,height});
    const scrollport={scrollTop:0,getBoundingClientRect:()=>rect(0,900)};
    const root={dataset:{},scrollTop:0,getBoundingClientRect:()=>rect(300-scrollport.scrollTop,3500)};
    const field={isConnected:true,disabled:false,parentElement:null,closest:()=>null,getClientRects:()=>[{}],focus(){focus++},scrollIntoView(){}};
    const parent={children:[],querySelector:()=>null,append(value){this.children.push(value)}};
    const marker={id:'report-correction-'+'a'.repeat(64),isConnected:true,dataset:{reportIdentity:'report',fieldKey:'caption',fieldKind:'input'},closest:()=>null,parentElement:parent};
    const link={isConnected:true,dataset:{reportIdentity:'report',token:'first'},getAttribute:()=> '#'+marker.id,closest:()=>null,parentElement:parent};
    let requests=[link],focus=0,schedules=0;
    const pair=(top,inside=false)=>({isConnected:true,contains:node=>inside&&node===marker,querySelector:()=>null,setAttribute(){},focus(){},getBoundingClientRect:()=>rect(top-scrollport.scrollTop,500)});
    const water=pair(1500,true),review=pair(4000),cover=pair(300);
    const back={disabled:false},next={disabled:false,textContent:'Next'},progress={dataset:{},textContent:''};
    const nav={getBoundingClientRect:()=>rect(64,52),querySelector:selector=>({'.epc-section-back':back,'.epc-section-next':next,'.epc-section-progress':progress})[selector]||null};
    const handlers={};
    const app={contains:node=>node.isConnected,querySelector:()=>review,
        querySelectorAll:selector=>selector==='.enfra-page-correction-request'?requests:selector==='.enfra-picture-correction'?[marker]:selector==='.st-key-caption input'?[field]:[],
        addEventListener(type,fn){handlers[type]=fn},removeEventListener(type){delete handlers[type]}};
    const context={document:{activeElement:null,createElement:()=>({})},CSS:{escape:x=>x},Promise};
    vm.createContext(context);
    for(const file of ['monthly_report_correction_navigation.js','workspace_navigation.js'])vm.runInContext(fs.readFileSync('app/'+file,'utf8'),context);
    const controller=context.ENFRAWorkspaceNavigation.create({root,app,scrollport,nav,state,geometry,schedule(){schedules++}});
    function measure(){const resolved=controller.prepare({mode:'wide',reason:'normal'},
        {chromeBottom:64,scrollport:{y:0},visual:{y:0}},[
        {id:'monthly_cover',title:'Cover',pair:cover},{id:'monthly_water',title:'Water',pair:water}]);
        controller.update(resolved,{chromeBottom:64,scrollport:{y:0},visual:{y:0}})}
    return {measure,state,link,marker,requests:value=>requests=value,counts:()=>({focus,schedules}),handlers};
}
const settled=async()=>{await Promise.resolve();await Promise.resolve();};
test('a committed exact page request navigates and focuses once across passive rerenders',async()=>{
    const h=harness();h.measure();await settled();assert.equal(h.state.navigationActive,'monthly_water');assert.equal(h.counts().focus,1);
    const before=h.counts();h.measure();h.measure();await settled();assert.deepEqual(h.counts(),before);
});
test('duplicate current request signals cannot choose an arbitrary owner',async()=>{
    const h=harness();h.requests([h.link,{...h.link}]);h.measure();await settled();assert.equal(h.counts().focus,0);assert.equal(h.counts().schedules,0);
});
test('a previously consumed nonce never regains focus after a newer request',async()=>{
    const h=harness();h.measure();await settled();h.link.dataset.token='second';h.measure();await settled();assert.equal(h.counts().focus,2);
    h.link.dataset.token='first';h.measure();await settled();assert.equal(h.counts().focus,2);
});
test('a newer native action cancels the queued display focus',async()=>{
    const h=harness();h.measure();h.handlers.pointerdown();await settled();assert.equal(h.counts().focus,0);
});
