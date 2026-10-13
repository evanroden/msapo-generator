"""Stage shared originals in a generation-bound, disposable Monthly workspace.

This is the production Starting report inspection handoff, not a second
parser, prefill oracle or automatic plan approval. Callers must first enter
``testing.isolated(run_token)`` and establish its lease via ``memory._data_dir``.
The returned stage is consumed by ``render_section_setup`` in the same context;
that ordinary UI still classifies, reviews, imports and merges the report.

The shared library remains outside this disposable namespace. Reset removes
the run copy, never its original. The caller must retain ``capture_namespace``
for callbacks/workers and validate this descriptor before reusing a staged
result; a descriptor is not authentication or permission to read live storage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import os

from app import memory
from app import monthly_report_fixture_vault as storage
from app import monthly_report_import as starting_import
from app import monthly_report_testing as testing
from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_shared_fixtures import SharedFixtureLibrary
from app.monthly_report_start import membership_key


_STAGING = "_enfra_fixture_start_v1"
_ENTRY = "starting-report"


@dataclass(frozen=True)
class FixtureRunContext:
    scope: str
    generation: str
    data_root: Path


@dataclass(frozen=True)
class FixtureRunLineage:
    fixture_id: str
    original_sha256: str
    original_size: int
    metadata: storage.FixtureMetadata
    target_profile_key: str
    scope: str
    generation: str


@dataclass(frozen=True)
class StagedFixture:
    context: FixtureRunContext
    lineage: FixtureRunLineage
    profile: ReportProfile
    period: ReportPeriod
    source_path: Path
    inspection: starting_import.DocxInspection

    @property
    def stage(self):
        """The exact saved-original tuple accepted by render_section_setup."""
        return None, self.source_path, self.inspection

    @property
    def setup_stage_key(self) -> str:
        return setup_stage_key(self.profile, self.period)


@dataclass(frozen=True)
class RunFixture:
    """Validated run receipt without eagerly parsing the document again."""
    context: FixtureRunContext
    lineage: FixtureRunLineage
    source_path: Path


def setup_stage_key(profile: ReportProfile, period: ReportPeriod) -> str:
    # Use the actual production identity/signature, including existing profile
    # keys. Do not generate a parallel report_key or rename a saved profile.
    from app.monthly_report_editor import _signature
    return "report_setup_" + _signature((profile.contract, profile.key, period.key)) + "_stage"


def validate_run(context: FixtureRunContext) -> Path:
    """Reject missing, changed or reset context before a later UI/job handoff."""
    if (not isinstance(context, FixtureRunContext)
            or testing.scope() != context.scope
            or testing.generation() != context.generation
            or not context.scope or not context.generation):
        raise ValueError("Fixture work requires its original isolated scope and bound generation.")
    # data_dir enforces the existing reset lease and cannot create a missing
    # namespace while this generation is bound. Never accept an unscoped path.
    root = memory._data_dir()
    if (root != context.data_root or root.name != context.scope
            or root.parent.name != testing._BUCKET):
        raise OSError("Fixture work cannot fall back to ordinary report storage.")
    with storage._root(root) as directory:
        marker = storage._read_file(directory, testing._SENTINEL, 1024)
        if marker != (context.scope + "|" + context.generation).encode("ascii"):
            raise OSError("The isolated fixture generation changed; stale work was blocked.")
    return root


def _current_run(run_token: str) -> FixtureRunContext:
    scope, generation = testing.scope(), testing.generation()
    if scope is None or generation is None:
        raise ValueError("Enter isolated testing and bind its generation before staging a fixture.")
    # Derive the identity through the existing API rather than copying its
    # token hashing/version rules. The enclosing lease is restored on exit.
    with testing.isolated(run_token) as expected_scope:
        pass
    if scope != expected_scope:
        raise ValueError("The fixture run token does not match this isolated workspace.")
    context = FixtureRunContext(scope, generation, memory._data_dir())
    validate_run(context)
    return context


def _target(metadata, profile, requested_period):
    if not isinstance(profile, ReportProfile):
        raise ValueError("Choose an explicit production report profile for the fixture target.")
    target = metadata.target
    # Fixture metadata stores explicit canonical site keys, not filenames,
    # inferred aliases or display names. Order does not change membership.
    if (profile.contract != target.contract
            or membership_key(profile.facilities) != tuple(sorted(target.sites))):
        raise ValueError("The selected target contract/sites do not match this fixture's confirmed target.")
    year, month = map(int, target.month.split("-"))
    period = ReportPeriod(year, month)
    if requested_period is not None and requested_period != period:
        raise ValueError("The selected target month does not match this fixture's confirmed target.")
    return period


def stage_fixture(library: SharedFixtureLibrary, fixture_id: str, run_token: str,
                  target_profile: ReportProfile, *,
                  target_period: ReportPeriod | None = None) -> StagedFixture:
    """Copy and inspect one fixture inside an already-bound fresh namespace.

    No actor credential is required: the selected library is intentionally
    shared. A namespace can stage one fixture; choose a new run for another
    scenario. A failed inspection retains its disposable source for diagnosis
    until scoped reset, and cannot overwrite the shared original or a prior
    run's source. No expected content is injected into the inspected report.
    """
    context = _current_run(run_token)
    original = library.read(fixture_id)
    receipt = original.receipt
    period = _target(receipt.metadata, target_profile, target_period)
    digest = sha256(original.original).hexdigest()
    if (receipt.fixture_id != fixture_id or digest != receipt.original_sha256
            or len(original.original) != receipt.original_size):
        raise storage.VaultIntegrityError("Fixture original identity/hash changed before staging.")
    lineage = FixtureRunLineage(fixture_id, digest, len(original.original), receipt.metadata,
                                target_profile.key, context.scope, context.generation)
    marker = storage._json_bytes({"schema": 1, "kind": "fixture-starting-report",
                                  "scope": context.scope, "generation": context.generation})
    files = {"source.docx": original.original,
             "lineage.json": storage._json_bytes({"schema": 1, **asdict(lineage)})}
    added_bytes = sum(len(raw) for raw in files.values()) + len(
        storage.FixtureVault._transaction("fixture-starting-report", _ENTRY, files))
    from app.monthly_report_fixture_admission import admit_run_copy
    validate_run(context)
    with admit_run_copy(context, added_bytes):
        with storage._root(context.data_root) as root:
            with storage._marked_dir(root, _STAGING, marker, True) as directory:
                with storage._admission_lock(directory):
                    if set(os.listdir(directory)) - {storage._MARKER, storage._LOCK}:
                        raise ValueError("This workspace already staged a fixture; choose a fresh isolated run.")
                    storage.FixtureVault._install(
                        directory, _ENTRY, files,
                        lambda: validate_run(context), kind="fixture-starting-report",
                    )
    source = context.data_root / _STAGING / _ENTRY / "source.docx"
    validate_run(context)
    # Native parsing is exactly the production Starting report inspector. It
    # opens no external readers and does not construct or approve section plans.
    inspection = starting_import.inspect_docx(source)
    if inspection.sha256 != digest:
        raise storage.VaultIntegrityError("The inspected run copy does not match its fixture original.")
    validate_run(context)
    return StagedFixture(context, lineage, target_profile, period, source, inspection)


def read_run_fixture(library: SharedFixtureLibrary, run_token: str) -> RunFixture | None:
    """Recover only this generation's staged receipt, with original lineage.

    This does not restore an initial import over an already-saved draft. The
    caller checks the ordinary isolated report library before choosing whether
    to resume its unfinished Starting report review or normal draft recovery.
    """
    import json
    context = _current_run(run_token)
    marker = storage._json_bytes({"schema": 1, "kind": "fixture-starting-report",
                                  "scope": context.scope, "generation": context.generation})
    with storage._root(context.data_root) as root:
        if _STAGING not in os.listdir(root):
            return None
        with storage._marked_dir(root, _STAGING, marker, False) as directory:
            if set(os.listdir(directory)) != {storage._MARKER, storage._LOCK, _ENTRY}:
                raise storage.VaultIntegrityError("Interrupted fixture staging requires a fresh isolated run.")
            entry = os.open(_ENTRY, storage._DIRECTORY_FLAGS, dir_fd=directory)
            try:
                encoded = storage._read_file(entry, "lineage.json", 128 * 1024)
                try:
                    raw = json.loads(encoded)
                    fixture_id = storage._identifier(raw["fixture_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise storage.VaultIntegrityError("The fixture run lineage could not be verified.") from exc
                original = library.read(fixture_id)
                receipt = original.receipt
                lineage = FixtureRunLineage(fixture_id, receipt.original_sha256, receipt.original_size,
                                           receipt.metadata, raw.get("target_profile_key", ""),
                                           context.scope, context.generation)
                # JSON normalization preserves tuples/lists without accepting
                # altered source, target, expectations or old reset identities.
                expected = json.loads(storage._json_bytes({"schema": 1, **asdict(lineage)}))
                if raw != expected or not lineage.target_profile_key:
                    raise storage.VaultIntegrityError("The fixture run lineage does not match its shared original.")
                copied = storage._read_file(entry, "source.docx", starting_import.MAX_DOCX_BYTES)
                if (len(copied) != receipt.original_size
                        or sha256(copied).hexdigest() != receipt.original_sha256):
                    raise storage.VaultIntegrityError("The fixture run copy no longer matches its original.")
                files = {"source.docx": copied, "lineage.json": encoded}
                transaction = storage._read_file(entry, storage._TRANSACTION, 4096)
                if (set(os.listdir(entry)) != {*files, storage._TRANSACTION}
                        or transaction != storage.FixtureVault._transaction("fixture-starting-report", _ENTRY, files)):
                    raise storage.VaultIntegrityError("The fixture run commit record does not match.")
            finally:
                os.close(entry)
    validate_run(context)
    return RunFixture(context, lineage, context.data_root / _STAGING / _ENTRY / "source.docx")


def resume_fixture(record: RunFixture, target_profile: ReportProfile) -> StagedFixture:
    """Reinspect an unfinished initial import with the production inspector."""
    validate_run(record.context)
    period = _target(record.lineage.metadata, target_profile, None)
    if target_profile.key != record.lineage.target_profile_key:
        raise ValueError("The resumed fixture must retain its original target profile identity.")
    inspection = starting_import.inspect_docx(record.source_path)
    if inspection.sha256 != record.lineage.original_sha256:
        raise storage.VaultIntegrityError("The resumed fixture copy does not match its original.")
    validate_run(record.context)
    return StagedFixture(record.context, record.lineage, target_profile, period, record.source_path, inspection)
