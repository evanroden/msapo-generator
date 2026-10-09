"""Fail builds if the verified document renderer or template fonts drift."""

import re
import subprocess
from pathlib import Path

FONT_MATCHES = {
    "Arial": "LiberationSans-Regular.ttf",
    "Arial:style=Bold": "LiberationSans-Bold.ttf",
    "Arial Narrow": "texgyreheroscn-regular.otf",
    "Arial Narrow:style=Bold": "texgyreheroscn-bold.otf",
    "Times New Roman": "LiberationSerif-Regular.ttf",
    "Symbol": "opens___.ttf",
    "Calibri": "Carlito-Regular.ttf",
    "Calibri:style=Bold": "Carlito-Bold.ttf",
    "Calibri:style=Italic": "Carlito-Italic.ttf",
    "Cambria": "Caladea-Regular.ttf",
    "Cambria:style=Bold": "Caladea-Bold.ttf",
}


def check_renderer() -> None:
    version = subprocess.check_output(
        ["libreoffice", "--version"], text=True, timeout=30
    ).strip()
    if not re.match(r"LibreOffice 24\.2\.\d+\b", version):
        raise RuntimeError(f"Expected the verified LibreOffice 24.2 renderer: {version}")
    print(version)
    for pattern, expected in FONT_MATCHES.items():
        resolved = subprocess.check_output(
            ["fc-match", "--format=%{file}", pattern], text=True, timeout=30
        ).strip()
        if Path(resolved).name != expected or not Path(resolved).is_file():
            raise RuntimeError(f"Font {pattern!r}: expected {expected}, got {resolved!r}")
        print(f"{pattern}: {expected}")


if __name__ == "__main__":
    check_renderer()
