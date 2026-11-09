"""Check an Azure Container Apps configuration against what this app needs.

Run from a clone of this repository, for example in Azure Cloud Shell, which
has git, python3 and the az command (no other packages are needed):

    az containerapp show -g <group> -n <app> -o json > app.json
    az containerapp auth show -g <group> -n <app> -o json > auth.json
    python3 scripts/azure_config_check.py app.json --auth auth.json

The expected settings come from this repository: the environment in
render.yaml, the port and health path the Dockerfile serves, and the storage
the app's data folder relies on. It reads the two files and changes nothing in
Azure. It prints setting and secret names, never their values; image names
appear without the registry.

Exit status: 0 when nothing failed (warnings allowed), 1 otherwise, 2 when an
input cannot be read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.host_check import OPTIONAL_SECRETS, Report  # noqa: E402

RENDER_YAML = ROOT / "render.yaml"
PORT = 8501
HEALTH_PATH = "/_stcore/health"
# Render's starter plan, which the export tests cap themselves to.
MIN_CPU, MIN_MEMORY_GIB = 0.5, 0.5
STALE_WHEN_SET = ("APP_GIT_COMMIT", "RENDER_GIT_COMMIT")
JOURNAL_MODES = ("wal", "delete")  # what app/sqlite_storage.py honours; anything else is ignored
# Microsoft's issuers that accept accounts from more than one organisation.
ANY_TENANT = ("common", "organizations", "consumers")


class InputError(Exception):
    pass


def _scalar(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return json.loads(text)
    return text.split(" #", 1)[0].strip()


def render_env(path: Path = RENDER_YAML) -> list[tuple[str, str | None]]:
    """(name, value) for each envVars entry in render.yaml; None for a secret.

    A small reader for this file's own shape, so the check needs nothing
    beyond the standard library.
    """
    entries: list[list] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = re.fullmatch(r"-\s*key:\s*(\S+)", stripped)
        if key:
            entries.append([key.group(1), None, False])
            continue
        field = re.fullmatch(r"(value|sync):\s*(.*)", stripped)
        if field and entries:
            if field.group(1) == "value":
                entries[-1][1] = _scalar(field.group(2))
            else:
                entries[-1][2] = _scalar(field.group(2)) == "false"
    for name, value, secret in entries:
        if (value is None) != secret:
            raise ValueError(f"render.yaml entry {name} must have either a value or sync: false")
    return [(name, value) for name, value, _secret in entries]


def _load(path: str) -> dict:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as error:
        raise InputError(f"cannot read {path}: {error}") from None
    if not isinstance(data, dict):
        raise InputError(f"{path} is not a JSON object (use -o json)")
    properties = data.get("properties")
    return properties if isinstance(properties, dict) else data


def _gib(memory: str) -> float | None:
    match = re.fullmatch(r"\s*([0-9.]+)\s*(Gi|Mi|G|M)?\s*", str(memory))
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "Gi"
    return number / 1024 if unit.startswith("M") else number


def _same(actual: str, expected: str) -> bool:
    """Equal, or the same JSON object written with different spacing."""
    if actual == expected:
        return True
    if not expected.lstrip().startswith(("{", "[")):
        return False
    try:
        return json.loads(actual) == json.loads(expected)
    except ValueError:
        return False


def check_status(report: Report, app: dict) -> None:
    state = app.get("provisioningState") or "unknown"
    running = app.get("runningStatus") or "unknown"
    report.line("INFO" if state == "Succeeded" else "WARN", f"provisioning {state}, running status {running}")
    latest, ready = app.get("latestRevisionName"), app.get("latestReadyRevisionName")
    if latest and ready and latest != ready:
        report.line("WARN", "the latest revision is not the latest ready one: it may have failed to start "
                    "(see az containerapp logs show)")


def check_revisions_and_scale(report: Report, config: dict, template: dict) -> None:
    mode = str(config.get("activeRevisionsMode") or "Single")
    report.line("PASS" if mode.lower() == "single" else "FAIL",
                f"revisions mode {mode}" + ("" if mode.lower() == "single" else
                                            ": two revisions could serve and write the data at once"))
    scale = template.get("scale") or {}
    low = scale.get("minReplicas") or 0
    high = scale.get("maxReplicas") or 10  # Azure's defaults
    report.line("PASS" if high == 1 else "FAIL", f"maximum replicas {high}" + (
        "" if high == 1 else ": the app is single-instance only (SQLite files, in-memory sessions); set 1"))
    report.line("PASS" if low == 1 else "WARN", f"minimum replicas {low}" + (
        "" if low == 1 else ": Azure stops the app when idle and the next visitor waits for it to start; set 1"))


def check_ingress(report: Report, config: dict) -> None:
    ingress = config.get("ingress")
    if not ingress:
        report.line("FAIL", "no ingress: nobody can reach the app")
        return
    report.line("INFO", "ingress is " + ("external: reachable from the internet, so sign-in must be on"
                                         if ingress.get("external") else "internal: virtual network only"))
    port = ingress.get("targetPort")
    report.line("PASS" if port == PORT else "FAIL", f"ingress target port {port}"
                + ("" if port == PORT else f": the app listens on {PORT}"))
    transport = str(ingress.get("transport") or "Auto")
    fine = transport.lower() in ("auto", "http")
    report.line("PASS" if fine else "FAIL", f"ingress transport {transport}"
                + ("" if fine else ": Streamlit needs HTTP/1.1 and WebSockets; use Auto"))
    insecure = bool(ingress.get("allowInsecure"))
    report.line("WARN" if insecure else "PASS", "plain http is " + ("allowed" if insecure else "redirected to https"))


def _app_container(template: dict, data_dir: str) -> dict | None:
    containers = template.get("containers") or []
    for container in containers:
        if any(mount.get("mountPath") == data_dir for mount in container.get("volumeMounts") or []):
            return container
    return containers[0] if containers else None


def check_container(report: Report, template: dict, data_dir: str) -> dict:
    container = _app_container(template, data_dir)
    if container is None:
        report.line("FAIL", "no container in the template")
        return {}
    image = str(container.get("image") or "")
    name = image.rsplit("/", 1)[-1]
    tag = name.split("@", 1)[0].rpartition(":")[2] if ":" in name.split("@", 1)[0] else ""
    pinned = "@" in name or (tag and tag != "latest")
    report.line("PASS" if pinned else "WARN", f"image {name or '(none)'}"
                + ("" if pinned else ": tag each build (for example with the commit) so a rollback is unambiguous"))
    resources = container.get("resources") or {}
    cpu = float(resources.get("cpu") or 0)
    memory = _gib(resources.get("memory") or "0")
    enough = cpu >= MIN_CPU and (memory or 0) >= MIN_MEMORY_GIB
    report.line("PASS" if enough else "FAIL", f"{cpu:g} CPU, {resources.get('memory') or 'no'} memory"
                + ("" if enough else ": less than Render's starter plan (0.5 CPU, 512 MB); exports may fail"))
    probes = container.get("probes") or []
    if not probes:
        report.line("WARN", f"no health probes: Azure only checks that port {PORT} accepts connections; "
                    f"add liveness and readiness probes on {HEALTH_PATH}")
    for probe in probes:
        kind = probe.get("type") or "probe"
        http = probe.get("httpGet") or {}
        if http.get("port") not in (None, PORT):
            report.line("FAIL", f"{kind} probe checks port {http.get('port')}; the app listens on {PORT}")
        elif http.get("path") == HEALTH_PATH:
            report.line("PASS", f"{kind} probe on {HEALTH_PATH}")
        else:
            report.line("WARN", f"{kind} probe does not use {HEALTH_PATH}")
    return container


def check_storage(report: Report, template: dict, container: dict, data_dir: str) -> None:
    mount = next((mount for mount in container.get("volumeMounts") or [] if mount.get("mountPath") == data_dir), None)
    if mount is None:
        report.line("FAIL", f"nothing is mounted at {data_dir}: the data would be lost on every restart")
        return
    volume = next((volume for volume in template.get("volumes") or []
                   if volume.get("name") == mount.get("volumeName")), {})
    kind = str(volume.get("storageType") or "EmptyDir")
    if kind == "NfsAzureFile":
        report.line("PASS", f"{data_dir} is an NFS Azure Files share ({volume.get('storageName') or 'unnamed'})")
    elif kind == "AzureFile":
        report.line("FAIL", f"{data_dir} is an SMB Azure Files share: owner-only permissions and hard links, "
                    "which the app's data needs, do not work there; use an NFS share")
    else:
        report.line("FAIL", f"{data_dir} is {kind} storage: it is lost when the replica restarts")


def check_environment(report: Report, config: dict, container: dict,
                      expected: list[tuple[str, str | None]]) -> None:
    env = container.get("env") or []
    by_name: dict[str, dict] = {}
    for item in env:
        if item.get("name") in by_name:
            report.line("WARN", f"setting {item.get('name')} is listed more than once")
        by_name[str(item.get("name"))] = item
    secrets = {str(secret.get("name")): secret for secret in config.get("secrets") or []}
    for name, value in expected:
        item = by_name.get(name)
        if value is None:
            _check_secret(report, name, item, secrets)
            continue
        shown = f" (render.yaml: {value})" if len(value) <= 40 else " (see render.yaml)"
        if item is None:
            report.line("FAIL", f"setting {name} is missing{shown}")
        elif "value" not in item:
            report.line("WARN", f"setting {name} comes from a secret; render.yaml has a fixed value{shown}")
        elif not _same(str(item.get("value")), value):
            report.line("FAIL", f"setting {name} differs from render.yaml{shown}")
        else:
            report.line("PASS", f"setting {name} matches render.yaml")
    journal = by_name.get("EPC_SQLITE_JOURNAL_MODE")
    mode = str(journal.get("value") or "").strip().lower() if journal else ""
    if journal is None:
        report.line("INFO", "EPC_SQLITE_JOURNAL_MODE is not set: the app detects the NFS share and uses "
                    "SQLite's rollback journal (host_check.py confirms it)")
    elif "value" not in journal:
        report.line("WARN", "EPC_SQLITE_JOURNAL_MODE comes from a secret, so its value cannot be checked "
                    "here; set it as a plain value (delete), and check the mode with host_check.py")
    elif mode == "delete":
        report.line("PASS", "EPC_SQLITE_JOURNAL_MODE pins SQLite's rollback journal")
    elif mode == "wal":
        report.line("FAIL", "EPC_SQLITE_JOURNAL_MODE must be delete on a network share")
    else:
        report.line("WARN", f"EPC_SQLITE_JOURNAL_MODE has a value the app ignores (it reads only "
                    f"{' or '.join(JOURNAL_MODES)}); it detects the share instead")
    for name in STALE_WHEN_SET:
        if name in by_name:
            report.line("WARN", f"{name} is an app setting: it goes stale when the image changes; "
                        "pass APP_GIT_COMMIT as a build argument instead")
    known = {name for name, _value in expected} | {"EPC_SQLITE_JOURNAL_MODE", *STALE_WHEN_SET}
    extra = sorted(set(by_name) - known)
    if extra:
        report.line("INFO", "also set: " + ", ".join(extra))
    used = {str(item.get("secretRef")) for item in env if item.get("secretRef")}
    unused = sorted(set(secrets) - used)
    if unused:
        report.line("INFO", "secrets no setting uses: " + ", ".join(unused))


def _check_secret(report: Report, name: str, item: dict | None, secrets: dict) -> None:
    if item is None:
        if name in OPTIONAL_SECRETS:
            report.line("INFO", f"optional secret {name} is not set (only needed for the Smartsheet API)")
        else:
            report.line("FAIL", f"secret {name} is missing")
        return
    if "value" in item:
        report.line("FAIL", f"secret {name} is a plain value that anyone who can read the app's settings "
                    "sees; store it in Key Vault and use secretRef")
        return
    reference = str(item.get("secretRef") or "")
    secret = secrets.get(reference)
    if secret is None:
        report.line("FAIL", f"secret {name} refers to {reference or 'nothing'}, which the app does not define")
    elif secret.get("keyVaultUrl"):
        report.line("PASS", f"secret {name} comes from Key Vault ({reference})")
    else:
        report.line("WARN", f"secret {name} is stored in the app ({reference}) rather than in Key Vault")


def check_sign_in(report: Report, auth: dict | None) -> None:
    if auth is None:
        report.line("INFO", "sign-in not checked: pass --auth with the output of az containerapp auth show")
        return
    enabled = (auth.get("platform") or {}).get("enabled") is True
    report.line("PASS" if enabled else "FAIL", "built-in sign-in is " + ("on" if enabled else
                "off: the app has no sign-in of its own, so anyone with the address could use it"))
    validation = auth.get("globalValidation") or {}
    action = validation.get("unauthenticatedClientAction")
    if action in ("RedirectToLoginPage", "Return401", "Return403"):
        report.line("PASS", f"signed-out visitors are refused ({action})")
    elif action == "AllowAnonymous":
        report.line("FAIL", "signed-out visitors reach the app (AllowAnonymous); use RedirectToLoginPage")
    else:
        report.line("WARN", "what signed-out visitors get is not set; use RedirectToLoginPage")
    skipped = [str(path) for path in validation.get("excludedPaths") or [] if str(path).rstrip("/") != HEALTH_PATH]
    if skipped:
        report.line("FAIL", "sign-in is skipped for " + ", ".join(skipped)
                    + f": the app has no sign-in of its own; exclude nothing but {HEALTH_PATH}")
    providers = auth.get("identityProviders") or {}
    entra = providers.get("azureActiveDirectory")
    report.line("PASS" if _provider_on(entra) else "FAIL", "Microsoft Entra ID sign-in is "
                + ("configured" if _provider_on(entra) else "not configured"))
    if _provider_on(entra):
        issuer = str(entra["registration"].get("openIdIssuer") or "")
        tenant = urlparse(issuer).path.strip("/").split("/")[0].lower()
        if not tenant:
            report.line("WARN", "the Entra issuer is not set: check that only the company's tenant can sign in")
        elif tenant in ANY_TENANT:
            report.line("FAIL", f"Entra accepts accounts from any organisation (/{tenant}/); "
                        "use the company tenant's issuer")
        else:
            report.line("PASS", "Entra accepts only the accounts of one tenant")
    others = []
    for name, provider in providers.items():
        if name == "customOpenIdConnectProviders" and isinstance(provider, dict):
            others += [f"{name}.{key}" for key, custom in provider.items() if _provider_on(custom)]
        elif name != "azureActiveDirectory" and _provider_on(provider):
            others.append(name)
    if others:
        report.line("FAIL", "other sign-in providers are on (" + ", ".join(sorted(others))
                    + "): people outside the company could sign in")
    https = (auth.get("httpSettings") or {}).get("requireHttps", True)
    report.line("PASS" if https is not False else "WARN", "sign-in requires https" if https is not False
                else "sign-in allows plain http")


def _provider_on(provider) -> bool:
    """Configured (it has a registration) and not switched off."""
    return (isinstance(provider, dict) and isinstance(provider.get("registration"), dict)
            and bool(provider["registration"]) and provider.get("enabled") is not False)


def run(app_path: str, auth_path: str | None = None) -> int:
    app = _load(app_path)
    config, template = app.get("configuration"), app.get("template")
    if not isinstance(config, dict) or not isinstance(template, dict):
        raise InputError(f"{app_path} is not a container app (use az containerapp show -o json)")
    auth = _load(auth_path) if auth_path else None
    expected = render_env()
    data_dir = dict(expected).get("EPC_DATA_DIR") or "/test1"
    report = Report()
    check_status(report, app)
    check_revisions_and_scale(report, config, template)
    check_ingress(report, config)
    container = check_container(report, template, data_dir)
    if container:
        check_storage(report, template, container, data_dir)
        check_environment(report, config, container, expected)
    check_sign_in(report, auth)
    print(f"\n{report.failures} failure(s), {report.warnings} warning(s).")
    return 1 if report.failures else 0


def main(argv=()) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("app", help="output of az containerapp show -o json ('-' reads standard input)")
    parser.add_argument("--auth", help="output of az containerapp auth show -o json")
    args = parser.parse_args(list(argv))
    try:
        return run(args.app, args.auth)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
