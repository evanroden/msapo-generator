"""Provider-neutral AI requests and built-in provider adapters."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Callable, FrozenSet, Mapping, Protocol
from urllib.parse import urlsplit

import requests

from app.adapter_loader import AdapterConfigurationError, load_adapter


CAP_TEXT = "text"
CAP_IMAGE = "image"
CAP_DOCUMENT = "document"
_VALID_CAPABILITIES = frozenset({CAP_TEXT, CAP_IMAGE, CAP_DOCUMENT})


class AIProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class UnsupportedCapabilityError(AIProviderError):
    def __init__(self, capability: str, message: str | None = None) -> None:
        super().__init__(
            message or f"The configured AI provider does not support {capability} input.",
            code="unsupported_capability",
            retryable=False,
        )
        self.capability = capability


@dataclass(frozen=True)
class BinaryPart:
    kind: str
    data: bytes
    media_type: str
    filename: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {CAP_IMAGE, CAP_DOCUMENT}:
            raise ValueError(f"Unsupported binary part kind: {self.kind}")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("Binary AI parts must contain non-empty bytes.")
        if not self.media_type:
            raise ValueError("Binary AI parts require a media type.")


@dataclass(frozen=True)
class AIRequest:
    operation: str
    prompt: str
    system: str | None = None
    parts: tuple[BinaryPart, ...] = ()
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("AI requests require an operation name.")
        if not self.prompt.strip():
            raise ValueError("AI requests require a prompt.")
        if not 1 <= self.max_tokens <= 65536:
            raise ValueError("AI max_tokens must be between 1 and 65,536.")


class AIProvider(Protocol):
    name: str
    capabilities: FrozenSet[str]

    def complete(self, request: AIRequest) -> str: ...

    def diagnostic(self) -> Mapping[str, object]: ...


def _validate_provider(provider: object, *, kind: str = "AI") -> AIProvider:
    if not callable(getattr(provider, "complete", None)):
        raise AdapterConfigurationError(f"{kind} provider must implement complete(request).")
    capabilities = frozenset(getattr(provider, "capabilities", ()))
    if not capabilities or not capabilities.issubset(_VALID_CAPABILITIES):
        raise AdapterConfigurationError(
            f"{kind} provider capabilities must be a non-empty subset of "
            f"{sorted(_VALID_CAPABILITIES)}."
        )
    if not getattr(provider, "name", None):
        raise AdapterConfigurationError(f"{kind} provider must expose a name.")
    if not callable(getattr(provider, "diagnostic", None)):
        raise AdapterConfigurationError(f"{kind} provider must implement diagnostic().")
    return provider  # type: ignore[return-value]


def require_capability(provider: AIProvider, capability: str) -> None:
    if capability not in provider.capabilities:
        raise UnsupportedCapabilityError(capability)


class AnthropicAIProvider:
    name = "anthropic"
    capabilities = frozenset({CAP_TEXT, CAP_IMAGE, CAP_DOCUMENT})

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_retries: int = 3,
        retry_base_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_retries = max(1, int(max_retries))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._sleep = sleep

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None
    ) -> "AnthropicAIProvider":
        source = os.environ if env is None else env
        api_key = (
            source.get("EPC_AI_API_KEY") or source.get("ANTHROPIC_API_KEY") or ""
        ).strip()
        model = (
            source.get("EPC_AI_MODEL")
            or source.get("ANTHROPIC_MODEL")
            or "claude-sonnet-4-6"
        ).strip()
        return cls(
            api_key=api_key,
            model=model,
            max_retries=int(source.get("EPC_AI_MAX_RETRIES", "3")),
            retry_base_seconds=float(source.get("EPC_AI_RETRY_BASE_SECONDS", "5")),
        )

    def diagnostic(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "model": self.model,
            "configured": bool(self.api_key and self.model),
            "capabilities": sorted(self.capabilities),
        }

    @staticmethod
    def _content(request: AIRequest) -> list[dict]:
        content: list[dict] = []
        for part in request.parts:
            if part.kind == CAP_IMAGE:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part.media_type,
                            "data": base64.standard_b64encode(part.data).decode("ascii"),
                        },
                    }
                )
            elif part.kind == CAP_DOCUMENT:
                content.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": part.media_type,
                            "data": base64.standard_b64encode(part.data).decode("ascii"),
                        },
                    }
                )
        content.append({"type": "text", "text": request.prompt})
        return content

    @staticmethod
    def _response_text(message: object) -> str:
        blocks = getattr(message, "content", None) or []
        texts = [
            str(getattr(block, "text", ""))
            for block in blocks
            if getattr(block, "type", "text") == "text" and getattr(block, "text", None)
        ]
        result = "\n".join(texts).strip()
        if not result:
            raise AIProviderError("The AI provider returned no text.", code="empty_response")
        return result

    def complete(self, request: AIRequest) -> str:
        if not self.api_key:
            raise AIProviderError(
                "The Anthropic API key is not configured.", code="authentication"
            )
        for part in request.parts:
            require_capability(self, part.kind)
        try:
            import anthropic
        except ImportError as exc:
            raise AIProviderError(
                "The Anthropic adapter is selected but the anthropic package is not installed.",
                code="missing_dependency",
            ) from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "max_tokens": request.max_tokens,
                    "messages": [{"role": "user", "content": self._content(request)}],
                }
                if request.system:
                    kwargs["system"] = request.system
                message = client.messages.create(**kwargs)
                return self._response_text(message)
            except anthropic.APIStatusError as exc:
                last_error = exc
                status = int(getattr(exc, "status_code", 0) or 0)
                text = str(exc)
                if status in {401, 403}:
                    raise AIProviderError(text, code="authentication") from exc
                if request.parts and any(part.kind == CAP_DOCUMENT for part in request.parts):
                    if status in {413, 415, 422} or (
                        status == 400
                        and any(
                            word in text.lower()
                            for word in ("document", "pdf", "unsupported")
                        )
                    ):
                        raise UnsupportedCapabilityError(CAP_DOCUMENT, text) from exc
                retryable = status in {408, 425, 429, 529} or status >= 500
                if retryable and attempt + 1 < self.max_retries:
                    self._sleep(self.retry_base_seconds * (attempt + 1))
                    continue
                raise AIProviderError(
                    text, code=f"http_{status}", retryable=retryable
                ) from exc
            except anthropic.APIConnectionError as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    self._sleep(self.retry_base_seconds * (attempt + 1))
                    continue
                raise AIProviderError(
                    str(exc), code="connection", retryable=True
                ) from exc
        raise AIProviderError(str(last_error or "AI request failed."), retryable=True)


class OpenAIChatCompatibleProvider:
    """Generic OpenAI Chat Completions-compatible HTTP adapter.

    This adapter supports text and images. PDF OCR therefore falls back to the
    configured PDF reader's rendered page images. The endpoint is explicit so
    enterprise gateways can be used without host-specific URL construction.
    """

    name = "openai_chat_compatible"
    capabilities = frozenset({CAP_TEXT, CAP_IMAGE})

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
        timeout: int = 120,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        split = urlsplit(endpoint)
        local = split.hostname in {"localhost", "127.0.0.1", "::1"}
        if split.scheme not in {"http", "https"} or not split.hostname:
            raise AdapterConfigurationError(
                "EPC_AI_ENDPOINT must be an absolute HTTP(S) URL."
            )
        if split.scheme != "https" and not local:
            raise AdapterConfigurationError("Remote AI endpoints must use HTTPS.")
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._sleep = sleep

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None):
        source = os.environ if env is None else env
        return cls(
            endpoint=(source.get("EPC_AI_ENDPOINT") or "").strip(),
            api_key=(source.get("EPC_AI_API_KEY") or "").strip(),
            model=(source.get("EPC_AI_MODEL") or "").strip(),
            auth_header=(source.get("EPC_AI_AUTH_HEADER") or "Authorization").strip(),
            auth_prefix=source.get("EPC_AI_AUTH_PREFIX", "Bearer "),
            timeout=int(source.get("EPC_AI_TIMEOUT_SECONDS", "120")),
            max_retries=int(source.get("EPC_AI_MAX_RETRIES", "3")),
        )

    def diagnostic(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "endpoint": self.endpoint,
            "model": self.model,
            "configured": bool(self.endpoint and self.api_key and self.model),
            "capabilities": sorted(self.capabilities),
        }

    @staticmethod
    def _user_content(request: AIRequest):
        if not request.parts:
            return request.prompt
        content: list[dict] = [{"type": "text", "text": request.prompt}]
        for part in request.parts:
            if part.kind != CAP_IMAGE:
                raise UnsupportedCapabilityError(part.kind)
            encoded = base64.standard_b64encode(part.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.media_type};base64,{encoded}"},
                }
            )
        return content

    @staticmethod
    def _response_text(payload: object) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "The OpenAI-compatible endpoint returned an unexpected response shape.",
                code="invalid_response",
            ) from exc
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "\n".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("text")
            ).strip()
        else:
            text = ""
        if not text:
            raise AIProviderError("The AI endpoint returned no text.", code="empty_response")
        return text

    def complete(self, request: AIRequest) -> str:
        if not self.api_key or not self.model or not self.endpoint:
            raise AIProviderError(
                "The OpenAI-compatible endpoint, key, and model must be configured.",
                code="authentication",
            )
        messages: list[dict] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": self._user_content(request)})
        headers = {"Content-Type": "application/json"}
        headers[self.auth_header] = f"{self.auth_prefix}{self.api_key}"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    if attempt + 1 < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = min(30.0, max(0.0, float(retry_after)))
                        except (TypeError, ValueError):
                            delay = float(attempt + 1) * 2.0
                        self._sleep(delay)
                        continue
                if response.status_code in {401, 403}:
                    raise AIProviderError(
                        "The OpenAI-compatible endpoint rejected the credentials.",
                        code="authentication",
                    )
                if response.status_code >= 400:
                    detail = (
                        response.text[:500]
                        if getattr(response, "text", None)
                        else ""
                    )
                    raise AIProviderError(
                        f"AI endpoint returned HTTP {response.status_code}: {detail}".strip(),
                        code=f"http_{response.status_code}",
                        retryable=False,
                    )
                return self._response_text(response.json())
            except AIProviderError:
                raise
            except requests.RequestException as exc:
                last_error = exc
                error_response = getattr(exc, "response", None)
                status = getattr(error_response, "status_code", None)
                retryable = status is None or status in {408, 425, 429} or (
                    isinstance(status, int) and status >= 500
                )
                if retryable and attempt + 1 < self.max_retries:
                    self._sleep(float(attempt + 1) * 2.0)
                    continue
                raise AIProviderError(
                    str(exc),
                    code=f"http_{status}" if status else "connection",
                    retryable=retryable,
                ) from exc
        raise AIProviderError(str(last_error or "AI request failed."), retryable=True)


def get_ai_provider(env: Mapping[str, str] | None = None) -> AIProvider:
    source = os.environ if env is None else env
    name = (source.get("EPC_AI_PROVIDER") or "anthropic").strip().lower()
    if name == "anthropic":
        return _validate_provider(AnthropicAIProvider.from_environment(source))
    if name in {"openai_chat_compatible", "openai_compatible"}:
        return _validate_provider(OpenAIChatCompatibleProvider.from_environment(source))
    if name == "custom":
        path = (source.get("EPC_AI_ADAPTER") or "").strip()
        provider = load_adapter(
            path,
            kind="AI",
            required_methods=("complete", "diagnostic"),
            env=source,
        )
        return _validate_provider(provider)
    raise AdapterConfigurationError(
        f"Unknown EPC_AI_PROVIDER {name!r}. Use anthropic, "
        "openai_chat_compatible, or custom."
    )
