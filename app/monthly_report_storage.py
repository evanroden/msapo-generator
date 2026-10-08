"""Bounded, read-only storage totals; never enumerate filenames in the UI."""

import os
import shutil
import time

from app.memory import _data_dir


def storage_summary(*, max_entries=50000, seconds=1.0):
    root = _data_dir()
    capacity = shutil.disk_usage(root)
    pending = [root / "monthly_reports"]
    size = count = seen = 0
    complete = True
    inodes = set()
    deadline = time.monotonic() + seconds
    while pending:
        directory = pending.pop()
        if not directory.exists():
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    seen += 1
                    if seen > max_entries or time.monotonic() >= deadline:
                        return dict(total=capacity.total, free=capacity.free, monthly=size,
                                    files=count, complete=False)
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(directory / entry.name)
                    elif entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        inode = (stat.st_dev, stat.st_ino)
                        if inode not in inodes:
                            inodes.add(inode)
                            size += stat.st_size
                            count += 1
        except OSError:
            complete = False
    return dict(total=capacity.total, free=capacity.free, monthly=size,
                files=count, complete=complete)


def readable_bytes(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024
