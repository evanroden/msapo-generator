"""Truthful, bounded environment metadata for synthetic browser acceptance.

This describes the automation host and browser, not a physical phone, native
Safari, a screen reader, or an actual IME. It makes no business requests.
"""
from __future__ import annotations

import platform


def browser_evidence(page, *, engine: str, input_method: str) -> dict:
    """Record the execution method alongside a browser check group.

    The host's machine architecture is not a retail hardware model. DOM media
    query values describe browser *emulation*, not physical pointer hardware.
    """
    observed = page.evaluate("""() => ({
        user_agent: navigator.userAgent,
        platform: navigator.platform,
        max_touch_points: navigator.maxTouchPoints,
        coarse_pointer: matchMedia('(pointer: coarse)').matches,
        fine_pointer: matchMedia('(pointer: fine)').matches,
        viewport: {width: innerWidth, height: innerHeight},
        visual_viewport: window.visualViewport ? {
            width: visualViewport.width,
            height: visualViewport.height,
            scale: visualViewport.scale
        } : null
    })""")
    browser = page.context.browser
    if browser is None:
        raise AssertionError('Playwright browser identity unavailable')
    return {
        'engine': engine,
        'browser_version': browser.version,
        'host_os': platform.platform(),
        'host_arch': platform.machine(),
        'hardware_model': 'NOT REPORTED: hosted/local VM, not verified physical device',
        'browser_automation': 'Playwright',
        'input_method': input_method,
        'accessibility_method': 'Programmatic DOM/role/name/label assertions where scripted; no screen-reader listening',
        'physical_device': False,
        'physical_safari': False,
        'screen_reader_listening': False,
        'native_ime': False,
        'native_browser_zoom': False,
        'segment_geometry': 'Injected viewport segments where scripted; not real fold/posture',
        'browser_observed': observed,
    }
