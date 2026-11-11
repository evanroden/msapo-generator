"""A10: privacy-preserving, paired-environment artifact comparison.

Runs on trusted local/ENFRA runners. Never uploads originals or their extracted text.
The JSON result contains only statuses, metrics and one-way digests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

from lxml import etree
import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat

FORMATS = {".docx", ".pdf"}
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def hashed(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return sha256(raw).hexdigest()


def outcome(left, right, *, precision=None):
    if precision is not None:
        left = [round(float(v), precision) for v in left]
        right = [round(float(v), precision) for v in right]
    return "PASS" if left == right else "FAIL"


def word_fingerprint(blob: bytes) -> dict:
    """Ignore ZIP timestamps and OOXML core metadata, not authored words."""
    with ZipFile(BytesIO(blob)) as z:
        names = sorted(p for p in z.namelist() if p.startswith("word/") and p.endswith(".xml")
                       and (p == "word/document.xml" or re.search(r"/(?:header|footer)\d*\.xml$", p)))
        if "word/document.xml" not in names:
            raise ValueError("Missing Word document body")
        text, tables, fonts, geometry = [], [], [], []
        for name in names:
            root = etree.fromstring(z.read(name))
            text.extend([node.text or "" for node in root.xpath(".//w:t", namespaces=_NS)])
            for tbl in root.xpath(".//w:tbl[not(ancestor::w:tbl)]", namespaces=_NS):
                rows = []
                for row in tbl.xpath("./w:tr", namespaces=_NS):
                    rows.append(tuple("".join(node.text or "" for node in cell.xpath(".//w:t", namespaces=_NS))
                                      for cell in row.xpath("./w:tc", namespaces=_NS)))
                tables.append(rows)
            for elem in root.xpath(".//w:rFonts|.//w:sz|.//w:szCs", namespaces=_NS):
                fonts.append((etree.QName(elem).localname, tuple(sorted(elem.attrib.items()))))
            for elem in root.xpath(".//w:pgSz|.//w:pgMar|.//w:tblW|.//w:tcW|.//w:gridCol|.//w:ind|.//w:spacing", namespaces=_NS):
                geometry.append((etree.QName(elem).localname, tuple(sorted(elem.attrib.items()))))
        media_paths = [p for p in z.namelist() if p.startswith("word/media/") and not p.endswith("/")]
        embedding_paths = [p for p in z.namelist() if p.startswith("word/embeddings/") and not p.endswith("/")]
        embedded_hashes = sorted(hashed(z.read(p)) for p in embedding_paths)
        colors, media_hashes = Counter(), []
        for media_path in media_paths:
            item = z.read(media_path)
            media_hashes.append(hashed(item))
            try:
                with Image.open(BytesIO(item)) as im:
                    sample = im.convert("RGB")
                    sample.thumbnail((160, 160))
                    pixels = list(sample.getdata())
                    colors["chromatic"] += sum(max(c) - min(c) > 12 for c in pixels)
                    colors["total"] += len(pixels)
            except Exception:
                colors["unreadable"] += 1
        return {"text": hashed("\x1f".join(text)), "tables": hashed(repr(tables)),
                "table_count": len(tables), "fonts": hashed(repr(fonts)),
                "geometry": hashed(repr(geometry)), "media": sorted(media_hashes),
                "media_count": len(media_paths), "attachments": embedded_hashes,
                "attachment_count": len(embedding_paths),
                "chromatic_fraction": round(colors["chromatic"] / max(1, colors["total"]), 4),
                "unreadable_media": colors["unreadable"]}


def pdf_page_fingerprint(p) -> dict:
    """One page in bounded memory, independent of PDF object metadata."""
    raw = p.get_text("dict", sort=False)
    spans = []
    for block in raw.get("blocks", ()):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                spans.append((span.get("text", ""), span.get("font", ""),
                              round(span.get("size", 0), 1), span.get("color", 0),
                              tuple(round(float(c), 1) for c in span.get("bbox", ()))))
    scale = min(1, (2000000 / max(1, p.rect.width * p.rect.height)) ** .5)
    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    chroma, pixels = 0, 0
    for r, g, b in image.getdata():
        chroma += max(r, g, b) - min(r, g, b) > 12
        pixels += 1
    return {"text": hashed("\x1f".join(s[0] for s in spans)),
            "captions_and_fonts": hashed(repr([(s[0], s[1], s[2], s[3]) for s in spans])),
            "span_geometry": hashed(repr([s[4] for s in spans])),
            "page_size": [round(p.rect.width, 1), round(p.rect.height, 1)],
            "image_count": len(p.get_images(full=True)), "pixels": image,
            "chromatic_fraction": round(chroma / max(1, pixels), 4)}


def compare_word(a: bytes, b: bytes) -> dict:
    x, y = word_fingerprint(a), word_fingerprint(b)
    return {"content": outcome(x["text"], y["text"]),
            "tables": outcome((x["tables"], x["table_count"]), (y["tables"], y["table_count"])),
            "fonts": outcome(x["fonts"], y["fonts"]),
            "geometry": outcome(x["geometry"], y["geometry"]),
            "artwork": outcome((x["media"], x["unreadable_media"]), (y["media"], y["unreadable_media"])),
            "attachments": outcome(x["attachments"], y["attachments"]),
            "grayscale": outcome(x["chromatic_fraction"], y["chromatic_fraction"]),
            "counts": {"baseline_tables": x["table_count"], "azure_tables": y["table_count"],
                       "baseline_artwork": x["media_count"], "azure_artwork": y["media_count"],
                       "baseline_attachments": x["attachment_count"], "azure_attachments": y["attachment_count"]}}


def compare_pdf(a: bytes, b: bytes, *, max_mean_pixel_error: float = 1.5) -> dict:
    # Do not keep full-page raster buffers for large native reports.
    page_fields = ("text", "captions_and_fonts", "span_geometry", "page_size",
                   "image_count", "chromatic_fraction")
    comparisons = {field: True for field in page_fields}
    errors = []
    with fitz.open(stream=a, filetype="pdf") as base, fitz.open(stream=b, filetype="pdf") as azure:
        page_count = {"baseline": len(base), "azure": len(azure)}
        base_attachments = sorted(hashed(base.embfile_get(i)) for i in range(base.embfile_count()))
        azure_attachments = sorted(hashed(azure.embfile_get(i)) for i in range(azure.embfile_count()))
        for i in range(min(len(base), len(azure))):
            left = pdf_page_fingerprint(base[i])
            right = pdf_page_fingerprint(azure[i])
            for field in page_fields:
                comparisons[field] &= left[field] == right[field]
            if left["pixels"].size != right["pixels"].size:
                errors.append(None)
            else:
                errors.append(round(sum(ImageStat.Stat(ImageChops.difference(
                    left["pixels"], right["pixels"])).mean) / 3, 3))
    same_pages = page_count["baseline"] == page_count["azure"]
    result = {"page_order": "PASS" if same_pages and comparisons["text"] else "FAIL",
              "fonts_captions": "PASS" if same_pages and comparisons["captions_and_fonts"] else "FAIL",
              "geometry": "PASS" if same_pages and comparisons["span_geometry"] and comparisons["page_size"] else "FAIL",
              "artwork_count": "PASS" if same_pages and comparisons["image_count"] else "FAIL",
              "attachments": outcome(base_attachments, azure_attachments),
              "grayscale": "PASS" if same_pages and comparisons["chromatic_fraction"] else "FAIL",
              "page_counts": page_count}
    result["visual"] = ("PASS" if same_pages and all(
        e is not None and e <= max_mean_pixel_error for e in errors) else "FAIL")
    result["max_mean_pixel_error"] = max((e for e in errors if e is not None), default=None)
    return result


def load_identity(path: Path, expected_sha: str, expected_environment: str) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("source_sha") != expected_sha or not SHA.fullmatch(expected_sha):
        raise ValueError("Source SHA missing or mismatched")
    if record.get("environment") != expected_environment:
        raise ValueError("Incorrect environment; refuse production or mislabeled target")
    if record.get("dataset_classification") != "synthetic":
        raise ValueError("Only synthetic data can be compared in public CI")
    if not isinstance(record.get("image_digest"), str) or not DIGEST.fullmatch(record["image_digest"]):
        raise ValueError("Verified image digest absent")
    if not isinstance(record.get("fixture_id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,72}", record["fixture_id"]):
        raise ValueError("Invalid fixture identity")
    return record


def compare_bundle(baseline: Path, azure: Path, *, sha: str, baseline_identity: Path,
                   azure_identity: Path, required: list[str]) -> dict:
    left = load_identity(baseline_identity, sha, "container")
    right = load_identity(azure_identity, sha, "azure-staging")
    if left["image_digest"] != right["image_digest"] or left["fixture_id"] != right["fixture_id"]:
        raise ValueError("Source/digest/fixture mismatch: not comparable environments")
    if not baseline.is_dir() or not azure.is_dir():
        raise ValueError("Both environment output folders must exist")
    if not required:
        raise ValueError("Require explicit artifact paths; an empty pair cannot PASS")
    findings = {}
    for rel in required:
        target = Path(rel)
        if target.is_absolute() or ".." in target.parts or target.suffix.lower() not in FORMATS:
            raise ValueError("Unsafe artifact path or unsupported format")
        a, b = baseline / target, azure / target
        key = hashed(target.as_posix())[:16]  # never publish private file names
        if not a.is_file() or not b.is_file():
            findings[key] = {"format": target.suffix.lower(), "status": "NOT_RUN", "reason": "missing paired artifact"}
            continue
        try:
            checks = (compare_word(a.read_bytes(), b.read_bytes()) if target.suffix.lower() == ".docx"
                      else compare_pdf(a.read_bytes(), b.read_bytes()))
            verdicts = [v for v in checks.values() if v in ("PASS", "FAIL")]
            findings[key] = {"format": target.suffix.lower(), "status": "PASS" if all(v == "PASS" for v in verdicts) else "FAIL",
                             "checks": checks, "baseline_sha256": hashed(a.read_bytes()),
                             "azure_sha256": hashed(b.read_bytes())}
        except (ValueError, OSError, RuntimeError, BadZipFile, etree.XMLSyntaxError) as err:
            findings[key] = {"format": target.suffix.lower(), "status": "FAIL", "reason": type(err).__name__}
    statuses = [v["status"] for v in findings.values()]
    verdict = "FAIL" if "FAIL" in statuses else "NOT_RUN" if "NOT_RUN" in statuses else "PASS"
    return {"status": verdict, "source_sha": sha, "image_digest": left["image_digest"],
            "fixture_sha256": hashed(left["fixture_id"]), "synthetic_only": True,
            "baseline": "container", "candidate": "azure-staging", "artifacts": findings,
            "limitations": ["Neither native Microsoft Word nor physical devices are tested.",
                            "Synthetic parity does not certify AUTH01/AUTH02/AUTH03."]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--azure", type=Path, required=True)
    parser.add_argument("--baseline-identity", type=Path, required=True)
    parser.add_argument("--azure-identity", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--require", action="append", required=True, metavar="RELATIVE_FILE")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_bundle(args.baseline, args.azure, sha=args.sha,
                                baseline_identity=args.baseline_identity,
                                azure_identity=args.azure_identity, required=args.require)
    except (ValueError, OSError, json.JSONDecodeError) as err:
        result = {"status": "BLOCKED", "reason": type(err).__name__,
                  "note": "No parity verdict established"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("A10 parity: " + result["status"])
    return {"PASS": 0, "FAIL": 2, "NOT_RUN": 3, "BLOCKED": 4}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
