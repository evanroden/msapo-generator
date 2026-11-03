const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

function fixture() {
    let changed,disconnected=false,writes=0;
    const picture=(text,alt='0')=>({caption:text===null?null:{textContent:text},image:{alt,
        getAttribute:()=>alt,setAttribute:(name,value)=>{assert.equal(name,'alt');alt=value;writes++;},
        current:()=>alt},querySelector(selector){return selector.includes('stImageCaption')?this.caption:this.image;}});
    const first=picture('Synthetic pump inspection · Image-only'),second=picture('Original chart/contact page 2 · Image-only'),
        absent=picture(null,'Existing meaningful description'),unrelated=picture('Unrelated card','0');
    const root={isConnected:true,querySelectorAll(selector){assert.equal(selector,'[data-testid="stImageContainer"]');return [first,second,absent];}};
    const context={CSS:{escape:value=>value},document:{querySelector:selector=>{
        assert.equal(selector,'.st-key-monthly_import_picture_synthetic');return root;}},
        MutationObserver:class {constructor(fn){changed=fn;}observe(target,options){assert.equal(target,root);assert.deepEqual([...options.attributeFilter],['alt']);assert.ok(options.characterData&&options.subtree&&options.childList);}disconnect(){disconnected=true;}}};
    vm.runInNewContext(fs.readFileSync('app/monthly_report_picture_accessibility.js','utf8').replace('export default function','globalThis.install = function'),context);
    return {first,second,absent,unrelated,root,install:()=>context.install({data:{owner:'monthly_import_picture_synthetic'}}),
        changed:()=>changed(),writes:()=>writes,disconnected:()=>disconnected};
}

test('descriptions come from each rendered caption without changing unrelated images',()=>{
    const f=fixture();f.install();
    assert.equal(f.first.image.current(),f.first.caption.textContent);
    assert.equal(f.second.image.current(),f.second.caption.textContent);
    assert.equal(f.absent.image.current(),'Existing meaningful description');
    assert.equal(f.unrelated.image.current(),'0');
});
test('caption changes and native rerenders recover without an observer write loop',()=>{
    const f=fixture();f.install();assert.equal(f.writes(),2);f.changed();assert.equal(f.writes(),2);
    f.first.caption.textContent='Updated synthetic purpose';f.changed();assert.equal(f.first.image.current(),'Updated synthetic purpose');
    f.first.image.setAttribute('alt','0');f.changed();assert.equal(f.first.image.current(),'Updated synthetic purpose');
    const writes=f.writes();f.changed();assert.equal(f.writes(),writes);
});
test('empty captions and detached containers are not given borrowed descriptions; cleanup disconnects',()=>{
    const f=fixture(),cleanup=f.install();f.first.caption.textContent='';f.changed();
    assert.equal(f.first.image.current(),'0');
    f.root.isConnected=false;f.second.caption.textContent='Detached';f.changed();
    assert.equal(f.second.image.current(),'Original chart/contact page 2 · Image-only');
    cleanup();assert.equal(f.disconnected(),true);
});
