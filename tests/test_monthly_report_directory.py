"""A synthetic worksheet matrix; never embed an owner-supplied directory."""

from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

import pytest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import Facility, ReportPeriod, synthetic_draft, synthetic_profiles


def workbook(*, external=False, unsafe_xml=False, duplicate_cell=False):
    values = {'A2':'Contract overview', 'A6':'Facility', 'B6':'Synthetic North', 'C6':'Synthetic South',
              'A7':'Address', 'B7':'100 Example Way', 'C7':'200 Example Way',
              'A9':'Asset Manager', 'B9':'Synthetic Lead', 'C9':'Synthetic Alternate',
              'A10':'Phone', 'B10':'202-555-0100', 'A11':'Email', 'B11':'lead@example.invalid'}
    cells = ''.join(f'<c r="{address}" t="inlineStr"><is><t>{escape(value)}</t></is></c>' for address,value in values.items())
    cells += '<c r="D20"><f>WEBSERVICE("https://example.invalid/never-fetch")</f></c>'
    cells += '<c r="D21" t="str"><f>"Saved"</f><v>Saved</v></c>'
    if duplicate_cell:
        cells += '<c r="B6" t="inlineStr"><is><t>Duplicate</t></is></c>'
    sheet = f'<worksheet xmlns="{directory.S[1:-1]}"><dimension ref="A1:XFD1048576"/><sheetData><row>{cells}</row></sheetData></worksheet>'
    if unsafe_xml:
        sheet = '<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><x>&y;</x>'
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{directory.S[1:-1]}" xmlns:r="{directory.R[1:-1]}"><sheets><sheet name="Synthetic Contract" sheetId="1" r:id="r1"/></sheets></workbook>')
        mode=' TargetMode="External"' if external else ''
        target='https://example.invalid/never-fetch' if external else 'worksheets/sheet1.xml'
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="{target}"{mode}/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml',sheet)
    return stream.getvalue()


def inspected():
    raw=workbook()
    book=directory.inspect_workbook(raw)
    sheet=book.sheets[0]
    mapping=directory.suggest_matrix(sheet)
    return raw,book,sheet,directory.matrix_sites(book,sheet,*mapping)


def test_sparse_dimensions_cached_formulas_and_contact_mapping():
    _,book,sheet,sites=inspected()
    assert len(sheet.cells)==16  # Actual cells, not the formatted worksheet dimensions.
    assert sheet.values()[(20,4)]==''
    assert sheet.values()[(21,4)]=='Saved'
    assert any('2 formula' in n for n in book.notices)
    assert directory.suggest_matrix(sheet)[:3]==(6,1,7)
    assert [s.title for s in sites]==['Synthetic North','Synthetic South']
    assert sites[0].contacts[0].email=='lead@example.invalid'
    assert sites[0].contacts[0].source.endswith('Synthetic Contract!B9,B10,B11')


@pytest.mark.parametrize('options',[{'external':True},{'unsafe_xml':True},{'duplicate_cell':True}])
def test_unsafe_or_ambiguous_packages_rejected(options):
    with pytest.raises(ValueError):
        directory.inspect_workbook(workbook(**options))


def test_cell_budget_and_traversal_rejected(monkeypatch):
    raw=workbook()
    with ZipFile(BytesIO(raw)) as z:
        files={i.filename:z.read(i.filename) for i in z.infolist()}
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        for name,value in files.items(): z.writestr(name,value)
        z.writestr('../escape.xml','<x/>')
    with pytest.raises(ValueError,match='unsafe'):
        directory.inspect_workbook(stream.getvalue())
    monkeypatch.setattr(directory,'MAX_CELLS',2)
    with pytest.raises(ValueError,match='stored cells'):
        directory.inspect_workbook(raw)


