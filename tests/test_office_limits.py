"""Disposable cache controls must not alter document or PDF export settings."""
from xml.etree import ElementTree as ET

from app.office_limits import prepare_profile


def test_graphics_can_be_swapped_during_short_exports(tmp_path):
    profile = tmp_path / 'office'
    uri = prepare_profile(profile)
    assert uri == profile.resolve().as_uri()
    root = ET.parse(profile / 'user' / 'registrymodifications.xcu').getroot()
    oor = '{http://openoffice.org/2001/registry}'
    items = root.findall('item')
    assert len(items) == 1
    assert items[0].get(oor + 'path') == '/org.openoffice.Office.Common/Cache/GraphicManager'
    values = {prop.get(oor + 'name'): prop.findtext('value') for prop in items[0]}
    assert values == {'GraphicMemoryLimit': str(48 * 1024 * 1024),
                      'GraphicSwappingEnabled': 'true', 'GraphicAllowedIdleTime': '0'}
    # The old ten-second idle floor defeated the threshold during short CLI
    # exports. Changing that floor cannot set image quality or resampling.
    assert all(prop.get(oor + 'op') == 'fuse' for prop in items[0])
