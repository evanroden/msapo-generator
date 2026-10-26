"""The finished-PDF viewer uses only exact current-session bytes; never history."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import monthly_report_output_ui as output_ui
from app import reference_preview


@pytest.fixture
def rendered(monkeypatch):
    state, previews, expansions, captions, info = {}, [], [], [], []

    @contextmanager
    def expander(label, *, expanded, key):
        expansions.append((label, expanded, key))
        yield

    monkeypatch.setattr(output_ui.st, "session_state", state)
    monkeypatch.setattr(output_ui.st, "expander", expander)
    monkeypatch.setattr(output_ui.st, "caption", captions.append)
    monkeypatch.setattr(output_ui.st, "info", info.append)
    monkeypatch.setattr(reference_preview, "render_reference", lambda **kwargs: previews.append(kwargs))
    return SimpleNamespace(state=state, previews=previews, expansions=expansions,
                           captions=captions, info=info)


def package(*, pdf=b"%PDF-synthetic", fingerprint="draft-1"):
    return SimpleNamespace(docx=b"word", pdf=pdf, pdf_name="final.pdf",
                           fingerprint=fingerprint)


def test_exact_current_package_renders_existing_pdf_bytes_only(rendered):
    current = package()
    rendered.state["monthly_package"] = current
    draft = SimpleNamespace(fingerprint="draft-1")

    output_ui.render_current_session_pdf_preview(current, draft, "monthly", session_scope="session-A")

    assert rendered.expansions == [
        ("View PDF here (this session)", False, "monthly_finished_pdf_view")]
    assert len(rendered.previews) == 1
    shown = rendered.previews[0]
    assert shown["key"] == "finished_report_pdf"
    assert shown["raw"] is current.pdf and shown["filename"] == "final.pdf"
    assert shown["owner_scope"] == output_ui._final_pdf_scope("monthly", "session-A")
    assert "Shared version history stores" in rendered.captions[0]


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
    assert rendered.previews == [] and rendered.expansions == []


@pytest.mark.parametrize("pdf", (b"not-a-pdf", b"%PDF-" + b"x" * (25 * 1024 * 1024)))
def test_unviewable_bytes_do_not_bypass_disposable_store_limit(rendered, pdf):
    current = package(pdf=pdf)
    rendered.state["monthly_package"] = current
    output_ui.render_current_session_pdf_preview(
        current, SimpleNamespace(fingerprint="draft-1"), "monthly", session_scope="session-A")
    assert rendered.expansions and not rendered.previews
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
    assert len(rendered.expansions) == 2


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
        # The previous byte-backed fragment must be retired before any new
        # report package, including a failed PDF retry, becomes authoritative.
        assert rendered.state["monthly_package"] is previous
        discarded.append(owner)

    monkeypatch.setattr(reference_preview, "discard_reference_scope", discard)
    replacement = package(pdf=replacement_pdf)
    output_ui.replace_current_session_pdf_package("monthly", "session-A", replacement)

    assert discarded == [output_ui._final_pdf_scope("monthly", "session-A")]
    assert rendered.state["monthly_package"] is replacement
    output_ui.render_current_session_pdf_preview(
        replacement, SimpleNamespace(fingerprint="draft-1"),
        "monthly", session_scope="session-A",
    )
    assert bool(rendered.previews) == bool(replacement_pdf)


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
