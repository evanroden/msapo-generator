"""Metadata-only photo preparation must survive after a shared report save."""
from io import BytesIO
import pytest
from PIL import Image
from app import monthly_report_active_work as active, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from test_monthly_report_ui import monthly
from test_monthly_report_active_recovery_ui import _visit, _value, _button, TOKEN, PERIOD


@pytest.mark.parametrize("replacement,status", [("corrupt","unrecoverable"),("valid","ready"),("busy","pending")])
def test_replacement_after_shared_save_is_durable_without_changing_last_good(monkeypatch,tmp_path,replacement,status):
    from app import monthly_report_cover_ui as ui
    from app import monthly_report_render_jobs as jobs
    _visit(monkeypatch)
    incoming={};real=ui.st.file_uploader
    monkeypatch.setattr(ui.st,'file_uploader',lambda label,*a,**kw:incoming.get(label) or real(label,*a,**kw))
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    app=monthly(monkeypatch,tmp_path)
    _value(app,'Prepared by','text_input').set_value('Synthetic recovery tester').run()
    raw=BytesIO();Image.new('RGB',(80,40),'cyan').save(raw,'PNG')
    raw.name='synthetic-good.png';raw.size=len(raw.getvalue())
    incoming['New photograph for this report']=raw
    app.run();assert not app.exception
    _button(app,'Use this photograph').click().run()
    _button(app,'Save shared version').click().run()
    assert not app.exception
    saved=library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)
    history=library.snapshot_history(RRH_CONTRACT,'synthetic-guided',PERIOD)
    assert saved.draft.cover_recovery_request.status=='applied'
    bad=BytesIO(b'not a decodable photograph')
    if replacement!='corrupt':
        bad=BytesIO();Image.new('RGB',(90,45),'orange').save(bad,'PNG')
    if replacement=='busy':
        monkeypatch.setattr(jobs,'memory_headroom',lambda:0)
    bad.name='synthetic-replacement.png';bad.size=len(bad.getvalue())
    incoming['New photograph for this report']=bad
    app.run();assert not app.exception
    journal=active.load(TOKEN,RRH_CONTRACT,'synthetic-guided',PERIOD)
    assert journal is not None
    assert journal.draft.cover_recovery_request.status==status
    assert journal.draft.blocks==saved.draft.blocks
    assert journal.draft.sources==saved.draft.sources
    assert journal.draft.fingerprint==saved.draft.fingerprint
    assert library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)==saved
    assert library.snapshot_history(RRH_CONTRACT,'synthetic-guided',PERIOD)==history

    # Reload loses the native selected file, but not the private durable intent.
    incoming.clear()
    from test_monthly_report_active_recovery_ui import _reopen
    reopened=_reopen()
    again=active.load(TOKEN,RRH_CONTRACT,'synthetic-guided',PERIOD)
    assert again.draft.cover_recovery_request.status==status
    assert again.draft.blocks==saved.draft.blocks
    assert library.snapshot_history(RRH_CONTRACT,'synthetic-guided',PERIOD)==history


def test_shared_saved_content_reversion_updates_existing_journal(monkeypatch,tmp_path):
    """Returning to shared content must not leave an older private edit on disk."""
    _visit(monkeypatch)
    app=monthly(monkeypatch,tmp_path)
    _value(app,'Prepared by','text_input').set_value('Synthetic recovery tester').run()
    _button(app,'Save shared version').click().run()
    saved=library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)
    original=_value(app,'Prepared by','text_input').value
    _value(app,'Prepared by','text_input').set_value('Temporary private author').run()
    _value(app,'Prepared by','text_input').set_value(original).run()
    kept=active.load(TOKEN,RRH_CONTRACT,'synthetic-guided',PERIOD)
    assert kept.draft.fingerprint==saved.draft.fingerprint
    assert kept.draft.blocks==saved.draft.blocks
    assert library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)==saved


def test_clearing_new_upload_after_shared_save_is_durable(monkeypatch,tmp_path):
    from app import monthly_report_cover_ui as ui, monthly_report_render_jobs as jobs
    _visit(monkeypatch)
    incoming={};real=ui.st.file_uploader
    monkeypatch.setattr(ui.st,'file_uploader',lambda label,*a,**kw:incoming.get(label) or real(label,*a,**kw))
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    app=monthly(monkeypatch,tmp_path)
    _value(app,'Prepared by','text_input').set_value('Synthetic recovery tester').run()
    _button(app,'Save shared version').click().run()
    saved=library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)
    raw=BytesIO();Image.new('RGB',(80,40),'cyan').save(raw,'PNG')
    raw.name='synthetic-good.png';raw.size=len(raw.getvalue())
    incoming['New photograph for this report']=raw
    app.run()
    assert active.load(TOKEN,RRH_CONTRACT,'synthetic-guided',PERIOD).draft.cover_recovery_request.status=='ready'
    incoming.clear();app.run()
    kept=active.load(TOKEN,RRH_CONTRACT,'synthetic-guided',PERIOD)
    assert kept.draft.cover_recovery_request is None
    assert kept.draft.blocks==saved.draft.blocks
    assert library.load_snapshot(RRH_CONTRACT,'synthetic-guided',PERIOD)==saved
