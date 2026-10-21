"""Passive diagnostics around the two existing, synthetic-only browser journeys.

Run an unchanged QA script once. Keep its actions, assertions, route restrictions
and exceptions; record native events, image decode callers and Playwright traces.
This wrapper never visits Render, uploads client material or changes browser policy.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import wraps
import json
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"qa_monthly_adaptive.py": "monthly-adaptive",
           "qa_shared_fixture_testing.py": "shared-fixture-testing"}

# Observe without preventing events, committing input, replacing nodes, changing
# image sources or handling a rejected decode promise. Returning the SAME promise
# preserves the browser's original unhandled-rejection/pageerror behavior.
CLIENT = r"""(() => {
  if (location.hostname !== '127.0.0.1' || !['8520','8521'].includes(location.port)) return;
  let count=0, nextId=0;
  const ids=new WeakMap();
  const identity=n=>{if(!n || typeof n!=='object')return null;
    if(!ids.has(n))ids.set(n,++nextId);return ids.get(n)};
  const source=s=>s?.startsWith('data:') ? s.slice(0,60)+' [length '+s.length+']' : (s||'').slice(0,500);
  const describe=n=>{
    if(!n || !n.tagName)return null;
    const item={id:identity(n),tag:n.tagName,name:n.getAttribute('aria-label')||'',
      connected:n.isConnected,focused:document.activeElement===n};
    if(n.matches('input,textarea')) Object.assign(item,{value:n.value.slice(0,16384),
      length:n.value.length,start:n.selectionStart,end:n.selectionEnd});
    if(n.tagName==='IMG')Object.assign(item,{src:source(n.currentSrc||n.src),
      complete:n.complete,width:n.naturalWidth,height:n.naturalHeight});
    return item;
  };
  const emit=(kind,detail)=>{if(count++<1500)console.debug('ENFRA_QA_DIAGNOSTIC '+JSON.stringify({
    kind,at:performance.now(),document:performance.timeOrigin,detail}));};
  const imageList=()=>{
    const images=[];
    const scan=root=>{for(const n of root.querySelectorAll('*')){
      if(n.tagName==='IMG' && images.length<30)images.push(describe(n));
      if(n.shadowRoot && images.length<30)scan(n.shadowRoot);
    }};scan(document);return images;
  };
  for(const type of ['beforeinput','input','change','keydown','keyup','focus','blur','focusin','focusout']){
    document.addEventListener(type,event=>{
      if(!event.target?.matches?.('input,textarea'))return;
      emit('native-event',{type,key:event.key||'',trusted:event.isTrusted,
        target:describe(event.target),related:describe(event.relatedTarget),
        active:describe(document.activeElement),running:document.querySelector('[data-testid="stApp"]')
          ?.getAttribute('data-test-script-state')});
    },{capture:true,passive:true});
  }
  for(const type of ['load','error'])document.addEventListener(type,event=>{
    if(event.target?.tagName==='IMG')emit('image-'+type,describe(event.target));
  },{capture:true,passive:true});
  const decode=HTMLImageElement.prototype.decode;
  if(decode)HTMLImageElement.prototype.decode=function(...args){
    emit('image-decode-call',{image:describe(this),stack:new Error().stack?.slice(0,2000)});
    return Reflect.apply(decode,this,args);
  };
  addEventListener('unhandledrejection',event=>emit('unhandled-rejection',{
    name:event.reason?.name,message:event.reason?.message||String(event.reason),
    stack:event.reason?.stack,images:imageList()}),{passive:true});
  for(const type of ['pagehide','beforeunload'])addEventListener(type,()=>emit(type,{
    active:describe(document.activeElement),images:imageList()}),{passive:true});
})();"""


def target_path(name: str) -> Path:
    """Restrict diagnostics to the existing localhost synthetic test entrypoints."""
    if name not in TARGETS:
        raise ValueError("Choose qa_monthly_adaptive.py or qa_shared_fixture_testing.py.")
    return ROOT / "scripts" / name


@contextmanager
def observe(output: Path, browser_class, context_class, *, widget_ports=(8520, 8521, 8528),
            source_selection=False):
    output.mkdir(parents=True, exist_ok=True)
    states = {}
    sequence = 0
    original_new = browser_class.new_context
    original_close = context_class.close
    source_asset, source_asset_error = None, None
    if source_selection:
        from scripts.qa_source_selection_delivery import expected_combobox
        try:
            source_asset = expected_combobox()
        except Exception as error:
            # Keep the original journey even if diagnostic setup is unavailable.
            source_asset_error = type(error).__name__

    @wraps(original_new)
    def new_context(browser, *args, **kwargs):
        nonlocal sequence
        context = original_new(browser, *args, **kwargs)
        sequence += 1
        engine = browser.browser_type.name
        label = f"{engine}-{sequence}"
        log = (output / (label + '-events.jsonl')).open('w', encoding='utf-8')
        states[context] = {'log': log, 'label': label, 'count': 0, 'tracing': False}
        state = states[context]

        def record(kind, detail):
            if log.closed or state['count'] >= 6000:
                return
            state['count'] += 1
            log.write(json.dumps({'kind': kind, 'time': time.time(), 'detail': detail},
                                 ensure_ascii=False) + '\n')
            log.flush()

        state['record'] = record

        def on_page(page):
            from scripts.qa_widget_delivery import WidgetDelivery
            if source_selection:
                from scripts.qa_source_selection_delivery import SourceSelectionDelivery
                SourceSelectionDelivery(record, expected_asset=source_asset).attach(page)
            else:
                WidgetDelivery(record, ports=widget_ports).attach(page)
            page.on('console', lambda msg: record('client', msg.text)
                    if msg.text.startswith('ENFRA_QA_DIAGNOSTIC ') else None)
            page.on('pageerror', lambda error: record('pageerror', {
                'message': str(error), 'stack': getattr(error, 'stack', '')}))
            page.on('requestfailed', lambda req: record('requestfailed', {
                'url': req.url[:500], 'type': req.resource_type, 'failure': req.failure}))
            page.on('response', lambda response: record('image-response', {
                'url': response.url[:500], 'status': response.status})
                if response.request.resource_type == 'image' else None)
        context.add_init_script(CLIENT)
        if source_selection:
            from scripts.qa_source_selection_delivery import CLIENT as SOURCE_SELECTION_CLIENT
            context.add_init_script(SOURCE_SELECTION_CLIENT)
        context.on('page', on_page)
        try:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        except Exception as exc:
            record('diagnostic-error', {'stage': 'start',
                   'error': type(exc).__name__ + ': ' + str(exc)})
        else:
            state['tracing'] = True
        record('started', {'engine': engine})
        if source_asset_error:
            record('diagnostic-error', {'stage': 'expected-source-asset', 'error_type': source_asset_error})
        return context

    @wraps(original_close)
    def close_context(context, *args, **kwargs):
        state = states.pop(context, None)
        try:
            if state and state['tracing']:
                try:
                    context.tracing.stop(path=str(output / (state['label'] + '-trace.zip')))
                except Exception as exc:
                    state['record']('diagnostic-error', {'stage': 'stop',
                        'error': type(exc).__name__ + ': ' + str(exc)})
        finally:
            if state:
                state['log'].close()
            original_close(context, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(browser_class, 'new_context', new_context))
        stack.enter_context(patch.object(context_class, 'close', close_context))
        try:
            yield
        finally:
            # An interrupted script may leave a context open. Preserve whatever
            # diagnostics are available; never retry its failed workflow action.
            for context, state in list(states.items()):
                try:
                    close_context(context)
                except Exception as exc:
                    (output / (state['label'] + '-diagnostic-error.txt')).write_text(
                        type(exc).__name__ + ': ' + str(exc), encoding='utf-8')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/qa_browser_diagnostics.py <synthetic-script-name>')
    name = sys.argv[1]
    script = target_path(name)
    from playwright.sync_api import Browser, BrowserContext
    # Do not leak the wrapper argument into the unchanged test's CLI.
    argv = sys.argv[:]
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        sys.argv = [str(script)]
        with observe(ROOT / 'test-artifacts' / TARGETS[name] / 'diagnostics', Browser, BrowserContext):
            runpy.run_path(str(script), run_name='__main__')
    finally:
        sys.argv = argv


if __name__ == '__main__':
    main()
