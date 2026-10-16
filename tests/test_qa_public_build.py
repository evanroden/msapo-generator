"""Build readers use About without changing routes or weakening exact SHA checks."""

from scripts.qa_public_build import running_code_marker


class Marker:
    def __init__(self, page):
        self.page = page
        self.waits = []

    @property
    def first(self):
        return self

    def wait_for(self, *, state, timeout):
        self.waits.append(state)
        if state == "visible":
            assert self.page.visible

    def is_visible(self):
        return self.page.visible


class About:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def filter(self, *, has):
        assert has == "about-label"
        return self

    def locator(self, selector):
        assert selector == "summary"
        return self

    def click(self, *, timeout):
        self.page.clicks += 1
        self.page.visible = True


class Page:
    def __init__(self, visible):
        self.visible = visible
        self.clicks = 0
        self.marker = Marker(self)

    def get_by_text(self, value, **kwargs):
        if value == "About":
            assert kwargs == {"exact": True}
            return "about-label"
        assert value.pattern == "^Running code:"
        return self.marker

    def get_by_test_id(self, value):
        assert value == "stExpander"
        return About(self)


def test_visible_prior_build_marker_is_observed_without_extra_ui_action():
    page = Page(True)
    assert running_code_marker(page) is page.marker
    assert page.clicks == 0 and page.marker.waits == ["attached", "visible"]


def test_closed_about_opens_once_then_returns_the_same_marker():
    page = Page(False)
    assert running_code_marker(page) is page.marker
    assert page.clicks == 1 and page.marker.waits == ["attached", "visible"]
