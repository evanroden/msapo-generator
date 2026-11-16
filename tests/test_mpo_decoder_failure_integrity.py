"""MPO decoder failures are file-local; accepted siblings and edits are durable."""
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


def mpo():
    stream = BytesIO()
    Image.new("RGB", (24, 18), "red").save(
        stream, format="MPO", save_all=True,
        append_images=[Image.new("RGB", (24, 18), "blue")],
    )
    return stream.getvalue()


@pytest.mark.parametrize("point,reason", (
    ("open", "damaged or truncated"),
    ("seek", "damaged or truncated"),
    ("frames", "frame information"),
    ("bomb_open", "too large to decode safely"),
    ("bomb_seek", "too large to decode safely"),
))
def test_mpo_open_and_inventory_parser_failures_keep_good_batch_siblings(
    monkeypatch, tmp_path, point, reason,
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    original = mpo()
    first, last = b"First accepted inspection.", b"Last accepted inspection."

    class BrokenMpo:
        format = "MPO"
        size = (24, 18)

        @property
        def n_frames(self):
            return None if point == "frames" else 2

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def seek(self, number):
            if point == "seek":
                raise OSError("Truncated File Read")
            if point == "bomb_seek":
                raise Image.DecompressionBombError("pixel bomb in next header")

    def broken_open(*_args, **_kwargs):
        if point == "open":
            raise OSError("Truncated File Read")
        if point == "bomb_open":
            raise Image.DecompressionBombError("pixel bomb in header")
        return BrokenMpo()

    monkeypatch.setattr(Image, "open", broken_open)
    contents, notices = sources.ingest_batch(profile, (
        ("first.txt", first), ("damaged.mpo", original), ("last.txt", last),
    ))
    assert tuple(c.source.filename for c in contents) == ("first.txt", "last.txt")
    assert tuple(sources.source_bytes(profile, c.source) for c in contents) == (first, last)
    assert len(notices) == 1 and notices[0].startswith("Not read: damaged.mpo.")
    assert reason in notices[0]
    assert not sources._path(profile, sha256(original).hexdigest(), ".mpo").exists()
    assert not sources._path(profile, sha256(original).hexdigest(), ".json").exists()


def test_real_truncated_mpo_keeps_jpeg_and_text_and_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    stream = BytesIO()
    Image.new("RGB", (32, 20), "green").save(stream, "JPEG")
    jpeg = stream.getvalue()
    incomplete = mpo()[:-100]
    last = b"Last valid activity."
    contents, notices = sources.ingest_batch(profile, (
        ("phone.jpg", jpeg), ("truncated.mpo", incomplete), ("last.txt", last),
    ))
    assert tuple(c.source.filename for c in contents) == ("phone.jpg", "last.txt")
    assert tuple(sources.source_bytes(profile, c.source) for c in contents) == (jpeg, last)
    assert len(notices) == 1
    assert notices[0].startswith("Not read: truncated.mpo.")
    assert "damaged or truncated" in notices[0]
    assert not sources._path(profile, sha256(incomplete).hexdigest(), ".mpo").exists()
    assert not sources._path(profile, sha256(incomplete).hexdigest(), ".json").exists()

    complete = mpo()
    again, retry_notices = sources.ingest_batch(
        profile, (("repaired.mpo", complete),), contents,
    )
    assert len(again) == 3 and not retry_notices
    assert sources.source_bytes(profile, again[-1].source) == complete
    assert sources.image_numbers(again[-1]) == (1, 2)


def test_guided_mpo_failure_preserves_pending_activity_and_reopens(monkeypatch, tmp_path):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_active_work as active_work
    from app.monthly_report_model import ReportPeriod
    from test_monthly_report_activity_intake_commit import (
        APP, TOKEN, setup_app, editor, draft, activity,
    )

    app, profile = setup_app(monkeypatch, tmp_path)
    first, last = b"First synthetic inspection.", b"Last synthetic inspection."
    good_bad_good = (
        ("first.txt", first), ("damaged.mpo", mpo()[:-100]), ("last.txt", last),
    )
    original_uploader = st.file_uploader

    def upload(label, *args, **kwargs):
        if label == "Add source files":
            values = []
            for name, raw in good_bad_good:
                stream = BytesIO(raw)
                stream.name = name
                values.append(stream)
            return values
        return original_uploader(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", upload)
    editor(app).set_value("The unsaved Activity edit must survive.").run()
    assert not app.exception
    expected_ids = {sha256(first).hexdigest(), sha256(last).hexdigest()}
    assert {src.id for src in draft(app).sources} == expected_ids
    expected = "\n\n".join(("The unsaved Activity edit must survive.", first.decode(), last.decode()))
    assert activity(app).text == editor(app).value == expected
    notice = "\n".join(item.value for item in (*app.warning, *app.info, *app.error))
    assert "damaged.mpo" in notice and "damaged or truncated" in notice
    saved = active_work.load(TOKEN, profile.contract, profile.key, ReportPeriod(2026, 10))
    assert saved and next(b for b in saved.draft.blocks if b.key == "activity_summary").text == expected
    monkeypatch.setattr(st, "file_uploader", original_uploader)
    resumed = AppTest.from_string(APP, default_timeout=45).run()
    assert not resumed.exception
    assert activity(resumed).text == editor(resumed).value == expected
    assert {src.id for src in draft(resumed).sources} == expected_ids
