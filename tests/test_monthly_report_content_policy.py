

def test_date_before_harmless_cost_narrative_is_not_a_price():
    from app.monthly_report_content_policy import contains_price
    text = ('Status reflects August 2026 coordination; no September 2026 update was received. '
            'Final scope and cost will be updated when vendor proposals are received.')
    assert not contains_price(text)
    assert contains_price('September 2026 cost: 1500')
    assert contains_price('1500 cost')
    assert contains_price('Cost\n1500')


def test_receivable_aging_buckets_do_not_reclassify_current_capacity():
    from app.monthly_report_content_policy import table_price_columns
    columns = ('Facility', 'Current', '31-60', 'Capacity')
    assert table_price_columns(columns, (('Unity', '500', '600', '700'),)) == ()
    columns = ('Invoice', 'Amount Due', 'Current', '31-60')
    assert table_price_columns(columns, (('INV-1', '500', '250', '250'),)) == (1, 2, 3)


def test_exact_canonical_merged_capital_header_recovers_four_columns_only():
    from app.monthly_report_content_policy import logical_table_columns, table_has_pricing
    from app.monthly_report_sections import table_without_prices
    from app.monthly_report_import import ImportItem
    heading = 'Equipment Description End of Useful Life Cost Summary of deficiency'
    item = ImportItem('capital', 'table', 'word/document.xml', 1, 1, 'capital', rows=(
        (heading, '', '', ''), ('Pump', '2030', '$500', 'Worn casing')))
    table, removed = table_without_prices(item)
    assert removed == (2,)
    assert table.columns == ('Equipment Description', 'End of Useful Life', 'Summary of deficiency')
    assert table.rows == (('Pump', '2030', 'Worn casing'),)
    assert not table_has_pricing(table.columns, table.rows)
    assert logical_table_columns((heading, 'Vendor', '', '')) == (heading, 'Vendor', '', '')
    assert logical_table_columns((heading, '', '')) == (heading, '', '')


def test_exact_five_column_capital_header_recovers_wrapped_life_and_submission_date():
    from app.monthly_report_content_policy import logical_table_columns, table_has_pricing
    from app.monthly_report_sections import table_without_prices
    from app.monthly_report_import import ImportItem
    heading = 'Equipment Description End of Useful Cost Summary of deficiency Date\nLife Sub.'
    item = ImportItem('capital', 'table', 'word/document.xml', 1, 1152, 'capital', rows=(
        (heading, '', '', '', ''), ('Pump', '2030', '$500', 'Worn casing', '9/15/2026')))
    table, removed = table_without_prices(item)
    assert removed == (2,)
    assert table.columns == ('Equipment Description', 'End of Useful Life', 'Summary of deficiency', 'Date Sub.')
    assert table.rows == (('Pump', '2030', 'Worn casing', '9/15/2026'),)
    assert not table_has_pricing(table.columns, table.rows)
    assert logical_table_columns((heading, 'Vendor', '', '', '')) == (heading, 'Vendor', '', '', '')
    assert logical_table_columns((heading, '', '', '')) == (heading, '', '', '')
    assert logical_table_columns((heading.replace('Date', 'Price'), '', '', '', '')) == (heading.replace('Date', 'Price'), '', '', '', '')
    assert table_has_pricing(table.columns, (('Pump', '2030', 'Estimated savings $600', '9/15/2026'),))
