"""Site-first report selection and safe reuse of a contract's report design."""

from dataclasses import asdict, replace
import hashlib

from app import monthly_report_library as library
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, profile_sections, layout_blocks
from app.monthly_report_setup import new_month_draft


def membership_key(facilities):
    return tuple(sorted(f.key for f in facilities))


def matching_profiles(profiles, facilities):
    return tuple(p for p in profiles if membership_key(p.facilities) == membership_key(facilities))


def report_key(facilities):
    # The saved identity survives renaming a site combination.
    return "sites-" + hashlib.sha256("\0".join(membership_key(facilities)).encode()).hexdigest()[:20]


def latest_snapshot(contract, key, period):
    paths = sorted(library._profile_path(contract, key, snapshots=True).glob("????-??.json"), reverse=True)
    for path in paths:
        if path.stem < period.key:
            year, month = map(int, path.stem.split("-"))
            return library.load_snapshot(contract, key, ReportPeriod(year, month))
    return None


def design_seed(profile, period, actor, source=None):
    """Reuse layout/schema/branding, never another site's activity or contacts."""
    if source and source.profile.contract != profile.contract:
        raise ValueError("Choose a starting report from the same contract.")
    if source:
        profile = replace(source.profile, key=profile.key, title=profile.title, facilities=profile.facilities,
                          scope_type=profile.scope_type, imported_from="")
    prior_blocks = {}
    if source:
        saved = library.load_snapshot(source.profile.contract, source.profile.key, period) or latest_snapshot(source.profile.contract, source.profile.key, period)
        seed = saved.draft if saved else library.load_imported_draft(source.profile.contract, source.profile.key)
        if seed:
            prior_blocks = {b.key: b for b in seed.blocks}
            profile = replace(profile, section_order=tuple(s.key for s in seed.sections),
                              excluded_sections=tuple(s.key for s in seed.sections if not s.included),
                              section_titles=tuple((s.key, s.title) for s in seed.sections),
                              section_block_order=tuple((s.key, tuple(b.key for b in s.blocks)) for s in seed.sections),
                              block_overrides=tuple(b for s in seed.sections for b in s.blocks))
    blocks, assets = [], {}
    specs = (*[b for s in profile_sections(profile) for b in s.blocks], *layout_blocks())
    for spec in specs:
        prior = prior_blocks.get(spec.key) or (source.block(spec.key) if source else None)
        reusable = spec.key in ("brand_logo", "client_logo") or spec.key.startswith("divider_")
        if reusable and prior:
            block = replace(prior, source="Library", references=(), reviewed_fingerprint="", client_reviewed_fingerprint="")
            for reference in block.asset_hashes:
                assets[reference] = library.read_asset(source.profile.contract, source.profile.key, reference)
        else:
            # Table schemas are retained in profile overrides. No copied values,
            # org charts, site photographs or contact records can be mistaken for
            # this site's information.
            block = ResolvedBlock(spec.key, "This month", extra_tables=tuple(replace(t, rows=(), reference="") for t in prior.extra_tables) if prior else ())
        blocks.append(block)
    return ReportDraft(profile, period, actor, profile_sections(profile), tuple(blocks)), assets


def save_design_start(draft, assets, *, actor, confirmed):
    """Publish a new saved design only after assets and seed are durable."""
    actor = library._confirmation(actor, confirmed)
    profile = draft.profile
    library._validate_profile(profile)
    path = library._profile_path(profile.contract, profile.key)
    with library._locked(path):
        if (path / "manifest.json").exists():
            raise library.RevisionConflict("A report for these sites was just created. Choose the saved report to continue it.")
        for reference, raw in assets.items():
            if not library._ASSET.fullmatch(reference) or library.asset_reference(raw, reference.rsplit('.', 1)[-1]) != reference:
                raise ValueError("Invalid starting-design image.")
            library._atomic_write(path / "assets" / reference, raw)
        for block in draft.blocks:
            for ref in block.asset_hashes:
                library.read_asset(profile.contract, profile.key, ref)
        at = library._now()
        versions, current = [], []
        for block in draft.blocks:
            if not block.asset_hashes:
                continue
            identity = hashlib.sha256(library._json(asdict(block))).hexdigest()
            versions.append(asdict(library.LibraryVersion(identity, block.key, block.key.replace('_', ' '), block, actor, at)))
            current.append((block.key, identity))
        value = {"schema": 1, "profile": asdict(profile), "revision": 1, "versions": versions,
                 "current": current, "bootstrap": asdict(draft), "bootstrap_snapshot_revision": 0,
                 "audit": [{"action": "design_start", "actor": actor, "at": at, "period": draft.period.key}]}
        raw = library._json(value)
        library._atomic_write(path / "history" / "00000001.json", raw)
        library._atomic_write(path / "manifest.json", raw)
    return library.load_profile(profile.contract, profile.key)


def returning_draft(state, period, actor):
    prior = latest_snapshot(state.profile.contract, state.profile.key, period)
    if prior:
        return replace(new_month_draft(prior.draft, period), profile=state.profile, prepared_by=actor), prior
    return None, None
