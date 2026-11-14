"""Dynamic adapter loading for operator-supplied integrations.

Custom adapter paths use ``package.module:factory``. The factory receives a copy
of the environment mapping and returns an object implementing the documented
protocol for that adapter type. Environment-controlled imports are appropriate
only for trusted deployment configuration; user input is never used here.
"""

from __future__ import annotations

import inspect
import os
from importlib import import_module
from typing import Any, Mapping, Sequence


class AdapterConfigurationError(RuntimeError):
    """Raised when a configured adapter cannot be loaded or validated."""


def load_adapter(
    path: str,
    *,
    kind: str,
    required_methods: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> Any:
    """Load and validate one trusted adapter factory.

    Factories may accept either zero arguments or one environment mapping. This
    makes small internal adapters easy to write while still allowing fully
    configuration-driven implementations.
    """
    target = (path or "").strip()
    if not target or ":" not in target:
        raise AdapterConfigurationError(
            f"{kind} adapter must use 'package.module:factory' syntax."
        )
    module_name, attr_name = target.rsplit(":", 1)
    if not module_name or not attr_name or module_name.startswith("."):
        raise AdapterConfigurationError(
            f"{kind} adapter path {target!r} is invalid."
        )
    try:
        factory = getattr(import_module(module_name), attr_name)
    except (ImportError, AttributeError) as exc:
        raise AdapterConfigurationError(
            f"Could not import {kind} adapter {target!r}: {exc}"
        ) from exc
    if not callable(factory):
        raise AdapterConfigurationError(
            f"Configured {kind} adapter factory {target!r} is not callable."
        )

    environment = dict(os.environ if env is None else env)
    try:
        signature = inspect.signature(factory)
        # Prefer passing the environment whenever the callable accepts one
        # positional value, including optional ``env=None`` factories. Fall back
        # to a zero-argument call only when binding one argument is invalid.
        try:
            signature.bind(environment)
        except TypeError:
            try:
                signature.bind()
            except TypeError as exc:
                raise AdapterConfigurationError(
                    f"{kind} adapter factory {target!r} must accept zero arguments "
                    "or one environment mapping."
                ) from exc
            adapter = factory()
        else:
            adapter = factory(environment)
    except AdapterConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve adapter root cause
        raise AdapterConfigurationError(
            f"Could not initialize {kind} adapter {target!r}: {exc}"
        ) from exc

    missing = [name for name in required_methods if not callable(getattr(adapter, name, None))]
    if missing:
        raise AdapterConfigurationError(
            f"{kind} adapter {target!r} is missing required methods: "
            + ", ".join(missing)
        )
    return adapter
