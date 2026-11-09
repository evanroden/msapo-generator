"""Bounded optional photo recovery service. UI activation is a separate change.

Never replaces a block itself. Callers commit only a validated recovered image
and retain their last-good block for pending/exhausted outcomes.
"""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from app import monthly_report_library as library
from app import monthly_report_cover_storage as private
from app.monthly_report_cover_originals import cover_original_path
from app.monthly_report_cover_images import cover_uploader_limit_mb

MIB = 1024*1024
MAX_OUTPUT_BYTES = 4*MIB
MAX_CACHE_RECORDS = 64
WALL_SECONDS = 15
# Reserve two maximum native (Windows MiB) upload buffers plus 64 MiB margin.
# The exact accepted source cap remains64 MiB; rejected transport padding can
# still briefly occupy native buffers. Existing
# retained uploads are already included in actual cgroup memory.current. This
# is conservative admission, not protection against unlimited concurrent users.
PARENT_UPLOAD_RESERVE = (2*cover_uploader_limit_mb()+64)*MIB
_WORKER = Path(__file__).resolve().parents[1] / 'scripts' / 'cover_image_worker.py'

@dataclass(frozen=True)
class CoverRecoveryOutcome:
    status: str
    image: object = None
    reason: str = ''


def _policy():
    from PIL import __version__ as pillow_version
    from pillow_heif import __version__ as heif_version, libheif_info
    record = {'version':2, 'pillow':pillow_version, 'heif':heif_version,
              'heif_runtime':libheif_info(),
              'worker':hashlib.sha256(_WORKER.read_bytes()).hexdigest(),
              'normalizer':hashlib.sha256((Path(__file__).parent/'monthly_report_docx.py').read_bytes()).hexdigest(),
              'header_guard':hashlib.sha256((Path(__file__).parent/'monthly_report_cover_images.py').read_bytes()).hexdigest(),
              'frame':[1400,1800], 'quality':82, 'alpha':'flatten-white', 'max_output':MAX_OUTPUT_BYTES}
    return hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()


def _validated_image(raw):
    from PIL import Image
    from app.monthly_report_docx import ReportImage
    if not 0 < len(raw) <= MAX_OUTPUT_BYTES:
        raise ValueError('Invalid recovered photograph size.')
    with Image.open(BytesIO(raw)) as image:
        if (image.format != 'JPEG' or image.width > 1400 or image.height > 1800
                or getattr(image,'n_frames',1) != 1):
            raise ValueError('Invalid recovered photograph dimensions or format.')
        image.load()
        return ReportImage(raw, 'jpg',image.width,image.height)


def _read(path, limit):
    with private.open_file(path) as source:
        if os.fstat(source.fileno()).st_size > limit:
            raise ValueError('Invalid cover recovery cache.')
        raw=source.read(limit+1)
    if len(raw)>limit:
        raise ValueError('Invalid cover recovery cache.')
    return raw


def _run_worker(source, target, budget):
    env={'PATH':os.defpath,'LANG':'C.UTF-8','OMP_NUM_THREADS':'1',
         'OPENBLAS_NUM_THREADS':'1','MALLOC_ARENA_MAX':'2'}
    with private.open_file(source) as original, private.directory(target.parent) as output_directory:
        expected = source.name.removesuffix('.original')
        digest = hashlib.file_digest(original, 'sha256').hexdigest()
        if digest != expected:
            raise ValueError('Cover original changed before decoder launch.')
        original.seek(0)
        process=subprocess.Popen([sys.executable,'-I',str(_WORKER),'--fds',str(original.fileno()),
                                  str(output_directory),target.name,str(budget)],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 env=env,start_new_session=True,
                                 pass_fds=(original.fileno(),output_directory))
    try:
        code=process.wait(timeout=WALL_SECONDS)
        return 'success' if code==0 else ('memory_limit' if code==3 else 'decoder_failed')
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return 'timeout'
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()



