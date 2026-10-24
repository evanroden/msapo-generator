"""Passive upload identity for the cookie-isolated synthetic admin fixture only."""
from hashlib import sha256

from app.monthly_report_editor import _signature


def upload_observation(state, selected_key, revision):
    """Read the current widget without consuming its stream or editing state."""
    key = 'report_single_logo_' + _signature((selected_key, revision)) + '_upload'
    upload = state.get(key)
    raw = upload.getvalue() if upload is not None else None
    return {'selected_key': selected_key, 'catalog_revision': revision,
            'upload_widget_key': key, 'upload_present': raw is not None,
            'upload_size': len(raw) if raw is not None else 0,
            'upload_sha256': sha256(raw).hexdigest() if raw is not None else ''}
