"""First-paint completed-session summary cannot hydrate under a later press."""
from app.monthly_report_training_ui import _session_hours
from test_monthly_report_training_retention import training, current
from app.monthly_report_training import EVENT_REF


def test_completed_summary_has_no_lazy_native_table(training):
    app, *_ = training
    assert not app.exception
    assert len(app.table) == 0, 'Native Table is lazy and moves later row actions during first hydration'
    summaries = [e.value for e in app.markdown if 'data-enfra-training-summary' in e.value]
    assert len(summaries) == 1
    assert 'Accepted safety event' in summaries[0]
    assert 'Synthetic Hospital Tech' in summaries[0]
    assert '0.75 hours' in summaries[0]
    assert len(next(t for t in current(app).extra_tables if t.reference == EVENT_REF).rows) == 1


def test_summary_escapes_source_and_preserves_long_values():
    from app.monthly_report_training_ui import _session_summary_html
    row = ('<img src=x onerror=alert(1)> & safety ' * 12, '2026-09-01', 'In person', 'A & B <staff>', '')
    result = _session_summary_html((row,))
    assert '<img' not in result and '&lt;img' in result
    assert 'A &amp; B &lt;staff&gt;' in result
    assert 'Unknown' in result
    assert result.count('<tbody>') == 1 and result.count('<td>') == 5
    assert 'overflow-x:auto' in result
    assert '[data-enfra-training-summary]::-webkit-scrollbar{height:6px;width:6px}' in result
    assert '[data-enfra-training-summary]{height:' not in result and 'ellipsis' not in result
