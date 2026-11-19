"""Ticket-only review PDF shortcut.

A private PreviewStore ticket is rasterized on demand before reaching the
browser. The downloadable legacy draft PDF MUST continue using the flattened,
low-resolution path in monthly_report_preview.preview_report.
"""

from app.monthly_report_preview_metrics import measured


@measured("private_ticket_stamp_all_pages")
def private_ticket_pdf(pdf, *, source_bytes, max_pages, max_bytes):
    """Stamp every converted page without an eager full-document raster.

    Returns None when an oversized source/output needs the legacy JPEG
    compression path. The caller owns and closes `pdf`; the conversion file on
    disk is never modified. Do not use this function for downloadable PDFs.
    """
    pages = len(pdf)
    if not 0 < pages <= max_pages:
        raise ValueError("Preview is limited to 150 pages. Preview fewer sections or reduce page selections.")
    if source_bytes > max_bytes:
        return None

    for page in pdf:
        point = (page.rect.width * 0.18, page.rect.height * 0.63)
        import pymupdf as fitz
        anchor = fitz.Point(*point)
        page.insert_text(
            anchor, "DRAFT - REVIEW ONLY", fontsize=32,
            color=(0.7, 0.08, 0.08), fill_opacity=0.4,
            morph=(anchor, fitz.Matrix(35)),
        )
        page.insert_text(
            (25, 22), "DRAFT PREVIEW - NOT A FINISHED CLIENT REPORT",
            fontsize=9, color=(0.65, 0.05, 0.05),
        )
    raw = pdf.tobytes(garbage=3, deflate=True)
    return raw if len(raw) <= max_bytes else None
