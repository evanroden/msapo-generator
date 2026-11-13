"""The Azure configuration check holds a container app to what the app needs.

Every configuration here is synthetic: placeholder IDs, example registry and
vault names, no real settings.
"""
import ast
import copy
import io
import json
import sys
from pathlib import Path

import pytest

from scripts import azure_config_check
from scripts.azure_config_check import render_env

ROOT = Path(__file__).resolve().parents[1]
ZERO_ID = "00000000-0000-0000-0000-000000000000"
IDENTITY = (f"/subscriptions/{ZERO_ID}/resourceGroups/rg-example/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/id-example")
PLAIN_SECRET = "synthetic-secret-NEVER-PRINT-ME"


def planned_app():
    env, secrets = [], []
    for name, value in render_env():
        if value is None:
            reference = name.lower().replace("_", "-")
            env.append({"name": name, "secretRef": reference})
            secrets.append({"name": reference, "identity": IDENTITY,
                            "keyVaultUrl": f"https://kv-example.vault.azure.net/secrets/{reference}"})
        else:
            env.append({"name": name, "value": value})
    health = {"path": "/_stcore/health", "port": 8501}
    return {
        "id": f"/subscriptions/{ZERO_ID}/resourceGroups/rg-example/providers/Microsoft.App/containerApps/ca-example",
        "name": "ca-example",
        "properties": {
            "provisioningState": "Succeeded",
            "runningStatus": "Running",
            "latestRevisionName": "ca-example--0000001",
            "latestReadyRevisionName": "ca-example--0000001",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {"external": True, "targetPort": 8501, "transport": "Auto", "allowInsecure": False,
                            "fqdn": "ca-example.example.invalid"},
                "registries": [{"server": "example.azurecr.io", "identity": IDENTITY}],
                "secrets": secrets,
            },
            "template": {
                "containers": [{
                    "name": "msapo",
                    "image": "example.azurecr.io/msapo-generator:0000001",
                    "env": env,
                    "resources": {"cpu": 1.0, "memory": "2Gi"},
                    "probes": [{"type": "Liveness", "httpGet": dict(health)},
                               {"type": "Readiness", "httpGet": dict(health)}],
                    "volumeMounts": [{"volumeName": "epcdata", "mountPath": "/test1"}],
                }],
                "scale": {"minReplicas": 1, "maxReplicas": 1},
                "volumes": [{"name": "epcdata", "storageType": "NfsAzureFile", "storageName": "epcdata"}],
            },
        },
    }


PLANNED_AUTH = {"name": "current", "properties": {
    "platform": {"enabled": True},
    "globalValidation": {"unauthenticatedClientAction": "RedirectToLoginPage",
                         "redirectToProvider": "azureactivedirectory"},
    "identityProviders": {"azureActiveDirectory": {"enabled": True, "registration": {
        "clientId": ZERO_ID, "openIdIssuer": f"https://login.microsoftonline.com/{ZERO_ID}/v2.0"}}},
    "httpSettings": {"requireHttps": True},
}}


def check(tmp_path, capsys, app, auth=PLANNED_AUTH):
    (tmp_path / "app.json").write_text(json.dumps(app))
    args = [str(tmp_path / "app.json")]
    if auth is not None:
        (tmp_path / "auth.json").write_text(json.dumps(auth))
        args += ["--auth", str(tmp_path / "auth.json")]
    code = azure_config_check.main(args)
    return code, capsys.readouterr().out


def _container(app):
    return app["properties"]["template"]["containers"][0]


def _env(app, name):
    return next(item for item in _container(app)["env"] if item["name"] == name)


def test_the_planned_configuration_passes_and_prints_no_ids(tmp_path, capsys):
    code, out = check(tmp_path, capsys, planned_app())
    assert code == 0, out
    statuses = {line.split()[0] for line in out.splitlines() if line.strip() and not line.startswith(("0 ", "\n"))}
    assert statuses <= {"PASS", "INFO", "0"}, out
    for private in (ZERO_ID, "example.azurecr.io", "kv-example", "vault.azure.net", "example.invalid"):
        assert private not in out
    assert "PASS  /test1 is an NFS Azure Files share (epcdata)" in out
    assert "PASS  secret ANTHROPIC_API_KEY comes from Key Vault (anthropic-api-key)" in out
    assert "PASS  setting SMARTSHEET_FORM_FIELD_MAP_JSON matches render.yaml" in out
    assert "PASS  signed-out visitors are refused (RedirectToLoginPage)" in out


def _set(path, value):
    def change(app):
        target = app["properties"]
        for key in path[:-1]:
            target = target[key]
        if value is None:
            target.pop(path[-1], None)
        else:
            target[path[-1]] = value
    return change