def _normal_candidate(source, reference):
    """Keep #591's normal admission/codec/pixel guards as the first path.

    Do not turn programmer errors into silent fallback. Only known image
    validation outcomes and decoder/resource failures are classified here.
    """
    from app.monthly_report_cover_images import (check_cover_headroom, cover_photo_suffix, MEMORY_ERROR)
    from app.monthly_report_docx import normalize_report_image
    try:
        check_cover_headroom(reference.byte_count)  # Before copying saved raw.
    except ValueError as exc:
        if str(exc) == MEMORY_ERROR:
            return 'memory', None
        raise
    try:
        raw = _read(source, 64*MIB)
    except MemoryError:
        return 'memory', None
    if len(raw) != reference.byte_count or hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError('Cover original changed before normal decoding.')
    try:
        image = normalize_report_image(raw, cover_photo_suffix(raw, ''), cover_photo=True)
        return 'recovered', _validated_image(image.data)
    except (OSError, MemoryError):
        return 'fallback', None
    except ValueError as exc:
        if str(exc) == MEMORY_ERROR:
            return 'memory', None
        known_policy = (
            'Choose a supported image format', 'Choose a PNG, JPEG, WebP',
            'Choose a fresh PNG or JPEG export', 'Image is too large to decode safely',
            'Choose a single image', 'Image frame information could not be read',
        )
        if str(exc).startswith(known_policy):
            return 'rejected', None
        raise


# A selected upload is foreground work: give an already-running preview a
# bounded chance to finish, while work_slot prevents new previews overtaking it.
# No decoder is admitted until the lock is actually acquired.
WORK_SLOT_WAIT_SECONDS = 5


