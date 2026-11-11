"""Static regression guards for bypass routes; Azure ingress still needs browser QA."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_requires_identity_before_workflow_import_and_render():
    code = (ROOT / "run_web.py").read_text(encoding="utf-8")
    assert code.index("require_streamlit_entry()") < code.index("from app.web_ui import main")
    assert code.index("from app.web_ui import main") < code.index("main()", code.index("from app.web_ui import main"))


def test_legacy_bookmark_requires_identity_before_any_page_data():
    code = (ROOT / "pages/2_Smartsheet_PO.py").read_text(encoding="utf-8")
    assert code.index("require_streamlit_entry()") < code.index('st.title("Smartsheet PO handoff")')
    assert "submit_po" not in code


def test_auth_configuration_requires_auth_and_does_not_exclude_health_or_ws():
    code = (ROOT / "docs/azure/app_service_auth.bicep").read_text(encoding="utf-8")
    assert "'authsettingsV2'" in code
    assert "requireAuthentication: true" in code
    assert "unauthenticatedClientAction: 'RedirectToLoginPage'" in code
    assert "excludedPaths: []" in code
    assert "requireHttps: true" in code
    assert "azureActiveDirectory:" in code
    assert "openIdIssuer: 'https://login.microsoftonline.com/${tenantId}/v2.0'" in code
    assert "google:" not in code and "facebook:" not in code
    assert "AllowAnonymous" not in code


def test_no_runtime_config_only_bypass_of_shared_storage():
    code = (ROOT / "app/azure_identity.py").read_text(encoding="utf-8")
    assert "RESOURCE_BOUNDARIES_INTEGRATED = False" in code
    assert 'environment.get("MSAPO_AUTHZ_DATA_BOUNDARY_READY") != "verified"' in code
