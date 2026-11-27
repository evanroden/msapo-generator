"""Compact navigation remains reachable without a full-width white overlay."""
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'app'
CSS=(ROOT/'workspace_layout.css').read_text()
INITIAL=(ROOT/'workspace_initial.css').read_text()


def declarations(text, selector_fragment):
    return [body for selector,body in re.findall(r'([^{}]+)\{([^{}]*)\}',text) if selector_fragment in selector]


def test_monthly_wrapper_sticks_but_empty_area_passes_pointer_events():
    rules=declarations(CSS,':has(> .st-key-monthly_report_navigation)')
    assert rules and any('position:sticky' in r and 'pointer-events:none' in r for r in rules)


def test_control_capsule_has_bounded_width_and_remains_interactive():
    rules=declarations(INITIAL,'.epc-section-navigation')
    assert any('width:min(100%,25rem)' in r and '25rem' in r and 'pointer-events:auto' in r for r in rules)
    wrappers=declarations(INITIAL,'.st-key-monthly_report_navigation')
    assert any('background:transparent' in r and 'border:0' in r for r in wrappers)


def test_review_controls_are_fixed_compact_and_reference_can_stick():
    assert any('position:fixed' in r and '25rem' in r for r in declarations(CSS,'.epc-section-navigation'))
    assert any('position:sticky' in r for r in declarations(CSS,'.epc-workspace-reference'))


def test_progress_absorbs_attention_width_without_moving_next():
    assert any('flex:1 1 0' in rule for rule in declarations(INITIAL,'.epc-section-progress'))


def test_attention_leaves_room_for_section_progress_on_small_screens():
    assert any('max-width:38%' in rule for rule in declarations(INITIAL,'.epc-navigation-attention'))
