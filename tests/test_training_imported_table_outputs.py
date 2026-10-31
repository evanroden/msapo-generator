"""Real synthetic source-table edits through existing gated Word/PDF paths."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re

from docx import Document
import fitz
import pytest

from app import monthly_report_designs as designs
from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx, generate_report
from app.monthly_report_preview import section_preview_docx
from app.monthly_report_model import BlockSpec, SectionSpec
from tests.conftest import requires_libreoffice
from test_training_imported_table_editing import (
    COLUMNS, ROWS, current, edit, imported_training, open_app,
)


def cells(raw):
    return [tuple(tuple(c.text for c in r.cells) for r in t.rows)
            for t in Document(BytesIO(raw)).tables]


def corrected(imported_training, native):
    draft, path, original = imported_training
    app = open_app(draft)
    edit(app, edited={0: {'Hours': '1.75', 'Source note': 'Corrected source record'}}, deleted=[1])
    block = current(app)
    if native:
        profile = designs.install(path, draft.profile, actor='Synthetic Editor', expected_revision=0)
        draft = replace(draft, profile=profile)
    # Deliberately isolate this section; do not bypass other required sections
    # or treat a source-table correction as their acceptance.
    section = SectionSpec('training', '12', 'Training Summary',
                          (BlockSpec('training_summary', 'rich_text'),))
    draft = replace(draft, sections=(section,), blocks=(block,))
    return draft, path, original


@requires_libreoffice
@pytest.mark.parametrize('native', [False, True], ids=['plain', 'native'])
def test_edited_source_values_survive_preview_snapshot_and_word_pdf(imported_training, tmp_path, native):
    draft, path, original = corrected(imported_training, native)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    draft = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert draft == saved.draft
    expected = (COLUMNS, (*ROWS[0][:3], '1.75', 'Corrected source record'), ROWS[2])
    preview = section_preview_docx(draft, 'training')
    assert cells(preview) == [expected]
    result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    assert result.docx and result.pdf, result.pdf_error
    assert cells(result.docx) == [expected]
    folder = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path / 'evidence'))) / 'training-source-edit' / ('native' if native else 'plain')
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {'synthetic_only': True, 'files': {}}
    for name, data in (('preview.docx', preview), ('report.docx', result.docx), ('report.pdf', result.pdf)):
        (folder / name).write_bytes(data)
        manifest['files'][name] = {'bytes': len(data), 'sha256': sha256(data).hexdigest()}
    with fitz.open(stream=result.pdf, filetype='pdf') as pdf:
        text = re.sub(r'\s+', ' ', '\n'.join(page.get_text() for page in pdf))
        assert text.count('Current exercise') == 1
        assert text.count('Incomplete topic') == 1
        for value in ('2026-09-03', '1.75', 'Corrected source record'):
            assert value in text
        assert 'Prior briefing' not in text and '2026-08-01' not in text
        assert 'Completed training sessions' not in text
        manifest['page_count'] = len(pdf)
        for number, page in enumerate(pdf, 1):
            page.get_pixmap(dpi=110).save(folder / f'page-{number}.png')
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assert path.read_bytes() == original


def test_old_date_stays_reviewable_and_monetary_guard_is_not_bypassed(imported_training):
    draft, _, _ = imported_training
    app = open_app(draft)
    edit(app, edited={0: {'Hours': '1.25'}})
    draft = replace(draft, sections=(SectionSpec('training', '12', 'Training Summary',
        (BlockSpec('training_summary', 'rich_text'),)),), blocks=(current(app),))
    assert any(check.code == 'period' and '2026-08-01' in check.message for check in preflight(draft))
    with pytest.raises(ValueError, match='Acknowledge the warnings'):
        assemble_docx(draft)
    # Explicit warning acknowledgment keeps the real date; no current date
    # or completion state is fabricated from the source table.
    assert cells(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint))[0][2][1] == '2026-08-01'
    edit(app, edited={0: {'Source note': 'Repair cost $3200'}})
    unsafe = replace(draft, blocks=(current(app),))
    with pytest.raises(ValueError, match='[Pp]ric|[Mm]onetary|[Cc]ost'):
        assemble_docx(unsafe, acknowledged_fingerprint=unsafe.fingerprint)
