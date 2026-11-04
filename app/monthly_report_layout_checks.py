"""Renderer limits that preflight checks before Generate is offered (Refs #296).

The Word/PDF renderers refuse a chart with too much text for its pages, a photo
caption longer than its grid allows, and a table row with more cells than
columns. Without these checks Generate looked available and then failed with a
late "could not be loaded" message. Each check names the item and keys it to
the block whose editor fixes it. Blank optional content is never flagged.
"""
from app.monthly_report_model import included_sections


def _label(key):
    return key.replace("_", " ")


def _first_wide_row(rows, width):
    return next(((number, len(row)) for number, row in enumerate(rows, 1)
                 if len(row) > width), None)


def _renders_photo_pages(profile):
    """Photo grid pages are drawn only by the generic layout, not native designs."""
    from app.monthly_report_designs import source_for
    try:
        return source_for(profile) is None
    except (OSError, ValueError):
        return False  # the design error itself is reported when generating


def layout_checks(draft):
    from app.monthly_report_checks import ReportCheck
    from app.monthly_report_visuals import org_chart_problem, photo_caption_problems

    checks = []
    blocks = {block.key: block for block in draft.blocks}
    photo_pages = None
    for section in included_sections(draft.sections):
        for spec in section.blocks:
            block = blocks.get(spec.key)
            if block is None or block.source == "Omit":
                continue
            from app.monthly_report_asset_layout import document_page_indexes, document_caption_problems
            # Keep the existing single source of renderer-limit checks. Plain
            # photos need no standalone document-page caption measurement.
            document_captions = (document_caption_problems(block, draft.sources)
                                 if document_page_indexes(block, draft.sources) else ())
            for index in document_captions:
                checks.append(ReportCheck('document_caption',
                    f'Shorten the source-page caption for picture {index + 1} in {_label(spec.key)} to at most three lines before generating.',
                    True, block.key))
            if block.org_nodes:
                problem = org_chart_problem(block.org_nodes)
                if problem:
                    checks.append(ReportCheck("org_chart", problem, True, block.key))
            elif spec.type == "image_grid" and block.asset_hashes:
                if photo_pages is None:
                    photo_pages = _renders_photo_pages(draft.profile)
                if photo_pages and type(block.photos_per_page) is int and 1 <= block.photos_per_page <= 6:
                    from app.monthly_report_asset_layout import picture_runs, photo_run
                    problems = (indexes[local] for is_document, indexes in picture_runs(block, draft.sources)
                                if not is_document for local in photo_caption_problems(photo_run(block, indexes)))
                    for index in problems:
                        checks.append(ReportCheck(
                            "photo_caption",
                            f"Shorten photo caption {index + 1} in {_label(spec.key)}, or choose fewer "
                            f"photos per page. At {block.photos_per_page} per page a caption can use "
                            "at most four lines.", True, block.key))
            too_wide = _first_wide_row(block.rows, len(spec.columns)) if spec.columns else None
            if too_wide is not None:
                row_number, cells = too_wide
                checks.append(ReportCheck(
                    "table_columns",
                    f"Row {row_number} in {_label(spec.key)} has {cells} cells but only {len(spec.columns)} columns. "
                    "Remove the extra cells or move them into the right column.", True, block.key))
            for table_number, table in enumerate(block.extra_tables, 1):
                # Blank added tables are skipped by the renderer; never block them.
                filled = any(cell is not None and str(cell).strip() for row in table.rows for cell in row)
                if filled and not table.columns:
                    checks.append(ReportCheck(
                        "table_missing_columns",
                        f"Imported table {table_number} in {_label(spec.key)} "
                        "has source rows but no column headings. Add headings "
                        "or leave this table out before creating the report.",
                        True, block.key))
                too_wide = _first_wide_row(table.rows, len(table.columns)) if filled and table.columns else None
                if too_wide is not None:
                    row_number, cells = too_wide
                    checks.append(ReportCheck(
                        "table_columns",
                        f"Imported table {table_number}, row {row_number} in {_label(spec.key)} has {cells} cells but "
                        f"{len(table.columns)} columns. Remove the extra cells or add the missing column.",
                        True, block.key))
    return checks
