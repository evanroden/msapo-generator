"""Bound the pinned ordinary-Cover widget return copy before image admission.

Streamlit's default BytesIO deepcopy allocates a second encoded-size buffer at
registration, before the application can release it or check decoder headroom.
Only the exact native UploadedFile under an ordinary Cover action key gets an
independent copy-on-write buffer. Every native state policy still runs; every
other widget/type retains the dependency's ordinary deepcopy behavior.
"""
from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile

STREAMLIT_VERSION = '1.61.1'
SOURCE_SHA256 = 'f278f759fa3e4cf168996404937f1aa6e19dd8fd0e7ffdaca8912fcc9034cf9a'
REPAIRED_SHA256 = '9e4f32521254776a48d890210c342c27d05ca4cb0b7a58a839d54647877c7826'
RELATIVE_PATH = Path('runtime/state/session_state.py')
ANCHOR = b'\ndef _sanitize_url_array(\n'
RETURN_COPY = b'        widget_value = deepcopy(widget_value)\n'
REPAIRED_RETURN = b'        widget_value = _enfra_copy_cover_return(widget_value, metadata.value_type, user_key)\n'
HELPER = b'''
def _enfra_copy_cover_return(value, value_type, user_key):
    """Keep native return isolation without another full Cover upload buffer."""
    from io import BytesIO
    from streamlit.runtime.uploaded_file_manager import UploadedFile

    prefix, separator, signature = (user_key or "").rpartition("_cover_photograph_upload_")
    if not (
        value_type == "file_uploader_state_value"
        and prefix and separator and len(signature) == 20
        and all(character in "0123456789abcdef" for character in signature)
        and type(value) is UploadedFile
    ):
        return deepcopy(value)
    # Builtin getvalue exposes immutable bytes; BytesIO(bytes) uses COW on our
    # pinned CPython runtime. Do not export a mutable buffer or share the stream.
    # This is a copy, not admission: preserve even malformed size metadata so
    # the unchanged application's exact byte/pixel/source guards can reject it.
    raw = BytesIO.getvalue(value)
    position = BytesIO.tell(value)
    clone = UploadedFile.__new__(UploadedFile)
    BytesIO.__init__(clone, raw)
    BytesIO.seek(clone, position)
    # Preserve custom metadata, aliases and self-references with normal deep
    # copying, while giving the returned file its own cursor and mutable state.
    clone.__dict__.update(deepcopy(value.__dict__, {id(value): clone}))
    return clone

'''


def repaired_source(raw, *, installed_version):
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError('Unexpected Streamlit version; Cover return source was not changed.')
    digest = sha256(raw).hexdigest()
    if digest == REPAIRED_SHA256:
        return raw
    if digest != SOURCE_SHA256 or raw.count(ANCHOR) != 1 or raw.count(RETURN_COPY) != 1:
        raise RuntimeError('Unexpected native state source; no bytes were changed.')
    result = raw.replace(ANCHOR, HELPER + ANCHOR, 1).replace(RETURN_COPY, REPAIRED_RETURN, 1)
    if sha256(result).hexdigest() != REPAIRED_SHA256:
        raise RuntimeError('Cover return repair did not match its pinned bytes.')
    return result


def patch_cover_upload_copy(streamlit_root, *, installed_version):
    """Validate and atomically install before service startup; never live-patch."""
    import fcntl

    path = Path(streamlit_root) / RELATIVE_PATH
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        original = path.read_bytes()
        repaired = repaired_source(original, installed_version=installed_version)
        if repaired != original:
            mode = stat.S_IMODE(path.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.pending-enfra-cover-copy-', delete=False) as output:
                temporary = Path(output.name)
                output.write(repaired)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(mode)
            if path.read_bytes() != original:
                raise RuntimeError('Native state source changed during installation; no replacement was made.')
            os.replace(temporary, path)
            temporary = None
        return {'version': installed_version, 'source_sha256': REPAIRED_SHA256,
                'already_patched': repaired == original, 'cover_return_copy_on_write': True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(descriptor)
