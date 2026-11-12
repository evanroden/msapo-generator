"""Opt-in, renderer-neutral section decisions and scoped report pages.

This module intentionally has no Streamlit widgets or persistent side effects.
The existing profile manifest holds standing exclusions; the existing report
snapshot holds report-only included flags and every retained content block.
Native master pages require a separate, reviewed assembly integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Mapping

from app.monthly_report_content_policy import contains_price
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportProfile, ResolvedBlock, SectionSpec,
    included_sections, profile_sections,
)

_PAGE_SLUG = re.compile(r"[a-z][a-z0-9_]{0,49}\Z")
_CUSTOM_KEY = re.compile(r"custom_([a-z][a-z0-9_]{0,49})_([0-9a-f]{16})\Z")


def _validated_decisions(available: set[str], decisions: Mapping[str, bool]) -> dict[str, bool]:
    if not isinstance(decisions, Mapping):
        raise ValueError("Section choices must be keyed by section identity.")
    changes = dict(decisions)
    if any(not isinstance(key, str) or key not in available for key in changes):
        raise ValueError("Unknown section choice; review the report design before changing it.")
    if any(type(value) is not bool for value in changes.values()):
        raise ValueError("A section choice must be explicitly on or off.")
    return changes


def report_only_sections(draft: ReportDraft, changes: Mapping[str, bool]) -> ReportDraft:
    """Apply a report-only choice; do not rewrite the contract's saved defaults.

    Suppressed sections and blocks remain present in the draft and its history.
    Renderers use included_sections() for display numbers and output ordering.
    """
    available = {section.key for section in draft.sections}
    decisions = _validated_decisions(available, changes)
    return replace(draft, sections=tuple(
        replace(section, included=decisions.get(section.key, section.included))
        for section in draft.sections
    ))


def standing_sections(profile: ReportProfile, changes: Mapping[str, bool]) -> ReportProfile:
    """Build a candidate standing preference for the EXISTING revisioned save path.

    This function never saves anything. The caller must use save_profile with
    explicit shared-change confirmation and compare-and-swap revision.
    """
    available = {section.key for section in profile_sections(profile)}
    decisions = _validated_decisions(available, changes)
    excluded = set(profile.excluded_sections)
    for key, enabled in decisions.items():
        if enabled:
            excluded.discard(key)
        else:
            excluded.add(key)
    # Keep original ordering of untouched (even historic) exclusions.
    ordered = tuple(dict.fromkeys((*profile.excluded_sections, *decisions)))
    return replace(profile, excluded_sections=tuple(key for key in ordered if key in excluded))


def visible_outline(draft: ReportDraft) -> tuple[tuple[str, str, str], ...]:
    """The same included/renumbered model used by DOCX navigation and the TOC."""
    return tuple((section.key, section.number, section.title)
                 for section in included_sections(draft.sections))


@dataclass(frozen=True)
class ContractPage:
    """An identity-bound editable text page, with no monetary-output exception."""
    contract: str
    profile_key: str
    facility_keys: tuple[str, ...]
    slug: str
    title: str

    def __post_init__(self) -> None:
        if not self.contract.strip() or not self.profile_key.strip():
            raise ValueError("A custom page needs its exact contract and profile.")
        if not self.facility_keys or len(set(self.facility_keys)) != len(self.facility_keys):
            raise ValueError("A custom page needs unique site identities.")
        if any(not isinstance(site, str) or not site.strip() for site in self.facility_keys):
            raise ValueError("Invalid custom-page site.")
        if not _PAGE_SLUG.fullmatch(self.slug):
            raise ValueError("Invalid custom-page key.")
        if not self.title.strip() or len(self.title) > 160:
            raise ValueError("A custom page needs a short title.")

    @classmethod
    def for_report(cls, draft: ReportDraft, slug: str, title: str) -> ContractPage:
        return cls(draft.profile.contract, draft.profile.key,
                   tuple(sorted(site.key for site in draft.profile.facilities)), slug, title)

    @property
    def key(self) -> str:
        scope = json.dumps(
            (self.contract, self.profile_key, tuple(sorted(self.facility_keys)), self.slug),
            separators=(",", ":"), ensure_ascii=False,
        )
        return "custom_" + self.slug + "_" + sha256(scope.encode("utf-8")).hexdigest()[:16]

    @property
    def block_key(self) -> str:
        return self.key + "_content"

    def matches(self, draft: ReportDraft) -> bool:
        return (self.contract == draft.profile.contract
                and self.profile_key == draft.profile.key
                and tuple(sorted(self.facility_keys))
                == tuple(sorted(site.key for site in draft.profile.facilities)))


def _check_native(draft: ReportDraft) -> None:
    # A pinned Word design cannot acquire a real new page by inventing a
    # SectionSpec; the native layout must be extended and checked separately.
    if draft.profile.imported_from or draft.profile.template != "monthly_review_v1":
        raise ValueError("Pinned native designs require reviewed custom-page placement.")


def install_text_page(draft: ReportDraft, page: ContractPage,
                      content: ResolvedBlock) -> ReportDraft:
    """Add an editable, nonfinancial page to an unpinned generic report.

    Do not treat a page title, checkbox or user-supplied source classification
    as proof that client-facing amounts are eligible. Monetary and visual
    material must use the separately verified field/page policy, not this path.
    """
    if not page.matches(draft):
        raise ValueError("Custom page scope does not match this contract and site selection.")
    _check_native(draft)
    if content.key != page.block_key or content.source not in ("This month", "Last month", "Replace once", "Omit"):
        raise ValueError("Custom page content identity or source is invalid.")
    if (content.rows or content.extra_tables or content.asset_hashes or content.org_nodes
            or content.asset_captions or contains_price(content.text)):
        raise ValueError("Use independently verified field/page review for monetary, table or image content.")
    if content.ai_written and not content.reviewed:
        raise ValueError("Review AI-generated content before adding a custom page.")
    if any(section.key == page.key for section in draft.sections):
        raise ValueError("This page already exists; edit its saved content rather than adding another copy.")
    if any(block.key == page.block_key for block in draft.blocks):
        raise ValueError("A custom-page block key already exists.")
    section = SectionSpec(page.key, "", page.title, (BlockSpec(page.block_key, "rich_text"),))
    index = next((i for i, item in enumerate(draft.sections) if item.appendix), len(draft.sections))
    return replace(draft, sections=(*draft.sections[:index], section, *draft.sections[index:]),
                   blocks=(*draft.blocks, content))


def verify_custom_page_scope(draft: ReportDraft) -> None:
    """Fail closed if a retained page is copied into another report identity.

    Call at both render/preflight and reload boundaries when integrating this
    module. No existing native renderer has been modified by this module.
    """
    seen = set()
    for section in draft.sections:
        if not section.key.startswith("custom_"):
            continue
        if section.key in seen:
            raise ValueError("Duplicate custom page identity.")
        seen.add(section.key)
        match = _CUSTOM_KEY.fullmatch(section.key)
        if match is None:
            raise ValueError("Custom page has an unknown scope marker.")
        page = ContractPage.for_report(draft, match.group(1), section.title)
        if page.key != section.key:
            raise ValueError("Custom page belongs to another contract or site selection.")
        if len(section.blocks) != 1 or section.blocks[0].key != page.block_key:
            raise ValueError("Custom page has unexpected content slots.")
        content = [block for block in draft.blocks if block.key == page.block_key]
        if len(content) != 1:
            raise ValueError("Custom page content was not preserved.")
        block = content[0]
        if (block.rows or block.extra_tables or block.asset_hashes or block.org_nodes
                or block.asset_captions or contains_price(block.text)):
            raise ValueError("Custom page needs field/page review for monetary, table or image content.")
        if block.ai_written and not block.reviewed:
            raise ValueError("Custom page AI content needs review.")
        if section.included:
            _check_native(draft)
