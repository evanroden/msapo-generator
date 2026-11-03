const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
function setup(repaired=true) {
 const listeners={},windows={},frames=new Map(),observers=[];let next=1,offset=300,moves=0;
 const on=(map,type,fn)=>{(map[type]??=[]).push(fn)};
 const marker={isConnected:true,dataset:{reportIdentity:'a'.repeat(24),sourceId:'c'.repeat(64)}};
 const owner={dataset:{reportIdentity:'a'.repeat(24)}};
 const workspace={isConnected:true,dataset:{},querySelector:()=>owner};
 const block={};
 const main={isConnected:true,scrollTop:0,scrollLeft:0,querySelector:()=>block,
  scrollTo({top,left,behavior}){assert.equal(behavior,'instant');this.scrollTop=top;this.scrollLeft=left;moves++;}};
 const group={querySelector:()=>marker};
 const button={isConnected:true,disabled:false,stale:false,
  closest(s){if(s==='button')return this;if(s.includes('monthly_source_warning'))return group;if(s.includes('stMain'))return main;if(s.includes('inert'))return this.stale?{}:null;},
  getBoundingClientRect(){return {x:20,y:offset-main.scrollTop,width:100,height:40}}};
 const document={hidden:false,addEventListener:(t,f)=>on(listeners,t,f),querySelector:()=>workspace,querySelectorAll:()=>[workspace]};
 const window={addEventListener:(t,f)=>on(windows,t,f)};
 class ResizeObserver {constructor(fn){this.fn=fn;this.live=true;observers.push(this)}observe(){}disconnect(){this.live=false}}
 if(repaired)vm.runInNewContext(source,{document,window,ResizeObserver,Math,requestAnimationFrame:f=>{frames.set(next,f);return next++},cancelAnimationFrame:i=>frames.delete(i)});
 const fire=(type,fields={},win=false)=>{for(const f of (win?windows:listeners)[type]||[])f({isTrusted:true,isPrimary:true,button:0,pointerType:'mouse',pointerId:1,clientX:40,clientY:320,target:button,...fields})};
 const resize=()=>{for(const o of observers)if(o.live)o.fn()};
 return {button,marker,owner,workspace,main,document,fire,resize,frames,observers,
  shift(n){offset+=n;resize()},get moves(){return moves},get y(){return button.getBoundingClientRect().y},
  active(){return observers.some(o=>o.live)}};
}
let count=0;function test(name,fn){fn();count++;}
test('negative control misses native pointer-up after 218px hydration',()=>{let s=setup(false);s.fire('pointerdown');s.shift(218);assert.equal(s.y,518);assert.equal(s.moves,0)});
test('same pressed button retains geometry without activation',()=>{let s=setup();s.fire('pointerdown');s.shift(218);assert.equal(s.y,300);assert.equal(s.moves,1);s.shift(43);assert.equal(s.y,300);s.fire('pointerup');assert(!s.active());s.shift(50);assert.equal(s.y,350);assert.equal(s.frames.size,0)});
for(const type of ['pointerup','pointercancel','wheel','keydown','visibilitychange'])test(type+' cancels',()=>{let s=setup();s.fire('pointerdown');s.fire(type);s.shift(218);assert.equal(s.moves,0);assert.equal(s.frames.size,0)});
for(const type of ['blur','pagehide'])test(type+' cancels',()=>{let s=setup();s.fire('pointerdown');s.fire(type,{},true);s.shift(218);assert.equal(s.moves,0)});
for(const fields of [{isTrusted:false},{isPrimary:false},{button:2},{pointerType:'touch'},{pointerType:'pen'}])test('unowned gesture ignored '+JSON.stringify(fields),()=>{let s=setup();s.fire('pointerdown',fields);s.shift(218);assert.equal(s.moves,0)});
for(const mutate of [s=>s.button.disabled=true,s=>s.button.stale=true,s=>s.button.isConnected=false,s=>s.marker.isConnected=false,s=>s.workspace.isConnected=false,s=>s.main.isConnected=false,s=>s.document.hidden=true,s=>s.marker.dataset.reportIdentity='b'.repeat(24),s=>s.marker.dataset.sourceId='d'.repeat(64),s=>s.owner.dataset.reportIdentity='b'.repeat(24),s=>s.workspace.dataset.epcMode='wide',s=>s.document.querySelectorAll=()=>[s.workspace,s.workspace]])test('identity/native state guard',()=>{let s=setup();s.fire('pointerdown');mutate(s);s.shift(218);assert.equal(s.moves,0);assert(!s.active())});
test('user scroll cancels compensation',()=>{let s=setup();s.fire('pointerdown');s.main.scrollTop=100;s.shift(218);assert.equal(s.moves,0)});
for(const fields of [{clientX:50},{pointerId:2}])test('drag or other pointer cancels',()=>{let s=setup();s.fire('pointerdown');s.fire('pointermove',fields);s.shift(218);assert.equal(s.moves,0)});
test('second gesture replaces observer, not duplicated',()=>{let s=setup();s.fire('pointerdown');s.fire('pointerdown');s.shift(218);assert.equal(s.moves,1);assert.equal(s.observers.filter(o=>o.live).length,1)});
test('unrelated target cancels without acquiring',()=>{let s=setup();s.fire('pointerdown');s.fire('pointerdown',{target:{closest:()=>null}});s.shift(218);assert.equal(s.moves,0)});
assert(!/dispatchEvent|\.click\(|preventDefault|stopPropagation|setPointerCapture|setTimeout/.test(source));
console.log(JSON.stringify({passed:count}));
