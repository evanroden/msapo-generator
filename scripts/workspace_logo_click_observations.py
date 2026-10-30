"""Bounded read-only telemetry for the isolated About-logo native output click."""
from contextlib import contextmanager
import json

INSTALL = r'''() => {
  if (location.origin !== 'http://127.0.0.1:8546' ||
      !document.querySelector('[data-enfra-logo-refresh]'))
    throw Error('Click geometry requires the isolated logo fixture');
  if (window.__enfraLogoClickGeometry) throw Error('Click geometry already installed');
  const main=document.querySelector('[data-testid="stMain"]');
  const root=document.querySelector('.st-key-epc_workspace_monthly');
  const button=[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Render synthetic native logo outputs');
  if (!main || !root || !button) throw Error('Missing native logo geometry target');
  const limit=96, byteLimit=524288;
  const record={version:1,syntheticOnly:true,limit,byteLimit,events:[],dropped:0,bytes:0};
  const rect=n=>n ? n.getBoundingClientRect().toJSON() : null;
  const identity=n=>n?.nodeType===1 ? {tag:n.tagName,connected:n.isConnected,testid:n.getAttribute('data-testid'),
    key:([...n.classList].find(c=>c.startsWith('st-key-'))||'').slice(0,200)||null} : null;
  const box=n=>n ? {node:identity(n),rect:rect(n),scrollTop:n.scrollTop,
    scrollHeight:n.scrollHeight,clientHeight:n.clientHeight} : null;
  const last=root.querySelector('.st-key-epc_pair_monthly_rfi');
  const reference=last?.querySelector('.epc-workspace-reference');
  const slot=reference?.querySelector('[class*="st-key-epc_preview_slot_"]');
  function surface() {
    const pending=reference?[reference]:[];let visited=0;
    while(pending.length && visited++<256) {
      const node=pending.pop(), found=node.querySelector('.report-preview');
      if(found)return found;
      for(const child of node.querySelectorAll('*'))if(child.shadowRoot)pending.push(child.shadowRoot);
    }
    return null;
  }
  function snapshot(kind,event) {
    const controls=[...root.querySelectorAll('[data-testid="stSkeleton"], [data-testid="stFullScreenFrame"], [data-testid="stFileUploader"]')];
    return {kind,at:performance.now(),event:event?{type:event.type,trusted:event.isTrusted,
      target:identity(event.target),x:event.clientX??null,y:event.clientY??null}:null,
      active:identity(document.activeElement),running:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
      viewport:{width:innerWidth,height:innerHeight},main:box(main),root:box(root),button:box(button),
      block:box(main.querySelector('[data-testid="stMainBlockContainer"]')),
      last:box(last),reference:box(reference),slot:box(slot),surface:box(surface()),
      mode:root.dataset.epcMode,review:root.dataset.epcReviewOpen,
      previewHeight:reference?getComputedStyle(reference).getPropertyValue('--epc-preview-height'):null,
      skeletonCount:controls.filter(n=>n.getAttribute('data-testid')==='stSkeleton').length,
      controlCount:controls.length,controls:controls.slice(0,40).map(n=>({node:identity(n),
        owner:identity(n.closest('[data-testid="stElementContainer"]')),rect:rect(n)}))};
  }
  function sample(kind,event) {
    if (record.events.length>=limit || record.bytes>=byteLimit) {record.dropped++;return;}
    const value=snapshot(kind,event), size=new TextEncoder().encode(JSON.stringify(value)).byteLength;
    if (record.bytes+size>byteLimit) {record.dropped++;return;}
    record.bytes+=size;record.events.push(value);
  }
  const types=['pointerdown','pointerup','click','wheel','keydown','scroll'];
  const listener=event=>sample('native-event',event);
  for(const type of types)document.addEventListener(type,listener,{capture:true,passive:true});
  const resize=new ResizeObserver(()=>sample('resize'));
  for(const node of [main,root,button,last,reference,slot,main.querySelector('[data-testid="stMainBlockContainer"]')])
    if(node)resize.observe(node);
  const mutation=new MutationObserver(()=>sample('mutation'));
  mutation.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style','data-test-script-state']});
  window.__enfraLogoClickGeometry={finish(){
    for(const type of types)document.removeEventListener(type,listener,{capture:true});
    resize.disconnect();mutation.disconnect();
    try {record.final=snapshot('final');return record;}
    finally {delete window.__enfraLogoClickGeometry;}
  }};
  sample('installed');
}'''

FINISH = '() => window.__enfraLogoClickGeometry?.finish() || {error:"observer missing"}'


@contextmanager
def native_click_geometry(page, directory):
    """No waits or browser actions; save evidence even if the native action fails."""
    page.evaluate(INSTALL)
    native_failed = False
    try:
        yield
    except BaseException:
        native_failed = True
        raise
    finally:
        try:
            collection_error = None
            try:
                evidence = page.evaluate(FINISH)
            except Exception as exc:
                collection_error = exc
                evidence = {'diagnostic_error': type(exc).__name__}
            # Secondary UTF-8 artifact cap includes the final geometry sample.
            encoded = json.dumps(evidence, separators=(',', ':'))
            if len(encoded.encode('utf-8')) > 600_000:
                collection_error = ValueError('geometry exceeded serialized limit')
                encoded = json.dumps({'diagnostic_error': 'geometry exceeded serialized limit'})
            (directory / 'native-click-geometry.json').write_text(encoded)
            if collection_error is not None and not native_failed:
                raise RuntimeError('Native click geometry unavailable') from collection_error
        except Exception:
            # Evidence I/O/serialization must never replace the original native
            # first-action failure. If that action succeeded, evidence failure
            # is itself explicit rather than silently reporting a clean run.
            if not native_failed:
                raise


# This is the disposable native-output oracle, not the production Generate
# action or About's first-click replacement action. Server notRunning alone
# does not mean the lazy native controls above this appended helper have mounted.
OUTPUT_READY = r'''wanted => {
  if (location.origin !== 'http://127.0.0.1:8546') return false;
  const nodes=document.querySelectorAll('[data-enfra-logo-refresh]');
  if (!nodes.length) return false;
  let state;
  try {state=JSON.parse(nodes[nodes.length-1].dataset.enfraLogoRefresh);} catch {return false;}
  if (state.scope!==wanted.scope || state.generation!==wanted.generation ||
      state.sequence!==wanted.sequence || !state.original_unchanged ||
      document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')!=='notRunning') return false;
  const main=document.querySelector('[data-testid="stMain"]');
  const inFlow=node=>node.isConnected && [...node.getClientRects()].some(r=>r.width>0 && r.height>0) &&
    getComputedStyle(node).visibility!=='hidden';
  const button=[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Render synthetic native logo outputs');
  if (!main || !button || !main.contains(button) || button.disabled || !inFlow(button)) return false;
  // Include offscreen main-flow controls: native click will scroll past them.
  // Ignore sidebar and collapsed/non-layout placeholders, neither moves helper.
  return ![...main.querySelectorAll('[data-testid="stSkeleton"]')].some(inFlow);
}'''


def click_ready_native_output(page, prior):
    """One native helper click; readiness shares its existing 30-second budget."""
    import time
    deadline = time.monotonic() + 30
    page.wait_for_function(OUTPUT_READY, arg={key: prior[key] for key in ('scope', 'generation', 'sequence')}, timeout=30000)
    remaining = (deadline - time.monotonic()) * 1000
    if remaining <= 0:
        raise TimeoutError('Synthetic native output readiness exhausted click deadline')
    page.get_by_role('button', name='Render synthetic native logo outputs', exact=True).click(timeout=remaining)
