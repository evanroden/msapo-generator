import sqlite3

import pytest

from app import memory
from app.vendor_identity import is_operator_vendor_name


@pytest.mark.parametrize('name', ['Evan Roden', ' EVAN   RODEN ', 'Evan J. Roden', 'Roden, Evan', 'Roden, Evan J.', 'Ｅｖａｎ Ｒｏｄｅｎ'])
def test_operator_identity_formats(name):
    assert is_operator_vendor_name(name)


@pytest.mark.parametrize('name', ['Evan Jones', 'Jane Roden', 'Evan Roden-Smith', 'Roden Company', '', None])
def test_other_people_are_not_excluded(name):
    assert not is_operator_vendor_name(name)


def test_operator_cannot_be_learned_but_requester_and_other_reps_are_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    assert memory.record_vendor_contact(contract='Account', vendor='Vendor', contact_name='Evan Roden',
                                        contact_email='rep@example.com', context_id='bad') == 0
    assert memory.record_vendor_contact(contract='Account', vendor='Vendor', contact_name='Jane Vendor',
                                        contact_email='rep@example.com', context_id='good') == 1
    assert memory.record_send(contract='Account', vendor='Vendor', contact_name='Evan Roden',
                              contact_email='other@example.com')
    assert memory.vendor_reps('Account', 'Vendor') == [('Jane Vendor', 'rep@example.com')]
    assert not memory.correct_vendor_contact('Account', 'vendor', 'Jane Vendor', 'rep@example.com',
                                             new_name='Evan Roden', new_email='rep@example.com')
    with sqlite3.connect(tmp_path / 'epc_memory.db') as db:
        assert db.execute('SELECT name FROM vendor_contacts').fetchall() == [('Jane Vendor',)]
        assert db.execute('SELECT name FROM vendor_contact_events').fetchall() == [('Jane Vendor',)]
    # Requester normalization remains role-independent.
    assert memory._requester_key(' Evan  Roden ') == 'evan roden'


def test_legacy_bad_rows_are_not_recalled_even_before_database_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    memory.record_vendor_contact(contract='Account', vendor='Vendor', contact_name='Jane Vendor',
                                 contact_email='rep@example.com', context_id='good')
    with sqlite3.connect(tmp_path / 'epc_memory.db') as db:
        db.execute("INSERT INTO vendor_contacts VALUES (?, ?, ?, ?, ?, ?)",
                   ('Account', 'vendor', 'Evan Roden', 'bad@example.com', 99, 9999999999))
    assert memory.vendor_reps('Account', 'Vendor') == [('Jane Vendor', 'rep@example.com')]
    assert memory.remembered_vendor_contact('Account', 'Vendor') == ('Jane Vendor', 'rep@example.com')
    assert {x['name'] for x in memory.saved_vendor_contacts('Account')} == {'Jane Vendor', 'Evan Roden'}
