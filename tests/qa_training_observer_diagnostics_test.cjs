const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../scripts/qa_training_observer_diagnostics.js'), 'utf8');

function install(Native, location = {protocol:'http:', hostname:'127.0.0.1', port:'8535'}) {
    let clock = 0;
    const listeners = new Map();
    const context = {location, performance:{timeOrigin:123, now:()=>++clock},
        addEventListener(type, callback, options) {listeners.set(type, {callback, options});},
        requestAnimationFrame() {throw Error('Diagnostics must not schedule a frame');},
        getComputedStyle() {throw Error('Diagnostics must not request layout');}};
    context.window = context;
    Object.defineProperty(context, 'ResizeObserver', {value:Native, configurable:true, writable:true, enumerable:false});
    const descriptor = Object.getOwnPropertyDescriptor(context, 'ResizeObserver');
    vm.runInNewContext(source, context);
    return {context, listeners, descriptor};
}

// Node has no native ResizeObserver. Its real Map constructor verifies
// the native-function feature branch and native constructor/prototype shape.
{
    const {context, descriptor} = install(Map), Wrapped = context.ResizeObserver;
    assert.notEqual(Wrapped, Map);
    assert.equal(Wrapped.name, Map.name);
    assert.equal(Wrapped.length, Map.length);
    assert.equal(Wrapped.prototype, Map.prototype);
    assert.equal(Wrapped.prototype.set, Map.prototype.set);
    assert.equal(Wrapped.toString().includes('[native code]'), true);
    assert.equal(Function.prototype.toString.call(Wrapped).includes('[native code]'), true);
    assert.deepEqual(Object.getOwnPropertyDescriptor(context, 'ResizeObserver'), {...descriptor, value:Wrapped});
    assert.equal(new Wrapped() instanceof Map, true);
    class Child extends Wrapped {}
    assert.equal(Object.getPrototypeOf(new Child()), Child.prototype);
}

// A native-contract adapter supplies delivery, which Node's Map does
// not have. A proxy retains the native-toString branch without a fake string.
class DeliveryObserver {
    constructor(callback) {if (typeof callback !== 'function') throw TypeError('callback'); this.callback=callback; this.calls=[];}
    observe(...args) {this.calls.push(['observe', ...args]);}
    unobserve(...args) {this.calls.push(['unobserve', ...args]);}
    disconnect() {this.calls.push(['disconnect']);}
    deliver(entries, receiver=this) {return Reflect.apply(this.callback, receiver, [entries, this]);}
}
const Native = new Proxy(DeliveryObserver, {});
{
    const {context,listeners}=install(DeliveryObserver);
    assert.equal(context.ResizeObserver,DeliveryObserver);
    assert.equal(context.__enfraTrainingObserverEvidence.installation,'native-feature-branch-would-change');
    assert.equal(listeners.size,0);
}
{
    const {context, listeners} = install(Native), Wrapped=context.ResizeObserver;
    const entries=[{target:{tagName:'DIV', getAttribute:()=> 'stDataFrame',
        getBoundingClientRect(){throw Error('No layout read');}}, contentRect:{width:12, height:34}}];
    const receiver={}, result={}, order=[];
    const observer=new Wrapped(function(actual, owner) {
        order.push('callback'); assert.equal(this, receiver);
        assert.equal(actual, entries); assert.equal(owner, observer); return result;
    });
    order.push('before'); assert.equal(observer.deliver(entries, receiver), result); order.push('after');
    assert.deepEqual(order, ['before','callback','after']);
    const target={}, options={box:'content-box'};
    observer.observe(target, options); observer.unobserve(target); observer.disconnect();
    assert.deepEqual(observer.calls, [['observe',target,options], ['unobserve',target], ['disconnect']]);
    for (const method of ['observe','unobserve','disconnect']) assert.equal(Wrapped.prototype[method], Native.prototype[method]);
    const exception=Error('original callback exception'), throwing=new Wrapped(()=>{throw exception;});
    assert.throws(()=>throwing.deliver(entries), error=>error===exception);
    for (const expectedReceiver of [undefined, null, 0]) {
        const strict=new Wrapped(function(actual, owner) {'use strict';
            assert.equal(this, expectedReceiver); assert.equal(actual, entries); assert.equal(owner, strict);
        });
        Reflect.apply(strict.callback, expectedReceiver, [entries, strict]);
    }
    assert.throws(()=>new Wrapped(), TypeError);
    assert.throws(()=>Wrapped(()=>{}), TypeError);
    const evidence=context.__enfraTrainingObserverEvidence;
    assert.equal(evidence.callbacks.length, 5);
    assert.deepEqual(JSON.parse(JSON.stringify(evidence.callbacks[0].entries)), [{tag:'DIV',testid:'stDataFrame',width:12,height:34}]);
    assert.equal(listeners.get('error').options.passive, true);
    let prevented=false;
    context.__enfraTrainingDateEvents=[{type:'input', value:'2026/09/', at:8}];
    listeners.get('error').callback({message:'ResizeObserver loop completed with undelivered notifications.', preventDefault(){prevented=true;}});
    listeners.get('error').callback({message:'Unrelated original error'});
    assert.equal(prevented, false); assert.equal(evidence.errors.length, 2);
    assert.equal(evidence.errors[1].message, 'Unrelated original error');
    assert.equal(evidence.errors[0].nativeEvents[0].value, '2026/09/');
}
{
    const {context, listeners}=install(Native), evidence=context.__enfraTrainingObserverEvidence;
    for (let n=0;n<80;n++) {
        const callback=()=>{}; Object.defineProperty(callback, 'name', {value:'callback'+n});
        new context.ResizeObserver(callback);
    }
    let reads=0;
    const entries=Array.from({length:30}, ()=>({target:{tagName:'DIV',getAttribute(){reads++;return 'stDataFrame';}}, contentRect:{width:1,height:2}}));
    const observer=new context.ResizeObserver(()=>{});
    for(let n=0;n<120;n++) observer.deliver(entries);
    for(let n=0;n<12;n++) listeners.get('error').callback({message:'error'});
    assert.equal(evidence.origins.length, 64); assert(evidence.droppedOrigins>0);
    assert.equal(evidence.callbacks.length, 96); assert.equal(evidence.droppedCallbacks,24);
    assert.equal(evidence.errors.length,8); assert.equal(evidence.droppedErrors,4);
    assert.equal(reads,360); assert.equal(evidence.callbacks[0].entryCount,30);
}
for (const location of [{protocol:'https:',hostname:'msapo-generator.onrender.com',port:''},
    {protocol:'http:',hostname:'127.0.0.1',port:'8501'}, {protocol:'http:',hostname:'localhost',port:'8535'}]) {
    const {context,listeners}=install(Native,location);
    assert.equal(context.ResizeObserver,Native); assert.equal(context.__enfraTrainingObserverEvidence,undefined);
    assert.equal(listeners.size,0);
}
console.log('Training observer diagnostics: native shape, same-turn delivery, unchanged errors, bounds and isolation passed.');
