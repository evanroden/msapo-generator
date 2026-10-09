"""Report previews use the real layout; finished downloads keep strict gates."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import fitz
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from app import monthly_report_library as library, pdf_converter
from app.monthly_report_checks import preflight
from app.monthly_report_docx import _build_docx, _save, normalize_report_image
from app.monthly_report_model import COVER_ASSET_KEYS, included_sections


@dataclass(frozen=True)
class ReportPreview:
    pdf: bytes
    pages: int
    fingerprint: str
    period: str


MAX_PREVIEW_PAGES = 150
MAX_PREVIEW_BYTES = 25 * 1024 * 1024
# Previewing unfinished work is deliberate. These exceptions never apply to
# assemble_docx/generate_report or remove the final-output review requirements.
_REVIEW_CODES = {
    "prepared_by",
    "required",
    "review",
    "client_pages",
    "ai_evidence",
    "ai_number",
    "follow_up",
    "follow_up_section",
    "library_save",
}


def preview_report(draft, asset_loader=None):
    blockers = [
        c.message
        for c in preflight(draft)
        if c.blocking and c.code not in _REVIEW_CODES
    ]
    if blockers:
        raise ValueError(" ".join(blockers))
    if not draft.sections:
        raise ValueError("Add report sections before creating a preview.")

    @lru_cache(maxsize=12)
    def small_asset(ref):
        if asset_loader is None:
            raise ValueError("Preview needs the saved report images.")
        image = normalize_report_image(
            asset_loader(ref), Path(ref).suffix, line_art=True, dpi=96
        )
        return image.data

    raw = _build_docx(draft, asset_loader=small_asset if asset_loader else None)
    scratch = library._root() / "previews"
    scratch.mkdir(parents=True, exist_ok=True)
    stem = "preview-" + uuid4().hex
    expected = pdf_converter.OUTPUT_DIR / (stem + ".pdf")
    actual = None
    try:
        with tempfile.TemporaryDirectory(prefix="report-", dir=scratch) as directory:
            path = Path(directory) / (stem + ".docx")
            path.write_bytes(raw)
            actual = pdf_converter.convert_to_pdf(path)
            if actual.stat().st_size > 80 * 1024 * 1024:
                raise ValueError(
                    "Preview exceeds the 80 MB conversion bound. Preview fewer sections or reduce image sizes."
                )
            output = fitz.open()
            try:
                image_bytes = 0
                with fitz.open(actual) as pdf:
                    if pdf.page_count > MAX_PREVIEW_PAGES:
                        raise ValueError(
                            "Preview is limited to 150 pages. Preview fewer sections or reduce page selections."
                        )
                    for source in pdf:
                        pix = source.get_pixmap(
                            matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False
                        )
                        image = Image.frombytes(
                            "RGB", (pix.width, pix.height), pix.samples
                        )
                        buffer = BytesIO()
                        image.save(buffer, "JPEG", quality=65, optimize=True)
                        image_bytes += len(buffer.getvalue())
                        if image_bytes > MAX_PREVIEW_BYTES:
                            raise ValueError(
                                "Preview exceeds 25 MB. Preview fewer sections or reduce the selected pages."
                            )
                        page = output.new_page(
                            width=source.rect.width, height=source.rect.height
                        )
                        page.insert_image(page.rect, stream=buffer.getvalue())
                        point = fitz.Point(
                            page.rect.width * 0.18, page.rect.height * 0.63
                        )
                        page.insert_text(
                            point,
                            "DRAFT - REVIEW ONLY",
                            fontsize=32,
                            color=(0.7, 0.08, 0.08),
                            fill_opacity=0.4,
                            morph=(point, fitz.Matrix(35)),
                        )
                        page.insert_text(
                            (25, 22),
                            "DRAFT PREVIEW - NOT A FINISHED CLIENT REPORT",
                            fontsize=9,
                            color=(0.65, 0.05, 0.05),
                        )
                result = output.tobytes(garbage=3, deflate=True)
                if len(result) > MAX_PREVIEW_BYTES:
                    raise ValueError(
                        "Preview exceeds 25 MB. Preview fewer sections or reduce the selected pages."
                    )
                return ReportPreview(
                    result, len(output), draft.fingerprint, draft.period.label
                )
            finally:
                output.close()
    finally:
        for path in {actual, expected} - {None}:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def preview_page(preview, index, *, dpi=150):
    if dpi not in (96, 150, 200):
        raise ValueError("Choose a supported preview resolution.")
    with fitz.open(stream=preview.pdf, filetype="pdf") as pdf:
        if not 0 <= index < len(pdf):
            raise ValueError("Choose an existing preview page.")
        return (
            pdf[index].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False).tobytes("png")
        )


def _section_scope(draft, section_key):
    """Keep numbering, but resolve assets/content only for the visible section."""
    sections = included_sections(draft.sections)
    if section_key == "cover":
        keys = set(COVER_ASSET_KEYS)
        selected = None
    else:
        selected = next((section for section in sections if section.key == section_key), None)
        if selected is None:
            raise ValueError("Choose an existing report section to preview.")
        keys = {spec.key for spec in selected.blocks} | {"brand_logo", "divider_" + section_key}
    # Empty scaffolding retains the section's true number without reading other
    # sections' images. The scaffolding is removed BEFORE PDF conversion.
    scope = replace(
        draft,
        sections=tuple(section if section == selected else replace(section, blocks=(), divider_asset="")
                       for section in sections) if selected else (),
        blocks=tuple(block for block in draft.blocks if block.key in keys),
        follow_ups=tuple(item for item in draft.follow_ups
                         if ("issues" if item.category == "issue" else "proposals") == section_key),
    )
    return scope, selected


def section_preview_fingerprint(draft, section_key):
    """Review toggles and changes to another section do not rerender this one."""
    scope, section = _section_scope(draft, section_key)
    blocks = []
    for block in scope.blocks:
        if block.source == "Omit":
            # Keep explicit omission of a divider, which overrides its design.
            blocks.append({"key": block.key, "source": "Omit"})
            continue
        blocks.append({name: getattr(block, name) for name in (
            "key", "text", "rows", "asset_hashes", "asset_captions", "photos_per_page",
        )} | {"org_nodes": [asdict(node) for node in block.org_nodes],
             "extra_tables": [asdict(table) for table in block.extra_tables]})
    from app.monthly_report_followups import report_text
    value = {
        "version": 3,
        "period": draft.period.key,
        "title": draft.profile.title,
        "contract": draft.profile.contract,
        "profile": draft.profile.key,
        "section": asdict(section) if section else "cover",
        "blocks": blocks,
        "address": draft.address_line if section else "",
        "follow_ups": [report_text(item) for item in scope.follow_ups if item.included],
    }
    from app.monthly_report_designs import fingerprint
    value["native_layout"] = fingerprint(draft.profile)
    if section is None:
        value["cover"] = {"title": draft.profile.title, "period": draft.period.key,
                          "prepared_by": draft.prepared_by, "synthetic": draft.synthetic,
                          "facilities": [facility.title for facility in draft.profile.facilities]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _slice_document_sections(raw, first, count):
    """Slice Word section boundaries, including overflow pages and page chrome.

    A cover or long contents table can occupy several pages. Hard-coded PDF page
    offsets would show the wrong pages, so scope the DOCX before pagination.
    """
    document = Document(BytesIO(raw))
    body = document.element.body
    children = list(body)
    endings = []
    for index, child in enumerate(children):
        properties = child if child.tag == qn("w:sectPr") else child.find("./" + qn("w:pPr") + "/" + qn("w:sectPr"))
        if properties is not None:
            endings.append((index, properties))
    if first < 0 or count < 1 or first + count > len(endings):
        raise ValueError("The section preview could not be matched to the report layout.")
    start = endings[first - 1][0] + 1 if first else 0
    stop, properties = endings[first + count - 1]
    selected = children[start:stop]
    final_properties = deepcopy(properties)
    body.clear_content()
    # clear_content preserves the old final sectPr; replace it with the selected
    # section's properties (especially cover margins and header/footer links).
    for child in list(body):
        body.remove(child)
    for child in selected:
        body.append(child)
    body.append(final_properties)
    return _save(document)


def section_preview_docx(draft, section_key, asset_loader=None):
    """Private unfinished preview input, never an approved client download."""
    scope, section = _section_scope(draft, section_key)
    checks_scope = replace(scope, sections=(section,) if section else ())
    unfinished_codes = _REVIEW_CODES | {
        "sections", "placeholder", "carried_period", "client_source_page", "client_source_missing",
    }
    blockers = [check.message for check in preflight(checks_scope)
                if check.blocking and check.code not in unfinished_codes]
    if blockers:
        raise ValueError(" ".join(blockers))

    from app.monthly_report_designs import source_for, is_master
    source = source_for(draft.profile)
    if source is not None:
        from app.monthly_report_native_layout import build_native_docx
        return build_native_docx(draft, source, asset_loader=asset_loader, section_key=section_key, master=is_master(draft.profile))

    @lru_cache(maxsize=12)
    def image_asset(ref):
        if asset_loader is None:
            raise ValueError("The saved picture is not available for this preview.")
        return normalize_report_image(asset_loader(ref), Path(ref).suffix, line_art=True, dpi=150).data

    raw = _build_docx(scope, asset_loader=image_asset if asset_loader else None)
    index = next((n for n, value in enumerate(scope.sections) if value.key == section_key), 0)
    return _slice_document_sections(raw, 2 + 2 * index if section else 0, 2 if section else 1)


def preview_section(draft, section_key, asset_loader=None):
    """High-quality, section-only preview with bounded, cleaned-up conversion."""
    raw = section_preview_docx(draft, section_key, asset_loader)
    stem = "section-preview-" + uuid4().hex
    expected = pdf_converter.OUTPUT_DIR / (stem + ".pdf")
    actual = None
    try:
        with tempfile.TemporaryDirectory(prefix="monthly-section-preview-") as directory:
            path = Path(directory) / (stem + ".docx")
            path.write_bytes(raw)
            actual = pdf_converter.convert_to_pdf(path)
            if actual.stat().st_size > MAX_PREVIEW_BYTES:
                raise ValueError("This section preview exceeds 25 MB. Reduce the size of its pictures.")
            with fitz.open(actual) as pdf:
                if len(pdf) > MAX_PREVIEW_PAGES:
                    raise ValueError("This section preview is limited to 150 pages.")
                if not len(pdf):
                    raise ValueError("The renderer returned an empty section preview.")
                # Keep the real PDF's vector text and diagrams. Draft status is
                # shown in the editor, outside the page, so layout stays legible.
                result = pdf.tobytes(garbage=3, deflate=True)
                if len(result) > MAX_PREVIEW_BYTES:
                    raise ValueError("This section preview exceeds 25 MB. Reduce the size of its pictures.")
                return ReportPreview(result, len(pdf), section_preview_fingerprint(draft, section_key), draft.period.label)
    finally:
        for path in {actual, expected} - {None}:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def render_preview(draft, assets, prefix, field):
    import streamlit as st

    with st.expander("Preview the report at any time"):
        st.caption(
            "A low-resolution, watermarked PDF helps you check the whole layout while work is unfinished. It does not approve content or replace the final review."
        )
        key = prefix + "_preview_pdf"
        preview = st.session_state.get(key)
        if preview and preview.fingerprint != draft.fingerprint:
            st.caption(
                "The report changed. Refresh the preview to see the current version."
            )
        if st.button(
            "Refresh preview PDF" if preview else "Create preview PDF",
            key=prefix + "_preview_build",
        ):
            loader = lambda ref: (
                assets.get(ref)
                or library.read_asset(draft.profile.contract, draft.profile.key, ref)
            )
            try:
                with st.spinner("Building the preview…"):
                    preview = preview_report(draft, loader)
                st.session_state[key] = preview
            except Exception as exc:
                st.warning(
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Preview conversion could not finish. Your draft and finished downloads are unchanged."
                )
        if preview:
            stale = preview.fingerprint != draft.fingerprint
            page = int(
                st.number_input(
                    "Preview page",
                    min_value=1,
                    max_value=preview.pages,
                    key=field(prefix + "_preview_page_" + str(preview.pages), 1),
                )
            )
            st.image(preview_page(preview, page - 1), width="stretch")
            st.download_button(
                "Download draft preview PDF",
                preview.pdf,
                file_name="Draft preview - " + preview.period + ".pdf",
                mime="application/pdf",
                key=prefix + "_preview_download",
                disabled=stale,
            )
            st.caption(
                f"{preview.pages} preview pages · {len(preview.pdf) / (1024 * 1024):.1f} MB. Finished DOCX/PDF downloads are in Review & download."
            )
