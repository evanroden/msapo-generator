"""Read-only receipts for the marked synthetic warning-route fixture only.

No callbacks, retries, timings, generation policy or widget values are changed.
The bounded receipt fields contain no report text, filenames or identities.
"""
from contextlib import contextmanager
from functools import wraps
import json
from time import monotonic

from scripts.workspace_browser_observations import require_synthetic_root


def _append(path, event, **values):
    allowed = {'pressed', 'disabled', 'fragment', 'elapsed_ms', 'pdf_bytes', 'docx_bytes'}
    if event not in {'render_enter', 'button_return', 'generation_enter', 'generation_return',
                     'generation_error', 'package_replace_enter', 'package_replace_return',
                     'render_return', 'render_error'} or set(values) - allowed:
        raise ValueError('Invalid synthetic final-action observation.')
    if any(type(value) not in (bool, int) for value in values.values()):
        raise ValueError('Synthetic observations permit only booleans and integers.')
    with path.open('a', encoding='ascii') as stream:
        stream.write(json.dumps({'event': event, **values}, sort_keys=True) + '\n')


@contextmanager
def observe_final_action(base):
    require_synthetic_root(base)
    from pathlib import Path
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    from app import monthly_report_guided as guided, monthly_report_output_ui as output
    path = Path(base) / 'synthetic-final-action-receipts.jsonl'
    # Each fixture runs in a dedicated process. Restore every wrapper even if
    # Streamlit interrupts the full run or a native conversion fails.
    original_button, original_generate = guided.st.button, guided.generate_report
    original_replace = output.replace_current_session_pdf_package
    context = get_script_run_ctx()
    _append(path, 'render_enter', fragment=bool(context and context.fragment_ids_this_run))

    @wraps(original_button)
    def button(label, *args, **kwargs):
        pressed = original_button(label, *args, **kwargs)
        if label == 'Create Word and PDF':
            _append(path, 'button_return', pressed=bool(pressed), disabled=bool(kwargs.get('disabled')))
        return pressed

    @wraps(original_generate)
    def generate(*args, **kwargs):
        start = monotonic()
        _append(path, 'generation_enter')
        try:
            package = original_generate(*args, **kwargs)
        except BaseException:
            _append(path, 'generation_error', elapsed_ms=int(1000 * (monotonic() - start)))
            raise
        _append(path, 'generation_return', elapsed_ms=int(1000 * (monotonic() - start)),
                pdf_bytes=len(package.pdf or b''), docx_bytes=len(package.docx or b''))
        return package

    @wraps(original_replace)
    def replace_package(*args, **kwargs):
        _append(path, 'package_replace_enter')
        value = original_replace(*args, **kwargs)
        _append(path, 'package_replace_return')
        return value

    guided.st.button, guided.generate_report = button, generate
    output.replace_current_session_pdf_package = replace_package
    try:
        yield
    except BaseException:
        _append(path, 'render_error')
        raise
    else:
        _append(path, 'render_return')
    finally:
        guided.st.button, guided.generate_report = original_button, original_generate
        output.replace_current_session_pdf_package = original_replace
