"""Prefer the runner's existing HTTPS Ubuntu archive, without changing trust.

GitHub's Ubuntu image configures these three signed-archive mirrors:
https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/configure-apt-sources.sh
Only their documented priority metadata changes. No URI, key, suite, package,
source declaration, signature requirement or TLS option is added or removed.
Unknown image configuration fails closed instead of being overwritten.
"""
from pathlib import Path
import re


MIRROR_FILE = Path('/etc/apt/apt-mirrors.txt')
ORIGINAL = {
    'http://azure.archive.ubuntu.com/ubuntu/': '1',
    'https://archive.ubuntu.com/ubuntu/': '2',
    'https://security.ubuntu.com/ubuntu/': '3',
}
PREFERRED = {**ORIGINAL, 'http://azure.archive.ubuntu.com/ubuntu/': '2',
             'https://archive.ubuntu.com/ubuntu/': '1'}
ENTRY = re.compile(r'(?P<uri>\S+)(?P<separator>\t+)priority:(?P<priority>[1-3])(?P<end>\r?\n|$)')


def prefer_official_archive(source: str) -> str:
    """Validate the entire allowlisted mirror list before changing any byte."""
    lines = source.splitlines(keepends=True)
    entries = []
    seen = {}
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = ENTRY.fullmatch(line)
        if match is None:
            raise ValueError('Unrecognized Ubuntu mirror entry; no change made')
        uri = match['uri']
        if uri not in ORIGINAL or uri in seen:
            raise ValueError('Unexpected or duplicate Ubuntu mirror; no change made')
        seen[uri] = match['priority']
        entries.append((index, match))
    if seen not in (ORIGINAL, PREFERRED):
        raise ValueError('Unexpected Ubuntu mirror priorities; no change made')
    for index, match in entries:
        start, end = match.span('priority')
        lines[index] = lines[index][:start] + PREFERRED[match['uri']] + lines[index][end:]
    return ''.join(lines)


def main() -> None:
    # Fixed runner-owned path only, never arbitrary paths or source/key files.
    if MIRROR_FILE.is_symlink() or not MIRROR_FILE.is_file():
        raise ValueError('Expected regular runner Ubuntu mirror file')
    before = MIRROR_FILE.read_bytes().decode('utf-8')
    after = prefer_official_archive(before)
    if before != after:
        MIRROR_FILE.write_bytes(after.encode('utf-8'))
    if MIRROR_FILE.read_bytes().decode('utf-8') != after:
        raise RuntimeError('Ubuntu mirror priority write could not be verified')
    print('Existing signed Ubuntu archive preferred; all three mirror URIs and trust settings retained.')


if __name__ == '__main__':
    main()
