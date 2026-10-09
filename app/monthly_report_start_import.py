"""One starting report, with reuse decided from its content and site identity.

The cover supplies the original report period; dated current work takes
precedence when an old cover has not yet been updated. Unrelated sites
contribute design rather than contacts or activity. Omitted content remains
in the saved original document.
"""

import calendar
import re
from dataclasses import dataclass, replace

from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_import import MappedImport
from app.monthly_report_model import known_sections, layout_blocks
from app.monthly_report_sections import (
    build_section_import,
    default_slot,
    section_reviews,
    small_artwork,
    table_without_prices,
)
from app.monthly_report_setup import MONTHLY_BLOCKS


@dataclass(frozen=True)
class StartingReportAnalysis:
    source_sites: tuple
    site_relation: str
    current_items: tuple[str, ...]
    older_items: tuple[str, ...]
    uncertain_items: tuple[str, ...]
    source_period: tuple[int, int] | None = None


def _words(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _named_group(profile):
    """Only a distinctive multi-site group name is membership evidence.

    Report labels and contract names describe many sites. In particular a
    saved design called 'Monthly Report' must never identify an unknown site's
    report as the selected facility. Individual facilities must match their
    actual known names/aliases instead of a freely named report design.
    """
    if len(profile.facilities) < 2:
        return False
    boilerplate = {
        "a", "an", "the", "and", "for", "of", "at", "in", "to", "enfra", "bernhard",
        "monthly", "month", "report", "reports", "status", "progress", "update", "summary",
        "operations", "operation", "operational", "maintenance", "review", "management",
        "asset", "assets", "facility", "facilities", "site", "sites", "hospital", "hospitals",
        "individual", "multi", "multiple", "combined", "group", "region", "regional",
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        *_words(profile.contract).split(),
        "".join(word[0] for word in _words(profile.contract).split()),
        *(name.casefold() for name in calendar.month_name if name),
        *(name.casefold() for name in calendar.month_abbr if name),
    }
    return any(token.isalpha() and token not in boilerplate for token in _words(profile.title).split())


def source_sites(inspection, known_sites):
    """Match complete names/aliases on the cover, never incidental body names."""
    cover = " " + _words("\n".join(inspection.title_candidates)) + " "
    matches = []
    for site in known_sites:
        for name in (site.title, *site.aliases):
            term = _words(name)
            if term and " " + term + " " in cover:
                matches.append((site, term))
    # A short alias such as Unity must not manufacture a second site when the
    # document explicitly names Unity Specialty Hospital.
    return tuple({site.key: site for site, term in matches
                  if not any(other.key != site.key and term != longer
                             and " " + term + " " in " " + longer + " "
                             for other, longer in matches)}.values())


def mentioned_periods(text):
    """Dates with explicit years; undated words such as 'September' stay unknown."""
    periods = set()
    for month in range(1, 13):
        name = calendar.month_name[month]
        for match in re.finditer(rf"\b(?:{name}|{name[:3]}\.?)\s+(?:\d{{1,2}},?\s+)?(20\d{{2}})\b", text, re.IGNORECASE):
            periods.add((int(match[1]), month))
    for match in re.finditer(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])(?:[-/]\d{1,2})?\b", text):
        periods.add((int(match[1]), int(match[2])))
    for match in re.finditer(r"\b(0?[1-9]|1[0-2])/\d{1,2}/(20\d{2})\b", text):
        periods.add((int(match[2]), int(match[1])))
    return periods


def analyze_starting_report(inspection, profile, period, known_sites=(), *, confirmed_sites=None, known_profiles=()):
    known = {}
    # Existing target membership wins over a catalog's spelling/key for the
    # same named facility. A directory import must not turn a same-site report
    # into a different-site design just because it generated a longer slug.
    for site in (*profile.facilities, *known_sites):
        names = {_words(n) for n in (site.title, *site.aliases)}
        overlaps = [prior for prior in known.values()
                    if names.intersection(_words(n) for n in (prior.title, *prior.aliases))]
        if len(overlaps) == 1:
            prior = overlaps[0]
            known[prior.key] = replace(prior, aliases=tuple(dict.fromkeys((*prior.aliases, *(n for n in (site.title, *site.aliases) if n != prior.title)))))
        else:
            known.setdefault(site.key, site)
    sites = tuple(confirmed_sites) if confirmed_sites is not None else source_sites(inspection, known.values())
    if confirmed_sites is None:
        cover = " " + _words("\n".join(inspection.title_candidates)) + " "
        groups = [p for p in (*known_profiles, profile) if p.contract == profile.contract and _named_group(p)
                  and " " + _words(p.title) + " " in cover]
        memberships = {tuple(sorted(f.key for f in p.facilities)) for p in groups}
        if len(memberships) == 1:
            matched = groups[0].facilities
            # A known group name supplies its already confirmed membership.
            if not sites or {s.key for s in sites}.issubset({s.key for s in matched}):
                sites = matched
    target = {site.key for site in profile.facilities}
    relation = "same" if sites and {s.key for s in sites} == target else "other" if sites else "unknown"
    current, older, uncertain = [], [], []
    requested = (period.year, period.month)
    cover_periods = mentioned_periods("\n".join(inspection.title_candidates))
    source_period = next(iter(cover_periods)) if len(cover_periods) == 1 else None
    for item in inspection.items:
        if item.suggested_slot not in MONTHLY_BLOCKS:
            continue
        if item.kind == "image":
            uncertain.append(item.id)
            continue
        text = "\n".join((item.text, *(" ".join(row) for row in item.rows)))
        periods = mentioned_periods(text)
        if requested in periods:
            current.append(item.id)
        # Only standalone dated prose is safely left out automatically. Tables
        # can contain cumulative history; images cannot inherit a nearby date.
        elif item.kind == "text" and periods and all(p < requested for p in periods):
            older.append(item.id)
        else:
            uncertain.append(item.id)
    # A clearly older report supplies the design and standing information.
    # A stale cover on a partially updated report must not discard undated new
    # work, nor can it overrule a current date found inside the report body.
    if source_period and source_period < requested and not current:
        rollover = {i.id for i in inspection.items if i.suggested_slot in MONTHLY_BLOCKS
                    and i.kind in ("text", "image")}
        older = list(dict.fromkeys((*older, *sorted(rollover))))
        uncertain = [identity for identity in uncertain if identity not in rollover]
    return StartingReportAnalysis(sites, relation, tuple(current), tuple(older), tuple(uncertain), source_period)


