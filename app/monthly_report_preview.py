"""Low-resolution, watermarked preview; finished downloads keep strict gates."""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import tempfile
from uuid import uuid4

import fitz
from PIL import Image

from app import monthly_report_library as library, pdf_converter
from app.monthly_report_checks import preflight
from app.monthly_report_docx import _build_docx, normalize_report_image


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


def preview_page(preview, index):
    with fitz.open(stream=preview.pdf, filetype="pdf") as pdf:
        if not 0 <= index < len(pdf):
            raise ValueError("Choose an existing preview page.")
        return (
            pdf[index].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False).tobytes("png")
        )


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
