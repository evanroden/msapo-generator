"""Page preview states remain concise and never disguise stale output."""
from pathlib import Path

from app.monthly_report_section_preview_ui import _preview_status


def test_one_primary_preview_state_with_real_page_count():
    assert _preview_status() == ""
    assert _preview_status(pending=True) == "Updating preview…"
    assert _preview_status(pages=1) == "Current · 1 page"
    assert _preview_status(pages=3) == "Current · 3 pages"
    assert _preview_status(pages=2, pending=True) == "Current · 2 pages"
    assert _preview_status(failed=True) == "Preview unavailable — retry"


def test_older_preview_explicitly_disclaims_new_edits():
    waiting = _preview_status(stale=True, pending=True)
    stopped = _preview_status(stale=True, pending=False)
    assert waiting.startswith("Showing older preview")
    assert "latest changes not shown" in waiting and "Updating" in waiting
    assert "latest changes not shown" in stopped and "Retry preview" in stopped
    assert "Current" not in waiting + stopped
    assert _preview_status(stale=True, failed=True) == "Preview unavailable — retry"


def test_preview_headings_do_not_duplicate_shareable_chain_anchors():
    source = (Path(__file__).resolve().parents[1] /
              "app" / "monthly_report_section_preview_ui.py").read_text()
    assert "st.caption('Preview')" in source
    assert "st.subheader('Preview'" not in source
    assert "st.subheader('Section preview')" not in source
    assert "Updates automatically while in view." not in source
    renderer = (Path(__file__).resolve().parents[1] /
                "app" / "monthly_report_preview_view.py").read_text()
    assert "'Draft layout'" not in renderer
    assert "'Page ' + (index + 1) + ' of ' + sizes.length" in renderer
    assert "data.status || ''" in renderer