def test_confirmation_revision_history_and_atomic_failure(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    raw,book,sheet,sites=inspected()
    params=dict(expected_revision=0,actor='Synthetic Editor',confirmed=True,raw=raw,source_sha256=book.sha256,source_sheet=sheet.name)
    with pytest.raises(library.LibraryError):
        directory.save_directory('Synthetic Contract',sites,**(params|{'confirmed':False}))
    first=directory.save_directory('Synthetic Contract',sites,**params)
    assert directory.load_directory(first.contract)==first
    assert directory.directory_contracts()==('Synthetic Contract',)
    with pytest.raises(library.RevisionConflict):
        directory.save_directory(first.contract,sites,**params)
    renamed=(replace(sites[0],title='Synthetic North Campus',aliases=('Synthetic North',)),sites[1])
    second=directory.save_directory(first.contract,renamed,expected_revision=1,actor='Synthetic Editor',confirmed=True)
    assert second.sites[0].key==first.sites[0].key
    original_write=library._atomic_write
    def fail_head(path,raw):
        if path.name=='manifest.json': raise OSError('Synthetic write failure')
        return original_write(path,raw)
    monkeypatch.setattr(library,'_atomic_write',fail_head)
    with pytest.raises(OSError):
        directory.save_directory(first.contract,sites,expected_revision=2,actor='Synthetic Editor',confirmed=True)
    assert directory.load_directory(first.contract)==second
    monkeypatch.setattr(library,'_atomic_write',original_write)
    restored=directory.restore_directory(first.contract,1,expected_revision=2,actor='Synthetic Editor',confirmed=True)
    assert restored.revision==3 and restored.sites==first.sites and restored.action=='restore:1'
    assert directory.load_directory(first.contract,2)==second


def test_alias_ambiguity_and_duplicate_links_are_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    _,_,_,sites=inspected()
    with pytest.raises(ValueError):
        directory.save_directory('Synthetic Contract',(sites[0],replace(sites[1],aliases=(sites[0].title,))),expected_revision=0,actor='Synthetic Editor',confirmed=True)
    with pytest.raises(ValueError,match='Two imported columns'):
        directory.merge_sites(sites,(sites[0],sites[0]))
    assert len(directory.merge_sites(sites,(replace(sites[0],title='Updated synthetic name'),)))==2


def test_contact_update_never_assigns_old_person_details_to_replacement():
    old=directory.DirectoryContact('Manager','Synthetic Prior','202-555-0100','prior@example.invalid','old')
    new=directory.DirectoryContact('Manager','Synthetic Next',source='new')
    assert directory.proposed_contacts((old,),(new,))==(new,)
    same=directory.DirectoryContact('Manager','Synthetic Prior',email='updated@example.invalid',source='new')
    result=directory.proposed_contacts((old,),(same,))[0]
    assert result.phone==old.phone and result.email==same.email


def test_directory_membership_never_changes_a_report_implicitly(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    _,_,_,sites=inspected()
    state=directory.save_directory('Synthetic Contract',sites,expected_revision=0,actor='Synthetic Editor',confirmed=True)
    facilities=(Facility('existing-id','Synthetic North'),)
    block,missing=directory.contact_block(state,facilities)
    assert missing==('Synthetic North',) and not block.rows
    block,missing=directory.contact_block(state,facilities,{'existing-id':sites[0].key})
    assert not missing and len(block.rows)==1
    assert block.rows[0][0]=='Synthetic North'
    draft=synthetic_draft(synthetic_profiles()[0],ReportPeriod(2026,9))
    with pytest.raises(ValueError,match='no contact-matrix'):
        directory.apply_contacts(draft,block)


def test_copied_headers_are_visible_without_inferred_contract_membership():
    _,book,sheet,_=inspected()
    copied=replace(sheet,name='Another Synthetic Contract')
    findings=directory.sheet_findings(replace(book,sheets=(sheet,copied)),copied)
    assert any('also appear' in f for f in findings)


def test_setup_site_options_use_confirmed_identity_and_hide_inactive(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    from app.monthly_report_section_ui import _site_options
    _,_,_,sites=inspected()
    sites=(replace(sites[0],aliases=('Synthetic Former North',)),replace(sites[1],active=False))
    directory.save_directory('Synthetic Contract',sites,expected_revision=0,actor='Synthetic Editor',confirmed=True)
    assert _site_options('Synthetic Contract')==(sites[0].facility,)


def test_partial_directory_keeps_catalog_sites_and_explicit_retirements(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    from app import contracts
    from app.monthly_report_editor import _key
    from app.monthly_report_section_ui import _site_options
    from app.monthly_report_start_ui import site_choices
    from app.monthly_report_directory_ui import _known_sites
    monkeypatch.setattr(contracts, 'sites_for_contract', lambda _: ['Synthetic North', 'Synthetic South', 'Synthetic West'])
    _, _, _, sites = inspected()
    sites = (replace(sites[0], title='Synthetic North Campus', aliases=('Synthetic North',)), replace(sites[1], active=False))
    state = directory.save_directory('Synthetic Contract', sites, expected_revision=0, actor='Synthetic Editor', confirmed=True)
    choices = _site_options('Synthetic Contract')
    assert choices == (sites[0].facility, Facility(_key('Synthetic West'), 'Synthetic West'))
    assert _known_sites('Synthetic Contract', state) == (*sites, directory.DirectorySite(_key('Synthetic West'), 'Synthetic West'))
    # An existing report's identity survives a later directory import.
    profile = replace(synthetic_profiles()[0], facilities=(Facility('prior-id', 'Synthetic North'),))
    assert site_choices('Synthetic Contract', (profile,)) == (profile.facilities[0], choices[1])


def test_site_name_ambiguity_is_never_silently_merged():
    site = directory.DirectorySite('directory', 'Synthetic Campus', ('Synthetic North', 'Synthetic South'))
    state = directory.DirectoryState('Synthetic Contract', 1, (site,), 'Synthetic Editor', '')
    catalog = (Facility('north', 'Synthetic North'), Facility('south', 'Synthetic South'))
    assert directory.available_sites(catalog, state) == (site.facility, *catalog)
    assert directory.suggest_contact_bindings(state, catalog) == {'north': '', 'south': ''}


def test_contact_suggestions_require_unique_exact_identity_or_alias():
    north = directory.DirectorySite('north', 'Synthetic North', ('Former Campus',))
    south = directory.DirectorySite('south', 'Synthetic South')
    state = directory.DirectoryState('Synthetic Contract', 1, (north, south), 'Synthetic Editor', '')
    facilities = (Facility('prior', ' FORMER   campus '), Facility('other', 'Synthetic South Annex'))
    assert directory.suggest_contact_bindings(state, facilities) == {'prior': 'north', 'other': ''}
    assert directory.suggest_contact_bindings(state, facilities, {'prior': 'south'})['prior'] == 'south'
    retired = replace(state, sites=(replace(north, active=False), south))
    assert directory.suggest_contact_bindings(retired, facilities, {'prior': 'north'})['prior'] == ''
    # A confirmed link cannot be re-used by another automatic name suggestion.
    facilities = (Facility('existing', 'Synthetic Alias'), Facility('new', 'Synthetic North'))
    assert directory.suggest_contact_bindings(state, facilities, {'existing': 'north'}) == {'existing': 'north', 'new': ''}


def test_directory_upload_preview_confirmation_and_save_in_app(tmp_path,monkeypatch):
    from pathlib import Path
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from app import contracts
    from app.monthly_report_editor import _key
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    original_sites = contracts.sites_for_contract
    monkeypatch.setattr(contracts, 'sites_for_contract', lambda contract: ['Synthetic North', 'Synthetic West'] if contract == 'Synthetic Contract' else original_sites(contract))
    upload=BytesIO(workbook()); upload.name='synthetic-directory.xlsx'
    original=st.file_uploader
    monkeypatch.setattr(st,'file_uploader',lambda label,*a,**kw: upload if label=='Contract / site directory workbook' else original(label,*a,**kw))
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'run_web.py',default_timeout=20).run()
    app.segmented_control[0].set_value('Monthly report').run()
    next(b for b in app.button if b.label=='Manage contract and site directory').click().run()
    next(b for b in app.button if b.label=='Read workbook').click().run()
    assert not app.exception
    assert next(b for b in app.button if b.label=='Save contract directory').disabled
    assert directory.load_directory('Synthetic Contract') is None
    next(t for t in app.text_input if t.label=='Directory editor name').set_value('Synthetic Editor').run()
    next(c for c in app.checkbox if c.label=='I reviewed all included sites and contacts and confirm this shared save').check().run()
    next(b for b in app.button if b.label=='Save contract directory').click().run()
    assert not app.exception
    state=directory.load_directory('Synthetic Contract')
    assert state.revision==1 and len(state.sites)==2
    assert state.sites[0].key==_key('Synthetic North')  # First import links to the listed site.
    assert state.sites[0].contacts[0].email=='lead@example.invalid'
    next(b for b in app.button if b.label=='Back to monthly reports').click().run()
    assert not app.exception
    assert any(b.label == 'Synthetic Contract' for b in app.button)
    assert not library.list_profiles('Synthetic Contract')  # Directory is not report membership.
