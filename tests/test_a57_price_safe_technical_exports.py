"""A57: synthetic price/contact canaries and technical-sibling preservation.

No customer documents or paid model calls. Readable native passages and original
page images have different client-export safety requirements.
"""
from dataclasses import asdict
import json

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_structured_uploads as structured
from app.monthly_report_content_policy import contains_price, page_status
from app.monthly_report_model import ReportSource
from app.monthly_report_sources import SourceContent


TECH = "Inspected pump P-TEST-42 at 128 psi."
SECOND = "Replacement valve V-TEST-3 remains pending."
PRICE = "Proposal amount: $18,675.50"
RANGE = "Quoted range USD 4,000 to 6,000"
FOOTER = "Footer - not-to-exceed $29,450"
CONTACT = "Contact: Sample Person; Email: sample@example.invalid"


def source(text, suffix=".pdf"):
    return ReportSource("a" * 64, "synthetic-vendor" + suffix, "b" * 64,
                        suffix, page_texts=(text,))


def test_native_activity_recovers_independent_technical_siblings_without_approving_original_page():
    original = source("\n".join((PRICE, TECH, RANGE, SECOND, FOOTER, CONTACT)))
    before = asdict(original)
    result = structured.native_update((SourceContent(original, ()),), "activity_summary")
    assert TECH in result.text and SECOND in result.text
    assert not any(value in result.text for value in ("18,675.50", "4,000", "6,000", "29,450", "sample@example.invalid"))
    assert not contains_price(result.text)
    assert result.references
    assert asdict(original) == before
    assert page_status(original.page_texts[0])[0] == "pricing"


def test_optional_reader_receives_only_price_free_native_spans():
    original = source("\n".join((PRICE, TECH, RANGE, SECOND, FOOTER, CONTACT)), ".docx")
    before = asdict(original)
    key, request = ai.extraction_request(original, (1,))
    assert key and len(request) == 1
    payload = json.loads(request[0]["text"].rsplit("\n", 1)[1])
    sent = payload["pages"][0]["text"]
    assert TECH in sent and SECOND in sent
    assert not any(value in sent for value in ("18,675.50", "4,000", "6,000", "29,450", "sample@example.invalid", "Sample Person"))
    assert not contains_price(sent)
    assert asdict(original) == before


def test_mixed_single_line_and_table_cells_do_not_drop_unpriced_work_or_leak_bare_amount():
    from app.monthly_report_content_policy import technical_source_text
    text = ("Quote amount: $1,700; " + TECH + "\n"
            "Scope\tQuote Amount\tStatus\n"
            "Inspected V-TEST-2 at 46 psi.\t18675\tPending\n"
            "Quote total\n12500\n" + SECOND)
    safe = technical_source_text(text)
    assert TECH in safe and "Inspected V-TEST-2 at 46 psi." in safe
    assert "Pending" in safe and SECOND in safe
    assert all(token not in safe for token in ("$1,700", "18675", "12500", "Quote total"))
    assert not contains_price(safe)


@pytest.mark.parametrize("value", (None, 12, [], {}))
def test_malformed_technical_text_is_rejected_without_guessing(value):
    from app.monthly_report_content_policy import technical_source_text
    with pytest.raises((TypeError, ValueError)):
        technical_source_text(value)


def test_price_only_or_raster_without_readable_text_cannot_fabricate_activity():
    from app.monthly_report_content_policy import technical_source_text
    assert not technical_source_text(PRICE + "\n" + RANGE + "\n" + FOOTER)
    assert not technical_source_text("")
    blank = source("")
    with pytest.raises(ValueError, match="No readable text"):
        ai.extraction_request(blank, (1,))



def test_prompt_hints_and_legacy_facts_cannot_reintroduce_private_costs():
    from dataclasses import replace
    from app.monthly_report_model import EvidenceFact, ReportPeriod

    original = source(TECH, ".docx")
    good = EvidenceFact("good", original.id, 1, "action", TECH, TECH)
    bad = EvidenceFact("bad", original.id, 1, "action", TECH,
                       "Quote amount: $18,675.50")
    saved = replace(original, facts=(bad, good))
    key, parts, facts = ai.drafting_request(
        "activity_summary", (saved,), ReportPeriod(2026, 11),
        vendors=("Synthetic Mechanical", "contact@example.invalid"),
        tags=("P-TEST-42", "Price $88"))
    assert key and facts == (good,)
    payload = json.loads(parts[0]["text"].rsplit("\n", 1)[1])
    assert payload["vendors"] == ["Synthetic Mechanical"]
    assert payload["known_tags"] == ["P-TEST-42"]
    assert "18,675.50" not in parts[0]["text"]
    assert "contact@example.invalid" not in parts[0]["text"]
    with pytest.raises(ValueError, match="pricing and private contacts"):
        ai.drafting_request("activity_summary", (saved,), ReportPeriod(2026, 11),
                            instruction="Include invoice total $1,700")


