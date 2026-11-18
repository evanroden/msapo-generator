"""A30 synthetic 50-file source form mount and unsent-edit regression.

The eager comparator runs the previous full-source form strategy through the
current renderer. Wall/CPU timing is descriptive, never a CI threshold or a
production/served-browser benchmark. All sources are generated in temporary
test storage. No paid reading, external files or client data.
"""
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import resource
from time import perf_counter, process_time

import pymupdf as fitz
from streamlit.testing.v1 import AppTest

from app import monthly_report_source_manager_ui as manager
from app.monthly_report_model import ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles
from app.monthly_report_sources import ingest, source_bytes
from test_monthly_report_upload_ui import button, select


APP = """
import streamlit as st
from dataclasses import replace
from app.monthly_report_source_manager_ui import render_guided_source_manager

def field(key, initial):
    st.session_state.setdefault(key, initial)
    return key

# The ordinary guided page resets this one-render ownership map.
st.session_state["_monthly_source_detail_forms"] = {}
st.session_state["_monthly_source_details_managed"] = True
draft = st.session_state["current"]
draft, blocks = render_guided_source_manager(
    draft, {block.key: block for block in draft.blocks}, "a30", field,
    lambda report, blocks, additions, specs, prefix: (report, blocks),
    lambda prefix, sources: sources,
)
st.session_state["current"] = replace(draft, blocks=tuple(blocks.values()))
# Like the guided page, apply a manager close or source switch with the one
# post-commit refresh rerun (monthly_report_guided._refresh_period_editors_after_commit).
if st.session_state.pop("a30_period_editor_refresh", False):
    st.rerun()
"""


def fifty_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    contents, originals = [], {}
    for number in range(50):
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((48, 80), "TEST ONLY — all records invented")
            page.insert_text((48, 112), "Demo North — September 2026")
            page.insert_text((48, 144), f"Synthetic utility review {number:02d}, no prices")
            raw = pdf.tobytes()
        name = f"synthetic-source-{number:02d}.pdf"
        content, _ = ingest(profile, name, raw)
        contents.append(content)
        originals[content.source.id] = raw
    assert len({content.source.id for content in contents}) == 50
    report = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic A30 reviewer",
        (SectionSpec("scorecards", "3", "Scorecards", ()),), (),
        sources=tuple(content.source for content in contents))
    return report, tuple(contents), originals


def app_for(report, contents):
    app = AppTest.from_string(APP, default_timeout=40)
    app.session_state["current"] = report
    app.session_state["a30_evidence"] = contents
    return app


def mounted(app):
    return sum(widget.label in ("Source date", "Source date (YYYY-MM-DD)")
               for widget in (*app.date_input, *app.text_input))


def route_widgets(app):
    return [widget for widget in app.selectbox
            if widget.label.startswith("Report section for ")]


def native_widgets(app):
    """Actual native widget count by kind (read-only AppTest inventory)."""
    kinds = ("date_input", "text_input", "text_area", "selectbox",
             "multiselect", "button", "checkbox", "file_uploader")
    return {kind: len(app.get(kind) if kind == "file_uploader" else getattr(app, kind))
            for kind in kinds}


