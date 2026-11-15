"""Read-only, broad pre-generation planning ranges for Monthly Word/PDF exports.

The preflight estimate is an input-size/layout heuristic, NOT a finished file.
These intentionally broad bands bracket the two dated historical P7 failures
and the capped synthetic native-report run, pending a larger calibration set.
No report assembly, conversion, AI, library save or asset read occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from shutil import which

_MIB = 1024 * 1024
_MIN = 16 * 1024
# Largest dated synthetic native example was roughly 13 MiB; cap extrapolation.
_MAX_CALIBRATED_INPUT = 16 * _MIB


@dataclass(frozen=True)
class SizeRange:
    low: int
    high: int

    def __post_init__(self):
        if not (0 < self.low <= self.high):
            raise ValueError("Invalid size forecast range")


@dataclass(frozen=True)
class OutputSizeForecast:
    word: SizeRange | None
    pdf: SizeRange | None
    reason: str = ""
    pdf_reason: str = ""


def _range(estimate: int, *, low_ratio: float, high_ratio: float, minimum_high: int) -> SizeRange:
    # Outward rounding avoids presenting false byte-level precision.
    quantum = 16 * 1024
    low = max(_MIN, floor(estimate * low_ratio / quantum) * quantum)
    high = ceil(max(minimum_high, estimate * high_ratio) / quantum) * quantum
    return SizeRange(low, high)


def forecast_output_sizes(estimated_source_bytes: int, *, sources_ready: bool = True,
                          pdf_backend: str = "libreoffice",
                          libreoffice_available: bool | None = None) -> OutputSizeForecast:
    """Return distinct broad ranges, or an explicit unavailable result.

    ``estimated_source_bytes`` is the existing cheap preflight heuristic. It
    cannot be relabeled as finished Word/PDF size. Ratios deliberately allow
    compressed native artwork and expanded/repackaged illustrations, whose
    outputs have differed by several-fold in the reported P7 samples. Bounds
    are planning aids, not hard limits, confidence intervals or approval.
    """
    if not sources_ready:
        return OutputSizeForecast(None, None, "Required source files are unavailable.")
    if type(estimated_source_bytes) is not int or not 0 < estimated_source_bytes <= _MAX_CALIBRATED_INPUT:
        return OutputSizeForecast(None, None, "This report is outside the measured forecast inputs.")
    word = _range(estimated_source_bytes, low_ratio=0.08, high_ratio=6.5,
                  minimum_high=4 * _MIB)
    # Gotenberg and docx2pdf are not production/CI-validated conversion paths.
    # Do not imply they are available or that their PDF sizes are predictable.
    if pdf_backend != "libreoffice":
        return OutputSizeForecast(word, None, pdf_reason="PDF converter is not calibrated for estimates.")
    if libreoffice_available is None:
        libreoffice_available = bool(which("libreoffice") or which("soffice"))
    if not libreoffice_available:
        return OutputSizeForecast(word, None, pdf_reason="PDF conversion is unavailable here.")
    pdf = _range(estimated_source_bytes, low_ratio=0.06, high_ratio=6.0,
                 minimum_high=5 * _MIB)
    return OutputSizeForecast(word, pdf)


def format_size_range(value: SizeRange | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value.low / _MIB:.2f}–{value.high / _MIB:.2f} MB"
