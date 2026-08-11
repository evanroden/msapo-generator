from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from scripts import patch_streamlit_metadata as metadata


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STREAMLIT_SHELL = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="description" content="old description" />
    <meta property="og:title" content="old title" />
    <link rel="shortcut icon" href="./favicon.png" />
    <link rel="canonical" href="https://old.example.test/" />
    <title>Streamlit</title>
  </head>
  <body><div id="root"></div></body>
</html>
"""


def _fake_static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "streamlit-static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        DEFAULT_STREAMLIT_SHELL, encoding="utf-8"
    )
    return static_dir


def test_install_branding_replaces_streamlit_shell_with_crawler_metadata(tmp_path):
    static_dir = _fake_static_dir(tmp_path)
    origin = "https://preview.example.test/"

    metadata.install_branding(
        static_dir,
        branding_dir=REPO_ROOT / "branding",
        origin=origin,
    )

    source = (static_dir / "index.html").read_text(encoding="utf-8")
    assert "<title>Process Control</title>" in source
    assert "<title>Streamlit</title>" not in source
    assert f'<meta name="description" content="{metadata.SITE_DESCRIPTION}"' in source
    assert '<meta property="og:title" content="Process Control"' in source
    assert '<meta name="twitter:card" content="summary_large_image"' in source
    assert (
        'content="https://preview.example.test/process-control-preview-v1.png"'
        in source
    )
    assert '<link rel="canonical" href="https://preview.example.test/"' in source
    assert source.count(metadata._BLOCK_START) == 1
    assert source.count(metadata._BLOCK_END) == 1

    assert (static_dir / metadata.ICON_NAME).read_bytes() == (
        REPO_ROOT / "branding" / "process-control-icon.png"
    ).read_bytes()
    assert (static_dir / "favicon.png").read_bytes() == (
        REPO_ROOT / "branding" / "process-control-icon.png"
    ).read_bytes()
    assert (static_dir / metadata.PREVIEW_NAME).read_bytes() == (
        REPO_ROOT / "branding" / "process-control-preview.png"
    ).read_bytes()


def test_install_branding_is_idempotent(tmp_path):
    static_dir = _fake_static_dir(tmp_path)
    branding_dir = REPO_ROOT / "branding"

    metadata.install_branding(static_dir, branding_dir=branding_dir)
    first = (static_dir / "index.html").read_text(encoding="utf-8")
    metadata.install_branding(static_dir, branding_dir=branding_dir)
    second = (static_dir / "index.html").read_text(encoding="utf-8")

    assert second == first
    assert second.count("<title>") == 1
    assert second.count('property="og:title"') == 1
    assert second.count(metadata._BLOCK_START) == 1


@pytest.mark.parametrize(
    "shell",
    (
        "<html><head></head><body></body></html>",
        "<html><head><title>Streamlit</title><body></body></html>",
    ),
)
def test_patch_index_fails_closed_when_streamlit_shell_shape_is_invalid(
    tmp_path, shell
):
    index_path = tmp_path / "index.html"
    index_path.write_text(shell, encoding="utf-8")

    with pytest.raises(RuntimeError):
        metadata.patch_index(index_path)


def test_brand_assets_have_exact_dimensions_and_safe_png_format():
    expected = {
        "process-control-icon.png": (512, 512),
        "process-control-preview.png": (1200, 630),
    }
    for filename, dimensions in expected.items():
        with Image.open(REPO_ROOT / "branding" / filename) as image:
            assert image.format == "PNG"
            assert image.size == dimensions
            image.verify()


def test_docker_build_patches_metadata_after_repository_copy():
    source = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    copy_position = source.index("COPY . .")
    patch_position = source.index("RUN python scripts/patch_streamlit_metadata.py")
    assert patch_position > copy_position
