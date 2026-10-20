"""Native contact edits preserve report scope, pending text and source rows."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_visual_ui import _contact_scope_labels
from test_monthly_report_vendor_contacts import vendor_app, vendor_block


ROWS = (("North", "HVAC", "Same vendor", "Alex", "202-555-0101", "Pending"),
        ("South", "Electrical", "Same vendor", "Alex", "202-555-0102", ""))


def button(app, label, n=0):
    return [item for item in app.button if item.label == label][n]


def test_remove_and_undo_capture_pending_other_row_without_changing_sources():
    app = vendor_app(ROWS)
    original = vendor_block(app)
    button(app, "Edit vendor contact").click().run()
    next(item for item in app.text_input if item.label == "Agreement status (MSA)").set_value("Awaiting named signature")
    button(app, "Remove vendor contact", 1).click().run()
    assert not app.exception
    assert vendor_block(app).rows == ((*ROWS[0][:-1], "Awaiting named signature"),)
    button(app, "Undo remove vendor contact").click().run()
    assert not app.exception
    assert vendor_block(app).rows == ((*ROWS[0][:-1], "Awaiting named signature"), ROWS[1])
    assert vendor_block(app).references == original.references
    assert vendor_block(app).asset_hashes == original.asset_hashes
    assert not any(item.label == "Undo remove vendor contact" for item in app.button)


def test_later_delivered_edit_expires_remove_undo_without_losing_human_text():
    app = vendor_app(ROWS)
    button(app, "Remove vendor contact", 1).click().run()
    button(app, "Edit vendor contact").click().run()
    next(item for item in app.text_input if item.label == "Agreement status (MSA)").set_value("Later deliberate edit")
    # A still-displayed Undo receives the pending native field in the same
    # event. It cannot replace that edit with a previous table snapshot.
    button(app, "Undo remove vendor contact").click().run()
    assert not app.exception
    assert vendor_block(app).rows == ((*ROWS[0][:-1], "Later deliberate edit"),)
    assert not any(item.label == "Undo remove vendor contact" for item in app.button)


def test_same_name_contacts_keep_custom_fields_and_one_active_editor():
    from test_monthly_report_organization_ui import SCRIPT
    script = SCRIPT.replace('(("Operator", "Synthetic Person"),)',
                            '(("Operator", "Same Person"), ("Supervisor", "Same Person"))')
    app = AppTest.from_string(script).run()
    button(app, "Edit contact").click().run()
    identity = next(item for item in app.text_input if item.label == "Name").proto.id
    next(item for item in app.text_input if item.label == "Name").set_value("Corrected first person")
    button(app, "Edit contact").click().run()
    assert not app.exception and len(app.text_input) == 2
    assert next(item for item in app.text_input if item.label == "Role").value == "Supervisor"
    assert app.session_state["blocks"]["contact_matrix"].extra_tables[0].rows == (
        ("Operator", "Corrected first person"), ("Supervisor", "Same Person"))
    button(app, "Edit contact").click().run()
    assert next(item for item in app.text_input if item.label == "Name").proto.id == identity


def test_scope_uses_exact_historical_site_copy_and_reading_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    site = directory.DirectorySite("directory-north", "Directory North", aliases=(profile.facilities[0].title,),
        contacts=(directory.DirectoryContact("Site Lead", "Synthetic North Lead"),))
    state = directory.save_directory(profile.contract, (site,), expected_revision=0,
        actor="Synthetic Editor", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Contract Lead", "Synthetic Contract Lead"),))
    draft = directory.apply_defaults(ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), ()))
    block = next(item for item in draft.blocks if item.key == "contact_matrix")
    labels = _contact_scope_labels(draft, block, 0, block.rows, has_primary=True)
    assert labels[0] == "This report only"
    assert labels[1].startswith("Reused for this site")
    assert directory.load_directory(profile.contract) == state
    altered = replace(block, rows=(block.rows[0], (*block.rows[1][:2], "Manual override", *block.rows[1][3:])))
    assert _contact_scope_labels(draft, altered, 0, altered.rows, has_primary=True) == ["This report only"] * 2
    removed = replace(block, source="This month", rows=block.rows[1:])
    assert directory.automatically_keep_directory_contact_edits(profile, block, removed, "Synthetic Editor") is None
    assert directory.load_directory(profile.contract) == state


def test_blank_new_contact_is_neither_counted_nor_exported_and_second_add_is_deliberate():
    app = vendor_app(())
    original = vendor_block(app)
    button(app, "Add vendor contact").click().run()
    assert not app.exception and vendor_block(app) == original
    assert not any(item.value == "No vendor contacts added" for item in app.caption)
    button(app, "Close editing").click().run()
    assert vendor_block(app) == original
    button(app, "Add vendor contact").click().run()
    next(item for item in app.text_input if item.label == "Vendor").set_value("New vendor")
    button(app, "Close editing").click().run()
    assert len(vendor_block(app).rows) == 1
    app.run()
    assert len(vendor_block(app).rows) == 1
    assert not any(item.label == "Close editing" for item in app.button)


def test_native_site_contact_correction_is_reused_but_remove_and_undo_do_not_delete_standing(monkeypatch, tmp_path):
    from test_monthly_report_organization_ui import SCRIPT
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    site = directory.DirectorySite('directory-north', profile.facilities[0].title,
        contacts=(directory.DirectoryContact('Operator', 'Synthetic Operator', '202-555-0100'),))
    original = directory.save_directory(profile.contract, (site,), expected_revision=0,
        actor='Synthetic Editor', confirmed=True)
    saved_draft = directory.apply_defaults(ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(), ()))
    block = next(item for item in saved_draft.blocks if item.key == 'contact_matrix')
    script = SCRIPT.replace('st.session_state.setdefault("original", original)',
        'original["contact_matrix"] = st.session_state["seed_contact"]\nst.session_state.setdefault("original", original)')
    script = script.replace('draft = replace(synthetic_draft',
        'from app.monthly_report_directory import CONTACT_SPEC\nspecs["contact_matrix"] = CONTACT_SPEC\ndraft = replace(synthetic_draft')
    app = AppTest.from_string(script)
    app.session_state['seed_contact'] = block
    app.run()
    assert not app.exception
    button(app, 'Edit contact').click().run()
    assert any(item.value.startswith('Reused for this site') for item in app.caption)
    assert directory.load_directory(profile.contract) == original
    next(item for item in app.text_input if item.label == 'Phone').set_value('202-555-0199')
    button(app, 'Close editing').click().run()
    assert not app.exception
    corrected = directory.load_directory(profile.contract)
    assert corrected.revision == original.revision + 1
    assert corrected.sites[0].contacts[0].phone == '202-555-0199'
    assert directory.load_directory(profile.contract, original.revision) == original
    button(app, 'Remove contact').click().run()
    assert not app.exception and not app.session_state['blocks']['contact_matrix'].rows
    assert directory.load_directory(profile.contract) == corrected
    button(app, 'Undo remove contact').click().run()
    assert not app.exception
    assert app.session_state['blocks']['contact_matrix'].rows[0][3] == '202-555-0199'
    assert directory.load_directory(profile.contract) == corrected
