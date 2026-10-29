"""Damaged-source recovery keeps valid evidence and saved report history intact."""
from dataclasses import asdict, replace
from pathlib import Path
import json

from app.monthly_report_model import used_block_keys
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
    from app.monthly_report_section_uploads import source_route
    keys = used_block_keys(draft)
    # A removed page's remembered destination is not supporting evidence.
    # Actual narrative/page/provenance references remain in this dependency scan.
    records = tuple(replace(block, references=tuple(ref for ref in block.references if source_route(ref) is None))
                    for block in draft.blocks
                    if block.key in keys and block.source != "Omit") + draft.follow_ups
    serialized = "\n".join(json.dumps(asdict(record), ensure_ascii=False) for record in records)
    return tuple(source for source in missing if source.id in serialized)
