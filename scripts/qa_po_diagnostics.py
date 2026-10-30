"""Bounded, passive evidence for the localhost synthetic PO browser gate.

No workflow actions, retries, route changes, waits or renderer fallbacks.
"""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit


MAX_EVENTS = 600
MAX_EVENT_BYTES = 512 * 1024
MAX_TRACE_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024


def safe_url(value):
    parts = urlsplit(str(value))
    if parts.scheme in {"data", "blob"}:
        return parts.scheme + ":[local bytes omitted]"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))[:500]


SNAPSHOT = r"""() => {
  const pair=document.querySelector('.st-key-epc_pair_purchase_package');
  const root=pair?.closest('.epc-workspace');
  const rect=node=>node?.getBoundingClientRect().toJSON()||null;
  const deep=(root,selector)=>{
    const found=[];let visited=0;
    const scan=current=>{for(const node of current?.querySelectorAll('*')||[]){
      if(++visited>4000)return;
      if(node.matches(selector))found.push(node);
      if(node.shadowRoot)scan(node.shadowRoot);
    }};
    scan(root);return found;
  };
  const nodes=selector=>deep(pair,selector);
  const panels=nodes('.report-preview').slice(0,2).map(panel=>{
    const s=panel._previewState||{};
    return {rect:rect(panel),display:getComputedStyle(panel).display,
      visibility:getComputedStyle(panel).visibility,
      status:panel.querySelector('.report-preview-status')?.textContent?.slice(0,300),
      position:panel.querySelector('.report-preview-position')?.textContent?.slice(0,100),
      figures:panel.querySelectorAll('figure').length,
      state:{visible:s.visible,page:s.page,requestFailed:s.requestFailed,
        requestAttempts:s.requestAttempts,requestSequence:s.requestSequence,
        sent:s.sent?.slice(0,1000),signature:s.requestSignature?.slice(0,1000)},
      images:[...panel.querySelectorAll('img')].slice(0,8).map(image=>({
        alt:image.alt.slice(0,150),complete:image.complete,
        width:image.naturalWidth,height:image.naturalHeight,rect:rect(image),
        sourceScheme:(image.currentSrc||image.src).split(':',1)[0]}))};});
  return {scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
    mode:root?.dataset.epcMode,fullRender:root?.dataset.epcFullRender,
    package:{rect:rect(pair),active:pair?.dataset.epcActive,
      reference:rect(pair?.querySelector('.epc-workspace-reference'))},panels,
    acknowledgments:nodes('[data-qa-preview-ack]').slice(-4).map(node=>({
      key:node.dataset.qaPreviewAck,pages:node.dataset.requestPages,count:node.dataset.count})),
    nativeErrors:deep(document,'[data-testid="stException"]').slice(0,4)
      .map(node=>node.textContent.slice(0,1500))};
}"""


