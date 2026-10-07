"""Reviewed public logos on persistent storage, never fetched during a rerun.

A small PNG-only bundle installs explicit contract mappings in one atomic
manifest. Report snapshots keep their own pinned copies; refreshing this
catalog cannot silently change an existing report or custom logo.
"""

from dataclasses import asdict, dataclass, replace
from datetime import date
from io import BytesIO
import json
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError

from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock

MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class BrandLogo:
    key: str
    title: str
    contracts: tuple[str, ...]
    asset: str
    source_url: str
    asset_url: str
    checked_on: str
    source_note: str = ""


@dataclass(frozen=True)
class BrandingState:
    revision: int
    logos: tuple[BrandLogo, ...]
    actor: str
    updated_at: str
    action: str = "save"


def _path():
    return library._root() / "branding"


def _logos(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError("A logo collection needs between 1 and 100 logos.")
    result, keys, contracts = [], set(), set()
    for value in values:
        try:
            logo = BrandLogo(**(value | {"contracts": tuple(value["contracts"])}))
            library._valid_key(logo.key)
            if (not isinstance(value["contracts"], list) or len(logo.contracts) > 100
                    or not logo.title.strip() or len(logo.title) > 200
                    or not isinstance(logo.source_note, str) or len(logo.source_note) > 1000
                    or logo.key in keys or not library._ASSET.fullmatch(logo.asset)
                    or not logo.asset.endswith(".png")):
                raise ValueError
            date.fromisoformat(logo.checked_on)
            for url in (logo.source_url, logo.asset_url):
                parsed = urlsplit(url)
                if len(url) > 2000 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError
            for contract in logo.contracts:
                library._contract_directory(contract)
                if contract in contracts:
                    raise ValueError
                contracts.add(contract)
            keys.add(logo.key)
            result.append(logo)
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise ValueError("Check logo names, source links, review dates and unique contract mappings.") from exc
    return tuple(result)


def _image(raw, reference):
    if len(raw) > MAX_IMAGE_BYTES or library.asset_reference(raw, "png") != reference:
        raise ValueError("A logo is too large or does not match its fingerprint.")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG" or not 1 <= image.width <= 2400 or not 1 <= image.height <= 1600:
                raise ValueError("Logos must be PNG images no larger than 2400 × 1600 pixels.")
            image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("A logo image could not be read.") from exc


def inspect_bundle(raw):
    """Read bounded data only. No SVG, URL fetches or ZIP extraction to disk."""
    if not raw or len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("Choose a logo collection ZIP up to 32 MB.")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            if (len(names) > 101 or len(names) != len(set(names))
                    or sum(m.file_size for m in members) > MAX_BUNDLE_BYTES
                    or any(m.file_size > MAX_IMAGE_BYTES or m.flag_bits & 1 for m in members)
                    or "manifest.json" not in names):
                raise ValueError("Logo collection exceeds its safe reading limits.")
            if archive.getinfo("manifest.json").file_size > 300_000:
                raise ValueError("Logo descriptions are too large.")
            value = json.loads(archive.read("manifest.json"))
            if not isinstance(value, dict) or value.get("schema") != 1:
                raise ValueError("Unsupported logo collection format.")
            logos = _logos(value.get("logos"))
            expected = {"manifest.json", *("assets/" + logo.asset for logo in logos)}
            if set(names) != expected:
                raise ValueError("Only the listed PNG logos and manifest are allowed in this collection.")
            assets = {}
            for logo in logos:
                if logo.asset not in assets:
                    data = archive.read("assets/" + logo.asset)
                    _image(data, logo.asset)
                    assets[logo.asset] = data
            return logos, assets
    except (BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        raise ValueError("The logo collection is not a readable, complete ZIP.") from exc


def load_branding(revision=None):
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("Invalid logo history revision.")
    path = _path() / (f"history/{revision:08d}.json" if revision else "manifest.json")
    if not path.exists() and revision is None:
        return None
    value = library._read(path)
    return BrandingState(value["revision"], _logos(value["logos"]), value["actor"], value["updated_at"], value.get("action", "save"))


def save_branding(logos, assets, *, expected_revision, actor, confirmed, action="save"):
    actor = library._confirmation(actor, confirmed)
    logos = _logos(json.loads(library._json([asdict(v) for v in logos])))
    path = _path()
    with library._locked(path):
        current = load_branding()
        if expected_revision != (current.revision if current else 0):
            raise library.RevisionConflict("The shared logos changed. Reload and review the current collection before saving.")
        for logo in logos:
            raw = assets.get(logo.asset)
            if raw is None:
                raw = (path / "assets" / logo.asset).read_bytes()
            _image(raw, logo.asset)
            library._atomic_write(path / "assets" / logo.asset, raw)
        state = BrandingState(expected_revision + 1, logos, actor, library._now(), action)
        encoded = library._json({"schema": 1, **asdict(state)})
        library._atomic_write(path / "history" / f"{state.revision:08d}.json", encoded)
        library._atomic_write(path / "manifest.json", encoded)
        return state


def restore_branding(revision, *, expected_revision, actor, confirmed):
    old = load_branding(revision)
    return save_branding(old.logos, {}, expected_revision=expected_revision, actor=actor,
                         confirmed=confirmed, action=f"restore:{revision}")


def find_logo(contract=None, *, brand=False, state=None):
    state = state or load_branding()
    if not state:
        return None
    return next((v for v in state.logos if (v.key == "enfra" if brand else contract in v.contracts)), None)


def read_logo(logo):
    if not library._ASSET.fullmatch(logo.asset):
        raise ValueError("Invalid saved logo reference.")
    raw = (_path() / "assets" / logo.asset).read_bytes()
    _image(raw, logo.asset)
    return raw


def apply_defaults(draft, assets):
    """Fill empty logos only; pinned/custom content always stays intact."""
    blocks = {block.key: block for block in draft.blocks}
    state = load_branding()
    for key in ("client_logo", "brand_logo"):
        block = blocks.get(key)
        if block and (block.asset_hashes or block.source == "Omit"):
            continue
        logo = find_logo(draft.profile.contract, brand=key == "brand_logo", state=state)
        if logo:
            assets[logo.asset] = read_logo(logo)
            blocks[key] = ResolvedBlock(key, "Library", asset_hashes=(logo.asset,))
    return replace(draft, blocks=tuple(blocks.values()))
