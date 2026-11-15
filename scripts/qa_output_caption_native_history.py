"""Native history navigation for the unchanged external caption assertions.

The first retained probe missed this collapsed disclosure before it could save.
This adapter changes only browser navigation, never product code or assertions.
"""
from playwright.sync_api import expect
from scripts import qa_output_caption_production as acceptance

original_save = acceptance.save_version


def native_save(page, revision):
    history = page.locator("details").filter(
        has=page.locator("summary").filter(has_text="Shared report history"))
    expect(history).to_have_count(1)
    if history.get_attribute("open") is None:
        history.locator("summary").click()
    expect(history).to_have_attribute("open", "")
    original_save(page, revision)
    # History must not force a refresh after first generation and hide the
    # stale-snapshot defect. Close it before returning to the export controls.
    if history.get_attribute("open") is not None:
        history.locator("summary").click()
    expect(history).not_to_have_attribute("open", "")
    print("PASS Native history opened for checkpoint and closed before generation", flush=True)


if __name__ == "__main__":
    acceptance.save_version = native_save
    acceptance.run()
