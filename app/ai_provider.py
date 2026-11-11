"""Fail-closed AI provider selection and the existing Anthropic SDK boundary.

Azure hosting is not AI-provider approval. Only the already-installed Anthropic
client is implemented here; disabled/unrecognized providers never create a
client or silently fall back to an external destination. An enterprise adapter
must be added only after ENFRA approves its actual endpoint and data contract.

This module does not send requests, store secrets, log payloads or decide model
outputs. The callers retain their deadline, schema, evidence and media limits.
"""

from __future__ import annotations

import os
from typing import Any, Callable


class AIProviderConfigurationError(ValueError):
    """The configured AI destination is disabled or has no reviewed adapter."""


def require_configured_provider() -> None:
    """Validate routing before creating an SDK client or submitting any content.

    The default retains the existing Render behavior, not an Azure approval.
    Azure environments MUST set EPC_AI_PROVIDER=disabled unless Anthropic
    egress is explicitly approved. No other provider is implemented yet.
    """
    choice = os.environ.get("EPC_AI_PROVIDER", "anthropic").strip().casefold()
    if choice == "disabled":
        raise AIProviderConfigurationError(
            "Automatic reading is disabled for this environment. "
            "Use manual entry or available local document reading."
        )
    if choice != "anthropic":
        raise AIProviderConfigurationError(
            "The configured AI provider has no approved adapter. "
            "No external request was made; continue manually."
        )
    # The Anthropic SDK honors ANTHROPIC_BASE_URL as a global transport
    # override. Do not accidentally route existing credentials/documents to
    # a custom endpoint presented as a drop-in enterprise gateway.
    if os.environ.get("ANTHROPIC_BASE_URL", "").strip():
        raise AIProviderConfigurationError(
            "A custom Anthropic base URL is not enabled by this adapter. "
            "No external request was made; continue manually."
        )


def anthropic_client(
    *,
    factory: Callable[..., Any],
    api_key: str,
    timeout: Any = None,
) -> Any:
    """Create the only supported SDK client; callers own lifecycle and retry.

    Injecting the SDK factory preserves existing synthetic test seams. This
    function performs no paid request and intentionally has no fallback route.
    """
    require_configured_provider()
    if not api_key:
        raise AIProviderConfigurationError(
            "Automatic reading credentials are not configured. "
            "Continue manually or use locally extracted text."
        )
    options: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
    if timeout is not None:
        options["timeout"] = timeout
    return factory(**options)
