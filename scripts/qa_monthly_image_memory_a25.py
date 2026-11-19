"""A25 synthetic image memory/CPU benchmark. No client files or network.

Use the *same* script, dependencies and 512 MiB / 0.5 CPU container
against the baseline and candidate code roots. The subprocess for each
scenario prevents previous high-water RSS from contaminating the next one.
Output is observational; no fabricated baseline or imposed speed target.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
from time import perf_counter
from zipfile import ZIP_DEFLATED, ZipFile


def _hash(data):
    return sha256(data).hexdigest()


def _jpeg(index, size=(4800, 3200)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, ((index * 31 + 90) % 256, 80, 170))
    draw = ImageDraw.Draw(image)
    for n in range(0, 24):
        x = n * 197
        draw.line((x, 0, max(0, x - 250), size[1]), fill=(20, 90 + index, 230), width=8)
    output = BytesIO()
    image.save(output, "JPEG", quality=85)
    image.close()
    return output.getvalue()


def _png(*, transparent):
    from PIL import Image, ImageDraw, PngImagePlugin
    image = Image.new("RGBA" if transparent else "RGB", (4800, 3200),
                      (240, 20, 90, 0) if transparent else (255, 255, 255))
    ImageDraw.Draw(image).rectangle((600, 600, 4100, 2600),
                                    fill=(8, 125, 210, 255) if transparent else (8, 125, 210))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Author", "A25_SYNTHETIC_METADATA_CANARY")
    output = BytesIO()
    image.save(output, "PNG", pnginfo=metadata)
    image.close()
    return output.getvalue()


def _heif():
    from PIL import Image
    from pillow_heif import from_pillow
    image = Image.new("RGB", (4800, 3200), (12, 140, 80))
    output = BytesIO()
    from_pillow(image).save(output)
    image.close()
    return output.getvalue()


def _rss_mib():
    # Linux maximum resident set size, not virtual size or estimated image bytes.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _cgroup():
    results = {}
    for item in ("memory.max", "cpu.max"):
        try:
            results[item] = Path("/sys/fs/cgroup", item).read_text().strip()
        except OSError:
            results[item] = "not available"
    return results


def _docx_with_repeated_photos(photo):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<document>synthetic</document>")
        for index in range(8):
            archive.writestr(f"word/media/photo{index}.jpg", photo)
    return output.getvalue()


def prepare_fixtures(directory):
    """Create source bytes once, then share EXACT inputs between base and head."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(8):
        (directory / f"photo{index}.jpg").write_bytes(_jpeg(index))
    (directory / "preview.docx").write_bytes(_docx_with_repeated_photos(
        (directory / "photo0.jpg").read_bytes()))
    (directory / "line_art.png").write_bytes(_png(transparent=False))
    (directory / "transparency.png").write_bytes(_png(transparent=True))
    (directory / "control.heic").write_bytes(_heif())
    return {p.name: _hash(p.read_bytes()) for p in sorted(directory.iterdir()) if p.is_file()}


