const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.complete=false;this.naturalWidth=0;this.checked=false;this.disabled=false;}
 append(...xs){this.children.push(...xs);} replaceChildren(){this.children=[];} setAttribute(k,v){this[k]=v;}
 querySelector(){return this.root;}
 decode(){return new Promise((resolve,reject)=>{this.resolveDecode=resolve;this.rejectDecode=reject;});}
}
function setup(count=6){
 const root=new Element('section'), parent={querySelector:()=>root};
 const document={createElement:tag=>new Element(tag),createTextNode:value=>value};
 const source=fs.readFileSync('app/monthly_report_picture_group.js','utf8').replace('export default ','');
 const render=vm.runInNewContext('('+source+')',{document});
 const data={identity:'exact',nonce:'first',pictures:Array.from({length:count},(_,i)=>({title:'Picture '+i,context:'Synthetic',image:'bytes',mime:'image/png'}))};
 const events=[];const component={parentElement:parent,data,setStateValue:(k,v)=>events.push(v)};
 const cleanup=render(component);const figures=root.children.slice(0,count);
 return {root,render,component,cleanup,events,images:figures.map(f=>f.children[2]),choices:figures.map(f=>f.children[5].children[0]),retries:figures.map(f=>f.children[4]),button:root.children.at(-1)};
}
async function loaded(img){img.complete=true;img.naturalWidth=20;const pending=img.onload();img.resolveDecode();await pending;}
test('all URL loads must finish decode before one explicit full boolean submission',async()=>{
 const c=setup();assert.equal(c.button.disabled,true);
 for(const image of c.images.slice(0,5))await loaded(image);
 assert.equal(c.button.disabled,true);c.button.onclick();assert.equal(c.events.length,0);
 const image=c.images[5];image.complete=true;image.naturalWidth=20;const pending=image.onload();
 assert.equal(c.button.disabled,true);image.resolveDecode();await pending;assert.equal(c.button.disabled,false);
 c.choices[2].checked=true;c.button.onclick();c.button.onclick();assert.equal(c.events.length,1);
 assert.deepEqual(Array.from(c.events[0].left),[false,false,true,false,false,false]);
 assert.equal(c.events[0].nonce,'first');assert.equal(c.button.disabled,true);
});
test('failed decode disables confirmation until explicit retry succeeds',async()=>{
 const c=setup(1),image=c.images[0];image.complete=true;image.naturalWidth=20;
 const pending=image.onload();image.rejectDecode(Error('broken'));await pending;
 assert.equal(c.button.disabled,true);assert.equal(c.retries[0].hidden,false);
 c.retries[0].onclick();await loaded(image);assert.equal(c.button.disabled,false);
 image.onerror();assert.equal(c.button.disabled,true);c.button.onclick();assert.equal(c.events.length,0);
});
test('old cleanup, decode and click cannot submit after rerender/reopen',async()=>{
 const c=setup(1),image=c.images[0];image.complete=true;image.naturalWidth=20;
 const pending=image.onload();const late=c.button.onclick;
 c.render({...c.component,data:{...c.component.data,nonce:'second'}});
 image.resolveDecode();await pending;late();assert.equal(c.events.length,0);
 assert.equal(c.root.children.at(-1).disabled,true);
 c.cleanup();assert.equal(c.root.children.at(-1).disabled,true);
});