def timed(action):
    wall, cpu = perf_counter(), process_time()
    action()
    return {"wall_s": round(perf_counter() - wall, 4),
            "cpu_s": round(process_time() - cpu, 4),
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def test_fifty_cold_warm_eager_comparator_and_lazy_widget_budget(monkeypatch, tmp_path):
    report, contents, originals = fifty_sources(tmp_path, monkeypatch)
    original = manager._resident_source_forms
    modes = {}
    # This is the pre-change eager metadata loop, simulated within the
    # same exact-source renderer. The old route-selectbox loop is NOT timed.
    for eager in (True, False):
        with monkeypatch.context() as patch:
            if eager:
                patch.setattr(manager, "_resident_source_forms",
                    lambda prefix, available, requested, selected, opened, needed=(): tuple(available))
            else:
                patch.setattr(manager, "_resident_source_forms", original)
            app = app_for(report, contents)
            cold = timed(app.run)
            assert not app.exception
            closed_widgets = mounted(app)
            closed_inventory = native_widgets(app)
            open_time = timed(lambda: button(app, "Manage source files").click().run())
            assert not app.exception
            open_widgets = mounted(app)
            open_inventory = native_widgets(app)
            warm = timed(app.run)
            assert not app.exception
            assert mounted(app) == open_widgets
            modes["eager" if eager else "lazy"] = {
                "cold": cold, "open": open_time, "warm": warm,
                "closed_metadata_inputs": closed_widgets,
                "open_metadata_inputs": open_widgets,
                "closed_native_widgets": closed_inventory,
                "open_native_widgets": open_inventory,
                "warm_native_widgets": native_widgets(app),
                "open_route_selectboxes": len(route_widgets(app)),
            }
    assert modes["eager"]["closed_metadata_inputs"] == 50
    assert modes["eager"]["open_metadata_inputs"] == 50
    assert modes["lazy"]["closed_metadata_inputs"] == 0
    assert modes["lazy"]["open_metadata_inputs"] == 1
    assert modes["lazy"]["open_route_selectboxes"] == 1
    for item in contents:
        assert source_bytes(report.profile, item.source) == originals[item.source.id]
    target = os.environ.get("INDEPENDENT_OUTPUT")
    if target:
        output = Path(target)
        output.mkdir(parents=True, exist_ok=True)
        (output / "a30-source-mount.json").write_text(json.dumps({
            "fixture": "50 one-page distinct synthetic PDFs",
            "comparison": "same renderer; eager metadata mount override versus lazy source forms",
            "main_reference": "f0af99567223aea3375f60e671450048be2bf0a0",
            "not_measured": ["main commit full-route widget timing", "live browser first paint",
                             "512 MiB / 0.5 CPU cgroup", "actual client documents"],
            "measurements": modes,
        }, indent=2) + "\n")


def test_fifty_switch_pending_unsent_form_save_close_reopen_and_route_receipts(monkeypatch, tmp_path):
    report, contents, originals = fifty_sources(tmp_path, monkeypatch)
    app = app_for(report, contents).run()
    assert not app.exception
    assert mounted(app) == 0
    button(app, "Manage source files").click().run()
    assert not app.exception
    first, last = contents[0].source, contents[-1].source
    assert mounted(app) == 1
    first_widget = next(w for w in app.date_input if first.id in w.key)
    identity = first_widget.id
    first_widget.set_value(date(2026, 9, 21))  # Unsubmitted browser form.
    active_route = route_widgets(app)
    assert len(active_route) == 1 and first.filename in active_route[0].label
    active_route[0].set_value("utility_analysis").run()
    # The native form still has an unsent value, independent of the route.
    assert next(w for w in app.date_input if first.id in w.key).value == date(2026, 9, 21)
    select(app, "File to review").set_value(last.id).run()
    assert not app.exception
    assert mounted(app) == 2
    assert next(w for w in app.date_input if first.id in w.key).id == identity
    assert app.session_state["current"].sources[0].service_date == first.service_date
    # The destination and page editor deliberately follow the active source
    # only after capturing the previous source's delivered native widgets.
    app.run()
    second_route = route_widgets(app)
    assert len(second_route) == 1 and last.filename in second_route[0].label
    second_route[0].set_value("mbcx_report").run()
    last_widget = next(w for w in app.date_input if last.id in w.key)
    last_widget.set_value(date(2026, 9, 22))
    next(b for b in app.button if b.label == "Use these source details" and last.id in b.key).click().run()
    assert not app.exception
    assert app.session_state["current"].sources[-1].service_date == "2026-09-22"
    assert app.session_state["current"].sources[0].service_date == first.service_date
    select(app, "File to review").set_value(first.id).run()
    app.run()
    assert next(w for w in app.date_input if first.id in w.key).value == date(2026, 9, 21)
    assert next(w for w in app.date_input if first.id in w.key).id == identity
    assert route_widgets(app)[0].value == "utility_analysis"
    routes = app.session_state["a30_evidence_destination_route_values"]
    assert routes["a30_evidence_destination_" + first.id + "_" + first.classification] == "utility_analysis"
    assert routes["a30_evidence_destination_" + last.id + "_" + last.classification] == "mbcx_report"
    button(app, "Done with source files").click().run()
    assert not app.exception
    assert mounted(app) == 2  # Done hides but never retires unsubmitted forms.
    button(app, "Manage source files").click().run()
    assert not app.exception
    assert next(w for w in app.date_input if first.id in w.key).value == date(2026, 9, 21)
    next(b for b in app.button if b.label == "Use these source details" and first.id in b.key).click().run()
    assert not app.exception
    assert app.session_state["current"].sources[0].service_date == "2026-09-21"
    assert app.session_state["current"].sources[-1].service_date == "2026-09-22"
    app.run()  # Warm rerun cannot undo either accepted native correction.
    assert app.session_state["current"].sources[0].service_date == "2026-09-21"
    assert all(source_bytes(report.profile, item.source) == originals[item.source.id]
               for item in contents)


def test_removed_form_is_retired_without_touching_other_sources(monkeypatch, tmp_path):
    report, contents, _ = fifty_sources(tmp_path, monkeypatch)
    app = app_for(report, contents).run()
    button(app, "Manage source files").click().run()
    old = contents[0].source
    other = contents[1].source
    select(app, "File to review").set_value(other.id).run()
    assert mounted(app) == 2
    app.session_state["current"] = replace(app.session_state["current"],
        sources=tuple(s for s in report.sources if s.id != old.id))
    app.session_state["a30_evidence"] = tuple(c for c in contents if c.source.id != old.id)
    app.run()
    assert not app.exception
    assert all(old.id not in w.key for w in app.date_input)
    assert any(other.id in w.key for w in app.date_input)
    assert old.id not in app.session_state["a30_source_resident_forms"]
    assert other.id in app.session_state["a30_source_resident_forms"]


def test_rejects_missing_or_unsupported_synthetic_source_without_spoofing_a_form(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with pytest.raises(ValueError, match="empty"):
        ingest(profile, "empty.pdf", b"")
    with pytest.raises(ValueError, match="Unsupported"):
        ingest(profile, "malformed.exe", b"not a source")