def worker(root, scenario, fixtures):
    sys.path.insert(0, str(Path(root).resolve()))
    from app.image_open import open_image
    from app.monthly_report_media_privacy import clear_transparent_png_rgb
    from app.monthly_report_docx import normalize_report_image
    from app.monthly_report_preview_images import write_preview_docx

    fixture = Path(fixtures)
    if scenario == "photos":
        inputs = [(fixture / f"photo{index}.jpg").read_bytes() for index in range(8)]
    elif scenario in ("preview", "line_art", "transparency", "heif"):
        filename = {"preview": "preview.docx", "line_art": "line_art.png",
                    "transparency": "transparency.png", "heif": "control.heic"}[scenario]
        inputs = [(fixture / filename).read_bytes()]
    else:
        raise ValueError(scenario)
    input_hashes = [_hash(data) for data in inputs]
    rss_after_fixtures = _rss_mib()

    measurements = []
    for pass_index in range(2):
        start_wall = perf_counter()
        start_cpu = resource.getrusage(resource.RUSAGE_SELF)
        shapes, result_hashes = [], []
        hidden_rgb_leak = False
        author_metadata_leak = False
        if scenario == "preview":
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory, "preview.docx")
                write_preview_docx(inputs[0], target)
                with ZipFile(target) as archive:
                    parts = [archive.read(info) for info in archive.namelist()
                             if info.startswith("word/media/")]
                if len(parts) != 8 or len(set(map(_hash, parts))) != 1:
                    raise AssertionError("duplicate photos not preserved")
                for data in parts:
                    with open_image(BytesIO(data), formats=("JPEG", "PNG")) as image:
                        shapes.append(image.size)
                    result_hashes.append(_hash(data))
        else:
            suffix = ".heic" if scenario == "heif" else ".png" if scenario in (
                "line_art", "transparency") else ".jpg"
            for raw in inputs:
                result = normalize_report_image(raw, suffix,
                    line_art=scenario == "line_art",
                    preserve_transparency=scenario == "transparency")
                # Normalized assets keep their prior digest. Privacy applies to
                # the disposable exported rendition, not stored normalization.
                exported = (clear_transparent_png_rgb(result.data)
                            if scenario == "transparency" else result.data)
                with open_image(BytesIO(exported), formats=("JPEG", "PNG")) as image:
                    if image.size != (result.width, result.height):
                        raise AssertionError("incorrect reported geometry")
                    if scenario == "transparency" and image.getpixel((0, 0)) != (0, 0, 0, 0):
                        hidden_rgb_leak = True
                if b"A25_SYNTHETIC_METADATA_CANARY" in exported:
                    author_metadata_leak = True
                shapes.append((result.width, result.height))
                result_hashes.append(_hash(exported))
        if [_hash(data) for data in inputs] != input_hashes:
            raise AssertionError("original modified")
        end_cpu = resource.getrusage(resource.RUSAGE_SELF)
        measurements.append({
            "pass": "cold" if pass_index == 0 else "warm-repeat",
            "wall_ms": round((perf_counter() - start_wall) * 1000, 2),
            "cpu_ms": round(((end_cpu.ru_utime + end_cpu.ru_stime)
                             - (start_cpu.ru_utime + start_cpu.ru_stime)) * 1000, 2),
            "process_peak_rss_mib": round(_rss_mib(), 2),
            "geometry": shapes, "output_sha256": result_hashes,
            "hidden_rgb_leak": hidden_rgb_leak,
            "author_metadata_leak": author_metadata_leak
        })
    if measurements[0]["output_sha256"] != measurements[1]["output_sha256"]:
        raise AssertionError("cold/warm output changed")
    return {"scenario": scenario, "inputs": len(inputs),
            "original_sha256": input_hashes, "rss_after_fixtures_mib": rss_after_fixtures,
            "passes": measurements, "cgroup": _cgroup()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--fixtures")
    parser.add_argument("--prepare-fixtures", action="store_true")
    parser.add_argument("--worker", choices=["photos", "preview", "line_art", "transparency", "heif"])
    args = parser.parse_args()
    if args.prepare_fixtures:
        if not args.fixtures:
            parser.error("--prepare-fixtures needs --fixtures")
        print(json.dumps(prepare_fixtures(args.fixtures), sort_keys=True))
        return
    if args.worker:
        print(json.dumps(worker(args.code_root, args.worker, args.fixtures), sort_keys=True))
        return
    if not args.fixtures:
        parser.error("--fixtures is required to compare identical source bytes")
    results = []
    for scenario in ("photos", "preview", "line_art", "transparency", "heif"):
        command = [sys.executable, __file__, "--worker", scenario, "--code-root", args.code_root,
                   "--fixtures", args.fixtures]
        try:
            run = subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)
        except subprocess.CalledProcessError as exc:
            print("worker failed:", scenario, exc, file=sys.stderr)
            print(exc.stdout, file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
            raise
        results.append(json.loads(run.stdout))
    result = {"code_root": args.code_root, "scenarios": results}
    data = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(data + "\n")
    print(data)


if __name__ == "__main__":
    main()
