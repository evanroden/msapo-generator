"""The documentation index must not fall behind the directory it indexes.

An agent arriving with no conversation history reads ``docs/README.md`` to learn
what is current and what has been superseded. An unlisted document is invisible
to that reader, and -- worse -- a document listed as current after it has been
reversed is actively misleading. Both failures are silent, so both are pinned
here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"


def _index_text() -> str:
    return INDEX.read_text(encoding="utf-8")


def _documents() -> list[Path]:
    return sorted(p for p in DOCS.glob("*.md") if p.name != "README.md")


def test_every_document_appears_in_the_index():
    text = _index_text()
    missing = [p.name for p in _documents() if p.name not in text]
    assert not missing, (
        "these documents are invisible to an agent reading docs/README.md: "
        + ", ".join(missing)
    )


def test_the_index_lists_no_document_that_was_deleted():
    """A dangling row is a broken link in the one file meant to orient a reader."""
    text = _index_text()
    present = {p.name for p in _documents()}
    referenced = {
        token.strip("()[]`,")
        for token in text.replace("(", " ").replace(")", " ").split()
        if token.strip("()[]`,").endswith(".md")
    }
    dangling = {
        name
        for name in referenced
        if name not in present and name not in {"README.md", "../README.md"}
    }
    assert not dangling, f"index references missing documents: {sorted(dangling)}"


@pytest.mark.parametrize(
    "name",
    [p.name for p in DOCS.glob("COMMIT_NOTES_*.md")],
)
def test_every_commit_notes_document_carries_locating_front_matter(name):
    """The front matter is what lets an agent get from a ``git log`` line to the
    reasoning behind it, and back. Without a base commit the notes cannot be
    placed in history at all."""
    text = (DOCS / name).read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{name} has no YAML front matter"
    front = text.split("---\n", 2)[1]
    for field in ("document_type:", "base_commit:", "date:", "status:"):
        assert field in front, f"{name} front matter is missing {field}"


def test_superseded_documents_still_warn_at_the_top():
    """The PO attachment format reversed twice. Both overtaken documents remain
    linked from the README as authoritative on other subjects, so the warning has
    to travel with the document rather than living only in the index."""
    for name in (
        "PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md",
        "STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md",
    ):
        head = (DOCS / name).read_text(encoding="utf-8")[:2000]
        assert "PARTIALLY REVERSED 2026-08-12" in head, (
            f"{name} no longer warns that its attachment-format section is stale"
        )


def test_readme_does_not_call_the_live_renderer_modules_dormant():
    """They were dormant, then became the PO attachment path on 2026-08-12. The
    stale sentence invited deleting the code that renders every attachment."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/README.md" in readme, "the README no longer points at the index"

    # "were dormant until 2026-08-12" is the correct history and must stay
    # sayable; a present-tense claim is the one that misleads.
    stale = ("remain dormant", "are dormant", "is dormant", "dormant historical")
    for line in readme.splitlines():
        if "document_generator" in line or "pdf_converter" in line:
            lowered = line.lower()
            assert not any(phrase in lowered for phrase in stale), (
                f"README calls a live renderer module dormant: {line!r}"
            )

    # And the live path must actually be findable in the structure listing.
    assert "app/document_generator.py" in readme and "app/pdf_converter.py" in readme
