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
            content, _ = ingest(profile, safe_source_name(source), source_bytes(profile, source))
            recovered.append(replace(content, source=source))
        except (ValueError, OSError, RuntimeError):
            missing.append(source)
    return tuple(recovered), tuple(missing)


def retain_unavailable(available, missing):
    known = {source.id for source in available}
    return tuple(available) + tuple(source for source in missing if source.id not in known)


def used_missing_sources(draft, missing):
    keys = used_block_keys(draft)
    records = tuple(block for block in draft.blocks
                    if block.key in keys and block.source != "Omit") + draft.follow_ups
    serialized = "\n".join(json.dumps(asdict(record), ensure_ascii=False) for record in records)
    return tuple(source for source in missing if source.id in serialized)
