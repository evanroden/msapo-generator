"""Finished files retain precise shared-save state and target only failed work."""
from dataclasses import replace
from pathlib import Path

from app import monthly_report_guided as guided, monthly_report_library as library
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import ReportPeriod
from app.contracts import RRH_CONTRACT
from test_monthly_report_ui import monthly


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def ready(monkeypatch, tmp_path, *, pdf=True):
    calls = []
    def generate(draft, **kwargs):
        calls.append(draft.fingerprint)
        return ReportPackage(b'synthetic-finished-word', b'%PDF-synthetic' if pdf else None,
                             'synthetic.docx', 'synthetic.pdf', draft.fingerprint,
                             '' if pdf else 'Synthetic PDF conversion failed. The DOCX is ready to download.')
    monkeypatch.setattr(guided, 'generate_report', generate)
    app = monthly(monkeypatch, tmp_path)
    widget(app, 'text_input', 'Prepared by').set_value('Synthetic output editor').run()
    widget(app, 'text_area', 'Activity summary').set_value('Completed synthetic monthly repair.').run()
    return app, calls


def create(app):
    widget(app, 'button', 'Create Word and PDF').click().run()
    assert not app.exception


def test_shared_save_failure_survives_neutral_rerun_with_files(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    def unavailable(*args, **kwargs):
        raise OSError('Synthetic shared disk unavailable')
    monkeypatch.setattr(library, 'save_snapshot', unavailable)
    create(app)
    assert any('Synthetic shared disk unavailable' in item.value for item in app.warning)
    app.run()
    assert not app.exception
    assert any('Synthetic shared disk unavailable' in item.value for item in app.warning)
    assert [item.label for item in app.get('download_button')] == ['Download DOCX', 'Download PDF']
    assert len(calls) == 1


def test_success_names_actual_shared_version_and_uses_one_replacing_save_status(monkeypatch, tmp_path):
    app, _ = ready(monkeypatch, tmp_path)
    create(app)
    assert any('[Shared version 1](#shared-report-history)' in item.value for item in app.caption)
    statuses = [item.value for item in app.markdown if 'class="enfra-browser-save-status"' in item.value]
    assert len(statuses) == 1 and 'Shared report<br>Version 1 is saved' in statuses[0]
    assert 'Browser draft' not in statuses[0]
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026,9)).revision == 1


def test_retry_shared_save_preserves_output_and_does_not_generate_or_duplicate(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    original = library.save_snapshot
    monkeypatch.setattr(library, 'save_snapshot', lambda *a, **kw: (_ for _ in ()).throw(OSError('Synthetic save failure')))
    create(app)
    assert widget(app, 'button', 'Retry saving this version')
    monkeypatch.setattr(library, 'save_snapshot', original)
    widget(app, 'button', 'Retry saving this version').click().run()
    assert not app.exception
    assert any('[Shared version 1]' in item.value for item in app.caption)
    assert not any(item.label == 'Retry saving this version' for item in app.button)
    app.run()
    assert len(calls) == 1
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026,9)).revision == 1


def test_concurrent_shared_version_disables_targeted_save_and_keeps_both(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    original = library.save_snapshot
    monkeypatch.setattr(library, 'save_snapshot', lambda *a, **kw: (_ for _ in ()).throw(OSError('Synthetic save failure')))
    create(app)
    monkeypatch.setattr(library, 'save_snapshot', original)
    draft = next(value for key,value in app.session_state.filtered_state.items() if key.endswith('_draft') and hasattr(value, 'blocks'))
    newer = original(replace(draft, prepared_by='Concurrent synthetic editor'), expected_revision=0, entered_editor='Concurrent synthetic editor')
    app.run()
    assert not app.exception
    assert widget(app, 'button', 'Retry saving this version').disabled
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == newer
    assert len(calls) == 1


def test_pdf_retry_uses_same_word_bytes_and_never_resaves_shared_version(monkeypatch, tmp_path):
    from app import monthly_report_docx as docx
    app, calls = ready(monkeypatch, tmp_path, pdf=False)
    create(app)
    converted = []
    def retry(draft, package):
        converted.append(package.docx)
        return replace(package, pdf=b'%PDF-retried', pdf_error='')
    monkeypatch.setattr(docx, 'retry_report_pdf', retry)
    widget(app, 'button', 'Retry PDF').click().run()
    assert not app.exception
    assert converted == [b'synthetic-finished-word'] and len(calls) == 1
    assert [item.label for item in app.get('download_button')] == ['Download DOCX', 'Download PDF']
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026,9)).revision == 1
    assert not any(item.label == 'Retry PDF' for item in app.button)


