"""Bounded passive metadata around the existing synthetic navigation gesture."""
from contextlib import contextmanager
import json
import math
from pathlib import Path

INSTALL = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
STOP = """() => {const observer=window.__enfraNavigationObservation;
    try {return observer?.stop?.() || null;}
    finally {delete window.__enfraNavigationObservation;}}"""
MAX_BYTES = 1024 * 1024


# Fail closed on unexpected browser payloads; never serialize exception text.
_KEYS = frozenset("""schema limits records bytes dropped errors disposed sequence at_ms source native
 type trusted prevented target key button root_count root app port nav id connected current direct_stale
 state_id controller_id report_ordinal render_changed mode owns_scroll root_scroll port_scroll viewport
 width height script_state back next count disabled handler has_handler status index focus kind active_index
 layout_active_index jump_index jump_scroll landing_index review_navigation explicit_review request_index
 request_present input_serial sections_count sections_truncated review_count order marker origin destination
 focus_hidden stale_count hidden_stale visible_stale scan_truncated intent owner_id owner_matches report_matches
 origin_index target_index origin_matches request_matches input_matches back_matches next_matches nodes_match""".split())
_STRINGS = frozenset({'installed', 'finally', 'mutation', 'resize', 'layout', 'native-capture',
    'native-after-dispatch', 'keydown', 'keyup', 'click', 'focusin', 'focusout', 'Enter', ' ', 'Tab',
    'ArrowUp', 'ArrowDown', 'Escape', 'wide', 'compact', 'book', 'tabletop', 'running', 'notRunning',
    'next', 'back', 'editor', 'section', 'other'})


def _valid_metadata(value):
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        return value in _STRINGS
    if isinstance(value, list):
        return len(value) <= 256 and all(_valid_metadata(item) for item in value)
    if isinstance(value, dict):
        return all(key in _KEYS and _valid_metadata(item) for key, item in value.items())
    return False


def _bounded_result(result, installed):
    if not isinstance(result, dict) or set(result) != {'schema', 'limits', 'dropped', 'errors', 'disposed', 'records'} or \
            result.get('schema') != 1 or result.get('limits') != {'records': 256, 'bytes': MAX_BYTES} or \
            not isinstance(result.get('records'), list) or not _valid_metadata(result):
        return {'schema': 1, 'schema_rejected': True, 'installation_completed': installed}
    result = dict(result, installation_completed=installed)
    if len(json.dumps(result, ensure_ascii=True).encode('utf-8')) > MAX_BYTES:
        return {'schema': 1, 'oversize_rejected': True, 'installation_completed': installed}
    return result


@contextmanager
def observe_navigation(page, evidence):
    """Never mask an original action/assertion failure with diagnostic failure."""
    installed = False
    try:
        try:
            installed = bool((page.evaluate(INSTALL) or {}).get('installed'))
        except Exception:
            pass
        yield
    finally:
        try:
            result = page.evaluate(STOP)
            record = _bounded_result(result, installed)
        except Exception:
            record = {'schema': 1, 'collection_error': True, 'installation_completed': installed}
        try:
            evidence['navigation_observation'] = record
        except Exception:
            pass
