"""Hidden shared fixtures, followed by the ordinary isolated report workflow.

There is deliberately no login. Uploaded originals, metadata and downloads are
available to anyone who reaches this testing area. The fixture library is
shared; editable report runs remain browser-scoped and generation-bound.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import memory
from app import monthly_report_fixture_runs as runs
from app import monthly_report_library as report_library
from app import monthly_report_testing as testing
from app.monthly_report_editor import _key
from app.monthly_report_fixture_vault import ExpectedSection, FixtureMetadata, ReportIdentity
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_shared_fixtures import SharedFixtureLibrary
from app.monthly_report_start import report_key


_PREFIX = "_shared_fixture_"
_LIMIT = 32 * 1024 * 1024


def _queue_upload():
    if not st.session_state.get(_PREFIX + "pending"):
        st.session_state[_PREFIX + "pending"] = {"action": "upload", "id": uuid4().hex}


def _queue_source_bundle_upload():
    """A source archive does not create or reset a report run."""
    if not st.session_state.get(_PREFIX + "pending"):
        st.session_state[_PREFIX + "pending"] = {"action": "source_bundle", "id": uuid4().hex}


def _queue_evidence_bundle_upload():
    """Synthetic run evidence stays separate from originals and report runs."""
    if not st.session_state.get(_PREFIX + "pending"):
        st.session_state[_PREFIX + "pending"] = {"action": "evidence_bundle", "id": uuid4().hex}


def _queue_run(fixture_id, generation):
    if not st.session_state.get(_PREFIX + "pending"):
        st.session_state[_PREFIX + "pending"] = {
            "action": "start" if fixture_id else "reset", "fixture_id": fixture_id,
            "id": uuid4().hex, "generation": generation, "phase": "reset",
        }


def _expectations(text: str) -> tuple[ExpectedSection, ...]:
    sections = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = tuple(part.strip() for part in line.split("|", 2))
        if len(parts) != 3 or not all(parts) or parts[1] not in ("include", "exclude"):
            raise ValueError("Each expectation needs: section | include or exclude | fact.")
        item = sections.setdefault(parts[0], {"include": [], "exclude": []})
        item[parts[1]].append(parts[2])
    if not sections:
        raise ValueError("Enter at least one independent expected result.")
    return tuple(ExpectedSection(section, tuple(values["include"]), tuple(values["exclude"]))
                 for section, values in sections.items())


def _named_sites(contract: str, text: str) -> tuple[Facility, ...]:
    from app.monthly_report_section_ui import _site_options
    # This executes inside the isolated context. Known configured identities
    # may match explicitly entered titles/aliases; no live directory is read.
    available = _site_options(contract)
    selected = []
    normalize = lambda value: " ".join(value.casefold().split())
    for title in (part.strip() for part in text.split(";")):
        if not title:
            continue
        matches = [site for site in available if normalize(title) in {
            normalize(name) for name in (site.title, *site.aliases)}]
        if len(matches) > 1:
            raise ValueError("A site name matches more than one configured site. Use its full site title.")
        selected.append(matches[0] if matches else Facility(_key(title), title))
    if not selected or len({site.key for site in selected}) != len(selected):
        raise ValueError("Enter one distinct site name per semicolon-separated item.")
    # Preserve the same alias/membership validation as the ordinary selection.
    ReportProfile(contract, report_key(selected), "Selected sites", tuple(selected),
                  "individual" if len(selected) == 1 else "multi_site")
    return tuple(selected)


def target_profile(metadata: FixtureMetadata) -> ReportProfile:
    from app.monthly_report_section_ui import _site_options
    target = metadata.target
    known = {site.key: site for site in _site_options(target.contract)}
    titles = target.site_titles or target.sites
    facilities = []
    for key, title in zip(target.sites, titles):
        site = known.get(key) or Facility(key, title)
        if key not in known and _key(title) != key:
            raise ValueError("This older fixture has an unmatched site key. Upload it with explicitly named target sites.")
        facilities.append(site)
    chosen = tuple(facilities)
    return ReportProfile(target.contract, report_key(chosen), " / ".join(site.title for site in chosen),
                         chosen, "individual" if len(chosen) == 1 else "multi_site")


def _upload_metadata() -> FixtureMetadata:
    value = lambda name: st.session_state.get(_PREFIX + "upload_" + name, "")
    contract = value("contract").strip()
    if not contract:
        raise ValueError("Enter the exact source and target contract.")
    source = _named_sites(contract, value("source_sites"))
    target = _named_sites(contract, value("target_sites"))
    return FixtureMetadata(
        friendly_name=value("name").strip(),
        source=ReportIdentity(contract, tuple(site.key for site in source), value("source_month").strip(),
                              tuple(site.title for site in source)),
        target=ReportIdentity(contract, tuple(site.key for site in target), value("target_month").strip(),
                              tuple(site.title for site in target)),
        scenario=value("scenario"), owner_expectations=value("notes").strip(),
        expected_content=_expectations(value("expectations")),
        confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        partial_file_confirmed=bool(value("partial")),
    )


def _clear_run_ui():
    from app.monthly_report_testing_ui import _clear_report_widgets
    _clear_report_widgets()
    for suffix in ("record", "staged", "initial_review_finished"):
        st.session_state.pop(_PREFIX + suffix, None)


def _seed_target(profile, period, *, force=False):
    from app.monthly_report_start_ui import site_choices
    def select(key, value):
        if force:
            st.session_state[key] = value
        else:
            st.session_state.setdefault(key, value)
    select("report_contract", profile.contract)
    select("report_change_contract", False)
    select("report_month_number", period.month)
    select("report_year", period.year)
    options = site_choices(profile.contract, report_library.list_profiles(profile.contract))
    chosen = {site.key for site in profile.facilities}
    prefix = "report_sites_" + _key(profile.contract)
    for site in options:
        select(prefix + "_" + site.key, site.key in chosen)
    known = {site.key for site in options}
    select(prefix + "_new_site", "; ".join(
        site.title for site in profile.facilities if site.key not in known))


def _target_matches(profile, period):
    """A scenario's lineage cannot keep its old label after a target change."""
    from app.monthly_report_start_ui import site_choices
    if (st.session_state.get("report_contract") != profile.contract
            or st.session_state.get("report_year") != period.year
            or st.session_state.get("report_month_number") != period.month):
        return False
    options = site_choices(profile.contract, report_library.list_profiles(profile.contract))
    prefix = "report_sites_" + _key(profile.contract)
    selected = [site.key for site in options if st.session_state.get(prefix + "_" + site.key, False)]
    selected.extend(_key(name.strip()) for name in st.session_state.get(prefix + "_new_site", "").split(";")
                    if name.strip())
    return sorted(selected) == sorted(site.key for site in profile.facilities)