def test_optional_activity_notes_keep_work_but_drop_bounded_price_and_contact_spans():
    from app.monthly_report_activity_notes_draft import draft_request

    request, notices, safe = draft_request(
        "Invoice amount: $1,700; " + TECH + "\n"
        + "Contact: Sample Person; " + SECOND)
    assert request and notices
    assert TECH in safe and SECOND in safe
    assert "1,700" not in safe and "Sample Person" not in safe
    assert not contains_price(request[0]["text"])


def test_readable_source_page_cannot_authorize_unchanged_priced_graphics():
    from app.monthly_report_content_policy import page_allowed, page_fingerprint
    from dataclasses import replace

    original = source(PRICE + "\n" + TECH)
    selected = replace(original, selected_pages=(1,),
                       client_page_reviews=((1, page_fingerprint(original, 1)),))
    assert not page_allowed(selected, 1)


def test_actual_saved_word_and_pdf_contain_technical_siblings_only(monkeypatch, tmp_path):
    """Renderer/persisted synthetic report, not a served or authentic-source pass."""
    from dataclasses import replace
    from hashlib import sha256
    from io import BytesIO
    from pathlib import Path
    from zipfile import ZipFile
    import os

    import pymupdf as fitz
    from docx import Document

    from app import monthly_report_library as library
    from app import monthly_report_sources as sources
    from app.monthly_report_checks import preflight
    from app.monthly_report_docx import generate_report
    from app.monthly_report_model import (
        ReportDraft, ReportPeriod, default_sections, synthetic_profiles,
    )
    from app.monthly_report_source_details import correct_source_details
    # The actual export is gated by the repository's renderer availability.
    if not os.environ.get('CI') and not __import__('shutil').which('libreoffice'):
        pytest.skip('LibreOffice not installed in this environment')

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((48, 80), "\n".join((PRICE, TECH, RANGE, SECOND, FOOTER, CONTACT)),
                         fontsize=10)
        raw = pdf.tobytes()
    content, attachments = sources.ingest(profile, "synthetic-a57-vendor.pdf", raw)
    assert not attachments
    bound = replace(content, source=correct_source_details(
        content.source, profile, None, profile.facilities[0].key))
    block = structured.native_update((bound,), "activity_summary")
    assert TECH in block.text and SECOND in block.text and not contains_price(block.text)
    sections = tuple(replace(s, included=s.key == "activity") for s in default_sections())
    draft = ReportDraft(profile, ReportPeriod(2026, 11), "Synthetic reviewer",
                        sections, (block,), sources=(bound.source,))
    stored = library.save_snapshot(draft, expected_revision=0,
                                   entered_editor=draft.prepared_by)
    recovered = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert recovered.revision == stored.revision and recovered.draft == draft
    assert sources.source_bytes(profile, bound.source) == raw
    assert sha256(raw).hexdigest() == bound.source.sha256
    assert not [check for check in preflight(recovered.draft) if check.blocking]
    package = generate_report(recovered.draft, acknowledged_fingerprint=recovered.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    with ZipFile(BytesIO(package.docx)) as archive:
        package_xml = "\n".join(archive.read(name).decode("utf-8")
                                for name in archive.namelist() if name.endswith(".xml"))
    document = Document(BytesIO(package.docx))
    word_text = "\n".join(p.text for p in document.paragraphs)
    with fitz.open(stream=package.pdf, filetype="pdf") as exported:
        pdf_text = "\n".join(page.get_text() for page in exported)
        pages = len(exported)
    # OOXML can split one visible sentence across <w:t> nodes; validate its
    # rendered text separately, but search every XML part for priced canaries.
    for text in (word_text, pdf_text):
        assert TECH in text and SECOND in text
    for text in (package_xml, word_text, pdf_text):
        assert not any(value in text for value in (
            "18,675.50", "4,000", "6,000", "29,450", "sample@example.invalid", "Sample Person"))
    output = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / "a57-price-safe-activity.json").write_text(json.dumps({
        "kind": "synthetic persisted Monthly DOCX/PDF",
        "revision": recovered.revision,
        "input_sha256": sha256(raw).hexdigest(),
        "docx_sha256": sha256(package.docx).hexdigest(),
        "pdf_sha256": sha256(package.pdf).hexdigest(),
        "pdf_pages": pages,
        "head": os.getenv("MSAPO_SHA", "local"),
    }, indent=2))
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == recovered



