"""Exact-operation acknowledgment never adopts another writer's revision."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app import monthly_report_active_work as active, monthly_report_library as library
from app import monthly_report_recovery_save as recovery
from app.monthly_report_model import ReportPeriod
from test_monthly_report_active_work import make_draft, _image

TOKEN = "a" * 32
OP = "b" * 32


def request(draft, **changes):
    values = dict(expected_revision=0, expected_generation="", base_snapshot_revision=0,
                  operation_id=OP)
    values.update(changes)
    return values


def location(draft):
    return active._directory(TOKEN, draft.profile.contract, draft.profile.key, draft.period) / "working.json"


def test_only_exact_last_operation_replays_without_another_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    first = active.save(TOKEN, draft, **request(draft))
    before = location(draft).read_bytes()
    replay = active.save(TOKEN, draft, **request(draft))
    assert replay == first
    assert location(draft).read_bytes() == before
    # A new no-op request retains existing no-write semantics.
    same = active.save(TOKEN, draft, **request(draft, expected_revision=first.revision,
        expected_generation=first.generation, operation_id="c" * 32))
    assert same == first and location(draft).read_bytes() == before


@pytest.mark.parametrize("change", ["draft", "base", "revision", "generation", "assets", "id"])
def test_mismatched_replay_keeps_committed_bytes(monkeypatch, tmp_path, change):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    active.save(TOKEN, draft, **request(draft))
    before = location(draft).read_bytes()
    kwargs = request(draft)
    if change == "draft":
        draft = replace(draft, prepared_by="Different delivered edit")
    elif change == "base":
        kwargs["base_snapshot_revision"] = 1
    elif change == "revision":
        kwargs["expected_revision"] = 1
    elif change == "generation":
        kwargs["expected_generation"] = "d" * 32
    elif change == "assets":
        raw = _image()
        kwargs["assets"] = {library.asset_reference(raw, "png"): raw}
    else:
        kwargs["operation_id"] = "e" * 32
    with pytest.raises(active.ActiveWorkConflict):
        active.save(TOKEN, draft, **kwargs)
    assert location(draft).read_bytes() == before


@pytest.mark.parametrize("case", ["other_identical", "newer", "aba", "discard", "recreate"])
def test_other_writer_or_reset_cannot_be_acknowledged(monkeypatch, tmp_path, case):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    first = active.save(TOKEN, draft, **request(draft, operation_id="c" * 32 if case == "other_identical" else OP))
    if case in ("newer", "aba"):
        second = active.save(TOKEN, replace(draft, prepared_by="Other tab"),
            **request(draft, expected_revision=first.revision, expected_generation=first.generation,
                      operation_id="d" * 32))
        if case == "aba":
            active.save(TOKEN, draft, **request(draft, expected_revision=second.revision,
                expected_generation=second.generation, operation_id="e" * 32))
    elif case in ("discard", "recreate"):
        generation = active.discard(TOKEN, draft.profile.contract, draft.profile.key, draft.period,
            expected_revision=first.revision, expected_generation=first.generation)
        if case == "recreate":
            active.save(TOKEN, draft, **request(draft, expected_generation=generation, operation_id="f" * 32))
    before = location(draft).read_bytes()
    with pytest.raises(active.ActiveWorkConflict):
        active.save(TOKEN, draft, **request(draft))
    assert location(draft).read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_replay_checks_committed_asset_integrity(monkeypatch, tmp_path, damage):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    raw = _image()
    name = library.asset_reference(raw, "png")
    kwargs = request(draft, assets={name: raw})
    active.save(TOKEN, draft, **kwargs)
    path = location(draft).parent / "assets" / name
    path.unlink()
    if damage == "corrupt":
        path.write_bytes(b"changed")
    with pytest.raises(library.LibraryError, match="integrity"):
        active.save(TOKEN, draft, **kwargs)


def state_for(draft):
    return {"report_active_sequence": 0, "report_active_generation": "", "report_revision": 0}


def scope_for(draft):
    return (draft.profile.contract, draft.profile.key, draft.period.key, "editor-one", "qa-one")


class Interrupted(Exception):
    pass


class InterruptState(dict):
    def __init__(self, initial, suffix):
        super().__init__(initial)
        self.suffix = suffix
        self.armed = True

    def __setitem__(self, key, value):
        if self.armed and key.endswith(self.suffix):
            self.armed = False
            raise Interrupted
        super().__setitem__(key, value)


@pytest.mark.parametrize("suffix", ["_active_sequence", "_active_generation"])
@pytest.mark.parametrize("existing", [False, True])
def test_interrupted_acknowledgment_then_new_edit_preserves_both(monkeypatch, tmp_path, suffix, existing):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    state = state_for(draft)
    scope = scope_for(draft)
    if existing:
        recovery.save(state, "report", scope, TOKEN, draft, {})
        draft = replace(draft, prepared_by="First delivered update")
    state = InterruptState(state, suffix)
    with pytest.raises(Interrupted):
        recovery.save(state, "report", scope, TOKEN, draft, {})
    pending = state["report_pending_browser_save"]
    old = active.load(TOKEN, draft.profile.contract, draft.profile.key, draft.period)
    assert old.draft == draft
    newer = replace(draft, prepared_by="Newer delivered update")
    saved = recovery.save(state, "report", scope, TOKEN, newer, {})
    assert saved.draft == newer and saved.revision == old.revision + 1
    assert state["report_active_sequence"] == saved.revision
    assert state["report_active_generation"] == saved.generation
    assert "report_pending_browser_save" not in state
    assert library._read(location(draft))["save_operation"]["id"] != pending.operation_id


@pytest.mark.parametrize("change", ["browser", "profile", "month", "incarnation", "qa_reset"])
def test_pending_request_cannot_cross_scope(monkeypatch, tmp_path, change):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    state = InterruptState(state_for(draft), "_active_sequence")
    scope = scope_for(draft)
    with pytest.raises(Interrupted):
        recovery.save(state, "report", scope, TOKEN, draft, {})
    before = location(draft).read_bytes()
    token = TOKEN
    if change == "browser":
        token = "c" * 32
    else:
        index = {"profile": 1, "month": 2, "incarnation": 3, "qa_reset": 4}[change]
        scope = (*scope[:index], "different", *scope[index + 1:])
    with pytest.raises(active.ActiveWorkConflict):
        recovery.acknowledge(state, "report", scope, token)
    assert location(draft).read_bytes() == before
    assert state["report_active_sequence"] == 0


def test_overlapping_same_operation_commits_once_then_new_edit_uses_cas(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    entered, release = Event(), Event()
    write = library._atomic_write
    def pause_commit(path, data):
        if path.name == "working.json" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return write(path, data)
    monkeypatch.setattr(library, "_atomic_write", pause_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(active.save, TOKEN, draft, **request(draft))
        assert entered.wait(5)
        replay = pool.submit(active.save, TOKEN, draft, **request(draft))
        release.set()
        first, second = old.result(5), replay.result(5)
    assert first == second and first.revision == 1
    newer = replace(draft, prepared_by="Newest input")
    saved = active.save(TOKEN, newer, **request(draft, expected_revision=second.revision,
        expected_generation=second.generation, operation_id="d" * 32))
    with pytest.raises(active.ActiveWorkConflict):
        active.save(TOKEN, draft, **request(draft))
    assert active.load(TOKEN, draft.profile.contract, draft.profile.key, draft.period) == saved


@pytest.mark.parametrize("suffix", ["_active_sequence", "_active_generation"])
def test_real_editor_recovers_at_streamlit_ack_yield_and_keeps_next_event(monkeypatch, tmp_path, suffix):
    import streamlit as st
    from streamlit.runtime.state.safe_session_state import SafeSessionState
    from test_monthly_report_qa_ui import visit, ACTOR_COOKIE
    from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture
    from app.monthly_report_sources import source_reference

    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Replay synthetic source files").click().run()
    with qa.isolated(ACTOR_COOKIE):
        original = next(s for s in library.load_snapshot(
            fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft.sources
            if s.filename == "synthetic-activity.txt")
    next(w for w in app.multiselect if w.label == "Source sites" and original.id in w.key).set_value(["qa-north"])
    next(b for b in app.button if b.label == "Use these source details" and original.id in b.key).click().run()
    with qa.isolated(ACTOR_COOKIE):
        source = next(s for s in active.load(ACTOR_COOKIE, fixture.CONTRACT,
            fixture.profile().key, fixture.PERIOD).draft.sources if s.id == original.id)
    reference = source_reference(source, 1)
    setter = SafeSessionState.__setitem__
    armed = [True]
    def interrupt_ack(self, key, value):
        if armed[0] and key.endswith(suffix):
            armed[0] = False
            # SafeSessionState yields before its native assignment. Model a
            # new rerun at that actual boundary, after the disk save returned.
            st.rerun()
        return setter(self, key, value)
    monkeypatch.setattr(SafeSessionState, "__setitem__", interrupt_ack)
    next(w for w in app.multiselect if w.label == "Supporting source pages").set_value([reference]).run()
    assert not armed[0] and not app.exception
    assert not any("Another tab or a new working copy" in e.value for e in app.error)
    next(w for w in app.checkbox if w.label == "Remove unavailable source links").check().run()
    assert not app.exception
    assert not any("Another tab or a new working copy" in e.value for e in app.error)
    with qa.isolated(ACTOR_COOKIE):
        saved = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    assert saved.draft.follow_ups[0].references == (reference,)
    assert any(w.value == "QA working report SHA256: " + saved.draft.fingerprint for w in app.caption)
    assert any(w.value == "QA durable report SHA256: " + saved.draft.fingerprint for w in app.caption)
    reopened = visit(monkeypatch, tmp_path)
    assert not reopened.exception
    assert next(w for w in reopened.multiselect if w.label == "Supporting source pages").value == [reference]


@pytest.mark.parametrize("damage", ["receipt_type", "missing_field", "generation", "revision", "parent_type"])
def test_malformed_or_changed_committed_receipt_fails_closed(monkeypatch, tmp_path, damage):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    active.save(TOKEN, draft, **request(draft))
    path = location(draft)
    data = library._read(path)
    if damage == "receipt_type":
        data["save_operation"] = "wrong"
    elif damage == "missing_field":
        data["save_operation"].pop("generation")
    elif damage == "generation":
        data["generation"] = "e" * 32
    elif damage == "revision":
        data["revision"] += 1
    else:
        data["save_operation"]["parent_revision"] = False
    library._atomic_write(path, library._json(data))
    before = path.read_bytes()
    with pytest.raises(library.LibraryError):
        active.save(TOKEN, draft, **request(draft))
    assert path.read_bytes() == before


def test_real_first_save_recovers_interrupt_between_revision_and_new_generation(monkeypatch, tmp_path):
    import streamlit as st
    from streamlit.runtime.state.safe_session_state import SafeSessionState
    from test_monthly_report_qa_ui import visit, ACTOR_COOKIE
    from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture

    app = visit(monkeypatch, tmp_path)
    save, setter = active.save, SafeSessionState.__setitem__
    committed, interrupted = [False], [False]
    def observe_first_commit(*args, **kwargs):
        saved = save(*args, **kwargs)
        if kwargs["expected_revision"] == 0 and kwargs.get("expected_generation") == "":
            committed[0] = True
        return saved
    def interrupt_new_generation(self, key, value):
        if committed[0] and not interrupted[0] and key.endswith("_active_generation"):
            interrupted[0] = True
            st.rerun()
        return setter(self, key, value)
    monkeypatch.setattr(active, "save", observe_first_commit)
    monkeypatch.setattr(SafeSessionState, "__setitem__", interrupt_new_generation)
    next(b for b in app.button if b.label == "Replay synthetic source files").click().run()
    assert committed[0] and interrupted[0] and not app.exception
    assert not any("Another tab or a new working copy" in e.value for e in app.error)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("New delivered work after first-save acknowledgment.").run()
    assert not app.exception
    assert not any("Another tab or a new working copy" in e.value for e in app.error)
    with qa.isolated(ACTOR_COOKIE):
        saved = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    assert next(b.text for b in saved.draft.blocks if b.key == "activity_summary") == "New delivered work after first-save acknowledgment."
    assert any(w.value == "QA working report SHA256: " + saved.draft.fingerprint for w in app.caption)
    assert any(w.value == "QA durable report SHA256: " + saved.draft.fingerprint for w in app.caption)


def test_pending_payload_identity_cannot_be_replaced_before_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = make_draft()
    state = InterruptState(state_for(draft), "_active_sequence")
    scope = scope_for(draft)
    with pytest.raises(Interrupted):
        recovery.save(state, "report", scope, TOKEN, draft, {})
    pending = state["report_pending_browser_save"]
    state["report_pending_browser_save"] = replace(pending, draft=replace(draft, prepared_by="Changed payload"))
    before = location(draft).read_bytes()
    with pytest.raises(active.ActiveWorkConflict):
        recovery.acknowledge(state, "report", scope, TOKEN)
    assert location(draft).read_bytes() == before
