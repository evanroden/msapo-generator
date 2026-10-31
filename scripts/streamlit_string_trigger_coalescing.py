"""Preserve native ButtonColumn intent in the pinned Streamlit rerun queue.

Streamlit 1.61.1 coalesces boolean and chat triggers but drops a string trigger
when a subsequent cell-edit snapshot omits it. Add that existing protobuf
trigger family to the same native rules; newer values and type changes win.
This installer changes the server source before the application process starts.
"""
from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile


STREAMLIT_VERSION = "1.61.1"
SOURCE_SHA256 = "67b05f1cb5357b73c39aba18b9b2354860058e4ddbdef65e7ee87de650a83ca8"
REPAIRED_SHA256 = "bfe599b59ef271ce0d49f6ac709da2e7f64c5378b5e3c0c79b5d29f99ae984cd"
RELATIVE_PATH = Path("runtime/scriptrunner_utils/script_requests.py")
IMPORT = b"from streamlit.proto.Common_pb2 import ChatInputValue as ChatInputValueProto\n"
ADDED_IMPORT = b"from streamlit.proto.Common_pb2 import StringTriggerValue as StringTriggerValueProto\n"
TRIGGER = b'        ("trigger_value", False),\n'
ADDED_TRIGGER = b'        ("string_trigger_value", StringTriggerValueProto(data=None)),\n'


def repaired_source(raw, *, installed_version):
    """Validate the complete dependency bytes before accepting or repairing them."""
    if installed_version != STREAMLIT_VERSION:
        raise RuntimeError("Unexpected Streamlit version; native trigger source was not changed.")
    digest = sha256(raw).hexdigest()
    if digest == REPAIRED_SHA256:
        return raw
    if digest != SOURCE_SHA256 or raw.count(IMPORT) != 1 or raw.count(TRIGGER) != 1:
        raise RuntimeError("Unexpected native trigger source; no bytes were changed.")
    result = raw.replace(IMPORT, IMPORT + ADDED_IMPORT, 1).replace(TRIGGER, TRIGGER + ADDED_TRIGGER, 1)
    if sha256(result).hexdigest() != REPAIRED_SHA256:
        raise RuntimeError("Native trigger repair did not match its pinned bytes.")
    return result


def patch_script_requests(streamlit_root, *, installed_version):
    """Serialize installers and publish one validated server module atomically."""
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
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-enfra-trigger-", delete=False) as output:
                temporary = Path(output.name)
                output.write(repaired)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(mode)
            if path.read_bytes() != original:
                raise RuntimeError("Native trigger source changed during installation; no replacement was made.")
            os.replace(temporary, path)
            temporary = None
        return {"version": installed_version, "source_sha256": REPAIRED_SHA256,
                "already_patched": repaired == original, "string_trigger_coalescing": True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(descriptor)
