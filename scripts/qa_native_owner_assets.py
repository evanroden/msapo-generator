"""Exact-source, QA-only annotations in a disposable copy of the native client.

This is not a production publisher or a resize repair. Import paths and the
existing callback bodies/scheduling stay intact; only bounded observations are
inserted at the known native observer sites. Installed assets are never written.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import shutil

from scripts import patch_streamlit_frontend as compat

SCHEMA = "enfra-native-owner-copy-v1"
FLOATING = "useFloatingOverlay.NyFxHaQF.js"
FLOATING_SHA256 = "0bb3da6d472fd03e249c6c42e6cb3c1e6f4e9f57804278d94cda231638d06e80"
SINK = "__enfraNativeOwnerObservation"


def _note(expression):
    # A broken or missing diagnostic must never replace a native return/throw.
    return "try{" + expression + "}catch{}"


def _registration(owner, target, box="void 0", *, condition=None):
    note = _note(f"enfraOwnerId=globalThis.{SINK}?.register({owner},{target},{box},new Error().stack)")
    return "let enfraOwnerId;" + ("if(" + condition + "){" + note + "}" if condition else note)


def _callback(body):
    return (_note(f"globalThis.{SINK}?.start(enfraOwnerId,e)")
            + "try{" + body + "}finally{"
            + _note(f"globalThis.{SINK}?.end(enfraOwnerId)") + "}")


XT = ("function Xt(e){let{ref:t,box:n,onResize:r}=e,i=Ze(r);(0,u.useEffect)(()=>{let e=t?.current;"
      "if(e)if(Yt()){let t=new window.ResizeObserver(e=>{e.length&&i()});"
      "return t.observe(e,{box:n}),()=>{e&&t.unobserve(e)}}else return window.addEventListener(`resize`,i,!1),"
      "()=>{window.removeEventListener(`resize`,i,!1)}},[t,n])}")
XT_OBSERVED = ("function Xt(e){let{ref:t,box:n,onResize:r,enfraOwner:o}=e,i=Ze(r);"
               "(0,u.useEffect)(()=>{let e=t?.current;if(e)if(Yt()){"
               + _registration("o??`aria-other`", "e", "n")
               + "let t=new window.ResizeObserver(e=>{" + _callback("e.length&&i()") + "});"
               "return t.observe(e,{box:n}),()=>{e&&t.unobserve(e)}}else return window.addEventListener(`resize`,i,!1),"
               "()=>{window.removeEventListener(`resize`,i,!1)}},[t,n])}")
RN_START = "let d=l&&s?nn(l,n,a):null,f=-1,p=null;o&&(p=new ResizeObserver(e=>{"
RN_BODY = ("let[r]=e;r&&r.target===l&&p&&t&&(p.unobserve(t),cancelAnimationFrame(f),"
           "f=requestAnimationFrame(()=>{var e;(e=p)==null||e.observe(t)})),n()")
RN_END = "}),l&&!c&&p.observe(l),t&&p.observe(t));"
RN = RN_START + RN_BODY + RN_END
RN_OBSERVED = ("let d=l&&s?nn(l,n,a):null,f=-1,p=null;"
               + _registration("`floating-auto-update`", "[l&&!c?l:null,t]", condition="o")
               + "o&&(p=new ResizeObserver(e=>{" + _callback(RN_BODY) + RN_END)


def annotate(raw, replacements):
    """All sites must match once before any diagnostic asset is produced."""
    text = raw.decode("utf-8")
    for before, after in replacements:
        if text.count(before) != 1:
            raise RuntimeError("Unexpected exact native observer annotation boundary")
        text = text.replace(before, after, 1)
    return text.encode("utf-8")


def expected_assets(source):
    """Derive bytes from the pinned ordinary client, never from served output."""
    source = Path(source)
    selected = compat.selected_frontend(source)
    if selected["virtualizer_resize"] is not True:
        raise RuntimeError("The diagnostic requires the current repaired virtualizer client")
    scripts = source / "static/js"
    floating = (scripts / FLOATING).read_bytes()
    if sha256(floating).hexdigest() != FLOATING_SHA256:
        raise RuntimeError("Unexpected locked Floating UI native source")
    overlay_name, virtual_name = selected["overlay_bundle"], selected["virtualizer_bundle"]
    overlay = (scripts / overlay_name).read_bytes()
    virtual = (scripts / virtual_name).read_bytes()
    overlay_changes = [
        (XT, XT_OBSERVED),
        ("Xt({ref:i,onResize:enfraResizePosition})", "Xt({enfraOwner:`aria-position-floating`,ref:i,onResize:enfraResizePosition})"),
        ("Xt({ref:r,onResize:enfraResizePosition})", "Xt({enfraOwner:`aria-position-trigger`,ref:r,onResize:enfraResizePosition})"),
    ]
    virtual_changes = [
        ("k({ref:_.style?.[`--trigger-width`]?void 0:i.triggerRef,onResize:j})",
         "k({enfraOwner:`aria-popover-trigger-width`,ref:_.style?.[`--trigger-width`]?void 0:i.triggerRef,onResize:j})"),
        ("k({ref:f,onResize:(0,J.useCallback)(()=>{if(f.current&&!p.current)",
         "k({enfraOwner:`aria-combobox-input-width`,ref:f,onResize:(0,J.useCallback)(()=>{if(f.current&&!p.current)"),
        ("k({ref:t,box:`border-box`,onResize:enfraQueue})",
         "k({enfraOwner:`aria-virtualizer-container`,ref:t,box:`border-box`,onResize:enfraQueue})"),
    ]
    native = {selected["entry"]: (scripts / selected["entry"]).read_bytes(),
              overlay_name: overlay, virtual_name: virtual, FLOATING: floating}
    output = {**native, overlay_name: annotate(overlay, overlay_changes),
              virtual_name: annotate(virtual, virtual_changes), FLOATING: annotate(floating, [(RN, RN_OBSERVED)])}
    recipe = {"overlay": overlay_changes, "virtualizer": virtual_changes, "floating": [(RN, RN_OBSERVED)]}
    manifest = {"schema": SCHEMA, "purpose": "diagnostic derivative, never acceptance or a repair",
                "selected_production": selected,
                "sink_sha256": sha256(Path(__file__).with_name("qa_native_owner_sink.js").read_bytes()).hexdigest(),
                "recipe_sha256": sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest(),
                "html_sha256": sha256((source / "index.html").read_bytes()).hexdigest(),
                "assets": {name: {"input_sha256": sha256(native[name]).hexdigest(),
                                  "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
                                  "annotated": raw != native[name]} for name, raw in output.items()}}
    return manifest, output


def build_copy(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source == destination or source in destination.parents or destination in source.parents:
        raise RuntimeError("Diagnostic static destination must be new and separate")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise RuntimeError("Diagnostic static source cannot contain symlinks")
    manifest, output = expected_assets(source)
    shutil.copytree(source, destination)
    # Validate the copied ordinary graph before any annotation. The immutable
    # source remains selected normally throughout this independent experiment.
    compat.selected_frontend(destination)
    for name, raw in output.items():
        path = destination / "static/js" / name
        if sha256(path.read_bytes()).hexdigest() != manifest["assets"][name]["input_sha256"]:
            raise RuntimeError("Native static copy changed during preparation")
        path.write_bytes(raw)
        if path.read_bytes() != raw:
            raise RuntimeError("Diagnostic static copy failed its byte check")
    verify_copy(destination, manifest)
    return manifest


def verify_copy(root, manifest):
    root = Path(root).resolve()
    if manifest.get("schema") != SCHEMA or len(manifest.get("assets", {})) != 4:
        raise RuntimeError("Invalid native owner diagnostic manifest")
    if sha256((root / "index.html").read_bytes()).hexdigest() != manifest["html_sha256"]:
        raise RuntimeError("Diagnostic HTML differs from the pinned ordinary entry")
    for name, row in manifest["assets"].items():
        if Path(name).name != name or not name.endswith(".js"):
            raise RuntimeError("Unsafe native owner diagnostic asset name")
        path = root / "static/js" / name
        if path.is_symlink():
            raise RuntimeError("Diagnostic asset cannot be a symlink")
        raw = path.read_bytes()
        if len(raw) != row["bytes"] or sha256(raw).hexdigest() != row["sha256"]:
            raise RuntimeError("Diagnostic asset differs from the exact intended derivative")


@contextmanager
def owned_static(root, manifest, data_root):
    """Redirect one explicitly invoked diagnostic server; restore on every exit."""
    from streamlit import file_util
    root, data_root = Path(root).resolve(), Path(data_root).resolve()
    if root.parent != data_root.parent or root.name != "static" or data_root.name != "data":
        raise RuntimeError("Diagnostic static and data roots must share one owned temporary directory")
    if (data_root / "monthly-dom-synthetic-only.marker").read_text() != "synthetic-monthly-dom-v1":
        raise RuntimeError("Native owner diagnostics require the isolated synthetic marker")
    original = file_util.get_static_dir
    if Path(original()).resolve() == root:
        raise RuntimeError("Diagnostic server cannot own the installed static directory")
    expected, _ = expected_assets(original())
    if manifest != expected:
        raise RuntimeError("Diagnostic manifest is not derived from the pinned installed client")
    verify_copy(root, manifest)
    try:
        file_util.get_static_dir = lambda: str(root)
        yield
    finally:
        file_util.get_static_dir = original
