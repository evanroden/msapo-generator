import pytest

from app.monthly_report_model import ReportSource, ResolvedBlock
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_structured_uploads import mapped_rows, native_update, reader_update, useful_activity


def content(text='', *, suffix='.pdf', tables=(), vision=()):
    return SourceContent(ReportSource('a' * 64, 'source' + suffix, 'a' * 64, suffix,
                                     page_texts=(text,), needs_vision=vision), tables)


@pytest.mark.parametrize('text', ['', 'ENFRA Monthly Report September 2026',
                                 'Signed by: Michael Smith',
                                 'Terms and conditions. Limitation of liability. Governing law.',
                                 'Replaced motor. Total cost $1234'])
def test_activity_omits_boilerplate_and_prices(text):
    assert not useful_activity(text)


def test_activity_preserves_qualifiers_and_human_edits():
    source = content('Inspection findings: motor was not replaced.\nReplacement is scheduled for October.')
    block = native_update((source,), 'activity_summary', ResolvedBlock('activity_summary', 'This month', text='AM notes'))
    assert block.text == 'AM notes\n\nInspection findings: motor was not replaced.\n\nReplacement is scheduled for October.'
    assert len(block.references) == 1


@pytest.mark.parametrize('suffix', ['.xlsx', '.csv', '.docx', '.pdf'])
def test_capital_native_tables_omit_prices(suffix):
    table = SourceTable('Renewals', ('Site', 'Rank', 'Description', 'Cost'), (('Unity', '1', 'Replace boiler', '25000'),))
    source = content('Site\tRank\tDescription\tCost\nUnity\t1\tReplace boiler\t25000', suffix=suffix,
                     tables=(table,) if suffix in {'.xlsx', '.csv'} else ())
    assert mapped_rows(source, 'capital_renewal') == (('Unity', '1', 'Replace boiler'),)


def test_quotes_never_copy_prices_or_infer_pending_status():
    table = SourceTable('Quotes', ('Company', 'Scope', 'Price'), (('Vendor A', 'Replace pump', '3000'), ('Vendor B', 'Repair for $200', '200')))
    block = native_update((content(tables=(table,)),), 'proposals')
    assert block.rows == (('', 'Vendor A', 'Replace pump', ''),)
    assert not block.asset_hashes


@pytest.mark.parametrize('suffix', ['.pdf', '.docx', '.png'])
def test_reader_scans_accept_values_but_never_quote_images(suffix):
    source = content(suffix=suffix, vision=(1,))
    result, pages = reader_update((source,), 'proposals', {'visual_pages': [[source.source.id, 1]], 'items': [
        {'source': source.source.id, 'page': 1, 'row': ['Unity', 'Vendor', 'Repair pump', 'Pending'], 'include_page': True},
        {'source': source.source.id, 'page': 1, 'row': ['Unity', 'Vendor', 'Repair $100', 'Pending']}]})
    assert result.rows == (('Unity', 'Vendor', 'Repair pump', 'Pending'),)
    assert not pages and not result.asset_hashes


def test_reader_rejects_invented_page_and_native_claim():
    source = content('Inspected pump. Replacement pending.')
    item = {'source': source.source.id, 'page': 1, 'text': 'Replaced pump.', 'row': []}
    with pytest.raises(ValueError, match='not present'):
        reader_update((source,), 'activity_summary', {'items': [item]})
    with pytest.raises(ValueError, match='unknown page'):
        reader_update((source,), 'activity_summary', {'items': [dict(item, page=2)]})


def test_activity_reader_cannot_include_native_priced_page():
    source = content('Inspection completed.\nPrice $400.')
    result, pages = reader_update((source,), 'activity_summary', {'items': [
        {'source': source.source.id, 'page': 1, 'text': 'Inspection completed.', 'row': [], 'include_page': True}]})
    assert result.text == 'Inspection completed.'
    assert not pages


def test_repeat_import_does_not_duplicate_rows_or_text():
    source = content('Inspected motor.')
    first = native_update((source,), 'activity_summary')
    assert native_update((source,), 'activity_summary', first).text == first.text


def test_mixed_price_scope_column_is_not_silently_imported():
    source = content(tables=(SourceTable('Quote', ('Vendor', 'Scope / Cost'), (('V', '5000'),)),))
    assert mapped_rows(source, 'proposals') == ()


def test_repeat_multiple_paragraphs_stays_idempotent():
    source = content('Inspected pump.\nRepaired valve.')
    first = native_update((source,), 'activity_summary')
    assert native_update((source,), 'activity_summary', first).text == first.text


def test_reader_cannot_invent_unread_scanned_values():
    source = content(suffix='.png', vision=(1,))
    block, pages = reader_update((source,), 'proposals', {'items': [
        {'source': source.source.id, 'page': 1, 'row': ['Unity', 'Vendor', 'Repair', 'Pending']}]})
    assert not block.rows and not pages


def test_reader_chunks_large_report_without_changing_page_identity(monkeypatch):
    from dataclasses import replace
    from app import monthly_report_structured_uploads as uploads
    source = content('Inspected motor.')
    source = replace(source, source=replace(source.source, page_texts=('Inspected motor.',) * 45))
    monkeypatch.setattr(uploads, 'reader_request', lambda profile, contents, destination, refs: refs)
    chunks = uploads.reader_batches(None, (source,), 'activity_summary')
    assert list(map(len, chunks)) == [20, 20, 5]
    assert [page for chunk in chunks for _, page in chunk] == list(range(1, 46))


@pytest.mark.parametrize('text', ['Installed a replacement motor.', 'Calibrated the meter.', 'Restarted the controller.', 'Fixed the valve.', 'The bearing remained under observation this month.', 'Flow: 450 gpm'])
def test_meaningful_activity_is_not_limited_to_completed_repair_verbs(text):
    assert useful_activity(text)


def test_bulk_visual_budget_is_explicit_bounded_and_content_addressed(monkeypatch, tmp_path):
    from app import monthly_report_structured_uploads as uploads
    from app.monthly_report_model import synthetic_profiles
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(uploads, 'MAX_BULK_SOURCE_IMAGES', 2)
    profile = synthetic_profiles()[0]
    uploads.reserve_bulk_image(profile, 'a' * 64, b'page one')
    uploads.reserve_bulk_image(profile, 'a' * 64, b'page one')
    uploads.reserve_bulk_image(profile, 'a' * 64, b'page two')
    with pytest.raises(ValueError, match='allowance'):
        uploads.reserve_bulk_image(profile, 'a' * 64, b'page three')
