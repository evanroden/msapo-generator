import fitz

from app.scope_pdf import build_scope_pdf


def _text(payload: bytes) -> str:
    document = fitz.open(stream=payload, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def test_scope_pdf_contains_only_the_reviewed_supporting_sections():
    payload = build_scope_pdf(
        scope="Repair the chilled water pump and verify operation.",
        inclusions=["Labor", "Startup testing"],
        exclusions=["Painting"],
        vendor="Vendor & Sons",
        site="UMMC",
    )

    assert payload.startswith(b"%PDF-")
    text = _text(payload)
    assert "ENFRA | PURCHASE ORDER SUPPORT" in text
    assert "Scope, Inclusions, and Exclusions" in text
    assert "Vendor: Vendor & Sons" in text
    assert "Site: UMMC" in text
    assert "Scope" in text
    assert "Repair the chilled water pump" in text
    assert "Inclusions" in text
    assert "- Labor" in text
    assert "Exclusions" in text
    assert "- Painting" in text
    assert "MSAPO AGREEMENT" not in text


def test_scope_pdf_paginates_long_content_without_dropping_the_final_item():
    inclusions = [f"Inclusion item {index} with supporting detail" for index in range(80)]
    exclusions = [f"Exclusion item {index}" for index in range(50)]
    payload = build_scope_pdf(
        scope="\n".join(f"Scope task {index}" for index in range(100)),
        inclusions=inclusions,
        exclusions=exclusions,
    )

    document = fitz.open(stream=payload, filetype="pdf")
    try:
        assert len(document) > 1
        text = "\n".join(page.get_text() for page in document)
    finally:
        document.close()
    assert "Scope task 99" in text
    assert "Inclusion item 79" in text
    assert "Exclusion item 49" in text
