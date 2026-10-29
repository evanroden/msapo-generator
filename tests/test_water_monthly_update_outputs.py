"""Actual synthetic Water exports; schema order alone is not output proof."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from app.monthly_report_docx import assemble_docx, generate_report
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from tests.conftest import requires_libreoffice

UPDATE = 'Synthetic September water update.'
CAPTION = 'Synthetic vendor water page.'


def water_case(update, pages, legacy=False):
    water = next(s for s in default_sections() if s.key == 'water')
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((30, 60), 'SYNTHETIC WATER VENDOR PAGE')
    raw = page.get_pixmap().tobytes('png')
    document.close()
    blocks = (
        ResolvedBlock('water_monthly_update', 'This month', text=UPDATE if update else ''),
        ResolvedBlock('water_reports', 'This month', asset_hashes=('synthetic-water.png',) if pages else (),
                      asset_captions=(CAPTION,) if pages else ()),
    )
    # Explicitly approve this known synthetic page through the existing per-asset contract.
    if pages:
        from app.monthly_report_asset_review import asset_fingerprint
        blocks = (blocks[0], replace(blocks[1], client_asset_reviews=(asset_fingerprint(blocks[1], 0),)))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor', (water,), blocks)
    if legacy:
        from app.monthly_report_guided import complete_guided_sections
        older = replace(draft, sections=(replace(water, blocks=water.blocks[1:]),))
        completed = complete_guided_sections(older)
        draft = replace(completed, sections=tuple(s for s in completed.sections if s.key == "water"))
    return draft, lambda _: raw


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('update,pages', [(True,False),(False,True),(True,True),(False,False)])
def test_water_word_update_exactly_once_before_vendor_pages(update, pages, legacy):
    draft, loader = water_case(update, pages, legacy)
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    word = Document(BytesIO(raw))
    text = '\n'.join(p.text for p in word.paragraphs)
    assert text.count(UPDATE) == int(update)
    assert text.count(CAPTION) == int(pages)
    assert len(word.inline_shapes) == int(pages)
    if update and pages:
        assert text.index(UPDATE) < text.index(CAPTION)


@requires_libreoffice
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('update,pages', [(True,False),(False,True),(True,True),(False,False)])
def test_water_actual_pdf_output_and_empty_update_has_no_extra_page(update, pages, legacy, tmp_path):
    draft, loader = water_case(update, pages, legacy)
    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    assert package.pdf, package.pdf_error
    (tmp_path / 'water.docx').write_bytes(package.docx)
    (tmp_path / 'water.pdf').write_bytes(package.pdf)
    with pymupdf.open(stream=package.pdf, filetype='pdf') as pdf:
        text = '\n'.join(p.get_text() for p in pdf)
        assert text.count(UPDATE) == int(update)
        assert text.count(CAPTION) == int(pages)
        if update and pages:
            assert text.index(UPDATE) < text.index(CAPTION)
        count = len(pdf)
    # Compare against the same existing Water section without the optional slot.
    if not update:
        baseline = replace(draft, sections=(replace(draft.sections[0], blocks=draft.sections[0].blocks[1:]),), blocks=draft.blocks[1:])
        previous = generate_report(baseline, acknowledged_fingerprint=baseline.fingerprint, asset_loader=loader)
        assert previous.pdf, previous.pdf_error
        with pymupdf.open(stream=previous.pdf, filetype='pdf') as pdf:
            assert len(pdf) == count
