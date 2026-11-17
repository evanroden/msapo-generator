"""The Claude client comes from the Claude API or, when configured, Microsoft Foundry."""

from __future__ import annotations

import anthropic
import httpx
import pytest

from app import ai_client

FOUNDRY_VARS = ("ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL",
                "ANTHROPIC_FOUNDRY_API_KEY", "AZURE_CLIENT_ID", "IDENTITY_ENDPOINT", "IDENTITY_HEADER")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in FOUNDRY_VARS:
        monkeypatch.delenv(name, raising=False)
    ai_client._PROVIDERS.clear()
    yield
    ai_client._PROVIDERS.clear()


def test_without_foundry_settings_the_claude_api_key_is_used():
    assert ai_client.foundry_settings() is None
    assert ai_client.ai_available("sk-test") is True
    assert ai_client.ai_available("") is False
    assert ai_client.ai_available(None) is False
    client = ai_client.make_client("sk-test", max_retries=0, timeout=12)
    assert type(client) is anthropic.Anthropic
    assert client.api_key == "sk-test"
    assert client.max_retries == 0
    assert str(client.base_url).startswith("https://api.anthropic.com")


def test_foundry_resource_with_a_key_uses_the_foundry_endpoint_and_never_the_claude_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "example-resource")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "foundry-test-key")
    assert ai_client.ai_available("") is True
    settings = ai_client.foundry_settings()
    assert settings.sign_in == "a Foundry key"
    assert settings.address == "https://example-resource.services.ai.azure.com/anthropic/"
    client = ai_client.make_client("sk-personal", max_retries=0)
    assert isinstance(client, anthropic.AnthropicFoundry)
    assert str(client.base_url) == "https://example-resource.services.ai.azure.com/anthropic/"
    assert client.api_key == "foundry-test-key"


def test_foundry_base_url_wins_over_the_resource_name(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_BASE_URL", "https://other.services.ai.azure.com/anthropic/")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "foundry-test-key")
    settings = ai_client.foundry_settings()
    assert settings.target == {"base_url": "https://other.services.ai.azure.com/anthropic/"}
    client = ai_client.make_client("", max_retries=0)
    assert str(client.base_url) == "https://other.services.ai.azure.com/anthropic/"


def _identity_transport(calls, *, status=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = body if body is not None else {"access_token": f"token-{len(calls)}", "expires_on": "4102444800"}
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def test_identity_token_request_names_the_foundry_audience_and_the_identity(monkeypatch):
    calls = []
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "header-value")
    with httpx.Client(transport=_identity_transport(calls)) as http:
        token, expires_on = ai_client.fetch_identity_token("client-guid", http_client=http)
    assert (token, expires_on) == ("token-1", 4102444800.0)
    request = calls[0]
    assert request.headers["X-IDENTITY-HEADER"] == "header-value"
    assert request.url.params["resource"] == "https://ai.azure.com"
    assert request.url.params["api-version"] == "2019-08-01"
    assert request.url.params["client_id"] == "client-guid"


def test_token_is_cached_and_shared_per_identity(monkeypatch):
    fetched = []
    monkeypatch.setattr(ai_client, "fetch_identity_token",
                        lambda client_id="": fetched.append(client_id) or (f"tok-{len(fetched)}", 4102444800.0))
    provider = ai_client.managed_identity_token("client-guid")
    assert provider() == "tok-1"
    assert provider() == "tok-1"
    assert fetched == ["client-guid"]
    assert ai_client.managed_identity_token("client-guid") is provider
    assert ai_client.managed_identity_token("other") is not provider


def test_expiring_token_is_fetched_again(monkeypatch):
    tokens = iter([("first", 1000.0), ("second", 4102444800.0)])
    monkeypatch.setattr(ai_client, "fetch_identity_token", lambda client_id="": next(tokens))
    monkeypatch.setattr(ai_client.time, "time", lambda: 900.0)  # inside the 300 s refresh margin
    provider = ai_client.ManagedIdentityToken("")
    assert provider() == "first"
    assert provider() == "second"


def test_missing_identity_is_a_connection_error_the_app_already_handles():
    with pytest.raises(anthropic.APIConnectionError) as raised:
        ai_client.fetch_identity_token("")
    assert "ANTHROPIC_FOUNDRY_API_KEY" in str(raised.value)


@pytest.mark.parametrize("status, body", [(400, {"error": "no identity"}), (200, {"expires_on": "1"}),
                                          (200, {"access_token": "", "expires_on": "4102444800"})])
def test_identity_endpoint_failures_never_echo_the_response(monkeypatch, status, body):
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "header-value")
    with httpx.Client(transport=_identity_transport([], status=status, body=body)) as http:
        with pytest.raises(anthropic.APIConnectionError) as raised:
            ai_client.fetch_identity_token("client-guid", http_client=http)
    assert "no identity" not in str(raised.value)
    assert "header-value" not in str(raised.value)


def test_foundry_with_managed_identity_sends_a_bearer_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "example-resource")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setattr(ai_client, "fetch_identity_token", lambda client_id="": (f"tok-for-{client_id}", 4102444800.0))
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with ai_client.make_client("sk-personal", max_retries=0, http_client=http) as client:
            message = client.messages.create(model="claude-opus-5-5", max_tokens=1,
                                             messages=[{"role": "user", "content": "ping"}])
    assert message.content[0].text == "ok"
    request = seen[0]
    assert str(request.url) == "https://example-resource.services.ai.azure.com/anthropic/v1/messages"
    assert request.headers["Authorization"] == "Bearer tok-for-client-guid"
    assert "x-api-key" not in request.headers  # the personal key is never sent to Foundry
