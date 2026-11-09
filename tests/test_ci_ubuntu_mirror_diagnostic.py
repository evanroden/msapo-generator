"""Failure diagnostics are evidence, never permission to change apt trust."""
import json

import pytest

from scripts import ci_ubuntu_mirror_priority as mirror


ORIGINAL = ''.join(f'{uri}\tpriority:{priority}\n' for uri, priority in mirror.ORIGINAL.items())
PREFIX = 'Ubuntu mirror validation evidence: '


def invoke_rejected(tmp_path, monkeypatch, capsys, source, expected=ValueError):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_bytes(source)
    target.chmod(0o640)
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    with pytest.raises(expected) as failure:
        mirror.main()
    assert target.read_bytes() == source
    assert target.stat().st_mode & 0o777 == 0o640
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err.startswith(PREFIX)
    assert len(captured.err.splitlines()) == 1
    return json.loads(captured.err.removeprefix(PREFIX)), captured.err, failure.value


def test_known_duplicate_is_identifiable_but_still_rejected(tmp_path, monkeypatch, capsys):
    source = (ORIGINAL + ORIGINAL.splitlines(keepends=True)[0]).encode()
    summary, _, error = invoke_rejected(tmp_path, monkeypatch, capsys, source)
    assert str(error) == 'Unexpected or duplicate Ubuntu mirror; no change made'
    assert summary['sampled_entries'] == 4
    assert summary['duplicate_known_entries'] == 1
    assert summary['known_hosts'] == {
        'azure.archive.ubuntu.com': 2, 'archive.ubuntu.com': 1, 'security.ubuntu.com': 1,
    }
    assert summary['unknown_hosts'] == []
    assert summary['kinds']['recognized'] == 4
    assert not summary['truncated']


@pytest.mark.parametrize('uri,host,scheme', [
    ('https://user-secret:password-secret@new.invalid:8443/path-secret?query-secret#fragment-secret', 'new.invalid', 'https'),
    ('ftp://user-secret:password-secret@new.invalid/path-secret?query-secret#fragment-secret', 'new.invalid', 'other'),
    ('https://archive.ubuntu.com.evil.invalid/path-secret', 'archive.ubuntu.com.evil.invalid', 'https'),
    ('https://new.invalid%40path-secret/path-secret', 'unavailable', 'https'),
    ('https://[broken-secret/path-secret', 'unavailable', 'other'),
    ('file:///path-secret?query-secret#fragment-secret', 'unavailable', 'other'),
    ('path-secret', 'unavailable', 'other'),
    ('https://new.invalid\\path-secret/path-secret', 'unavailable', 'https'),
])
def test_unknown_uri_only_emits_classified_scheme_and_safe_hostname(
    tmp_path, monkeypatch, capsys, uri, host, scheme,
):
    source = (ORIGINAL + uri + '\tpriority:1\n').encode()
    summary, output, _ = invoke_rejected(tmp_path, monkeypatch, capsys, source)
    assert summary['unknown_hosts'] == [{'scheme': scheme, 'hostname': host, 'count': 1}]
    for secret in ('user-secret', 'password-secret', 'path-secret', 'query-secret', 'fragment-secret', '8443'):
        assert secret not in output
    assert summary['duplicate_known_entries'] == 0


def test_comments_and_malformed_metadata_are_not_echoed(tmp_path, monkeypatch, capsys):
    source = ('# private-comment-secret\n\n' + ORIGINAL +
              'https://archive.ubuntu.com/ubuntu/\tpriority:1 trusted:secret\n').encode()
    summary, output, error = invoke_rejected(tmp_path, monkeypatch, capsys, source)
    assert str(error) == 'Unrecognized Ubuntu mirror entry; no change made'
    assert summary['kinds'] == {'blank': 1, 'comment': 1, 'recognized': 3, 'unknown': 0, 'malformed': 1}
    assert summary['duplicate_known_entries'] == 1
    assert 'secret' not in output


def test_accepted_input_behavior_and_output_are_unchanged(tmp_path, monkeypatch, capsys):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_bytes(ORIGINAL.encode())
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    for _ in range(2):
        mirror.main()
        captured = capsys.readouterr()
        assert captured.err == ''
        assert captured.out == 'Existing signed Ubuntu archive preferred; all three mirror URIs and trust settings retained.\n'
    assert target.read_text() == ''.join(f'{uri}\tpriority:{priority}\n' for uri, priority in mirror.PREFERRED.items())


def test_invalid_utf8_preserves_original_decode_error_without_raw_bytes(tmp_path, monkeypatch, capsys):
    summary, output, _ = invoke_rejected(
        tmp_path, monkeypatch, capsys, b'https://new.invalid/path-secret\tpriority:1\n\xffsecret', UnicodeDecodeError,
    )
    assert summary['kinds']['malformed'] == 1
    assert 'secret' not in output


def test_sample_is_byte_line_and_distinct_host_bounded():
    source = ''.join(f'https://host-{i}.invalid/path-secret\tpriority:1\n' for i in range(1000)).encode()
    summary = mirror.mirror_failure_summary(source)
    assert summary['bytes'] == len(source)
    assert summary['sampled_lines'] == mirror.DIAGNOSTIC_LINES
    assert summary['sampled_entries'] == mirror.DIAGNOSTIC_LINES
    assert len(summary['unknown_hosts']) == mirror.DIAGNOSTIC_HOSTS
    assert summary['omitted_unknown_host_entries'] == mirror.DIAGNOSTIC_LINES - mirror.DIAGNOSTIC_HOSTS
    assert summary['truncated']
    assert len(json.dumps(summary)) < 4096
    assert 'path-secret' not in json.dumps(summary)


def test_byte_truncated_uri_is_not_reported_as_a_complete_host():
    summary = mirror.mirror_failure_summary(b'https://' + b'x' * (mirror.DIAGNOSTIC_BYTES + 100))
    assert summary['truncated']
    assert summary['sampled_entries'] == 0
    assert summary['unknown_hosts'] == []


def test_hostname_and_log_injection_cannot_expand_output():
    for uri in ('https://' + 'a' * 254, 'https://bad\x1bhost.invalid/path-secret',
                'https://bad\x00host.invalid/path-secret', 'https://\u202eevil.invalid/path-secret'):
        output = json.dumps(mirror.mirror_failure_summary((uri + '\tpriority:1\n').encode()))
        assert 'path-secret' not in output
        assert 'unavailable' in output
        assert len(output) < 1024


def test_all_prior_validation_cases_keep_identical_failures(tmp_path, monkeypatch, capsys):
    for source in ('', ORIGINAL.splitlines(keepends=True)[0],
                   ORIGINAL.replace('priority:1', 'priority:0'),
                   ORIGINAL.replace('priority:1', 'priority:2'),
                   ORIGINAL.replace('\tpriority:', ' priority:')):
        with pytest.raises(ValueError) as original_error:
            mirror.prefer_official_archive(source)
        _, _, diagnostic_error = invoke_rejected(tmp_path, monkeypatch, capsys, source.encode())
        assert type(diagnostic_error) is type(original_error.value)
        assert str(diagnostic_error) == str(original_error.value)
