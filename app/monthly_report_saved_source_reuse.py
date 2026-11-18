"""Scoped, metadata-only discovery of originals already reviewed in this report.

This is not the shared public QA bundle shelf. Only saved report snapshots for
the exact contract and site-combination profile are eligible. Listing never
opens source bytes, extracts facts, invokes an AI reader, or changes a report.
"""
from dataclasses import dataclass
import re

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ReportProfile, ReportSource
from app.monthly_report_source_details import KEEP_FACILITY, facility_choice
from app.monthly_report_source_recovery import restore_sources
from app.monthly_report_source_scope import source_review


@dataclass(frozen=True)
class SavedSourceChoice:
    period: ReportPeriod
    source: ReportSource
    label: str


def _same_owner(saved_profile: ReportProfile, target: ReportProfile) -> bool:
    """Profile key alone is not proof that its contract/site membership is safe."""
    return (
        saved_profile.contract == target.contract
        and saved_profile.key == target.key
        and saved_profile.scope_type == target.scope_type
        and {facility.key for facility in saved_profile.facilities}
            == {facility.key for facility in target.facilities}
    )


def _site_eligible(source: ReportSource, profile: ReportProfile) -> bool:
    # A foreign explicitly printed site is never remapped to the first site.
    if source.facility and facility_choice(source, profile) == KEEP_FACILITY:
        return False
    scope = source_review(source)
    if scope.get("kind") == "sites":
        claimed = scope.get("facilities")
        if (not isinstance(claimed, list)
                or any(type(site) is not str for site in claimed)
                or not set(claimed) <= {site.key for site in profile.facilities}):
            return False
    # An unknown site may enter the existing correction form; it is not approval.
    return True


def saved_source_choices(
    profile: ReportProfile, *, exclude_ids=(), max_periods: int = 24,
) -> tuple[SavedSourceChoice, ...]:
    """Discover recent saved sources without opening originals or extraction caches.

    Period comes from the saved snapshot, not a filename, source service-date
    guess, or a global contract-wide listing. Duplicate identical originals
    appear once (newest saved month wins); different bytes with the same name
    remain different SHA-256 choices.
    """
    if type(max_periods) is not int or not 1 <= max_periods <= 36:
        raise ValueError("Invalid saved-source catalog period limit.")
    directory = library._profile_path(profile.contract, profile.key, snapshots=True)
    library._qa_path_guard(directory)
    periods = sorted(
        (path.stem for path in directory.glob("????-??.json")
         if re.fullmatch(r"[0-9]{4}-[0-9]{2}", path.stem)),
        reverse=True,
    )[:max_periods]
    seen = set(exclude_ids)
    choices = []
    for label in periods:
        try:
            year, month = map(int, label.split("-"))
            source_period = ReportPeriod(year, month)
        except ValueError:
            continue
        saved = library.load_snapshot(profile.contract, profile.key, source_period)
        if saved is None or not _same_owner(saved.draft.profile, profile):
            continue
        sites = ", ".join(facility.title for facility in saved.draft.profile.facilities)
        for source in saved.draft.sources:
            if source.id in seen or source.sha256 in seen or not _site_eligible(source, profile):
                continue
            seen.update((source.id, source.sha256))
            choices.append(SavedSourceChoice(
                source_period, source,
                f"{source.filename} · {profile.contract} · {sites} · "
                f"{source_period.label} · SHA-256 {source.sha256[:12]}",
            ))
    return tuple(choices)


def reuse_saved_source(profile: ReportProfile, choice: SavedSourceChoice):
    """Verify the still-current saved record and immutable bytes on one click.

    Restore overlays the saved reviewed source object over its extracted content,
    preserving exact source SHA, captions, page decisions and mapping. There is
    no separate approval path, no AI call and no duplicated stored original.
    The caller attaches the returned SourceContent only to its working draft.
    """
    if not isinstance(choice, SavedSourceChoice):
        raise ValueError("Select one saved source from this report's catalog.")
    saved = library.load_snapshot(profile.contract, profile.key, choice.period)
    if saved is None or not _same_owner(saved.draft.profile, profile):
        raise ValueError("Saved source ownership changed. Select a current file again.")
    source = next((item for item in saved.draft.sources
                   if item.id == choice.source.id and item.sha256 == choice.source.sha256), None)
    if source != choice.source or not _site_eligible(source, profile):
        raise ValueError("Saved source or site review changed. Select a current file again.")
    available, missing = restore_sources(profile, (source,))
    if missing or len(available) != 1 or available[0].source != source:
        raise ValueError("The saved original is unavailable or failed verification. Re-upload a valid copy.")
    return available[0]
