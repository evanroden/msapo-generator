"""An accepted Water page action advances only its own source-form revision."""
from dataclasses import replace
from datetime import date

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from test_water_caption_done import loaded_water, current, assert_durable
from test_monthly_report_section_uploads import button


@pytest.mark.parametrize("action", ["Include page", "Exclude page"])
@pytest.mark.parametrize("external_correction", [False, True])
def test_page_action_then_immediate_source_submit_is_owned(
        monkeypatch, tmp_path, action, external_correction):
    app = loaded_water(monkeypatch, tmp_path)
    before = current(app)
    original = sources.source_bytes(before.profile, before.sources[0])
    shared = library.load_snapshot(before.profile.contract, before.profile.key, before.period)
    button(app, "Report pages").click().run()
    next(w for w in app.text_input if w.label == "Page caption").set_value(
        "Concise synthetic inspection caption.").run()
    button(app, action).click().run()
    assert not app.exception
    source = current(app).sources[0]
    page_state = (source.selected_pages, source.captions,
                  source.client_page_reviews, source.client_page_exclusions)
    # No unrelated rerun between this owned page action and the form submit.
    # Such a rerun used to hide the false "corrected elsewhere" rejection.
    next(w for w in app.date_input if source.id in w.key).set_value(date(2026, 9, 13))
    next(w for w in app.selectbox if w.label == "Source facility" and source.id in w.key).set_value(
        before.profile.facilities[0].key)
    if external_correction:
        prefix = next(k[:-6] for k, v in app.session_state.filtered_state.items()
                      if k.startswith("report_guided_") and k.endswith("_draft") and v == current(app))
        # A real canonical source correction arriving after the displayed form
        # must still invalidate its stale buffered submission.
        newer = replace(source, service_date="2026-09-22")
        app.session_state[prefix + "_evidence"] = tuple(
            replace(c, source=newer) if c.source.id == source.id else c
            for c in app.session_state[prefix + "_evidence"])
    next(w for w in app.button if w.label == "Use these source details" and source.id in w.key).click().run()
    assert not app.exception
    updated = current(app).sources[0]
    assert updated.service_date == ("2026-09-22" if external_correction else "2026-09-13")
    if external_correction:
        assert updated.facility == source.facility
        assert any("corrected elsewhere" in item.value for item in app.info)
    else:
        assert updated.facility == before.profile.facilities[0].key
        assert not any("corrected elsewhere" in item.value for item in app.info)
    assert (updated.selected_pages, updated.captions,
            updated.client_page_reviews, updated.client_page_exclusions) == page_state
    assert sources.source_bytes(before.profile, updated) == original
    assert library.load_snapshot(before.profile.contract, before.profile.key, before.period) == shared
    assert_durable(app)
    app.run()
    assert current(app).sources[0] == updated
    assert_durable(app)
