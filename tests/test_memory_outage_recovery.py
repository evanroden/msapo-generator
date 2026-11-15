"""Learned memory is optional; unavailable storage cannot stop package work."""
import sqlite3
import pytest
from app import memory


def exercise_unavailable():
    assert memory.record_send(contract='TEST ACCOUNT',admin_email='admin@example.invalid') is False
    assert memory.record_vendor_contact(contract='TEST ACCOUNT',vendor='TEST VENDOR',
        contact_name='TEST CONTACT',contact_email='test@example.invalid',context_id='test-event')==0
    assert memory.record_device_account_manager(device_token='test-browser',account='TEST ACCOUNT',
        manager_name='TEST MANAGER',context_id='test-event')==0
    assert memory.suggest_admin_emails('TEST ACCOUNT')==[]
    assert memory.suggest_contacts('TEST ACCOUNT')==[]
    assert memory.vendor_reps('TEST ACCOUNT','TEST VENDOR')==[]
    assert memory.remembered_vendor_contact('TEST ACCOUNT','TEST VENDOR')==('','')
    assert memory.remembered_device_account_manager('test-browser','TEST ACCOUNT')==''
    assert memory.expense_approvers('TEST ACCOUNT')==[]
    assert memory.remembered_expense_profile('test-browser','TEST ACCOUNT')=={}
    assert memory.remembered_expense_employee_number('test-browser','TEST ACCOUNT','TEST EMPLOYEE')==''
    assert memory.remembered_report_preparer('test-browser','TEST ACCOUNT','TEST SITE')==''
    assert memory.remembered_report_preferences('test-browser')==('','')


@pytest.mark.parametrize('state',['corrupt','directory','missing-parent'])
def test_unavailable_memory_returns_safe_defaults_without_changing_bad_storage(monkeypatch,tmp_path,state):
    path=tmp_path/'epc_memory.db'
    if state=='corrupt':path.write_bytes(b'TEST ONLY corrupt database, preserve for recovery')
    elif state=='directory':path.mkdir()
    else:path=tmp_path/'absent'/'epc_memory.db'
    before=path.read_bytes() if path.is_file() else None
    monkeypatch.setattr(memory,'_db_path',lambda:path)
    exercise_unavailable()
    assert (path.read_bytes() if path.is_file() else None)==before


def test_transient_connection_failure_recovers_without_restart_or_cross_account_leak(monkeypatch,tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    real=sqlite3.connect
    def failed(*args,**kwargs):raise sqlite3.OperationalError('TEST ONLY disk unavailable')
    monkeypatch.setattr(memory.sqlite3,'connect',failed)
    exercise_unavailable()
    monkeypatch.setattr(memory.sqlite3,'connect',real)
    assert memory.record_vendor_contact(contract='TEST ACCOUNT',vendor='TEST VENDOR',
        contact_name='TEST CONTACT',contact_email='test@example.invalid',context_id='test-event')==1
    assert memory.remembered_vendor_contact('TEST ACCOUNT','TEST VENDOR')==('TEST CONTACT','test@example.invalid')
    assert memory.remembered_vendor_contact('OTHER ACCOUNT','TEST VENDOR')==('','')
