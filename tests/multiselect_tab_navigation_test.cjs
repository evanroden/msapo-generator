// The actual locked keydown and commit bodies, with inert UI collaborators.
// This does not synthesize a browser event or model a full React lifecycle.
const assert = require('node:assert/strict');
const native = JSON.parse(process.argv[2]);
function exercise(source, {mode='multiple', key='Tab', open=true,
  focused='workorders', selected=false, composing=false, shift=false,
  custom=false, input='', action=false, link=false}={}) {
  const calls=[], state={values:['activity'], prevented:0, propagated:0};
  const manager={selectionMode:mode, focusedKey:focused, isEmpty:false,
    isSelected:()=>selected, select(value){calls.push(['select',value]);state.values.push(value)},
    setFocusedKey(value){calls.push(['focus',value])}};
  const t={isOpen:open, selectionManager:manager, inputValue:input,
    collection:{getItem:()=>({props:action?{onAction:()=>calls.push(['action'])}:link?{href:'/synthetic'}:{}})},
    close(){calls.push(['close']);t.isOpen=false}, revert(){calls.push(['revert'])},
    open(...args){calls.push(['open',...args])}};
  t.commit=new Function('F','x','o','ie','K','return '+source.commit)(t,manager,mode,
    forced=>calls.push(['commit',forced]),()=>t.close());
  class HTMLAnchorElement {}
  const handler=new Function('t','a','w','e','HTMLAnchorElement','CSS','return '+source.keyboard)(
    t,{current:{querySelector:()=>new HTMLAnchorElement}},
    {open:()=>calls.push(['link'])},{allowsCustomValue:custom},HTMLAnchorElement,{escape:x=>x});
  handler({key,shiftKey:shift,nativeEvent:{isComposing:composing},
    preventDefault(){state.prevented++},continuePropagation(){state.propagated++}});
  return {...state,calls,open:t.isOpen};
}
// Retain an executable negative control: choosing Activity then Tab commits
// the next focused Workorders option on the original shipped handler.
assert.deepEqual(exercise(native.before).values,['activity','workorders']);
assert.deepEqual(exercise(native.after).values,['activity'],
  'Tab must navigate, not add an unchosen highlighted evidence source');
for (const mode of ['single','multiple']) for (const key of ['Tab','Enter','Escape','ArrowDown','ArrowUp','ArrowLeft','ArrowRight'])
for (const open of [false,true]) for (const focused of [null,'workorders'])
for (const selected of [false,true]) for (const composing of [false,true])
for (const shift of [false,true]) for (const custom of [false,true]) for (const input of ['', 'filter']) {
  const options={mode,key,open,focused,selected,composing,shift,custom,input};
  const before=exercise(native.before,options),after=exercise(native.after,options);
  if(mode!=='multiple'||key!=='Tab'||composing) assert.deepEqual(after,before);
  else {
    assert.deepEqual(after.values,['activity']);
    assert.equal(after.prevented,0,'default Tab/Shift+Tab focus navigation stays native');
    assert.equal(after.propagated,1);
    assert.deepEqual(after.calls,open?[['close']]:[]);
    assert.equal(after.open,false);
  }
}
// Action/link items retain Enter and single-selection semantics; navigating
// out of a multiple selector never invokes an unrequested item action either.
for(const action of [false,true])for(const link of [false,true])for(const mode of ['single','multiple'])
for(const key of ['Tab','Enter']) {
 const before=exercise(native.before,{mode,key,action,link}),after=exercise(native.after,{mode,key,action,link});
 if(mode==='multiple'&&key==='Tab')assert.deepEqual(after.calls,[['close']]);
 else assert.deepEqual(after,before);
}
console.log('native Tab navigation and unchanged keyboard controls passed');
