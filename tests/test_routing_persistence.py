from types import SimpleNamespace

from app import web_ui


def _analysis(*, work_category="repairs"):
    return SimpleNamespace(
        facility_name="United Memorial Medical Center",
        facility_address="127 North St, Batavia, NY 14020",
        work_category=work_category,
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
        web_ui.contracts,
        "is_known_contract",
        lambda contract: contract in {"Rochester Regional Health", "Tulane"},
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


def test_unconfigured_mirrored_contract_is_rejected(monkeypatch):
    monkeypatch.setattr(
        web_ui.contracts,
        "match_facility",
        lambda *_args: ("Rochester Regional Health", "UMMC"),
    )
    monkeypatch.setattr(
        web_ui,
        "st",
        SimpleNamespace(
            session_state={
                "routing_quote123": {
                    "contract": "Unconfigured Contract",
                    "site": "Invented Site",
                }
            }
        ),
    )

    contract, site, facility, _ = web_ui._routing_for_generation(
        _analysis(), "Batavia quote", "quote123"
    )

    assert contract == "Rochester Regional Health"
    assert site == "UMMC"
    assert facility == "United Memorial Medical Center"


def test_missing_or_invalid_rrh_category_stays_unresolved(monkeypatch):
    monkeypatch.setattr(web_ui, "st", SimpleNamespace(session_state={}))

    for category in (None, "not_a_real_category"):
        snapshot = web_ui._routing_snapshot(
            _analysis(work_category=category), "Batavia quote", "quote123"
        )

        assert snapshot.contract == "Rochester Regional Health"
        assert snapshot.site == "UMMC"
        assert snapshot.category_label == ""
        assert snapshot.cost_code == ""


def test_explicit_routing_placeholders_do_not_fall_back_to_detection(monkeypatch):
    monkeypatch.setattr(
        web_ui,
        "st",
        SimpleNamespace(
            session_state={"contract_quote123": web_ui.CONTRACT_PLACEHOLDER}
        ),
    )
    contract_cleared = web_ui._routing_snapshot(
        _analysis(), "Batavia quote", "quote123"
    )
    assert contract_cleared.contract == ""

    web_ui.st.session_state = {
        "contract_quote123": "Rochester Regional Health",
        "site_quote123": web_ui.SITE_PLACEHOLDER,
    }
    site_cleared = web_ui._routing_snapshot(
        _analysis(), "Batavia quote", "quote123"
    )
    assert site_cleared.contract == "Rochester Regional Health"
    assert site_cleared.site == ""


def test_explicit_category_placeholder_stays_unresolved(monkeypatch):
    monkeypatch.setattr(
        web_ui,
        "st",
        SimpleNamespace(
            session_state={
                "contract_quote123": "Rochester Regional Health",
                "site_quote123": "UMMC",
                "cat_quote123_united_memorial": web_ui.CATEGORY_PLACEHOLDER,
            }
        ),
    )

    snapshot = web_ui._routing_snapshot(
        _analysis(), "Batavia quote", "quote123"
    )
    assert snapshot.category_label == ""
    assert snapshot.cost_code == ""
