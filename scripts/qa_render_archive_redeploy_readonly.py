"""Read-only, exact-served Render disk archive verification for external QA agents.

Does not upload, delete, extract, ingest, or print client content. The initial
upload is an explicit owner operation on the existing no-login shared test page.
Run once before and once after DISTINCT actual served Render builds, then
compare the hash-only receipts. No service config or state changes are made.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse

ORIGIN = 'https://msapo-generator.onrender.com'
SHELF_ROUTE = '/?workflow=monthly&monthly_qa=fixtures'
BUILD_ROUTE = '/?workflow=monthly&monthly_qa=isolated'
KIND = 'enfra-render-archive-readonly-v1'
ID = re.compile(r'[0-9a-f]{32}\Z')
ID_PREFIX = re.compile(r'[0-9a-f]{12}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')

SHELVES = {
    'originals': {
        'expander': 'Immutable six-source reference archive for external testers',
        'selection': 'Stored source archive',
        'option': 'Original sources · ',
        'prepare': 'Prepare verified ZIP download',
        'download': 'Download unchanged source archive',
        'key_prefix': '_shared_fixture_source_bundle_download_',
        'max_size': 96 * 1024 * 1024,
    },
    'synthetic': {
        'expander': 'Synthetic QA evidence archive for external agents',
        'selection': 'Saved synthetic evidence archive',
        'option': 'Synthetic evidence · ',
        'prepare': 'Prepare evidence ZIP download',
        'download': 'Download unchanged synthetic evidence archive',
        'key_prefix': '_shared_fixture_evidence_bundle_download_',
        'max_size': 24 * 1024 * 1024,
    },
    'templates': {
        'expander': 'Shared report templates for agents',
        'selection': 'Stored report template',
        'option': 'Report template · ',
        'prepare': 'Prepare verified template download',
        'download': 'Download unchanged report template',
        'key_prefix': '_shared_template_download_',
        'max_size': 512 * 1024 * 1024,
        'extension': '.docx',
        'filename_in_option': True,
    },
}


def _option_pattern(settings, prefix):
    suffix = r' · .+' if settings.get('filename_in_option') else ''
    return re.compile('^' + re.escape(settings['option'] + prefix) + suffix + '$')


def _valid_inputs(archive_kind: str, bundle_prefix: str, original_sha: str, expected_size: int,
                  served_commit: str, phase: str) -> None:
    if archive_kind not in SHELVES:
        raise ValueError('Unknown archive shelf.')
    if not isinstance(bundle_prefix, str) or not (ID_PREFIX.fullmatch(bundle_prefix) or ID.fullmatch(bundle_prefix)):
        raise ValueError('Use a 12-character visible bundle prefix or full 32-character bundle ID.')
    if not isinstance(original_sha, str) or not SHA.fullmatch(original_sha):
        raise ValueError('Exact expected archive SHA-256 is required.')
    if type(expected_size) is not int or not 1 <= expected_size <= SHELVES[archive_kind]['max_size']:
        raise ValueError('Expected archive length is outside the bounded limit.')
    if not isinstance(served_commit, str) or not COMMIT.fullmatch(served_commit):
        raise ValueError('Full 40-character exact served commit is required.')
    if phase not in ('before', 'after'):
        raise ValueError('Phase must be before or after.')


def _validated_receipt(receipt: dict, phase: str) -> dict:
    if type(receipt) is not dict or receipt.get('schema') != 1 or receipt.get('kind') != KIND:
        raise ValueError('Not an accepted hash-only Render archive receipt.')
    if receipt.get('endpoint') != ORIGIN or receipt.get('phase') != phase:
        raise ValueError('The receipt references another endpoint or phase.')
    _valid_inputs(receipt.get('archive_kind'), receipt.get('bundle_id'),
                  receipt.get('archive_sha256'), receipt.get('archive_size'),
                  receipt.get('served_commit'), phase)
    if not ID.fullmatch(receipt['bundle_id']):
        raise ValueError('Receipt must bind a full 32-character archive ID.')
    if receipt.get('read_only_checks') != [
        'exact_served_commit_before', 'selected_archive_identity',
        'downloaded_original_sha256', 'exact_served_commit_after',
    ]:
        raise ValueError('Mandatory read-only checks were not all completed.')
    try:
        moment = datetime.fromisoformat(receipt['verified_at_utc'].replace('Z', '+00:00'))
        if moment.utcoffset() is None or moment.utcoffset().total_seconds() != 0:
            raise ValueError('Not UTC')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError('Invalid verification timestamp.') from exc
    return receipt


def compare(before: dict, after: dict) -> dict:
    a, b = _validated_receipt(before, 'before'), _validated_receipt(after, 'after')
    for key in ('archive_kind', 'bundle_id', 'archive_sha256', 'archive_size'):
        if a[key] != b[key]:
            raise ValueError('Before and after verification refer to different archive bytes or identity.')
    if a['served_commit'] == b['served_commit']:
        raise ValueError('The SAME served build cannot prove archive redeploy retention.')
    earlier = datetime.fromisoformat(a['verified_at_utc'].replace('Z', '+00:00'))
    later = datetime.fromisoformat(b['verified_at_utc'].replace('Z', '+00:00'))
    if later <= earlier:
        raise ValueError('After receipt must be later than before receipt.')
    return {
        'schema': 1, 'kind': 'enfra-render-archive-redeploy-comparison-v1',
        'archive_kind': a['archive_kind'], 'endpoint': ORIGIN,
        'bundle_id': a['bundle_id'], 'archive_sha256': a['archive_sha256'],
        'archive_size': a['archive_size'], 'before_commit': a['served_commit'],
        'after_commit': b['served_commit'], 'hash_identical_across_distinct_served_builds': True,
        'limits': ('Full archive byte identity on two separately observed served builds only. '
                   'Does not approve authentic report imports, privacy, native Word/Adobe layout, '
                   'physical Safari/device or operational use.'),
    }


def _native_archive_id(classes: list[str], key_prefix: str, chosen_prefix: str, expected_sha: str) -> str:
    """Require one source/hash-bound actual Streamlit download button key."""
    search = re.compile(r'^st-key-' + re.escape(key_prefix) +
                        r'([0-9a-f]{32})_' + expected_sha[:16] + r'\Z')
    matches = {found[1] for value in classes if isinstance(value, str)
               for class_name in value.split()
               if (found := search.fullmatch(class_name))}
    if len(matches) != 1:
        raise AssertionError('No single verified source-bound download is mounted.')
    full = next(iter(matches))
    if full[:12] != chosen_prefix[:12] or (len(chosen_prefix) == 32 and full != chosen_prefix):
        raise AssertionError('Visible selected archive does not match the actual native download.')
    return full


def _browser_route(route, rejected: list[str]) -> None:
    parsed = urlparse(route.request.url)
    if parsed.scheme in ('blob', 'data') or parsed.scheme == 'https' and parsed.netloc == 'msapo-generator.onrender.com':
        route.continue_()
    else:
        rejected.append((parsed.scheme or '?') + ':' + (parsed.hostname or '?'))
        route.abort()


def _check_served(page, expected: str, *, wait: bool) -> None:
    from playwright.sync_api import expect
    deadline = time.monotonic() + (8 * 60 if wait else 1)
    last = ''
    while True:
        try:
            page.goto(ORIGIN + BUILD_ROUTE, wait_until='domcontentloaded', timeout=65000)
            from scripts.qa_public_build import running_code_marker
            marker = running_code_marker(page)
            expect(marker).to_have_text('Running code: ' + expected, timeout=16000)
            return
        except Exception as exc:
            last = type(exc).__name__
            if not wait or time.monotonic() >= deadline:
                raise AssertionError('Expected exact served commit unavailable: ' + last) from exc
            time.sleep(12)


def verify_one(archive_kind: str, bundle_prefix: str, expected_sha: str, expected_size: int,
               served_commit: str, phase: str) -> dict:
    _valid_inputs(archive_kind, bundle_prefix, expected_sha, expected_size, served_commit, phase)
    from playwright.sync_api import sync_playwright, expect
    settings = SHELVES[archive_kind]
    rejected: list[str] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            context.route('**/*', lambda route: _browser_route(route, rejected))
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.set_default_timeout(25000)
            _check_served(page, served_commit, wait=True)
            page.goto(ORIGIN + SHELF_ROUTE, wait_until='domcontentloaded', timeout=65000)
            expect(page.get_by_role('heading', name='Shared report testing', exact=True)).to_be_visible(timeout=60000)
            page.get_by_text(settings['expander'], exact=True).click()
            box = page.get_by_role('combobox', name=settings['selection'], exact=True)
            expect(box).to_be_visible(timeout=45000)
            box.click()
            option = page.get_by_role('option', name=_option_pattern(settings, bundle_prefix[:12]))
            expect(option).to_have_count(1, timeout=20000)
            option.click()
            # Unlike a prior failed synthetic source-key regression, a label
            # or displayed digest alone cannot authorize the download.
            expect(page.get_by_text(re.compile('SHA-256: ' + expected_sha + r'$'))).to_be_visible(timeout=45000)
            page.get_by_role('button', name=settings['prepare'], exact=True).click()
            expect(page.get_by_role('button', name=settings['download'], exact=True)).to_be_visible(timeout=90000)
            classes = page.locator('[class*="st-key-' + settings['key_prefix'] + '"]').evaluate_all(
                '(nodes) => nodes.map(node => node.className).filter(value => typeof value === "string")')
            full_id = _native_archive_id(classes, settings['key_prefix'], bundle_prefix, expected_sha)
            expected_scope = full_id + '_' + expected_sha[:16]
            expect(page.locator('.st-key-' + settings['key_prefix'] + expected_scope)).to_be_visible(timeout=45000)
            with page.expect_download(timeout=240000) as action:
                page.get_by_role('button', name=settings['download'], exact=True).click()
            tmp_path = action.value.path()
            if tmp_path is None:
                raise AssertionError('Archive download was not completed.')
            hasher, size = sha256(), 0
            with Path(tmp_path).open('rb') as stream:
                while chunk := stream.read(256 * 1024):
                    size += len(chunk)
                    if size > settings['max_size']:
                        raise AssertionError('Download exceeded archive size allowance.')
                    hasher.update(chunk)
            if size != expected_size or hasher.hexdigest() != expected_sha:
                raise AssertionError('Downloaded archive differs from the independently expected original.')
            _check_served(page, served_commit, wait=False)
            if rejected or errors:
                raise AssertionError('Browser blocked an external request or raised a script error.')
        finally:
            browser.close()
    return {
        'schema': 1, 'kind': KIND, 'phase': phase, 'endpoint': ORIGIN,
        'archive_kind': archive_kind, 'bundle_id': full_id,
        'archive_sha256': expected_sha, 'archive_size': size,
        'served_commit': served_commit,
        'verified_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'read_only_checks': [
            'exact_served_commit_before', 'selected_archive_identity',
            'downloaded_original_sha256', 'exact_served_commit_after',
        ],
    }


def _save_new(path: Path, receipt: dict) -> None:
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    verify = sub.add_parser('verify', help='Observe/download one existing archive on exact served Render SHA')
    verify.add_argument('--archive-kind', choices=tuple(SHELVES), required=True)
    verify.add_argument('--bundle-prefix', required=True)
    verify.add_argument('--archive-sha256', required=True)
    verify.add_argument('--archive-size', type=int, required=True)
    verify.add_argument('--expected-commit', required=True)
    verify.add_argument('--phase', choices=('before', 'after'), required=True)
    verify.add_argument('--output', type=Path, required=True)
    compare_parser = sub.add_parser('compare', help='Compare two read-only archive receipts')
    compare_parser.add_argument('--before', type=Path, required=True)
    compare_parser.add_argument('--after', type=Path, required=True)
    compare_parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'verify':
        result = verify_one(args.archive_kind, args.bundle_prefix, args.archive_sha256,
                            args.archive_size, args.expected_commit, args.phase)
        _validated_receipt(result, args.phase)
    else:
        result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    _save_new(args.output, result)
    print(json.dumps({
        'accepted': True, 'kind': result['kind'], 'archive_kind': result['archive_kind'],
        'archive_sha256': result['archive_sha256'], 'size': result['archive_size'],
        'output': str(args.output),
    }, sort_keys=True))


if __name__ == '__main__':
    main()
