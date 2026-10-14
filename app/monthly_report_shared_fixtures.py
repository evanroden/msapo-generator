"""Explicitly shared fixture storage for the hidden testing area.

This library deliberately has NO owner login or visitor authorization. Anyone
who can reach a route wired to it can list, upload, read, download and replay
its fixtures, including every original byte and all supplied metadata. Hiding
that route from navigation does not make its contents private or confidential.
Visitor contexts are ignored, so coworkers and agents see the same library.

The shared access policy and disk markers are separate from FixtureVault's
owner-only policy. No anonymous visitor is represented as an AuthorizedOwner.
Restrictive filesystem permissions protect against accidental local access;
they do not restrict visitors to a future shared application route.

Only the immutable native-DOCX storage engine is reused here. The explicit
existing root is never inferred from live report storage, environment settings
or the working directory. This module installs no UI, URL or importer, and
proves neither Render persistence nor run/reset isolation. There is no purge
operation; repeated uploads create distinct immutable fixture receipts.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os

from app import monthly_report_fixture_vault as storage


_FIXTURES = "_enfra_shared_fixtures_v1"
_RUNS = "_enfra_shared_fixture_runs_v1"


@dataclass(frozen=True)
class SharedAudience:
    """A fixed public access policy, never an authenticated person's identity."""

    audience: str = "all-visitors"
    authentication: str = "none"


SHARED_AUDIENCE = SharedAudience()


def _marker(bucket: str) -> bytes:
    return storage._json_bytes({
        "schema": 1, "bucket": bucket,
        "audience": SHARED_AUDIENCE.audience,
        "authentication": SHARED_AUDIENCE.authentication,
    })


class _SharedStorage(storage.FixtureVault):
    """Reuse immutable operations with an intentionally different access policy.

    The inherited operations still check the policy before an operation and
    before returning bytes or committing a new entry. The fixed shared policy
    grants all visitors; these checks do not authenticate a request.
    """

    def _authorize(self, context, request, expected=None):
        if expected is not None and expected != SHARED_AUDIENCE:
            raise storage.VaultIntegrityError("Shared fixture access policy changed during the operation.")
        return SHARED_AUDIENCE

    @contextmanager
    def _owner_directory(self, audience, *, runs=False, create=False):
        # Override the owner's storage hook without adopting any owner bucket.
        # Descriptor traversal and marker validation are the original engine's
        # no-follow primitives, including all intermediate root components.
        self._authorize(None, None, audience)
        bucket = _RUNS if runs else _FIXTURES
        with storage._root(self._root) as root:
            with storage._marked_dir(root, bucket, _marker(bucket), create) as directory:
                yield directory, self._root / bucket

    def list(self, context=None) -> storage.VaultListing:
        request = storage.AccessRequest("list")
        audience = self._authorize(context, request)
        result = storage.VaultListing(())
        with storage._root(self._root) as root:
            if _FIXTURES in os.listdir(root):
                with storage._marked_dir(root, _FIXTURES, _marker(_FIXTURES), False) as directory:
                    with storage._admission_lock(directory):
                        result, _ = self._scan(directory)
        self._authorize(context, request, audience)
        return result


class SharedFixtureLibrary:
    """All visitors share one explicitly rooted, immutable fixture library.

    ``visitor_context`` is accepted only so callers can pass their ordinary
    request context without inventing a shared login. It is intentionally
    ignored and grants no identity, ownership, isolation or access restriction.
    Metadata confirmation records a supplied assertion, not a verified actor.
    """

    audience = SHARED_AUDIENCE

    def __init__(self, storage_root: Path, *,
                 max_fixture_bytes: int = 32 * 1024 * 1024,
                 max_library_bytes: int = 128 * 1024 * 1024,
                 max_run_copy_bytes: int = 128 * 1024 * 1024):
        self._storage = _SharedStorage(
            storage_root,
            max_fixture_bytes=max_fixture_bytes,
            max_owner_bytes=max_library_bytes,
            max_run_copy_bytes=max_run_copy_bytes,
        )

    def list(self, *, visitor_context=None) -> storage.VaultListing:
        return self._storage.list(visitor_context)

    def upload(self, original: bytes, metadata: storage.FixtureMetadata, *,
               visitor_context=None) -> storage.FixtureReceipt:
        return self._storage.upload(visitor_context, original, metadata)

    def read(self, fixture_id: str, *, visitor_context=None) -> storage.FixtureOriginal:
        return self._storage.read(visitor_context, fixture_id)

    def download(self, fixture_id: str, *, visitor_context=None) -> bytes:
        """Return publicly shared bytes; this does not install a download URL."""
        return self._storage.download(visitor_context, fixture_id)

    def replay_copy(self, fixture_id: str, *, run_id: str, generation: str,
                    visitor_context=None) -> storage.ReplayCopy:
        """Create a separate byte copy, not an imported or reset-leased run."""
        return self._storage.replay_copy(visitor_context, fixture_id,
                                         run_id=run_id, generation=generation)