def _process_pending(library, browser_token, live_storage_root):
    pending = st.session_state.get(_PREFIX + "pending")
    if not pending:
        return
    if pending["action"] == "template":
        try:
            from app.monthly_report_shared_templates_ui import save_pending
            save_pending(live_storage_root, pending["upload_key"])
        except (ValueError, OSError) as exc:
            st.session_state[_PREFIX + "error"] = "The report template was not saved: " + str(exc)
        finally:
            st.session_state.pop(_PREFIX + "pending", None)
        return
    if pending["action"] == "evidence_bundle":
        try:
            upload = st.session_state.get(_PREFIX + "evidence_bundle_file")
            if upload is None:
                raise ValueError("Choose the synthetic evidence ZIP archive.")
            if upload.size > 24 * 1024 * 1024:
                raise ValueError("Synthetic evidence exceeds the 24 MiB upload limit.")
            from app.monthly_report_shared_source_bundles import SharedSyntheticEvidenceBundles
            receipt = SharedSyntheticEvidenceBundles(Path(live_storage_root)).upload(upload.getvalue())
            st.session_state[_PREFIX + "evidence_bundle_receipt"] = receipt.bundle_id
        except (ValueError, OSError) as exc:
            st.session_state[_PREFIX + "error"] = "Synthetic evidence ZIP was not saved: " + str(exc)
        finally:
            st.session_state.pop(_PREFIX + "pending", None)
        return
    if pending["action"] == "source_bundle":
        try:
            upload = st.session_state.get(_PREFIX + "source_bundle_file")
            if upload is None:
                raise ValueError("Choose the original six-source ZIP archive.")
            if upload.size > 96 * 1024 * 1024:
                raise ValueError("This reference archive exceeds the 96 MiB upload limit.")
            from app.monthly_report_shared_source_bundles import SharedSourceBundles
            receipt = SharedSourceBundles(Path(live_storage_root)).upload(upload.getvalue())
            st.session_state[_PREFIX + "source_bundle_receipt"] = receipt.bundle_id
        except (ValueError, OSError) as exc:
            st.session_state[_PREFIX + "error"] = "The immutable source bundle was not saved: " + str(exc)
        finally:
            st.session_state.pop(_PREFIX + "pending", None)
        return
    if pending["action"] == "upload":
        try:
            upload = st.session_state.get(_PREFIX + "upload_file")
            if upload is None:
                raise ValueError("Choose a native Word report to upload.")
            if upload.size > _LIMIT:
                raise ValueError("The report exceeds the 32 MiB fixture limit.")
            metadata = _upload_metadata()
            receipt = library.upload(upload.getvalue(), metadata)
            st.session_state[_PREFIX + "upload_receipt"] = receipt.fixture_id
            st.session_state[_PREFIX + "selection"] = receipt.fixture_id
        except (ValueError, OSError) as exc:
            st.session_state[_PREFIX + "error"] = "Shared fixture upload was not completed: " + str(exc)
        finally:
            st.session_state.pop(_PREFIX + "pending", None)
        return
    # A delayed Start callback may belong to a different combobox selection.
    # Reject it BEFORE discarding this browser's current run or staging bytes.
    # The next rerun also checks this when a two-phase Start was interrupted.
    if (pending.get("action") == "start" and
            _PREFIX + "selection" in st.session_state and
            st.session_state[_PREFIX + "selection"] != pending.get("fixture_id")):
        st.session_state.pop(_PREFIX + "pending", None)
        if pending.get("phase") == "reset":
            message = "No report was reset or imported."
        else:
            message = "The earlier request already reset this test; no different fixture was imported."
        st.session_state[_PREFIX + "error"] = (
            "The selected shared fixture changed after Start was clicked. "
            + message + " Select the intended fixture and choose Start again.")
        return
    if pending["phase"] == "reset":
        if pending["generation"] != testing.generation():
            st.session_state.pop(_PREFIX + "pending", None)
            st.session_state[_PREFIX + "error"] = "This test changed after that action. Review the current test and try again."
            return
        try:
            from app.monthly_report_preview_store import STORE
            STORE.reset_scope()
            testing.reset(Path(live_storage_root))
        except (ValueError, OSError):
            st.session_state.pop(_PREFIX + "pending", None)
            st.error("The isolated reset could not be confirmed. Reload to inspect this test before retrying.")
            st.stop()
        _clear_run_ui()
        if pending["action"] == "start":
            # Bind the exact new generation now. Merely requiring a different
            # generation on the next rerun could revive this old Start action
            # after another tab intentionally resets the workspace again.
            try:
                with testing.isolated(browser_token):
                    memory._data_dir()
                    expected_generation = testing.generation()
            except (ValueError, OSError):
                st.session_state.pop(_PREFIX + "pending", None)
                st.error("The old test was reset, but a fresh workspace could not be opened. Reload to try again.")
                st.stop()
            st.session_state[_PREFIX + "pending"] = {
                **pending, "phase": "stage", "expected_generation": expected_generation,
            }
        else:
            st.session_state.pop(_PREFIX + "pending", None)
            st.session_state[_PREFIX + "reset_receipt"] = pending["id"]
        st.rerun()
    if pending["phase"] == "stage":
        try:
            if pending.get("expected_generation") != testing.generation():
                raise ValueError("This test was reset again after the fixture was selected. Choose Start fresh test again.")
            receipt = library.read(pending["fixture_id"]).receipt
            profile = target_profile(receipt.metadata)
            # Recover a completed atomic stage if a rerun interrupted only its
            # UI acknowledgment. Never overwrite another staged fixture.
            record = runs.read_run_fixture(library, browser_token)
            if record is not None:
                if record.lineage.fixture_id != receipt.fixture_id:
                    raise ValueError("The current run contains a different fixture; start a fresh test.")
                staged = runs.resume_fixture(record, profile)
            else:
                staged = runs.stage_fixture(library, receipt.fixture_id, browser_token, profile)
            _seed_target(staged.profile, staged.period)
            st.session_state[staged.setup_stage_key] = staged.stage
            st.session_state[_PREFIX + "staged"] = staged
            st.session_state[_PREFIX + "record"] = runs.RunFixture(staged.context, staged.lineage, staged.source_path)
            st.session_state[_PREFIX + "run_receipt"] = pending["id"]
        except (ValueError, OSError) as exc:
            st.session_state[_PREFIX + "error"] = "The isolated Starting report review could not open: " + str(exc)
        finally:
            st.session_state.pop(_PREFIX + "pending", None)


