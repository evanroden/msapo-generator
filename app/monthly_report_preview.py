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

import pymupdf as fitz
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from app.monthly_report_preview_metrics import measured, phase
from app.monthly_report_render_compat import rendering_docx
from app import monthly_report_library as library, pdf_converter
from app import monthly_report_render_jobs as monthly_render_jobs
from app.monthly_report_checks import preflight
from app.monthly_report_docx import _build_docx, _save, normalize_report_image
from app.monthly_report_model import COVER_ASSET_KEYS, included_sections


@dataclass(frozen=True)
class ReportPreview:
    pdf: bytes
    pages: int
    fingerprint: str
    period: str
    initial_page: int = 0


def section_initial_page(pdf, section):
    """Start past a proved title-only divider, keeping every PDF page intact.

    Do not guess that an image-only first page or an unfamiliar native layout
    is a divider. A content-first report keeps its real first page.
    """
    if section is None or len(pdf) < 2:
        return 0
    # A matching title does not prove the page is otherwise empty. Retain the
    # first page for unclassified artwork, including unfamiliar branding;
    # neither its position nor its size establishes that it is a divider.
    if pdf[0].get_image_info() or pdf[0].get_drawings():
        return 0
    normalize = lambda value: ''.join(c.casefold() for c in value if c.isalnum())
    expected = normalize(('Appendix ' if section.appendix else 'Section ') + section.number + ' ' + section.title)
    return int(normalize(pdf[0].get_text()) == expected)


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
    "ai_date",
    "follow_up",
    "follow_up_section",
    "library_save",
    # The private, watermarked editing view must remain available while the
    # user inspects and corrects a source's site. Finished output still uses
    # the mandatory source-facility gate in preflight/assemble_docx.
    "source_facility",
}


@measured("report_preview_total_including_queue")
def preview_report(draft, asset_loader=None, *, source_view=None, ticket_only=False):
    """Full review preview; ticket_only is exclusively for private raster-on-read stores."""
    with monthly_render_jobs.work_slot(preview=True, review=True, wait_seconds=10):
        return _preview_report(draft, asset_loader, source_view=source_view,
                               ticket_only=ticket_only)


def _preview_report(draft, asset_loader=None, *, source_view=None, ticket_only=False):
    from app.monthly_report_source_view_runtime import render_operation, preview_fingerprint
    with render_operation(draft, source_view) as operation:
        fingerprint = preview_fingerprint(draft)
        result = _preview_verified_report(draft, asset_loader, source_view=operation.view,
                                          fingerprint=fingerprint, ticket_only=ticket_only)
        if preview_fingerprint(draft) != fingerprint:
            raise ValueError('The source-view preview evidence changed during conversion; no output was published.')
        return result


