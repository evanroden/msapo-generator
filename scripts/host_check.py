"""Check that the container this runs in can safely serve the app's data.

Run inside the app's container on any host (Render shell, or
`az containerapp exec` on Azure), from /app:

    python scripts/host_check.py

It tests what the app relies on, on the real data folder: owner-only folder
permissions, file locks between processes, SQLite in the journal mode the app
will choose, and the settings the app reads. It prints whether each setting is
present, never a value. The only writes are a temporary probe folder inside
the data folder, removed at the end; the app's own files are only read.

It also asks Anthropic's Models API about the configured model, a free call
that uses no tokens: it proves the key, the outbound network path and the
model in one go. --offline skips it.

Exit status: 0 when nothing failed (warnings allowed), 1 otherwise.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sqlite_storage import filesystem_type, journal_mode  # noqa: E402

SECRETS = ("ANTHROPIC_API_KEY", "SMARTSHEET_FORM_URL", "EXPENSE_ACCOUNT_DIRECTORS_JSON")
OPTIONAL_SECRETS = ("SMARTSHEET_API_TOKEN", "SMARTSHEET_SHEET_ID")
FIXED = ("EPC_DATA_DIR", "PDF_BACKEND", "ANTHROPIC_MODEL", "SMARTSHEET_FORM_FIELD_MAP_JSON",
         "SMARTSHEET_URL_PREFILL_ENABLED", "SMARTSHEET_PREFILL_MAX_URL_LENGTH", "SMARTSHEET_API_MODE",
         "SMARTSHEET_ALLOW_CUSTOM_API_BASE")
DATABASES = ("epc_memory.db", "smartsheet_submissions.db")
_HOLDER = """
import fcntl, sys
kind, path = sys.argv[1], sys.argv[2]
handle = open(path, "a+")
(fcntl.flock(handle, fcntl.LOCK_EX) if kind == "flock" else fcntl.lockf(handle, fcntl.LOCK_EX))
print("held", flush=True)
sys.stdin.readline()
"""


class Report:
    def __init__(self):
        self.failures = 0
        self.warnings = 0

    def line(self, status: str, text: str) -> None:
        if status == "FAIL":
            self.failures += 1
        elif status == "WARN":
            self.warnings += 1
        print(f"{status:<5} {text}", flush=True)


def _data_dir() -> Path:
    configured = os.getenv("EPC_DATA_DIR", "").strip()
    return Path(configured) if configured else Path("/test1")


def _lock_conflicts(kind: str, path: Path) -> bool:
    """True when a lock held by another process blocks this one, as the app needs."""
    import fcntl
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, kind, str(path)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        if holder.stdout.readline().strip() != "held":
            raise RuntimeError("the helper process could not take the lock")
        with open(path, "a+") as handle:
            try:
                if kind == "flock":
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError):
                return True
            return False
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=10)


def check_storage(report: Report, data: Path) -> None:
    kind = filesystem_type(data.resolve()) or "unknown"
    if not data.is_dir():
        report.line("FAIL", f"data folder {data} does not exist (is the share mounted?)")
        return
    report.line("PASS", f"data folder {data} ({kind})")
    usage = shutil.disk_usage(data)
    report.line("PASS" if usage.free > 1 << 30 else "WARN",
                f"free space in the data folder: {usage.free / (1 << 30):.1f} GiB")
    probe = data / f".host-check-{os.getpid()}"
    try:
        os.mkdir(probe, 0o700)
    except OSError as error:
        report.line("FAIL", f"cannot create a folder in the data folder: {error.strerror}")
        return
    try:
        os.chmod(probe, 0o700)
        mode = probe.stat().st_mode & 0o777
        report.line("PASS" if mode == 0o700 else "FAIL",
                    f"owner-only folders stay owner-only (got {mode:o}); the private stores require it")
        owner = probe.stat().st_uid
        report.line("PASS" if owner == os.getuid() else "FAIL",
                    f"new files belong to this user (uid {owner}, running as {os.getuid()})"
                    + ("" if owner == os.getuid() else "; turn root squash off on the share"))
        sample = probe / "file"
        sample.write_text("probe")
        os.chmod(sample, 0o600)
        report.line("PASS" if sample.stat().st_mode & 0o777 == 0o600 else "FAIL",
                    "owner-only files stay owner-only")
        for lock in ("flock", "lockf"):
            try:
                held = _lock_conflicts(lock, probe / f"{lock}.lock")
            except Exception as error:  # noqa: BLE001 - reported, not raised
                report.line("FAIL", f"{lock} lock test could not run: {error}")
                continue
            report.line("PASS" if held else "FAIL",
                        f"{lock} locks are honoured between processes"
                        + ("" if held else " (they are not: concurrent writers would collide)"))
        database = probe / "probe.db"
        wanted = journal_mode(database)
        connection = sqlite3.connect(database)
        try:
            actual = str(connection.execute(f"PRAGMA journal_mode={wanted}").fetchone()[0]).upper()
            connection.execute("CREATE TABLE t (x)")
            connection.execute("INSERT INTO t VALUES (1)")
            connection.commit()
            other = subprocess.run([sys.executable, "-c",
                                    "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute("
                                    "'SELECT count(*) FROM t').fetchone()[0])", str(database)],
                                   capture_output=True, text=True, timeout=30)
            visible = other.stdout.strip() == "1"
        finally:
            connection.close()
        safe = not (wanted == "WAL" and kind.startswith(("nfs", "cifs", "smb")))
        report.line("PASS" if actual == wanted and visible and safe else "FAIL",
                    f"SQLite works here in {actual} mode (chosen for {kind})"
                    + ("" if visible else "; another process could not read the write"))
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def check_databases(report: Report, data: Path) -> None:
    for name in DATABASES:
        path = data / name
        if not path.exists():
            report.line("INFO", f"{name}: not created yet (expected before the data is restored)")
            continue
        try:
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
            try:
                current = connection.execute("PRAGMA journal_mode").fetchone()[0].upper()
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            report.line("FAIL", f"{name}: cannot be read ({error})")
            continue
        wanted = journal_mode(path)
        status = "FAIL" if result != "ok" else ("PASS" if current == wanted else "WARN")
        note = "" if current == wanted else f"; the app switches it to {wanted} on next use (restart if it stays)"
        report.line(status, f"{name}: {current} mode, integrity {result}{note}")


def check_settings(report: Report) -> None:
    for name in SECRETS:
        report.line("PASS" if os.getenv(name, "").strip() else "FAIL", f"secret {name} is "
                    + ("set" if os.getenv(name, "").strip() else "missing"))
    for name in OPTIONAL_SECRETS:
        report.line("INFO", f"optional secret {name} is " + ("set" if os.getenv(name, "").strip() else "not set"))
    for name in FIXED:
        report.line("PASS" if os.getenv(name, "").strip() else "WARN",
                    f"setting {name} is " + ("set" if os.getenv(name, "").strip() else "not set (render.yaml has it)"))
    from app import contracts
    from app.config import account_director, director_config_problems
    accounts = contracts.contract_names()
    configured = sum(account_director(account) is not None for account in accounts)
    problems = director_config_problems(accounts)
    report.line("PASS" if configured and not problems else "WARN",
                f"expense directors configured for {configured} of {len(accounts)} account(s)"
                + ("" if configured else ": expense forms will name no director")
                + ("" if not problems else f"; {len(problems)} problem(s):"))
    for problem in problems:
        report.line("", "  " + problem)


def check_anthropic(report: Report, http_client=None) -> None:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return  # check_settings has already failed it
    from app import config
    model = os.getenv("ANTHROPIC_MODEL", config.ANTHROPIC_MODEL).strip()
    if not model:
        report.line("FAIL", "ANTHROPIC_MODEL is empty: every AI feature would fail")
        return
    import anthropic
    # Only status codes and error class names are printed: an error's own
    # message could echo request details.
    try:
        with anthropic.Anthropic(api_key=key, max_retries=0, timeout=30, http_client=http_client) as client:
            found = client.models.retrieve(model)
    except anthropic.AuthenticationError:
        report.line("FAIL", "Anthropic rejected ANTHROPIC_API_KEY (401): copy the key again")
    except anthropic.PermissionDeniedError:
        report.line("FAIL", f"the API key may not use model {model} (403)")
    except anthropic.NotFoundError:
        report.line("FAIL", f"model {model} is not available to this key (404): check ANTHROPIC_MODEL")
    except anthropic.RateLimitError:
        report.line("WARN", "Anthropic answered 429 (rate limited); the key and the network path work")
    except anthropic.APIStatusError as error:
        report.line("WARN" if error.status_code >= 500 else "FAIL",
                    f"Anthropic answered {error.status_code}"
                    + ("; a problem on Anthropic's side, try again" if error.status_code >= 500 else ""))
    except anthropic.APIConnectionError as error:
        cause = type(error.__cause__ or error).__name__
        report.line("FAIL", f"cannot reach the Anthropic API from this host ({cause}): allow outbound "
                    "https to api.anthropic.com, or set HTTPS_PROXY if the network needs a proxy")
    else:
        report.line("PASS", f"Anthropic API reachable from this host, key accepted, model {found.id} available")


def check_build(report: Report) -> None:
    from app.public_build import runtime_commit
    commit = runtime_commit()
    report.line("PASS" if commit else "WARN",
                f"About shows commit {commit}" if commit else
                "no build commit: About will say \"build identifier unavailable\" (build with APP_GIT_COMMIT)")
    office = shutil.which("libreoffice") or shutil.which("soffice")
    report.line("PASS" if office else "FAIL", f"LibreOffice: {office or 'not found'}")
    temporary = shutil.disk_usage(tempfile.gettempdir()).free
    report.line("INFO", f"free temporary space: {temporary / (1 << 30):.1f} GiB "
                "(a data-move archive must fit here)")
    revision = os.getenv("CONTAINER_APP_REVISION")
    if revision:
        report.line("INFO", f"Azure revision {revision}, replica {os.getenv('CONTAINER_APP_REPLICA_NAME', '?')}"
                    " (keep exactly one replica)")


def main(argv=()) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--offline", action="store_true", help="skip the call to Anthropic's API")
    args = parser.parse_args(list(argv))
    report = Report()
    data = _data_dir()
    print(f"Host check for {data}", flush=True)
    check_storage(report, data)
    check_databases(report, data)
    check_settings(report)
    if args.offline:
        report.line("INFO", "Anthropic API not checked (--offline)")
    else:
        check_anthropic(report)
    check_build(report)
    print(f"\n{report.failures} failure(s), {report.warnings} warning(s).")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
