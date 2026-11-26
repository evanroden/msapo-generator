"""Share native session locking between overlapping fast replacement runners.

Each replacement runner has a separate safe wrapper but the same raw state.
A per-wrapper lock allows a late callback from the stopped runner to overwrite
a completed callback from its replacement. Weak lock storage does not retain
sessions after their wrappers disappear.
"""
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import stat

STREAMLIT_VERSION = '1.61.1'
SOURCE_SHA256 = 'ef640b5d9deb8e205f5f8a033ec53cb48758ad70f26e276b5d8649ba42f837b7'
RELATIVE_PATH = Path('runtime/state/safe_session_state.py')
BEFORE = b'        object.__setattr__(self, "_lock", threading.RLock())\n'
AFTER = b'        object.__setattr__(self, "_lock", _enfra_shared_state_lock(state))\n'
ANCHOR = b'\nclass SafeSessionState:'
HELPER = b'''
# Wrappers own their locks. The weak registry only lets concurrent replacement
# wrappers for the same live state find that lock, without retaining a session.
from weakref import WeakValueDictionary
_enfra_state_locks = WeakValueDictionary()
_enfra_state_locks_guard = threading.Lock()


def _enfra_shared_state_lock(state):
    with _enfra_state_locks_guard:
        identity = id(state)
        lock = _enfra_state_locks.get(identity)
        if lock is None:
            lock = threading.RLock()
            _enfra_state_locks[identity] = lock
        return lock

'''


def repaired_source(raw, *, installed_version):
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError('Unexpected Streamlit version; shared-lock source was not changed.')
    if sha256(raw).hexdigest() == REPAIRED_SHA256:
        return raw
    if sha256(raw).hexdigest() != SOURCE_SHA256 or raw.count(BEFORE) != 1:
        raise RuntimeError('Unexpected safe-state source; no bytes were changed.')
    result = raw.replace(BEFORE, AFTER, 1).replace(ANCHOR, HELPER + ANCHOR, 1)
    if sha256(result).hexdigest() != REPAIRED_SHA256:
        raise RuntimeError('Shared-lock repair did not match its pinned bytes.')
    return result


def patch_shared_state_lock(streamlit_root, *, installed_version):
    import fcntl
    path = Path(streamlit_root) / RELATIVE_PATH
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        original = path.read_bytes()
        repaired = repaired_source(original, installed_version=installed_version)
        if repaired != original:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.pending-enfra-state-lock-', delete=False) as output:
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
                'already_patched': repaired == original, 'shared_native_session_lock': True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(descriptor)


REPAIRED_SHA256 = 'd01beaf3c2375decdb6b11f6c4d3c1a8f26cd14bbead409ff6b0fd73d6f77a0e'