def automatic_section_plans(inspection, analysis, *, preferred_logos=(), native_design=False):
    """Pre-fill recognizable content; ask only about unresolved source content.

    'approved' satisfies the existing import builder's structural validation.
    It does not mean the writer reviewed automatically routed pictures; that
    distinction is enforced by build_starting_import below.
    """
    known = {b.key for s in known_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    result = {}
    for section in section_reviews(inspection):
        plan = {"key": section.key, "action": "Keep and review", "target": section.key,
                "omit": False, "selected": [], "texts": {}, "tables": {}, "destinations": {},
                "new_assets": [], "image_notes": {}, "automatic": True, "approved": True}
        if analysis.site_relation != "same":
            plan["unsupported_reviewed"] = True
        questions = []
        for item in section.items:
            slot = item.suggested_slot
            if native_design and slot.startswith("divider_"):
                continue  # The pinned native master owns its page art, not monthly content.
            design = slot in ("brand_logo", "client_logo") or slot.startswith("divider_")
            if analysis.site_relation != "same" and not design:
                # Different sites may reuse table headings, never their rows.
                if item.kind == "table" and section.key not in ("cover", "other"):
                    table, _ = table_without_prices(item)
                    if table:
                        plan["selected"].append(item.id)
                        plan["tables"][item.id] = replace(table, rows=())
                continue
            if item.id in analysis.older_items or slot in preferred_logos:
                continue
            if section.key == "cover" and item.kind == "text" and slot != "footer_text":
                continue  # The target report already supplies its cover title/date.
            if item.kind == "unsupported":
                questions.append("Some Word artwork needs its complete page preserved.")
                continue
            if section.key == "other":
                questions.append("Choose where the additional content belongs.")
                continue
            if item.kind == "image":
                if small_artwork(item):
                    continue
                if not slot or (slot in ("cover_photo", "brand_logo", "client_logo")
                                and sum(i.kind == "image" and i.suggested_slot == slot for i in section.items) > 1):
                    questions.append("A picture's purpose is not clear.")
                    continue
            if item.kind == "text" and contains_price(item.text):
                questions.append("Remove pricing from the report text.")
                continue
            if item.kind == "table":
                table, _ = table_without_prices(item)
                if not table:
                    continue
                if table_has_pricing(table.columns, table.rows):
                    questions.append("Check this table's pricing or column headings.")
                    continue
                plan["tables"][item.id] = table
            if slot not in known:
                slot = default_slot(section.key)
            plan["selected"].append(item.id)
            plan["destinations"][item.id] = slot
            if item.kind == "text":
                plan["texts"][item.id] = item.text
        plan["questions"] = tuple(dict.fromkeys(questions))
        plan["approved"] = not questions
        result[section.key] = plan
    return result


def build_starting_import(path, inspection, plans):
    """Build auto-routed content without forging a human picture approval."""
    plans = tuple(plans)
    if not all(p.get("approved") for p in plans):
        raise ValueError("Resolve the remaining starting-report questions before continuing.")
    if not any(p.get("selected") or p.get("new_assets") or p.get("preserved_assets") for p in plans):
        return MappedImport((), (), (), ()), ()
    # Unrelated/old sections intentionally carry no data. The original keeps
    # their unsupported objects, but they are not new target-site exceptions.
    active = tuple(p for p in plans if p.get("selected") or p.get("new_assets") or p.get("preserved_assets"))
    mapped, mappings = build_section_import(path, inspection, active)
    automatic_refs = {f"docx:{inspection.sha256}:{identity}" for p in active if p.get("automatic")
                      for identity in p.get("selected", ())}
    from app.monthly_report_asset_review import (
        asset_fingerprint,
        normalize_asset_reviews,
    )
    blocks = []
    for block in mapped.blocks:
        block = normalize_asset_reviews(block)
        contexts = dict(block.asset_provenance)
        unreviewed = {asset_fingerprint(block, index) for index, ref in enumerate(block.asset_hashes)
                      if automatic_refs.intersection(contexts.get(ref, ()))}
        if unreviewed:
            block = replace(block, client_reviewed_fingerprint="",
                            client_asset_reviews=tuple(v for v in block.client_asset_reviews if v not in unreviewed))
        blocks.append(block)
    return replace(mapped, blocks=tuple(blocks)), mappings
