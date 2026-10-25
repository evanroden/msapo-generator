"""One Add action asks the browser, once, to focus its new row's text.

The browser side is covered by tests/workspace_navigation_test.cjs and the
Chromium/WebKit row-card journey in scripts/qa_report_row_cards.py (#301).
"""
import re

from app.monthly_report_model import ReportTable, ResolvedBlock
from test_monthly_report_rfi_ui import add_request, field, install, press, type_into, workspace
import test_monthly_report_row_cards_ui as cards


def requests(app):
    return [found for element in app.get("html") for found in re.findall(
        r'data-enfra-entry-focus="([^"]+)" data-enfra-entry-field="([^"]+)" data-enfra-entry-origin="([^"]+)"',
        element.proto.body)]


def css(key):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())


def add_button(app, label):
    return next(button for button in app.button if button.label == label)


def test_add_request_asks_once_to_focus_the_requested_item():
    app = workspace()
    assert not requests(app), "an ordinary render never moves focus"
    add_request(app)
    [(nonce, target, origin)] = requests(app)
    assert target == css(field(app, "Requested item").key)
    assert origin == css(add_button(app, "Add request").key)
    app.run()
    assert not requests(app), "a later rerun keeps the reader in place"
    type_into(app, "Requested item", "Confirm the drawing revision.")
    assert not requests(app)
    press(app, "Close editing")
    press(app, "Edit request")
    assert not requests(app), "opening an existing request does not move focus"
    press(app, "Close editing")
    add_request(app)
    [(again, target, _)] = requests(app)
    assert again != nonce and target == css(field(app, "Requested item").key)


def test_an_imported_request_table_focuses_its_own_request_column():
    columns = ("Request #", "System / facility", "Requested details", "Recorded status")
    frame = ReportTable(columns, (("1", "North", "Confirm drawing", "NR"),), "native-frame")
    app = install(workspace(), ResolvedBlock("rfi_matrix", "Last month", extra_tables=(frame,),
                                             references=("synthetic-source",)))
    add_request(app)
    [(_, target, _)] = requests(app)
    assert target == css(field(app, "Requested details").key)


def test_other_card_tables_focus_their_first_field():
    app = cards.workspace("proposals")
    cards.button(app, "Add proposal").click().run()
    assert not app.exception
    [(_, target, origin)] = requests(app)
    assert target == css(cards.field(app, "Proposal #").key)
    assert origin == css(cards.button(app, "Add proposal").key)
