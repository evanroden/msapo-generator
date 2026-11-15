"""Native controls for reviewing Maintenance from the existing source."""
import streamlit as st

from app.monthly_report_model import ResolvedBlock
from app.monthly_report_maintenance_workflow import preview
from app.monthly_report_non_pm_maintenance import FIELD_HEADERS, _norm


def _recorded_performer(row):
    positions = [n for n, name in enumerate(row.original.columns)
                 if _norm(name) in FIELD_HEADERS['performer']]
    return row.original.cells[positions[0]] if len(positions) == 1 else ''


def render(draft, blocks, bundle, index, local, base, request_key, queue):
    with st.expander('Use these work orders for Maintenance'):
        st.caption('This uses the same saved file. Completed non-PM work by ENFRA goes to Maintenance; vendor or leased work goes to Activity. Identify the performer before including rows.')
        state = bundle.get('maintenance_projection') or {}
        if not st.checkbox('Review this file for Maintenance', value=bool(state), key=local + '_maintenance_start'):
            return
        if state.get('publication'):
            with st.form(local + '_maintenance_remove'):
                manual_key = local + '_maintenance_keep_manual'
                confirm_key = local + '_maintenance_remove_confirm'
                st.checkbox('Keep the current Maintenance and vendor rows as manual entries', key=manual_key,
                    help='Leave unchecked to remove the exact rows previously added from this source. Edited rows are never overwritten.')
                st.checkbox('I confirm how to handle these included rows', key=confirm_key)
                expected = {key: blocks.get(key, ResolvedBlock(key, 'This month')).fingerprint
                            for key in ('work_orders', 'service_calls')}
                st.form_submit_button('Remove the Maintenance source link', on_click=queue,
                    args=(request_key, {**base, 'action': 'maintenance_remove', 'group': index, 'blocks': expected},
                          (('keep_manual', manual_key), ('confirmed', confirm_key))))
        try:
            projection = preview(draft, bundle, index)
        except ValueError as exc:
            st.info(str(exc))
            return
        candidates = tuple(row for row in projection.candidates if row.disposition != 'not_eligible')
        if not candidates:
            st.caption('No completed non-PM candidates for this reporting month were found.')
            return
        st.dataframe([{'Source row': row.original.row_number, 'Work order': row.work_order,
            'Site': row.site, 'Completion date': row.completed_date,
            'Recorded performer': _recorded_performer(row), 'Performer decision': row.performer or 'Unclassified',
            'Work performed': row.task, 'Area': row.area, 'Equipment tag': row.tag,
            'Destination': row.disposition.replace('_', ' '), 'Review needed': '; '.join(row.reasons)}
            for row in candidates], hide_index=True)
        if projection.needs_review:
            st.info(f'{len(projection.needs_review)} candidate(s) need a decision before inclusion.')
        selected = st.selectbox('Maintenance row to review', range(len(candidates)),
            format_func=lambda n: f'Source row {candidates[n].original.row_number} · {candidates[n].work_order}',
            key=local + '_maintenance_row')
        row = candidates[selected]
        with st.form(local + '_maintenance_correct_' + row.key):
            fields = []
            for name, label, value in (('area', 'Maintenance area', row.area),
                                       ('task', 'Maintenance work performed', row.task),
                                       ('tag', 'Maintenance equipment tag', row.tag)):
                widget = local + '_maintenance_' + row.key + '_' + name
                st.text_input(label, value=value, key=widget)
                fields.append((name, widget))
            widget = local + '_maintenance_' + row.key + '_performer'
            choices = ('Unknown', 'ENFRA onsite', 'Vendor/leased')
            st.selectbox('Who performed this work?', choices,
                index=choices.index(row.performer if row.performer in choices else 'Unknown'), key=widget)
            fields.append(('performer', widget))
            st.form_submit_button('Save Maintenance row decision', on_click=queue,
                args=(request_key, {**base, 'action': 'maintenance_correct', 'group': index, 'row': row.key}, fields))
        with st.form(local + '_maintenance_classify'):
            sites = tuple(site.key for site in draft.profile.facilities)
            site_key = local + '_maintenance_bulk_site'
            st.selectbox('Site for unclassified performers', sites, key=site_key,
                format_func=lambda key: next((site.title for site in draft.profile.facilities if site.key == key), key))
            performer_key = local + '_maintenance_bulk_performer'
            st.selectbox('Verified performer for unclassified rows at this site',
                ('Choose', 'ENFRA onsite', 'Vendor/leased'), key=performer_key)
            confirm_key = local + '_maintenance_bulk_confirm'
            st.checkbox('I verified this performer for every unclassified candidate at the selected site', key=confirm_key)
            st.form_submit_button('Classify unclassified performers', on_click=queue,
                args=(request_key, {**base, 'action': 'maintenance_classify', 'group': index},
                      (('site', site_key), ('performer', performer_key), ('confirmed', confirm_key))))
        if projection.onsite_table:
            st.caption(f'{len(projection.onsite_table.rows)} onsite row(s) will be added to Maintenance.')
        if projection.vendor_activity_table:
            st.caption(f'{len(projection.vendor_activity_table.rows)} vendor/leased row(s) will be added to Activity.')
        with st.form(local + '_maintenance_publish'):
            confirm_key = local + '_maintenance_publish_confirm'
            st.checkbox('I reviewed the completed non-PM rows and their destinations', key=confirm_key)
            expected = {key: blocks.get(key, ResolvedBlock(key, 'This month')).fingerprint
                        for key in ('work_orders', 'service_calls')}
            st.form_submit_button('Include reviewed Maintenance and vendor work',
                disabled=bool(projection.needs_review), on_click=queue,
                args=(request_key, {**base, 'action': 'maintenance_publish', 'group': index, 'blocks': expected},
                      (('confirmed', confirm_key),)))
