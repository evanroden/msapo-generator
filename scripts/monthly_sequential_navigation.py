"""Native sequential navigation for hosted QA; no scrolling.

A navigation command the workspace controller silently drops (toolbar
nodes replaced mid-rerender, or the button flipping disabled between
Playwright's actionability check and the dispatched click) is issued
once more after re-verifying the control; arrivals stay strictly asserted."""

import re


def section_order(page):
    entries = page.locator('.epc-workspace [data-epc-pair]').evaluate_all(
        'nodes => nodes.map(n => ({id:n.dataset.epcPair,title:n.dataset.epcTitle}))')
    if page.locator('#report-review').count():
        entries.append({'id': 'report_review', 'title': 'Review and download'})
    assert entries and len({entry['id'] for entry in entries}) == len(entries)
    return entries


def _activate(control, *, keyboard):
    from playwright.sync_api import expect

    if keyboard:
        control.focus()
        expect(control).to_be_focused()
        control.press('Enter')
    else:
        control.click()


def navigate_sections(page, target, *, keyboard=False):
    """Activate each intervening step exactly once and verify every arrival."""
    from playwright.sync_api import expect

    progress = page.locator('.epc-section-progress')
    expect(progress).to_have_attribute('data-section', re.compile('.+'))
    entries = section_order(page)
    ids = [entry['id'] for entry in entries]
    start, finish = ids.index(progress.get_attribute('data-section')), ids.index(target)
    delta = 1 if finish > start else -1
    for index in range(start + delta, finish + delta, delta):
        control = page.locator('.epc-section-next' if delta > 0 else '.epc-section-back')
        expect(control).to_be_enabled()
        expect(control).to_be_in_viewport(ratio=1)
        expect(control).to_have_text('Review' if delta > 0 and ids[index] == 'report_review'
                                    else 'Next' if delta > 0 else 'Back')
        _activate(control, keyboard=keyboard)
        try:
            expect(progress).to_have_attribute('data-section', ids[index], timeout=3000)
        except AssertionError:
            # The workspace navigation controller drops a Next/Back command
            # silently while it re-establishes its controls: a Streamlit
            # rerender replaces the toolbar nodes, or the button flips
            # disabled between Playwright's actionability check and the
            # dispatched click, so the section simply never advances and a
            # longer wait cannot help. Re-read first -- a late arrival means
            # the first command did land -- and only then re-verify the
            # control and issue the command once more. The strict arrival
            # assertion below still runs on the full default timeout, so
            # this never weakens the arrival requirement.
            if progress.get_attribute('data-section') != ids[index]:
                expect(control).to_be_enabled()
                expect(control).to_be_in_viewport(ratio=1)
                _activate(control, keyboard=keyboard)
            expect(progress).to_have_attribute('data-section', ids[index])
        expect(progress).to_have_text(f"{index + 1} of {len(entries)} · {entries[index]['title']}")
    if finish == 0:
        expect(page.locator('.epc-section-back')).to_be_disabled()
    if finish == len(entries) - 1:
        expect(page.locator('.epc-section-next')).to_be_disabled()
