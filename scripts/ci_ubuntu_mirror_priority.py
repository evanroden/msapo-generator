"""Prefer the runner's existing HTTPS Ubuntu archive, without changing trust.

GitHub's Ubuntu image configures these three signed-archive mirrors:
https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/configure-apt-sources.sh
Only their documented priority metadata changes. No URI, key, suite, package,
source declaration, signature requirement or TLS option is added or removed.
Unknown image configuration fails closed instead of being overwritten.
"""
from pathlib import Path
import json
import re
import sys
from urllib.parse import urlsplit


MIRROR_FILE = Path('/etc/apt/apt-mirrors.txt')
ORIGINAL = {
    'http://azure.archive.ubuntu.com/ubuntu/': '1',
    'https://archive.ubuntu.com/ubuntu/': '2',
    'https://security.ubuntu.com/ubuntu/': '3',
}
PREFERRED = {**ORIGINAL, 'http://azure.archive.ubuntu.com/ubuntu/': '2',
             'https://archive.ubuntu.com/ubuntu/': '1'}
ENTRY = re.compile(r'(?P<uri>\S+)(?P<separator>\t+)priority:(?P<priority>[1-3])(?P<end>\r?\n|$)')
DIAGNOSTIC_BYTES = 4096
DIAGNOSTIC_LINES = 32
DIAGNOSTIC_HOSTS = 8


def mirror_failure_summary(source: bytes) -> dict:
    """Bounded structural evidence only; never echo raw lines or URI secrets.

    This is not validation and cannot authorize a mirror or alter its priority.
    Unknown schemes are classified, not echoed. Unknown hosts must be plain ASCII
    DNS names; credentials, ports, paths, queries and fragments are never logged.
    """
    sample = source[:DIAGNOSTIC_BYTES]
    lines = sample.splitlines(keepends=True)
    if len(source) > len(sample) and lines and not lines[-1].endswith((b'\n', b'\r')):
        lines.pop()  # Do not interpret a URI cut in the middle by the byte limit.
    truncated = len(source) > len(sample) or len(lines) > DIAGNOSTIC_LINES
    lines = lines[:DIAGNOSTIC_LINES]
    kinds = {'blank': 0, 'comment': 0, 'recognized': 0, 'unknown': 0, 'malformed': 0}
    known_hosts = {}
    unknown_hosts = {}
    seen_known = set()
    duplicate_known = 0
    omitted_hosts = 0
    entries = 0
    for raw in lines:
        line = raw.decode('utf-8', errors='replace')
        if not line.strip():
            kinds['blank'] += 1
            continue
        if line.lstrip().startswith('#'):
            kinds['comment'] += 1
            continue
        entries += 1
        uri = line.split()[0]
        if ENTRY.fullmatch(line) is None:
            kinds['malformed'] += 1
        elif uri in ORIGINAL:
            kinds['recognized'] += 1
        else:
            kinds['unknown'] += 1
        if uri in ORIGINAL:
            host = urlsplit(uri).hostname
            known_hosts[host] = known_hosts.get(host, 0) + 1
            duplicate_known += uri in seen_known
            seen_known.add(uri)
            continue
        scheme, host = 'other', 'unavailable'
        try:
            parsed = urlsplit(uri)
            if parsed.scheme in ('http', 'https'):
                scheme = parsed.scheme
            candidate = parsed.hostname or ''
            if len(candidate) <= 253 and re.fullmatch(
                r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', candidate, flags=re.ASCII
            ):
                host = candidate
        except ValueError:
            pass
        key = (scheme, host)
        if key in unknown_hosts or len(unknown_hosts) < DIAGNOSTIC_HOSTS:
            unknown_hosts[key] = unknown_hosts.get(key, 0) + 1
        else:
            omitted_hosts += 1
    return {
        'bytes': len(source), 'sampled_lines': len(lines), 'sampled_entries': entries,
        'truncated': truncated, 'kinds': kinds, 'known_hosts': known_hosts,
        'duplicate_known_entries': duplicate_known,
        'unknown_hosts': [
            {'scheme': scheme, 'hostname': host, 'count': count}
            for (scheme, host), count in sorted(unknown_hosts.items())
        ],
        'omitted_unknown_host_entries': omitted_hosts,
    }


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
    source = MIRROR_FILE.read_bytes()
    try:
        before = source.decode('utf-8')
        after = prefer_official_archive(before)
    except ValueError:
        print('Ubuntu mirror validation evidence: ' + json.dumps(
            mirror_failure_summary(source), sort_keys=True, ensure_ascii=True
        ), file=sys.stderr)
        raise
    if before != after:
        MIRROR_FILE.write_bytes(after.encode('utf-8'))
    if MIRROR_FILE.read_bytes().decode('utf-8') != after:
        raise RuntimeError('Ubuntu mirror priority write could not be verified')
    print('Existing signed Ubuntu archive preferred; all three mirror URIs and trust settings retained.')


if __name__ == '__main__':
    main()
