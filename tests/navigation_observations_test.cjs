const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('scripts/qa_navigation_observations.js','utf8');
function harness(){
 const callbacks=new Map(),micro=[],observers=[];let calls=0,time=0;
 const node=()=>({isConnected:true,dataset:{},scrollTop:0,querySelectorAll:()=>[],querySelector:()=>null,closest:()=>null,contains:()=>true});
 const app=node(),port=node(),root=node(),nav=node(),next=node(),back=node(),status=node(),target=node(),marker=node();
 marker.dataset.epcPair='private-section'; marker.closest=s=>s.includes('epc_pair')?target:null;
 status.dataset.section='private-section'; next.onclick=()=>{calls++};next.disabled=false;
 root._epcWorkspace={identity:'secret-report-identity',mode:'compact',navigationActive:'private-section',navigationController:{}};
 root.dataset.epcFullRender='secret-render-token';root.closest=s=>s.includes('stMainBlockContainer')?app:port;
 root.querySelectorAll=s=>s.includes('monthly_report_navigation')?[nav]:s==='[data-epc-pair]'?[marker]:[];
 nav.querySelectorAll=s=>s==='.epc-section-next'?[next]:s==='.epc-section-back'?[back]:s==='.epc-section-progress'?[status]:[];
 const doc={activeElement:next,querySelectorAll:s=>s.includes('epc_workspace_monthly')?[root]:[],querySelector:()=>({getAttribute:()=> 'notRunning'})};
 const win={innerWidth:390,innerHeight:844};
 for(const [name,obj]of[['doc',doc],['win',win]]){obj.addEventListener=(type,cb,options)=>{assert.equal(options.passive,true);callbacks.set(name+type,cb)};obj.removeEventListener=(type,cb)=>{assert.equal(callbacks.get(name+type),cb);callbacks.delete(name+type)}}
 class MutationObserver{constructor(cb){this.cb=cb;this.active=false;observers.push(this)} observe(){this.active=true}disconnect(){this.active=false}}
 const context={window:win,document:doc,MutationObserver,TextEncoder,CSS:{escape:s=>s.replace(/:/g,'\\:')},performance:{now:()=>++time},queueMicrotask:cb=>micro.push(cb)};
 const result=vm.runInNewContext('('+source+')()',context);
 return{result,root,next,back,nav,doc,win,target,marker,status,app,port,callbacks,observers,
  mutate:()=>observers[0].cb(),dispatch:(type,extra={})=>{const event={type,target:next,isTrusted:true,defaultPrevented:false,...extra};callbacks.get('doc'+type)?.(event);return event;},
  flush:()=>{while(micro.length)micro.shift()()},stop:()=>win.__enfraNavigationObservation.stop(),calls:()=>calls};
}
test('passive installation, metadata only and cleanup',()=>{const h=harness();assert.equal(h.result.installed,true);const handler=h.next.onclick;h.dispatch('keydown',{key:'Enter'});h.flush();const out=h.stop();assert.equal(out.errors,0);assert.equal(out.disposed,true);assert.equal(h.callbacks.size,0);assert.equal(h.observers[0].active,false);assert.equal(h.calls(),0);assert.equal(h.next.onclick,handler);assert.equal(h.doc.activeElement,h.next);assert.equal(h.root.scrollTop,0);const text=JSON.stringify(out);for(const secret of ['secret-report-identity','secret-render-token','private-section'])assert(!text.includes(secret));assert(out.records.some(r=>r.native?.key==='Enter'));});
test('same control pending state and controller replacement stay distinct',()=>{const h=harness(),s=h.root._epcWorkspace;s.navigationRequest='private-section';s.navigationIntent={owner:s.navigationController,identity:s.identity,origin:'private-section',target:'private-section',input:0,back:h.back,next:h.next,nodes:[{id:'private-section',marker:h.marker,target:h.target}]};h.mutate();s.navigationController={};h.mutate();const r=h.stop().records;assert(r.some(r=>r.intent?.owner_matches===true&&r.intent.nodes_match));assert(r.some(r=>r.intent?.owner_matches===false));assert.equal(h.calls(),0)});
test('replacement callback gets a distinct ordinal without reading function source',()=>{const h=harness();h.next.onclick=()=>{};h.mutate();const r=h.stop().records;assert.notEqual(r[0].next.handler,r[1].next.handler)});
test('cold missing workspace and later replacement are observed safely',()=>{const h=harness();h.doc.querySelectorAll=()=>[];h.mutate();const r=h.stop().records;assert(r.some(r=>r.root_count===0));assert.equal(r.at(-1).root.id,0)});
test('record and byte limits include final observation and indicate truncation',()=>{const h=harness();for(let i=0;i<800;i++)h.mutate();const out=h.stop();assert(out.records.length<=256);assert(out.dropped>0);assert.equal(out.records.at(-1).source,'finally');assert(Buffer.byteLength(JSON.stringify(out))<1048576)});
test('stop is idempotent and queued microtasks cannot add records after disposal',()=>{const h=harness();h.dispatch('click');const a=h.stop();h.flush();assert.deepEqual(h.stop(),a)});
test('event values are filtered and postdispatch cancellation is visible',()=>{const h=harness(),ev=h.dispatch('keydown',{key:'private text'});ev.defaultPrevented=true;h.flush();const out=h.stop();assert(!JSON.stringify(out).includes('private text'));assert(out.records.filter(r=>r.native).every(r=>r.native.key===null));assert(out.records.some(r=>r.source==='native-after-dispatch'&&r.native.prevented));});
test('metadata payload can be validated by Python without a browser',()=>{const h=harness();h.dispatch('keydown',{key:'Enter'});h.flush();const out=h.stop();const cp=require('node:child_process').spawnSync('python',['-c','import json,sys; from scripts.qa_navigation_observations import _bounded_result; r=_bounded_result(json.load(sys.stdin), True); assert not r.get("schema_rejected"),r'],{input:JSON.stringify(out),encoding:'utf8'});assert.equal(cp.status,0,cp.stderr)});

test('nested conflicting pair resolves the exact escaped section owner',()=>{const h=harness(),wrong={isConnected:true};let observed=[];h.marker.dataset.epcPair='private:section';h.marker.closest=selector=>{if(selector==='[data-stale="true"]')return null;observed.push(selector);return selector==='.st-key-epc_pair_private\\:section'?h.target:wrong};h.root._epcWorkspace.navigationActive='private:section';h.mutate();const out=h.stop();assert(observed.every(s=>s==='.st-key-epc_pair_private\\:section'));assert.equal(out.records.at(-1).origin.target.id,out.records[0].origin.target.id);});
