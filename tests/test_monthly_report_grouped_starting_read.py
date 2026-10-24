"""Request-local read reuse never replaces source or publication proof."""
from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from app import monthly_report_library as library, monthly_report_start as start
from app.monthly_report_model import ReportPeriod
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


def test_each_grouped_read_rederives_once_and_retains_month_order(sample, monkeypatch):
    from app import monthly_report_compatibility_view as compatibility
    draft, _ = save_sample(sample)
    real = compatibility.rederive_compatibility_view
    calls=[]
    def derive(*a, **kw):
        calls.append(1)
        return real(*a, **kw)
    monkeypatch.setattr(compatibility, 'rederive_compatibility_view', derive)
    for month in (9,10,8):
        imported, prior, selected = start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,month))
        assert imported == draft and prior is None
        assert selected == (draft if month > 9 else None)
    assert len(calls)==3


@pytest.mark.parametrize('changed', ['manifest','original','receipt','missing-original'])
def test_change_between_candidate_reads_refuses_result(sample,monkeypatch,changed):
    draft,_=save_sample(sample)
    folder=library._profile_path(draft.profile.contract,draft.profile.key)
    manifest=folder/'manifest.json'
    value=json.loads(manifest.read_bytes())
    record=value['source_views'][value['import_source_view']]
    original=folder/'imports'/(draft.profile.imported_from+'.docx')
    receipt=library._source_view_receipt_path(folder,record['scope'])
    count=0
    def mutate(*a):
        nonlocal count
        count+=1
        if count==2:
            if changed=='manifest':manifest.write_bytes(manifest.read_bytes()+b' ')
            elif changed=='original':
                raw=original.read_bytes()
                original.unlink()
                original.write_bytes(raw+b'changed')
            elif changed=='receipt':receipt.write_bytes(receipt.read_bytes()+b' ')
            else:original.unlink()
        return None
    monkeypatch.setattr(start,'latest_snapshot',mutate)
    with pytest.raises(ValueError,match='changed|disappeared'):
        start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))
    assert count==2


def test_invalid_receipt_fails_before_snapshot_selection(sample,monkeypatch):
    draft,_=save_sample(sample)
    folder=library._profile_path(draft.profile.contract,draft.profile.key)
    next((folder/'imports').glob('*.source-view.json')).write_bytes(b'{}')
    monkeypatch.setattr(start,'latest_snapshot',lambda *a:pytest.fail('Proof must precede fallback'))
    with pytest.raises(ValueError):start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))


@pytest.mark.parametrize('import_month,snapshot_month,revision,expected',[
    (9,8,0,'import'),(8,9,0,'saved'),(9,9,1,'import'),(9,9,0,'saved'),(10,9,1,'saved'),
])
def test_same_month_revision_and_snapshot_fallback_preserved(sample,monkeypatch,import_month,snapshot_month,revision,expected):
    draft,_=save_sample(sample)
    imported=replace(draft,period=ReportPeriod(2026,import_month))
    saved=SimpleNamespace(draft=replace(draft,period=ReportPeriod(2026,snapshot_month),prepared_by='Saved'),revision=1)
    monkeypatch.setattr(library,'imported_snapshot_revision',lambda *a:revision)
    result=start._select_saved_draft(saved,imported,draft.profile.contract,draft.profile.key,ReportPeriod(2026,10),before=True)
    assert result==(imported if expected=='import' else saved.draft)


def test_snapshot_exception_propagates_without_fallback(sample,monkeypatch):
    draft,_=save_sample(sample)
    def fail(*a):raise library.LibraryError('Synthetic damaged snapshot')
    monkeypatch.setattr(start,'latest_snapshot',fail)
    with pytest.raises(library.LibraryError,match='damaged snapshot'):
        start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))