def test_changing_draft_retires_old_outputs_and_retry_actions(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path, pdf=False)
    create(app)
    widget(app, 'text_area', 'Activity summary').set_value('A different synthetic monthly repair.').run()
    assert not app.exception
    assert not app.get('download_button')
    assert not any(item.label in ('Retry PDF', 'Retry saving this version') for item in app.button)
    assert len(calls) == 1


def _current_output_draft(app):
    return next((key, value) for key, value in app.session_state.filtered_state.items()
                if key.endswith('_draft') and hasattr(value, 'blocks'))


def _fail_output_shared_save(monkeypatch):
    monkeypatch.setattr(library, 'save_snapshot', lambda *a, **kw: (
        _ for _ in ()).throw(OSError('Synthetic save unavailable')))


def test_prior_save_button_cannot_save_new_fingerprint_with_identical_word_bytes(monkeypatch, tmp_path):
    from app.monthly_report_docx import assemble_docx
    app, calls = ready(monkeypatch, tmp_path)
    original_save = library.save_snapshot
    _fail_output_shared_save(monkeypatch)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry saving this version')
    key, earlier = _current_output_draft(app)
    changed = replace(earlier, blocks=tuple(
        replace(block, references=(*block.references, 'synthetic:additional-context'))
        if block.key == 'activity_summary' else block for block in earlier.blocks))
    assert changed.fingerprint != earlier.fingerprint
    # This real metadata change affects source identity but not native Word bytes;
    # a DOCX-hash-only native button key previously rebound to the later report.
    assert assemble_docx(earlier, acknowledged_fingerprint=earlier.fingerprint) == (
        assemble_docx(changed, acknowledged_fingerprint=changed.fingerprint))
    app.session_state[key] = changed
    app.run()
    create(app)
    assert widget(app, 'button', 'Retry saving this version').key != earlier_retry.key
    monkeypatch.setattr(library, 'save_snapshot', original_save)
    earlier_retry.click().run()
    assert not app.exception
    assert library.load_snapshot(earlier.profile.contract, earlier.profile.key, earlier.period) is None
    assert widget(app, 'button', 'Retry saving this version')
    assert len(calls) == 2


def test_prior_pdf_button_cannot_convert_new_fingerprint_with_identical_word_bytes(monkeypatch, tmp_path):
    from app import monthly_report_docx as docx
    app, calls = ready(monkeypatch, tmp_path, pdf=False)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry PDF')
    key, earlier = _current_output_draft(app)
    changed = replace(earlier, blocks=tuple(
        replace(block, references=(*block.references, 'synthetic:additional-context'))
        if block.key == 'activity_summary' else block for block in earlier.blocks))
    assert changed.fingerprint != earlier.fingerprint
    app.session_state[key] = changed
    app.run()
    create(app)
    assert widget(app, 'button', 'Retry PDF').key != earlier_retry.key
    conversions = []
    monkeypatch.setattr(docx, 'retry_report_pdf', lambda draft, package: (
        conversions.append(draft.fingerprint) or replace(package, pdf=b'%PDF-late', pdf_error='')))
    earlier_retry.click().run()
    assert not app.exception
    assert conversions == [] and len(calls) == 2
    assert widget(app, 'button', 'Retry PDF')
    assert library.load_snapshot(earlier.profile.contract, earlier.profile.key, earlier.period).revision == 2


