from dataclasses import replace
from pathlib import Path
import pytest
from app import monthly_report_cover_originals as originals
from app import monthly_report_cover_recovery as recovery
from app import monthly_report_library as library
from app.monthly_report_model import synthetic_profiles

@pytest.fixture
def profiles(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    a=synthetic_profiles()[0]
    b=replace(a,key='other')
    return a,b

@pytest.mark.parametrize('leaf',['cover-originals','cover-recovery'])
def test_directory_symlink_cannot_read_or_write_other_profile(profiles,leaf):
    a,b=profiles
    raw=b'original'
    ref=originals.store_cover_original(b,raw)
    bpath=library._profile_path(b.contract,b.key)/leaf
    bpath.mkdir(exist_ok=True)
    apath=library._profile_path(a.contract,a.key)/leaf
    apath.parent.mkdir(parents=True,exist_ok=True)
    apath.symlink_to(bpath,target_is_directory=True)
    before={str(p):p.read_bytes() for p in bpath.rglob('*') if p.is_file()}
    if leaf=='cover-originals':
        with pytest.raises((ValueError,OSError)):
            originals.store_cover_original(a,raw)
        with pytest.raises((ValueError,OSError)):
            originals.store_cover_original(a,b'new bytes')
    else:
        own=originals.store_cover_original(a,raw)
        with pytest.raises((ValueError,OSError)):
            recovery.recover_cover_original(a,own)
    assert {str(p):p.read_bytes() for p in bpath.rglob('*') if p.is_file()}==before

@pytest.mark.parametrize('entry',['.write-lock','record.json','output.image'])
def test_private_storage_rejects_final_symlinks_before_writing(profiles,tmp_path,entry):
    from app.monthly_report_cover_storage import locked_folder,atomic_write
    a,b=profiles
    folder=library._profile_path(a.contract,a.key)/'cover-recovery'
    folder.mkdir(parents=True)
    victim=tmp_path/'victim';victim.write_bytes(b'unchanged')
    (folder/entry).symlink_to(victim)
    with pytest.raises((ValueError,OSError)):
        with locked_folder(folder) as descriptor:
            atomic_write(folder/entry,b'new')
    assert victim.read_bytes()==b'unchanged'


def test_profile_ancestor_symlink_is_rejected(profiles):
    a,b=profiles
    originals.store_cover_original(b,b'original')
    apath=library._profile_path(a.contract,a.key)
    apath.symlink_to(library._profile_path(b.contract,b.key),target_is_directory=True)
    with pytest.raises((ValueError,OSError)):
        originals.store_cover_original(a,b'new')


def test_original_and_private_directories_are_owner_only(profiles):
    import stat
    a,b=profiles
    reference=originals.store_cover_original(a,b'original')
    path=originals.cover_original_path(a,reference)
    assert stat.S_IMODE(path.stat().st_mode)==0o400
    assert stat.S_IMODE(path.parent.stat().st_mode)==0o700
    assert stat.S_IMODE((path.parent/'.write-lock').stat().st_mode)==0o600


def test_original_hardlink_cannot_alias_other_profile(profiles):
    import os
    a,b=profiles
    reference=originals.store_cover_original(b,b'original')
    source=originals.cover_original_path(b,reference)
    target=library._profile_path(a.contract,a.key)/'cover-originals'/source.name
    target.parent.mkdir(parents=True)
    os.link(source,target)
    with pytest.raises((ValueError,OSError)):
        originals.store_cover_original(a,b'original')


@pytest.mark.parametrize('leaf',['cover-originals','cover-recovery'])
def test_fifo_is_rejected_before_blocking_open(profiles,leaf):
    import os
    from app.monthly_report_cover_storage import open_file,locked_folder
    a,b=profiles
    folder=library._profile_path(a.contract,a.key)/leaf
    with locked_folder(folder):
        fifo=folder/'fifo'
        os.mkfifo(fifo)
        with pytest.raises((ValueError,OSError)):
            open_file(fifo)