def test_metadata_change_during_loader_rejected_before_selection(sample,monkeypatch):
    draft,_=save_sample(sample)
    manifest=library._profile_path(draft.profile.contract,draft.profile.key)/'manifest.json'
    real=library._load_imported_draft_value
    def changed(*a,**kw):
        result=real(*a,**kw)
        manifest.write_bytes(manifest.read_bytes()+b' ')
        return result
    monkeypatch.setattr(library,'_load_imported_draft_value',changed)
    monkeypatch.setattr(start,'latest_snapshot',lambda *a:pytest.fail('Changed metadata must not be used'))
    with pytest.raises(library.LibraryError,match='metadata changed'):
        start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))


def test_both_prior_snapshot_lookups_keep_their_existing_order(sample,monkeypatch):
    draft,_=save_sample(sample)
    first=SimpleNamespace(draft=replace(draft,period=ReportPeriod(2026,7)),revision=1)
    second=SimpleNamespace(draft=replace(draft,period=ReportPeriod(2026,8)),revision=1)
    calls=[]
    def lookup(*a):
        calls.append(a)
        return first if len(calls)==1 else second
    monkeypatch.setattr(start,'latest_snapshot',lookup)
    imported,prior,selected=start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,9))
    assert imported==draft and prior is first and selected==second.draft
    assert len(calls)==2


def test_legacy_profile_without_import_is_still_empty(tmp_path,monkeypatch):
    from app.monthly_report_model import synthetic_profiles
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    profile=synthetic_profiles()[0]
    library.save_profile(profile,expected_revision=0,actor='Synthetic operator',confirmed=True)
    assert start.read_starting_state(profile.contract,profile.key,ReportPeriod(2026,10))==(None,None,None)


@pytest.mark.parametrize('when',['before','after-proof'])
def test_missing_manifest_retains_library_error(sample,monkeypatch,when):
    draft,_=save_sample(sample)
    manifest=library._profile_path(draft.profile.contract,draft.profile.key)/'manifest.json'
    if when=='before':manifest.unlink()
    else:
        real=library._load_imported_draft_value
        def removed(*a,**kw):
            result=real(*a,**kw)
            manifest.unlink()
            return result
        monkeypatch.setattr(library,'_load_imported_draft_value',removed)
    with pytest.raises(library.LibraryError):
        start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))


def test_manifest_aba_during_proof_uses_captured_bootstrap(sample,monkeypatch):
    draft,_=save_sample(sample)
    manifest=library._profile_path(draft.profile.contract,draft.profile.key)/'manifest.json'
    original=manifest.read_bytes()
    alternate=json.loads(original)
    alternate['bootstrap']['prepared_by']='Transient other operator'
    real=library._load_imported_draft_value
    def transient(*a,**kw):
        manifest.write_text(json.dumps(alternate))
        try:return real(*a,**kw)
        finally:manifest.write_bytes(original)
    monkeypatch.setattr(library,'_load_imported_draft_value',transient)
    imported,_,selected=start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))
    assert imported==draft and selected==draft
    assert manifest.read_bytes()==original


def test_manifest_aba_during_selection_cannot_supply_other_snapshot_revision(sample,monkeypatch):
    draft,_=save_sample(sample)
    manifest=library._profile_path(draft.profile.contract,draft.profile.key)/'manifest.json'
    original=manifest.read_bytes()
    alternate=json.loads(original)
    assert alternate.get('bootstrap_snapshot_revision',0)==0
    alternate['bootstrap_snapshot_revision']=1
    saved=SimpleNamespace(draft=replace(draft,prepared_by='Saved snapshot'),revision=1)
    monkeypatch.setattr(start,'latest_snapshot',lambda *a:saved)
    real=start._select_saved_draft
    def transient(*a,**kw):
        manifest.write_text(json.dumps(alternate))
        try:return real(*a,**kw)
        finally:manifest.write_bytes(original)
    monkeypatch.setattr(start,'_select_saved_draft',transient)
    imported,prior,selected=start.read_starting_state(draft.profile.contract,draft.profile.key,ReportPeriod(2026,10))
    assert imported==draft and prior is saved and selected==saved.draft
    assert manifest.read_bytes()==original
