"""Review and publish Maintenance from an existing work-order source."""
from dataclasses import asdict, replace
import json

from app.monthly_report_model import ReportTable, ResolvedBlock, used_block_keys
from app.monthly_report_non_pm_maintenance import project_completed_non_pm


def _table(value):
    if (not isinstance(value, dict) or not isinstance(value.get('reference'), str)
            or not isinstance(value.get('columns'), list) or not 1 <= len(value['columns']) <= 32
            or any(not isinstance(v, str) for v in value['columns'])
            or not isinstance(value.get('rows'), list) or len(value['rows']) > 20_000
            or any(not isinstance(row, list) or len(row) != len(value['columns'])
                   or any(not isinstance(v, str) for v in row) for row in value['rows'])):
        raise ValueError('Invalid saved Maintenance publication.')
    return ReportTable(tuple(value['columns']), tuple(tuple(row) for row in value['rows']), value['reference'])


def validate_state(state):
    if (not isinstance(state, dict) or type(state.get('schema')) is not int or state['schema'] != 1
            or type(state.get('group_index')) is not int or state['group_index'] < 0
            or not isinstance(state.get('corrections'), dict) or len(state['corrections']) > 20_000):
        raise ValueError('Invalid saved Maintenance review.')
    for key, changes in state['corrections'].items():
        if (not isinstance(key, str) or not key or not isinstance(changes, dict)
                or any(name not in ('area', 'task', 'tag', 'performer')
                       or not isinstance(value, str) or len(value) > 4000
                       for name, value in changes.items())):
            raise ValueError('Invalid saved Maintenance correction.')
    publication = state.get('publication')
    if publication is None:
        return ()
    if (not isinstance(publication, dict)
            or any(not isinstance(publication.get(key), str) or not publication[key]
                   for key in ('review_revision', 'corrections_revision'))
            or not isinstance(publication.get('tables'), list)
            or not 1 <= len(publication['tables']) <= 2):
        raise ValueError('Invalid saved Maintenance publication.')
    tables = []
    for entry in publication['tables']:
        if not isinstance(entry, dict) or entry.get('destination') not in ('work_orders', 'service_calls'):
            raise ValueError('Invalid saved Maintenance publication.')
        tables.append((entry['destination'], _table(entry.get('table'))))
    if len({key for key, _ in tables}) != len(tables):
        raise ValueError('Repeated Maintenance publication destination.')
    return tuple(tables)


def _state(bundle, index):
    state = bundle.get('maintenance_projection') or {
        'schema': 1, 'group_index': index, 'corrections': {}, 'publication': None}
    validate_state(state)
    if state['group_index'] != index:
        raise ValueError('This source already has a Maintenance review for another table. Keep that review before choosing a different table.')
    return json.loads(json.dumps(state, ensure_ascii=False))


def preview(draft, bundle, index, *, state=None):
    from app import monthly_report_work_order_review_flow as flow
    flow._validate(draft, bundle)
    if (bundle['kind'] != 'workorders' or type(index) is not int
            or not 0 <= index < len(bundle['groups'])):
        raise ValueError('Choose a reviewed work-order source table.')
    group = bundle['groups'][index]
    if group['omitted'] or not group['record'] or group['notes'] or group['unmatched']:
        raise ValueError('Resolve the selected work-order source group first.')
    review = flow.restored_group(bundle, group)
    selected = _state(bundle, index) if state is None else state
    validate_state(selected)
    if selected['group_index'] != index:
        raise ValueError('The Maintenance review belongs to another source table.')
    return project_completed_non_pm(review, draft.profile, draft.period,
        expected_revision=review.revision, corrections=selected['corrections'])


