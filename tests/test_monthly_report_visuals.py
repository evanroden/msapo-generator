from dataclasses import asdict, replace
from io import BytesIO
from zipfile import ZipFile

from PIL import Image
import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx, outline
from app.monthly_report_library import block_from_dict
from app.monthly_report_model import (
    OrgChartNode,
    ResolvedBlock,
    BlockSpec,
    ReportPeriod,
    ReportTable,
    Facility,
    synthetic_draft,
    synthetic_profiles,
)
from app.monthly_report_visuals import contact_positions, validate_org, org_groups, org_page, photo_page
from test_monthly_report_ui import monthly, step, choose_report


def nodes():
    return (
        OrgChartNode("lead", "Synthetic Lead", "Asset manager"),
        OrgChartNode(
            "tech", "Synthetic Technician", "Operations", "lead", "Example campus"
        ),
        OrgChartNode("specialist", "Synthetic Specialist", "Controls", "lead"),
    )


def draft_for(block, kind="image_page"):
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    return replace(
        draft,
        blocks=(block,),
        sections=(
            replace(draft.sections[0], blocks=(BlockSpec(block.key, kind, True),)),
        ),
    )


def test_chart_structure_and_prices_cannot_slip_through_as_picture_text():
    with pytest.raises(ValueError, match="loop"):
        validate_org(
            (
                OrgChartNode("a", role="Lead", reports_to="b"),
                OrgChartNode("b", role="Staff", reports_to="a"),
            )
        )
    with pytest.raises(ValueError, match="existing manager"):
        validate_org((OrgChartNode("a", role="Lead", reports_to="missing"),))
    block = ResolvedBlock(
        "org_chart", "This month", org_nodes=(OrgChartNode("a", role="Fee $150"),)
    )
    assert any(c.code == "pricing" for c in preflight(draft_for(block)))
    with pytest.raises(ValueError, match="pricing"):
        assemble_docx(draft_for(block))
    from app.monthly_report_setup import merge_blocks

    with pytest.raises(ValueError, match="different org chart"):
        merge_blocks(
            block,
            ResolvedBlock("org_chart", "Last month", asset_hashes=("replacement.png",)),
        )


def test_chart_persistence_and_large_teams_remain_readable():
    block = ResolvedBlock("org_chart", "This month", org_nodes=nodes())
    from app.monthly_report_asset_review import normalize_asset_reviews
    assert block_from_dict(asdict(block)) == normalize_asset_reviews(block)
    assert block_from_dict({"key": "org_chart", "source": "Library"}).org_nodes == ()
    large = (
        nodes()[0],
        *(
            OrgChartNode(f"staff-{n}", f"Synthetic Staff {n}", "Technician", "lead")
            for n in range(13)
        ),
    )
    groups = org_groups(large)
    assert len(groups) == 4
    assert {n.key for group in groups for n in group} == {n.key for n in large}
    for n in range(len(groups)):
        with Image.open(BytesIO(org_page(large, n))) as page:
            assert page.size == (1400, 1540)


def test_contact_chart_positions_are_scoped_explicit_and_do_not_infer_managers():
    from app.monthly_report_directory import CONTACT_SPEC
    block = ResolvedBlock('contact_matrix', 'This month', rows=(
        ('Synthetic Site', 'Manager', 'Synthetic Lead', '202-555-0100', 'lead@example.invalid'),
        ('Synthetic Site', 'Technician', 'Synthetic Worker', '', ''),
    ), extra_tables=(
        ReportTable(('Name', 'Role', 'Site'), (('Synthetic Lead', 'Manager', 'Synthetic Site'),)),
        ReportTable(('Person and telephone', 'Details'), (('Unmapped', 'Do not guess'),)),
        ReportTable(('Name', 'Contact name'), (('Ambiguous', 'Do not guess'),)),
    ))
    draft = draft_for(block, 'table')
    draft = replace(draft, sections=(replace(draft.sections[0], blocks=(CONTACT_SPEC,)),),
                    blocks=(block, ResolvedBlock('subcontractor_matrix', 'This month', rows=(('Other vendor',),))))
    positions = contact_positions(draft)
    assert [(n.name, n.role, n.team, n.reports_to) for n in positions] == [
        ('Synthetic Lead', 'Manager', 'Synthetic Site', ''),
        ('Synthetic Worker', 'Technician', 'Synthetic Site', ''),
    ]
    assert '202-555' not in str(positions) and 'example.invalid' not in str(positions)
    assert contact_positions(replace(draft, blocks=(replace(block, source='Omit'),))) == ()
    assert contact_positions(replace(draft, sections=(replace(draft.sections[0], included=False),))) == ()
    changed = replace(block, rows=tuple(reversed(block.rows)))
    assert {n.key for n in contact_positions(replace(draft, blocks=(changed,)))} == {n.key for n in positions}