def _ocr_tsv(lines):
    """Tesseract TSV for whole synthetic lines, one word per row."""
    rows = ["\t".join(("level", "page_num", "block_num", "par_num", "line_num", "word_num",
                        "left", "top", "width", "height", "conf", "text"))]
    for line_number, line in enumerate(lines, 1):
        for word_number, word in enumerate(line.split(), 1):
            rows.append("\t".join(str(value) for value in (
                5, 1, 1, 1, line_number, word_number, 20 + 60 * word_number, 30 * line_number,
                50, 20, 92, word)))
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize("ocr", ["unavailable", "reads the page"])
def test_raster_only_proposal_canary_has_no_automatic_technical_or_image_route(
        monkeypatch, tmp_path, ocr):
    """Image pixels may have prices that text extractors cannot verify.

    Production installs local OCR (tesseract) and CI does not, so both are
    pinned here. Lines that OCR reads stay unverified review text: the price
    stays out and the technical line never becomes automatic Activity.
    """
    from hashlib import sha256
    import pymupdf as fitz

    from app import monthly_report_pdf_reader as reader
    from app import monthly_report_sources as sources
    from app.monthly_report_content_policy import page_allowed, suggested_pages
    from app.monthly_report_model import synthetic_profiles

    lines = ("SYNTHETIC PROPOSAL - quoted amount $75,900", "Inspected pump P-TEST-42 at 128 psi.")
    which = reader.shutil.which  # The shared module: answer only for tesseract.
    tesseract = None if ocr == "unavailable" else "/usr/bin/tesseract"
    monkeypatch.setattr(reader.shutil, "which",
                        lambda name, *a, **k: tesseract if name == "tesseract" else which(name, *a, **k))
    if ocr != "unavailable":
        monkeypatch.setattr(reader, "_ocr_image", lambda data, *, timeout: _ocr_tsv(lines))
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    with fitz.open() as drawing:
        page = drawing.new_page()
        page.insert_text((50, 70), "\n".join(lines), fontsize=11)
        image = page.get_pixmap().tobytes("png")
    with fitz.open() as scanned:
        page = scanned.new_page()
        page.insert_image(page.rect, stream=image)
        raw = scanned.tobytes()
    content, attachments = sources.ingest(profile, "synthetic-raster-priced-proposal.pdf", raw)
    assert not attachments
    if ocr == "unavailable":
        assert content.source.page_texts and all(not p.strip() for p in content.source.page_texts)
    else:
        # OCR text is kept for the reviewer, with each line's exact range.
        assert list(content.source.page_texts) == ["\n".join(lines)]
        assert [(span[0], content.source.page_texts[0][span[1]:span[2]])
                for span in content.ocr_spans] == [(1, line) for line in lines]
    assert 1 in content.source.needs_vision
    assert not suggested_pages(content.source)
    assert not page_allowed(content.source, 1)
    block = structured.native_update((content,), "activity_summary")
    assert not block.text
    assert sources.source_bytes(profile, content.source) == raw
    assert sha256(raw).hexdigest() == content.source.sha256



