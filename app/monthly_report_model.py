"""Immutable report definitions, shared by the editor, checks and renderer.

Profiles describe scope explicitly: a regional title is not a facility, and a
facility alias must never become a second member of a report. Synthetic builders
are regression fixtures only; the application uses saved real-report profiles.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Literal


BlockType = Literal[
    "image_page", "image_grid", "pdf_pages", "rich_text", "table",
    "stock_text", "work_order_grid",
]
BLOCK_SOURCES = (
    "Library", "Last month", "This month", "Replace once",
    "Replace and save to library", "Stock text", "Omit",
)
COVER_ASSET_KEYS = ("brand_logo", "client_logo", "cover_photo")


@dataclass(frozen=True)
class Facility:
    key: str
    title: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.title.strip():
            raise ValueError("Facility identity and title are required")


@dataclass(frozen=True)
class ReportProfile:
    contract: str
    key: str
    title: str
    facilities: tuple[Facility, ...]
    scope_type: Literal["individual", "multi_site", "regional"] = "individual"
    section_order: tuple[str, ...] = ()
    default_block_sources: tuple[tuple[str, str], ...] = ()
    template: str = "monthly_review_v1"
    excluded_sections: tuple[str, ...] = ()
    # Imported tables keep their actual schema instead of dropping extra cells.
    block_overrides: tuple[BlockSpec, ...] = ()
    section_titles: tuple[tuple[str, str], ...] = ()
    section_block_order: tuple[tuple[str, tuple[str, ...]], ...] = ()
    imported_from: str = ""

    def __post_init__(self) -> None:
        if self.scope_type not in ("individual", "multi_site", "regional"):
            raise ValueError("Unknown profile scope")
        if not self.facilities or len({f.key for f in self.facilities}) != len(self.facilities):
            raise ValueError("A profile needs unique facility identities")
        if self.scope_type == "individual" and len(self.facilities) != 1:
            raise ValueError("An individual report covers exactly one facility")
        identities = {}
        for facility in self.facilities:
            for name in (facility.title, *facility.aliases):
                normalized = " ".join(name.casefold().split())
                if normalized in identities and identities[normalized] != facility.key:
                    raise ValueError("A facility alias cannot identify two different facilities")
                if normalized:
                    identities[normalized] = facility.key


@dataclass(frozen=True)
class ReportPeriod:
    year: int
    month: int

    def __post_init__(self) -> None:
        date(self.year, self.month, 1)

    @classmethod
    def previous(cls, today: date) -> ReportPeriod:
        return cls(today.year - 1, 12) if today.month == 1 else cls(today.year, today.month - 1)

    @property
    def start(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def label(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    title: str
    type: Literal["text", "date", "number", "currency", "boolean"] = "text"


@dataclass(frozen=True)
class BlockSpec:
    key: str
    type: BlockType
    required: bool = False
    allowed_sources: tuple[str, ...] = BLOCK_SOURCES
    stock_text_keys: tuple[str, ...] = ()
    columns: tuple[ColumnSpec, ...] = ()


@dataclass(frozen=True)
class SectionSpec:
    key: str
    number: str
    title: str
    blocks: tuple[BlockSpec, ...]
    divider_asset: str = ""
    included: bool = True
    appendix: bool = False


@dataclass(frozen=True)
class ReportTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    reference: str = ""


@dataclass(frozen=True)
class OrgChartNode:
    key: str
    name: str = ""
    role: str = ""
    reports_to: str = ""
    team: str = ""


@dataclass(frozen=True)
class ResolvedBlock:
    key: str
    source: str
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    asset_hashes: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    ai_written: bool = False
    reviewed_fingerprint: str = ""
    pending_library_save: bool = False
    asset_captions: tuple[str, ...] = ()
    extra_tables: tuple[ReportTable, ...] = ()
    client_reviewed_fingerprint: str = ""
    org_nodes: tuple[OrgChartNode, ...] = ()
    photos_per_page: int = 1

    @property
    def fingerprint(self) -> str:
        # Review is evidence-specific, not a sticky boolean. New sources must
        # invalidate it even if the visible paragraph happens to be unchanged.
        return _digest(replace(self, reviewed_fingerprint="", client_reviewed_fingerprint=""))

    @property
    def reviewed(self) -> bool:
        return not self.ai_written or self.reviewed_fingerprint == self.fingerprint


@dataclass(frozen=True)
class ReportSource:
    id: str
    filename: str
    sha256: str
    suffix: str
    classification: str = "Reference only"
    confidence: str = "low"
    vendor: str = ""
    service_date: str = ""
    facility: str = ""
    tags: tuple[str, ...] = ()
    work_order: str = ""
    actions: str = ""
    findings: str = ""
    recommendations: str = ""
    follow_ups: str = ""
    quotes: str = ""
    out_of_limit: str = ""
    page_texts: tuple[str, ...] = ()
    selected_pages: tuple[int, ...] = ()
    needs_vision: tuple[int, ...] = ()
    captions: tuple[tuple[int, str], ...] = ()
    notices: tuple[str, ...] = ()
    client_page_reviews: tuple[tuple[int, str], ...] = ()

    @property
    def fingerprint(self) -> str:
        return _digest(self)


@dataclass(frozen=True)
class ReportDraft:
    profile: ReportProfile
    period: ReportPeriod
    prepared_by: str
    sections: tuple[SectionSpec, ...]
    blocks: tuple[ResolvedBlock, ...]
    address_line: str = ""
    synthetic: bool = False
    sources: tuple[ReportSource, ...] = ()

    @property
    def fingerprint(self) -> str:
        return _digest(self)


@dataclass(frozen=True)
class ReportSnapshot:
    profile: ReportProfile
    month: ReportPeriod
    resolved_blocks: tuple[ResolvedBlock, ...]
    open_issues: tuple[str, ...]
    pending_proposals: tuple[str, ...]
    generated_at: str


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(asdict(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


STOCK_TEXTS = {
    "cmms_pending": "FacilityOne transition: work-order reporting is pending. Verified monthly counts have not been supplied.",
    "utility_pending": "Utility-rate analysis is pending M&V approval.",
    "mbcx_pending": "ENFRA Connect monitoring-based commissioning reporting is pending implementation.",
    "no_capital": "No Priority Zero recommendations this month.",
    "no_training_hours": "Training hours not provided.",
}

PLACEHOLDER_PHRASES = (
    "should include", "Example:", "Author: Name", "Insert image", "Month Year",
    "X Hours", "CM/PM Pics", "Lunch/Learn", "Team Pics",
)


def default_sections() -> tuple[SectionSpec, ...]:
    """The complete skeleton; library profiles only override these definitions."""
    return (
        SectionSpec("organization", "1", "Organizational Chart", (
            BlockSpec("org_chart", "image_page", True),
            BlockSpec("business_hours_workflow", "image_page"),
            BlockSpec("after_hours_workflow", "image_page"),
            BlockSpec("contact_matrix", "image_page"),
        )),
        SectionSpec("activity", "2", "Monthly Activity Summary", (
            BlockSpec("work_orders", "work_order_grid", stock_text_keys=("cmms_pending",)),
            BlockSpec("activity_summary", "rich_text", True),
            BlockSpec("improvements", "image_grid"),
        )),
        SectionSpec("scorecards", "3", "Monthly Scorecards", (
            BlockSpec("utility_analysis", "stock_text", stock_text_keys=("utility_pending",)),
            BlockSpec("thermal_capacity", "table", columns=(ColumnSpec("facility", "Facility"), ColumnSpec("service", "Service"), ColumnSpec("capacity", "Capacity", "number"), ColumnSpec("units", "Units"))),
        )),
        SectionSpec("mbcx", "4", "MBCx Reports", (
            BlockSpec("mbcx_report", "pdf_pages", stock_text_keys=("mbcx_pending",)),
        )),
        SectionSpec("maintenance", "5", "Maintenance Schedule / In-House Maintenance", (
            BlockSpec("service_calls", "table", stock_text_keys=("cmms_pending",), columns=(
                ColumnSpec("wo", "WO #"), ColumnSpec("finished", "Finish Date", "date"),
                ColumnSpec("area", "Area"), ColumnSpec("task", "Task Code-Description"),
                ColumnSpec("tag", "Tag #"),
            )), BlockSpec("vendor_reports", "pdf_pages"),
        )),
        SectionSpec("subcontractors", "6", "Sub-Contractor Status", (BlockSpec("subcontractor_matrix", "table", columns=(
            ColumnSpec("facility", "Facility"), ColumnSpec("discipline", "Discipline"), ColumnSpec("vendor", "Vendor"),
            ColumnSpec("contact", "Contact"), ColumnSpec("phone", "Phone"), ColumnSpec("msa", "MSA", "boolean"),
        )),)),
        SectionSpec("water", "7", "Water Treatment Reports", (BlockSpec("water_reports", "pdf_pages"),)),
        SectionSpec("issues", "8", "Equipment Performance Issues", (BlockSpec("equipment_issues", "rich_text", True),)),
        SectionSpec("capital", "9", "Priority Capital Renewal List", (
            BlockSpec("capital_renewal", "table", stock_text_keys=("no_capital",), columns=(
                ColumnSpec("facility", "Facility"), ColumnSpec("priority", "Priority"), ColumnSpec("recommendation", "Recommendation"), ColumnSpec("cost", "Cost", "currency"),
            )),
            BlockSpec("end_of_life", "table", columns=(ColumnSpec("facility", "Facility"), ColumnSpec("asset", "Asset"), ColumnSpec("end_date", "End of useful life", "date"))),
        )),
        SectionSpec("proposals", "10", "Pending & Declined Proposals", (BlockSpec("proposals", "table", columns=(
            ColumnSpec("facility", "Facility"), ColumnSpec("vendor", "Vendor"), ColumnSpec("scope", "Scope"), ColumnSpec("amount", "Amount", "currency"), ColumnSpec("status", "Status"),
        )),)),
        SectionSpec("training", "11", "Training Summary", (BlockSpec("training_summary", "rich_text", True),)),
        SectionSpec("rfi", "G", "RFI Matrix", (BlockSpec("rfi_matrix", "table", columns=(ColumnSpec("facility", "Facility"), ColumnSpec("item", "Requested item"), ColumnSpec("complete", "Complete", "boolean"))),), included=False, appendix=True),
    )


def included_sections(sections: tuple[SectionSpec, ...]) -> tuple[SectionSpec, ...]:
    """Renumber ordinary sections in their actual order; preserve appendix IDs."""
    result = []
    number = 0
    for section in sections:
        if not section.included:
            continue
        if not section.appendix:
            number += 1
        result.append(replace(section, number=section.number if section.appendix else str(number)))
    return tuple(result)


def profile_sections(profile: ReportProfile) -> tuple[SectionSpec, ...]:
    """Resolve the saved design independently of last month's report content."""
    overrides, titles = {b.key: b for b in profile.block_overrides}, dict(profile.section_titles)
    block_orders = dict(profile.section_block_order)
    sections = {}
    for section in default_sections():
        blocks = {b.key: overrides.get(b.key, b) for b in section.blocks}
        order = block_orders.get(section.key, tuple(blocks))
        sections[section.key] = replace(section, title=titles.get(section.key, section.title),
                                        included=section.key not in profile.excluded_sections,
                                        blocks=tuple(blocks[k] for k in order))
    return tuple(sections[k] for k in profile.section_order or tuple(sections))


