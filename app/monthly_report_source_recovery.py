"""Damaged-source recovery keeps valid evidence and saved report history intact."""
from dataclasses import replace
from pathlib import Path

from app.monthly_report_model import used_source_ids
from app.monthly_report_sources import ingest, source_bytes


def safe_source_name(source):
    return Path(str(source.filename).replace("\\", "/")).name[:120] or "an uploaded file"


def restore_sources(profile, records):
    recovered, missing = [], []
    for source in records:
        try:
            # Ingest sanitizes the full name; UI truncation can change its suffix.
            content, _ = ingest(profile, str(source.filename), source_bytes(profile, source))
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


# The native uploader is not a durable store of rejected bytes. Retry requests
# hold only identities and must be revalidated against the *current* chooser
# and report revision before accessing a source. Replacements with new bytes
# are normal new admissions, not a rewrite of an accepted source identity.
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class FailedSourceRetry:
    filename: str
    sha256: str
    position: int
    scope: tuple
    selection: tuple
    accepted_ids: tuple


def _retry_scope(profile, period, revision):
    return (profile.contract, profile.key, period.key, revision)


def failed_source_retries(profile, period, revision, files, contents):
    """One retry per rejected original, not one replay of the whole selection.

    Replacing failed bytes under the same name with accepted new bytes retires
    the old failure action; content hashes, never filenames, own source data.
    """
    selection = tuple(
        (Path(str(name).replace("\\", "/")).name, sha256(raw).hexdigest())
        for name, raw in files
    )
    accepted = tuple(item.source.id for item in contents)
    accepted_set = set(accepted)
    replaced_names = {name for name, digest in selection if digest in accepted_set}
    seen = set()
    result = []
    for position, (name, digest) in enumerate(selection):
        if digest in accepted_set or digest in seen or name in replaced_names:
            continue
        seen.add(digest)
        result.append(FailedSourceRetry(
            name, digest, position, _retry_scope(profile, period, revision),
            selection, accepted))
    return tuple(result)


def retry_failed_source(profile, period, revision, files, contents, request):
    """Retry only selected, unchanged bytes if the originating report still owns it.

    The contract refuses stale selections, switched site/month, replaced bytes,
    and changes to sibling identities before any file storage is touched.
    Ingest's established parser/limit/cleanup checks remain authoritative.
    """
    if (not isinstance(request, FailedSourceRetry)
            or request not in failed_source_retries(profile, period, revision, files, contents)):
        raise ValueError("The report or selected files changed. Review the current files before retrying.")
    filename, raw = files[request.position]
    return ingest_batch_single(profile, filename, raw, contents)


def ingest_batch_single(profile, filename, raw, contents):
    """Delegate resource budgets and rejected-blob cleanup to canonical ingest."""
    from app.monthly_report_sources import ingest_batch
    return ingest_batch(profile, ((filename, raw),), contents)