def test_opaque_total_and_sensitive_fact_status_never_reach_public_reader():
    from dataclasses import replace
    from app.monthly_report_content_policy import technical_source_text
    from app.monthly_report_model import EvidenceFact, ReportPeriod

    safe = technical_source_text("Total 4600\n" + TECH + "\nTotal 2 pumps")
    assert TECH in safe and "4600" not in safe and "Total 2 pumps" in safe
    src = source(TECH)
    clean = EvidenceFact("clean", src.id, 1, "action", TECH, TECH)
    private = replace(clean, id="private", status="Invoice total $7,600")
    flags = replace(clean, id="flags", flags=("Contact: Synthetic Person",))
    retained = replace(src, facts=(clean, private, flags))
    _, output, facts = ai.drafting_request(
        "activity_summary", (retained,), ReportPeriod(2026, 11))
    assert facts == (clean,)
    # The clean fact legitimately serializes an empty "flags" schema key;
    # prove that the unsafe fact ID and its sensitive flag were excluded.
    outgoing = json.loads(output[0]["text"].rsplit("\n", 1)[-1])
    assert [fact["id"] for fact in outgoing["facts"]] == ["clean"]
    assert "$7,600" not in output[0]["text"]



def test_optional_section_reader_has_no_raw_price_text_or_unreviewed_raster(
        monkeypatch, tmp_path):
    from app import monthly_report_sources as sources
    from app.monthly_report_model import synthetic_profiles

    original = source(PRICE + "\n" + TECH + "\n" + CONTACT, ".pdf")
    content = SourceContent(original, ())
    def forbidden(*args, **kwargs):
        pytest.fail("Unreviewed source-page raster must never be transmitted.")
    monkeypatch.setattr(sources, "page_image", forbidden)
    payload = structured.reader_request(synthetic_profiles()[0],
                                        (content,), "activity_summary")
    outbound = "\n".join(part.get("text", "") for part in payload)
    assert TECH in outbound
    assert PRICE not in outbound and CONTACT not in outbound
    assert not any(part.get("type") == "image" for part in payload)
    assert all("18,675.50" not in str(part) for part in payload)
    # Price-only source: no model call with an empty/financial payload.
    priced_only = SourceContent(source(PRICE, ".pdf"), ())
    with pytest.raises(ValueError, match="No policy-permitted"):
        structured.reader_request(synthetic_profiles()[0],
                                  (priced_only,), "proposals")


def test_raster_only_reader_requires_local_review_before_model_transmission(
        monkeypatch, tmp_path):
    from dataclasses import replace
    from app import monthly_report_sources as sources
    from app.monthly_report_model import synthetic_profiles

    original = replace(source("", ".pdf"), needs_vision=(1,))
    content = SourceContent(original, ())
    monkeypatch.setattr(sources, "image_numbers", lambda *_: (1,))
    monkeypatch.setattr(sources, "page_image", lambda *_:
                        pytest.fail("Unreviewed raster bytes must not be read for AI."))
    with pytest.raises(ValueError, match="No policy-permitted"):
        structured.reader_request(synthetic_profiles()[0],
                                  (content,), "activity_summary")



def test_preflight_does_not_delete_human_work_but_blocks_private_technical_contact():
    from app.monthly_report_checks import preflight
    from app.monthly_report_model import (
        ReportDraft, ReportPeriod, ResolvedBlock, default_sections,
        synthetic_profiles,
    )
    from dataclasses import replace

    original = ResolvedBlock("activity_summary", "This month",
                             text=TECH + "\nContact: Sample Person (202) 555-0176")
    sections = tuple(replace(s, included=s.key == "activity") for s in default_sections())
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 11),
                        "Synthetic preparer", sections, (original,))
    problems = preflight(draft)
    assert any(item.code == "private_contact" and item.blocking
               for item in problems)
    assert original.text.endswith("(202) 555-0176"), "Human edit retained for correction."
    corrected = replace(original, text=TECH)
    clean = replace(draft, blocks=(corrected,))
    assert not any(item.code == "private_contact" for item in preflight(clean))



def test_labeled_vendor_work_survives_separate_quote_but_status_ambiguity_holds():
    from dataclasses import replace

    original = source("Actions: " + TECH + "\n" + PRICE)
    classified = replace(original, classification="Vendor service")
    before = asdict(classified)
    result = structured.native_update((SourceContent(classified, ()),),
                                      "activity_summary")
    assert TECH in result.text and PRICE not in result.text
    assert result.references
    assert asdict(classified) == before
    # Removing the completion qualifier would turn a pending task into work.
    unsure = replace(classified,
                     page_texts=("Actions: " + TECH
                                 + "\nStatus: Pending approval"
                                 + "\n" + PRICE,))
    withheld = structured.native_update((SourceContent(unsure, ()),),
                                        "activity_summary")
    assert not withheld.text