def correct(draft, bundle, *, index, row_key, changes):
    from app import monthly_report_work_order_review_flow as flow
    state = _state(bundle, index)
    if not isinstance(row_key, str) or not isinstance(changes, dict):
        raise ValueError('Select a source row to review.')
    state['corrections'][row_key] = changes
    preview(draft, bundle, index, state=state)  # Verify row identity and decision values.
    value = flow.decoded(flow.encoded(bundle))
    value['maintenance_projection'] = state
    return value


def classify_unknown(draft, bundle, *, index, site, performer, confirmed):
    """One explicit site-scoped decision; never replace a recorded performer."""
    from app import monthly_report_work_order_review_flow as flow
    if (confirmed is not True or site not in {s.key for s in draft.profile.facilities}
            or performer not in ('ENFRA onsite', 'Vendor/leased')):
        raise ValueError('Confirm the site and performer category before applying it.')
    state = _state(bundle, index)
    projection = preview(draft, bundle, index, state=state)
    targets = [row for row in projection.needs_review if row.site == site and not row.performer
               and 'Performer is unknown; cannot attribute work to ENFRA.' in row.reasons]
    if not targets:
        raise ValueError('No eligible rows for this site need a performer decision.')
    for row in targets:
        changes = dict(state['corrections'].get(row.key, {}))
        changes['performer'] = performer
        state['corrections'][row.key] = changes
    preview(draft, bundle, index, state=state)
    value = flow.decoded(flow.encoded(bundle))
    value['maintenance_projection'] = state
    return value


def publish(draft, bundle, *, expected_revision, expected_blocks, index, confirmed):
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_row_review_receipts import decoded
    if confirmed is not True:
        raise ValueError('Confirm the reviewed completed non-PM work before inclusion.')
    state = _state(bundle, index)
    projection = preview(draft, bundle, index, state=state)
    if projection.needs_review:
        raise ValueError('Resolve every candidate needing review before including Maintenance or vendor Activity rows.')
    incoming = tuple((key, table) for key, table in (
        ('service_calls', projection.onsite_table), ('work_orders', projection.vendor_activity_table)) if table)
    if not incoming:
        raise ValueError('No completed non-PM work remains for this report month.')
    blocks = {block.key: block for block in draft.blocks}
    for key in ('service_calls', 'work_orders'):
        current = blocks.get(key, ResolvedBlock(key, 'This month'))
        if expected_blocks.get(key) != current.fingerprint:
            raise ValueError('A destination table changed. Reopen this review before adding work.')
    for key, _ in incoming:
        current = blocks.get(key, ResolvedBlock(key, 'This month'))
        if key not in used_block_keys(draft) or current.source == 'Omit':
            raise ValueError('Include the destination section before adding reviewed work.')
        blocks[key] = current
    active_ids = {(row.site, row.work_order.casefold()) for row in projection.candidates
                  if row.disposition in ('onsite', 'vendor_activity')}
    for raw in draft.source_row_reviews:
        other = decoded(raw)
        if other.get('scope') != bundle['scope']:
            continue
        other_projection = other.get('maintenance_projection') if other.get('kind') == 'workorders' else None
        is_other_projection = (other_projection and other_projection.get('publication')
                               and other.get('source_id') != bundle['source_id'])
        is_other_maintenance = other.get('kind') == 'maintenance' and other.get('published')
        if not is_other_projection and not is_other_maintenance:
            continue
        old_ids = set()
        for group in other['groups']:
            if group['record'] and not group['omitted']:
                old_review = flow.restored_group(other, group)
                old_ids.update((row.site, (row.work_order if is_other_projection else row.wo).casefold())
                               for row in old_review.rows if not row.excluded)
        if active_ids & old_ids:
            raise ValueError('Another included source already contains one of these work orders. Compare the sources before including duplicate work.')
    previous = validate_state(state)
    for key, table in previous:
        current = blocks.get(key, ResolvedBlock(key, 'This month'))
        if current.extra_tables.count(table) != 1:
            raise ValueError('Previously included Maintenance or vendor rows were edited or removed. Your changes are retained.')
        remaining = list(current.extra_tables)
        remaining.remove(table)
        blocks[key] = replace(current, extra_tables=tuple(remaining),
                              reviewed_fingerprint='', client_reviewed_fingerprint='')
    for key, table in incoming:
        current = blocks[key]
        blocks[key] = replace(current, extra_tables=(*current.extra_tables, table),
            references=tuple(dict.fromkeys((*current.references, table.reference))),
            reviewed_fingerprint='', client_reviewed_fingerprint='')
    review = flow.restored_group(bundle, bundle['groups'][index])
    state['publication'] = {'review_revision': review.revision,
        'corrections_revision': flow.revision(state['corrections']),
        'tables': [{'destination': key, 'table': asdict(table)} for key, table in incoming]}
    value = flow.decoded(flow.encoded(bundle))
    value['maintenance_projection'] = state
    result = flow.store_bundle(draft, value, expected_revision=expected_revision)
    return replace(result, blocks=tuple(blocks.values()))