@measured("report_preview_verified_total")
def _preview_verified_report(draft, asset_loader=None, *, source_view=None, fingerprint,
                             ticket_only=False):
    blockers = [
        c.message
        for c in preflight(draft)
        if c.blocking and c.code not in _REVIEW_CODES
    ]
    if blockers:
        raise ValueError(" ".join(blockers))
    if not draft.sections:
        raise ValueError("Add report sections before creating a preview.")

    from app.monthly_report_asset_layout import photo_preview_references
    photo_assets = photo_preview_references(draft)
    logo_assets = {ref for block in draft.blocks if block.key in ('brand_logo', 'client_logo')
                   for ref in block.asset_hashes}

    @lru_cache(maxsize=4)
    def small_asset(ref):
        if asset_loader is None:
            raise ValueError("Preview needs the saved report images.")
        image = normalize_report_image(
            asset_loader(ref), Path(ref).suffix, line_art=ref not in photo_assets, dpi=96,
            preserve_transparency=ref in logo_assets,
        )
        return image.data

    with phase("report_docx_assembly"):
        raw = _build_docx(draft, asset_loader=small_asset if asset_loader else None, source_view=source_view)
    # This DOCX is disposable conversion input, never a standing report asset.
    # Keep it outside the durable library while a view-only fragment runs in
    # parallel with editor recovery and its storage-integrity checks.
    stem = "preview-" + uuid4().hex
    expected = pdf_converter.OUTPUT_DIR / (stem + ".pdf")
    actual = None
    try:
        with tempfile.TemporaryDirectory(prefix="monthly-review-preview-") as directory:
            path = Path(directory) / (stem + ".docx")
            from app.monthly_report_designs import render_profile_for
            with phase("report_render_compat"):
                compatible = rendering_docx(raw, profile=render_profile_for(draft.profile))
            del raw
            from app.monthly_report_preview_images import write_preview_docx
            with phase("report_preview_image_copy"):
                write_preview_docx(compatible, path)
            del compatible
            small_asset.cache_clear()
            with phase("report_pdf_conversion"):
                actual = monthly_render_jobs.convert_to_pdf(path, wait_seconds=0)
            if actual.stat().st_size > 80 * 1024 * 1024:
                raise ValueError(
                    "Preview exceeds the 80 MB conversion bound. Preview fewer sections or reduce image sizes."
                )
            # Review uses a private PreviewStore ticket, which sends only
            # JPEG page rasters to the browser. Unlike the legacy downloadable
            # PDF, that server-only ticket need not flatten *every* page first.
            # Preserve the original all-page raster path for large inputs and
            # every caller that can download a draft PDF.
            if ticket_only:
                from app.monthly_report_preview_ticket import private_ticket_pdf
                with fitz.open(actual) as native:
                    fast = private_ticket_pdf(
                        native, source_bytes=actual.stat().st_size,
                        max_pages=MAX_PREVIEW_PAGES, max_bytes=MAX_PREVIEW_BYTES,
                    )
                    if fast is not None:
                        return ReportPreview(fast, len(native), fingerprint, draft.period.label)
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
                return ReportPreview(result, len(output), fingerprint, draft.period.label)
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
    """Fingerprint visible geometry without reserializing unchanged sections.

    _section_scope retains the real section, including shared logos and its
    included-section numbering. The immutable key excludes unrelated blocks.
    Source-view evidence is rechecked *before* each cache lookup: a manifest,
    original or receipt replacement must never hit a stale preview fingerprint.
    """
    from app.monthly_report_source_view_runtime import cache_identity, source_revision_identity
    scope, section = _section_scope(draft, section_key)
    source_identity = cache_identity(draft)
    # Ordered (id, filename, SHA-256) tuples: an immutable part of the key, so a
    # same-name replacement upload never hits a stale memoized fingerprint.
    source_revisions = source_revision_identity(scope) if scope.sources else ()
    # Only improvements' document/photo classification reads ReportSources.
    # Other sections must not hash or retain unrelated source-page contents.
    page_sources = scope.sources if any(block.key == "improvements" for block in scope.blocks) else ()
    key = (
        draft.profile, draft.period.key, section_key, section, scope.blocks,
        page_sources, scope.follow_ups, draft.address_line if section else "",
        draft.prepared_by if section is None else "",
        draft.synthetic if section is None else False, source_identity,
        source_revisions,
    )
    try:
        return _cached_section_fingerprint(*key)
    except TypeError:
        # Some migrated reports may carry legacy unhashable metadata in fields
        # that the v6 visible digest never serialized. Preserve their prior
        # preview behavior, but never retain that unsuitable cache key.
        return _cached_section_fingerprint.__wrapped__(*key)


@lru_cache(maxsize=32)
def _cached_section_fingerprint(profile, period_key, section_key, section, blocks,
                                page_sources, follow_ups, address, prepared_by,
                                synthetic, source_identity, source_revisions):
    """Keep at most 32 immutable section revisions; never cache rendered output.

    All inputs are frozen model values or strings. The cache only avoids a
    repeat JSON walk/hash: it grants no approval and cannot affect final DOCX.
    """
    from app.monthly_report_asset_layout import document_page_indexes
    serialized_blocks = []
    for block in blocks:
        if block.source == "Omit":
            # Keep explicit omission of a divider, which overrides its design.
            serialized_blocks.append({"key": block.key, "source": "Omit"})
            continue
        serialized_blocks.append({name: getattr(block, name) for name in (
            "key", "text", "rows", "asset_hashes", "asset_captions", "photos_per_page", "references",
        )} | {"org_nodes": [asdict(node) for node in block.org_nodes],
             "extra_tables": [asdict(table) for table in block.extra_tables],
             "document_pages": sorted(document_page_indexes(block, page_sources))})
    from app.monthly_report_followups import report_text
    value = {
        "version": 6,
        "period": period_key,
        "title": profile.title,
        "contract": profile.contract,
        "profile": profile.key,
        "section": asdict(section) if section else "cover",
        "blocks": serialized_blocks,
        "address": address,
        "follow_ups": [report_text(item) for item in follow_ups if item.included],
    }
    from app.monthly_report_designs import fingerprint
    value["native_layout"] = fingerprint(profile)
    # Replacing one immutable source with new bytes under the same filename
    # must invalidate page images and the "Current" label. A page selection
    # alone can have unchanged references/geometry after that replacement.
    if source_revisions:
        value["source_revisions"] = source_revisions
    if source_identity:
        value["source_view"] = source_identity
    if section is None:
        value["cover"] = {"title": profile.title, "period": period_key,
                          "prepared_by": prepared_by, "synthetic": synthetic,
                          "facilities": [facility.title for facility in profile.facilities]}
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


@measured("section_docx_assembly")
def section_preview_docx(draft, section_key, asset_loader=None, *, source_view=None):
    """Private unfinished preview input, never an approved client download."""
    from app.monthly_report_source_view_runtime import render_operation
    scope, _ = _section_scope(draft, section_key)
    with render_operation(scope, source_view, section_key=section_key) as operation:
        return _section_preview_docx(draft, section_key, asset_loader, source_view=operation.view)