def _container_set(key, value):
    def change(app):
        if value is None:
            _container(app).pop(key, None)
        else:
            _container(app)[key] = value
    return change


def _env_set(name, item):
    def change(app):
        env = _container(app)["env"]
        env[:] = [entry for entry in env if entry["name"] != name] + ([dict(item, name=name)] if item else [])
    return change


def _secret_set(reference, **fields):
    def change(app):
        secret = next(s for s in app["properties"]["configuration"]["secrets"] if s["name"] == reference)
        secret.pop("keyVaultUrl")
        secret.update(fields)
    return change


DEFECTS = {
    "multiple revisions": (_set(["configuration", "activeRevisionsMode"], "Multiple"),
                           "FAIL  revisions mode Multiple: two revisions could serve and write the data at once"),
    "several replicas": (_set(["template", "scale", "maxReplicas"], 3), "FAIL  maximum replicas 3"),
    "no scale": (_set(["template", "scale"], None), "FAIL  maximum replicas 10"),
    "scale to zero": (_set(["template", "scale", "minReplicas"], 0), "WARN  minimum replicas 0"),
    "no ingress": (_set(["configuration", "ingress"], None), "FAIL  no ingress"),
    "wrong port": (_set(["configuration", "ingress", "targetPort"], 80),
                   "FAIL  ingress target port 80: the app listens on 8501"),
    "http2 transport": (_set(["configuration", "ingress", "transport"], "Http2"), "FAIL  ingress transport Http2"),
    "plain http": (_set(["configuration", "ingress", "allowInsecure"], True), "WARN  plain http is allowed"),
    "smb share": (_set(["template", "volumes"], [{"name": "epcdata", "storageType": "AzureFile"}]),
                  "FAIL  /test1 is an SMB Azure Files share"),
    "temporary disk": (_set(["template", "volumes"], [{"name": "epcdata", "storageType": "EmptyDir"}]),
                       "FAIL  /test1 is EmptyDir storage: it is lost when the replica restarts"),
    "no mount": (_container_set("volumeMounts", None), "FAIL  nothing is mounted at /test1"),
    "too small": (_container_set("resources", {"cpu": 0.25, "memory": "0.5Gi"}), "FAIL  0.25 CPU, 0.5Gi memory"),
    "no probes": (_container_set("probes", None), "WARN  no health probes"),
    "probe path": (_container_set("probes", [{"type": "Liveness", "httpGet": {"path": "/", "port": 8501}}]),
                   "WARN  Liveness probe does not use /_stcore/health"),
    "probe port": (_container_set("probes", [{"type": "Readiness", "httpGet": {"path": "/_stcore/health",
                                                                                 "port": 80}}]),
                   "FAIL  Readiness probe checks port 80"),
    "latest tag": (_container_set("image", "example.azurecr.io/msapo-generator:latest"),
                   "WARN  image msapo-generator:latest: tag each build"),
    "untagged": (_container_set("image", "example.azurecr.io/msapo-generator"), "WARN  image msapo-generator:"),
    "unready revision": (_set(["latestReadyRevisionName"], "ca-example--0000000"),
                         "WARN  the latest revision is not the latest ready one"),
    "fixed value differs": (_env_set("PDF_BACKEND", {"value": PLAIN_SECRET}),
                            "FAIL  setting PDF_BACKEND differs from render.yaml (render.yaml: libreoffice)"),
    "fixed value missing": (_env_set("SMARTSHEET_API_MODE", None),
                            "FAIL  setting SMARTSHEET_API_MODE is missing (render.yaml: disabled)"),
    "field map changed": (_env_set("SMARTSHEET_FORM_FIELD_MAP_JSON", {"value": '{"total": "AMOUNT"}'}),
                          "FAIL  setting SMARTSHEET_FORM_FIELD_MAP_JSON differs from render.yaml (see render.yaml)"),
    "fixed value from a secret": (_env_set("PDF_BACKEND", {"secretRef": "anthropic-api-key"}),
                                  "WARN  setting PDF_BACKEND comes from a secret"),
    "plain secret": (_env_set("ANTHROPIC_API_KEY", {"value": PLAIN_SECRET}),
                     "FAIL  secret ANTHROPIC_API_KEY is a plain value"),
    "dangling secret": (_env_set("SMARTSHEET_FORM_URL", {"secretRef": "smartsheet-url"}),
                        "FAIL  secret SMARTSHEET_FORM_URL refers to smartsheet-url, which the app does not define"),
    "secret kept in the app": (_secret_set("expense-account-directors-json", value=PLAIN_SECRET),
                               "WARN  secret EXPENSE_ACCOUNT_DIRECTORS_JSON is stored in the app "
                               "(expense-account-directors-json) rather than in Key Vault"),
    "required secret missing": (_env_set("EXPENSE_ACCOUNT_DIRECTORS_JSON", None),
                                "FAIL  secret EXPENSE_ACCOUNT_DIRECTORS_JSON is missing"),
    "wal forced": (_env_set("EPC_SQLITE_JOURNAL_MODE", {"value": "wal"}),
                   "FAIL  EPC_SQLITE_JOURNAL_MODE must be delete on a network share"),
    "commit as a setting": (_env_set("APP_GIT_COMMIT", {"value": "0" * 40}),
                            "WARN  APP_GIT_COMMIT is an app setting: it goes stale"),
    "journal from a secret": (_env_set("EPC_SQLITE_JOURNAL_MODE", {"secretRef": "anthropic-api-key"}),
                              "WARN  EPC_SQLITE_JOURNAL_MODE comes from a secret, so its value cannot be checked"),
    "journal value ignored": (_env_set("EPC_SQLITE_JOURNAL_MODE", {"value": "truncate"}),
                              "WARN  EPC_SQLITE_JOURNAL_MODE has a value the app ignores (it reads only wal or delete)"),
}


