"""Concise site scope and onsite/vendor section copy retain real report semantics."""

from app.monthly_report_section_help import section_help
from test_monthly_report_ui import monthly


def test_site_selection_copy_keeps_one_and_two_site_identities(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    assert not app.exception
    assert any(node.value == "Sites in this report" for node in app.get("subheader"))
    assert any(node.value == "Select one or more sites." for node in app.get("caption"))
    assert any("Selecting several sites combines them in one report." in node.value
               for node in app.get("caption"))
    site_boxes = [item for item in app.checkbox if item.key.startswith("report_sites_")]
    assert len(site_boxes) >= 2
    first, second = (site_boxes[0].label, site_boxes[1].label)

    next(item for item in app.checkbox if item.label == first).check().run()
    assert not app.exception
    assert any(node.value == f"Sites selected (1): {first}"
               for node in app.get("caption"))

    next(item for item in app.checkbox if item.label == second).check().run()
    assert not app.exception
    assert any(node.value == f"Sites selected (2): {first}; {second}"
               for node in app.get("caption"))


def test_onsite_boundary_and_direct_vendor_activity_link_remain(monkeypatch, tmp_path):
    help_text = section_help("maintenance").guidance
    assert "ENFRA onsite service calls only." in help_text
    assert "[Monthly Activity Summary](#report-section-activity)" in help_text
    assert "not applicable" not in help_text.casefold()

    app = monthly(monkeypatch, tmp_path, saved=True)
    assert not app.exception
    assert not any("This part remains available for earlier report versions."
                   in node.value for node in app.get("caption"))
    # This is presentation-only: existing section routing is exercised by
    # test_monthly_report_section_uploads and final monthly export regressions.
