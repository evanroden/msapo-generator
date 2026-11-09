"""Forwarded message/rfc822 attachments are not direct Monthly source files.

Use only invented EmailMessage bytes. A nested email remains in the exact
original and can be uploaded separately, but nested private attachments must
never enter the outer message's direct attachment queue or consume its budget.
"""
from dataclasses import replace
from email.message import EmailMessage
from hashlib import sha256

import pytest

from app import monthly_report_sources as sources
from app import monthly_report_library as library
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)


NOTICE = "Nested email retained in the original; save its attachments separately."
PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)


def mail(body="Synthetic outer work summary.", *, subject="Synthetic Outer", html=None):
    msg = EmailMessage()
    msg["From"] = "synthetic-sender@example.invalid"
    msg["Subject"] = subject
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    return msg


def direct(msg, name, payload):
    msg.add_attachment(payload, maintype="application",
                       subtype="octet-stream", filename=name)


def forward(msg, nested, *, name="forwarded.eml"):
    msg.add_attachment(nested, subtype="rfc822", filename=name)


@pytest.mark.parametrize("mode", ("named", "inline", "anonymous"))
def test_one_forwarded_message_excludes_its_internal_attachment_but_keeps_direct_siblings(mode):
    outer = mail()
    direct(outer, "first.txt", b"Direct first synthetic document")
    nested = mail("Private nested details.", subject="Nested Subject")
    direct(nested, "same.txt", b"Private nested canary")
    if mode == "named":
        forward(outer, nested)
    elif mode == "inline":
        outer.add_attachment(nested, subtype="rfc822", disposition="inline")
    else:
        outer.add_attachment(nested, subtype="rfc822")
    direct(outer, "same.txt", b"Direct duplicate filename with other bytes")
    before = outer.as_bytes()
    text, attachments, notices = sources._email(before)
    assert "Synthetic outer work summary." in text
    assert "Private nested canary" not in text
    assert attachments == (
        ("first.txt", b"Direct first synthetic document"),
        ("same.txt", b"Direct duplicate filename with other bytes"),
    )
    assert notices == (NOTICE,)
    assert before == outer.as_bytes()


def test_multiple_forwarded_messages_are_pruned_without_dropping_outer_attachments():
    outer = mail()
    for index in range(4):
        inner = mail(subject=f"Synthetic nested {index}")
        direct(inner, f"private-{index}.txt", f"Forbidden nested {index}".encode())
        forward(outer, inner, name=f"nested-{index}.eml")
        direct(outer, f"ordinary-{index}.txt", f"Allowed outer {index}".encode())
    text, attached, notices = sources._email(outer.as_bytes())
    assert attached == tuple(
        (f"ordinary-{index}.txt", f"Allowed outer {index}".encode()) for index in range(4))
    assert notices == (NOTICE,) * 4
    assert "Synthetic outer work summary." in text
    assert not any(name.startswith("private-") for name, _ in attached)


def test_deeply_forwarded_message_does_not_expose_multiple_inner_levels():
    outer, child, grandchild = mail(), mail("Private level one."), mail("Private level two.")
    direct(grandchild, "deep-secret.txt", b"Must not be imported")
    direct(child, "middle-secret.txt", b"Also private")
    forward(child, grandchild, name="deep.eml")
    forward(outer, child, name="middle.eml")
    direct(outer, "top-level.txt", b"Valid sibling")
    text, attached, notices = sources._email(outer.as_bytes())
    assert attached == (("top-level.txt", b"Valid sibling"),)
    assert notices == (NOTICE,)
    assert "Private level" not in text
    # Explicit upload is separate and retains its own safety budget.
    separate_text, separate_files, separate_notices = sources._email(child.as_bytes())
    assert "Private level one." in separate_text
    assert separate_files == (("middle-secret.txt", b"Also private"),)
    assert separate_notices == (NOTICE,)


def test_multipart_alternative_html_and_direct_related_attachment_are_preserved():
    outer = mail(
        "Outer plain body.", html="<html><body><p>Outer HTML body.</p></body></html>")
    alternative = outer.get_payload()[-1]
    alternative.add_related(
        b"synthetic-image-bytes", maintype="image", subtype="png",
        filename="inline-asset.png", cid="<synthetic-inline>")
    direct(outer, "direct-data.csv", b"Asset,Status\nP-1,Reviewed\n")
    nested = mail("Nested contents.")
    direct(nested, "nested-should-not-read.txt", b"Not a direct attachment")
    forward(outer, nested)
    text, attachments, notices = sources._email(outer.as_bytes())
    assert "Outer plain body." in text
    assert attachments == (
        ("inline-asset.png", b"synthetic-image-bytes"),
        ("direct-data.csv", b"Asset,Status\nP-1,Reviewed\n"),
    )
    assert notices == (NOTICE,)


@pytest.mark.parametrize("name", ("same.txt", "shared.dat"))
def test_matching_inner_and_outer_names_are_not_deduplicated_or_confused(name):
    outer = mail()
    direct(outer, name, b"Only outer bytes")
    nested = mail()
    direct(nested, name, b"Only nested bytes")
    forward(outer, nested)
    direct(outer, name, b"Second direct bytes")
    _, attachments, notices = sources._email(outer.as_bytes())
    assert attachments == ((name, b"Only outer bytes"), (name, b"Second direct bytes"))
    assert notices == (NOTICE,)


