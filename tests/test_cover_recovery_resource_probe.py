from scripts.qa_cover_recovery_resources import independent_uploads


def test_synthetic_visitors_have_independent_retained_buffers():
    source=b'x'*(1024*1024)
    uploads=independent_uploads(source=source,visitors=2)
    first,second=(upload.getvalue() for upload in uploads)
    assert first==second==source
    assert first is not second and first is not source and second is not source


def test_file_visitors_are_independent_reads(tmp_path):
    path=tmp_path/'input';path.write_bytes(b'x'*(1024*1024))
    uploads=independent_uploads(path=path,visitors=2)
    assert uploads[0].getvalue()==uploads[1].getvalue()
    assert uploads[0].getvalue() is not uploads[1].getvalue()


def test_oom_accounting_supports_v1_without_silently_skipping_children(monkeypatch):
    from pathlib import Path
    from scripts.qa_cover_recovery_resources import oom_kills
    def read(path):
        if path.name=='memory.events':raise FileNotFoundError
        return 'oom_kill_disable 0\nunder_oom 0\noom_kill 2\n'
    monkeypatch.setattr(Path,'read_text',read)
    assert oom_kills()==2


def test_gate_refuses_missing_child_oom_accounting(monkeypatch):
    import pytest
    from scripts import qa_cover_recovery_resources as probe,qa_cover_photo_resources as baseline
    monkeypatch.setenv('RESOURCE_REQUIRE_512_MB','1')
    monkeypatch.setattr(baseline,'cgroup_memory',lambda:(512*1024*1024,0))
    monkeypatch.setattr(probe,'oom_kills',lambda:None)
    with pytest.raises(AssertionError,match='OOM accounting is required'):
        probe.main(None)
