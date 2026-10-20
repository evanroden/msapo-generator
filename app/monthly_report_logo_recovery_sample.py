"""Disposable legacy-logo fault sample in its own browser-bound QA namespace."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import struct
from uuid import uuid4
import zlib

from PIL import Image, ImageDraw

from app import monthly_report_branding as branding, monthly_report_directory as directory
from app import monthly_report_library as library, monthly_report_testing as testing

_ACTIVE = ContextVar("monthly_logo_recovery_sample", default=None)


@contextmanager
def sample_scope(browser_token):
    if not isinstance(browser_token, str) or not re.fullmatch(r"[0-9a-f]{32}", browser_token):
        raise ValueError("Logo recovery testing requires this browser's valid device identity.")
    token = sha256(("logo-recovery-v1:" + browser_token).encode("ascii")).hexdigest()[:32]
    with testing.isolated(token) as identity:
        active = _ACTIVE.set(identity)
        try:
            yield
        finally:
            _ACTIVE.reset(active)


def _path():
    if testing.scope() is None or _ACTIVE.get() != testing.scope():
        raise ValueError("Logo recovery samples require their separate test area.")
    path = library._root() / "qa_logo_recovery" / "sample.json"
    _safe(path)
    return path


def _safe(path):
    library._qa_path_guard(path)
    root = library._root()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("Linked logo sample storage is unavailable.")
        if parent == root:
            break


def _bytes(path, limit=library.MAX_JSON_BYTES):
    _safe(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _safe(path)
    if len(raw) > limit:
        raise ValueError("Logo sample exceeds its reading limit.")
    return raw


def _artwork(label, color):
    image = Image.new("RGB", (240, 80), color)
    ImageDraw.Draw(image).text((12, 30), label, fill="white")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def _broken_png(original):
    """Keep valid PNG framing/CRCs but replace the compressed pixel stream."""
    result, cursor = bytearray(original[:8]), 8
    while cursor < len(original):
        length = struct.unpack(">I", original[cursor:cursor + 4])[0]
        kind = original[cursor + 4:cursor + 8]
        data = original[cursor + 8:cursor + 8 + length]
        if kind == b"IDAT":
            data = b"synthetic undecodable pixel stream"
        result.extend(struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data)))
        cursor += length + 12
    return bytes(result)


def create_sample():
    receipt_path = _path()
    with library._locked(receipt_path.parent):
        if receipt_path.exists():
            receipt = library._read(receipt_path)
            if receipt.get("status") != "ready":
                raise ValueError("The earlier sample was interrupted. Its records were retained; no sample was replaced.")
            return receipt
        path = branding._path()
        _safe(path)
        with library._locked(path):
            if any(p.name != ".write-lock" for p in path.iterdir()):
                raise ValueError("Existing logo records were preserved. This sample needs an empty test area.")
        suffix = uuid4().hex
        contract, control = "Synthetic Logo Recovery " + suffix, "Synthetic Logo Control " + suffix
        receipt = {"schema": 1, "status": "pending", "contract": contract, "control": control}
        library._atomic_write(receipt_path, library._json(receipt))
        good = _artwork("SYNTHETIC RECOVERY", "#174237")
        healthy = _artwork("SYNTHETIC CONTROL", "#294f80")
        broken = _broken_png(good)
        def logo(key, title, name, raw):
            return branding.BrandLogo(key, title, (name,), library.asset_reference(raw, "png"),
                "https://example.invalid/synthetic", "https://example.invalid/synthetic.png", "2026-10-20",
                "Invented artwork for isolated recovery testing only.")
        target = logo("synthetic-recovery", "Synthetic recovery logo", contract, good)
        sibling = logo("synthetic-control", "Synthetic healthy logo", control, healthy)
        first = branding.save_branding((target, sibling), {target.asset: good, sibling.asset: healthy},
            expected_revision=0, actor="Synthetic Logo Sample", confirmed=True)
        directory_hashes = {}
        for name in (contract, control):
            state = directory.save_directory(name, (directory.DirectorySite("synthetic-logo-site", "Synthetic Logo Site"),),
                expected_revision=0, actor="Synthetic Logo Sample", confirmed=True)
            directory_hashes[name] = sha256(library._json({"schema": 1, **asdict(state)})).hexdigest()
        # Fault injection is confined to this newly reserved sample collection.
        # Recheck under the ordinary branding lock; never damage a changed head.
        with library._locked(path):
            if branding.load_branding() != first:
                raise library.RevisionConflict("The sample logos changed; no artwork was damaged.")
            damaged = replace(target, asset=library.asset_reference(broken, "png"))
            second = replace(first, revision=2, logos=(damaged, sibling), action="synthetic-legacy-artwork")
            encoded = library._json({"schema": 1, **asdict(second)})
            library._atomic_write(path / "assets" / damaged.asset, broken)
            library._atomic_write(path / "history" / "00000002.json", encoded)
            library._atomic_write(path / "manifest.json", encoded)
        receipt.update(status="ready", damaged_asset=damaged.asset, healthy_asset=sibling.asset,
            history_1=sha256(library._json({"schema": 1, **asdict(first)})).hexdigest(),
            history_2=sha256(encoded).hexdigest(), directory_hashes=directory_hashes)
        library._atomic_write(receipt_path, library._json(receipt))
        return receipt


def check_sample():
    receipt = library._read(_path())
    if receipt.get("status") != "ready":
        raise ValueError("No completed logo recovery sample is available.")
    path = branding._path()
    first, second, current = branding.load_branding(1), branding.load_branding(2), branding.load_branding()
    checks = {
        "Original readable history unchanged": sha256(_bytes(path / "history" / "00000001.json")).hexdigest() == receipt["history_1"],
        "Damaged collection history unchanged": sha256(_bytes(path / "history" / "00000002.json")).hexdigest() == receipt["history_2"],
        "Damaged artwork retained exactly": library.asset_reference(_bytes(path / "assets" / receipt["damaged_asset"], branding.MAX_IMAGE_BYTES), "png") == receipt["damaged_asset"],
        "Healthy logo and mapping unchanged": bool(current and current.logos[1:] == first.logos[1:] == second.logos[1:]
            and library.asset_reference(branding.read_logo(first.logos[1]), "png") == receipt["healthy_asset"]),
        "Recovered as revision 3": bool(current and current.revision == 3 and current.action == "restore:1" and current.logos == first.logos),
        "Both directory records unchanged": all(sha256(_bytes(library._root() / "directory" / library._contract_directory(name) / "manifest.json")).hexdigest() == digest for name, digest in receipt["directory_hashes"].items()),
    }
    if checks["Recovered as revision 3"]:
        branding.read_logo(current.logos[0])
    return receipt, checks


def render_banner():
    import streamlit as st
    _path()  # Verify this is the dedicated sample context before rendering.
    st.warning("ISOLATED LOGO RECOVERY TESTING — invented records only. No live report or existing synthetic report, contact, logo or fixture records are accessible here.")


def render_sample():
    import streamlit as st
    from app.monthly_report_ui_text import literal
    _path()
    with st.expander("Stored-logo recovery sample (synthetic only)"):
        st.caption("Creates a fresh collection with readable history, one undecodable saved logo and a healthy control. Repeating creation preserves the existing sample, including after recovery.")
        if st.button("Create stored-logo recovery sample", key="report_logo_sample_create"):
            try:
                receipt = create_sample()
                st.success("Sample is available. Inspect the contract cards and use Shared contract logos to review its history.")
                st.text(receipt["contract"])
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
        if st.button("Check stored-logo recovery", key="report_logo_sample_check"):
            try:
                receipt, checks = check_sample()
                st.text(receipt["contract"])
                for label, passed in checks.items():
                    (st.success if passed else st.warning)(label if passed else label + ": not yet verified")
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
    with st.expander("Input observations (synthetic only)"):
        st.caption("Optional local observations of the restore checkbox and Saved collection control. Records event types and checkbox state only; no field text is collected or sent to the server. Reload to stop.")
        if st.button("Observe input events", key="report_logo_sample_observe"):
            st.session_state["report_logo_sample_observing"] = True
        if st.session_state.get("report_logo_sample_observing"):
            _input_observer()(key="report_logo_sample_input_observer", height=180)


def _input_observer():
    """Observation is available only after the separate sample scope check."""
    import streamlit as st
    _path()
    return st.components.v2.component("enfra_logo_sample_input_observer",
        html='<pre data-input-observations style="white-space:pre-wrap;font-size:11px;max-height:170px;overflow:auto"></pre>',
        js=Path(__file__).with_name("monthly_report_input_observation.js").read_text())


def render(browser_token, browser_timezone, field, move, live_root):
    from app.monthly_report_guided import render_guided_workflow
    render_banner()
    render_sample()
    render_guided_workflow(browser_token, browser_timezone, field, move)
