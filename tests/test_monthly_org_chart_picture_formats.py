"""Contract/site chart pictures must be decodable as their declared image type.

Refs #787, #270; all published fixtures and storage are synthetic.
"""

from dataclasses import asdict
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_library as library
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import OrgChartNode, ResolvedBlock
from test_monthly_report_org_chart_defaults import scopes, fresh, with_chart, chart


def _image(fmt="PNG", color="navy"):
    stream = BytesIO()
    Image.new("RGB", (40, 30), color).save(stream, fmt)
    return stream.getvalue()


def _candidate(raw, suffix="png"):
    ref = library.asset_reference(raw, suffix)
    block = approve_all_assets(ResolvedBlock("org_chart", "This month", asset_hashes=(ref,)))
    return block, {ref: raw}


def _publish(profile, block, assets, *, revision=0, scope="contract"):
    draft = with_chart(fresh(profile), block)
    return charts.save_default(
        draft, block, assets, scope=scope, expected_revision=revision,
        expected_fingerprint=block.fingerprint, confirmed=True)


def _stored(contract):
    path = charts._path(contract)
    return {str(p.relative_to(path)): p.read_bytes()
            for p in path.rglob("*") if p.is_file() and p.suffix != ".lock"}


@pytest.mark.parametrize("suffix,raw", [
    ("png", b"not a real PNG despite matching the saved SHA"),
    ("jpg", b"not a real JPEG despite matching the saved SHA"),
    ("png", bytes.fromhex("89504e470d0a1a0a") + b"broken image data"),
    ("jpg", bytes.fromhex("ffd8ffe0") + b"broken image data"),
])
def test_hash_named_nonimages_do_not_publish_a_chart(scopes, suffix, raw):
    profile = scopes[0]
    block, assets = _candidate(raw, suffix)
    before = _stored(profile.contract)
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        _publish(profile, block, assets)
    assert _stored(profile.contract) == before
    assert charts.load_defaults(profile.contract).revision == 0


@pytest.mark.parametrize("actual,declared", [("PNG", "jpg"), ("JPEG", "png")])
def test_wrongly_declared_picture_format_does_not_publish(scopes, actual, declared):
    profile = scopes[0]
    block, assets = _candidate(_image(actual), declared)
    before = _stored(profile.contract)
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        _publish(profile, block, assets)
    assert _stored(profile.contract) == before


@pytest.mark.parametrize("trim", [2, 12])
def test_truncated_jpeg_fails_before_shared_chart_publication(scopes, trim):
    profile = scopes[0]
    # verify() alone accepts this case, so require a bounded draft decode too.
    block, assets = _candidate(_image("JPEG")[:-trim], "jpg")
    before = _stored(profile.contract)
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        _publish(profile, block, assets)
    assert _stored(profile.contract) == before


@pytest.mark.parametrize("fmt,suffix,scope", [
    ("PNG", "png", "contract"),
    ("JPEG", "jpg", "site"),
])
def test_valid_chart_picture_remains_publishable_readable_and_reusable(scopes, fmt, suffix, scope):
    profile = scopes[0]
    block, assets = _candidate(_image(fmt), suffix)
    state = _publish(profile, block, assets, scope=scope)
    assert state.revision == 1
    assert charts.read_asset(profile.contract, block.asset_hashes[0]) == next(iter(assets.values()))
    working = fresh(profile)
    current = chart(working)
    restored_assets = {}
    selected = charts.use_default(
        working, current, restored_assets, expected_revision=1,
        expected_fingerprint=current.fingerprint)
    assert selected.asset_hashes == block.asset_hashes
    assert restored_assets == assets
    assert charts.load_defaults(profile.contract) == state


def test_rejected_replacement_keeps_prior_contract_chart_and_history(scopes):
    profile, other_profile = scopes[0], scopes[2]
    first, original_assets = _candidate(_image("PNG"))
    prior = _publish(profile, first, original_assets)
    assert charts.load_defaults(other_profile.contract).revision == 0
    before = _stored(profile.contract)
    bad, bad_assets = _candidate(b"bad but correctly hash-named")
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        _publish(profile, bad, bad_assets, revision=1)
    assert charts.load_defaults(profile.contract) == prior
    assert _stored(profile.contract) == before
    assert charts.read_asset(profile.contract, first.asset_hashes[0]) == next(iter(original_assets.values()))
    replacement, replacement_assets = _candidate(_image("PNG", "green"))
    latest = _publish(profile, replacement, replacement_assets, revision=1)
    assert latest.revision == 2
    assert latest.charts[0].block.asset_hashes == replacement.asset_hashes
    assert charts.load_defaults(other_profile.contract).revision == 0
    assert _stored(profile.contract)["history/00000001.json"] == before["history/00000001.json"]


