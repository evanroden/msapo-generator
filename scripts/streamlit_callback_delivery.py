"""Finish native callback delivery before servicing a queued script interruption.

The pinned runner otherwise accepts a value before a callback can be interrupted
at its first state access. An identical following packet no longer counts as a
change. Explicit st.rerun semantics inside callbacks remain unchanged.
"""
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import stat

STREAMLIT_VERSION = '1.61.1'
SOURCE_SHA256 = 'f0cf87186750842b99532967cdebf0498a1fe451e952dda9cfc416deb34c591e'
RELATIVE_PATH = Path('runtime/scriptrunner/script_runner.py')
BEFORE = b'''                        self._session_state.on_script_will_rerun(
                            rerun_data.widget_states
                        )
'''
LEGACY_AFTER = b'''                        # Complete native value + callback delivery together.
                        # External reruns remain queued until the next yield;
                        # explicit callback st.rerun behavior is unchanged.
                        self._execing = False
                        try:
                            self._session_state.on_script_will_rerun(
                                rerun_data.widget_states
                            )
                        finally:
                            self._execing = True
'''

# A runner can wait behind a newer replacement's shared state lock. Check its
# queued Stop after acquiring that lock, before applying its now-obsolete packet.
AFTER = b'''                        # Serialize packet admission across replacement runners.
                        # A stopped runner must not apply an older packet after
                        # waiting for a newer runner's callback to finish.
                        with self._session_state._lock:
                            self._maybe_handle_execution_control_request()
                            self._execing = False
                            try:
                                self._session_state.on_script_will_rerun(
                                    rerun_data.widget_states
                                )
                            finally:
                                self._execing = True
'''


def repaired_source(raw, *, installed_version):
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError('Unexpected Streamlit version; callback source was not changed.')
    if sha256(raw).hexdigest() == REPAIRED_SHA256:
        return raw
    if sha256(raw).hexdigest() == LEGACY_REPAIRED_SHA256:
        raw = raw.replace(LEGACY_AFTER, BEFORE, 1)
    if sha256(raw).hexdigest() != SOURCE_SHA256 or raw.count(BEFORE) != 1:
        raise RuntimeError('Unexpected runner source; no bytes were changed.')
    result = raw.replace(BEFORE, AFTER, 1)
    if sha256(result).hexdigest() != REPAIRED_SHA256:
        raise RuntimeError('Callback repair did not match its pinned bytes.')
    return result


def patch_callback_delivery(streamlit_root, *, installed_version):
    import fcntl
    path = Path(streamlit_root) / RELATIVE_PATH
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        original = path.read_bytes()
        repaired = repaired_source(original, installed_version=installed_version)
        if repaired != original:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.pending-enfra-callback-', delete=False) as output:
                temporary = Path(output.name)
                output.write(repaired)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
            if path.read_bytes() != original:
                raise RuntimeError('Runner changed during installation; no replacement was made.')
            os.replace(temporary, path)
            temporary = None
        return {'version': installed_version, 'source_sha256': REPAIRED_SHA256,
                'already_patched': repaired == original, 'callback_delivery_boundary': True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(descriptor)


LEGACY_REPAIRED_SHA256 = '56b253d547ea9f4d68b57f635e8e626962a7b3a630fd56ca857da697cd6b1620'

REPAIRED_SHA256 = '1530c2a85815a640f1a360b2c8e5eeba84b5f75deca0de1ab15592574a95cafb'