def test_chart_contact_choice_is_bounded_without_truncating_people():
    rows = tuple((f'Synthetic Person {n}',) for n in range(61))
    block = ResolvedBlock('contact_matrix', 'This month', extra_tables=(ReportTable(('Name',), rows),))
    choices = contact_positions(draft_for(block, 'table'))
    assert len(choices) == 61  # Operator selects a subset; no silent first-60 crop.
    with pytest.raises(ValueError, match='60'):
        validate_org(choices)
    block = replace(block, extra_tables=(ReportTable(('Name',), (('S' * 101,),)),))
    assert len(contact_positions(draft_for(block, 'table'))[0].name) == 101


def test_reviewed_directory_contacts_can_seed_chart_without_replacing_it_silently(monkeypatch, tmp_path):
    from app import monthly_report_library as library, monthly_report_directory as directory
    from app.contracts import RRH_CONTRACT
    from app.monthly_report_start import design_seed, save_design_start
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    sites = (
        directory.DirectorySite('directory-north', 'Synthetic North', contacts=(
            directory.DirectoryContact('Asset manager', 'Synthetic Lead', email='lead@example.invalid'),
            directory.DirectoryContact('Technician', 'Synthetic Worker'),
        )),
        directory.DirectorySite('directory-south', 'Synthetic South', contacts=(directory.DirectoryContact('Manager', 'Other Site Person'),)),
    )
    directory.save_directory(RRH_CONTRACT, sites, expected_revision=0, actor='Synthetic Editor', confirmed=True)
    profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, facilities=(Facility('existing-north', 'Synthetic North'),))
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), 'Synthetic Editor')
    raw = BytesIO()
    Image.new('RGB', (100, 80), '#123456').save(raw, 'PNG')
    ref = library.asset_reference(raw.getvalue(), 'png')
    draft = replace(draft, blocks=tuple(ResolvedBlock('org_chart', 'Replace once', asset_hashes=(ref,)) if b.key == 'org_chart' else b for b in draft.blocks))
    save_design_start(draft, {ref: raw.getvalue()}, actor='Synthetic Editor', confirmed=True)
    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, 'Synthetic North')
    next(w for w in app.text_input if w.label == 'Prepared by').set_value('Synthetic Current Editor').run()
    step(app, 3)
    assert any(w.label == 'Contract and site directory' for w in app.expander)
    assert not any(w.label.startswith('Directory site for ') for w in app.selectbox)
    current = next(value for key, value in app.session_state.filtered_state.items()
                   if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value, 'blocks'))
    contacts = next(block for block in current.blocks if block.key == 'contact_matrix')
    assert len(contacts.rows) == 2 and not any('Other Site' in str(row) for row in contacts.rows)
    assert next(block for block in current.blocks if block.key == 'org_chart').asset_hashes == (ref,)
    next(b for b in app.button if b.label == 'Change team chart').click().run()
    choices = next(w for w in app.multiselect if w.label == 'People to include in the org chart')
    assert len(choices.options) == 2 and not any('Other Site' in str(v) for v in choices.options)
    assert next(b for b in app.button if b.label == 'Start an editable org chart').disabled
    selected = choices.value[:1]
    choices.set_value(selected).run()
    next(c for c in app.checkbox if c.label == 'Replace this report’s uploaded chart with the editable chart').check().run()
    next(b for b in app.button if b.label == 'Start an editable org chart').click().run()
    assert not app.exception
    assert next(w for w in app.text_input if w.label == 'Name' and '_org_person_' in w.key).value == 'Synthetic Lead'
    assert next(w for w in app.selectbox if w.label == 'Reports to').value == ''
    step(app, 2)
    step(app, 3)
    next(b for b in app.button if b.label == 'Save progress').click().run()
    assert not app.exception
    saved = library.load_snapshot(RRH_CONTRACT, profile.key, ReportPeriod(2026, 9)).draft
    chart = next(b for b in saved.blocks if b.key == 'org_chart')
    assert len(chart.org_nodes) == 1 and chart.org_nodes[0].name == 'Synthetic Lead' and not chart.asset_hashes
    assert library.read_asset(RRH_CONTRACT, profile.key, ref) == raw.getvalue()  # Original still recoverable.
    assert len(next(b for b in saved.blocks if b.key == 'contact_matrix').rows) == 2
    assert saved.profile.facilities == profile.facilities


def test_preview_pages_are_the_images_embedded_in_deterministic_docx():
    block = ResolvedBlock("org_chart", "This month", org_nodes=nodes())
    draft = draft_for(block)
    first = assemble_docx(draft)
    assert first == assemble_docx(draft)
    with ZipFile(BytesIO(first)) as zip:
        assert org_page(nodes()) in [
            zip.read(n) for n in zip.namelist() if n.startswith("word/media/")
        ]
    photo = BytesIO()
    Image.new("RGB", (300, 100), "#123456").save(photo, "PNG")
    block = ResolvedBlock(
        "improvements",
        "This month",
        asset_hashes=tuple(f"photo{n}.png" for n in range(7)),
        asset_captions=tuple(f"Synthetic work item {n}" for n in range(7)),
        photos_per_page=6,
    )
    block = replace(block, client_reviewed_fingerprint=block.fingerprint)
    loader = lambda ref: photo.getvalue()
    draft = draft_for(block, "image_grid")
    assert outline(draft)[0][2] == 3  # divider plus two photo pages
    docx = assemble_docx(draft, asset_loader=loader)
    with ZipFile(BytesIO(docx)) as zip:
        images = [zip.read(n) for n in zip.namelist() if n.startswith("word/media/")]
        assert (
            photo_page(block, loader, 0) in images
            and photo_page(block, loader, 1) in images
        )
    assert docx == assemble_docx(draft, asset_loader=loader)
    from app.monthly_report_asset_review import normalize_asset_reviews
    assert block_from_dict(asdict(block)) == normalize_asset_reviews(block)


