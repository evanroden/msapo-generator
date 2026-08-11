from types import SimpleNamespace

from app import web_ui


def _analysis():
    return SimpleNamespace(
        facility_name="United Memorial Medical Center",
        facility_address="127 North St, Batavia, NY 14020",
        work_category="repairs",
    )


def test_generation_prefers_confirmed_routing_when_widget_keys_are_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        web_ui.contracts,
        "match_facility",
        lambda *_args: ("Rochester Regional Health", "UMMC"),
    )
    monkeypatch.setattr(
        web_ui.contracts,
        "sites_for_contract",
        lambda contract: ["Tulane Medical Center"] if contract == "Tulane" else [],
    )
    monkeypatch.setattr(
        web_ui,
        "st",
        SimpleNamespace(
            session_state={
                "routing_quote123": {
                    "contract": "Tulane",
                    "site": "Tulane Medical Center",
                }
            }
        ),
    )

    contract, site, facility, address = web_ui._routing_for_generation(
        _analysis(), "Batavia quote", "quote123"
    )

    assert contract == "Tulane"
    assert site == "Tulane Medical Center"
    assert facility == "Tulane Medical Center"
    assert address == ""


def test_generation_falls_back_to_detected_routing_before_confirmation(monkeypatch):
    monkeypatch.setattr(
        web_ui.contracts,
        "match_facility",
        lambda *_args: ("Rochester Regional Health", "UMMC"),
    )
    monkeypatch.setattr(
        web_ui,
        "st",
        SimpleNamespace(session_state={}),
    )

    contract, site, facility, address = web_ui._routing_for_generation(
        _analysis(), "Batavia quote", "quote123"
    )

    assert contract == "Rochester Regional Health"
    assert site == "UMMC"
    assert facility == "United Memorial Medical Center"
    assert address == "127 North St, Batavia, NY 14020"
