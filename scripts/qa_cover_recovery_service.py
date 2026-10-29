"""Hosted-only full Streamlit service smoke, browser OUTSIDE capped container.

Does not launch a server, change cgroups, inject report state, or replace any
production guard. The workflow owns the real 512 MiB/.5 CPU service. All edits
use native browser controls in the marked isolated synthetic fixture.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
import re
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
MIB = 1024 * 1024
RECEIPT = '[data-cover-service-receipt]'



def synthetic_photo(visitor):
    """Known visual signature independent of report state and asset receipts."""
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(420,250),('navy','purple')[visitor])
    draw=ImageDraw.Draw(image)
    draw.rectangle((30,30,130,220),fill=(12,230,210))
    draw.rectangle((280,30,390,220),fill=(240,70,15))
    stream=BytesIO();image.save(stream,'PNG')
    return stream.getvalue()


def assert_visible_last_good(raster):
    """Independent first-page raster check, not an expected-assets echo.

    Two unusual source colors must occupy visible areas in the correct order.
    This proves the invented chosen art survived failed replacement in rendered
    PDF, not full cover layout fidelity (which still needs visual acceptance).
    """
    from PIL import Image
    with Image.open(BytesIO(raster)) as image:
        image=image.convert('RGB')
        assert image.width*image.height<=2_000_000
        points=[[],[]]
        colors=((12,230,210),(240,70,15))
        for y in range(image.height):
            for x in range(image.width):
                color=image.getpixel((x,y))
                for n,expected in enumerate(colors):
                    if max(abs(a-b) for a,b in zip(color,expected))<=14:
                        points[n].append((x,y))
        assert all(len(p)>100 for p in points), 'Last-good artwork color regions missing from rendered cover'
        centers=[(sum(x for x,y in p)/len(p),sum(y for x,y in p)/len(p)) for p in points]
        assert centers[0][0]<centers[1][0], 'Last-good artwork orientation changed'
        assert abs(centers[0][1]-centers[1][1])<image.height*.08, 'Last-good artwork regions displaced'
        return {'matching_pixels':[len(p) for p in points],'region_centers':centers,
                'raster_size':image.size}

def docker_json(container, code):
    result = subprocess.run(['docker', 'exec', container, 'python', '-c', code],
                            capture_output=True, text=True, timeout=20, check=True)
    return json.loads(result.stdout)


def resources(container):
    return docker_json(container, """
import json
from pathlib import Path
p=Path('/sys/fs/cgroup')
print(json.dumps({k:(p/k).read_text().strip() for k in
 ('memory.current','memory.peak','memory.max','memory.swap.max','memory.events','cpu.max')}))
""")


def assert_resources(value):
    assert int(value['memory.max']) == 512*MIB
    assert value['memory.swap.max'] == '0'
    quota, period = map(int, value['cpu.max'].split())
    assert quota / period == .5
    assert int(value['memory.peak']) <= 512*MIB
    events = dict(line.split() for line in value['memory.events'].splitlines())
    assert int(events['oom_kill']) == int(events['oom']) == 0


def runtime_bookkeeping(root, path):
    """Validate exactly two ephemeral renderer records, never report content.

    These records can change during background previews. Do not compare their
    mtime/hash as user content, but reject links, unexpected bytes or scope.
    """
    import os
    import stat
    relative = path.relative_to(root).as_posix()
    if relative not in ("render-jobs/.conversion-lock", "render-jobs/.active-office.json"):
        return False
    assert not root.is_symlink() and not path.parent.is_symlink()
    assert path.parent.is_dir()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return True  # Only these exact transient records may disappear.
    try:
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        limit = 0 if path.name == ".conversion-lock" else 1024
        assert 0 <= info.st_size <= limit
        raw = os.read(fd, limit + 1)
        assert len(raw) <= limit
        if path.name == ".conversion-lock":
            assert raw == b""
        else:
            value = json.loads(raw)
            assert type(value) is dict and set(value) == {"pid", "boot"}
            assert type(value["pid"]) is int and value["pid"] > 1
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            assert value["boot"] == boot + ":" + os.readlink("/proc/self/ns/pid")
    finally:
        os.close(fd)
    return True


def inventory(container, token):
    # Exact namespace only, fresh bounded streaming hashes; no original bytes
    # leave the service. Unlike the small history observer, this inventory is
    # explicitly scoped to the resource gate and accepts bounded64 MiB files.
    assert len(token) == 32 and all(c in '0123456789abcdef' for c in token)
    return docker_json(container, """
