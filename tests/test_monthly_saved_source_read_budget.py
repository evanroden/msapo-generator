"""Stored originals have a bound at the read, even when stat becomes stale."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from docx import Document
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    profile = synthetic_profiles()[0]
    raw = b'Synthetic accepted original.'
    content, _ = sources.ingest(profile, 'synthetic.txt', raw)
    return profile, content, raw, sources._path(profile, content.source.sha256, '.txt')


def bounded_open(monkeypatch, path, limit):
    real_open = Path.open
    requests = []
    class Reader:
        def __enter__(self):
            self.stream = real_open(path, 'rb')
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            requests.append(size)
            assert 0 <= size <= limit + 1, 'saved-original read must be bounded'
            return self.stream.read(size)
    def opening(current, *args, **kwargs):
        if current == path and (args[0] if args else kwargs.get('mode')) == 'rb':
            return Reader()
        return real_open(current, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opening)
    return requests


def test_exact_boundary_returns_complete_original_with_one_bounded_read(saved, monkeypatch):
    profile, content, raw, path = saved
    monkeypatch.setattr(sources, 'MAX_FILE_BYTES', len(raw))
    requests = bounded_open(monkeypatch, path, len(raw))
    assert sources.source_bytes(profile, content.source) == raw
    assert requests == [len(raw) + 1]


def test_source_growth_after_stat_refuses_before_hash_and_retry_retains_original(saved, monkeypatch):
    profile, content, raw, path = saved
    real_stat = Path.stat
    grown = raw + b' additional synthetic bytes'
    path.unlink()
    path.write_bytes(grown)
    real_hash = sources.hashlib.sha256
    hashed = []
    def observe_hash(value):
        if value != profile.contract.encode():
            hashed.append(value)
        return real_hash(value)
    with monkeypatch.context() as racing:
        racing.setattr(sources, 'MAX_FILE_BYTES', len(raw))
        racing.setattr(Path, 'stat', lambda p, *a, **k: SimpleNamespace(st_size=len(raw)) if p == path else real_stat(p, *a, **k))
        requests = bounded_open(racing, path, len(raw))
        racing.setattr(sources.hashlib, 'sha256', observe_hash)
        with pytest.raises(ValueError, match='upload limit'):
            sources.source_bytes(profile, content.source)
        assert requests == [len(raw) + 1]
        assert not hashed
    assert path.read_bytes() == grown  # Rejection does not truncate or rewrite.
    path.write_bytes(raw)
    assert sources.source_bytes(profile, content.source) == raw


def test_early_oversize_never_opens_saved_original(saved, monkeypatch):
    profile, content, raw, path = saved
    monkeypatch.setattr(sources, 'MAX_FILE_BYTES', len(raw) - 1)
    real_open = Path.open
    def no_open(current, *args, **kwargs):
        if current == path:
            pytest.fail('oversize stat must refuse before opening')
        return real_open(current, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_open)
    with pytest.raises(ValueError, match='upload limit'):
        sources.source_bytes(profile, content.source)


@pytest.mark.parametrize('change', [b'X', b''])
def test_substituted_or_truncated_bytes_still_fail_integrity(saved, monkeypatch, change):
    profile, content, raw, path = saved
    path.unlink()
    path.write_bytes(change + raw[1:])
    monkeypatch.setattr(sources, 'MAX_FILE_BYTES', len(raw))
    with pytest.raises(ValueError, match='integrity'):
        sources.source_bytes(profile, content.source)
    assert path.read_bytes() == change + raw[1:]


def test_docx_uses_its_distinct_file_limit_and_returns_exact_package(saved, monkeypatch):
    profile, _, _, _ = saved
    document = Document()
    document.add_paragraph('Synthetic unchanged DOCX source.')
    output = BytesIO()
    document.save(output)
    raw = output.getvalue()
    content, _ = sources.ingest(profile, 'synthetic.docx', raw)
    monkeypatch.setattr(sources, 'MAX_FILE_BYTES', 1)
    monkeypatch.setattr(sources.docx_import, 'MAX_DOCX_BYTES', len(raw))
    path = sources._path(profile, content.source.sha256, '.docx')
    requests = bounded_open(monkeypatch, path, len(raw))
    assert sources.source_bytes(profile, content.source) == raw
    assert requests == [len(raw) + 1]
