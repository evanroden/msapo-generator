"""No network or system mutation: validate the hosted runner mirror transform."""
from pathlib import Path
import re

import pytest

from scripts import ci_ubuntu_mirror_priority as mirror


ORIGINAL = ''.join(f'{uri}\tpriority:{priority}\n' for uri, priority in mirror.ORIGINAL.items())
PREFERRED = ''.join(f'{uri}\tpriority:{priority}\n' for uri, priority in mirror.PREFERRED.items())


def test_only_priority_digits_change_and_reapplication_is_noop():
    assert mirror.prefer_official_archive(ORIGINAL) == PREFERRED
    assert mirror.prefer_official_archive(PREFERRED) == PREFERRED
    strip_priority = lambda value: re.sub(r'priority:[1-3]', 'priority:X', value)
    assert strip_priority(ORIGINAL) == strip_priority(PREFERRED)


@pytest.mark.parametrize('source', [
    ORIGINAL.rstrip('\n'),
    ORIGINAL.replace('\n', '\r\n'),
    '# Runner mirrors\n\n' + ORIGINAL,
    ''.join(reversed(ORIGINAL.splitlines(keepends=True))),
])
def test_comments_line_endings_and_order_are_preserved(source):
    result = mirror.prefer_official_archive(source)
    assert re.sub(r'priority:[1-3]', 'priority:X', source) == re.sub(r'priority:[1-3]', 'priority:X', result)
    assert mirror.prefer_official_archive(result) == result


@pytest.mark.parametrize('source', [
    '', ORIGINAL.splitlines(keepends=True)[0],
    ORIGINAL + ORIGINAL.splitlines(keepends=True)[0],
    ORIGINAL + 'https://untrusted.invalid/ubuntu/\tpriority:1\n',
    ORIGINAL.replace('https://archive.ubuntu.com/', 'http://archive.ubuntu.com/'),
    ORIGINAL.replace('https://archive.ubuntu.com/', 'https://archive.ubuntu.com.evil.invalid/'),
    ORIGINAL.replace('priority:1', 'priority:0'),
    ORIGINAL.replace('priority:1', 'priority:2'),
    ORIGINAL.replace('priority:1', 'priority:1 trusted:yes'),
    ORIGINAL.replace('priority:1', 'priority:1 type:deb'),
    ORIGINAL.replace('\tpriority:', ' priority:'),
])
def test_unknown_configuration_fails_before_write(source, tmp_path, monkeypatch):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_text(source)
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    with pytest.raises(ValueError):
        mirror.main()
    assert target.read_text() == source


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_main_changes_only_mirror_file_preserves_mode_and_is_idempotent(tmp_path, monkeypatch, newline):
    target = tmp_path / 'apt-mirrors.txt'
    target.write_bytes(ORIGINAL.replace('\n', newline).encode())
    target.chmod(0o640)
    other = tmp_path / 'ubuntu.sources'
    other.write_text('existing suite, key and signature settings')
    monkeypatch.setattr(mirror, 'MIRROR_FILE', target)
    mirror.main()
    mirror.main()
    assert target.read_bytes() == PREFERRED.replace('\n', newline).encode()
    assert target.stat().st_mode & 0o777 == 0o640
    assert other.read_text() == 'existing suite, key and signature settings'


def test_symlink_is_rejected_without_mutating_target(tmp_path, monkeypatch):
    target = tmp_path / 'actual'
    target.write_text(ORIGINAL)
    link = tmp_path / 'apt-mirrors.txt'
    link.symlink_to(target)
    monkeypatch.setattr(mirror, 'MIRROR_FILE', link)
    with pytest.raises(ValueError):
        mirror.main()
    assert target.read_text() == ORIGINAL


def test_each_native_setup_prefers_existing_mirror_before_dependency_fetch():
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    for name in ('literal-labels', 'synthetic-progress-photos', 'synthetic-history', 'synthetic-dom', 'training-date'):
        section = workflow.split(f'\n  {name}:', 1)[1]
        section = re.split(r'^  [a-z][a-z-]+:', section, maxsplit=1, flags=re.MULTILINE)[0]
        command = 'sudo python3 scripts/ci_ubuntu_mirror_priority.py'
        assert section.count(command) == 1
        assert section.index(command) < section.index('python -m playwright install --with-deps')
        if 'sudo apt-get update' in section:
            assert section.index(command) < section.index('sudo apt-get update')
    events = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    for paths in events[2::2]:
        assert "      - 'scripts/ci_ubuntu_mirror_priority.py'" in paths
        assert "      - 'tests/test_ci_ubuntu_mirror_priority.py'" in paths
