"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs");
function load(path) {
 const text = fs.readFileSync(path,"utf8"), start=text.indexOf("function rn(e,t,n,r){");
 return text.slice(start,text.indexOf("var an=",start));
}
function setup(source, options={}) {
 const frames=new Map(), callbacks=[], observations=[], listeners=new Map(), writes=[];
 let serial=0, shift, geometry=0;
 const ancestor={addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:(type,fn)=>{if(listeners.has(type))assert.equal(listeners.get(type),fn);listeners.delete(type)}};
 const trigger={}, popup={};
 class Observer {
  constructor(fn){this.callback=fn;callbacks.push(fn)}
  observe(target){observations.push(["observe",target])}
  unobserve(target){observations.push(["unobserve",target])}
  disconnect(){observations.push(["disconnect"])}
 }
 const rn=new Function("Mt","O","nn","X","tn","ResizeObserver","requestAnimationFrame","cancelAnimationFrame",source+";return rn;")(
  value=>value,()=>[ancestor],(_e,fn)=>{shift=fn;return()=>{shift=null}},()=>({width:geometry}),
  (a,b)=>a.width===b.width,Observer,fn=>{const id=++serial;frames.set(id,fn);return id},id=>frames.delete(id));
 const update=()=>{writes.push(geometry);if(options.throwUpdate)throw Error("original update failure")};
 const cleanup=rn(trigger,popup,update,{layoutShift:true,...options});
 return {frames,callbacks,observations,listeners,writes,cleanup,trigger,popup,get shift(){return shift},
  resize:()=>callbacks[0]([{target:trigger}]),tick(){const next=[...frames];frames.clear();for(const [,fn] of next)fn()},
  setGeometry(value){geometry=value}};
}
const before=load(process.argv[2]), after=load(process.argv[3]);
const old=setup(before);assert.equal(old.writes.length,1);old.resize();assert.equal(old.writes.length,2);old.cleanup();
const fixed=setup(after);assert.equal(fixed.writes.length,1,"native initial update");
fixed.resize();fixed.resize();fixed.setGeometry(17);
assert.equal(fixed.writes.length,1,"no synchronous RO update");assert.equal(fixed.frames.size,2,"one update and one native reobserve frame");
fixed.tick();assert.deepEqual(fixed.writes,[0,17]);assert.equal(fixed.frames.size,0);
fixed.listeners.get("scroll")();fixed.listeners.get("resize")();fixed.shift();
assert.deepEqual(fixed.writes,[0,17,17,17,17],"native scroll/window/layout callbacks stay immediate");
fixed.resize();const stale=[...fixed.frames.values()], callback=fixed.callbacks[0];fixed.cleanup();
assert.equal(fixed.frames.size,0);assert.equal(fixed.listeners.size,0);assert.equal(fixed.shift,null);
for(const fn of stale)fn();callback([{target:fixed.trigger}]);
assert.equal(fixed.frames.size,0);assert.equal(fixed.writes.length,5,"unmounted queued callbacks are inert");
assert.equal(fixed.observations.at(-1)[0],"disconnect");
const disabled=setup(after,{elementResize:false});assert.equal(disabled.callbacks.length,0);assert.equal(disabled.writes.length,1);disabled.cleanup();
const animation=setup(after,{animationFrame:true});animation.setGeometry(7);animation.tick();
assert.deepEqual(animation.writes,[0,7],"native animation-frame geometry path remains active");animation.cleanup();assert.equal(animation.frames.size,0);
assert.throws(()=>setup(after,{throwUpdate:true}),/original update failure/,"native exceptions propagate");
console.log("original synchronous resize reproduced; coalescing, current geometry, native paths and lifetime cancellation passed");
