"""Synthetic claims only. No live tenant, application, or report data required."""
import base64
import json
import pytest

from app.azure_identity import (
    AccessDenied, Principal, ScopeGrant, authorize, decode_easy_auth,
    entry_principal, azure_enforced, ACTION_ROLES,
)

TID = "11111111-1111-4111-8111-111111111111"
OID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
AZURE = {"WEBSITE_SITE_NAME": "synthetic-app", "MSAPO_AUTH_MODE": "app_service",
         "ENFRA_ENTRA_CLIENT_ID": OTHER, "ENFRA_ENTRA_TENANT_ID": TID}


def headers(*, tenant=TID, oid=OID, roles=("MSAPO.AppAccess",), idp="aad", extra=()):
    claims = [
        {"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": tenant},
        {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": oid},
        *[{"typ": "roles", "val": r} for r in roles],
        *extra,
    ]
    payload = {"auth_typ": "aad", "claims": claims}
    return {"X-MS-CLIENT-PRINCIPAL-IDP": idp, "X-MS-CLIENT-PRINCIPAL":
            base64.b64encode(json.dumps(payload).encode()).decode()}


def test_render_local_unaffected_but_azure_fails_closed_on_missing_or_disabled_configuration():
    assert not azure_enforced({})
    assert entry_principal({}, {}) is None
    assert azure_enforced({"WEBSITE_SITE_NAME": "test"})
    for conf in ({"WEBSITE_SITE_NAME": "test"},
                 {**AZURE, "MSAPO_AUTH_MODE": "disabled"},
                 {k: v for k, v in AZURE.items() if k != "ENFRA_ENTRA_CLIENT_ID"},
                 {k: v for k, v in AZURE.items() if k != "WEBSITE_SITE_NAME"}):
        with pytest.raises(AccessDenied):
            entry_principal(headers(), conf)


def test_identity_is_stable_tenant_object_not_email_or_cookie():
    a = entry_principal(headers(extra=({"typ": "email", "val": "a@invalid.test"},)), AZURE)
    b = entry_principal(headers(extra=({"typ": "email", "val": "b@invalid.test"},)), AZURE)
    assert a == b == Principal(TID, OID, frozenset({"MSAPO.AppAccess"}))
    assert a.key == f"{TID}:{OID}"


@pytest.mark.parametrize("input_headers", [
    {}, {"x-ms-client-principal-idp": "aad", "x-ms-client-principal": "not base64"},
    headers(idp="google"), headers(tenant=OTHER), headers(oid="not-a-guid"),
    headers(roles=()), headers(roles=("MSAPO.ReportEditor",)),
    headers(extra=({"typ": "oid", "val": OTHER},)),
    headers(extra=({"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": OTHER},)),
])
def test_missing_wrong_tenant_unassigned_malformed_or_ambiguous_identity_denied(input_headers):
    with pytest.raises(AccessDenied):
        entry_principal(input_headers, AZURE)


def test_app_entry_does_not_elevate_to_report_read():
    principal = entry_principal(headers(), AZURE)
    with pytest.raises(AccessDenied):
        authorize(principal, "report.open", "contract-a", "site-1", [
            ScopeGrant(TID, OID, "report.open", "contract-a", "site-1")])


def test_app_role_and_explicit_server_grant_both_needed_for_resource():
    p = entry_principal(headers(roles=("MSAPO.AppAccess", "MSAPO.ReportEditor")), AZURE)
    grant = ScopeGrant(TID, OID, "report.edit", "contract-a", "site-1")
    authorize(p, "report.edit", "contract-a", "site-1", [grant])
    for action, contract, site, g in [
        ("report.edit", "contract-b", "site-1", [grant]),
        ("report.edit", "contract-a", "site-2", [grant]),
        ("report.edit", "contract-a", "site-1", [ScopeGrant(TID, OTHER, "report.edit", "contract-a", "site-1")]),
        ("report.edit", "contract-a", "site-1", [ScopeGrant(TID, OID, "report.edit", "contract-a", "site-1", False)]),
        ("report.edit", "contract-a", "site-1", []),
        ("report.download", "contract-a", "site-1", [grant]),
        ("report.preview", "contract-a", "site-1", [grant]),
        ("report.original", "contract-a", "site-1", [grant]),
        ("report.edit", "", "site-1", [grant]),
        ("report.edit", "contract-a", None, [grant]),
        ("unknown", "contract-a", "site-1", [grant]),
    ]:
        with pytest.raises(AccessDenied):
            authorize(p, action, contract, site, g)


def test_privileged_actions_never_inherit_reader_editor_or_tenant_admin():
    p = entry_principal(headers(roles=("MSAPO.AppAccess", "MSAPO.ReportEditor", "MSAPO.AppAdmin")), AZURE)
    for action in ("defaults.publish", "learned.admin", "external.submit"):
        with pytest.raises(AccessDenied):
            authorize(p, action, "contract-a", None, [ScopeGrant(TID, OID, action, "contract-a", None)])
    assert {"report.original", "report.preview", "report.download"}.issubset(ACTION_ROLES)


def test_read_and_download_permanent_scope_not_transferable_to_other_user():
    p = entry_principal(headers(roles=("MSAPO.AppAccess", "MSAPO.ReportReader")), AZURE)
    q = entry_principal(headers(oid=OTHER, roles=("MSAPO.AppAccess", "MSAPO.ReportReader")), AZURE)
    for action in ("report.open", "report.preview", "report.original", "report.download"):
        g = ScopeGrant(TID, OID, action, "contract-a", "site-1")
        authorize(p, action, "contract-a", "site-1", [g])
        with pytest.raises(AccessDenied):
            authorize(q, action, "contract-a", "site-1", [g])


def test_all_actions_need_explicit_exact_scope_even_for_administrator():
    p = entry_principal(headers(roles=("MSAPO.AppAccess", *tuple(set().union(*ACTION_ROLES.values())))), AZURE)
    for action in ACTION_ROLES:
        with pytest.raises(AccessDenied):
            authorize(p, action, "contract-a", "site-1", [])


def test_azure_browser_gate_disabled_until_data_scope_boundary_verified(monkeypatch):
    import sys
    from types import SimpleNamespace
    import app.azure_identity as identity

    class Halt(Exception):
        pass

    state = {"report_draft": "sensitive"}
    errors = []
    fake_st = SimpleNamespace(
        context=SimpleNamespace(headers=headers()), session_state=state,
        error=lambda message: errors.append(message),
        stop=lambda: (_ for _ in ()).throw(Halt()),
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    for key, value in AZURE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MSAPO_AUTHZ_DATA_BOUNDARY_READY", raising=False)
    with pytest.raises(Halt):
        identity.require_streamlit_entry()
    assert errors and "Access denied" in errors[-1]
    assert "_msapo_azure_identity_key" not in state


def test_two_users_clear_session_without_inheriting_draft_and_ws_age_caps(monkeypatch):
    import sys
    from types import SimpleNamespace
    import app.azure_identity as identity

    class Halt(Exception):
        pass

    state = {}
    fake_st = SimpleNamespace(
        context=SimpleNamespace(headers=headers()), session_state=state,
        error=lambda *_: None,
        stop=lambda: (_ for _ in ()).throw(Halt()),
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    for key, value in {**AZURE, "MSAPO_AUTHZ_DATA_BOUNDARY_READY": "verified"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(identity.time, "monotonic", lambda: 100.)
    a = identity.require_streamlit_entry()
    state["report_draft"] = "one-user-only"
    assert identity.require_streamlit_entry() == a
    fake_st.context.headers = headers(oid=OTHER)
    b = identity.require_streamlit_entry()
    assert b != a and "report_draft" not in state
    state["report_draft"] = "two-user-only"
    monkeypatch.setattr(identity.time, "monotonic", lambda: 701.)
    with pytest.raises(Halt):
        identity.require_streamlit_entry()
