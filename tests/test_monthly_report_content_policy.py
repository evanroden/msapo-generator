

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
