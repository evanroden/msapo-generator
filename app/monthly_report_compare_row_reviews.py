"""Read-only recovery descriptions of report-owned source row decisions."""
from collections import defaultdict
import re

from app.monthly_report_row_review_receipts import decoded
from app.monthly_report_training import EVENT_COLUMNS


KINDS = {'training': 'Training', 'workorders': 'Work orders', 'maintenance': 'Service calls'}
FIELDS = {'work_order': 'Work order', 'wo': 'Work order', 'site': 'Site', 'work_date': 'Work date',
          'completed_date': 'Completion date', 'finished': 'Finish date', 'status': 'Status',
          'work_type': 'Work type', 'trade': 'Trade', 'area': 'Area', 'task': 'Task', 'tag': 'Asset tag'}


def _index(draft):
    from app import monthly_report_training_review_flow as training
    from app import monthly_report_work_order_review_flow as orders

    reviews = {}
    for text in draft.source_row_reviews:
        value = decoded(text)
        if sum(s.id == value['source_id'] for s in draft.sources) != 1:
            raise ValueError('Ambiguous or missing source')
        if value['kind'] == 'training':
            training.validate(draft, value)
        else:
            orders._validate(draft, value)
        training_review = value['kind'] == 'training'
        key = (value['kind'], value['source_id'], value['table'] if training_review else None)
        if key in reviews:
            raise ValueError('Ambiguous source review')
        summary = (*_summary(value), _corrected_hours(value, draft) if training_review else '')
        # A Training form echoes every displayed value on Save. Suppress only
        # those exact echoes in the private decoded copy. Work-order editors
        # can reopen raw corrections even when normalization produced a blank.
        if training_review:
            record = value['record']
            record.pop('sha256')
            for row in record['review']['rows']:
                displayed = dict(zip(record['review']['normalized_columns'], row['values']))
                displayed['Completion status'] = row['status']
                row['corrections'] = [pair for pair in row['corrections'] if displayed.get(pair[0]) != pair[1]]
        reviews[key] = value, summary
    return reviews


def _groups(value):
    return [{'record': value['record']}] if value['kind'] == 'training' else value['groups']


def _corrected_hours(value, draft):
    """Show only a short numeric correction for a single confirmed-site event."""
    from app.monthly_report_source_scope import reviewed_scope
    from app.monthly_report_training_import import _event_mapping
    review = value['record']['review']
    if (review['kind'] != 'events' or tuple(review['normalized_columns']) != EVENT_COLUMNS
            or len(review['rows']) != 1 or review['issues'] or review['unmatched']):
        return ''
    # Additional source columns may carry a separate site or sensitive context.
    # Keep those values in the source editor, including any numeric correction.
    columns = review['original_columns']
    if len(columns) != 6 or set(_event_mapping(columns).values()) != set(range(6)):
        return ''
    row, = review['rows']
    source = next(s for s in draft.sources if s.id == value['source_id'])
    scope = reviewed_scope(source, draft.profile)
    if (not scope or scope['kind'] != 'sites' or len(set(scope['facilities'])) != 1
            or row['issues'] or row['excluded']):
        return ''
    hours = dict(row['corrections']).get('Hours', '')
    if (len(row['values']) == len(EVENT_COLUMNS) and hours == row['values'][-1]
            and re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,2})?', hours) and 0 < float(hours) <= 744):
        return 'Hours ' + hours + '.'
    return ''


def _summary(value):
    # Only fixed field labels, counts and choices leave this function for display.
    # Values are compared privately. Original cells and free-text corrections can
    # include financial details, another site's evidence or personal information.
    fields = defaultdict(list)
    fields['Historical sessions'] = sorted(value.get('history', ()))
    fields['Publication'] = bool(value['published'])
    fields['Trade totals'] = value.get('include_trades', False)
    fields['Date interpretation'] = value.get('date_order', '')
    total = corrected = excluded = 0
    for group in _groups(value):
        fields['Table inclusion'].append((group.get('omitted'), group.get('omit_unmatched')))
        record = group.get('record')
        if not record:
            continue
        review = record['review']
        fields['Source mapping'].append(review.get('mapping'))
        fields['Original table layout'].append(review.get('native_layout_confirmed'))
        fields['Financial exclusion'].append(review.get('financial_exclusion_confirmed'))
        fields['Requirements year'].append(review.get('source_year'))
        for row in review['rows']:
            total += 1
            corrected += bool(row['corrections'])
            excluded += row['excluded'] is True
            fields['Row inclusion'].append(row['excluded'])
            if value['kind'] == 'training':
                if review['kind'] == 'events':
                    for field, cell in zip(EVENT_COLUMNS, row['values']):
                        fields[field].append(cell)
                    fields['Completion status'].append(row['status'])
                else:
                    fields['Annual requirements'].append(row['values'])
            else:
                corrections = dict(row['corrections'])
                for field, label in FIELDS.items():
                    if field in row:
                        fields[label].append((row[field], corrections.get(field, row[field])))
    return (f'{total} rows, {corrected} with saved corrections, {excluded} left out. '
            + ('Included in report.' if value['published'] else 'Review saved.')), fields


def compare_row_reviews(working, saved):
    """Return bounded descriptions for the two copies, or None when equivalent."""
    before, after = saved.source_row_reviews, working.source_row_reviews
    if before == after:
        return None
    fallback = tuple(f'{len(items)} saved source reviews. Review details are unavailable here. Check the source editor before choosing a copy.'
                     for items in (before, after))
    if any(len(items) > 100 or any(not isinstance(raw, str) or len(raw) > 4_000_000 for raw in items)
           or sum(map(len, items)) > 16_000_000 for items in (before, after)):
        return fallback
    from app.monthly_report_training_review_flow import scope
    if scope(working) != scope(saved):
        return fallback
    try:
        left, right = _index(saved), _index(working)
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError):
        return fallback
    absent = None, ('No saved review', {}, '')
    changed = [key for key in dict.fromkeys((*left, *right))
               if left.get(key, absent)[0] != right.get(key, absent)[0]]
    if not changed:
        return None  # Equivalent decoded JSON, including key order and whitespace.
    descriptions = ([], [])
    for key in changed[:4]:
        a, b = left.get(key, absent)[1], right.get(key, absent)[1]
        detail, fields = '', []
        if key in left and key in right:
            fields = [name for name in dict.fromkeys((*a[1], *b[1])) if a[1].get(name) != b[1].get(name)]
            detail = 'Different decisions: ' + ', '.join(fields) + '.' if fields else 'Other saved review details differ.'
        for lines, draft, summary in zip(descriptions, (saved, working), (a, b)):
            source = next((i for i, s in enumerate(draft.sources, 1) if s.id == key[1]), None)
            label = KINDS[key[0]] + (f' · source {source}' if source else '')
            if key[2] is not None and key[2] < 10_000:
                label += f' · table {key[2]}'
            hours = summary[2] if 'Hours' in fields else ''
            lines.append(' '.join(filter(None, (label, summary[0], detail, hours))))
    if len(changed) > 4:
        for lines in descriptions:
            lines.append(f'{len(changed) - 4} additional source reviews differ.')
    return tuple('\n\n'.join(lines) for lines in descriptions)
