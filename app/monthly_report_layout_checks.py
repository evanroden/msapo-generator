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
            if block.org_nodes:
                problem = org_chart_problem(block.org_nodes)
                if problem:
                    checks.append(ReportCheck("org_chart", problem, True, block.key))
            elif spec.type == "image_grid" and block.asset_hashes:
                if photo_pages is None:
                    photo_pages = _renders_photo_pages(draft.profile)
                if photo_pages:
                    for index in photo_caption_problems(block):
                        checks.append(ReportCheck(
                            "photo_caption",
                            f"Shorten photo caption {index + 1} in {_label(spec.key)}, or choose fewer "
                            f"photos per page. At {block.photos_per_page} per page a caption can use "
                            "at most four lines.", True, block.key))
            if spec.columns and any(len(row) > len(spec.columns) for row in block.rows):
                checks.append(ReportCheck(
                    "table_columns",
                    f"A row in {_label(spec.key)} has more cells than its {len(spec.columns)} columns. "
                    "Remove the extra cells or move them into the right column.", True, block.key))
            for table in block.extra_tables:
                # Blank added tables are skipped by the renderer; never block them.
                filled = any(cell is not None and str(cell).strip() for row in table.rows for cell in row)
                if filled and table.columns and any(len(row) > len(table.columns) for row in table.rows):
                    checks.append(ReportCheck(
                        "table_columns",
                        f"A row in an added table in {_label(spec.key)} has more cells than its "
                        f"{len(table.columns)} columns. Remove the extra cells or add the missing column.",
                        True, block.key))
    return checks
