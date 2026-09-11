"""One bounded retry policy for interactive model requests.

SDK retries must be disabled on clients using this helper. A single deadline
covers transport retries AND malformed-response retries within an operation.
"""

from __future__ import annotations

import time
import os
import math
from collections.abc import Callable
from typing import TypeVar

import anthropic
import httpx

T = TypeVar("T")


def _seconds_setting(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if math.isfinite(value) and low <= value <= high else default


OPERATION_BUDGET_SECONDS = _seconds_setting(
    "EPC_ANALYSIS_BUDGET_SECONDS", 120.0, 30.0, 300.0
)
REQUEST_TIMEOUT_SECONDS = min(
    OPERATION_BUDGET_SECONDS,
    _seconds_setting("EPC_API_TIMEOUT_SECONDS", 60.0, 10.0, 120.0),
)


class IncompleteResponseError(RuntimeError):
    """Do not treat partial model output as a successful document reading."""


def complete_response_text(message: anthropic.types.Message) -> str:
    # A token-limited response can still contain valid JSON or plausible OCR.
    # Check the completion signal before exposing any of that partial content.
    # This is not a transport/encoding failure, so retrying or rasterizing the
    # same source must not hide it or spend another request automatically.
    if message.stop_reason not in {"end_turn", "stop_sequence"}:
        raise IncompleteResponseError(
            "Automatic reading was incomplete. Try a smaller source, paste the "
            "complete quote text, or enter receipt details manually."
        )
    text = "\n".join(block.text for block in message.content if block.type == "text").strip()
    if not text:
        raise IncompleteResponseError(
            "Automatic reading was incomplete: no readable text was returned. "
            "Retry or enter the details manually."
        )
    return text


def request_with_retry(
    operation: Callable[[httpx.Timeout], T],
    *,
    until: float,
    attempts: int = 3,
    backoff: float = 3.0,
) -> T:
    for attempt in range(attempts):
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Automatic reading timed out. Retry or enter the details manually."
            )
        try:
            return operation(
                httpx.Timeout(
                    min(REQUEST_TIMEOUT_SECONDS, remaining), connect=min(5.0, remaining)
                )
            )
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            retryable = isinstance(exc, anthropic.APIConnectionError) or (
                exc.status_code == 429 or exc.status_code >= 500
            )
            if not retryable or attempt == attempts - 1:
                raise
            delay = backoff * (attempt + 1)
            if time.monotonic() + delay >= until:
                raise TimeoutError(
                    "Automatic reading timed out. Retry or enter the details manually."
                ) from exc
            time.sleep(delay)
    raise ValueError("At least one API attempt is required")
