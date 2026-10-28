"""The derivative source byte cap bounds I/O, including stat/open races."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import monthly_report_compatibility_view as view
from test_monthly_report_source_frame_logo_role import source


@pytest.mark.parametrize('size', [15, 16, 17, 64])
def test_opened_source_is_bounded_even_if_it_grew_after_stat(tmp_path, monkeypatch, size):
    path = tmp_path / 'synthetic-growing.docx'
    path.write_bytes(b'x')  # The initial size check sees a small staged file.
    cap = 16
    monkeypatch.setattr(view, 'MAX_VIEW_SOURCE_BYTES', cap)
    reads, parsed = [], []

    class MeasuredStream(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    stream = MeasuredStream(b'a' * size)
    original_open = Path.open

    def opening(current, *args, **kwargs):
        return stream if current == path else original_open(current, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', opening)
    expected = SimpleNamespace(receipt_bytes=b'synthetic receipt')

    def derive(raw):
        parsed.append(raw)
        return expected

    monkeypatch.setattr(view, 'derive_compatibility_view', derive)
    if size > cap:
        with pytest.raises(view.CompatibilityError, match='source byte budget'):
            view.rederive_compatibility_view(path)
        assert parsed == []  # Never parse a truncated over-budget source.
    else:
        assert view.rederive_compatibility_view(path) is expected
        assert parsed == [b'a' * size]
    assert reads == [cap + 1]
    assert stream.closed


def test_known_oversized_source_is_rejected_before_open(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic-large.docx'
    path.write_bytes(b'x' * 17)
    monkeypatch.setattr(view, 'MAX_VIEW_SOURCE_BYTES', 16)

    def forbidden(*args, **kwargs):
        pytest.fail('Known over-budget source was opened')

    monkeypatch.setattr(Path, 'open', forbidden)
    with pytest.raises(view.CompatibilityError, match='source byte budget'):
        view.rederive_compatibility_view(path)


def test_budget_refusal_retry_and_receipt_keep_original_unchanged(tmp_path, monkeypatch):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    monkeypatch.setattr(view, 'MAX_VIEW_SOURCE_BYTES', len(original) - 1)
    with pytest.raises(view.CompatibilityError, match='source byte budget'):
        view.rederive_compatibility_view(path)
    assert path.read_bytes() == original
    monkeypatch.setattr(view, 'MAX_VIEW_SOURCE_BYTES', len(original))
    derived = view.rederive_compatibility_view(path)
    assert view.rederive_compatibility_view(path, derived.receipt_bytes) == derived
    with pytest.raises(view.CompatibilityError, match='receipt'):
        view.rederive_compatibility_view(path, b'wrong receipt')
    assert path.read_bytes() == original
