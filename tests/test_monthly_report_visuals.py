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
    synthetic_draft,
    synthetic_profiles,
)
from app.monthly_report_visuals import validate_org, org_groups, org_page, photo_page
from test_monthly_report_ui import monthly, step


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
    assert block_from_dict(asdict(block)) == block
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
    assert block_from_dict(asdict(block)) == block


def test_org_and_contacts_are_editable_and_survive_navigation(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == "Site name").set_value(
        "Synthetic Editable Site"
    ).run()
    next(w for w in app.text_input if w.label == "Your name").set_value(
        "Synthetic Editor"
    ).run()
    next(
        w
        for w in app.checkbox
        if w.label == "Save this design for these sites so we can use it next month"
    ).check().run()
    next(b for b in app.button if b.label == "Start this report").click().run()
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
    assert [
        w.value for w in app.text_input if w.label == "Name" and "_org_person_" in w.key
    ] == ["Synthetic Lead", "Synthetic Technician"]
    assert (
        next(w for w in app.text_input if w.label == "Email").value
        == "retained@example.invalid"
    )
    next(
        w
        for w in app.checkbox
        if w.label == "Save this draft for others on this report to continue"
    ).check().run()
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
    next(w for w in app.checkbox if w.label == "Include this photo").uncheck().run()
    next(b for b in app.button if b.label == "Apply photo selection").click().run()
    assert len([w for w in app.checkbox if w.label == "Include this photo"]) == 2
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.select_slider if w.label == "Photos per page").value == 3
    assert len([w for w in app.checkbox if w.label == "Include this photo"]) == 2
    draft = next(
        v
        for k, v in app.session_state.filtered_state.items()
        if k.startswith("report_guided_") and k.endswith("_draft") and hasattr(v,"blocks")
    )
    photos = next(b for b in draft.blocks if b.key == "improvements")
    assert len(photos.asset_hashes) == 2 and photos.photos_per_page == 3
    assert any(c.code == "client_pages" for c in preflight(draft))