def layout_blocks() -> tuple[BlockSpec, ...]:
    """Layout assets use the same versioning and confirmation as section blocks."""
    return (tuple(BlockSpec(key, "image_page") for key in COVER_ASSET_KEYS)
            + (BlockSpec("footer_text", "rich_text"),)
            + tuple(BlockSpec("divider_" + s.key, "image_page") for s in default_sections()))


def used_block_keys(draft: ReportDraft) -> set[str]:
    return (set(COVER_ASSET_KEYS) | {"footer_text"}
            | {b.key for s in included_sections(draft.sections) for b in s.blocks}
            | {"divider_" + s.key for s in included_sections(draft.sections)})


def used_asset_references(draft: ReportDraft) -> set[str]:
    keys = used_block_keys(draft)
    return ({ref for b in draft.blocks if b.key in keys and b.source != "Omit" for ref in b.asset_hashes}
            | {s.divider_asset for s in included_sections(draft.sections) if s.divider_asset})


def report_filename(draft: ReportDraft, extension: Literal["docx", "pdf"]) -> str:
    title = f"{draft.profile.contract} - {draft.profile.title} {draft.period.label} Monthly Report"
    # A display name is never allowed to create a path or a response-header line.
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", title).strip(" .")
    return f"{title}.{extension}"


