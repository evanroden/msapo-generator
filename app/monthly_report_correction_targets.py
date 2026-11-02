"""Read-only exact destinations for Review, never authority to change content.

Targets are receipts for the displayed warning. Names and image bytes alone
are not identities: equal files/pictures may have independent occurrences.
A changed or missing destination must be refreshed, not replaced by a sibling.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True)
class CorrectionTarget:
    report: str
    block_key: str = ""
    block_revision: str = ""
    occurrence: str = ""
    asset: str = ""
    source_id: str = ""
    source_hash: str = ""
    source_revision: str = ""
    page: int = 0
    navigation_key: str = ""

    @property
    def token(self):
        return sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def report_identity(draft):
    return sha256(json.dumps((asdict(draft.profile), asdict(draft.period)),
                             sort_keys=True).encode()).hexdigest()


def picture_target(draft, block, index, *, source=None, page=0):
    from app.monthly_report_asset_instances import asset_instances
    item = asset_instances(block)[index]
    from app.monthly_report_photo_controls import photo_disclosure_identity
    return CorrectionTarget(report_identity(draft), block.key, block.fingerprint,
        item.key, item.asset, source.id if source else "",
        source.sha256 if source else "", source.fingerprint if source else "", page,
        photo_disclosure_identity(block, index, scope=report_identity(draft)))


def source_target(draft, source, *, page=0):
    return CorrectionTarget(report_identity(draft), source_id=source.id,
        source_hash=source.sha256, source_revision=source.fingerprint, page=page)


def resolve_target(draft, target):
    """Return (block, picture index, source), or None; never choose first match."""
    from app.monthly_report_asset_instances import asset_instances
    if not isinstance(target, CorrectionTarget) or target.report != report_identity(draft):
        return None
    block = source = index = None
    if target.block_key:
        from app.monthly_report_model import used_block_keys
        if target.block_key not in used_block_keys(draft):
            return None
        matches = [b for b in draft.blocks if b.key == target.block_key]
        if len(matches) != 1 or matches[0].fingerprint != target.block_revision:
            return None
        block = matches[0]
        matches = [n for n, item in enumerate(asset_instances(block))
                   if item.key == target.occurrence and item.asset == target.asset]
        if len(matches) != 1 or block.source == "Omit":
            return None
        index = matches[0]
    if target.source_id:
        matches = [s for s in draft.sources if s.id == target.source_id]
        if (len(matches) != 1 or matches[0].sha256 != target.source_hash
                or matches[0].fingerprint != target.source_revision):
            return None
        source = matches[0]
        if type(target.page) is not int or target.page < 0 or target.page > len(source.page_texts):
            return None
    if block is None and source is None:
        return None
    return block, index, source
