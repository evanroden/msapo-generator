"""The acceptance ledger must not mislabel browser emulation as hardware."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qa_device_metadata import browser_evidence


class PageStub:
    def __init__(self):
        self.context = SimpleNamespace(browser=SimpleNamespace(version='145.0.7632.6'))
        self.evaluations = []

    def evaluate(self, script):
        self.evaluations.append(script)
        return {'user_agent': 'fixture', 'platform': 'Linux', 'max_touch_points': 0,
                'coarse_pointer': False, 'fine_pointer': True,
                'viewport': {'width': 390, 'height': 844},
                'visual_viewport': {'width': 390, 'height': 844, 'scale': 1}}


def test_browser_report_records_real_method_without_physical_claim():
    page = PageStub()
    receipt = browser_evidence(page, engine='chromium', input_method='Playwright pointer and keyboard')
    assert receipt['engine'] == 'chromium'
    assert receipt['browser_version'] == '145.0.7632.6'
    assert receipt['input_method'] == 'Playwright pointer and keyboard'
    assert receipt['browser_observed']['viewport'] == {'width': 390, 'height': 844}
    assert page.evaluations and 'navigator.userAgent' in page.evaluations[0]
    assert receipt['host_arch']
    assert all(receipt[key] is False for key in (
        'physical_device', 'physical_safari', 'screen_reader_listening',
        'native_ime', 'native_browser_zoom'))
    assert 'no screen-reader listening' in receipt['accessibility_method']


def test_missing_browser_fails_instead_of_inventing_version():
    page = PageStub()
    page.context.browser = None
    try:
        browser_evidence(page, engine='webkit', input_method='Playwright keyboard')
    except AssertionError as exc:
        assert 'unavailable' in str(exc)
    else:
        raise AssertionError('An absent browser must not produce a pass')
