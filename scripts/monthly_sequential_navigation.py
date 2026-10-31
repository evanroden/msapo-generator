"""Native sequential navigation for hosted QA; no scrolling or click retries."""

import re


def section_order(page):
    entries = page.locator('.epc-workspace [data-epc-pair]').evaluate_all(
        'nodes => nodes.map(n => ({id:n.dataset.epcPair,title:n.dataset.epcTitle}))')
    if page.locator('#report-review').count():
        entries.append({'id': 'report_review', 'title': 'Review and download'})
    assert entries and len({entry['id'] for entry in entries}) == len(entries)
    return entries


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
        if keyboard:
            control.focus()
            expect(control).to_be_focused()
            control.press('Enter')
        else:
            control.click()
        expect(progress).to_have_attribute('data-section', ids[index])
        expect(progress).to_have_text(f"{index + 1} of {len(entries)} · {entries[index]['title']}")
    if finish == 0:
        expect(page.locator('.epc-section-back')).to_be_disabled()
    if finish == len(entries) - 1:
        expect(page.locator('.epc-section-next')).to_be_disabled()
