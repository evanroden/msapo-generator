"""Opt-in, hashed receipts for the existing localhost source-correction journey.

Observe only the two named controls, without changing events or reporting raw
widget IDs, option labels, source references or protobuf bodies. Never enabled
by production code or other browser journeys.
"""
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.qa_widget_delivery import WidgetDelivery, _hash

LABELS = {"multiselect": "Supporting source pages",
          "checkbox": "Remove unavailable source links"}
MAX_WIDGETS = 32
MAX_VALUES = 64
MAX_CACHE = 128
TAB_MARKER = b"if(n.key===`Tab`&&t.selectionManager.selectionMode===`multiple`){t.isOpen&&t.close(),n.continuePropagation();break}"
CLOSE_MARKER = b"o!==`multiple`&&(t||o===`multiple`||T!==n)"


def expected_combobox():
    """Verify installed immutable bytes once, before starting the QA journey."""
    import streamlit
    from scripts.patch_streamlit_frontend import selected_frontend
    receipt = selected_frontend(Path(streamlit.__file__).parent / "static")
    return {"path": "/static/js/" + receipt["combobox_bundle"],
            "sha256": receipt["combobox_sha256"],
            "tab_navigation": receipt.get("tab_navigation", False)}


def array_receipt(values):
    values = list(values)
    return {"count": len(values), "hashes": [_hash(v) for v in values[:MAX_VALUES]],
            "truncated": len(values) > MAX_VALUES}


class SourceSelectionDelivery(WidgetDelivery):
    def __init__(self, record, *, expected_asset=None):
        super().__init__(record, ports=(8520,))
        self.source_widgets = OrderedDict()
        self.source_cache = OrderedDict()
        self.expected_asset = expected_asset

    def attach(self, page):
        super().attach(page)
        if self.expected_asset is None:
            return
        observed = False

        def response(received):
            nonlocal observed
            url = urlparse(received.url)
            if (observed or url.scheme != "http" or url.hostname != "127.0.0.1"
                    or url.port != 8520 or url.path != self.expected_asset["path"]
                    or url.query or url.fragment):
                return
            observed = True
            # This reads the one response already requested by the native
            # page. Never request an asset, retain its body, or change input.
            result = {"path": url.path, "status": received.status,
                      "expected_sha256": self.expected_asset["sha256"],
                      "expected_tab_navigation": self.expected_asset["tab_navigation"]}
            try:
                raw = received.body()
                result.update(length=len(raw), sha256=sha256(raw).hexdigest(),
                              tab_navigation_count=min(2, raw.count(TAB_MARKER)),
                              close_guard_count=min(2, raw.count(CLOSE_MARKER)))
                result["matches"] = (received.status == 200
                    and result["sha256"] == result["expected_sha256"]
                    and result["close_guard_count"] == 1
                    and result["tab_navigation_count"] == int(result["expected_tab_navigation"]))
            except Exception as error:
                result.update(matches=False, error_type=type(error).__name__)
            self.record("source-selection-asset", result)

        page.on("response", response)

    def message(self, direction, raw, socket_id):
        super().message(direction, raw, socket_id)
        if not isinstance(raw, bytes):
            return
        msg = ForwardMsg() if direction == "received" else BackMsg()
        try:
            msg.ParseFromString(raw)
        except DecodeError:
            return
        kind = msg.WhichOneof("type")
        result = {"direction": direction, "kind": kind, "socket": socket_id}
        if direction == "received" and kind == "delta":
            element = msg.delta.new_element.WhichOneof("type")
            if element not in LABELS:
                return
            widget = getattr(msg.delta.new_element, element)
            if widget.label != LABELS[element]:
                return
            identity = {"id_hash": _hash(widget.id), "widget": widget.label,
                        "widget_type": element}
            self.source_widgets[widget.id] = identity
            self.source_widgets.move_to_end(widget.id)
            while len(self.source_widgets) > MAX_WIDGETS:
                self.source_widgets.popitem(last=False)
            result.update(identity, set_value=widget.set_value, disabled=widget.disabled,
                          fragment=msg.delta.fragment_id, path=list(msg.metadata.delta_path))
            if element == "multiselect":
                result.update(options=array_receipt(widget.options),
                              default_indices=list(widget.default)[:MAX_VALUES],
                              default_count=len(widget.default),
                              raw_values=array_receipt(widget.raw_values))
            else:
                result.update(default=widget.default, value=widget.value)
            if msg.hash:
                self.source_cache[msg.hash] = dict(result)
                self.source_cache.move_to_end(msg.hash)
                while len(self.source_cache) > MAX_CACHE:
                    self.source_cache.popitem(last=False)
        elif direction == "received" and kind == "ref_hash":
            previous = self.source_cache.get(msg.ref_hash)
            if previous is None:
                return
            result.update(referenced_widget=previous, path=list(msg.metadata.delta_path))
        elif direction == "sent" and kind == "rerun_script":
            run = msg.rerun_script
            states = {w.id: w for w in run.widget_states.widgets
                      if w.id in self.source_widgets}
            selected = []
            for key, identity in self.source_widgets.items():
                state = states.get(key)
                item = dict(identity, present=state is not None)
                if state is not None:
                    value_type = state.WhichOneof("value")
                    item["value_type"] = value_type
                    if value_type == "string_array_value":
                        item["selection"] = array_receipt(state.string_array_value.data)
                    elif value_type == "int_array_value":
                        values = state.int_array_value.data
                        item.update(indices=list(values)[:MAX_VALUES], count=len(values))
                    elif value_type == "bool_value":
                        item["checked"] = state.bool_value
                selected.append(item)
            result.update(fragment=run.fragment_id, automatic=run.is_auto_rerun,
                          widgets=selected)
        else:
            return
        self.record("source-selection-wire", result)


CLIENT = r"""(() => {
  if (location.hostname !== '127.0.0.1' || location.port !== '8520') return;
  const ids = new WeakMap(); let next = 0, count = 0;
  const id = node => {if (!node) return null;
    if (!ids.has(node)) ids.set(node, ++next); return ids.get(node);};
  for (const type of ['pointerdown','pointerup','click','keydown','keyup','change','blur'])
    document.addEventListener(type, event => {
      const target = event.target;
      if (!(target instanceof Element) || count >= 120) return;
      const multi = target.closest('[data-testid="stMultiSelect"]');
      const input = multi?.querySelector('input[aria-label="Supporting source pages"]');
      const label = target.closest('label');
      const checkbox = label?.querySelector('input[aria-label="Remove unavailable source links"]');
      const list = target.closest('[role="listbox"][aria-label="Supporting source pages"]');
      if (!input && !checkbox && !list) return;
      count++;
      console.debug('ENFRA_QA_DIAGNOSTIC '+JSON.stringify({kind:'source-selection-native',
        at:performance.now(),document:performance.timeOrigin,detail:{type,
          key:['Tab','Enter','Escape',' '].includes(event.key)?event.key:'',trusted:event.isTrusted,
          control:input?'sources':checkbox?'remove-missing':'source-options',
          node:id(input||checkbox||list),targetNode:id(target),tag:target.tagName,
          role:target.getAttribute('role'),connected:target.isConnected,
          selectedTags:multi?.querySelectorAll('[data-tag]').length??null,
          checked:checkbox?.checked??null,
          running:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')}}));
    },{capture:true,passive:true});
})();"""
