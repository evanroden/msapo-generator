"""Synthetic, reproducible monthly size calibration: small, text, and photos.

One explicit generate per fixture. No user sources, paid calls or shared saves.
Run with production renderer, ideally under the same 512 MiB/0.5 CPU limits
used by the native source fixture. Print full byte counts; never use this
calibration probe as evidence of served/browser acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from io import BytesIO

from PIL import Image

from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_docx import estimate_bytes, generate_report
from app.monthly_report_model import (
    BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_size_forecast import forecast_output_sizes


def _fixture(kind):
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    assets = {}
    if kind == "small":
        return draft, assets
    if kind == "text":
        # Varied, repeatable text, including numerical statements, without
        # dates/prices or placeholder instructions that preflight refuses.
        prose = "\n".join(
            f"Synthetic equipment note {i:04d}: inspected pump and verified "
            f"flow {i % 127 + 10} gpm; work record QA-{i:04d} retained."
            for i in range(2200)
        )
        draft = replace(draft, blocks=tuple(
            replace(b, text=prose) if b.key == "demo_activity" else b
            for b in draft.blocks
        ))
        return draft, assets
    if kind != "photos":
        raise ValueError(kind)
    images = []
    for index in range(6):
        # No data copied from real facility photographs.
        img = Image.effect_noise((900, 600), 30 + index).convert("RGB")
        raw = BytesIO()
        img.save(raw, format="JPEG", quality=87)
        img.close()
        data = raw.getvalue()
        name = hashlib.sha256(data).hexdigest() + ".jpg"
        assets[name] = data
        images.append(name)
    photos = approve_all_assets(ResolvedBlock(
        "improvements", "This month", asset_hashes=tuple(images), photos_per_page=2))
    sections = tuple(
        replace(s, blocks=(*s.blocks, BlockSpec("improvements", "image_grid")))
        if s.key == "activity" else s for s in draft.sections
    )
    return replace(draft, sections=sections, blocks=(*draft.blocks, photos)), assets


def main():
    with tempfile.TemporaryDirectory(prefix="synthetic-size-calibration-") as root:
        os.environ["EPC_DATA_DIR"] = root
        results = []
        for kind in ("small", "text", "photos"):
            draft, assets = _fixture(kind)
            measured_input = estimate_bytes(draft, assets.__getitem__)
            forecast = forecast_output_sizes(measured_input, libreoffice_available=True)
            package = generate_report(
                draft, acknowledged_fingerprint=draft.fingerprint,
                asset_loader=assets.__getitem__)
            if not package.pdf:
                raise RuntimeError(f"{kind} PDF failed: {package.pdf_error}")
            word_bytes, pdf_bytes = len(package.docx), len(package.pdf)
            result = dict(
                kind=kind, preflight_heuristic_bytes=measured_input,
                image_asset_count=len(assets), word_bytes=word_bytes,
                pdf_bytes=pdf_bytes,
                word_forecast=[forecast.word.low, forecast.word.high],
                pdf_forecast=[forecast.pdf.low, forecast.pdf.high],
                word_inside=forecast.word.low <= word_bytes <= forecast.word.high,
                pdf_inside=forecast.pdf.low <= pdf_bytes <= forecast.pdf.high,
            )
            results.append(result)
            if not result["word_inside"] or not result["pdf_inside"]:
                print(json.dumps(dict(results=results), indent=2), flush=True)
                raise AssertionError(f"{kind}: output outside proposed forecast")
        print(json.dumps(dict(synthetic_only=True, results=results), indent=2), flush=True)


if __name__ == "__main__":
    main()
