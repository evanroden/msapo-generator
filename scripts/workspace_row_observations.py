"""Read-only row receipts in the existing marked synthetic namespace."""
from dataclasses import asdict, replace
from html import escape
import json

from scripts.workspace_history_observations import namespace

ROW_KEYS = {'proposals', 'service_calls', 'contact_matrix', 'subcontractor_matrix', 'rfi_matrix'}


def row_state(draft):
    specs = {spec.key: spec for section in draft.sections for spec in section.blocks}
    result = {}
    for block in draft.blocks:
        if block.key not in ROW_KEYS:
            continue
        tables = ([{'columns': [c.title for c in specs[block.key].columns],
                    'rows': block.rows, 'reference': ''}] if block.rows else [])
        tables.extend({'columns': table.columns, 'rows': table.rows, 'reference': table.reference}
                      for table in block.extra_tables)
        result[block.key] = {'tables': tables, 'references': block.references,
                             'source': block.source}
    return {'rows': result, 'fingerprint': draft.fingerprint,
            'unrelated': replace(draft, blocks=tuple(block for block in draft.blocks
                if block.key not in ROW_KEYS)).fingerprint}


def emit_row_snapshot(base, token):
    from app import monthly_report_library as library, monthly_report_testing as testing
    from app import monthly_report_qa_fixture as fixture
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    import streamlit as st
    target, identity, generation = namespace(base, token)
    if (testing.scope(), testing.generation()) != (identity, generation):
        raise ValueError('Row receipt requires the current isolated generation.')
    if library._root().resolve() != (target / 'monthly_reports').resolve():
        raise ValueError('Row receipt cannot read the live library.')
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved is None:
        return
    working = _working_report(saved)
    active = load(token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    from app import monthly_report_directory as directory
    contacts = directory.load_directory(fixture.CONTRACT)
    durable = active.draft if active else saved.draft
    value = {'scope': identity, 'generation': generation, 'saved_revision': saved.revision,
             'working': row_state(working), 'durable': row_state(durable),
             'directory': asdict(contacts) if contacts else None}
    if namespace(base, token)[1:] != (identity, generation):
        raise ValueError('Row receipt generation changed during observation.')
    st.html('<span hidden data-enfra-row-receipt="' + escape(json.dumps(value), quote=True) + '"></span>')
