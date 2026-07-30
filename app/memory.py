"""Contract-isolated learning with pluggable persistence backends."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Protocol

from app.adapter_loader import AdapterConfigurationError, load_adapter
from app.runtime import RuntimeSettings


SUGGEST_THRESHOLD = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_emails (
    contract TEXT NOT NULL,
    email TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, email)
);
CREATE TABLE IF NOT EXISTS contacts (
    contract TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, name, email)
);
CREATE TABLE IF NOT EXISTS vendor_contacts (
    contract TEXT NOT NULL,
    vendor TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, vendor, name, email)
);
"""


class MemoryBackend(Protocol):
    name: str

    def record_send(
        self,
        *,
        contract: str,
        admin_email: str | None = None,
        vendor: str | None = None,
        contact_name: str | None = None,
        contact_email: str | None = None,
    ) -> bool: ...

    def suggest_admin_emails(self, contract: str) -> list[str]: ...

    def suggest_contacts(self, contract: str) -> list[tuple[str, str]]: ...

    def vendor_reps(
        self, contract: str, vendor: str | None
    ) -> list[tuple[str, str]]: ...

    def diagnostic(self) -> Mapping[str, object]: ...


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _norm_name(name: str | None) -> str:
    return " ".join((name or "").split())


def _norm_vendor(vendor: str | None) -> str:
    return " ".join((vendor or "").split()).lower()


def _looks_like_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1] and " " not in email


class SQLiteMemoryBackend:
    name = "sqlite"

    def __init__(self, path: Path, *, threshold: int = SUGGEST_THRESHOLD) -> None:
        self.path = path
        self.threshold = threshold

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_SCHEMA)
        return conn

    def diagnostic(self) -> Mapping[str, object]:
        try:
            with closing(self._connect()) as conn:
                conn.execute("SELECT 1").fetchone()
            return {"name": self.name, "configured": True, "path": str(self.path)}
        except Exception as exc:  # noqa: BLE001
            return {
                "name": self.name,
                "configured": False,
                "path": str(self.path),
                "error": str(exc),
            }

    def record_send(
        self,
        *,
        contract: str,
        admin_email: str | None = None,
        vendor: str | None = None,
        contact_name: str | None = None,
        contact_email: str | None = None,
    ) -> bool:
        if not contract:
            return False
        now = time.time()
        admin = _norm_email(admin_email)
        name = _norm_name(contact_name)
        cemail = _norm_email(contact_email)
        vend = _norm_vendor(vendor)
        with closing(self._connect()) as conn, conn:
            if admin and _looks_like_email(admin):
                conn.execute(
                    "INSERT INTO admin_emails (contract,email,count,last_used) VALUES (?,?,1,?) "
                    "ON CONFLICT(contract,email) DO UPDATE SET count=count+1,last_used=?",
                    (contract, admin, now, now),
                )
            if name and cemail and _looks_like_email(cemail):
                conn.execute(
                    "INSERT INTO contacts (contract,name,email,count,last_used) VALUES (?,?,?,1,?) "
                    "ON CONFLICT(contract,name,email) DO UPDATE SET count=count+1,last_used=?",
                    (contract, name, cemail, now, now),
                )
                if vend:
                    conn.execute(
                        "INSERT INTO vendor_contacts (contract,vendor,name,email,count,last_used) "
                        "VALUES (?,?,?,?,1,?) ON CONFLICT(contract,vendor,name,email) "
                        "DO UPDATE SET count=count+1,last_used=?",
                        (contract, vend, name, cemail, now, now),
                    )
        return True

    def suggest_admin_emails(self, contract: str) -> list[str]:
        if not contract:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT email FROM admin_emails WHERE contract=? AND count>=? "
                "ORDER BY count DESC,last_used DESC",
                (contract, self.threshold),
            ).fetchall()
        return [row[0] for row in rows]

    def suggest_contacts(self, contract: str) -> list[tuple[str, str]]:
        if not contract:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT name,email FROM contacts WHERE contract=? AND count>=? "
                "ORDER BY count DESC,last_used DESC",
                (contract, self.threshold),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def vendor_reps(self, contract: str, vendor: str | None) -> list[tuple[str, str]]:
        vend = _norm_vendor(vendor)
        if not contract or not vend:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT name,email FROM vendor_contacts WHERE contract=? AND vendor=? "
                "ORDER BY count DESC,last_used DESC",
                (contract, vend),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]


class DisabledMemoryBackend:
    name = "disabled"

    def diagnostic(self) -> Mapping[str, object]:
        return {"name": self.name, "configured": True}

    def record_send(self, **_: object) -> bool:
        return False

    def suggest_admin_emails(self, contract: str) -> list[str]:
        return []

    def suggest_contacts(self, contract: str) -> list[tuple[str, str]]:
        return []

    def vendor_reps(self, contract: str, vendor: str | None) -> list[tuple[str, str]]:
        return []


def _validate_backend(backend: object) -> MemoryBackend:
    methods = (
        "record_send",
        "suggest_admin_emails",
        "suggest_contacts",
        "vendor_reps",
        "diagnostic",
    )
    missing = [name for name in methods if not callable(getattr(backend, name, None))]
    if missing or not getattr(backend, "name", None):
        raise AdapterConfigurationError(
            "Memory backend must expose a name and methods: " + ", ".join(methods)
        )
    return backend  # type: ignore[return-value]


def _build_backend(env: Mapping[str, str]) -> MemoryBackend:
    name = (env.get("EPC_MEMORY_BACKEND") or "sqlite").strip().lower()
    if name == "sqlite":
        settings = RuntimeSettings.from_environment(env)
        settings.ensure_directories()
        return _validate_backend(
            SQLiteMemoryBackend(settings.data_dir / "epc_memory.db")
        )
    if name in {"none", "disabled"}:
        return _validate_backend(DisabledMemoryBackend())
    if name == "custom":
        backend = load_adapter(
            env.get("EPC_MEMORY_ADAPTER", ""),
            kind="memory",
            required_methods=(
                "record_send",
                "suggest_admin_emails",
                "suggest_contacts",
                "vendor_reps",
                "diagnostic",
            ),
            env=env,
        )
        return _validate_backend(backend)
    raise AdapterConfigurationError(
        f"Unknown EPC_MEMORY_BACKEND {name!r}. Use sqlite, disabled, or custom."
    )


@lru_cache(maxsize=1)
def _default_backend() -> MemoryBackend:
    return _build_backend(dict(os.environ))


def reset_backend_cache() -> None:
    _default_backend.cache_clear()


def get_memory_backend(env: Mapping[str, str] | None = None) -> MemoryBackend:
    return _default_backend() if env is None else _build_backend(dict(env))


def record_send(**kwargs) -> bool:
    try:
        return get_memory_backend().record_send(**kwargs)
    except Exception:
        return False


def suggest_admin_emails(contract: str) -> list[str]:
    try:
        return get_memory_backend().suggest_admin_emails(contract)
    except Exception:
        return []


def suggest_contacts(contract: str) -> list[tuple[str, str]]:
    try:
        return get_memory_backend().suggest_contacts(contract)
    except Exception:
        return []


def vendor_reps(contract: str, vendor: str | None) -> list[tuple[str, str]]:
    try:
        return get_memory_backend().vendor_reps(contract, vendor)
    except Exception:
        return []
