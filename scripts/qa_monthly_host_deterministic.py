"""Run the existing Monthly latency workload with reproducible synthetic bytes.

Use ONLY in isolated containers, never in a live Streamlit process. Restores
none of the process-wide patches because this CLI intentionally exits after
one synthetic benchmark phase. It does not use production storage or clients.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from itertools import count
from pathlib import Path
import random
import re
import sys
from zipfile import ZipFile, ZipInfo

from PIL import Image
from docx.document import Document as DocumentClass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]+>\s*<[0-9A-Fa-f]+>\s*\]")
_FIXED_ID = b"/ID[<0123456789ABCDEF0123456789ABCDEF><FEDCBA9876543210FEDCBA9876543210>]"


def deterministic_noise(size, sigma, *, ordinal):
    """Seeded Pillow L image with bounded synthetic texture variance."""
    width, height = size
    seed = (width * 1000003 + height * 1009 + int(sigma * 100) * 13 + ordinal)
    img = Image.frombytes("L", size, random.Random(seed).randbytes(width * height))
    return img.point(lambda value: max(0, min(255, round(128 + (value - 128) * sigma / 74))))


def canonical_docx(raw):
    """Normalize only ZIP metadata; leave every source part's bytes unchanged."""
    result = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(result, "w") as target:
        for member in original.infolist():
            info = ZipInfo(member.filename, (2000, 1, 1, 0, 0, 0))
            info.compress_type = member.compress_type
            info.external_attr = member.external_attr
            info.create_system = member.create_system
            target.writestr(info, original.read(member.filename))
    return result.getvalue()


def canonical_pdf(raw):
    """Remove only PyMuPDF's random trailer identifier at fixed byte length."""
    def replace(match):
        if len(match.group(0)) != len(_FIXED_ID):
            raise ValueError("PDF ID geometry differs from synthetic fixture contract")
        return _FIXED_ID
    normalized, matches = _ID.subn(replace, raw)
    if matches != 1:
        raise ValueError("Synthetic PDF must contain exactly one trailer ID pair")
    return normalized


def install_synthetic_patches():
    """Patch only a disposable benchmark process, not the served application."""
    next_image = count(0)
    Image.effect_noise = lambda size, sigma: deterministic_noise(size, sigma, ordinal=next(next_image))
    original_save = DocumentClass.save

    def stable_save(self, target):
        buffer = BytesIO()
        original_save(self, buffer)
        raw = canonical_docx(buffer.getvalue())
        if hasattr(target, "write"):
            target.write(raw)
        else:
            Path(target).write_bytes(raw)

    DocumentClass.save = stable_save
    from scripts import qa_monthly_preview_latency_e2e as qa
    original_pdf = qa._pdf
    qa._pdf = lambda *args, **kwargs: canonical_pdf(original_pdf(*args, **kwargs))
    return qa


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", required=True, choices=("sources", "native"))
    args = parser.parse_args(argv)
    qa = install_synthetic_patches()
    sys.argv = [sys.argv[0], "--part", args.part]
    qa.main()


if __name__ == "__main__":
    main()
