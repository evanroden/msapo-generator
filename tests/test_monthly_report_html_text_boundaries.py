"""Real HTML email intake keeps visible cells and statements separate."""
from dataclasses import replace
from email.message import EmailMessage
import hashlib

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return profile


def _lines(html):
    return tuple(line.strip() for line in sources._plain_html(html).splitlines() if line.strip())


def _email(html, *, plain=None, attachment=False):
    message = EmailMessage()
    message["From"] = "vendor@example.invalid"
    message["Subject"] = "Synthetic service report"
    if plain is None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
    if attachment:
        message.add_attachment(b"Completed: checked synthetic gauge.", maintype="text",
                               subtype="plain", filename="direct.txt")
    return message.as_bytes()


@pytest.mark.parametrize("tag", ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                                 "blockquote", "pre", "dt", "dd"])
def test_block_boundaries_do_not_join_adjacent_source_words(tag):
    assert _lines(f"Before<{tag}>Inside</{tag}>After") == ("Before", "Inside", "After")


@pytest.mark.parametrize("cells", ["<td>12</td><td>34</td>", "<th>12</th><th>34</th>",
                                   "<td>12<td>34", "<th>12<th>34"])
def test_cell_boundaries_cannot_manufacture_a_combined_number(cells):
    text = sources._plain_html(f"<table><tr>{cells}</tr></table>")
    assert text.split() == ["12", "34"]
    assert "1234" not in text


def test_table_rows_headings_and_surrounding_text_stay_separate():
    text = sources._plain_html("Before<table><tr><th>Reading</th><th>Limit</th></tr>"
                               "<tr><td>12</td><td>34</td></tr></table>After")
    assert [line.split() for line in text.splitlines() if line.strip()] == [
        ["Before"], ["Reading", "Limit"], ["12", "34"], ["After"]]


def test_inline_markup_entities_unicode_and_negation_remain_in_one_statement():
    html = '<p>Inspected CH-<b>12</b>: did <em>not</em> start &amp; pressure was 12.5\u00b0F.</p>'
    assert _lines(html) == ("Inspected CH-12: did not start & pressure was 12.5\u00b0F.",)


def test_scripts_styles_comments_and_remote_attributes_are_not_source_text():
    html = ('<style>.x { content: "PRIVATE STYLE" }</style><!-- PRIVATE COMMENT -->'
            '<p>Visible<img src="https://example.invalid/private" alt="PRIVATE ALT"> text.</p>'
            '<script>document.write("PRIVATE SCRIPT")</script>Tail')
    assert _lines(html) == ("Visible text.", "Tail")


def test_list_items_and_br_variants_keep_their_boundaries():
    assert _lines('<ul><li>Inspected pump.</li><li>Pending replacement.</li></ul>'
                  'One<br>Two<br/>Three') == (
        "Inspected pump.", "Pending replacement.", "One", "Two", "Three")


def test_plain_email_preference_is_unchanged():
    raw = _email('<p>UNSELECTED HTML</p>', plain="Completed: inspected synthetic filter.")
    text, attachments, notices = sources._email(raw)
    assert "Completed: inspected synthetic filter." in text
    assert "UNSELECTED HTML" not in text
    assert attachments == notices == ()


def test_real_html_email_keeps_vendor_and_work_status_fields_separate(profile):
    html = ('<h2>Vendor service report</h2><ul><li>Vendor: Example Mechanical</li>'
            '<li>Date: 2026-09-12</li><li>Completed: inspected pump A.</li>'
            '<li>Pending: replace seal B.</li></ul>')
    raw = _email(html, attachment=True)
    result, messages = sources.ingest_batch(profile, (("service.eml", raw),))
    assert not messages
    assert len(result) == 2
    source = result[0].source
    assert source.vendor == "Example Mechanical"
    assert source.service_date == "2026-09-12"
    assert source.actions == "Completed: inspected pump A."
    assert source.follow_ups == "Pending: replace seal B."
    assert source.sha256 == hashlib.sha256(raw).hexdigest()
    assert sources.source_bytes(profile, source) == raw
    assert sources.source_bytes(profile, result[1].source) == b"Completed: checked synthetic gauge."


def test_batch_failure_reupload_and_saved_review_do_not_rewrite_originals(profile):
    raw = _email('<table><tr><th>Reading</th><th>Limit</th></tr>'
                 '<tr><td>12</td><td>34</td></tr></table>')
    result, messages = sources.ingest_batch(profile, (("readings.eml", raw),
        ("broken.png", b"not a picture"), ("good.txt", b"Inspected synthetic filter.")))
    assert len(result) == 2
    assert len(messages) == 1 and messages[0].startswith("Not read: broken.png.")
    source = result[0].source
    assert "1234" not in source.page_texts[0]
    assert "ReadingLimit" not in source.page_texts[0]
    reviewed = replace(result[0], source=replace(source, actions="Operator's reviewed wording.",
                                                 selected_pages=(), vendor="Reviewed vendor"))
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 9)), sources=(reviewed.source, result[1].source))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    again, duplicate = sources.ingest_batch(profile, (("renamed.eml", raw),), (reviewed, result[1]))
    assert again == (reviewed, result[1])
    assert duplicate == ("Duplicate skipped: renamed.eml",)
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened.draft == saved.draft
    assert library.load_snapshot_version(profile.contract, profile.key, draft.period, 1).draft == saved.draft
    assert sources.source_bytes(profile, reviewed.source) == raw
    assert sources.source_bytes(profile, result[1].source) == b"Inspected synthetic filter."
