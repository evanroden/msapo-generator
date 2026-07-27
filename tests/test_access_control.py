from app.access_control import configured_password, password_matches


def test_access_password_is_required(monkeypatch):
    monkeypatch.delenv("EPC_ACCESS_PASSWORD", raising=False)
    assert configured_password() is None


def test_configured_password_is_returned_exactly(monkeypatch):
    monkeypatch.setenv("EPC_ACCESS_PASSWORD", "  internal password  ")
    assert configured_password() == "  internal password  "


def test_password_comparison_requires_exact_match():
    expected = "correct horse battery staple"

    assert password_matches(expected, expected)
    assert not password_matches("Correct horse battery staple", expected)
    assert not password_matches("correct horse battery staple ", expected)