import hashlib,json
from pathlib import Path
from scripts.qa_cover_recovery_service import runtime_bookkeeping
base=Path('/qa-data')
assert base.is_dir() and not base.is_symlink()
assert (base/'monthly-dom-synthetic-only.marker').read_text()=='synthetic-monthly-dom-v1'
identity=hashlib.sha256(('monthly-qa-v1:'+TOKEN).encode('ascii')).hexdigest()[:32]
parent=base/'_enfra_monthly_report_qa_v1';target=parent/identity
assert not parent.is_symlink() and not target.is_symlink() and target.is_dir()
marker=target/'.enfra-qa-namespace'
assert not marker.is_symlink() and marker.read_text().split('|')[0]==identity
root=target/'monthly_reports'
assert not root.is_symlink() and root.resolve().is_relative_to(base.resolve())
out={};total=0
for n,p in enumerate(sorted(root.rglob('*'))):
 assert n<1024 and not p.is_symlink()
 if runtime_bookkeeping(root,p):continue
 if not p.is_file():continue
 stat=p.stat();total+=stat.st_size
 assert stat.st_size<=64*1024*1024 and total<=384*1024*1024
 with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 out[str(p.relative_to(root))]=[stat.st_size,stat.st_mtime_ns,digest]
print(json.dumps(out))
""".replace('TOKEN', repr(token)))


def unchanged(before, after, *, token, original_digest, allow_derivatives=(), last_good_reference=""):
    """Exact permitted private source/cache and current-journal paths only."""
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    contract = library._contract_directory(fixture.CONTRACT)
    profile = library._valid_key(fixture.profile().key)
    journal = Path('active_work')/sha256(token.encode('ascii')).hexdigest()/contract/profile/fixture.PERIOD.key
    private = Path('library')/contract/profile
    permitted = {str(journal/'working.json')}
    permitted.update(str(private/folder/name) for folder,names in (
        ('cover-originals',('.write-lock',original_digest+'.original')),
        ('cover-recovery',('.write-lock',original_digest+'.json',original_digest+'.image')))
        for name in names)
    for reference in allow_derivatives:
        digest=reference.split('.')[0]
        permitted.update((str(journal/'assets'/reference),str(Path('objects')/digest[:2]/digest),
                          str(Path('objects')/digest[:2]/'.write-lock')))
    if last_good_reference:
        # A shared save clears private journal assets. Keeping a later pending
        # upload may recreate ONLY the already-selected photograph in that
        # browser journal. Bind it to independently hashed pre-action library
        # bytes; never allow a new shared asset, object, profile or arbitrary ref.
        assert re.fullmatch(r'[0-9a-f]{64}\.jpg', last_good_reference)
        source = before.get(str(private/'assets'/last_good_reference))
        assert source is not None and 0 < source[0] <= 4*MIB
        assert source[2] == last_good_reference.split('.')[0]
        target = str(journal/'assets'/last_good_reference)
        if target in after:
            assert after[target][0] == source[0] and after[target][2] == source[2], 'Last-good journal copy changed'
        permitted.add(target)
    for name, record in before.items():
        if name != str(journal/'working.json'):
            assert after.get(name) == record, ('Existing stored file changed', name)
    unexpected = after.keys()-before.keys()-permitted
    assert not unexpected, ('Unrelated stored file added', sorted(unexpected)[:8], len(unexpected))
    original=after[str(private/'cover-originals'/(original_digest+'.original'))]
    assert original[2] == original_digest, 'Retained original is not the exact uploaded source'


def wait(page, *, after=0, status=None, revision=None):
    from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout
    try:
        return _wait(page, after=after, status=status, revision=revision)
    except BrowserTimeout:
        # Preserve the first failure, with only the existing bounded synthetic
        # read-only receipt. Never fetch source bytes or alter timeout/assertions.
        serialized = '{"receipt":"unavailable"}'
        try:
            raw = page.locator(RECEIPT).last.get_attribute(
                'data-cover-service-receipt', timeout=1000)
            if raw is not None and len(raw.encode('utf-8')) <= 32 * 1024:
                value = json.loads(raw)
                if isinstance(value, dict):
                    candidate = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                    if len(candidate.encode('utf-8')) <= 32 * 1024:
                        serialized = candidate
        except (BrowserError, ValueError, RecursionError):
            pass  # Diagnostic failure must not replace the original timeout.
        print('COVER_SERVICE_TIMEOUT_RECEIPT ' + serialized, flush=True)
        raise


def _wait(page, *, after=0, status=None, revision=None):
    page.wait_for_function("""w => {
 const es=document.querySelectorAll('[data-cover-service-receipt]');
 if(!es.length)return false;
 const s=JSON.parse(es[es.length-1].dataset.coverServiceReceipt);
 return s.sequence>w.after && (w.status==null||s.working?.request?.status===w.status) &&
 (w.revision==null||s.revision===w.revision) &&
 JSON.stringify(s.working)===JSON.stringify(s.durable) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
 }""", arg={'after':after, 'status':status, 'revision':revision}, timeout=120000)
    return json.loads(page.locator(RECEIPT).last.get_attribute('data-cover-service-receipt'))


def panel(page):
    return page.locator('.st-key-epc_pair_monthly_cover').get_by_test_id('stExpander').filter(
        has=page.locator('summary').get_by_text('Change cover photograph', exact=True))


def open_panel(page):
    p = panel(page)
    if not p.evaluate("n => n.matches('details') ? n.open : n.querySelector('details').open"):
        p.locator('summary').click()
    return p


def upload(page, raw, name):
    p = open_panel(page)
    sequence = wait(page)['sequence']
    p.get_by_test_id('stFileUploader').filter(has=page.get_by_text(
        'New photograph for this report', exact=True)).locator('input[type=file]').set_input_files(
            {'name': name, 'mimeType': 'image/png', 'buffer': raw} if isinstance(raw, bytes) else str(raw))
    return wait(page, after=sequence)


def same_content(old, new):
    for field in ('fingerprint', 'cover', 'sources'):
        assert old['working'][field] == new['working'][field], ('Unexpected report change', field)
    assert old['versions'] == new['versions'] and old['revision'] == new['revision']


def main(args):
    from PIL import Image
    from playwright.sync_api import sync_playwright
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {'kind':'full-running-service-browser', 'controlled_contention':True,
                'stages':[], 'acceptance':'pending'}
    parsed = urlparse(args.url)
    assert parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
    def checkpoint(stage, state=None):
        measured = resources(args.container); assert_resources(measured)
        with urlopen(args.url + '/_stcore/health', timeout=10) as response:
            assert response.status == 200 and response.read(64).strip() == b'ok'
        evidence['stages'].append({'stage':stage, 'resources':measured, 'receipt':state})
        (args.output/'evidence.json').write_text(json.dumps(evidence, indent=2))
    try:
        checkpoint('before-browser')
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            contexts=[]; pages=[]; tokens=[]
            for i in range(2):
                context=browser.new_context(viewport={'width':1365,'height':900})
                token=secrets.token_hex(16)
                context.add_cookies([{'name':'epc_device_id','value':token,'url':args.url}])
                def route(request):
                    target=urlparse(request.request.url)
                    if target.scheme in ('data','blob') or (target.hostname=='127.0.0.1' and target.port==parsed.port):
                        request.continue_()
                    else: request.abort()
                context.route('**/*',route)
                page=context.new_page(); page.set_default_timeout(120000)
                page.goto(args.url+'/?workflow=monthly&monthly_qa=isolated', wait_until='domcontentloaded')
                wait(page, revision=0)
                # Real fixture button only; no session-state or report injection.
                page.get_by_role('button',name='Load known-value report',exact=True).click()
                wait(page, revision=1)
                chosen_raw=synthetic_photo(i)
                baseline=wait(page);before=inventory(args.container,token)
                ready=upload(page,chosen_raw,'synthetic-last-good.png')
                assert ready['working']['request']['status']=='ready'
                assert ready['working']['request']['sha256']==sha256(chosen_raw).hexdigest()
                same_content(baseline,ready)
                p=panel(page);p.get_by_role('button',name='Use this photograph',exact=True).click()
                used=wait(page,after=ready['sequence'],status='applied')
                assert used['working']['cover']['asset_hashes']
                derivative=used['working']['cover']['asset_hashes'][0]
                unchanged(before,inventory(args.container,token),token=token,original_digest=sha256(chosen_raw).hexdigest(),allow_derivatives=(derivative,))
                # The new chosen synthetic photograph still requires the normal
                # explicit client-picture review; no backend approval injection.
                review=page.get_by_role('button',name='Confirm this picture is ready (unless left for correction)',exact=True)
                review.click()
                used=wait(page,after=used['sequence'])
                # Save normal shared versions so failure checks protect actual history.
                history=page.get_by_test_id('stExpander').filter(has=page.locator('summary').get_by_text('Shared report history',exact=True))
                if not history.evaluate("n => n.matches('details') ? n.open : n.querySelector('details').open"):
                    history.locator('summary').click()
                history.get_by_role('button',name='Save shared version',exact=True).click()
                used=wait(page,revision=2)
                contexts.append(context);pages.append(page);tokens.append(token)
                checkpoint('visitor-'+str(i)+'-last-good-saved',used)
            other_before=inventory(args.container,tokens[1])
            page=pages[0];token=tokens[0]
            baseline=wait(page);before=inventory(args.container,token)
            failed=upload(page,b'not a decodable photograph','synthetic-corrupt.png')
            assert failed['working']['request']['status']=='unrecoverable'
            same_content(baseline,failed);unchanged(before,inventory(args.container,token),token=token,original_digest=sha256(b'not a decodable photograph').hexdigest(),last_good_reference=baseline['working']['cover']['asset_hashes'][0])
            checkpoint('corrupt-retains-last-good-and-history',failed)
            # Bounded real process lock. No decoder or report function mocked.
            page.get_by_role('button',name='QA hold real report work slot for 15 seconds',exact=True).click()
            page.get_by_text('QA controlled contention active: true',exact=True).wait_for()
            out=BytesIO();Image.new('RGB',(430,260),'orange').save(out,'PNG')
            baseline=wait(page);before=inventory(args.container,token)
            busy=upload(page,out.getvalue(),'synthetic-contended.png')
            assert busy['working']['request']['status']=='pending'
            assert busy['working']['request']['reason']=='work_busy'
            same_content(baseline,busy);unchanged(before,inventory(args.container,token),token=token,original_digest=sha256(out.getvalue()).hexdigest())
            checkpoint('controlled-real-lock-retains-last-good',busy)
            page.get_by_role('button',name='QA release controlled report contention',exact=True).click()
            wait(page,after=busy['sequence'])
            page.reload(wait_until='domcontentloaded')
            ready=wait(page,status='ready')
            same_content(baseline,ready)
            # This newly prepared art is NOT selected; generate last-good output.
            checkpoint('pending-resumes-without-auto-applying',ready)
            page.get_by_role('button',name='Generate QA Word and PDF',exact=True).click()
            for label,filename in (('Download isolated QA DOCX','last-good.docx'),('Download isolated QA PDF','last-good.pdf')):
                button=page.get_by_role('button',name=label,exact=True)
                button.wait_for(timeout=180000)
                with page.expect_download(timeout=120000) as downloaded:button.click()
                downloaded.value.save_as(str(args.output/filename))
            with ZipFile(args.output/'last-good.docx') as archive:
                selected=baseline['working']['cover']['asset_hashes'][0]
                assert any(sha256(archive.read(n)).hexdigest()==selected.split('.')[0]
                           for n in archive.namelist() if n.startswith('word/media/'))
            import pymupdf
            with pymupdf.open(args.output/'last-good.pdf') as pdf:
                assert len(pdf)>=10
                assert '3 total, 2 completed, 1 open' in '\n'.join(p.get_text() for p in pdf)
                raster=pdf[0].get_pixmap(matrix=pymupdf.Matrix(1,1),alpha=False).tobytes('png')
                evidence['rendered_last_good_art']=assert_visible_last_good(raster)
                (args.output/'last-good-cover.png').write_bytes(raster)
            same_content(baseline,wait(page))
            checkpoint('real-last-good-word-and-pdf')
            assert inventory(args.container,tokens[1])==other_before, 'Other visitor namespace changed'
            # Two actual native multipart uploads retained in distinct live
            # Streamlit sessions, not BytesIO wrappers or direct function calls.
            large=args.fixtures/'progressive-444.jpg'
            assert 30*MIB<large.stat().st_size<=64*MIB
            with large.open('rb') as source:
                from hashlib import file_digest
                large_digest=file_digest(source,'sha256').hexdigest()
            states=[]
            for page,token in zip(pages,tokens):
                baseline=wait(page);before=inventory(args.container,token)
                state=upload(page,large,large.name)
                same_content(baseline,state)
                assert state['working']['request']['status'] in ('pending','unrecoverable','ready')
                assert large.stat().st_size in state['held_upload_sizes']
                assert state['working']['request']['sha256']==large_digest
                unchanged(before,inventory(args.container,token),token=token,original_digest=large_digest,allow_derivatives=(state['working']['request']['derivative'],) if state['working']['request']['status']=='ready' else ())
                states.append(state)
                checkpoint('large-native-upload-'+str(len(states)),state)
            # No reload or Use: a native read-only receipt action proves BOTH
            # sessions are still alive with their own uploader bytes retained.
            for page in pages:
                old=wait(page)
                page.get_by_role('button',name='QA refresh cover service receipt',exact=True).click()
                fresh=wait(page,after=old['sequence'])
                same_content(old,fresh)
                assert large.stat().st_size in fresh['held_upload_sizes']
                assert fresh['working']['request']['sha256']==large_digest
            for page in pages:
                assert page.get_by_test_id('stException').count()==0
            evidence['retained_native_upload_bytes']=2*large.stat().st_size
            checkpoint('two-browser-held-large-uploads')
            browser.close()
        evidence['browser_steps']='passed'
    finally:
        try:
            checkpoint('final')
            inspect=json.loads(subprocess.check_output(['docker','inspect',args.container],text=True))[0]
            evidence['container_state']=inspect['State']
            assert not inspect['State']['OOMKilled'] and inspect['State']['Running']
            if evidence.get('browser_steps')=='passed':evidence['acceptance']='passed'
        finally:
            (args.output/'evidence.json').write_text(json.dumps(evidence,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--container',required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args())