class PODiagnostics:
    """Diagnostic failures cannot replace the original native-gate outcome."""
    def __init__(self, output, name):
        self.output, self.name = Path(output), name
        self.log = self.temp = self.context = None
        self.count = self.bytes = self.dropped = 0
        self.tracing = False
        self.errors = []
        self.trace = {"staged": False}
        self.snapshot = {"staged": False}

    def error(self, stage, error):
        if len(self.errors) < 8:
            self.errors.append({"stage": stage, "type": type(error).__name__,
                                "message": str(error)[:500]})

    def record(self, kind, detail):
        try:
            row = json.dumps({"kind": kind, "at": time.monotonic(), "detail": detail},
                             ensure_ascii=True) + "\n"
            size = len(row.encode())
            if self.log is None or self.count >= MAX_EVENTS or self.bytes + size > MAX_EVENT_BYTES:
                self.dropped += 1
                return
            self.log.write(row)
            self.log.flush()
            self.count += 1
            self.bytes += size
        except Exception as error:
            self.error("record", error)

    def start(self, page):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            self.log = (self.output / (self.name + "-events.jsonl")).open("w", encoding="utf-8")
            self.context = page.context

            def capture(kind, make_detail):
                def handler(event):
                    try:
                        detail = make_detail(event)
                        if detail is not None:
                            self.record(kind, detail)
                    except Exception as error:
                        self.error(kind, error)
                return handler

            page.on("console", capture("console", lambda msg: {
                "type": msg.type, "text": msg.text[:2000],
                "url": safe_url(msg.location.get("url", "")),
                "line": msg.location.get("lineNumber"),
            } if msg.type in {"warning", "error"} else None))
            page.on("pageerror", capture("pageerror", lambda error: {
                "message": str(error)[:2000], "stack": str(getattr(error, "stack", ""))[:2000]}))
            page.on("requestfailed", capture("requestfailed", lambda request: {
                "url": safe_url(request.url), "type": request.resource_type,
                "failure": str(request.failure)[:1000]}))
            page.on("response", capture("response", lambda response: {
                "url": safe_url(response.url), "type": response.request.resource_type,
                "status": response.status,
                "content_type": response.headers.get("content-type", "")[:200],
            } if response.request.resource_type == "script" or response.status >= 400 else None))
            # API-call trace only: no screenshots, DOM snapshots, source or
            # binary response bodies. Export to temporary storage first, never
            # directly into the uploaded artifact; stage only under the cap.
            self.temp = tempfile.TemporaryDirectory(prefix="po-qa-trace-")
            self.context.tracing.start(screenshots=False, snapshots=False, sources=False)
            self.tracing = True
        except Exception as error:
            self.error("start", error)

    def failure_snapshot(self, page):
        try:
            raw = (json.dumps(page.evaluate(SNAPSHOT), ensure_ascii=True, indent=2) + "\n").encode()
            self.snapshot = {"staged": False, "bytes": len(raw), "limit": MAX_SNAPSHOT_BYTES}
            # Keep the first-failure state even if prior events filled their
            # separate log budget. Never truncate JSON into invalid evidence.
            if len(raw) <= MAX_SNAPSHOT_BYTES:
                (self.output / (self.name + "-first-failure.json")).write_bytes(raw)
                self.snapshot.update(staged=True, sha256=sha256(raw).hexdigest())
            else:
                self.snapshot["omitted"] = "Snapshot exceeds the artifact staging cap."
        except Exception as error:
            self.error("first-failure", error)

    def close(self):
        try:
            if self.tracing:
                path = Path(self.temp.name) / "trace.zip"
                self.context.tracing.stop(path=str(path))
                size = path.stat().st_size
                self.trace = {"staged": False, "bytes": size, "limit": MAX_TRACE_BYTES}
                if size <= MAX_TRACE_BYTES:
                    digest = sha256(path.read_bytes()).hexdigest()
                    shutil.copyfile(path, self.output / (self.name + "-trace.zip"))
                    self.trace.update(staged=True, sha256=digest)
                else:
                    self.trace["omitted"] = "Trace exceeds the artifact staging cap."
        except Exception as error:
            self.error("trace-stop", error)
        finally:
            try:
                if self.temp is not None:
                    self.temp.cleanup()
            except Exception as error:
                self.error("trace-cleanup", error)
            try:
                if self.log is not None:
                    self.log.close()
            except Exception as error:
                self.error("log-close", error)
            try:
                summary = {"synthetic_only": True, "events": self.count, "event_bytes": self.bytes,
                           "dropped": self.dropped, "event_limit": MAX_EVENTS,
                           "event_byte_limit": MAX_EVENT_BYTES, "trace": self.trace,
                           "snapshot": self.snapshot,
                           "diagnostic_errors": self.errors}
                (self.output / (self.name + "-summary.json")).write_text(json.dumps(summary, indent=2) + "\n")
            except Exception as error:
                self.error("summary-write", error)