def _render_upload():
    with st.expander("Upload an actual report"):
        st.caption("One immutable original, shared with anyone who reaches this area. Confirm the identities below; filenames are not evidence.")
        with st.form(_PREFIX + "upload_form"):
            st.file_uploader("Original Word report", type=["docx"], max_upload_size=32, key=_PREFIX + "upload_file")
            st.text_input("Fixture name", key=_PREFIX + "upload_name")
            st.selectbox("Scenario", ("AUTH01", "AUTH02", "AUTH03"), key=_PREFIX + "upload_scenario",
                         format_func=lambda value: {"AUTH01": "Same sites, previous month", "AUTH02": "Different sites, same contract", "AUTH03": "Half-finished report, correct month"}[value])
            st.text_input("Exact contract", key=_PREFIX + "upload_contract")
            st.text_input("Source sites", key=_PREFIX + "upload_source_sites", help="Separate full site names with semicolons.")
            st.text_input("Source month (YYYY-MM)", key=_PREFIX + "upload_source_month")
            st.text_input("Target sites", key=_PREFIX + "upload_target_sites", help="Separate full site names with semicolons.")
            st.text_input("Target month (YYYY-MM)", key=_PREFIX + "upload_target_month")
            st.checkbox("For the partial-report scenario, I confirm this is the actual half-finished file", key=_PREFIX + "upload_partial")
            st.text_area("Scenario notes", key=_PREFIX + "upload_notes")
            st.text_area("Expected results", key=_PREFIX + "upload_expectations",
                         help="One independent expectation per line: section | include or exclude | fact. These are review notes, never extracted or prefilled content.",
                         placeholder="Organization | include | Correct site contacts\nActivity | exclude | Previous-month work as current work")
            st.form_submit_button("Save shared fixture", on_click=_queue_upload)


