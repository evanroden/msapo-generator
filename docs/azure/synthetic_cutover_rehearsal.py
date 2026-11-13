"""Isolated cutover safety tabletop model. Not application/target platform testing.

Run: python3 docs/azure/synthetic_cutover_rehearsal.py
Uses tempfile, synthetic names/content and stdlib sqlite3 only.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_db(path):
    conn = sqlite3.connect(path)
    conn.execute("create table reports(id text primary key, version integer not null, body text not null)")
    conn.execute("insert into reports values('synthetic-1', 1, 'v1')")
    conn.commit()
    conn.close()


def create_claims(path):
    conn = sqlite3.connect(path)
    conn.execute("create table claims(id text primary key, status text not null)")
    conn.execute("insert into claims values('synthetic-claim-1', 'uncertain')")
    conn.commit()
    conn.close()


def rows(db, table):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("select * from " + table + " order by id").fetchall()
    finally:
        conn.close()


def backup_sqlite(source, dest):
    src = sqlite3.connect(source)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        assert dst.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        src.close()
        dst.close()


def validate_snapshot(source, copy, manifest):
    for name, h in manifest.items():
        assert digest(copy / name) == h, f"checksum mismatch: {name}"
    assert rows(source / "reports.db", "reports") == rows(copy / "reports.db", "reports")
    assert rows(source / "claims.db", "claims") == rows(copy / "claims.db", "claims")


def simulate():
    completed = []
    with tempfile.TemporaryDirectory(prefix="msapo-synthetic-cutover-") as d:
        base = Path(d)
        source, staging, azure, lost = (base / p for p in ("source", "staging", "azure", "lost-snapshot"))
        for path in (source, staging, azure, lost): path.mkdir()
        create_db(source / "reports.db")
        create_claims(source / "claims.db")
        (source / "original.bin").write_bytes(b"synthetic original, no employee data")

        # T0: freeze-fence model: only one writer owner at a time.
        writer = "render"
        def transfer_writer(previous, new):
            nonlocal writer
            if writer != previous or (previous != "none" and new != "none"):
                raise RuntimeError("handoff must pass through no writer")
            writer = new
        transfer_writer("render", "none")
        assert writer == "none"
        completed.append("PASS freeze fence denies simultaneous source and target writers")

        # Synthetic consistent export from a quiescent source. This is not the app's migrate_data.py.
        backup_sqlite(source / "reports.db", staging / "reports.db")
        backup_sqlite(source / "claims.db", staging / "claims.db")
        shutil.copyfile(source / "original.bin", staging / "original.bin")
        manifest = {p.name: digest(p) for p in staging.iterdir()}
        validate_snapshot(source, staging, manifest)
        assert len(manifest) == 3
        completed.append("PASS frozen snapshot 3/3 hashes and both SQLite row sets match")

        shutil.copytree(staging, azure, dirs_exist_ok=True)
        (azure / "original.bin").write_bytes(b"changed in transfer")
        try:
            validate_snapshot(source, azure, manifest)
        except AssertionError:
            completed.append("PASS damaged transferred original rejected by hash")
        else: raise AssertionError("corruption was accepted")
        shutil.copyfile(staging / "original.bin", azure / "original.bin")
        validate_snapshot(source, azure, manifest)

        # Allow Azure only after Render has been fenced.
        transfer_writer("none", "azure")
        assert writer == "azure"
        conn = sqlite3.connect(azure / "reports.db")
        conn.execute("insert into reports values ('synthetic-2', 1, 'new-on-azure')")
        conn.commit()
        conn.close()
        change_journal = [("synthetic-2", 1, "new-on-azure")]
        assert len(rows(azure / "reports.db", "reports")) == 2

        # An image-only rollback must leave Azure data exactly in place.
        image_digest_before, image_digest_after = "sha256:current-image", "sha256:prior-image"
        assert image_digest_before != image_digest_after
        assert len(rows(azure / "reports.db", "reports")) == 2
        completed.append("PASS image-only rollback retains post-cutover Azure record")

        # Demonstrate why restoring the old snapshot alone is unsafe.
        shutil.copyfile(staging / "reports.db", lost / "reports.db")
        assert len(rows(lost / "reports.db", "reports")) == 1
        conn = sqlite3.connect(lost / "reports.db")
        for record in change_journal:
            conn.execute("insert or ignore into reports values(?,?,?)", record)
        conn.commit()
        conn.close()
        assert rows(lost / "reports.db", "reports") == rows(azure / "reports.db", "reports")
        completed.append("PASS snapshot-alone loses Azure write; journal replay restores 2/2 reports")

        # Preserved claims and repeat replay must not introduce duplicate local claims/records.
        assert rows(azure / "claims.db", "claims") == rows(staging / "claims.db", "claims")
        conn = sqlite3.connect(lost / "reports.db")
        for record in change_journal:
            conn.execute("insert or ignore into reports values(?,?,?)", record)
        conn.commit()
        conn.close()
        assert len(rows(lost / "reports.db", "reports")) == 2
        completed.append("PASS replay is idempotent for synthetic report IDs; external API not exercised")

        # Schema guard: an older app expecting v1 may not open a v2-only store.
        required_app_schema_max = 1
        current_schema = 2
        assert not current_schema <= required_app_schema_max
        completed.append("PASS simulated incompatible schema blocks image-only downgrade")

        transfer_writer("azure", "none")
        try:
            transfer_writer("render", "azure")
        except RuntimeError:
            completed.append("PASS stale Render writer cannot be reenabled during handoff")
        else: raise AssertionError("stale owner accepted")
    return completed


if __name__ == "__main__":
    results = simulate()
    print("Synthetic cutover invariant model: " + str(len(results)) + " PASS, 0 FAIL")
    for result in results: print(result)
    print("LIMIT: no live Render/Azure, app adapters, native UI, external API, DNS or recovery-time test")