"""The finished-PDF viewer uses only exact current-session bytes; never history."""
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app import monthly_report_output_ui as output_ui
from app import reference_preview


@pytest.fixture
def rendered(monkeypatch):
    state, previews, containers, captions, info, headings = {}, [], [], [], [], []

    @contextmanager
    def container(*, key):
        containers.append(key)
        yield

    monkeypatch.setattr(output_ui.st, "session_state", state)
    monkeypatch.setattr(output_ui.st, "container", container)
    monkeypatch.setattr(output_ui.st, "markdown", headings.append)
    monkeypatch.setattr(output_ui.st, "caption", captions.append)
    monkeypatch.setattr(output_ui.st, "info", info.append)
    monkeypatch.setattr(reference_preview, "render_reference", lambda **kwargs: previews.append(kwargs))
    return SimpleNamespace(state=state, previews=previews, containers=containers,
                           captions=captions, info=info, headings=headings)


def package(*, pdf=b"%PDF-synthetic", fingerprint="draft-1"):
    return SimpleNamespace(docx=b"word", pdf=pdf, pdf_name="final.pdf",
                           fingerprint=fingerprint)


def test_exact_current_package_renders_existing_pdf_bytes_only(rendered):
    current = package()
    rendered.state["monthly_package"] = current
    draft = SimpleNamespace(fingerprint="draft-1")

    output_ui.render_current_session_pdf_preview(current, draft, "monthly", session_scope="session-A")

    assert rendered.containers == ["monthly_finished_pdf_view"]
    assert rendered.headings == ["**Final PDF · current draft**"]
    assert len(rendered.previews) == 1
    shown = rendered.previews[0]
    assert shown["key"] == "finished_report_pdf"
    assert shown["raw"] is current.pdf and shown["filename"] == "final.pdf"
    assert shown["owner_scope"] == output_ui._final_pdf_scope("monthly", "session-A")
    assert sha256(current.pdf).hexdigest() in rendered.captions[0]
    assert sha256(current.docx).hexdigest() in rendered.captions[0]
    assert shown["focus_on_open"] is True


@pytest.mark.parametrize("change", ("retired", "different_package", "different_draft", "no_pdf"))
def test_no_preview_for_retired_or_wrong_package(rendered, change):
    current = package()
    rendered.state["monthly_package"] = current
    draft = SimpleNamespace(fingerprint=current.fingerprint)
    candidate = current
    if change == "retired":
        rendered.state.pop("monthly_package")
    elif change == "different_package":
        candidate = package()
    elif change == "different_draft":
        draft = SimpleNamespace(fingerprint="draft-2")
    else:
        candidate = package(pdf=None)
        rendered.state["monthly_package"] = candidate

    output_ui.render_current_session_pdf_preview(candidate, draft, "monthly", session_scope="session-A")
    assert rendered.previews == [] and rendered.containers == []


@pytest.mark.parametrize("pdf", (b"not-a-pdf", b"%PDF-" + b"x" * (25 * 1024 * 1024)))
def test_unviewable_bytes_do_not_bypass_disposable_store_limit(rendered, pdf):
    current = package(pdf=pdf)
    rendered.state["monthly_package"] = current
    output_ui.render_current_session_pdf_preview(
        current, SimpleNamespace(fingerprint="draft-1"), "monthly", session_scope="session-A")
    assert rendered.containers and not rendered.previews
    assert "unavailable" in rendered.info[-1].lower()


def test_changed_pdf_bytes_reuse_scope_but_never_invent_old_bytes(rendered):
    a = package(pdf=b"%PDF-a")
    rendered.state["monthly_package"] = a
    draft = SimpleNamespace(fingerprint="draft-1")
    output_ui.render_current_session_pdf_preview(a, draft, "monthly", session_scope="session-A")
    b = package(pdf=b"%PDF-b")
    rendered.state["monthly_package"] = b
    output_ui.render_current_session_pdf_preview(b, draft, "monthly", session_scope="session-A")
    assert [v["raw"] for v in rendered.previews] == [b"%PDF-a", b"%PDF-b"]
    assert rendered.previews[0]["owner_scope"] == rendered.previews[1]["owner_scope"]
    # The reference renderer binds that owner/key to the content's SHA-256 and
    # invalidates its old raster/ticket on a different payload.
    assert len(rendered.containers) == 2


def test_scopes_are_isolated_and_cleanup_targets_only_the_active_view(monkeypatch, rendered):
    disposed = []
    monkeypatch.setattr(reference_preview, "discard_reference_scope", disposed.append)
    one = output_ui._final_pdf_scope("monthly", "session-A")
    other = output_ui._final_pdf_scope("monthly", "session-B")
    another_report = output_ui._final_pdf_scope("other-monthly", "session-A")
    assert len({one, other, another_report}) == 3
    output_ui.discard_current_session_pdf_preview("monthly", "session-A")
    assert disposed == [one]


