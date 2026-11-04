"""Section navigation must not obscure the report while scrolling."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / 'app/workspace_layout.css').read_text()


def declarations(selector_fragment):
    return [body for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', CSS)
            if selector_fragment in selector]


def test_monthly_navigation_wrapper_remains_in_document_flow():
    rules = declarations(':has(> .st-key-monthly_report_navigation)')
    assert rules and all(not re.search(r'position\s*:\s*(?:sticky|fixed)', r) for r in rules)


def test_open_review_does_not_pin_navigation_over_editor_or_preview():
    rules = declarations('.epc-section-navigation')
    assert all(not re.search(r'position\s*:\s*(?:sticky|fixed)', r) for r in rules)


def test_reference_preview_can_still_remain_sticky():
    assert any(re.search(r'position\s*:\s*sticky', r) for r in declarations('.epc-workspace-reference'))
