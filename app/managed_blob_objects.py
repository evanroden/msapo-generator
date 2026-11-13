"""Candidate Azure Blob object boundary: opaque references, never POSIX paths.

Only the original/source/artifact class of immutable bytes belongs here.
Disposable previews and converter scratch files remain temporary on each worker.
No new runtime adapter is selected merely by installing this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_BLOB_BYTES = 512 * 1024 * 1024


class BlobIntegrityError(RuntimeError):
    """The stored object is absent, corrupt, or outside the requested scope."""


class BlobStoreUnavailable(RuntimeError):
    """No trustworthy response was received from the object service."""


@dataclass(frozen=True)
class ObjectScope:
    namespace: str
    contract: str
    site: str = ""
    user_scope: str = ""

    def __post_init__(self) -> None:
        for label in ("namespace", "contract", "site", "user_scope"):
            value = getattr(self, label)
            if (not isinstance(value, str) or len(value) > 256
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise ValueError(f"Invalid object {label}.")
        if not self.namespace or not self.contract:
            raise ValueError("Object namespace and contract are required.")

    @property
    def digest(self) -> str:
        # Names in storage contain NO customer, site, person or device text.
        raw = json.dumps(
            [self.namespace, self.contract, self.site, self.user_scope],
            ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BlobReference:
    key: str
    sha256: str
    length: int
    scope_digest: str


class AzureBlobObjects:
    """Immutable scoped objects via an injected Azure Blob ContainerClient.

    Use an ENFRA-authorized client with managed identity, private networking and
    least-privilege access. The SDK is deliberately an injection, so the Render
    default requires neither an Azure account nor azure-storage-blob.
    """

    def __init__(self, container_client):
        self._container = container_client

    @staticmethod
    def _name(scope: ObjectScope, sha256: str) -> str:
        return f"v1/{scope.digest}/{sha256[:2]}/{sha256}"

    @staticmethod
    def _valid_reference(scope: ObjectScope, ref: BlobReference) -> bool:
        return (
            isinstance(ref, BlobReference)
            and isinstance(ref.sha256, str)
            and len(ref.sha256) == 64
            and all(ch in "0123456789abcdef" for ch in ref.sha256)
            and type(ref.length) is int
            and 0 <= ref.length <= MAX_BLOB_BYTES
            and ref.scope_digest == scope.digest
            and ref.key == AzureBlobObjects._name(scope, ref.sha256)
        )

    def put(self, scope: ObjectScope, raw: bytes) -> BlobReference:
        if not isinstance(scope, ObjectScope):
            raise TypeError("ObjectScope is required.")
        if not isinstance(raw, bytes) or len(raw) > MAX_BLOB_BYTES:
            raise ValueError("A bounded byte payload is required.")
        digest = hashlib.sha256(raw).hexdigest()
        reference = BlobReference(self._name(scope, digest), digest, len(raw), scope.digest)
        try:
            client = self._container.get_blob_client(reference.key)
            # A read-before-write is not an atomic create. overwrite=False uses
            # Blob's conditional creation; a racing identical upload is safe.
            client.upload_blob(
                raw, overwrite=False, metadata={"sha256": digest, "length": str(len(raw))}
            )
        except Exception as exc:
            # Only a definite BlobAlreadyExists is an idempotent conflict.
            # Timeout, 409 lease conflicts, 403 and 5xx are NEVER "already saved".
            code = str(getattr(exc, "error_code", "")).replace("_", "").lower()
            if "blobalreadyexists" not in code:
                raise BlobStoreUnavailable(
                    "Object upload was not confirmed; retry by object digest after recovery."
                ) from exc
        # Verify bytes under the expected scope before an authoritative DB row
        # can reference them. A failure must not silently publish metadata.
        if self.read(scope, reference) != raw:
            raise BlobIntegrityError("The immutable object did not round-trip.")
        return reference

    def read(self, scope: ObjectScope, reference: BlobReference) -> bytes:
        if not isinstance(scope, ObjectScope) or not self._valid_reference(scope, reference):
            raise BlobIntegrityError("Object reference does not match its requested scope.")
        try:
            raw = self._container.get_blob_client(reference.key).download_blob().readall()
        except Exception as exc:
            raise BlobStoreUnavailable("Could not retrieve the immutable object.") from exc
        if (not isinstance(raw, bytes) or len(raw) != reference.length
                or hashlib.sha256(raw).hexdigest() != reference.sha256):
            raise BlobIntegrityError("Object length or SHA-256 does not match its receipt.")
        return raw
