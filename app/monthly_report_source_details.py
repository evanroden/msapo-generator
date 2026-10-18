"""Explicit source metadata corrections; original bytes and page decisions stay intact."""
from dataclasses import replace
from datetime import date

KEEP_FACILITY = "__keep_source_facility__"


def source_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def facility_choice(source, profile):
    """Map only a unique exact title/key/alias; never infer a site from a filename."""
    value = source.facility.strip().casefold()
    if not value:
        from app.monthly_report_source_scope import (
            CONTRACT_ARTWORK, MULTIPLE_FACILITIES, source_review,
        )
        scope = source_review(source)
        if scope:
            return CONTRACT_ARTWORK if scope.get("kind") == "contract_artwork" else MULTIPLE_FACILITIES
        return ""
    matches = [site.key for site in profile.facilities
               if value in {name.strip().casefold() for name in
                            (site.key, site.title, *site.aliases)}]
    return matches[0] if len(matches) == 1 else KEEP_FACILITY


def detail_problems(source, profile, period, *, in_report=False, draft=None):
    """Short, read-only reasons to expose a saved source's correction route."""
    if not in_report and (source.classification == "Reference only" or not source.selected_pages):
        return ()
    problems = []
    when = source_date(source.service_date)
    if when is None:
        problems.append("date unreadable" if source.service_date else "date unknown")
    elif not period.start <= when <= period.end:
        problems.append("date outside this report month")
    site = facility_choice(source, profile)
    if not site:
        from app.monthly_report_source_scope import included_scope_valid
        if not (in_report and draft is not None and draft.profile == profile and draft.period == period
                and included_scope_valid(draft, source)):
            problems.append("site unknown")
    elif site == KEEP_FACILITY:
        problems.append("site does not match this report")
    elif source.scope_review:
        from app.monthly_report_source_scope import reviewed_scope
        if reviewed_scope(source, profile) is None:
            problems.append("source scope changed; review its sites")
    return tuple(problems)


def correct_source_details(source, profile, chosen_date, chosen_facility, *, chosen_facilities=(), artwork_keys=()):
    """Apply an explicit correction without relabeling a source or approving its pages."""
    if chosen_date is not None and type(chosen_date) is not date:
        raise ValueError("Choose one source date, or leave the date unknown.")
    sites = {site.key: site for site in profile.facilities}
    from app.monthly_report_source_scope import CONTRACT_ARTWORK, MULTIPLE_FACILITIES, correct_scope
    if chosen_facility in (MULTIPLE_FACILITIES, CONTRACT_ARTWORK):
        updated = replace(source, service_date=chosen_date.isoformat() if chosen_date else "",
                          facility="", scope_review="")
        return correct_scope(updated, profile, chosen_facilities,
                             contract_artwork=chosen_facility == CONTRACT_ARTWORK, artwork_keys=artwork_keys)
    if chosen_facility == KEEP_FACILITY:
        facility = source.facility
    elif chosen_facility == "":
        facility = ""
    elif chosen_facility in sites:
        facility = sites[chosen_facility].key
    else:
        raise ValueError("Choose an exact site from this report, or keep the source identity unresolved.")
    updated = replace(source, service_date=chosen_date.isoformat() if chosen_date else "",
                      facility=facility, scope_review="")
    return correct_scope(updated, profile, (chosen_facility,)) if chosen_facility in sites else updated
