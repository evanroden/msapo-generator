"""Build the Claude client for the service this deployment uses.

Render calls the Claude API directly with ``ANTHROPIC_API_KEY``. The Azure copy
calls Claude in Microsoft Foundry on the company's own Azure subscription, so no
personal key is involved. To use Foundry, set:

* ``ANTHROPIC_FOUNDRY_RESOURCE`` (the Foundry resource name) or
  ``ANTHROPIC_FOUNDRY_BASE_URL`` (its full ``.../anthropic/`` address);
* ``ANTHROPIC_MODEL`` to the Foundry deployment name;
* ``AZURE_CLIENT_ID`` to the client ID of the app's user-assigned managed
  identity, which needs the Cognitive Services User role on the resource.
  ``ANTHROPIC_FOUNDRY_API_KEY`` signs in with a Foundry key instead.

Callers pass their own ``ANTHROPIC_API_KEY`` value, so a test that patches one
module's key still controls that module. Foundry settings, when present, win.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import anthropic
import httpx

# Microsoft Entra audience for Foundry inference (scope https://ai.azure.com/.default).
FOUNDRY_AUDIENCE = "https://ai.azure.com"
# Container Apps and App Service managed identity protocol version.
IDENTITY_API_VERSION = "2019-08-01"
# Fetch a new token this long before Azure says the current one expires.
TOKEN_REFRESH_MARGIN_SECONDS = 300.0
IDENTITY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class FoundrySettings:
    resource: str
    base_url: str
    api_key: str
    client_id: str

    @property
    def target(self) -> dict[str, str]:
        # The SDK treats resource and base_url as mutually exclusive.
        return {"base_url": self.base_url} if self.base_url else {"resource": self.resource}

    @property
    def address(self) -> str:
        return self.base_url or f"https://{self.resource}.services.ai.azure.com/anthropic/"

    @property
    def sign_in(self) -> str:
        return "a Foundry key" if self.api_key else "the app's managed identity"


def foundry_settings() -> FoundrySettings | None:
    """The Foundry settings from the environment, or None when Foundry is not used."""
    resource = os.getenv("ANTHROPIC_FOUNDRY_RESOURCE", "").strip()
    base_url = os.getenv("ANTHROPIC_FOUNDRY_BASE_URL", "").strip()
    if not (resource or base_url):
        return None
    return FoundrySettings(
        resource=resource,
        base_url=base_url,
        api_key=os.getenv("ANTHROPIC_FOUNDRY_API_KEY", "").strip(),
        client_id=os.getenv("AZURE_CLIENT_ID", "").strip(),
    )


def ai_available(api_key: str | None) -> bool:
    """Whether AI reading is configured: a Claude API key or Foundry settings."""
    return bool(str(api_key or "").strip()) or foundry_settings() is not None


def make_client(api_key: str | None, **options) -> anthropic.Anthropic:
    """A Claude client: Foundry when configured, otherwise the Claude API with ``api_key``.

    ``options`` go to the SDK unchanged (``max_retries``, ``timeout``, ``http_client``).
    """
    settings = foundry_settings()
    if settings is None:
        return anthropic.Anthropic(api_key=api_key, **options)
    if settings.api_key:
        return anthropic.AnthropicFoundry(api_key=settings.api_key, **settings.target, **options)
    return anthropic.AnthropicFoundry(
        azure_ad_token_provider=managed_identity_token(settings.client_id),
        **settings.target,
        **options,
    )


class ManagedIdentityToken:
    """Token provider for AnthropicFoundry: a cached Entra token from the host's managed identity.

    The SDK calls the provider before every request, so the token is kept until
    shortly before it expires. Failures are raised as ``anthropic.APIConnectionError``
    so the app's retry and error handling treats them like any network failure.
    The token is never logged.
    """

    def __init__(self, client_id: str = "") -> None:
        self.client_id = client_id
        self._lock = threading.Lock()
        self._token = ""
        self._refresh_at = 0.0

    def __call__(self) -> str:
        with self._lock:
            if self._token and time.time() < self._refresh_at:
                return self._token
            token, expires_on = fetch_identity_token(self.client_id)
            self._token = token
            self._refresh_at = expires_on - TOKEN_REFRESH_MARGIN_SECONDS
            return token


_PROVIDERS: dict[str, ManagedIdentityToken] = {}
_PROVIDERS_LOCK = threading.Lock()


def managed_identity_token(client_id: str = "") -> ManagedIdentityToken:
    """One shared provider per identity, so every client reuses the cached token."""
    with _PROVIDERS_LOCK:
        return _PROVIDERS.setdefault(client_id, ManagedIdentityToken(client_id))


def fetch_identity_token(client_id: str = "", *, http_client: httpx.Client | None = None) -> tuple[str, float]:
    """(token, expiry as Unix time) from the Azure host's managed identity endpoint."""
    endpoint = os.getenv("IDENTITY_ENDPOINT", "").strip()
    secret_header = os.getenv("IDENTITY_HEADER", "").strip()
    request = httpx.Request("GET", endpoint or "http://localhost/managed-identity")
    if not endpoint or not secret_header:
        raise anthropic.APIConnectionError(
            message=(
                "This host has no managed identity, so Microsoft Foundry cannot be reached: "
                "run on Azure with an identity attached, or set ANTHROPIC_FOUNDRY_API_KEY."
            ),
            request=request,
        )
    params = {"resource": FOUNDRY_AUDIENCE, "api-version": IDENTITY_API_VERSION}
    if client_id:
        params["client_id"] = client_id
    try:
        if http_client is None:
            response = httpx.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": secret_header},
                                 timeout=IDENTITY_TIMEOUT_SECONDS)
        else:
            response = http_client.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": secret_header},
                                       timeout=IDENTITY_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        token = str(data["access_token"]).strip()
        expires_on = float(data["expires_on"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        raise anthropic.APIConnectionError(
            message=(
                "Could not get a sign-in token from Azure's managed identity"
                + (f" (HTTP {status})" if status else "")
                + ": check that the identity is attached to the app and AZURE_CLIENT_ID is its client ID."
            ),
            request=request,
        ) from error
    if not token:
        raise anthropic.APIConnectionError(
            message="Azure's managed identity returned an empty sign-in token.", request=request,
        )
    return token, expires_on
