"""Install Process Control branding into Streamlit's static crawler shell.

Streamlit's ``st.set_page_config`` updates the title and icon after the client
application connects. Link-preview crawlers commonly read only the initial
server-rendered ``index.html``, which otherwise says "Streamlit" and exposes no
Open Graph metadata. The Docker build runs this script after dependencies and
repository files have been copied into the image.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


SITE_ORIGIN = "https://msapo-generator.onrender.com"
SITE_TITLE = "Process Control"
SITE_DESCRIPTION = (
    "Prepare purchase-order requests and employee expense reports with guided "
    "review, generated files, and approval handoffs."
)
ICON_NAME = "process-control-icon-v1.png"
PREVIEW_NAME = "process-control-preview-v1.png"
_BLOCK_START = "<!-- process-control-link-preview:start -->"
_BLOCK_END = "<!-- process-control-link-preview:end -->"

_MANAGED_META_NAMES = {
    "application-name",
    "apple-mobile-web-app-title",
    "description",
    "theme-color",
    "twitter:card",
    "twitter:description",
    "twitter:image",
    "twitter:image:alt",
    "twitter:title",
}
_MANAGED_META_PROPERTIES = {
    "og:description",
    "og:image",
    "og:image:alt",
    "og:image:height",
    "og:image:secure_url",
    "og:image:type",
    "og:image:width",
    "og:site_name",
    "og:title",
    "og:type",
    "og:url",
}


def _metadata_block(origin: str = SITE_ORIGIN) -> str:
    """Return deterministic crawler metadata with absolute public image URLs."""
    normalized = origin.rstrip("/")
    icon_url = f"{normalized}/{ICON_NAME}"
    preview_url = f"{normalized}/{PREVIEW_NAME}"
    return f"""{_BLOCK_START}
    <meta name="description" content="{SITE_DESCRIPTION}" />
    <meta name="application-name" content="{SITE_TITLE}" />
    <meta name="apple-mobile-web-app-title" content="{SITE_TITLE}" />
    <meta name="theme-color" content="#092B24" />
    <link rel="canonical" href="{normalized}/" />
    <link rel="icon" type="image/png" sizes="512x512" href="/{ICON_NAME}" />
    <link rel="shortcut icon" type="image/png" href="/{ICON_NAME}" />
    <link rel="apple-touch-icon" sizes="512x512" href="/{ICON_NAME}" />

    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{SITE_TITLE}" />
    <meta property="og:title" content="{SITE_TITLE}" />
    <meta property="og:description" content="{SITE_DESCRIPTION}" />
    <meta property="og:url" content="{normalized}/" />
    <meta property="og:image" content="{preview_url}" />
    <meta property="og:image:secure_url" content="{preview_url}" />
    <meta property="og:image:type" content="image/png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="Process Control — purchase orders and expense reports" />

    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{SITE_TITLE}" />
    <meta name="twitter:description" content="{SITE_DESCRIPTION}" />
    <meta name="twitter:image" content="{preview_url}" />
    <meta name="twitter:image:alt" content="Process Control — purchase orders and expense reports" />
    {_BLOCK_END}"""


def _attribute(tag: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1",
        tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(2).strip().casefold() if match else ""


def _remove_managed_tags(source: str) -> str:
    """Remove Streamlit/default tags that would conflict with our metadata."""
    without_block = re.sub(
        rf"\s*{re.escape(_BLOCK_START)}.*?{re.escape(_BLOCK_END)}\s*",
        "\n",
        source,
        flags=re.DOTALL,
    )

    def keep_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        name = _attribute(tag, "name")
        prop = _attribute(tag, "property")
        if name in _MANAGED_META_NAMES or prop in _MANAGED_META_PROPERTIES:
            return ""
        return tag

    without_meta = re.sub(
        r"<meta\b[^>]*>", keep_meta, without_block, flags=re.IGNORECASE | re.DOTALL
    )

    def keep_link(match: re.Match[str]) -> str:
        tag = match.group(0)
        rel_tokens = set(_attribute(tag, "rel").split())
        if "canonical" in rel_tokens or "icon" in rel_tokens or "apple-touch-icon" in rel_tokens:
            return ""
        return tag

    return re.sub(
        r"<link\b[^>]*>", keep_link, without_meta, flags=re.IGNORECASE | re.DOTALL
    )


def patch_index(index_path: Path, *, origin: str = SITE_ORIGIN) -> None:
    """Patch one Streamlit index in place; safe to run repeatedly."""
    source = index_path.read_text(encoding="utf-8")
    if "</head>" not in source.casefold():
        raise RuntimeError(f"Streamlit index has no closing head tag: {index_path}")

    source = _remove_managed_tags(source)
    # Removing an indented tag can leave spaces on an otherwise empty line.
    # Normalize only whitespace-only lines so a second patch is byte-identical
    # without rewriting Streamlit's scripts or meaningful HTML formatting.
    source = re.sub(r"(?m)^[ \t]+$", "", source)
    source = re.sub(
        r"\s*</head>", "\n  </head>", source, count=1, flags=re.IGNORECASE
    )
    source, title_count = re.subn(
        r"<title\b[^>]*>.*?</title>",
        f"<title>{SITE_TITLE}</title>",
        source,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if title_count != 1:
        raise RuntimeError(
            f"Expected exactly one title in Streamlit index, found {title_count}: "
            f"{index_path}"
        )

    source, head_count = re.subn(
        r"\n[ \t]*</head>",
        f"\n    {_metadata_block(origin)}\n  </head>",
        source,
        count=1,
        flags=re.IGNORECASE,
    )
    if head_count != 1:
        raise RuntimeError(f"Could not patch Streamlit head: {index_path}")
    index_path.write_text(source, encoding="utf-8")


def install_branding(
    static_dir: Path,
    *,
    branding_dir: Path,
    origin: str = SITE_ORIGIN,
) -> None:
    """Copy public assets and patch the crawler-visible Streamlit shell."""
    index_path = static_dir / "index.html"
    icon_source = branding_dir / "process-control-icon.png"
    preview_source = branding_dir / "process-control-preview.png"
    required = (index_path, icon_source, preview_source)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing link-preview input(s): " + ", ".join(missing))

    shutil.copyfile(icon_source, static_dir / ICON_NAME)
    shutil.copyfile(icon_source, static_dir / "favicon.png")
    shutil.copyfile(preview_source, static_dir / PREVIEW_NAME)
    patch_index(index_path, origin=origin)


def _default_static_dir() -> Path:
    import streamlit

    return Path(streamlit.__file__).resolve().parent / "static"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", type=Path, default=None)
    parser.add_argument("--branding-dir", type=Path, default=None)
    parser.add_argument("--origin", default=SITE_ORIGIN)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    install_branding(
        args.static_dir or _default_static_dir(),
        branding_dir=args.branding_dir or repository_root / "branding",
        origin=args.origin,
    )


if __name__ == "__main__":
    main()