def recover_cover_original(profile, reference):
    """At most two worker attempts per original/policy, second only at more RAM.

    A cache hit is digest checked; transient contention or unknown headroom is
    not a failed decoder attempt. All data stays local to the profile scope.
    """
    from app.monthly_report_render_jobs import work_slot, RenderBusy, memory_headroom
    source=cover_original_path(profile,reference)
    folder=library._profile_path(profile.contract,profile.key)/'cover-recovery'
    policy=_policy()
    cache_path=folder/(reference.sha256+'.json')
    image_path=folder/(reference.sha256+'.image')
    if os.name!='posix':
        return CoverRecoveryOutcome('pending',reason='isolation_unavailable')
    try:
        with work_slot(wait_seconds=WORK_SLOT_WAIT_SECONDS), private.locked_folder(folder):
            record={}
            if cache_path.exists():
                try:
                    candidate=json.loads(_read(cache_path,16384))
                    if (isinstance(candidate,dict) and candidate.get('policy')==policy
                            and candidate.get('source')==reference.sha256):
                        record=candidate
                    if record.get('status')=='recovered':
                        raw=_read(image_path,MAX_OUTPUT_BYTES)
                        if hashlib.sha256(raw).hexdigest()!=record.get('derivative'):
                            raise ValueError('Invalid recovered photograph digest.')
                        return CoverRecoveryOutcome('recovered',_validated_image(raw))
                except (OSError,ValueError,TypeError):
                    return CoverRecoveryOutcome('pending',reason='cache_integrity')
            if not cache_path.exists():
                if len(private.entries(folder)) > MAX_CACHE_RECORDS*2:
                    return CoverRecoveryOutcome('pending',reason='cache_full')
            if record.get('normal_rejected'):
                return CoverRecoveryOutcome('unrecoverable',reason='image_policy')
            if not record.get('normal_attempted'):
                normal_status, normal_image = _normal_candidate(source, reference)
                record.update(source=reference.sha256,policy=policy,attempts=record.get('attempts',0),
                              budget=record.get('budget',0),normal_attempted=normal_status!='memory')
                if normal_status=='recovered':
                    private.atomic_write(image_path,normal_image.data)
                    record.update(status='recovered',method='normal',reason='',derivative=hashlib.sha256(normal_image.data).hexdigest())
                    private.atomic_write(cache_path,json.dumps(record).encode())
                    return CoverRecoveryOutcome('recovered',normal_image)
                if normal_status=='rejected':
                    record.update(status='failed',normal_rejected=True)
                    private.atomic_write(cache_path,json.dumps(record).encode())
                    return CoverRecoveryOutcome('unrecoverable',reason='image_policy')
                private.atomic_write(cache_path,json.dumps(record).encode())
            available=memory_headroom()
            if available is None or available < PARENT_UPLOAD_RESERVE+64*MIB:
                return CoverRecoveryOutcome('pending',reason='memory_busy')
            budget=min(256*MIB, ((available-PARENT_UPLOAD_RESERVE)//(64*MIB))*(64*MIB))
            attempts=record.get('attempts',0)
            prior_budget=record.get('budget',0)
            if (type(attempts) is not int or type(prior_budget) is not int
                    or attempts<0 or attempts>2):
                return CoverRecoveryOutcome('pending',reason='cache_integrity')
            if attempts>=2 or attempts and budget<=prior_budget:
                return CoverRecoveryOutcome('pending' if record.get('reason') in ('timeout','memory_limit') else 'unrecoverable',reason='attempts_exhausted')
            # Two bounded files per raw source, independent of rerun count.
            if not cache_path.exists():
                count=0
                for entry, info in private.entries(folder):
                    count+=1
                    if count>MAX_CACHE_RECORDS*2:
                        return CoverRecoveryOutcome('pending',reason='cache_full')
            record.update(source=reference.sha256,policy=policy,attempts=attempts+1,
                          budget=budget,status='failed',method='isolated')
            # Persist admission before launch: crashes must not cause retry storms.
            private.atomic_write(cache_path,json.dumps(record).encode())
            with private.temporary_folder(folder) as temporary:
                target=Path(temporary)/'derivative'
                result=_run_worker(source,target,budget)
                if result!='success':
                    record['reason']=result
                    private.atomic_write(cache_path,json.dumps(record).encode())
                    return CoverRecoveryOutcome('pending' if result in ('timeout','memory_limit') else 'unrecoverable',reason=result)
                try:
                    raw=_read(target,MAX_OUTPUT_BYTES)
                    image=_validated_image(raw)
                except (OSError,ValueError):
                    return CoverRecoveryOutcome('unrecoverable',reason='invalid_derivative')
                private.atomic_write(image_path,raw)
                record.update(status='recovered',reason='',derivative=hashlib.sha256(raw).hexdigest())
                private.atomic_write(cache_path,json.dumps(record).encode())
                return CoverRecoveryOutcome('recovered',image)
    except RenderBusy:
        return CoverRecoveryOutcome('pending',reason='work_busy')


def original_reference(occurrence):
    from app.monthly_report_cover_originals import CoverOriginalRef
    return CoverOriginalRef(occurrence.scope,occurrence.sha256,occurrence.byte_count)


def occurrence_from_dict(block):
    from app.monthly_report_model import CoverOriginalOccurrence
    import re
    raw=block.get('cover_original')
    if raw is None:
        return None
    if not isinstance(raw,dict) or block.get('key')!='cover_photo':
        raise ValueError('Invalid cover original occurrence.')
    item=CoverOriginalOccurrence(**raw)
    if (not isinstance(item.occurrence_id,str) or not re.fullmatch(r'[0-9a-f]{32}',item.occurrence_id)
            or any(not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value)
                   for value in (item.scope,item.sha256,item.policy))
            or type(item.byte_count) is not int or not 0<item.byte_count<=64*MIB
            or not isinstance(item.derivative,str)
            or not re.fullmatch(r'[0-9a-f]{64}\.(png|jpg)',item.derivative)
            or tuple(block.get('asset_hashes',()))!=(item.derivative,)):
        raise ValueError('Invalid cover original occurrence.')
    return item


def validate_cover_occurrence(profile, block):
    from dataclasses import asdict
    if block.cover_original is not None:
        occurrence_from_dict(asdict(block))
        cover_original_path(profile,original_reference(block.cover_original))


def prepare_cover_replacement(profile, block, raw, assets):
    """Return a new block only after original retention and derivative validation.

    Snapshot CAS remains the caller's responsibility. Failure never mutates the
    old block or asset mapping; a failed snapshot may leave bounded immutable
    original evidence but cannot alter the saved snapshot head.
    """
    from dataclasses import replace
    from uuid import uuid4
    from app.monthly_report_cover_originals import store_cover_original
    from app.monthly_report_model import CoverOriginalOccurrence, picture_replacement_references
    from app.monthly_report_asset_review import preserve_asset_reviews
    if block.key!='cover_photo':
        raise ValueError('Automatic photograph recovery is cover-only.')
    try:
        reference=store_cover_original(profile,raw)
        outcome=recover_cover_original(profile,reference)
    except (OSError,ValueError):
        return block,CoverRecoveryOutcome('pending',reason='original_storage')
    if outcome.status!='recovered':
        return block,outcome
    image=outcome.image
    derivative=library.asset_reference(image.data,image.extension)
    occurrence=CoverOriginalOccurrence(uuid4().hex,reference.scope,reference.sha256,
                                       reference.byte_count,derivative,_policy())
    result=preserve_asset_reviews(block,replace(
        block,source='Replace once',asset_hashes=(derivative,),cover_original=occurrence,
        asset_captions=(),references=picture_replacement_references(block),
        reviewed_fingerprint='',client_reviewed_fingerprint='',
        asset_provenance=((derivative,()),),client_asset_reviews=()))
    assets[derivative]=image.data
    return result,outcome


def _report_identity(draft):
    record=[draft.profile.contract,draft.profile.key,
            sorted(site.key for site in draft.profile.facilities),draft.period.key]
    return hashlib.sha256(json.dumps(record,ensure_ascii=False).encode()).hexdigest()


def _cover_block(draft):
    from app.monthly_report_model import ResolvedBlock
    return next((block for block in draft.blocks if block.key=='cover_photo'),
                ResolvedBlock('cover_photo','Omit'))


def _current_revision(draft):
    saved=library.load_snapshot(draft.profile.contract,draft.profile.key,draft.period)
    return saved.revision if saved else 0


def request_from_dict(value):
    from app.monthly_report_model import CoverRecoveryRequest
    import re
    if value is None:
        return None
    if not isinstance(value,dict):
        raise ValueError('Invalid cover preparation request.')
    request=CoverRecoveryRequest(**{**value,'events':tuple(value.get('events',()))})
    if (not isinstance(request.occurrence_id,str) or not re.fullmatch('[0-9a-f]{32}',request.occurrence_id)
            or any(not isinstance(item,str) or not re.fullmatch('[0-9a-f]{64}',item)
                   for item in (request.report_identity,request.scope,request.sha256,request.baseline))
            or type(request.byte_count) is not int or not 0<request.byte_count<=64*MIB
            or type(request.bound_revision) is not int or request.bound_revision<0
            or request.status not in ('pending','ready','applied','stale','unrecoverable')
            or len(request.events)>2 or len(set(request.events))!=len(request.events)
            or any(event not in ('upload','resume') for event in request.events)
            or not isinstance(request.reason,str) or len(request.reason)>80
            or not isinstance(request.derivative,str) or (request.derivative and not re.fullmatch('[0-9a-f]{64}\\.(png|jpg)',request.derivative))
            or not isinstance(request.policy,str) or (request.policy and not re.fullmatch('[0-9a-f]{64}',request.policy))
            or request.status in ('ready','applied') and not (request.derivative and request.policy)):
        raise ValueError('Invalid cover preparation request.')
    return request


def _request_matches(draft,revision):
    request=draft.cover_recovery_request
    return (request is not None and request.report_identity==_report_identity(draft)
            and request.bound_revision==revision and request.baseline==_cover_block(draft).fingerprint)


def begin_cover_recovery(draft,raw,*,revision):
    from dataclasses import replace
    from uuid import uuid4
    from app.monthly_report_model import CoverRecoveryRequest
    from app.monthly_report_cover_originals import store_cover_original
    if type(revision) is not int or revision<0 or _current_revision(draft)!=revision:
        raise ValueError('The report changed before this photograph was selected.')
    original=store_cover_original(draft.profile,raw)
    request=CoverRecoveryRequest(uuid4().hex,_report_identity(draft),original.scope,
        original.sha256,original.byte_count,_cover_block(draft).fingerprint,revision)
    return replace(draft,cover_recovery_request=request)


def attempt_cover_recovery(draft,*,revision,assets,event):
    """Prepare only: choosing an upload never applies a new cover photograph."""
    from dataclasses import replace
    request=draft.cover_recovery_request
    if request is None or request.status!='pending' or event in request.events:
        return draft
    if event not in ('upload','resume') or len(request.events)>=2:
        return draft
    if not _request_matches(draft,revision) or _current_revision(draft)!=revision:
        return replace(draft,cover_recovery_request=replace(request,status='stale'))
    request=replace(request,events=(*request.events,event))
    outcome=recover_cover_original(draft.profile,original_reference(request))
    if not _request_matches(draft,revision) or _current_revision(draft)!=revision:
        return replace(draft,cover_recovery_request=replace(request,status='stale'))
    if outcome.status=='recovered':
        image=outcome.image
        reference=library.asset_reference(image.data,image.extension)
        assets[reference]=image.data
        request=replace(request,status='ready',derivative=reference,policy=_policy(),reason='')
    else:
        if outcome.reason in ('work_busy','memory_busy','isolation_unavailable'):
            request=replace(request,events=draft.cover_recovery_request.events)
        request=replace(request,status=outcome.status,reason=outcome.reason)
    return replace(draft,cover_recovery_request=request)


def apply_cover_recovery(draft,*,revision,assets):
    """Explicit normal Use action; never invoked merely by selecting a file."""
    from dataclasses import replace
    from app.monthly_report_model import CoverOriginalOccurrence, picture_replacement_references
    from app.monthly_report_asset_review import preserve_asset_reviews
    request=draft.cover_recovery_request
    if request is None or request.status!='ready':
        return draft
    if not _request_matches(draft,revision) or _current_revision(draft)!=revision:
        return replace(draft,cover_recovery_request=replace(request,status='stale'))
    cover_original_path(draft.profile,original_reference(request))
    raw=assets.get(request.derivative)
    if raw is None:
        raw=library.read_asset(draft.profile.contract,draft.profile.key,request.derivative)
    image=_validated_image(raw)
    if library.asset_reference(raw,image.extension)!=request.derivative:
        raise ValueError('Prepared cover photograph failed its integrity check.')
    old=_cover_block(draft)
    occurrence=CoverOriginalOccurrence(request.occurrence_id,request.scope,request.sha256,
        request.byte_count,request.derivative,request.policy)
    block=preserve_asset_reviews(old,replace(old,source='Replace once',
        asset_hashes=(request.derivative,),cover_original=occurrence,asset_captions=(),
        references=picture_replacement_references(old),reviewed_fingerprint='',
        client_reviewed_fingerprint='',asset_provenance=((request.derivative,()),),client_asset_reviews=()))
    if old.source != 'Omit' and old.asset_hashes == (request.derivative,):
        # Identical displayed artwork retains its existing content/provenance
        # approvals. The newly retained raw occurrence is private metadata.
        block=preserve_asset_reviews(old,replace(old,cover_original=occurrence))
    blocks=tuple(block if item.key=='cover_photo' else item for item in draft.blocks)
    if not any(item.key=='cover_photo' for item in draft.blocks):
        blocks=(*blocks,block)
    return replace(draft,blocks=blocks,cover_recovery_request=replace(request,status='applied'))


def stamp_saved_request(draft,expected_revision,saved_revision):
    """Snapshot CAS has passed before this runs; do not rebase stale intent."""
    from dataclasses import replace
    request=draft.cover_recovery_request
    if request is None:
        return draft
    cover_original_path(draft.profile,original_reference(request))
    if request.status in ('pending','ready'):
        if not _request_matches(draft,expected_revision):
            request=replace(request,status='stale')
        else:
            if request.status=='ready':
                raw=library.read_asset(draft.profile.contract,draft.profile.key,request.derivative)
                image=_validated_image(raw)
                if library.asset_reference(raw,image.extension)!=request.derivative:
                    raise ValueError('Prepared cover photograph failed its integrity check.')
            request=replace(request,bound_revision=saved_revision)
    return replace(draft,cover_recovery_request=request)
