"""App Service Entra claim boundary and *scoped* authorization primitives.

Only trust X-MS-CLIENT-PRINCIPAL behind Azure's enabled Easy Auth proxy.
The helper is deliberately not a substitute for checking individual storage/
submission operations: A05 must call authorize() at every resource boundary.
Anonymous device cookies and requester names have no security significance.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
import re
import time
from collections.abc import Mapping, Iterable

_GUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
_OID = ("oid", "http://schemas.microsoft.com/identity/claims/objectidentifier")
_TID = ("tid", "http://schemas.microsoft.com/identity/claims/tenantid")
_ROLE = ("roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
# Set True only in the reviewed A05 data-layer authorization integration.
# An environment setting alone must never activate legacy shared data paths.
RESOURCE_BOUNDARIES_INTEGRATED = False

# Values are proposed, not yet ENFRA-approved Entra app-role IDs.
# This cannot be enabled by configuration alone. A05 must make a reviewed
# code change once every persisted data path authorizes per resource.
RESOURCE_BOUNDARIES_INTEGRATED = False

ACTION_ROLES = {
    "report.open": frozenset({"MSAPO.ReportReader", "MSAPO.ReportEditor"}),
    "report.edit": frozenset({"MSAPO.ReportEditor"}),
    "report.original": frozenset({"MSAPO.ReportReader", "MSAPO.ReportEditor"}),
    "report.preview": frozenset({"MSAPO.ReportReader", "MSAPO.ReportEditor"}),
    "report.download": frozenset({"MSAPO.ReportReader", "MSAPO.ReportEditor"}),
    "defaults.publish": frozenset({"MSAPO.DefaultsPublisher"}),
    "learned.admin": frozenset({"MSAPO.LearnedDataAdmin"}),
    "external.submit": frozenset({"MSAPO.ExternalSubmitter"}),
    "po.use": frozenset({"MSAPO.POOperator"}),
    "expense.use": frozenset({"MSAPO.ExpenseOperator"}),
}


class AccessDenied(PermissionError):
    """Failure is generic: do not leak whether a report or grant exists."""


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    object_id: str
    roles: frozenset[str]

    @property
    def key(self) -> str:
        return f"{self.tenant_id}:{self.object_id}"


@dataclass(frozen=True)
class ScopeGrant:
    """A05-owned, server-resolved record; never accept a browser grant list."""
    tenant_id: str
    object_id: str
    action: str
    contract_id: str
    site_id: str | None
    active: bool = True


def _guid(value: object) -> str:
    value = str(value or "").lower()
    if not _GUID.fullmatch(value):
        raise AccessDenied("Access denied")
    return value


def _unique(claims: list[dict], names: tuple[str, ...]) -> str:
    values = [c.get("val") for c in claims if c.get("typ") in names]
    if len(values) != 1 or not isinstance(values[0], str):
        raise AccessDenied("Access denied")
    return values[0]


def decode_easy_auth(headers: Mapping[str, str], tenant_id: str) -> Principal:
    """Parse already-validated Easy Auth claims (NOT a JWT verifier).

    Only call with headers injected by the App Service proxy, never for direct
    internet requests, custom reverse proxies, or local production fallbacks.
    """
    normalized = {}
    for k, value in headers.items():
        name = str(k).lower()
        if name in normalized:
            raise AccessDenied("Access denied")
        normalized[name] = value
    if normalized.get("x-ms-client-principal-idp", "").lower() != "aad":
        raise AccessDenied("Access denied")
    encoded = normalized.get("x-ms-client-principal", "")
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 16384:
        raise AccessDenied("Access denied")
    try:
        raw = base64.b64decode(encoded, validate=True)
        data = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccessDenied("Access denied") from exc
    if not isinstance(data, dict) or data.get("auth_typ") != "aad":
        raise AccessDenied("Access denied")
    claims = data.get("claims")
    if not isinstance(claims, list) or len(claims) > 256 or any(
        not isinstance(c, dict) or not isinstance(c.get("typ"), str)
        or not isinstance(c.get("val"), str) for c in claims
    ):
        raise AccessDenied("Access denied")
    tid = _guid(_unique(claims, _TID))
    oid = _guid(_unique(claims, _OID))
    if tid != _guid(tenant_id):
        raise AccessDenied("Access denied")
    roles = frozenset(c["val"] for c in claims if c["typ"] in _ROLE)
    # An assigned app user can still have no app role: that is not authorization.
    if "MSAPO.AppAccess" not in roles:
        raise AccessDenied("Access denied")
    return Principal(tid, oid, roles)


def azure_enforced(environment: Mapping[str, str]) -> bool:
    """Azure always fails closed, including when the feature flag is omitted."""
    return bool(environment.get("WEBSITE_SITE_NAME") or environment.get("WEBSITE_INSTANCE_ID")
                or environment.get("MSAPO_AUTH_MODE") == "app_service")


def entry_principal(headers: Mapping[str, str], environment: Mapping[str, str]) -> Principal | None:
    """Return None for existing Render/local behavior, never for Azure."""
    if not azure_enforced(environment):
        return None
    if (environment.get("MSAPO_AUTH_MODE") != "app_service"
            or not (environment.get("WEBSITE_SITE_NAME") or environment.get("WEBSITE_INSTANCE_ID"))
            or not environment.get("ENFRA_ENTRA_CLIENT_ID")):
        raise AccessDenied("Access denied")
    _guid(environment.get("ENFRA_ENTRA_CLIENT_ID"))
    return decode_easy_auth(headers, environment.get("ENFRA_ENTRA_TENANT_ID", ""))


def authorize(principal: Principal | None, action: str, contract_id: str,
              site_id: str | None, grants: Iterable[ScopeGrant]) -> None:
    """Fail closed on both app role and exact server-side resource entitlement.

    Report content, previews, originals and downloads must inherit the report's
    authoritative contract/site, not a site or owner supplied in the URL.
    Contract-wide actions use site_id=None and an explicit matching grant.
    """
    if (principal is None or action not in ACTION_ROLES
            or not principal.roles.intersection(ACTION_ROLES[action])
            or not isinstance(contract_id, str) or not contract_id.strip()
            or site_id == "" or (action.startswith("report.") and not site_id)):
        raise AccessDenied("Access denied")
    if not any(
        isinstance(grant, ScopeGrant) and grant.active
        and grant.tenant_id == principal.tenant_id and grant.object_id == principal.object_id
        and grant.action == action and grant.contract_id == contract_id
        and grant.site_id == site_id for grant in grants
    ):
        raise AccessDenied("Access denied")


def _resource_boundaries_implemented() -> bool:
    """A05 integration must replace this hard lock in a reviewed code change."""
    return False


def require_streamlit_entry() -> Principal | None:
    """Entry guard, before any user data/Streamlit UI initialization.

    Under Azure, no claim is trusted from the browser unless Easy Auth is the
    only ingress. Expired WS sessions stop on the next rerun. Separate resource
    guards and an authenticated browser logout/reconnect QA gate remain required.
    """
    environment = os.environ
    if not azure_enforced(environment):
        return None
    import streamlit as st
    try:
        principal = entry_principal(st.context.headers, environment)
        if (principal is None or not RESOURCE_BOUNDARIES_INTEGRATED
                or not _resource_boundaries_implemented()
                or environment.get("MSAPO_AUTHZ_DATA_BOUNDARY_READY") != "verified"):
            # Both code-validated A05 storage guards and an intentional
            # deployment readiness value are required. Neither suffices alone.
            raise AccessDenied("Access denied")
        key = "_msapo_azure_identity_key"
        if st.session_state.get(key) not in (None, principal.key):
            st.session_state.clear()  # never carry a prior user's report across login
        st.session_state[key] = principal.key
        began = st.session_state.setdefault("_msapo_azure_ws_started", time.monotonic())
        if time.monotonic() - began > 600:
            raise AccessDenied("Access denied")
        return principal
    except (AccessDenied, AttributeError, RuntimeError):
        st.error("Access denied. Sign in again to begin a new session.")
        st.stop()
        raise AccessDenied("Access denied")  # defensive if Streamlit is stubbed