@pytest.mark.parametrize("direct_count", (1, 2))
def test_nested_children_do_not_consume_direct_attachment_budget(monkeypatch, direct_count):
    monkeypatch.setattr(sources, "MAX_SOURCES", 2)
    outer = mail()
    forwarded = mail()
    for n in range(6):
        direct(forwarded, f"private-{n}.txt", f"private {n}".encode())
    forward(outer, forwarded)
    for n in range(direct_count):
        direct(outer, f"direct-{n}.txt", f"direct {n}".encode())
    _, attachments, notices = sources._email(outer.as_bytes())
    assert len(attachments) == direct_count
    assert tuple(name for name, _ in attachments) == tuple(
        f"direct-{n}.txt" for n in range(direct_count))
    assert notices == (NOTICE,)


def test_existing_direct_attachment_budget_still_rejects_too_many(monkeypatch):
    monkeypatch.setattr(sources, "MAX_SOURCES", 2)
    outer = mail()
    for index in range(3):
        direct(outer, f"direct-{index}.txt", b"Synthetic direct bytes")
    with pytest.raises(ValueError, match="Too many email attachments"):
        sources._email(outer.as_bytes())


@pytest.fixture
def batch(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    outer = mail("Synthetic outer inspection.")
    direct(outer, "valid-one.txt", b"Inspected synthetic equipment P-1.")
    nested = mail("Private forwarded content.")
    direct(nested, "malformed-inner.png", b"not-a-PNG")
    direct(nested, "private-attachment.txt", b"Private nested document")
    forward(outer, nested)
    direct(outer, "valid-two.txt", b"Confirmed synthetic valve V-2 was checked.")
    return outer.as_bytes(), nested.as_bytes()


def test_actual_batch_keeps_valid_siblings_and_original_but_never_sees_nested_bad_file(batch):
    raw, nested_raw = batch
    parsed, messages = sources.ingest_batch(PROFILE, (("synthetic-outer.eml", raw),))
    assert not any("malformed-inner" in m or "private-attachment" in m for m in messages)
    assert not messages
    assert {c.source.filename for c in parsed} == {
        "synthetic-outer.eml", "valid-one.txt", "valid-two.txt"}
    by_name = {c.source.filename: c for c in parsed}
    assert sources.source_bytes(PROFILE, by_name["synthetic-outer.eml"].source) == raw
    assert sources.source_bytes(PROFILE, by_name["valid-one.txt"].source) == b"Inspected synthetic equipment P-1."
    assert sources.source_bytes(PROFILE, by_name["valid-two.txt"].source) == b"Confirmed synthetic valve V-2 was checked."
    assert NOTICE in by_name["synthetic-outer.eml"].source.notices
    for forbidden in ("malformed-inner.png", "private-attachment.txt", "forwarded.eml"):
        assert forbidden not in by_name
    # Explicitly uploading the nested source separately is allowed, but it
    # never enters the outer email batch without that deliberate separate act.
    nested, extra = sources.ingest_batch(PROFILE, (("explicit-forwarded.eml", nested_raw),), parsed)
    assert {x.source.filename for x in nested} == {
        "synthetic-outer.eml", "valid-one.txt", "valid-two.txt",
        "explicit-forwarded.eml", "private-attachment.txt"}
    assert any("malformed-inner.png" in m and "Not read" in m for m in extra)
    assert sources.source_bytes(
        PROFILE, next(c.source for c in nested if c.source.filename == "synthetic-outer.eml")) == raw


def test_batch_reimport_is_idempotent_and_preserves_existing_review_edits(batch):
    raw, _ = batch
    initial, messages = sources.ingest_batch(PROFILE, (("outer.eml", raw),))
    assert not messages
    reviewed = tuple(replace(item, source=replace(item.source,
        vendor="Synthetic Verified Vendor",
        classification="Vendor service")) if item.source.filename == "valid-one.txt" else item
        for item in initial)
    repeated, notices = sources.ingest_batch(PROFILE, (("outer.eml", raw),), reviewed)
    assert repeated == reviewed
    assert notices == ("Duplicate skipped: outer.eml",)
    assert sources.source_bytes(
        PROFILE, next(c.source for c in repeated if c.source.filename == "outer.eml")) == raw


def test_batch_does_not_remove_prior_snapshot_or_another_contract_source(batch):
    raw, _ = batch
    first, _ = sources.ingest_batch(PROFILE, (("outer.eml", raw),))
    manual = ResolvedBlock(
        "activity_summary", "This month", text="Independent reviewed operator note.")
    draft = ReportDraft(PROFILE, PERIOD, "Synthetic Editor", default_sections(),
                        (manual,), sources=tuple(c.source for c in first))
    saved = library.save_snapshot(
        draft, expected_revision=0, entered_editor="Synthetic Editor")
    later, messages = sources.ingest_batch(PROFILE, (("outer.eml", raw),), first)
    assert later == first and messages == ("Duplicate skipped: outer.eml",)
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == saved
    other_profile = replace(PROFILE, contract="Foreign Synthetic Contract", key="foreign")
    other, _ = sources.ingest_batch(
        other_profile, (("unrelated.txt", b"Different contract synthetic report."),))
    assert len(other) == 1
    assert sources.source_bytes(other_profile, other[0].source) == b"Different contract synthetic report."
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == saved
    assert sources.source_bytes(PROFILE, first[0].source) == raw
