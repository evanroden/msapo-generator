"""Private cover files: descriptor-relative, no-follow access on Linux.

Reject links in every ancestor and final entry. The ordinary report library's
QA guard alone is not profile containment, and these bytes must not join its
cross-profile immutable object pool.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from uuid import uuid4

from app import monthly_report_library as library


def _guard(path):
    path=Path(path).absolute()
    root=library._root().absolute()
    if os.name!='posix' or '..' in path.parts or not path.is_relative_to(root):
        raise ValueError('Private cover storage is outside its supported scope.')
    library._qa_path_guard(path)
    return path


@contextmanager
def directory(path,*,create=False):
    path=_guard(path)
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    descriptor=os.open(path.anchor,flags)
    try:
        for part in path.parts[1:]:
            if create:
                try:os.mkdir(part,0o700,dir_fd=descriptor)
                except FileExistsError:pass
            child=os.open(part,flags,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        yield descriptor
    finally:
        os.close(descriptor)


def open_file(path):
    path=_guard(path)
    with directory(path.parent) as parent:
        descriptor=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    info=os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        os.close(descriptor)
        raise ValueError('Private cover file is linked or invalid.')
    return os.fdopen(descriptor,'rb')


@contextmanager
def locked_folder(path):
    import fcntl
    path=_guard(path)
    with directory(path,create=True) as parent:
        os.fchmod(parent,0o700)
        lock=os.open('.write-lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=parent)
        try:
            info=os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size:
                raise ValueError('Private cover lock is invalid.')
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield parent
        finally:
            os.close(lock)


def entries(path):
    with directory(path) as parent:
        return [(name,os.stat(name,dir_fd=parent,follow_symlinks=False)) for name in os.listdir(parent)]


def atomic_write(path,raw,*,mode=0o600):
    if not isinstance(raw, bytes) or len(raw) > 64*1024*1024:
        raise ValueError('Private cover write exceeds its hard byte bound.')
    path=_guard(path)
    with directory(path.parent) as parent:
        try:current=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:current=None
        if current is not None and (not stat.S_ISREG(current.st_mode) or current.st_nlink!=1):
            raise ValueError('Private cover destination is linked or invalid.')
        temporary='.pending-'+uuid4().hex
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        try:
            with os.fdopen(descriptor,'wb') as output:
                output.write(raw);output.flush();os.fchmod(output.fileno(),mode);os.fsync(output.fileno())
            os.replace(temporary,path.name,src_dir_fd=parent,dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:os.unlink(temporary,dir_fd=parent)
            except FileNotFoundError:pass


@contextmanager
def temporary_folder(folder):
    folder=_guard(folder)
    with directory(folder) as parent:
        name='.cover-recovery-'+uuid4().hex
        os.mkdir(name,0o700,dir_fd=parent)
        temporary=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        identity=os.fstat(temporary)
        try:
            yield folder/name
        finally:
            # Only the worker's one-level private outputs. Never follow a
            # malicious entry or recursively remove a substituted directory.
            try:
                for child in os.listdir(temporary):
                    info=os.stat(child,dir_fd=temporary,follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        raise ValueError('Unexpected directory in cover worker output.')
                    os.unlink(child,dir_fd=temporary)
            finally:
                os.close(temporary)
            current=os.stat(name,dir_fd=parent,follow_symlinks=False)
            if (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):
                raise ValueError('Cover temporary directory changed during recovery.')
            os.rmdir(name,dir_fd=parent)
