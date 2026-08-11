from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BINARY_SOURCE_FILES = {
    "templates/Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx",
    "templates/Master_MSAPO_Template.docx",
}
FORBIDDEN_TRACKED_PARTS = {
    "__pycache__",
    "data_store",
    "equipment_render",
    "output",
    "upload",
}
SECRET_PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "ENFRA email address": re.compile(
        r"[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)*enfrasolutions\.com\b",
        re.IGNORECASE,
    ),
    "live Smartsheet form identifier": re.compile(
        r"https://app\.smartsheet\.com/b/form/(?!0{32}(?:\b|/))[0-9a-f]{32}\b",
        re.IGNORECASE,
    ),
}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [item for item in result.stdout.decode().split("\0") if item]


def test_generated_private_and_uploaded_files_are_not_tracked():
    problems: list[str] = []
    for relative in _tracked_files():
        path = Path(relative)
        if FORBIDDEN_TRACKED_PARTS.intersection(path.parts):
            problems.append(relative)
        if path.suffix.casefold() in {
            ".db",
            ".eml",
            ".heic",
            ".jpeg",
            ".jpg",
            ".pdf",
            ".png",
            ".pyc",
            ".pyo",
            ".sqlite",
            ".tif",
            ".tiff",
            ".webp",
            ".xls",
            ".xlsx",
            ".docx",
        } and relative not in ALLOWED_BINARY_SOURCE_FILES:
            problems.append(relative)
        if path.name == ".env":
            problems.append(relative)
    assert not problems, "private/generated files are tracked: " + ", ".join(
        sorted(set(problems))
    )


def test_tracked_text_has_no_high_confidence_secret_or_private_endpoint():
    findings: list[str] = []
    for relative in _tracked_files():
        path = REPO_ROOT / relative
        if relative in ALLOWED_BINARY_SOURCE_FILES:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(source):
                findings.append(f"{relative}: {label}")
    assert not findings, "public-tree hygiene findings: " + ", ".join(findings)


def test_public_examples_and_render_blueprint_require_private_configuration():
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    blueprint = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "ANTHROPIC_API_KEY=replace-with-private-key" in example
    assert "RRH_APPROVER_EMAIL=rrh.approver@example.invalid" in example
    assert "/b/form/00000000000000000000000000000000" in example
    for key in (
        "RRH_APPROVER_NAME",
        "RRH_APPROVER_EMAIL",
        "SMARTSHEET_FORM_URL",
        "SMARTSHEET_API_TOKEN",
        "SMARTSHEET_SHEET_ID",
    ):
        assert f"- key: {key}\n        sync: false" in blueprint
