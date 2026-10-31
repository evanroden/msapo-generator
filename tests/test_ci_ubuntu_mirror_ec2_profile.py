"""One documented, observed EC2 host; no wildcard or trust-policy fallback."""
import re

import pytest

from scripts import ci_ubuntu_mirror_priority as mirror


AZURE = ''.join(f'{uri}\tpriority:{priority}\n' for uri, priority in mirror.ORIGINAL.items())
EC2_URI = 'http://us-east-2.ec2.archive.ubuntu.com/ubuntu/'
EC2 = AZURE.replace('http://azure.archive.ubuntu.com/ubuntu/', EC2_URI)
PREFERRED = EC2.replace('priority:1', 'priority:X').replace('priority:2', 'priority:1').replace('priority:X', 'priority:2')


def test_exact_documented_ec2_profile_changes_only_priority_digits():
    assert mirror.prefer_official_archive(EC2) == PREFERRED
    assert mirror.prefer_official_archive(PREFERRED) == PREFERRED
    mask = lambda s: re.sub(r'priority:[1-3]', 'priority:X', s)
    assert mask(EC2) == mask(PREFERRED)


@pytest.mark.parametrize('source', [
    EC2, PREFERRED, EC2.rstrip('\n'), EC2.replace('\n', '\r\n'),
    '# comment retained\n\n' + EC2,
    ''.join(reversed(EC2.splitlines(keepends=True))),
    EC2.replace('\tpriority:', '\t\tpriority:'),
])
def test_exact_profile_preserves_uri_bytes_format_mode_and_unrelated_source(
    source, tmp_path, monkeypatch, capsys,
):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_bytes(source.encode())
    target.chmod(0o640)
    other = tmp_path / 'ubuntu.sources'
    other.write_bytes(b'existing suites, components, Signed-By and signature policy')
    before = other.read_bytes()
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    mirror.main()
    once = target.read_bytes()
    mirror.main()
    assert target.read_bytes() == once
    assert target.stat().st_mode & 0o777 == 0o640
    assert other.read_bytes() == before
    assert capsys.readouterr().err == ''
    assert re.sub(rb'priority:[1-3]', b'priority:X', once) == re.sub(rb'priority:[1-3]', b'priority:X', source.encode())
    assert EC2_URI.encode() in once


@pytest.mark.parametrize('bad_uri', [
    'http://us-east-1.ec2.archive.ubuntu.com/ubuntu/',
    'http://us-west-2.ec2.archive.ubuntu.com/ubuntu/',
    'http://x.us-east-2.ec2.archive.ubuntu.com/ubuntu/',
    'http://us-east-2.ec2.archive.ubuntu.com.evil.invalid/ubuntu/',
    'http://us-east-2.ec2.archive.ubuntu.com@evil.invalid/ubuntu/',
    'http://user:password@us-east-2.ec2.archive.ubuntu.com/ubuntu/',
    'http://us-east-2.ec2.archive.ubuntu.com:80/ubuntu/',
    'http://us-east-2.ec2.archive.ubuntu.com/ubuntu/?key=secret',
    'http://us-east-2.ec2.archive.ubuntu.com/ubuntu/#secret',
    'http://us-east-2.ec2.archive.ubuntu.com/ubuntu',
    'http://us-east-2.ec2.archive.ubuntu.com/ubuntu/ubuntu/',
    'http://us-east-2.ec2.archive.ubuntu.com/other/',
    'http://us-east-2.ec2.archive.ubuntu.com/%75buntu/',
    'http://US-EAST-2.ec2.archive.ubuntu.com/ubuntu/',
    'https://us-east-2.ec2.archive.ubuntu.com/ubuntu/',
])
def test_other_regions_hosts_uri_components_and_forms_stay_rejected(
    bad_uri, tmp_path, monkeypatch,
):
    source = EC2.replace(EC2_URI, bad_uri)
    target = tmp_path / 'apt-mirrors.txt'
    target.write_text(source)
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    with pytest.raises(ValueError):
        mirror.main()
    assert target.read_text() == source


@pytest.mark.parametrize('source', [
    EC2 + AZURE.splitlines(keepends=True)[0],
    EC2 + EC2.splitlines(keepends=True)[0],
    EC2 + 'https://other.invalid/ubuntu/\tpriority:1\n',
    EC2.replace('priority:1', 'priority:2'),
    EC2.replace('priority:3', 'priority:2'),
    EC2.replace('priority:1', 'priority:3'),
    EC2.replace('priority:1', 'priority:0'),
    EC2.replace('priority:1', 'priority:1 trusted:yes'),
    EC2.replace('priority:1', 'priority:1 type:deb'),
    EC2.replace('\tpriority:', ' priority:'),
    EC2.splitlines(keepends=True)[0],
    ''.join(EC2.splitlines(keepends=True)[1:]),
])
def test_mixed_duplicate_missing_metadata_and_priority_inputs_never_write(
    source, tmp_path, monkeypatch,
):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_bytes(source.encode())
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    calls = []
    monkeypatch.setattr(type(target), 'write_bytes', lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        mirror.main()
    assert calls == []
    assert target.read_bytes() == source.encode()


def test_rejected_ec2_profile_diagnostic_remains_structural_and_private(tmp_path, monkeypatch, capsys):
    source = EC2 + EC2.splitlines(keepends=True)[0]
    target = tmp_path / 'apt-mirrors.txt'
    target.write_text(source)
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    with pytest.raises(ValueError):
        mirror.main()
    output = capsys.readouterr().err
    assert '"duplicate_known_entries": 1' in output
    assert '"us-east-2.ec2.archive.ubuntu.com": 2' in output
    assert '"unknown_hosts": []' in output
    assert '/ubuntu/' not in output