def test_org_and_contacts_are_editable_and_survive_navigation(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == "Site name").set_value(
        "Synthetic Editable Site"
    ).run()
    next(w for w in app.button if w.key and "report_start_card_use-the-general" in w.key).click().run()
    next(w for w in app.text_input if w.label == "Your name").set_value(
        "Synthetic Editor"
    ).run()
    next(b for b in app.button if b.label == "Start this report").click().run()
    step(app, 3)
    next(b for b in app.button if b.label == "Change team chart").click().run()
    next(
        b for b in app.button if b.label == "Start an editable org chart"
    ).click().run()
    next(w for w in app.text_input if w.label == "Name").set_value(
        "Synthetic Lead"
    ).run()
    next(b for b in app.button if b.label == "Add a person or position").click().run()
    names = [w for w in app.text_input if w.label == "Name"]
    names[1].set_value("Synthetic Technician").run()
    roles = [w for w in app.text_input if w.label == "Role / position"]
    roles[1].set_value("Technician").run()
    [w for w in app.selectbox if w.label == "Reports to"][1].set_value(
        "position-1"
    ).run()
    next(b for b in app.button if b.label == "Change facility contacts").click().run()
    next(b for b in app.button if b.label == "Create editable contacts").click().run()
    next(w for w in app.text_input if w.label == "Email").set_value(
        "operations@example.invalid"
    ).run()
    # Removing a row must not restore the deleted contact from widget memory.
    next(
        b for b in app.button if b.label == "Add contact" and "contact_matrix" in b.key
    ).click().run()
    emails = [w for w in app.text_input if w.label == "Email"]
    emails[1].set_value("retained@example.invalid").run()
    next(b for b in app.button if b.label == "Remove contact").click().run()
    assert (
        next(w for w in app.text_input if w.label == "Email").value
        == "retained@example.invalid"
    )
    assert not app.exception
    step(app, 2)
    step(app, 3)
    next(b for b in app.button if b.label == "Change team chart").click().run()
    assert [
        w.value for w in app.text_input if w.label == "Name" and "_org_person_" in w.key
    ] == ["Synthetic Lead", "Synthetic Technician"]
    next(b for b in app.button if b.label == "Change facility contacts").click().run()
    assert (
        next(w for w in app.text_input if w.label == "Email").value
        == "retained@example.invalid"
    )
    next(b for b in app.button if b.label == "Save progress").click().run()
    assert not app.exception
    from app import monthly_report_library as library
    from app.contracts import RRH_CONTRACT

    profile = library.list_profiles(RRH_CONTRACT)[0]
    saved = library.load_snapshot(
        RRH_CONTRACT, profile.key, ReportPeriod(2026, 9)
    ).draft
    chart = next(b for b in saved.blocks if b.key == "org_chart")
    assert chart.org_nodes[1].reports_to == "position-1"
    assert any("retained@example.invalid" in str(b.extra_tables) for b in saved.blocks)


def test_photo_upload_caption_layout_and_removal_survive_steps(monkeypatch, tmp_path):
    import streamlit as st

    uploads = []
    for n, color in enumerate(("red", "blue", "green")):
        raw = BytesIO()
        Image.new("RGB", (100, 80), color).save(raw, "PNG")
        raw.size, raw.name = len(raw.getvalue()), f"synthetic-{n}.png"
        uploads.append(raw)
    real = st.file_uploader
    monkeypatch.setattr(
        st,
        "file_uploader",
        lambda label, *a, **k: (
            uploads if label == "Progress photos" else real(label, *a, **k)
        ),
    )
    app = monthly(monkeypatch, tmp_path)
    step(app, 2)
    next(b for b in app.button if b.label == "Add these photos").click().run()
    assert not app.exception
    next(w for w in app.text_area if w.label == "Caption").set_value(
        "Synthetic inspection completed."
    ).run()
    next(w for w in app.select_slider if w.label == "Photos per page").set_value(
        3
    ).run()
    next(b for b in app.button if b.label == "Remove photo").click().run()
    assert not any(w.label == "Include this photo" for w in app.checkbox)
    assert len([b for b in app.button if b.label == "Remove photo"]) == 2
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.select_slider if w.label == "Photos per page").value == 3
    assert len([b for b in app.button if b.label == "Remove photo"]) == 2
    draft = next(
        v
        for k, v in app.session_state.filtered_state.items()
        if k.startswith("report_guided_") and k.endswith("_draft") and hasattr(v,"blocks")
    )
    photos = next(b for b in draft.blocks if b.key == "improvements")
    assert len(photos.asset_hashes) == 2 and photos.photos_per_page == 3
    assert any(c.code == "client_pages" for c in preflight(draft))
