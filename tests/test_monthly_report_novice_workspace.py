from dataclasses import replace

from app.monthly_report_guided import activity_from_sources, client_table_draft, MONTHLY_EDIT_KEYS
from app.monthly_report_model import (ColumnSpec, ReportSource, ResolvedBlock,
                                     ReportPeriod, synthetic_draft, synthetic_profiles, default_sections)
from app.monthly_report_setup import MONTHLY_BLOCKS
from test_monthly_report_ui import monthly, step


def test_empty_work_has_no_unusable_source_confirmation(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    step(app, 2)
    assert not any('_actions_ok_' in (w.key or '') for w in app.checkbox)
    assert not any(b.label == 'Add reviewed work to the activity summary' for b in app.button)


def test_readable_monthly_locations_do_not_change_rollover_policy():
    assert {'capital_renewal', 'proposals', 'equipment_issues', 'rfi_matrix'} <= MONTHLY_EDIT_KEYS
    assert not {'capital_renewal', 'proposals', 'equipment_issues', 'rfi_matrix'} & MONTHLY_BLOCKS


def test_legacy_price_columns_removed_from_copy_not_saved_history():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    sections = tuple(replace(s, blocks=tuple(replace(b, columns=(ColumnSpec('scope','Scope'), ColumnSpec('amount','Amount','currency'), ColumnSpec('status','Status'))) if b.key == 'proposals' else b for b in s.blocks)) for s in default_sections())
    draft = replace(draft, sections=sections, blocks=tuple(b for b in draft.blocks if b.key != 'proposals') + (ResolvedBlock('proposals', 'Last month', rows=(('Pump renewal', '$100', 'Pending'),)),))
    updated, removed = client_table_draft(draft)
    assert removed == ('Amount',)
    assert next(b for b in updated.blocks if b.key == 'proposals').rows == (('Pump renewal', 'Pending'),)
    assert next(b for b in draft.blocks if b.key == 'proposals').rows[0][1] == '$100'
    assert client_table_draft(updated) == (updated, ())


def test_actions_use_actual_page_and_preserve_colleague_work():
    source = ReportSource('a'*64, 'synthetic.pdf', 'a'*64, '.pdf', 'Vendor service', vendor='Synthetic Vendor',
                          actions='Inspected pump.\nReplaced pump for $100.',
                          page_texts=('Replaced pump for $100.', 'Inspected pump.'), selected_pages=(2,))
    original = ResolvedBlock('activity_summary', 'This month', text='Colleague checked the valve.')
    result = activity_from_sources((source,), original)
    assert original.text in result.text and 'Inspected pump.' in result.text
    assert '$100' not in result.text and len(result.references) == 1
    assert activity_from_sources((source,), result) == result


def test_general_template_sections_have_one_editing_home(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == 'Site name').set_value('Synthetic Cedar').run()
    next(b for b in app.button if b.label == 'Use ENFRA template').click().run()
    next(w for w in app.text_input if w.label == 'Your name').set_value('Synthetic Editor').run()
    next(w for w in app.checkbox if w.label == 'Save this design for these sites so we can use it next month').check().run()
    next(b for b in app.button if b.label == 'Start this report').click().run()
    step(app, 2)
    chooser = next(w for w in app.selectbox if w.label == 'Section to update')
    assert {'Equipment Performance Issues', 'Priority Capital Renewal List', 'Pending & Declined Proposals'} <= set(chooser.options)
    chooser.set_value('issues').run()
    assert any(w.label == 'Equipment issues' for w in app.text_area)
    assert not any(w.label == 'Utility analysis' for w in app.text_area)
    next(w for w in app.selectbox if w.label == 'Section to update').set_value('scorecards').run()
    assert any(w.label == 'Utility analysis' for w in app.text_area)
    step(app, 3)
    chooser = next(w for w in app.selectbox if w.label == 'Site information to update')
    assert {'Organizational Chart', 'Sub-Contractor Status'} <= set(chooser.options)
    assert any(b.label == 'Change team chart' for b in app.button)
    assert not any(w.label in ('Equipment issues', 'Utility analysis') for w in app.text_area)
    assert not any(w.label.startswith('Change the ') for w in app.checkbox)
    assert not any(w.label in ('Pictures/pages to keep', 'Picture/page to view') for w in (*app.selectbox, *app.multiselect))


def test_commissioning_update_is_editable_in_its_own_section_and_survives_next_month(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.contracts import RRH_CONTRACT
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == 'Prepared by').set_value('Synthetic Editor').run()
    next(w for w in app.checkbox if w.label == 'Include Monthly Activity Summary').uncheck().run()
    next(w for w in app.checkbox if w.label == 'Include MBCx Reports').check().run()
    step(app, 2)
    update = next(w for w in app.text_area if w.label == 'Update to include in the report')
    assert update.value == ''
    next(b for b in app.button if b.label == 'Reporting has not started').click().run()
    update = next(w for w in app.text_area if w.label == 'Update to include in the report')
    assert 'has not started' in update.value
    update.set_value('Synthetic equipment monitoring is awaiting activation.').run()
    next(b for b in app.button if b.label == 'Save progress').click().run()
    saved = library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026, 9))
    assert next(b for b in saved.draft.blocks if b.key == 'mbcx_status').text == 'Synthetic equipment monitoring is awaiting activation.'
    app.selectbox('report_month_number').set_value(10).run()
    step(app, 2)
    assert next(w for w in app.text_area if w.label == 'Update to include in the report').value == 'Synthetic equipment monitoring is awaiting activation.'