@pytest.mark.parametrize("prefix,scope", (("", "session"), ("report", ""), (None, "session")))
def test_no_anonymous_preview_scope(prefix, scope):
    with pytest.raises(ValueError):
        output_ui._final_pdf_scope(prefix, scope)


@pytest.mark.parametrize("replacement_pdf", (None, b"%PDF-new"))
def test_replacement_retires_old_fragments_before_new_package_becomes_current(
    monkeypatch, rendered, replacement_pdf
):
    previous = package(pdf=b"%PDF-previous")
    rendered.state["monthly_package"] = previous
    discarded = []

    def discard(owner):
        discarded.append((owner, rendered.state["monthly_package"] is previous))

    monkeypatch.setattr(reference_preview, "discard_reference_scope", discard)
    replacement = package(pdf=replacement_pdf)
    output_ui.replace_current_session_pdf_package("monthly", "session-A", replacement)

    # The previous byte-backed fragment is retired while it is still the
    # current package, before any new package (even a failed PDF retry) takes over.
    scope = output_ui._final_pdf_scope("monthly", "session-A")
    assert discarded == [(scope, True)]
    assert rendered.state["monthly_package"] is replacement
    output_ui.render_current_session_pdf_preview(
        replacement, SimpleNamespace(fingerprint="draft-1"),
        "monthly", session_scope="session-A",
    )
    assert bool(rendered.previews) == bool(replacement_pdf)
    # With no usable PDF, rendering revokes the same scope once more for any
    # late callback from the retired fragment; it never shows the old bytes.
    assert discarded[1:] == ([] if replacement_pdf else [(scope, False)])


def test_same_package_rerender_does_not_dispose_current_preview(monkeypatch, rendered):
    current = package()
    rendered.state["monthly_package"] = current
    discarded = []
    monkeypatch.setattr(reference_preview, "discard_reference_scope", discarded.append)
    output_ui.replace_current_session_pdf_package("monthly", "session-A", current)
    assert discarded == []
    assert rendered.state["monthly_package"] is current


def test_guided_generation_and_retry_use_atomic_ticket_retirement():
    from pathlib import Path

    guided = (Path(__file__).resolve().parents[1] / "app/monthly_report_guided.py").read_text()
    assert guided.count(
        "replace_current_session_pdf_package(prefix, _rich_text_scope(prefix), package)"
    ) == 2
    assert 'st.session_state[prefix + "_package"] = package' not in guided


def test_import_rotates_epoch_after_retiring_old_pdf_owner(monkeypatch, rendered):
    """Importing the same report must not target the NEW scope for cleanup."""
    from app import monthly_report_guided as guided

    rendered.state["monthly_rich_text_epoch"] = "prior-report-incarnation"
    prior_scope = guided._rich_text_scope("monthly")
    discarded = []

    def retire(owner):
        # An old fragment remains valid if the epoch has already rotated.
        assert rendered.state["monthly_rich_text_epoch"] == "prior-report-incarnation"
        assert guided._rich_text_scope("monthly") == prior_scope
        discarded.append(owner)

    monkeypatch.setattr(reference_preview, "discard_reference_scope", retire)
    guided._rotate_rich_text_epoch("monthly")
    assert discarded == [output_ui._final_pdf_scope("monthly", prior_scope)]
    assert rendered.state["monthly_rich_text_epoch"] != "prior-report-incarnation"
    assert guided._rich_text_scope("monthly") != prior_scope


def test_first_editor_epoch_has_no_previous_pdf_owner(monkeypatch, rendered):
    from app import monthly_report_guided as guided

    discarded = []
    monkeypatch.setattr(reference_preview, "discard_reference_scope", discarded.append)
    guided._rotate_rich_text_epoch("monthly")
    assert rendered.state["monthly_rich_text_epoch"]
    assert discarded == []


def test_guided_import_calls_guarded_scope_rotation():
    from pathlib import Path

    guided = (Path(__file__).resolve().parents[1] / "app/monthly_report_guided.py").read_text()
    assert guided.count("_rotate_rich_text_epoch(prefix)") == 2