def remove(draft, bundle, *, expected_revision, expected_blocks, index, confirmed, keep_manual=False):
    from app import monthly_report_work_order_review_flow as flow
    flow._validate(draft, bundle)
    if confirmed is not True or type(keep_manual) is not bool:
        raise ValueError('Confirm how to handle the included Maintenance rows first.')
    state = _state(bundle, index)
    previous = validate_state(state)
    if not previous:
        raise ValueError('There is no included Maintenance source link to remove.')
    blocks = {block.key: block for block in draft.blocks}
    for key in ('service_calls', 'work_orders'):
        current = blocks.get(key, ResolvedBlock(key, 'This month'))
        if expected_blocks.get(key) != current.fingerprint:
            raise ValueError('A destination table changed. Reopen this review first.')
    if not keep_manual:
        for key, table in previous:
            current = blocks.get(key, ResolvedBlock(key, 'This month'))
            if current.extra_tables.count(table) != 1:
                raise ValueError('Included rows were edited. Keep your edits as manual rows or restore them before removing the source link.')
            remaining = list(current.extra_tables)
            remaining.remove(table)
            blocks[key] = replace(current, extra_tables=tuple(remaining),
                reviewed_fingerprint='', client_reviewed_fingerprint='')
    else:
        for key, _ in previous:
            current = blocks.get(key, ResolvedBlock(key, 'This month'))
            blocks[key] = replace(current, reviewed_fingerprint='', client_reviewed_fingerprint='')
    state['publication'] = None
    value = flow.decoded(flow.encoded(bundle))
    value['maintenance_projection'] = state
    result = flow.store_bundle(draft, value, expected_revision=expected_revision)
    return replace(result, blocks=tuple(blocks.values()))


def check_binding(draft):
    """Guard exact published tables against later source/review edits."""
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_row_review_receipts import decoded
    blocks = {block.key: block for block in draft.blocks}
    included = used_block_keys(draft)
    for raw in draft.source_row_reviews:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            continue
        if not isinstance(value, dict) or value.get('kind') != 'workorders':
            continue
        state = value.get('maintenance_projection')
        if not isinstance(state, dict) or state.get('publication') is None:
            continue
        try:
            value = decoded(raw)
            state = value['maintenance_projection']
            tables = validate_state(state)
            active = [(key, table) for key, table in tables if key in included
                      and key in blocks and blocks[key].source != 'Omit']
            if not active:
                continue
            flow._validate(draft, value)
            group = value['groups'][state['group_index']]
            review = flow.restored_group(value, group)
            publication = state['publication']
            if (group['omitted'] or review.revision != publication['review_revision']
                    or flow.revision(state['corrections']) != publication['corrections_revision']
                    or any(blocks[key].extra_tables.count(table) != 1 for key, table in active)):
                raise ValueError('Maintenance evidence changed')
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return 'The Maintenance source, decisions or included rows changed. Reopen the work-order review before generating.'
    return None
