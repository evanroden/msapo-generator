"""External-agent Render archive fetch validates real output without overwriting files.

No customer documents or archive hashes in Git/CI; all data here are synthetic.
"""
from hashlib import sha256
from pathlib import Path
import importlib.util

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qa_fetch_render_archive.py"
spec = importlib.util.spec_from_file_location("external_render_fetch", SCRIPT)
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


def test_caption_parses_exact_reported_size_and_hash():
    digest = "b" * 64
    assert fetcher._read_caption(
        f"Six originals · 88,159,285 ZIP bytes · SHA-256: {digest}"
    ) == (88159285, digest)
    assert fetcher._read_caption(
        f"5 evidence artifacts · 13,206,290 ZIP bytes · SHA-256: {digest}"
    ) == (13206290, digest)
    assert fetcher._read_caption(
        f"Size 88,159,285 · SHA-256: {digest}"
    ) is None
    assert fetcher._read_caption(
        "Six originals · 999 ZIP bytes · SHA-256: " + digest[:63]
    ) is None


def test_list_options_keep_exact_visible_id_and_requested_shelf():
    assert fetcher._prefixes(
        ["Original sources · " + "a" * 12,
         "Synthetic evidence · " + "b" * 12,
         "Original sources · " + "a" * 12,
         "Original sources · xyz",
         "Another item"],
        "originals",
    ) == ("a" * 12,)
    assert fetcher._prefixes(["Original sources · " + "a" * 12],
                             "synthetic") == ()


def test_verified_byte_copy_is_private_and_complete(tmp_path):
    data = (b"ordinary-synthetic-test-" * 10000) + b"END"
    original = tmp_path / "fixture-source.tmp"
    original.write_bytes(data)
    dest = tmp_path / "output.zip"
    fetcher._write_verified(original, dest, digest=sha256(data).hexdigest(),
                            size=len(data), max_size=len(data))
    assert dest.read_bytes() == data
    assert dest.stat().st_mode & 0o077 == 0
    assert original.read_bytes() == data


@pytest.mark.parametrize("error", ["digest", "length", "limit"])
def test_invalid_bytes_leave_no_downloaded_archive(tmp_path, error):
    data = b"synthetic-only"
    source = tmp_path / "source"
    target = tmp_path / "result.zip"
    source.write_bytes(data)
    kwargs = {
        "digest": sha256(data).hexdigest(),
        "size": len(data),
        "max_size": len(data),
    }
    if error == "digest":
        kwargs["digest"] = "0" * 64
    if error == "length":
        kwargs["size"] += 1
    if error == "limit":
        kwargs["max_size"] -= 1
    with pytest.raises(ValueError):
        fetcher._write_verified(source, target, **kwargs)
    assert not target.exists()
    assert source.read_bytes() == data


def test_no_overwrite_even_if_requested_output_already_exists(tmp_path):
    payload = b"synthetic-sample"
    source, target = tmp_path / "source", tmp_path / "existing.zip"
    source.write_bytes(payload)
    target.write_bytes(b"important unrelated local file")
    with pytest.raises(FileExistsError):
        fetcher._write_verified(
            source, target, digest=sha256(payload).hexdigest(),
            size=len(payload), max_size=len(payload),
        )
    assert target.read_bytes() == b"important unrelated local file"


def test_extension_rejected_before_touching_disk(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    target = tmp_path / "wrong.txt"
    with pytest.raises(ValueError, match=".zip"):
        fetcher._write_verified(
            source, target, digest=sha256(b"abc").hexdigest(),
            size=3, max_size=3,
        )
    assert not target.exists()


def test_bad_identity_fails_before_launching_external_browser(tmp_path):
    with pytest.raises(ValueError):
        fetcher.fetch_archive(kind="originals", expected_sha="incorrect",
                              expected_size=500, destination=tmp_path / "file.zip")
    with pytest.raises(ValueError):
        fetcher.fetch_archive(kind="synthetic", expected_sha="0" * 64,
                              expected_size=88_159_285, destination=tmp_path / "file.zip")
    with pytest.raises(ValueError, match="12-character"):
        fetcher.fetch_archive(kind="originals", expected_sha="0" * 64,
                              expected_size=1000, requested_prefix="notanid",
                              destination=tmp_path / "file.zip")


def test_template_caption_named_option_and_docx_download(tmp_path):
    data = b"invented template download bytes"
    digest = sha256(data).hexdigest()
    assert fetcher._read_caption(
        f"Word template · {len(data):,} DOCX bytes · SHA-256: {digest}"
    ) == (len(data), digest)
    option = "Report template · " + "a" * 12 + " · Synthetic template.docx"
    assert fetcher._prefixes([option], "templates") == ("a" * 12,)
    assert fetcher._prefixes([option], "originals") == ()
    assert fetcher.audit._option_pattern(fetcher.audit.SHELVES["templates"], "a" * 12).fullmatch(option)
    source, target = tmp_path / "download", tmp_path / "template.docx"
    source.write_bytes(data)
    fetcher._write_verified(source, target, digest=digest, size=len(data),
                            max_size=len(data), extension=".docx")
    assert target.read_bytes() == data
    with pytest.raises(ValueError, match=".docx"):
        fetcher.fetch_archive(kind="templates", expected_sha=digest,
                              expected_size=len(data), destination=tmp_path / "wrong.zip")


def test_template_limit_admits_above_200_mib_but_rejects_above_512():
    audit = fetcher.audit
    audit._valid_inputs("templates", "a" * 12, "b" * 64,
                        300 * 1024 * 1024, "c" * 40, "before")
    with pytest.raises(ValueError, match="bounded limit"):
        audit._valid_inputs("templates", "a" * 12, "b" * 64,
                            512 * 1024 * 1024 + 1, "c" * 40, "before")
