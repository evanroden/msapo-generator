"""Read-only metadata for the unchanged localhost Prepared-by reload journey.

No protobuf bodies, widget values, URLs, cookies or report text are retained.
Nothing in this module is imported by production or changes message dispatch.
"""
from collections import Counter, deque
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg


class ReloadObservations:
    def __init__(self):
        self.events = deque(maxlen=2000)
        self.counts = Counter()
        self.sockets = 0

    def message(self, direction, payload, socket):
        if not isinstance(payload, bytes):
            self.counts[direction + ':nonbinary'] += 1
            return
        msg = ForwardMsg() if direction == 'received' else BackMsg()
        try:
            msg.ParseFromString(payload)
        except DecodeError:
            self.counts[direction + ':decode_error'] += 1
            return
        kind = msg.WhichOneof('type') or 'unset'
        self.counts[direction + ':' + kind] += 1
        item = dict(direction=direction, kind=kind, socket=socket, bytes=len(payload))
        if direction == 'received' and kind == 'delta':
            item.update(delta=msg.delta.WhichOneof('type'),
                        element=msg.delta.new_element.WhichOneof('type'),
                        path=list(msg.metadata.delta_path), cacheable=msg.metadata.cacheable,
                        fragment=bool(msg.delta.fragment_id))
        elif direction == 'received' and kind == 'script_finished':
            item['finish'] = msg.script_finished
        elif direction == 'received' and kind == 'new_session':
            item['fragments'] = len(msg.new_session.fragment_ids_this_run)
        elif direction == 'sent' and kind == 'rerun_script':
            item.update(fragment=bool(msg.rerun_script.fragment_id), automatic=msg.rerun_script.is_auto_rerun,
                        widgets=len(msg.rerun_script.widget_states.widgets),
                        cached=len(msg.rerun_script.cached_message_hashes))
        self.events.append(item)

    def attach(self, page):
        def connected(socket):
            parsed = urlparse(socket.url)
            if parsed.hostname != '127.0.0.1' or parsed.port != 8528:
                raise ValueError('Reload observations require the isolated preparer fixture')
            self.sockets += 1
            identity = self.sockets
            socket.on('framereceived', lambda raw: self.message('received', raw, identity))
            socket.on('framesent', lambda raw: self.message('sent', raw, identity))
        page.on('websocket', connected)
        page.add_init_script(CLIENT_INIT)

    def snapshot(self):
        return dict(sockets=self.sockets, counts=dict(self.counts), events=list(self.events))


CLIENT_INIT = """(() => {
 const states=[]; let previous='';
 window.__preparerReloadStates=states;
 const sample=()=>{
  const state={ready:document.readyState,
   app:!!document.querySelector('[data-testid="stApp"]'),
   script:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')||null,
   workspace:!!document.querySelector('.epc-workspace'),
   inputs:document.querySelectorAll('input,textarea').length,
   alerts:document.querySelectorAll('[data-testid="stAlert"]').length,
   headings:document.querySelectorAll('h1').length};
  const key=JSON.stringify(state); if(key===previous)return; previous=key;
  states.push({...state,at:Math.round(performance.now())});if(states.length>100)states.shift();
 };
 new MutationObserver(sample).observe(document,{subtree:true,childList:true,attributes:true,
  attributeFilter:['data-test-script-state','data-epc-full-render']});
 addEventListener('DOMContentLoaded',sample);addEventListener('load',sample);sample();
})();"""
