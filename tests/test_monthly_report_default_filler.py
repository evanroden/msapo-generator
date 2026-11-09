"""Fresh generated reports never invent statuses; explicit retained text stays."""
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from app.monthly_report_guided import _initial_draft
from app.monthly_report_model import ReportPeriod, ResolvedBlock, STOCK_TEXTS, synthetic_profiles
from app.monthly_report_docx import _build_docx


def state(saved=None):
    return SimpleNamespace(profile=synthetic_profiles()[0], block=lambda key: (saved or {}).get(key))


def test_fresh_report_has_no_unsupported_stock_statuses():
    draft = _initial_draft(state(), ReportPeriod(2026, 10), 'Synthetic Editor')
    assert not any(b.source == 'Stock text' for b in draft.blocks)
    text = '\n'.join(p.text for p in Document(BytesIO(_build_docx(draft))).paragraphs)
    assert 'FacilityOne transition' not in text
    assert not any(text_value in text for text_value in STOCK_TEXTS.values())


@pytest.mark.parametrize('source', ['This month', 'Last month', 'Library', 'Stock text'])
def test_explicit_retained_text_is_never_rewritten_as_filler(source):
    saved = ResolvedBlock('work_orders', source, text=STOCK_TEXTS['cmms_pending'])
    draft = _initial_draft(state({'work_orders': saved}), ReportPeriod(2026, 10), 'Synthetic Editor')
    assert next(b for b in draft.blocks if b.key == saved.key) == saved