@pytest.mark.parametrize("change, expected", DEFECTS.values(), ids=DEFECTS.keys())
def test_each_defect_is_reported_without_printing_values(tmp_path, capsys, change, expected):
    app = planned_app()
    change(app)
    code, out = check(tmp_path, capsys, app)
    assert expected in out, out
    assert PLAIN_SECRET not in out
    assert code == (1 if "FAIL" in out else 0)


def test_tolerated_differences_pass(tmp_path, capsys):
    app = planned_app()
    field_map = _env(app, "SMARTSHEET_FORM_FIELD_MAP_JSON")
    field_map["value"] = json.dumps(json.loads(field_map["value"]), indent=2)
    _container(app)["resources"] = {"cpu": 0.5, "memory": "512Mi"}
    _container(app)["image"] = "example.azurecr.io/msapo-generator@sha256:" + "0" * 64
    _container(app)["env"] = [item for item in _container(app)["env"]
                              if item["name"] not in ("SMARTSHEET_API_TOKEN", "SMARTSHEET_SHEET_ID")]
    _container(app)["env"] += [{"name": "EPC_SQLITE_JOURNAL_MODE", "value": "delete"},
                               {"name": "EPC_TIMEZONE", "value": PLAIN_SECRET}]
    code, out = check(tmp_path, capsys, app)
    assert code == 0, out
    assert "PASS  setting SMARTSHEET_FORM_FIELD_MAP_JSON matches render.yaml" in out
    assert "PASS  0.5 CPU, 512Mi memory" in out
    assert "PASS  image msapo-generator@sha256:" in out
    assert "INFO  optional secret SMARTSHEET_API_TOKEN is not set" in out
    assert "PASS  EPC_SQLITE_JOURNAL_MODE pins SQLite's rollback journal" in out
    assert "INFO  also set: EPC_TIMEZONE" in out
    assert "INFO  secrets no setting uses: smartsheet-api-token, smartsheet-sheet-id" in out
    assert PLAIN_SECRET not in out


def _entra(issuer=f"https://login.microsoftonline.com/{ZERO_ID}/v2.0", **providers):
    registration = {"clientId": ZERO_ID, **({"openIdIssuer": issuer} if issuer else {})}
    return {"identityProviders": {"azureActiveDirectory": {"enabled": True, "registration": registration},
                                  **providers}}


SIGN_IN = {
    "sign-in off": ({"platform": {"enabled": False}}, "FAIL  built-in sign-in is off"),
    "app paths skip sign-in": ({"globalValidation": {"unauthenticatedClientAction": "RedirectToLoginPage",
                                                     "excludedPaths": ["/", "/_stcore/stream"]}},
                               "FAIL  sign-in is skipped for /, /_stcore/stream"),
    "any organisation": (_entra("https://login.microsoftonline.com/common/v2.0"),
                         "FAIL  Entra accepts accounts from any organisation (/common/)"),
    "issuer unset": (_entra(issuer=None), "WARN  the Entra issuer is not set"),
    "Entra switched off": ({"identityProviders": {"azureActiveDirectory": {
        "enabled": False, "registration": {"clientId": ZERO_ID}}}}, "FAIL  Microsoft Entra ID sign-in is not configured"),
    "another provider": (_entra(gitHub={"registration": {"clientId": "synthetic"}}),
                         "FAIL  other sign-in providers are on (gitHub)"),
    "custom provider": (_entra(customOpenIdConnectProviders={"partner": {"registration": {"clientId": "synthetic"}}}),
                        "FAIL  other sign-in providers are on (customOpenIdConnectProviders.partner)"),
    "anonymous visitors": ({"globalValidation": {"unauthenticatedClientAction": "AllowAnonymous"}},
                           "FAIL  signed-out visitors reach the app (AllowAnonymous)"),
    "action unset": ({"globalValidation": {}}, "WARN  what signed-out visitors get is not set"),
    "no Entra": ({"identityProviders": {}}, "FAIL  Microsoft Entra ID sign-in is not configured"),
    "http sign-in": ({"httpSettings": {"requireHttps": False}}, "WARN  sign-in allows plain http"),
}


