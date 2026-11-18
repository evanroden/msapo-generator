"""Damaged-source recovery keeps valid evidence and saved report history intact."""
from dataclasses import replace
from pathlib import Path

from app.content_cache import ContentDigests
from app.monthly_report_model import used_source_ids
from app.monthly_report_sources import ingest, source_bytes


def safe_source_name(source):
    return Path(str(source.filename).replace("\\", "/")).name[:120] or "an uploaded file"


def restore_sources(profile, records):
    recovered, missing = [], []
    # A saved original is read and authenticated exactly once. The same
    # immutable bytes instance is passed to ingest for its digest lookup.
    digests = ContentDigests()
    for source in records:
        try:
            # Ingest sanitizes the full name; UI truncation can change its suffix.
            content, _ = ingest(
                profile, str(source.filename),
                source_bytes(profile, source, _digests=digests), _digests=digests)
            recovered.append(replace(content, source=source))
        except (ValueError, OSError, RuntimeError):
            missing.append(source)
    return tuple(recovered), tuple(missing)


def retain_unavailable(available, missing):
    known = {source.id for source in available}
    return tuple(available) + tuple(source for source in missing if source.id not in known)


def used_missing_sources(draft, missing):
    """Only unavailable originals actually cited by included report content.

    The generation preflight already uses the authoritative source/page
    provenance scan. Searching serialized report text instead can mistake a
    plain SHA mention, unused image, disabled follow-up or old route for proof
    that a missing original is still needed.
    """
    required = used_source_ids(draft)
    return tuple(source for source in missing if source.id in required)