def test_save_retry_delivered_with_native_edit_is_consumed_without_saving(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    original_save = library.save_snapshot
    _fail_output_shared_save(monkeypatch)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry saving this version')
    _, earlier = _current_output_draft(app)
    monkeypatch.setattr(library, 'save_snapshot', original_save)
    widget(app, 'text_area', 'Activity summary').set_value('New text delivered with the earlier save action.')
    earlier_retry.click().run()
    assert not app.exception
    assert library.load_snapshot(earlier.profile.contract, earlier.profile.key, earlier.period) is None
    assert not app.get('download_button')
    assert not any('_pending_output_' in key for key in app.session_state.filtered_state)
    app.run()
    assert library.load_snapshot(earlier.profile.contract, earlier.profile.key, earlier.period) is None
    assert len(calls) == 1


def test_pdf_retry_delivered_with_native_edit_is_consumed_without_conversion(monkeypatch, tmp_path):
    from app import monthly_report_docx as docx
    app, calls = ready(monkeypatch, tmp_path, pdf=False)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry PDF')
    conversions = []
    monkeypatch.setattr(docx, 'retry_report_pdf', lambda draft, package: (
        conversions.append(draft.fingerprint) or replace(package, pdf=b'%PDF-late', pdf_error='')))
    widget(app, 'text_area', 'Activity summary').set_value('New text delivered with the earlier PDF action.')
    earlier_retry.click().run()
    assert not app.exception
    assert conversions == [] and len(calls) == 1
    assert not app.get('download_button')
    assert not any('_pending_output_' in key for key in app.session_state.filtered_state)


def test_prior_save_retry_cannot_cross_discard_recreation_of_identical_report(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    original_save = library.save_snapshot
    _fail_output_shared_save(monkeypatch)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry saving this version')
    _, earlier = _current_output_draft(app)
    earlier_scope = next(value for key, value in app.session_state.filtered_state.items()
                         if key.endswith('_rich_text_epoch'))
    widget(app, 'checkbox', 'Discard my unfinished changes for this report').check().run()
    widget(app, 'button', 'Start this report over').click().run()
    widget(app, 'text_input', 'Prepared by').set_value('Synthetic output editor').run()
    widget(app, 'text_area', 'Activity summary').set_value('Completed synthetic monthly repair.').run()
    create(app)
    _, recreated = _current_output_draft(app)
    assert recreated.fingerprint == earlier.fingerprint
    assert next(value for key, value in app.session_state.filtered_state.items()
                if key.endswith('_rich_text_epoch')) != earlier_scope
    assert widget(app, 'button', 'Retry saving this version').key != earlier_retry.key
    monkeypatch.setattr(library, 'save_snapshot', original_save)
    # The retired tree contains intentionally deleted native text widgets;
    # AppTest cannot serialize that entire old tree after a real reset. Deliver
    # only its native stale button event alongside the current widget states.
    current = widget(app, 'button', 'Retry saving this version')
    states = current.root.get_widget_states()
    states.widgets.add().CopyFrom(earlier_retry.click()._widget_state)
    app._run(states)
    assert not app.exception
    assert library.load_snapshot(earlier.profile.contract, earlier.profile.key, earlier.period) is None
    assert widget(app, 'button', 'Retry saving this version')
    assert len(calls) == 2


def test_retry_before_concurrency_decision_cannot_save_after_base_is_accepted(monkeypatch, tmp_path):
    app, calls = ready(monkeypatch, tmp_path)
    original_save = library.save_snapshot
    _fail_output_shared_save(monkeypatch)
    create(app)
    earlier_retry = widget(app, 'button', 'Retry saving this version')
    _, draft = _current_output_draft(app)
    monkeypatch.setattr(library, 'save_snapshot', original_save)
    newer = original_save(replace(draft, prepared_by='Concurrent editor'), expected_revision=0,
                          entered_editor='Concurrent editor')
    app.run()
    widget(app, 'checkbox', 'I compared the saved version and want to save my draft as the next version').check().run()
    widget(app, 'button', 'Continue with my draft').click().run()
    assert not widget(app, 'button', 'Retry saving this version').disabled
    assert widget(app, 'button', 'Retry saving this version').key != earlier_retry.key
    earlier_retry.click().run()
    assert not app.exception
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == newer
    assert len(calls) == 1
