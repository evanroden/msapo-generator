"""A69: first-paint Monthly Training and conservative saved-source event preview."""
from datetime import date
from lxml import html

from app.monthly_report_training import EVENT_REF, load_training
from test_monthly_report_training_retention import training, current, widget, NOTE
from test_monthly_report_training_sessions_ui import fill_session, rows
from test_training_review_flow import report, storage
from test_training_review_ui import open_app


def completed_summary(app):
    # Inspect the rendered semantic table, not the removed lazy native Table.
    markup = next(item.value for item in app.markdown
                  if 'data-enfra-training-summary' in item.value)
    table, = html.fromstring(markup).xpath('.//table')
    headings = table.xpath('./thead/tr/th/text()')
    assert headings == ["Training", "Date", "Method", "Participants", "Hours"]
    return {name: [row[index].text_content() for row in table.xpath('./tbody/tr')]
            for index, name in enumerate(headings)}


def test_month_first_open_entry_and_compact_event_table_survive_retries(training):
    app, draft, matrix, initial, standing, snapshot = training
    annual = next(item for item in app.expander if item.label == "Yearly training requirements")
    assert annual.proto.expanded is False
    add = next(item for item in app.expander if item.label == "Add completed training")
    assert add.proto.expanded is True
    table = completed_summary(app)
    assert table["Training"] == ["Accepted safety event"]
    assert table["Hours"] == ["0.75 hours"]

    widget(app, "text_input", "Training topic").set_value("Current safety refresher")
    widget(app, "date_input", "Training date").set_value(date(2026, 9, 26))
    widget(app, "multiselect", "Participants").set_value(["Synthetic Hospital Tech"])
    widget(app, "text_input", "Hours (optional)").set_value("-2")
    widget(app, "text_area", "Training notes").set_value("Retained during failed validation")
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception
    assert any("positive hours" in error.value for error in app.error)
    assert len(rows(app)) == 1
    assert widget(app, "text_area", "Training notes").value == "Retained during failed validation"
    assert widget(app, "text_input", "Training topic").value == "Current safety refresher"

    widget(app, "text_input", "Hours (optional)").set_value("1")
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception and not app.error
    assert len(rows(app)) == 2
    assert widget(app, "text_input", "Training topic").value == ""
    assert widget(app, "date_input", "Training date").value is None
    assert widget(app, "text_input", "Hours (optional)").value == ""
    assert widget(app, "text_area", "Training notes").value == "Retained during failed validation"
    table = completed_summary(app)
    assert table["Hours"] == ["0.75 hours", "1 hour"]
    fill_session(app, title="Second completed safety refresher", when=date(2026, 9, 27), hours="2")
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception and not app.error
    app.run()
    assert len(rows(app)) == 3
    table = completed_summary(app)
    assert table["Hours"] == ["0.75 hours", "1 hour", "2 hours"]
    assert load_training(draft.profile.contract) == standing
    assert matrix in current(app).extra_tables
    assert current(app).text == "Retained during failed validation"


def test_verified_source_preview_is_current_month_only_without_auto_including(storage):
    raw = (b"Topic,Date,Method,Participants,Hours,Status\n"
           b"Verified course,2026-09-12,Virtual,Alice,1,Completed\n"
           b"Old course,2026-08-12,Virtual,Alice,2,Completed\n"
           b"Scheduled course,2026-09-15,Virtual,Alice,3,Scheduled\n"
           b"No date course,,Virtual,Alice,4,Completed\n"
           b"No hours course,2026-09-16,Virtual,Alice,,Completed\n")
    draft = report(raw)
    app = open_app(draft)
    preview = next(item.value for item in app.dataframe if "Course" in item.value.columns)
    assert preview["Course"].tolist() == ["Verified course", "No hours course"]
    assert preview["Date"].tolist() == ["2026-09-12", "2026-09-16"]
    assert preview["Hours"].tolist() == ["1 hour", "Unknown"]
    assert app.session_state["draft"] == draft
    assert not app.session_state["draft"].source_row_reviews
    assert not any(table.reference == EVENT_REF
                   for table in app.session_state["draft"].blocks[0].extra_tables)