def _section_preview_docx(draft, section_key, asset_loader=None, *, source_view=None):
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
        from app import monthly_report_section_assembly_cache as assembly_cache
        revision = None
        if assembly_cache.active():
            # Preflight and pinned-source validation still run on every request.
            # The native assembler receives this exact scoped draft. Avoid a
            # full-report serialization when only an unrelated section changed:
            # identical bytes are reused, while report period, operator, design
            # pin, source view and section dependencies stay in its digest.
            # Unsaved asset bytes remain owner-scope-bound.
            from app.monthly_report_source_view_runtime import cache_identity
            revision = (scope.fingerprint, section_key, cache_identity(draft))
            cached = assembly_cache.read(revision)
            if cached is not None:
                return cached
        raw = build_native_docx(scope, source, asset_loader=asset_loader,
                                section_key=section_key, master=is_master(draft.profile),
                                source_view=source_view)
        if revision is not None:
            assembly_cache.remember(revision, raw)
        return raw

    if source_view is not None:
        raise ValueError('A compatibility source view requires its pinned original native design.')
    logo_assets = {ref for block in scope.blocks if block.key in ('brand_logo', 'client_logo')
                   for ref in block.asset_hashes}

    @lru_cache(maxsize=12)
    def image_asset(ref):
        if asset_loader is None:
            raise ValueError("The saved picture is not available for this preview.")
        return normalize_report_image(
            asset_loader(ref), Path(ref).suffix, line_art=True, dpi=150,
            preserve_transparency=ref in logo_assets,
        ).data

    raw = _build_docx(scope, asset_loader=image_asset if asset_loader else None)
    index = next((n for n, value in enumerate(scope.sections) if value.key == section_key), 0)
    return _slice_document_sections(raw, 2 + 2 * index if section else 0, 2 if section else 1)


@measured("section_preview_total_including_queue")
def preview_section(draft, section_key, asset_loader=None, *, source_view=None,
                    owner=None, revision=None, is_current=None):
    """High-quality, section-only preview with cancellable waiting admission."""
    admission = ({'owner': owner, 'revision': revision, 'is_current': is_current}
                 if owner is not None else {})
    with monthly_render_jobs.work_slot(preview=True, **admission):
        return _preview_section(draft, section_key, asset_loader, source_view=source_view)


def _preview_section(draft, section_key, asset_loader=None, *, source_view=None):
    from app.monthly_report_source_view_runtime import render_operation
    scope, _ = _section_scope(draft, section_key)
    with render_operation(scope, source_view, section_key=section_key) as operation:
        fingerprint = section_preview_fingerprint(draft, section_key)
        result = _preview_verified_section(draft, section_key, asset_loader,
                                           source_view=operation.view, fingerprint=fingerprint)
        if section_preview_fingerprint(draft, section_key) != fingerprint:
            raise ValueError('The source-view preview evidence changed during conversion; no output was published.')
        return result


def _preview_verified_section(draft, section_key, asset_loader=None, *, source_view=None, fingerprint):
    raw = section_preview_docx(draft, section_key, asset_loader, source_view=source_view)
    stem = "section-preview-" + uuid4().hex
    expected = pdf_converter.OUTPUT_DIR / (stem + ".pdf")
    actual = None
    try:
        with tempfile.TemporaryDirectory(prefix="monthly-section-preview-") as directory:
            path = Path(directory) / (stem + ".docx")
            from app.monthly_report_designs import render_profile_for
            render_profile = render_profile_for(draft.profile)
            if section_key != "cover":
                render_profile = {**render_profile, "cover_zero_origin": False}
                if "cover_metrics" in render_profile:
                    render_profile["cover_metrics"] = []
            compatible = rendering_docx(raw, profile=render_profile)
            del raw
            from app.monthly_report_preview_images import write_preview_docx
            write_preview_docx(compatible, path)
            del compatible
            with phase("section_pdf_conversion"):
                actual = monthly_render_jobs.convert_to_pdf(path, wait_seconds=0)
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
                _, section = _section_scope(draft, section_key)
                return ReportPreview(result, len(pdf), fingerprint,
                                     draft.period.label, section_initial_page(pdf, section))
    finally:
        for path in {actual, expected} - {None}:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def render_preview(draft, assets, prefix, field):
    import streamlit as st

    with st.expander("Preview the report at any time"):
        from app.monthly_report_source_view_runtime import preview_fingerprint
        current_fingerprint = preview_fingerprint(draft)
        st.caption(
            "A low-resolution, watermarked PDF helps you check the whole layout while work is unfinished. It does not approve content or replace the final review."
        )
        key = prefix + "_preview_pdf"
        preview = st.session_state.get(key)
        if preview and preview.fingerprint != current_fingerprint:
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
            stale = preview.fingerprint != current_fingerprint
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
