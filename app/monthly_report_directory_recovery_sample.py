"""One disposable fault sample, exclusively inside an active isolated namespace."""
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from app import monthly_report_directory as directory, monthly_report_library as library
from app import monthly_report_testing as testing

BROKEN = b'{"schema":1,"synthetic-recovery-sample":'


def _receipt_path():
    if testing.scope() is None:
        raise ValueError("Directory recovery samples require isolated testing.")
    path = library._root() / "qa_directory_recovery" / "sample.json"
    library._qa_path_guard(path)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Linked recovery sample storage is unavailable.")
    return path


def create_sample():
    receipt_path = _receipt_path()
    with library._locked(receipt_path.parent):
        if receipt_path.exists():
            receipt = library._read(receipt_path)
            if receipt.get("status") != "ready":
                raise ValueError("The earlier sample was interrupted. Its records were retained; no sample was replaced.")
            return receipt  # Never re-damage a record, including after recovery.
        suffix = uuid4().hex
        contract = "Synthetic Recovery " + suffix
        control = "Synthetic Recovery Control " + suffix
        receipt = {"schema": 1, "status": "pending", "contract": contract, "control": control}
        library._atomic_write(receipt_path, library._json(receipt))
        site = directory.DirectorySite("synthetic-recovery-site", "Synthetic Recovery Site",
            contacts=(directory.DirectoryContact("Site manager", "Synthetic Recovery Person", "202-555-0100",
                                                 "recovery@example.invalid"),))
        healthy = directory.save_directory(control, (site,), expected_revision=0,
            actor="Synthetic Recovery Sample", confirmed=True)
        # A fresh reserved identity only. No existing directory is ever damaged.
        lock = library._root() / "directory_locks" / library._contract_directory(directory._contract_identity(contract))
        with library._locked(lock):
            path = library._root() / "directory" / library._contract_directory(contract)
            library._qa_path_guard(path)
            if path.exists() or path.is_symlink():
                raise ValueError("Sample identity already exists; no directory was replaced.")
            prior = directory.DirectoryState(contract, 1, (site,), "Synthetic Recovery Sample", library._now())
            original = library._json({"schema": 1, **asdict(prior)})
            library._atomic_write(path / "history" / "00000001.json", original)
            library._atomic_write(path / "manifest.json", BROKEN)
        receipt.update(status="ready", history_sha256=sha256(original).hexdigest(),
                       control_sha256=sha256(library._json({"schema": 1, **asdict(healthy)})).hexdigest(),
                       damaged_sha256=sha256(BROKEN).hexdigest())
        library._atomic_write(receipt_path, library._json(receipt))
        return receipt


def check_sample():
    receipt = library._read(_receipt_path())
    if receipt.get("status") != "ready":
        raise ValueError("No completed recovery sample is available.")
    from app.monthly_report_directory_recovery import _bytes, _path
    target = _path(library._contract_directory(receipt["contract"]))
    control = _path(library._contract_directory(receipt["control"]))
    results = {
        "Original history unchanged": sha256(_bytes(target / "history" / "00000001.json", library.MAX_JSON_BYTES)).hexdigest() == receipt["history_sha256"],
        "Healthy control unchanged": sha256(_bytes(control / "manifest.json", library.MAX_JSON_BYTES)).hexdigest() == receipt["control_sha256"],
    }
    try:
        state = directory.load_directory(receipt["contract"], include_archived=True)
    except library.LibraryError:
        state = None
    results["Recovered as revision 2"] = bool(state and state.revision == 2 and state.action == "recover:1:" + receipt["damaged_sha256"])
    backup = target / "recovery" / (receipt["damaged_sha256"] + ".bin")
    results["Damaged bytes retained exactly"] = backup.exists() and _bytes(backup, library.MAX_JSON_BYTES) == BROKEN
    return receipt, results


def render_sample():
    import streamlit as st
    from app.monthly_report_ui_text import literal
    with st.expander("Directory recovery sample (synthetic only)"):
        st.caption("Creates two new invented directories in this isolated test area: one damaged record with readable history, and one healthy control. Existing fixtures stay unchanged. Repeating creation reuses this sample without damaging it again.")
        if st.button("Create damaged-directory sample", key="report_directory_recovery_sample_create"):
            try:
                receipt = create_sample()
                st.success("Recovery sample is ready. Enter your editor name below, then inspect its recovery history.")
                st.text(receipt["contract"])
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
        if st.button("Check recovery sample", key="report_directory_recovery_sample_check"):
            try:
                receipt, checks = check_sample()
                st.text(receipt["contract"])
                for label, passed in checks.items():
                    (st.success if passed else st.warning)(label if passed else label + ": not yet verified")
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