def _render_reference_bundle_shelf(live_storage_root):
    """Read-only availability for external browser agents; not an AUTH importer."""
    from app.monthly_report_shared_source_bundles import SharedSourceBundles
    with st.expander("Immutable six-source reference archive for external testers"):
        st.warning("No login: anyone who finds this hidden test area can download the complete source archive. Do not upload unrelated files.")
        st.caption("Independent of AUTH01–03 or live reports. Uploaded member SHA-256 values are checked for consistency; external agents must also compare the full archive SHA-256 against the owner-recorded digest before trusting its identity.")
        st.file_uploader("Original six-source ZIP archive", type=["zip"],
                         max_upload_size=96, key=_PREFIX + "source_bundle_file")
        st.button("Store verified original source archive",
                  key=_PREFIX + "source_bundle_save", on_click=_queue_source_bundle_upload)
        shelf = SharedSourceBundles(Path(live_storage_root))
        try:
            saved = shelf.list()
        except (ValueError, OSError):
            st.error("Shared source archive storage needs recovery. Existing files were not reset.")
            return
        if not saved:
            st.info("No external-agent source archive is stored on Render yet.")
            return
        entries = {bundle.bundle_id: bundle for bundle in saved}
        chosen = st.selectbox("Stored source archive", tuple(entries),
                              key=_PREFIX + "source_bundle_select",
                              format_func=lambda entry: "Original sources · " + entry[:12])
        receipt = entries[chosen]
        st.caption(f"Six originals · {receipt.archive_size:,} ZIP bytes · SHA-256: {receipt.archive_sha256}")
        with st.expander("Source file names and original hashes"):
            for source in receipt.source_files:
                st.write(source.filename + " · " + source.sha256 + " · " + str(source.size_bytes) + " bytes")
        # An 88 MB archived ZIP must not be read from disk on every editor
        # fragment or normal full rerun. Only an explicit action materializes
        # the verified download response, and only for that exact source.
        action_scope = receipt.bundle_id + "_" + receipt.archive_sha256[:16]
        if st.button("Prepare verified ZIP download", key=_PREFIX + "source_bundle_prepare_" + action_scope):
            try:
                shelf.download(receipt.bundle_id)  # Explicit full-byte check once.
            except (OSError, ValueError):
                st.session_state.pop(_PREFIX + "prepared_bundle", None)
                st.error("Archive verification failed; original download is unavailable.")
            else:
                st.session_state[_PREFIX + "prepared_bundle"] = action_scope
        if st.session_state.get(_PREFIX + "prepared_bundle") == action_scope:
            # Streamlit 1.61+ supports deferred download data callables. Do
            # not retain or reread 88 MB of client sources on unrelated full
            # editor reruns after Prepare. Reverify on the actual click.
            def verified_source_bytes():
                return shelf.download(receipt.bundle_id)
            st.download_button("Download unchanged source archive", verified_source_bytes,
                               file_name="ENFRA_MSAPO_Owner_Originals_2026-10-14_PORTABLE.zip",
                               mime="application/zip",
                               key=_PREFIX + "source_bundle_download_" + action_scope,
                               on_click="ignore")
            st.caption("Archive bytes are verified on download. Test-run Reset never deletes the reference archive.")



