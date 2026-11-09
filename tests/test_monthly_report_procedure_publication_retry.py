"""A repeated procedure publication must actually leave its pictures usable."""

from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_workflow_standards as workflows
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import BlockSpec, ResolvedBlock, SectionSpec
from app.monthly_report_objects import object_path
from app.monthly_report_ui_text import literal
from test_monthly_report_contract_workflows import image_block, legacy, report
from test_monthly_report_contract_workflow_ui import button, start


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


def file_records(*, except_paths=()):
    """Keep original bytes and identity; relinking legitimately changes nlink."""
    return {
        str(path.relative_to(library._root())): (
            path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in library._root().rglob("*")
        if path.is_file() and path.name != ".write-lock" and path not in except_paths
    }


def published(key="business_hours_workflow", colors=("navy",), contract="Contract A"):
    images = [image_block(key, color) for color in colors]
    assets = {ref: raw for _, values in images for ref, raw in values.items()}
    block = approve_all_assets(replace(images[0][0], asset_hashes=tuple(assets),
        text="Synthetic report-only procedure note.", client_asset_reviews=(),
        client_reviewed_fingerprint=""))
    draft = report(contract, (block, ResolvedBlock("activity_summary", "This month",
                                                 text="Synthetic monthly work retained.")))
    state = workflows.save_standard(draft, block, assets, expected_revision=0,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    targets = tuple(workflows._path(contract) / "assets" / ref for ref in block.asset_hashes)
    return SimpleNamespace(draft=draft, block=block, assets=assets, state=state,
                           saved=saved, targets=targets)


def retry(item, assets=None):
    return workflows.save_standard(item.draft, item.block, item.assets if assets is None else assets,
        expected_revision=item.state.revision, expected_fingerprint=item.block.fingerprint, confirmed=True)


def damage_alias(path, kind):
    # Never write through a hard link to an immutable pooled/report original.
    path.unlink()
    if kind == "corrupt":
        path.write_bytes(b"Synthetic damaged contract alias.")


def pixels(raw):
    with Image.open(BytesIO(raw)) as image:
        return image.size, image.convert("RGB").tobytes()


def word_pixels(draft, assets, key):
    block = next(block for block in draft.blocks if block.key == key)
    section = SectionSpec("organization", "1", "Outage procedures", (BlockSpec(key, "image_page"),))
    output = assemble_docx(replace(draft, sections=(section,), blocks=(block,)),
                           asset_loader=assets.__getitem__)
    # Public final assembly, no acknowledgment override or internal builder.
    with ZipFile(BytesIO(output)) as package:
        return [pixels(package.read(name)) for name in package.namelist()
                if name.startswith("word/media/")]


def assert_original_report(item):
    profile, period = item.draft.profile, item.draft.period
    assert library.load_snapshot(profile.contract, profile.key, period) == item.saved
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == item.saved
    for ref, raw in item.assets.items():
        assert library.read_asset(profile.contract, profile.key, ref) == raw


def assert_reusable(item, foreign_assets=()):
    assets = {}
    fresh = workflows.apply_defaults(report(item.draft.profile.contract, key="another-site"), assets)
    actual = next(block for block in fresh.blocks if block.key == item.block.key)
    assert actual.asset_hashes == item.block.asset_hashes
    assert assets == item.assets
    rendered = word_pixels(fresh, assets, item.block.key)
    assert all(pixels(raw) in rendered for raw in item.assets.values())
    assert all(pixels(raw) not in rendered for raw in foreign_assets)


@pytest.mark.parametrize("key", workflows.WORKFLOW_KEYS)
def test_healthy_identical_publication_keeps_alias_pool_history_and_revision(key):
    item = published(key)
    before = file_records()
    assert retry(item) == item.state
    assert retry(item) == item.state
    assert file_records() == before
    assert_original_report(item)
    assert_reusable(item)
    assert file_records() == before


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
@pytest.mark.parametrize("key", workflows.WORKFLOW_KEYS)
def test_repeated_publication_recovers_only_its_missing_or_replaced_alias(key, kind):
    item = published(key)
    other = published(contract="Contract B", colors=("red",))
    target = item.targets[0]
    pool = object_path(target)
    damage_alias(target, kind)
    before = file_records(except_paths=(target,))
    original_assets = dict(item.assets)

    assert retry(item) == item.state
    assert target.exists(), "A successful publication must leave a usable saved picture."
    assert target.read_bytes() == item.assets[target.name]
    assert target.samefile(pool)
    assert file_records(except_paths=(target,)) == before
    assert item.assets == original_assets
    assert_original_report(item)
    assert_original_report(other)
    assert workflows.load_standards("Contract B") == other.state
    assert_reusable(item, other.assets.values())
    repaired = file_records()
    assert retry(item) == item.state and file_records() == repaired


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_actual_replace_then_use_control_recovers_picture_and_word_without_new_history(kind):
    item = published()
    other = published(contract="Contract B", colors=("red",))
    app = start(item.draft, dict(item.assets))
    assert not app.exception
    target = item.targets[0]
    damage_alias(target, kind)
    before = file_records(except_paths=(target,))
    button(app, "Replace contract default").click().run()

    assert not app.exception
    assert any("Contract default saved." in message.value for message in app.success)
    assert target.exists(), "The displayed save success must describe an available picture."
    assert workflows.read_asset(target.name, contract="Contract A") == item.assets[target.name]
    assert workflows.load_standards("Contract A") == item.state
    assert app.session_state["draft"] == item.draft
    assert app.session_state["assets"] == item.assets
    button(app, "Use contract default in this report").click().run()
    assert not app.exception and not app.warning
    assert app.session_state["explicit"]
    applied = app.session_state["draft"]
    actual = next(block for block in applied.blocks if block.key == item.block.key)
    assert actual.asset_hashes == item.block.asset_hashes and actual.text == item.block.text
    assert applied.blocks[1] == item.draft.blocks[1]
    rendered = word_pixels(applied, app.session_state["assets"], item.block.key)
    assert pixels(item.assets[target.name]) in rendered
    assert all(pixels(raw) not in rendered for raw in other.assets.values())
    assert file_records(except_paths=(target,)) == before
    assert_original_report(item)


@pytest.mark.parametrize("alias_kind", ["healthy", "missing", "corrupt"])
def test_corrupt_pooled_original_refuses_identical_publication_without_rewriting_data(alias_kind):
    item = published()
    target = item.targets[0]
    pool = object_path(target)
    # Replace only the pool name. Existing report links retain their good inode.
    pool.unlink()
    pool.write_bytes(b"Synthetic damaged pooled object.")
    if alias_kind != "healthy":
        damage_alias(target, alias_kind)
    before = file_records()
    with pytest.raises(library.LibraryError, match="Shared report object failed verification"):
        retry(item)
    assert file_records() == before
    assert workflows.load_standards("Contract A") == item.state
    assert_original_report(item)


def test_multiple_pictures_recover_all_damaged_aliases_and_keep_healthy_picture():
    item = published(colors=("navy", "green", "orange"))
    damage_alias(item.targets[0], "missing")
    damage_alias(item.targets[1], "corrupt")
    before = file_records(except_paths=item.targets[:2])
    assert retry(item) == item.state
    for target in item.targets:
        assert target.exists(), "Every picture in a successful publication must be available."
        assert target.read_bytes() == item.assets[target.name]
        assert target.samefile(object_path(target))
    assert file_records(except_paths=item.targets[:2]) == before
    assert_original_report(item)
    assert_reusable(item)


def test_later_write_failure_has_no_success_or_metadata_change_and_explicit_retry_recovers(monkeypatch):
    item = published(colors=("navy", "green"))
    app = start(item.draft, dict(item.assets))
    for target in item.targets:
        damage_alias(target, "missing")
    before = file_records(except_paths=item.targets)
    write = library._atomic_write
    attempts = []
    failure = OSError("Synthetic later picture write failed.")

    def fail_second(path, raw):
        if path in item.targets:
            attempts.append(path)
            if path == item.targets[1]:
                raise failure
        return write(path, raw)

    with monkeypatch.context() as current:
        current.setattr(library, "_atomic_write", fail_second)
        button(app, "Replace contract default").click().run()
    assert not app.exception
    assert any(literal(failure) == message.value for message in app.warning)
    assert not any("Contract default saved." in message.value for message in app.success)
    assert attempts == list(item.targets)
    # Asset aliases are repaired individually. A failed later write does not
    # promise rollback of an already recovered alias, or publish new metadata.
    assert item.targets[0].read_bytes() == item.assets[item.targets[0].name]
    assert not item.targets[1].exists()
    assert file_records(except_paths=item.targets) == before
    assert app.session_state["draft"] == item.draft
    assert app.session_state["assets"] == item.assets
    assert workflows.load_standards("Contract A") == item.state
    assert_original_report(item)

    button(app, "Replace contract default").click().run()
    assert not app.exception and not app.warning
    assert any("Contract default saved." in message.value for message in app.success)
    assert workflows.load_standards("Contract A") == item.state
    assert file_records(except_paths=item.targets) == before
    assert_reusable(item)


def test_saved_report_bytes_recover_alias_when_session_asset_map_is_empty():
    item = published()
    target = item.targets[0]
    damage_alias(target, "missing")
    assets = {}
    before = file_records(except_paths=(target,))
    assert retry(item, assets) == item.state
    assert target.exists(), "A verified report-owned original must reach the publication path."
    assert workflows.read_asset(target.name, contract="Contract A") == item.assets[target.name]
    assert assets == {} and file_records(except_paths=(target,)) == before
    assert_original_report(item)


@pytest.mark.parametrize("change", ["stale", "fingerprint", "unconfirmed", "unreviewed",
                                    "synthetic", "different_block", "invalid_incoming"])
def test_rejected_actions_do_not_repair_alias_or_mutate_stored_data(change, monkeypatch):
    item = published()
    target = item.targets[0]
    damage_alias(target, "missing")
    before = file_records()
    draft, block, assets = item.draft, item.block, dict(item.assets)
    kwargs = dict(expected_revision=1, expected_fingerprint=block.fingerprint, confirmed=True)
    if change == "stale":
        kwargs["expected_revision"] = 0
    elif change == "fingerprint":
        kwargs["expected_fingerprint"] = "changed"
    elif change == "unconfirmed":
        kwargs["confirmed"] = False
    elif change == "unreviewed":
        block = replace(block, client_asset_reviews=(), client_reviewed_fingerprint="")
        draft = replace(draft, blocks=(block, *draft.blocks[1:]))
        kwargs["expected_fingerprint"] = block.fingerprint
    elif change == "synthetic":
        draft = replace(draft, synthetic=True)
    elif change == "different_block":
        draft = replace(draft, blocks=(replace(block, text="Later delivered note."), *draft.blocks[1:]))
    else:
        assets[target.name] = b"Synthetic invalid incoming bytes."

    def unexpected_write(*args, **kwargs):
        raise AssertionError("A rejected action reached asset persistence.")

    monkeypatch.setattr(library, "_atomic_write", unexpected_write)
    with pytest.raises(library.LibraryError):
        workflows.save_standard(draft, block, assets, **kwargs)
    assert not target.exists() and file_records() == before
    assert workflows.load_standards("Contract A") == item.state
    assert_original_report(item)


@pytest.mark.parametrize("key", workflows.WORKFLOW_KEYS)
def test_changed_publication_still_creates_one_revision_and_retains_originals(key):
    item = published(key)
    before = file_records()
    replacement, assets = image_block(key, "blue")
    draft = replace(item.draft, blocks=(replacement, *item.draft.blocks[1:]))
    updated = workflows.save_standard(draft, replacement, assets, expected_revision=1,
        expected_fingerprint=replacement.fingerprint, confirmed=True)
    assert updated.revision == 2
    assert updated.workflows[0].block.asset_hashes == replacement.asset_hashes
    assert_original_report(item)
    after = file_records()
    manifest = str((workflows._path("Contract A") / "manifest.json").relative_to(library._root()))
    assert all(after[name] == value for name, value in before.items() if name != manifest)
    assert sorted(path.name for path in (workflows._path("Contract A") / "history").iterdir()) == [
        "00000001.json", "00000002.json"]


def test_repeated_same_contract_legacy_adoption_repairs_alias_without_changing_legacy_original():
    item = legacy()
    receipt = workflows.legacy_review_receipt(item)
    draft = report()
    first = workflows.adopt_legacy(draft, item.key, expected_revision=0,
        expected_legacy_fingerprint=item.block.fingerprint, expected_legacy_receipt=receipt, confirmed=True)
    target = workflows._path(draft.profile.contract) / "assets" / item.block.asset_hashes[0]
    original = workflows.read_asset(target.name)
    target.unlink()
    before = file_records(except_paths=(target,))
    again = workflows.adopt_legacy(draft, item.key, expected_revision=1,
        expected_legacy_fingerprint=item.block.fingerprint, expected_legacy_receipt=receipt, confirmed=True)
    assert again == first
    assert target.exists(), "Repeated explicit adoption must leave its contract copy usable."
    assert workflows.read_asset(target.name, contract=draft.profile.contract) == original
    assert workflows.legacy_review_receipt(item) == receipt
    assert file_records(except_paths=(target,)) == before
