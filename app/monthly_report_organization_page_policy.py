"""Output-only page policy for approved organization diagrams and contacts.

Inputs are exact current-report output nodes, never source guesses. This module
does not touch a library/default, re-encode pictures or rewrite contact data.
"""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_table_pagination import keep_current_header_with_rows


_DIAGRAM_LABELS = {
    "org_chart": "Organization chart for this report",
    "business_hours_workflow": "Business-hours workflow diagram for this contract",
    "after_hours_workflow": "After-hours workflow diagram for this contract",
}
_CHART_TITLES = {
    "organizational chart", "organization chart", "organization and reporting lines",
}


def label_current_diagram(root, key):
    """Add safe alt text after previous-client drawing metadata was removed.

    The pixels, reference and image-part identity are never changed. Descriptions
    cannot import unreviewed source contact information or an old client's title.
    """
    if root is None or (label := _DIAGRAM_LABELS.get(key)) is None:
        return
    for kind in ("wp:docPr", "pic:cNvPr"):
        for node in root.iter(qn(kind)):
            node.set("descr", label)
            node.set("title", label)


def repeat_current_contact_headers(table):
    """Repeat a proven current contact table's heading, even if source-bound.

    Only the caller's exact current contact tables qualify. A zero-row or
    header-only table is not inflated with an invented person.
    """
    if (table is not None and table.tag == qn("w:tbl")
            and len(table.findall(qn("w:tr"))) > 1):
        keep_current_header_with_rows(table, keep_all_rows_intact=True)


def _plain_text(node):
    return "".join(item.text or "" for item in node.iter(qn("w:t"))).strip().casefold()


def _is_page_boundary(node):
    if node.tag == qn("w:sectPr") or any(True for _ in node.iter(qn("w:sectPr"))):
        return True
    if any(br.get(qn("w:type")) == "page" for br in node.iter(qn("w:br"))):
        return True
    return any(flag.get(qn("w:val"), "1").casefold() not in {"0", "false", "off"}
               for flag in node.iter(qn("w:pageBreakBefore")))


def _ensure_page_start(body, root, *, title_words=(), force=False):
    if root is None or root.getparent() is not body:
        return
    anchor = root
    previous = root.getprevious()
    if (previous is not None and previous.tag == qn("w:p")
            and _plain_text(previous) in title_words):
        anchor = previous  # Move a recognized title with its diagram.
    if _is_page_boundary(anchor):
        return
    previous = anchor.getprevious()
    while previous is not None and not force:
        # Native section breaks and existing authored page breaks already
        # give the chart its own page; do not create a blank intermediate page.
        if _is_page_boundary(previous):
            return
        if (previous.tag == qn("w:tbl") or _plain_text(previous)
                or any(previous.iter(qn("a:blip")))):
            break
        previous = previous.getprevious()
    if previous is None and not force:
        return
    if anchor.tag == qn("w:p"):
        properties = anchor.get_or_add_pPr()
        flag = properties.find(qn("w:pageBreakBefore"))
        if flag is None:
            flag = OxmlElement("w:pageBreakBefore")
            properties.append(flag)
        flag.attrib.pop(qn("w:val"), None)
    else:
        # A diagram inside a table cannot carry paragraph pageBreakBefore.
        # The new separator is part of the output copy only, not its original.
        paragraph, properties = OxmlElement("w:p"), OxmlElement("w:pPr")
        properties.append(OxmlElement("w:pageBreakBefore"))
        paragraph.append(properties)
        anchor.addprevious(paragraph)


def separate_current_diagrams(body, chart_roots, workflow_roots):
    """Start charts and their following workflows cleanly without rearranging content.

    Existing native source page boundaries and intentional later slide-pair
    placement are preserved; only the first page start is normalized.
    """
    nodes = list(body)
    charts = [node for node in chart_roots if node.getparent() is body]
    workflows = [node for node in workflow_roots if node.getparent() is body]
    if not charts:
        return
    first_chart = min(charts, key=nodes.index)
    _ensure_page_start(body, first_chart, title_words=_CHART_TITLES)
    nodes = list(body)
    last_chart = max(charts, key=nodes.index)
    following = [node for node in workflows if nodes.index(node) > nodes.index(last_chart)]
    if not following:
        return
    first = min(following, key=nodes.index)
    between = nodes[nodes.index(last_chart) + 1:nodes.index(first)]
    if not any(_is_page_boundary(node) for node in between):
        _ensure_page_start(body, first, title_words=(
            "business hours workflow", "business-hours workflow",
            "after hours workflow", "after-hours workflow",
            "workflow diagram", "outage workflow",
        ), force=True)