def _render_synthetic_evidence_shelf(live_storage_root):
    """No-login immutable synthetic QA evidence, separated from source originals."""
    from app.monthly_report_shared_source_bundles import SharedSyntheticEvidenceBundles
    with st.expander("Synthetic QA evidence archive for external agents"):
        st.warning("Shared without login. Upload synthetic testing evidence only; source originals belong in the separate six-source archive shelf.")
        st.caption("The included evidence manifest identifies each test's exact run, commit, pass/fail state and SHA-256. Archive storage does not change acceptance status or imported reports.")
        st.file_uploader("Synthetic evidence ZIP archive", type=["zip"],
                         max_upload_size=24, key=_PREFIX + "evidence_bundle_file")
        st.button("Store hash-checked synthetic evidence archive",
                  key=_PREFIX + "evidence_bundle_save", on_click=_queue_evidence_bundle_upload)
        shelf = SharedSyntheticEvidenceBundles(Path(live_storage_root))
        try:
            saved = shelf.list()
        except (ValueError, OSError):
            st.error("Synthetic evidence storage needs recovery. No originals were removed.")
            return
        if not saved:
            st.info("No synthetic evidence ZIP is stored on Render yet.")
            return
        entries = {item.bundle_id: item for item in saved}
        chosen = st.selectbox("Saved synthetic evidence archive", tuple(entries),
                              key=_PREFIX + "evidence_bundle_select",
                              format_func=lambda item: "Synthetic evidence · " + item[:12])
        receipt = entries[chosen]
        st.caption(f"{len(receipt.source_files)} evidence artifacts · {receipt.archive_size:,} ZIP bytes · SHA-256: {receipt.archive_sha256}")
        with st.expander("Individually verified CI evidence ZIPs"):
            for item in receipt.source_files:
                st.write(item.filename + " · " + item.sha256 + " · " + str(item.size_bytes) + " bytes")
        action_scope = receipt.bundle_id + "_" + receipt.archive_sha256[:16]
        if st.button("Prepare evidence ZIP download",
                     key=_PREFIX + "evidence_bundle_prepare_" + action_scope):
            try:
                shelf.download(receipt.bundle_id)  # Verify once on explicit Prepare.
            except (ValueError, OSError):
                st.error("Evidence archive integrity check failed; download is unavailable.")
                st.session_state.pop(_PREFIX + "prepared_evidence_bundle", None)
            else:
                st.session_state[_PREFIX + "prepared_evidence_bundle"] = action_scope
        if st.session_state.get(_PREFIX + "prepared_evidence_bundle") == action_scope:
            def verified_evidence_bytes():
                return shelf.download(receipt.bundle_id)
            st.download_button("Download unchanged synthetic evidence archive", verified_evidence_bytes,
                               file_name="ENFRA_MSAPO_Synthetic_Evidence_" + receipt.archive_sha256[:12] + ".zip",
                               mime="application/zip",
                               key=_PREFIX + "evidence_bundle_download_" + action_scope,
                               on_click="ignore")
            st.caption("Source bytes are reverified on click; Reset preserves this immutable archive.")