@pytest.mark.parametrize("override, expected", SIGN_IN.values(), ids=SIGN_IN.keys())
def test_sign_in_gaps_are_reported(tmp_path, capsys, override, expected):
    auth = copy.deepcopy(PLANNED_AUTH)
    auth["properties"].update(override)
    code, out = check(tmp_path, capsys, planned_app(), auth)
    assert expected in out
    assert ZERO_ID not in out
    assert code == (1 if expected.startswith("FAIL") else 0)


def test_safe_sign_in_shapes_pass(tmp_path, capsys):
    auth = copy.deepcopy(PLANNED_AUTH)
    auth["properties"]["globalValidation"]["excludedPaths"] = ["/_stcore/health"]
    auth["properties"].update(_entra(issuer=f"https://sts.windows.net/{ZERO_ID}/",
                                     gitHub=None, google={"enabled": None, "registration": None},
                                     customOpenIdConnectProviders={}))
    code, out = check(tmp_path, capsys, planned_app(), auth)
    assert code == 0, out
    assert "skipped" not in out and "other sign-in providers" not in out
    assert "PASS  Entra accepts only the accounts of one tenant" in out
    assert ZERO_ID not in out


def test_journal_modes_are_the_ones_the_app_reads():
    from app.sqlite_storage import _MODES
    assert set(azure_config_check.JOURNAL_MODES) == set(_MODES)


def test_sign_in_never_configured_fails(tmp_path, capsys):
    code, out = check(tmp_path, capsys, planned_app(), {})
    assert code == 1
    assert "FAIL  built-in sign-in is off" in out


def test_without_auth_the_sign_in_is_named_as_unchecked(tmp_path, capsys):
    code, out = check(tmp_path, capsys, planned_app(), auth=None)
    assert code == 0
    assert "INFO  sign-in not checked: pass --auth" in out


def test_reads_standard_input_and_unwrapped_properties(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(planned_app()["properties"])))
    assert azure_config_check.main(["-"]) == 0
    assert "PASS  revisions mode Single" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["not json", "[]", json.dumps(PLANNED_AUTH)])
def test_unusable_input_exits_2(tmp_path, capsys, content):
    (tmp_path / "app.json").write_text(content)
    assert azure_config_check.main([str(tmp_path / "app.json")]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_render_env_reads_render_yaml_like_a_yaml_parser():
    yaml = pytest.importorskip("yaml")
    service = yaml.safe_load((ROOT / "render.yaml").read_text())["services"][0]
    assert render_env() == [(entry["key"], entry.get("value")) for entry in service["envVars"]]


def test_render_env_rejects_an_entry_without_value_or_sync(tmp_path):
    (tmp_path / "render.yaml").write_text("services:\n  - envVars:\n      - key: ORPHAN\n")
    with pytest.raises(ValueError, match="ORPHAN"):
        render_env(tmp_path / "render.yaml")


def test_expected_port_and_health_path_are_the_images():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f"EXPOSE {azure_config_check.PORT}" in dockerfile
    assert f"--server.port={azure_config_check.PORT}" in dockerfile
    # The image healthcheck is the portability readiness probe, which itself
# hits the Streamlit health endpoint (see container_portability.ready).
assert "scripts/container_portability.py ready" in dockerfile
probe = (ROOT / "scripts/container_portability.py").read_text()
assert azure_config_check.HEALTH_PATH in probe


@pytest.mark.parametrize("relative", ["scripts/azure_config_check.py", "scripts/host_check.py",
                                      "app/sqlite_storage.py", "app/__init__.py"])
def test_the_check_runs_on_a_plain_cloud_shell_python(relative):
    """Cloud Shell has python3 but none of the app's packages, and may be older."""
    tree = ast.parse((ROOT / relative).read_text(), feature_version=(3, 9))
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names or top in ("__future__", "app", "scripts"), (relative, name)
            if top == "app":
                assert name in ("app.sqlite_storage",), (relative, name)
            if top == "scripts":
                assert name in ("scripts.host_check",), (relative, name)
