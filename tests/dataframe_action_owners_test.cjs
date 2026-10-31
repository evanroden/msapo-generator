'use strict';
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const source=JSON.parse(process.argv[2]);
// Execute exact shipped hook, menu, manager and app cleanup bodies. Only React
// hook scheduling/JSX and browser timer collaborators are deterministic fakes.
// This is lifecycle unit evidence, not a local browser or native input proof.
function hooks(){
 const slots=[];let cursor=0,effects=[];
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((x,i)=>Object.is(x,b[i]));
 const U={
  useState(init){const i=cursor++;slots[i]??={value:typeof init==='function'?init():init};return[slots[i].value,x=>{slots[i].value=typeof x==='function'?x(slots[i].value):x}]},
  useRef(init){const i=cursor++;slots[i]??={current:init};return slots[i]},
  useCallback(fn,deps){const i=cursor++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={value:fn,deps};return slots[i].value},
  useEffect(fn,deps){const i=cursor++;if(!slots[i]||!same(slots[i].deps,deps)){const old=slots[i];slots[i]={deps};effects.push(()=>{old?.cleanup?.();slots[i].cleanup=fn()})}},
 };
 return{U,render(fn,...args){cursor=0;const result=fn(...args);for(const f of effects)f();effects=[];return result},dispose(){for(const s of slots)s?.cleanup?.()}};
}
const all=[];
(async()=>{
 globalThis.window={};
 const protobuf=await import(pathToFileURL(source.protobuf));
 const {Vs,Hs,Ys}=new Function('B','H','var '+source.treeNodes+';var '+source.appRoot+';return {Vs,Hs,Ys}')(protobuf.a,x=>x==null);
 const NativeState=new Function('qe','tt','return '+source.stateClass)(protobuf.H,protobuf.U);
 const getId=new Function('ne','Rt',source.getWidgetId+';return Wt')((o,p)=>p.reduce((v,k)=>v?.[k],o),x=>x);
 const cleanup=new Function('I','ce','return ({'+source.cleanup+'})').call(null,getId,x=>x!==undefined).removeInactiveWidgetState;
 const scriptFinished=new Function('gt','return ({'+source.scriptFinished+'})')(protobuf.v).handleScriptFinished;
 const fixedCleanup=new Function('I','ce','return ({'+source.fixedCleanup+'})').call(null,getId,x=>x!==undefined).removeInactiveWidgetState;
 const frameId='$$ID-synthetic-native-grid', actionId='$$ID-synthetic-native-row-action';
 const otherId='$$ID-synthetic-other-button', retiredId='$$ID-synthetic-retired-row-action';
 function scenario({fixed=false, order='select-cleanup-flush', disabled=false, missing=false, replacement=false, unmounted=false, nonframe=false, cancel=false, double=false, key=null, staleRun=false, staleParent=false, moved=false, movedCurrent=false, duplicate=false, noButtons=false, fresh=false, replay=false, fragment=false, staleFragment=false}={}){
  const timers=[],frames=[],sent=[],assigned=[];let serial=0;
  const mgr=new Function('Ze','qg','A','setTimeout','return ({'+source.managerMethods+'})')(
   protobuf.L,{warn(){}},x=>!!x,fn=>timers.push(fn));
  Object.assign(mgr,{widgetStates:new NativeState, forms:new Map,elementStates:new Map,
   pendingTriggerIds:new Set,triggerFlushResolvers:[],flushScheduled:false,hasFragmentIdConflict:false,
   props:{sendRerunBackMsg(msg,fragment){sent.push({fragment,widgets:protobuf.U.toObject(msg)})}},maybeSyncValueToUrl(){}});
  const realSet=mgr.setStringTriggerValue;
  mgr.setStringTriggerValue=function(...args){assigned.push(args);return realSet.apply(this,args)};
  const selectedAction=fresh?'$$ID-synthetic-fresh-row-action':actionId;
  const element={id:frameId,formId:'',buttonClickWidgets:{__work_order_row_action:selectedAction},disabled:false};
  const env=hooks();const actions=['Insert blank above','Insert blank below'];
  const hook=new Function('U','requestAnimationFrame','cancelAnimationFrame','zl','Dh','Bl','return '+source.hook)(env.U,
   fn=>{const id=++serial;frames.push({id,fn});return id},id=>{const f=frames.find(x=>x.id===id);if(f)f.cancelled=true},
   ()=>true,(column,map)=>map[column.name]?column.name:undefined,()=>({kind:'menu',actions,bounds:{clickY:300,clickX:190}}));
  let props={element,widgetMgr:mgr,columns:[{name:'__work_order_row_action'}],getCellContent:()=>({}),getOriginalIndex:x=>x,theme:{},disabled:false};
  let h=env.render(hook,props);
  const edit=JSON.stringify({edited_rows:{0:{'Work orders':'Received edited before insertion'}},added_rows:[],deleted_rows:[]});
  mgr.widgetStates.createState(otherId).boolValue=true;
  mgr.setStringValue({id:frameId,formId:''},edit,{fromUi:true},'');
  timers.shift()();assert.equal(sent.length,1);
  h.onCellClicked([0,0],{bounds:{},localEventX:5,localEventY:5,preventDefault(){}});
  for(const f of frames.splice(0))if(!f.cancelled)f.fn();h=env.render(hook,props);
  assert.deepEqual(h.buttonActionMenu.actions,actions);
  if(disabled||missing){props={...props,disabled,widgetMgr:missing?undefined:mgr};h=env.render(hook,props)}
  if(cancel){h.clearButtonActionMenu();h=env.render(hook,props)}
  const activeFrame={type:nonframe?'textInput':'dataframe',dataframe:{...element,
   buttonClickWidgets:noButtons?{}:replacement?{__work_order_row_action:'$$ID-synthetic-new-row-action'}:element.buttonClickWidgets}};
  const run='current',old='previous',parentId='$$ID-synthetic-parent-container';
  const node=new Hs(activeFrame,{},staleRun||moved||staleFragment?old:run,'app',staleFragment?'fragment':undefined);
  const roots=Array.from({length:4},()=>new Vs('app',[],{},run));
  roots[0]=new Vs('app',unmounted||movedCurrent?[]:[node],{id:parentId},staleParent?old:run,staleFragment?'fragment':undefined);
  if(movedCurrent)roots[1].children.push(node);
  if(moved)roots[1].children.push(new Hs({type:'dataframe',dataframe:{id:'$$ID-synthetic-moved-grid',buttonClickWidgets:{row:'$$ID-synthetic-moved-action'}}},{},run,'app'));
  if(duplicate)roots[1].children.push(new Hs({type:'dataframe',dataframe:{id:'$$ID-synthetic-second-grid',buttonClickWidgets:{row:selectedAction,again:selectedAction}}},{},run,'app'));
  roots[0].children.push(new Hs({type:'button',button:{id:otherId}},{},run,'app'));
  const tree=new Ys('app',new Vs('app',roots,{},run));
  const app={state:{elements:tree,scriptRunId:run,scriptRunFinishedSequence:0,fragmentIdsThisRun:fragment||staleFragment?['fragment']:[],scriptFinishedHandlers:[]},widgetMgr:mgr,
   connectionManager:null,setState(fn,callback){Object.assign(this.state,fn(this.state));callback?.()},removeInactiveWidgetState:fixed?fixedCleanup:cleanup};
  // A previous retired action is a canary: retaining all pending triggers would
  // pass the positive case but incorrectly keep this no-longer-owned action.
  if(order!=='select-flush-cleanup'){
   mgr.widgetStates.createState(retiredId).stringTriggerValue=new protobuf.L({data:'retired'});
   mgr.pendingTriggerIds.add(retiredId);
  }
  const clean=()=>{scriptFinished.call(app,protobuf.v.ScriptFinishedStatus.FINISHED_SUCCESSFULLY)};
  const select=()=>{
   // Use the exact menu component's own select/key handler, not a guessed call.
   const menuEnv=hooks(); const jsx=(type,props)=>({type,props});
   const menu=new Function('U','Be','Ct','Wg','document','window','a','o','s','Ug','Yg','n_','r_','Ae','je','k','return '+source.menu)(
    menuEnv.U,()=>({refs:{},floatingStyles:{}}),()=>({panelRef:{current:{contains:()=>true}},setFloatingRef(){}}),6,
    {addEventListener(){},removeEventListener(){}},{addEventListener(){},removeEventListener(){}},jsx,jsx,'fragment','portal','panel','list','item',label=>({text:label}),'icon','markdown');
   const tree=menuEnv.render(menu,{top:300,left:190,actions,onSelectAction:h.handleMenuSelectAction,onCloseMenu:h.clearButtonActionMenu});
   const item=tree.props.children[1].props.children.props.children.props.children[0];
   assert.equal(item.props.role,'menuitem');
   if(key)item.props.onKeyDown({key,preventDefault(){}});else item.props.onClick();
   if(double)item.props.onClick();
   menuEnv.dispose();h=env.render(hook,props);
  };
  if(order==='cleanup-select-flush'){clean();select()}
  else if(order==='select-flush-cleanup'){select();for(const f of timers.splice(0))f();clean()}
  else {select();clean()}
  for(const f of timers.splice(0))f();
  assert.equal(mgr.widgetStates.getState(retiredId),undefined,'retired actions must be cleaned');
  assert.equal(mgr.widgetStates.getState(selectedAction),undefined,'consumed action must not linger');
  assert.equal(sent.flatMap(m=>m.widgets.widgets||[]).filter(w=>w.id===retiredId).length,0,'pending intent cannot outlive its retired owner');
  if(!staleRun&&!staleParent&&!moved&&!unmounted&&!nonframe&&!staleFragment){
   for(const packet of sent){assert.equal(packet.widgets.widgets.find(w=>w.id===frameId).stringValue,edit);assert.equal(packet.widgets.widgets.find(w=>w.id===otherId).boolValue,true)}
  }
  const actionMessages=sent.flatMap(m=>m.widgets.widgets||[]).filter(w=>w.id===selectedAction);
  if(replay){const count=sent.length, accepted=assigned.length;select();for(const f of timers.splice(0))f();assert.equal(assigned.length,accepted);assert.equal(sent.length,count)}
  const result={fixed,order,disabled,missing,replacement,unmounted,nonframe,cancel,double,key,staleRun,staleParent,moved,movedCurrent,duplicate,noButtons,fresh,replay,fragment,staleFragment,assigned:assigned.length,packets:sent.length,actionPackets:actionMessages.length,menuClosed:h.buttonActionMenu===undefined};
  if(actionMessages.length){assert.equal(actionMessages[0].stringTriggerValue.data,JSON.stringify({row:0,label:actions[0]}));assert.equal(actionMessages.length,1)}
  // A later ordinary edit must not replay any consumed action.
  mgr.setStringValue({id:frameId,formId:''},'later delivered edit',{fromUi:true},'');
  for(const f of timers.splice(0))f();
  assert.ok(sent.at(-1).widgets.widgets.every(w=>!w.stringTriggerValue));
  env.dispose();all.push(result);return result;
 }
 const before=scenario();assert.equal(before.assigned,1);assert.equal(before.actionPackets,0);assert.equal(before.packets,2);assert.equal(before.menuClosed,true);
 const after=scenario({fixed:true});assert.equal(after.assigned,1);assert.equal(after.actionPackets,1);assert.equal(after.packets,2);
 for(const order of ['cleanup-select-flush','select-flush-cleanup'])for(const fixed of [false,true])assert.equal(scenario({fixed,order}).actionPackets,1);
 for(const field of ['disabled','missing','replacement','unmounted','nonframe','cancel','staleRun','staleParent','moved','noButtons','staleFragment'])for(const fixed of [false,true]){
  const r=scenario({fixed,[field]:true});assert.equal(r.actionPackets,0);
  assert.equal(r.assigned,['disabled','missing','cancel'].includes(field)?0:1);
 }
 for(const key of ['Enter',' ']){assert.equal(scenario({key}).actionPackets,0);assert.equal(scenario({fixed:true,key}).actionPackets,1)}
 for(const field of ['double','duplicate','fresh','replay','movedCurrent','fragment'])assert.equal(scenario({fixed:true,[field]:true}).actionPackets,1);
 // Unrelated native values and ordinary edits are in both snapshots. The
 // accepted action is ephemeral and must never be replayed in a later flush.
 console.log(JSON.stringify({cases:all,pass:true},null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
