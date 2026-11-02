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
from app.monthly_report_import import MappedImport, is_logo_artwork, is_header_artwork
from app.monthly_report_model import known_sections, layout_blocks
from app.monthly_report_sections import (
    build_section_import, _build_section_import,
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
    period_review_items: tuple[str, ...] = ()


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
    # The inspector records some native cover text in the "cover"
    # section rather than title_candidates. Only the first page's own
    # document text may establish identity; body/service content is never
    # permission to import another site's contacts or activity.
    cover_lines = list(inspection.title_candidates)
    cover_lines.extend(item.text for item in inspection.items
                       if item.kind == "text" and item.part == "word/document.xml"
                       and item.section in ("", "cover") and 0 <= item.position <= 80)
    cover = " " + _words("\n".join(dict.fromkeys(cover_lines))) + " "
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
    # A cover can lag unfinished body edits. Only an item's own explicit date
    # proves old prose; undated work stays available for a section-level check.
    period_review = tuple(i.id for i in inspection.items
                          if i.kind == "text" and i.id in uncertain) if (
        source_period and source_period < requested and not current) else ()
    return StartingReportAnalysis(sites, relation, tuple(current), tuple(older), tuple(uncertain), source_period, period_review)


def _cover_photo_window(items):
    """The first cover section and its one immediately adjacent photo panel.

    Some reports put the title/logo and building photo in separate Word
    sections. Only an adjoining picture-only panel can extend the cover;
    Contents, report content and later unlabelled image pages cannot do so.
    """
    body = tuple(item for item in items if item.part == "word/document.xml" and item.position)
    cover = tuple(item for item in body if item.section in ("", "cover"))
    earliest = min((item.word_section for item in cover), default=None)
    if earliest is None:
        return (), 0
    # A contents heading closes the cover, not incidental prose such as
    # "The contents of this report are confidential." Allow a wrapped title.
    stop = min((item.position for item in body
                if item.section not in ("", "cover")
                or (item.kind == "text" and re.search(
                    r"^\s*(?:table\s+of\s+)?contents[ \t]*:?[ \t]*(?:\n|$)", item.text, re.I | re.M))),
               default=max((item.position for item in body), default=0) + 1)
    first = tuple(item for item in cover if item.word_section == earliest and item.position < stop)
    # An existing photograph or unassigned drawing on the first cover stays
    # authoritative. Do not promote another illustration when that art needs
    # a specific recovery of its own. Known branding is not an independent
    # photograph; its unresolved owner remains a separate review requirement.
    independent_art = any(item.kind in ("image", "unsupported")
                          and item.suggested_slot not in ("brand_logo", "client_logo")
                          and not is_logo_artwork(item) and not is_header_artwork(item) for item in first)
    following = tuple(item for item in cover if item.word_section == earliest + 1 and item.position < stop)
    photo_panel = (following and any(item.kind == "image" for item in following)
                   and all(item.kind == "image" or (item.kind == "text"
                           and len(item.text) <= 140 and re.search(r"\b(?:cover|photo(?:graph)?|exterior)\b", item.text, re.I))
                           for item in following))
    return ((earliest, earliest + 1) if not independent_art and photo_panel else (earliest,)), stop


def cover_photo_candidates(items, *, native_furniture_ids=()):
    """Only cover photographs, not logos, dividers or package leftovers."""
    from app.monthly_report_sections import small_artwork
    items = tuple(items)
    cover_sections, stop = _cover_photo_window(items)
    possible = tuple(item for item in items
                     if item.kind == "image" and item.id not in native_furniture_ids
                     and item.part == "word/document.xml"
                     and item.section in ("", "cover")
                     and not is_logo_artwork(item) and not is_header_artwork(item)
                     and not item.suggested_slot.startswith("divider_")
                     and not small_artwork(item))
    if not possible:
        return ()
    return tuple(item for item in possible if item.word_section in cover_sections and item.position < stop)


def unresolved_cover_artwork(items, *, native_furniture_ids=()):
    """Visible cover rasters with neither a photo choice nor a known logo role.

    Later Contents art stays in its original Word section. Small artwork and
    non-logo header/footer graphics in the actual cover are not evidence of
    an empty or decorative image; keep their specific recovery reachable.
    """
    items = tuple(items)
    photo_ids = {item.id for item in cover_photo_candidates(items, native_furniture_ids=native_furniture_ids)}
    cover_sections, stop = _cover_photo_window(items)
    return tuple(item for item in items if item.kind == "image" and item.position
                 and item.id not in photo_ids
                 and item.suggested_slot not in ("brand_logo", "client_logo")
                 and not item.suggested_slot.startswith("divider_")
                 and (item.part != "word/document.xml"
                      or (item.word_section in cover_sections and item.position < stop)))


def suggested_cover_photo(items, *, native_furniture_ids=()):
    """Default to a uniquely plausible large cover picture, never a logo.

    The user can replace the suggestion in the thumbnail gallery. A tie or
    missing size proof leaves the optional cover photo unset instead of
    guessing from arbitrary client artwork.
    """
    candidates = tuple(item for item in cover_photo_candidates(items, native_furniture_ids=native_furniture_ids)
                       if not item.image_width or not item.image_height
                       or 0.42 <= item.image_width / item.image_height <= 2.9)
    if not candidates:
        return None
    tagged = tuple(item for item in candidates if item.suggested_slot == "cover_photo")
    if len(tagged) == 1:
        return tagged[0]
    ranked = sorted(candidates, key=lambda item: item.image_width * item.image_height,
                    reverse=True)
    if len(ranked) == 1:
        return ranked[0]
    first, second = ranked[:2]
    area, runner_up = first.image_width * first.image_height, second.image_width * second.image_height
    return first if area > 40000 and area >= 1.6 * max(1, runner_up) else None


def automatic_section_plans(inspection, analysis, *, preferred_logos=(), native_design=False, source_view=None,
                            native_art_review=None, source_path=None, profile=None, period=None):
    """Pre-fill recognizable content; ask only about unresolved source content.

    'approved' satisfies the existing import builder's structural validation.
    It does not mean the writer reviewed automatically routed pictures; that
    distinction is enforced by build_starting_import below.
    """
    from app.monthly_report_native_art_review import native_cover_furniture_ids
    furniture_ids = native_cover_furniture_ids(inspection.items) if source_view is not None else ()
    kept_native = set()
    if native_art_review is not None:
        if source_view is None or source_path is None or profile is None or period is None or analysis.site_relation != "same":
            raise ValueError("Native artwork preservation requires a verified same-site source and report scope.")
        from app.monthly_report_native_art_review import verify_native_art_review
        preserved = verify_native_art_review(source_path, source_view, profile, period, native_art_review)
        if preserved is not None:
            kept_native = {item.original_id for item in preserved.inventory.occurrences}
    known = {b.key for s in known_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    result = {}
    for section in section_reviews(inspection, source_view=source_view):
        cover_default = suggested_cover_photo(section.items, native_furniture_ids=furniture_ids) if section.key == "cover" else None
        cover_unknown = {item.id for item in unresolved_cover_artwork(section.items, native_furniture_ids=furniture_ids)} if section.key == "cover" else set()
        plan = {"key": section.key, "action": "Keep and review", "target": section.key,
                "omit": False, "selected": [], "texts": {}, "tables": {}, "destinations": {},
                "new_assets": [], "image_notes": {}, "automatic": True, "approved": True,
                "source_sha256": inspection.sha256, "source_site_relation": analysis.site_relation}
        if section.key == "cover" and native_art_review is not None:
            plan["native_art_review"] = native_art_review
        if analysis.site_relation != "same":
            plan["unsupported_reviewed"] = True
        questions = []
        for item in section.items:
            slot = item.suggested_slot
            if native_design and slot.startswith("divider_"):
                # Record the exact source image consumed by the native design.
                # Replaying it must not look like a new human omission.
                if item.kind == "image" and analysis.site_relation == "same":
                    plan.setdefault("automatic_divider_skips", {}).setdefault(slot, []).append(item.id)
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
            if slot in preferred_logos:
                # This is an automatic use of the report's current logo, not
                # an operator deselecting a source contribution. A verified
                # same-source receipt may retain only these exact image roles.
                if item.kind == "image" and slot in ("brand_logo", "client_logo"):
                    plan.setdefault("automatic_logo_skips", {}).setdefault(slot, []).append(item.id)
                continue
            if item.id in analysis.older_items and item.kind != "image":
                # Old prose is not current-month work. Its photos are still
                # source artwork belonging to this exact section, however:
                # retain them with immutable source/month provenance so they
                # can be updated, rather than making every image disappear
                # merely because the uploaded report is from August.
                continue
            if section.key == "cover" and item.kind == "text" and slot != "footer_text":
                continue  # The target report already supplies its cover title/date.
            if item.kind == "unsupported":
                # Never treat an unrendered source drawing as absent or as a
                # harmless omission. The section requires safe preservation or
                # a named replacement. Native artwork the inspector recognizes
                # as reusable design is filtered separately by section_reviews.
                questions.append(
                    "A Word diagram or image in this section needs preservation. "
                    "Its original section is retained; prepare its complete "
                    "pages or provide a clear replacement before continuing."
                )
                continue
            if section.key == "other":
                questions.append("Choose where the additional content belongs.")
                continue
            if item.kind == "image":
                if item.id in kept_native:
                    continue  # Exact reviewed native preservation, not a mapped or approved image asset.
                if analysis.site_relation == "same" and item.id in cover_unknown:
                    questions.append("Other cover artwork has no confirmed photograph or logo role.")
                    continue
                if section.key == "organization" and re.search(
                        r"(?:^|[_-])contact[_-]matrix(?:[_.-]|$)",
                        item.image_part.rsplit("/", 1)[-1].casefold()):
                    # Authentic ENFRA reports can embed a picture captioned
                    # only in the *media filename*, e.g. contact_matrix_rev6.
                    # Otherwise the generic organization fallback incorrectly
                    # makes the contact page another org_chart image. Never
                    # infer membership from the filename: source-site checks
                    # have already run above. Photo privacy review remains open.
                    slot = "contact_matrix"
                if not slot and section.key not in ("cover", "other", "proposals", "accounts_receivable"):
                    # A source image inside a recognized Word report section
                    # belongs with that section's visual evidence even when
                    # its individual paragraph lacks a filename or caption.
                    # Quote/receivable images are excluded from this fallback:
                    # they can contain amounts only in pixels.
                    from app.monthly_report_visual_preservation import VISUAL_SLOTS
                    slot = VISUAL_SLOTS.get(section.key, "")
                if section.key == "cover" and slot not in ("brand_logo", "client_logo"):
                    # Optional cover photo is one chosen image; even when
                    # several pictures exist the gallery does not need one
                    # approval radio for each unrelated logo/photo.
                    if cover_default is None or item.id != cover_default.id:
                        continue
                    slot = "cover_photo"
                elif small_artwork(item):
                    continue
                if section.key != "cover" and (not slot or (slot in ("cover_photo", "brand_logo", "client_logo")
                                and sum(i.kind == "image" and i.suggested_slot == slot for i in section.items) > 1)):
                    questions.append("A picture's purpose is not clear.")
                    continue
            if item.id in analysis.period_review_items:
                plan.setdefault("period_review_items", []).append(item.id)
                questions.append("Check the reporting month for this work; the cover shows an earlier month.")
            if item.kind == "text" and contains_price(item.text):
                questions.append("Remove pricing from the report text.")
                continue
            if item.kind == "table":
                table, _ = table_without_prices(item)
                if not table:
                    continue
                if section.key == "activity":
                    from app.monthly_report_annual_work_order_grid import (
                        annual_site_month_table, annual_grid_candidate, annual_grid_matches_profile)
                    annual = annual_site_month_table(item)
                    if annual_grid_candidate(item):
                        # Exact month headings do not prove the imported sites
                        # belong to the target report or the bands are sound.
                        if annual is None:
                            questions.append("Review this annual work-order grid's category bands, site fields and month order.")
                            continue
                        if profile is None or not annual_grid_matches_profile(annual, profile):
                            questions.append("Review this annual work-order grid's sites against the selected report group.")
                            continue
                        table = annual
                        slot = "work_orders"
                if table_has_pricing(table.columns, table.rows):
                    questions.append("Check this table's pricing or column headings.")
                    continue
                if slot == "subcontractor_matrix" and item.merged_title_rows:
                    from app.monthly_report_vendor_groups import grouped_vendor_contacts
                    grouped_vendor = grouped_vendor_contacts(item)
                    if grouped_vendor is None:
                        questions.append("Review the vendor table's merged category labels and contact headings.")
                        continue
                    if table_has_pricing(grouped_vendor.columns, grouped_vendor.rows):
                        questions.append("Check the vendor table for pricing before including it.")
                        continue
                    table = grouped_vendor
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


def build_starting_import(path, inspection, plans, *, source_view=None, profile=None, period=None):
    """Build auto-routed content without forging a human picture approval."""
    if source_view is not None:
        from app.monthly_report_operational_source import verified_operation
        with verified_operation(path, source_view, inspection) as operation:
            return _build_starting_import(path, inspection, plans, source_view=operation.view, _operation=operation,
                                          profile=profile, period=period)
    return _build_starting_import(path, inspection, plans, profile=profile, period=period)


def _build_starting_import(path, inspection, plans, *, source_view=None, _operation=None, profile=None, period=None):
    if source_view is not None:
        from app.monthly_report_operational_source import checked_operation
        checked_operation(path, source_view, _operation)
    plans = tuple(plans)
    if not all(p.get("approved") for p in plans):
        raise ValueError("Resolve the remaining starting-report questions before continuing.")
    # Check before contribution filtering: Omit cannot erase its conflicting
    # preservation record or move an exact target into an inactive plan.
    for plan in plans:
        review = plan.get("native_art_review")
        if review is not None:
            if source_view is None or profile is None or period is None:
                raise ValueError("Native artwork preservation requires its verified source view and report scope.")
            from app.monthly_report_native_art_review import _verify_native_art_review
            context = _verify_native_art_review(path, source_view, profile, period, review)
            ids = {item.original_id for item in context.inventory.occurrences} if context else set()
            if plan.get("omit") or any(ids.intersection(other.get("selected", ())) for other in plans):
                raise ValueError("Native artwork preservation conflicts with this exact occurrence's omission or mapping.")
    def contributes(plan):
        return not plan.get("omit") and bool(plan.get("selected") or plan.get("new_assets")
                                             or plan.get("preserved_assets") or plan.get("cover_photo_omitted")
                                             or plan.get("native_art_review"))
    if not any(contributes(plan) for plan in plans):
        return MappedImport((), (), (), ()), ()
    # Unrelated/old sections intentionally carry no data. The original keeps
    # their unsupported objects, but they are not new target-site exceptions.
    active = tuple(p for p in plans if contributes(p))
    mapped, mappings = (build_section_import(path, inspection, active, profile=profile, period=period) if source_view is None else
                        _build_section_import(path, inspection, active, source_view=source_view, _operation=_operation,
                                              profile=profile, period=period))
    automatic_refs = {f"docx:{inspection.sha256}:{identity}" for p in active if p.get("automatic")
                      for identity in p.get("selected", ())}
    # A source-bound Word diagram screenshot was rendered, not human-certified
    # for pricing hidden inside image pixels. Treat its asset provenance like
    # every other automatic imported image, not as blanket visual approval.
    automatic_refs.update(
        f"docx:{inspection.sha256}:word-sections:{','.join(map(str, record['sections']))}:page:{record['page']}"
        for plan in active if plan.get("auto_native_diagrams")
        for record in plan.get("word_page_records", ())
    )
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
