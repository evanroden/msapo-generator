"""Source-preview controls are separate from every report/editor action."""
from hashlib import sha256
from uuid import uuid4

import streamlit as st

from app import monthly_report_source_render_qa as preview
from app import monthly_report_testing as testing

_PREFIX = 'monthly_qa_source_preview_'


def _invalidate(activate):
    with activate():
        owner = st.session_state.get(_PREFIX + 'owner')
        if owner:
            st.session_state[_PREFIX + 'epoch'] = preview.retire(owner)
        for name in ('pending', 'request', 'receipt', 'error'):
            st.session_state.pop(_PREFIX + name, None)


def _clear(activate, owner, epoch):
    """An old Clear cannot discard a newer selection, even if bytes match."""
    with activate():
        if (st.session_state.get(_PREFIX + 'owner') != owner
                or st.session_state.get(_PREFIX + 'epoch') != epoch):
            return
        try:
            next_epoch = preview.retire(owner, expected_epoch=epoch)
        except (ValueError, OSError):
            return  # A reset/newer incarnation wins; mutate no session state.
        if (st.session_state.get(_PREFIX + 'owner') != owner
                or st.session_state.get(_PREFIX + 'epoch') != epoch):
            return
        st.session_state[_PREFIX + 'epoch'] = next_epoch
        for name in ('pending', 'request', 'receipt', 'error'):
            st.session_state.pop(_PREFIX + name, None)
        st.session_state[_PREFIX + 'uploader_epoch'] = uuid4().hex


def _queue(activate, request, upload_key):
    # Callback arguments bind the rendered selection, not a later same-name file.
    with activate():
        upload = st.session_state.get(upload_key)
        if (not isinstance(request, preview.Request) or not upload
                or str(upload.file_id) != request.upload_id
                or sha256(upload.getvalue()).hexdigest() != request.source_sha256
                or st.session_state.get(_PREFIX + 'epoch') != request.epoch):
            st.session_state[_PREFIX + 'error'] = 'The upload changed. Make a fresh render request.'
            return
        if not st.session_state.get(_PREFIX + 'pending') and not st.session_state.get(_PREFIX + 'request'):
            st.session_state[_PREFIX + 'pending'] = request


def render():
    if st.query_params.get('monthly_qa') not in {'isolated', 'fixtures'} or not testing.scope() or not testing.generation():
        return
    with st.expander('Inspect an original or test derivative with the production renderer'):
        st.warning('SOURCE PREVIEW ONLY — not a completed report or content approval.')
        st.caption('Upload one DOCX (32 MiB maximum). This does not import, save, reset or approve any report. '
                   'It renders a full-resolution passive safety copy, not the byte-identical original. '
                   'Prices and unfinished content may remain visible. Files stay in this browser’s isolated QA storage; '
                   'nothing is added to the shared fixture catalog. No authentication or confidentiality guarantee is added.')
        owner_key = _PREFIX + 'owner'
        if owner_key not in st.session_state:
            st.session_state[owner_key] = uuid4().hex
            st.session_state[_PREFIX + 'epoch'] = preview.retire(st.session_state[owner_key])
        activate = testing.capture_namespace()
        upload_key = _PREFIX + 'upload_' + st.session_state.setdefault(_PREFIX + 'uploader_epoch', uuid4().hex)
        upload = st.file_uploader('Fresh source DOCX for inspection', type=['docx'], key=upload_key,
                                  on_change=_invalidate, args=(activate,))
        kind = st.selectbox('Uploaded file is', ('original', 'named derivative'), key=_PREFIX + 'kind',
                            on_change=_invalidate, args=(activate,))
        label = st.text_input('Source or derivative name', max_chars=80, key=_PREFIX + 'label',
                              on_change=_invalidate, args=(activate,))
        request = None
        if upload and label.strip() and not st.session_state.get(_PREFIX + 'request'):
            try:
                if upload.size > preview.MAX_BYTES:
                    raise preview.SourcePreviewError('Choose one DOCX no larger than 32 MiB.')
                request = preview.new_request(st.session_state[owner_key], st.session_state[_PREFIX + 'epoch'],
                    upload.getvalue(), upload_id=upload.file_id, label=label, kind=kind)
            except (ValueError, OSError):
                st.error('This selection cannot be rendered. Check the 32 MiB limit and choose a fresh DOCX.')
        st.button('Render source preview only', key=_PREFIX + 'render', disabled=request is None,
                  on_click=_queue, args=(activate, request, upload_key))
        st.button('Clear source-preview files / start a new attempt',
                  key=_PREFIX + 'clear_' + st.session_state[owner_key] + '_' + st.session_state[_PREFIX + 'epoch'],
                  on_click=_clear, args=(activate, st.session_state[owner_key], st.session_state[_PREFIX + 'epoch']))
        if pending := st.session_state.pop(_PREFIX + 'pending', None):
            st.session_state[_PREFIX + 'request'] = pending  # Consume before work; no rerun retry.
            try:
                if not upload:
                    raise preview.SourcePreviewError('Choose a fresh DOCX.')
                with st.spinner('Rendering the passive source copy with the deployed engine…'):
                    receipt = preview.execute(pending, upload.getvalue(), upload_id=upload.file_id)
                # A newer upload/cancel must not revive a result on a later rerun.
                if st.session_state.get(_PREFIX + 'epoch') == pending.epoch:
                    st.session_state[_PREFIX + 'receipt'] = receipt
            except (ValueError, OSError, RuntimeError):
                st.session_state[_PREFIX + 'error'] = 'This render request became stale or unavailable. No automatic retry occurred.'
        if error := st.session_state.get(_PREFIX + 'error'):
            st.error(error)
        receipt = st.session_state.get(_PREFIX + 'receipt')
        completed = st.session_state.get(_PREFIX + 'request')
        if not receipt or not completed:
            return
        if receipt['status'] == 'rendered':
            st.success(f"Source inspection rendered {receipt['pages']} pages. This does not pass report preflight or approve any source role.")
            st.text('Renderer: ' + receipt['renderer']['version'])
        else:
            st.error(receipt.get('error', 'Source inspection failed.'))
            st.text('First failure stage: ' + receipt['stage'])
        st.text('Untouched source SHA-256: ' + receipt['source_sha256'])
        if receipt.get('render_input_sha256'):
            st.text('Passive render-input SHA-256: ' + receipt['render_input_sha256'])
        st.caption('No page watermark was added, so pixel comparisons remain meaningful. Every download is source inspection only.')
        downloads = [('receipt.json', 'Download source-inspection receipt', 'application/json')]
        if receipt.get('source_bytes') and receipt['stage'] != 'admission':
            downloads.append(('source.docx', 'Download untouched source', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
        if receipt.get('render_input_sha256'):
            downloads.append(('render-input.docx', 'Download exact passive render input', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
        if receipt.get('pdf_sha256'):
            downloads.append(('source-preview.pdf', 'Download source-inspection PDF', 'application/pdf'))
        for name, title, mime in downloads:
            try:
                data = preview.artifact(completed, name)
            except (ValueError, OSError):
                st.warning('These source-preview artifacts are no longer current. Make a fresh upload to inspect again.')
                break
            st.download_button(title, data, file_name='SOURCE-PREVIEW-ONLY-' + name, mime=mime,
                               key=_PREFIX + 'download_' + name, on_click='ignore')