def test_recovery_whole_copy_replacement_disposes_old_pdf_scope(monkeypatch, rendered):
    """Use-newer path must retire old fragments BEFORE it removes the epoch."""
    from app import monthly_report_active_conflict_ui as conflict
    from app import monthly_report_guided as guided

    previous = package(pdf=b"%PDF-previous")
    rendered.state["monthly_package"] = previous
    rendered.state["monthly_rich_text_epoch"] = "previous-incarnation"
    old_scope = guided._rich_text_scope("monthly")
    retired = []

    def discard(scope):
        assert rendered.state["monthly_package"] is previous
        assert rendered.state["monthly_rich_text_epoch"] == "previous-incarnation"
        assert guided._rich_text_scope("monthly") == old_scope
        retired.append(scope)

    monkeypatch.setattr(reference_preview, "discard_reference_scope", discard)
    newer = SimpleNamespace(draft=SimpleNamespace(fingerprint="newer-draft"), assets=(),
                            base_snapshot_revision=4, revision=7,
                            generation="newer-generation", updated_at="now")
    conflict._use_newer("monthly", newer)

    assert retired == [output_ui._final_pdf_scope("monthly", old_scope)]
    assert "monthly_package" not in rendered.state
    assert rendered.state["monthly_draft"] is newer.draft
    assert rendered.state["monthly_rich_text_epoch"] != "previous-incarnation"
    assert guided._rich_text_scope("monthly") != old_scope


def test_newer_copy_first_session_needs_no_old_pdf_retirement(monkeypatch, rendered):
    from app import monthly_report_active_conflict_ui as conflict

    disposed = []
    monkeypatch.setattr(reference_preview, "discard_reference_scope", disposed.append)
    newer = SimpleNamespace(draft=SimpleNamespace(fingerprint="newer-draft"), assets=(),
                            base_snapshot_revision=1, revision=2,
                            generation="test-generation", updated_at="now")
    conflict._use_newer("monthly", newer)
    assert not disposed
    assert rendered.state["monthly_draft"] is newer.draft


def test_pdf_artifact_identity_tracks_exact_bytes_independently_of_word_save_receipt():
    first = package(pdf=b"%PDF-first")
    changed_pdf = package(pdf=b"%PDF-second")
    changed_word = package(pdf=b"%PDF-first")
    changed_word.docx = b"new Word layout"
    absent = package(pdf=None)

    assert output_ui.package_identity(first) == output_ui.package_identity(changed_pdf)
    assert output_ui.final_pdf_artifact_identity(first) == (
        first.fingerprint, sha256(first.docx).hexdigest(), sha256(first.pdf).hexdigest())
    assert output_ui.final_pdf_artifact_identity(first) != output_ui.final_pdf_artifact_identity(changed_pdf)
    assert output_ui.final_pdf_artifact_identity(first) != output_ui.final_pdf_artifact_identity(changed_word)
    assert output_ui.final_pdf_artifact_identity(absent) is None
    assert output_ui.final_pdf_artifact_identity(package(pdf="not bytes")) is None


def test_edited_draft_retires_old_pages_before_late_callback(monkeypatch, rendered):
    current = package(pdf=b"%PDF-old")
    rendered.state["monthly_package"] = current
    retired = []
    monkeypatch.setattr(reference_preview, "discard_reference_scope", retired.append)

    output_ui.render_current_session_pdf_preview(
        current, SimpleNamespace(fingerprint="draft-1"), "monthly", session_scope="session-A")
    assert len(rendered.previews) == 1
    output_ui.render_current_session_pdf_preview(
        current, SimpleNamespace(fingerprint="edited-draft"), "monthly", session_scope="session-A")
    assert len(rendered.previews) == 1  # never show the previous PDF as the current draft
    assert retired == [output_ui._final_pdf_scope("monthly", "session-A")]
    assert len(rendered.containers) == 1

    # A revert to the exact prior fingerprint can re-admit the actual bytes,
    # but only through a fresh authorized owner/ticket, not the old callback.
    output_ui.render_current_session_pdf_preview(
        current, SimpleNamespace(fingerprint="draft-1"), "monthly", session_scope="session-A")
    assert len(rendered.previews) == 2


def test_last_created_output_receipt_is_scope_bound_without_old_file_bytes(monkeypatch, rendered):
    warnings = []
    monkeypatch.setattr(output_ui.st, "warning", warnings.append)
    previous = package(pdf=b"%PDF-old")

    output_ui.replace_current_session_pdf_package("monthly", "session-A", previous)
    assert rendered.state["monthly_last_created_output"] == ("session-A", "draft-1")
    assert output_ui.outdated_output_status(
        "monthly", "session-A", SimpleNamespace(fingerprint="draft-1")) is False
    assert output_ui.outdated_output_status(
        "monthly", "session-B", SimpleNamespace(fingerprint="edited")) is False

    # The real guided editor drops finished bytes before showing the warning.
    rendered.state.pop("monthly_package")
    assert output_ui.outdated_output_status(
        "monthly", "session-A", SimpleNamespace(fingerprint="edited")) is True
    assert len(warnings) == 1 and "Earlier files were retired" in warnings[0]
    assert "monthly_package" not in rendered.state
    assert all(type(value) is not bytes for value in rendered.state.values())