def render(browser_token, browser_timezone, field, move, live_storage_root):
    # The entry route owns initial binding; this validates its exact distinct
    # run token before touching either shared fixtures or ordinary report UI.
    context = runs._current_run(browser_token)
    library = SharedFixtureLibrary(Path(live_storage_root))
    st.subheader("Shared report testing")
    st.warning("Anyone with this link can upload, view and download these files without a login. The fixture library is shared; this browser’s report workspace is isolated.")
    _process_pending(library, browser_token, live_storage_root)
    if error := st.session_state.pop(_PREFIX + "error", None):
        st.error(error)
    _render_upload()
    from app.monthly_report_shared_templates_ui import render as render_templates
    render_templates(live_storage_root)
    _render_reference_bundle_shelf(live_storage_root)
    _render_synthetic_evidence_shelf(live_storage_root)
    try:
        listing = library.list()
    except (ValueError, OSError):
        st.error("Shared fixture storage is unavailable or needs recovery. Existing originals were preserved.")
        return
    if listing.recovery:
        st.warning("An interrupted upload was retained for recovery. Existing fixtures remain available; no original was deleted.")
    by_id = {receipt.fixture_id: receipt for receipt in listing.fixtures}
    if by_id:
        if st.session_state.get(_PREFIX + "selection") not in by_id:
            st.session_state[_PREFIX + "selection"] = next(iter(by_id))
        selected = st.selectbox("Shared fixture", tuple(by_id), key=_PREFIX + "selection",
                                format_func=lambda identity: by_id[identity].metadata.friendly_name + " · " + identity[:8])
        receipt = by_id[selected]
        metadata = receipt.metadata
        st.caption(f"{metadata.scenario} · {metadata.source.month} → {metadata.target.month} · {receipt.original_size:,} bytes")
        with st.expander("Confirmed source, target and expected results"):
            st.write("Contract: " + metadata.target.contract)
            st.write("Source: " + "; ".join(metadata.source.site_titles or metadata.source.sites))
            st.write("Target: " + "; ".join(metadata.target.site_titles or metadata.target.sites))
            st.write(metadata.owner_expectations)
            for expected in metadata.expected_content:
                for fact in expected.includes:
                    st.write(expected.section + " · include · " + fact)
                for fact in expected.excludes:
                    st.write(expected.section + " · exclude · " + fact)
            st.caption("Original SHA256: " + receipt.original_sha256)
        try:
            # Streamlit may retain a mounted download_button's binary payload
            # when only a separate fixture selector changes. A constant widget
            # key let the second browser download the FIRST browser's DOCX
            # after reset, even though the selector displayed the correct
            # fixture. Bind the native widget identity to the exact immutable
            # fixture and source hash, never merely the visible filename.
            # A reselect remounts only these actions, not the report editor.
            source_action_scope = selected + "_" + receipt.original_sha256[:16]
            st.download_button("Download unchanged original", library.download(selected),
                               file_name="fixture-" + selected[:12] + ".docx", mime=receipt.media_type,
                               key=_PREFIX + "download_" + source_action_scope, on_click="ignore")
        except (ValueError, OSError):
            st.error("The selected original could not be verified for download.")
        st.button("Start fresh test with this fixture",
                  key=_PREFIX + "start_" + source_action_scope, on_click=_queue_run,
                  args=(selected, context.generation))
        st.caption("Starting a fresh test replaces this browser’s current test workspace and keeps every shared fixture.")
    else:
        st.info("Upload a report to create the first shared fixture.")
    st.button("Reset this test workspace", key=_PREFIX + "reset", on_click=_queue_run,
              args=(None, context.generation))
    st.caption("Reset clears this browser’s disposable report run. Shared originals remain available.")
    try:
        record = st.session_state.get(_PREFIX + "record")
        if record is not None:
            runs.validate_run(record.context)
        else:
            record = runs.read_run_fixture(library, browser_token)
            if record is not None:
                st.session_state[_PREFIX + "record"] = record
        if record is None:
            return
        profile = target_profile(record.lineage.metadata)
        period = ReportPeriod(*map(int, record.lineage.metadata.target.month.split("-")))
        if st.session_state.get("report_setup_done") == profile.key:
            # Production select_sites performs this same transition after a
            # successful import: custom names are now saved site checkboxes.
            # Clear that entry before our guard counts each selected site once.
            st.session_state["report_sites_" + _key(profile.contract) + "_new_site"] = ""
        _seed_target(profile, period)
        if not _target_matches(profile, period):
            st.error("This test was confirmed for " + profile.contract + " · "
                     + "; ".join(site.title for site in profile.facilities) + " · " + period.label
                     + ". The selected report target changed. Restore that target or start a fresh fixture test.")
            if st.button("Restore fixture target", key=_PREFIX + "restore_target"):
                _seed_target(profile, period, force=True)
                st.rerun()
            return
        existing = next((candidate for candidate in report_library.list_profiles(profile.contract)
                         if candidate.key == profile.key), None)
        stage_key = runs.setup_stage_key(profile, period)
        if existing is None:
            staged = st.session_state.get(_PREFIX + "staged")
            if staged is None:
                staged = runs.resume_fixture(record, profile)
                st.session_state[_PREFIX + "staged"] = staged
            runs.validate_run(staged.context)
            st.session_state.setdefault(stage_key, staged.stage)
        elif not st.session_state.get(_PREFIX + "initial_review_finished"):
            # The normal importer saved this report. Do not resurrect its
            # initial review over the user's recoverable current draft.
            current_stage = st.session_state.get(stage_key)
            if current_stage and current_stage[1] == record.source_path:
                st.session_state.pop(stage_key, None)
            st.session_state.pop(_PREFIX + "staged", None)
            st.session_state[_PREFIX + "initial_review_finished"] = True
    except (ValueError, OSError):
        st.error("This test’s saved source or generation could not be verified. Start a fresh test; the shared original is retained.")
        return
    st.divider()
    st.caption("Current test: " + record.lineage.metadata.friendly_name + " · " + period.label)
    from app.monthly_report_guided import render_guided_workflow
    render_guided_workflow(browser_token, browser_timezone, field, move)