def test_node_only_chart_remains_eligible_without_picture_decoder(scopes):
    profile = scopes[0]
    block = ResolvedBlock("org_chart", "This month",
                          org_nodes=(OrgChartNode("lead", "Synthetic Lead", "Lead"),))
    state = _publish(profile, block, {})
    assert state.revision == 1
    assert state.charts[0].block.org_nodes == block.org_nodes
    assert state.charts[0].block.asset_hashes == ()


def test_malformed_preexisting_chart_asset_fails_without_erasing_history(scopes):
    profile = scopes[0]
    raw = b"synthetic legacy bytes with a correct hash but not PNG pixels"
    block, assets = _candidate(raw)
    reference = "contract-org-chart:v1:" + "a" * 64
    pinned = approve_all_assets(ResolvedBlock(
        "org_chart", "Library", asset_hashes=block.asset_hashes,
        references=(reference,),
        asset_provenance=((block.asset_hashes[0], (reference,)),)))
    state = charts.ChartDefaults(1, (charts.ChartDefault(
        "", pinned, profile.key, block.fingerprint, "2026-11-06"),))
    path = charts._path(profile.contract)
    library._atomic_write(path / "assets" / block.asset_hashes[0], raw)
    encoded = library._json({"schema": 1, "contract": charts._contract(profile.contract),
                             "actor": "Synthetic Editor", **asdict(state)})
    library._atomic_write(path / "manifest.json", encoded)
    before = _stored(profile.contract)
    working = fresh(profile)
    current = chart(working)
    retained = {"existing": b"untouched"}
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        charts.use_default(working, current, retained, expected_revision=1,
                           expected_fingerprint=current.fingerprint)
    assert retained == {"existing": b"untouched"}
    assert _stored(profile.contract) == before
    assert charts.load_defaults(profile.contract).revision == 1


def _png_with_untrue_dimensions(raw, width, height):
    import struct
    import zlib
    modified = bytearray(raw)
    modified[16:24] = struct.pack(">II", width, height)
    modified[29:33] = struct.pack(">I", zlib.crc32(modified[12:29]))
    return bytes(modified)


@pytest.mark.parametrize("width,height", [(42, 42), (7000, 7000)])
def test_png_valid_hash_and_crc_but_bad_raster_refuses_chart_publication(scopes, width, height):
    profile = scopes[0]
    raw = _png_with_untrue_dimensions(_image("PNG"), width, height)
    with Image.open(BytesIO(raw)) as opened:
        assert opened.format == "PNG"
        opened.verify()
    block, assets = _candidate(raw)
    before = _stored(profile.contract)
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        _publish(profile, block, assets)
    assert _stored(profile.contract) == before
    assert charts.load_defaults(profile.contract).revision == 0


def test_incomplete_png_raster_is_not_reused_from_existing_chart_default(scopes):
    profile = scopes[0]
    raw = _png_with_untrue_dimensions(_image("PNG"), 42, 42)
    block, assets = _candidate(raw)
    reference = "contract-org-chart:v1:" + "a" * 64
    pinned = approve_all_assets(ResolvedBlock(
        "org_chart", "Library", asset_hashes=block.asset_hashes,
        references=(reference,),
        asset_provenance=((block.asset_hashes[0], (reference,)),)))
    state = charts.ChartDefaults(1, (charts.ChartDefault(
        "", pinned, profile.key, block.fingerprint, "2026-11-11"),))
    path = charts._path(profile.contract)
    library._atomic_write(path / "assets" / block.asset_hashes[0], raw)
    library._atomic_write(path / "manifest.json", library._json({
        "schema": 1, "contract": charts._contract(profile.contract),
        "actor": "Synthetic Editor", **asdict(state),
    }))
    before = _stored(profile.contract)
    draft = fresh(profile)
    current = chart(draft)
    retained = {"unrelated": b"retained"}
    with pytest.raises(library.LibraryError, match="(?i)picture|image"):
        charts.use_default(draft, current, retained, expected_revision=1,
                           expected_fingerprint=current.fingerprint)
    assert retained == {"unrelated": b"retained"}
    assert _stored(profile.contract) == before


@pytest.mark.parametrize("field,bad", [
    ("origin_profile", 123),
    ("origin_fingerprint", True),
    ("saved_at", ["2026-11-11"]),
])
def test_chart_required_metadata_types_refuse_without_rewriting(scopes, field, bad):
    profile = scopes[0]
    block, assets = _candidate(_image())
    _publish(profile, block, assets)
    path = charts._path(profile.contract) / "manifest.json"
    data = library._read(path)
    data["charts"][0][field] = bad
    path.write_bytes(library._json(data))
    before = _stored(profile.contract)
    with pytest.raises(library.LibraryError, match="could not be read"):
        charts.load_defaults(profile.contract)
    assert _stored(profile.contract) == before