def synthetic_profiles() -> tuple[ReportProfile, ...]:
    north = Facility("north", "Demonstration North Facility", ("Demo North",))
    south = Facility("south", "Demonstration South Facility", ("Demo South",))
    return (
        ReportProfile("Demonstration", "individual", "Demonstration Individual Facility", (north,)),
        ReportProfile("Demonstration", "multi_site", "Demonstration Two-Site Group", (north, south), "multi_site"),
        ReportProfile("Demonstration", "regional", "Demonstration Region", (north, south), "regional"),
    )


def synthetic_draft(profile: ReportProfile, period: ReportPeriod) -> ReportDraft:
    # M1 deliberately has no client library. Its content blocks are explicitly
    # marked demo text instead of pretending missing charts/reports are resolved.
    stocks = {"scorecards": "utility_pending", "mbcx": "mbcx_pending", "training": "no_training_hours"}
    sections = tuple(replace(s, blocks=(BlockSpec(
        f"demo_{s.key}", "stock_text" if s.key in stocks else "rich_text", True,
    ),)) for s in default_sections())
    blocks = tuple(ResolvedBlock(s.blocks[0].key, "Stock text" if s.key in stocks else "This month", text=(
        f"Synthetic demonstration — {s.title}. No client information is included. "
        + (STOCK_TEXTS[stocks[s.key]] if s.key in stocks else "This section demonstrates the report layout.")
    )) for s in sections)
    return ReportDraft(profile, period, "ENFRA Asset Management Team", sections, blocks, synthetic=True)
