"""Route-specific upload hints without changing widget keys or file decisions."""
from app.monthly_report_upload_limits import byte_limit_label, docx_parser_help, uploader_limit_mib


def _docx_help():
    from app import monthly_report_import as docx
    return docx_parser_help(expanded=docx.MAX_EXPANDED_BYTES, member=docx.MAX_MEMBER_BYTES,
                            xml_part=docx.MAX_XML_BYTES, xml_total=docx.MAX_XML_TOTAL,
                            images=docx.MAX_NORMALIZED_BYTES)


def starting_upload_options():
    from app import monthly_report_import as docx
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
    return {
        "max_upload_size": uploader_limit_mib(docx.MAX_DOCX_BYTES),
        "help": (f"DOCX: up to {byte_limit_label(docx.MAX_DOCX_BYTES)}. "
                 f"Automatic Word-artwork interpretation: up to {byte_limit_label(MAX_VIEW_SOURCE_BYTES)}. "
                 "Larger artwork sources may need an available ENFRA template or an existing cover design. "
                 + _docx_help()),
    }


def evidence_limits_summary():
    from app import monthly_report_sources as sources
    return (
        f"DOCX: up to {byte_limit_label(sources.file_size_limit('.docx'))}. "
        f"Other supported files: up to {byte_limit_label(sources.MAX_FILE_BYTES)}. "
        f"Per report: {sources.MAX_SOURCES:,} sources / {byte_limit_label(sources.MAX_REPORT_BYTES)} "
        f"including attachments; {sources.MAX_REPORT_TEXT:,} extracted characters; "
        f"{sources.MAX_EMBED_PAGES:,} embedded pages and {sources.MAX_VISION_PAGES:,} OCR/vision pages."
    )


def evidence_upload_options():
    from app import monthly_report_sources as sources
    return {
        "max_upload_size": uploader_limit_mib(max(sources.file_size_limit(suffix) for suffix in sources.SUPPORTED)),
        "help": (evidence_limits_summary() + " "
                 f"PDF: at most {sources.MAX_PAGES:,} pages. Each file: at most {sources.ocr._MAX_EXTRACTED_CHARS:,} extracted characters. "
                 f"XLSX: {byte_limit_label(sources.MAX_WORKBOOK_BYTES)} expanded, "
                 f"{byte_limit_label(sources.MAX_WORKBOOK_PART_BYTES)} per part, {sources.MAX_WORKSHEETS:,} worksheets. "
                 + _docx_help()),
    }


def capacity_upload_options():
    from app import monthly_report_capacity as capacity, monthly_report_directory as directory
    from app import monthly_report_sources as sources
    return {
        "max_upload_size": uploader_limit_mib(max(capacity.file_size_limit(suffix) for suffix in capacity.SUPPORTED)),
        "help": (
            f"DOCX: up to {byte_limit_label(capacity.file_size_limit('.docx'))}. "
            f"XLSX: up to {byte_limit_label(capacity.file_size_limit('.xlsx'))}. "
            f"Other supported files: up to {byte_limit_label(sources.MAX_FILE_BYTES)}. "
            f"Capacity review: {capacity.MAX_INPUT_ITEMS:,} extracted pages/items, {capacity.MAX_TABLES:,} tables, "
            f"{capacity.MAX_ROWS:,} rows and {capacity.MAX_CELLS:,} cells. "
            f"XLSX parsing: {byte_limit_label(directory.MAX_EXPANDED_BYTES)} expanded and "
            f"{byte_limit_label(directory.MAX_PART_BYTES)} per part. "
            "Use only capacity content for the relevant sites. " + _docx_help()
        ),
    }
