"""One bounded, local photo decode. No report/Streamlit imports or delegates.

Parent must hold the report work slot, validate original integrity and actual
cgroup headroom, enforce wall timeout and reap this process group. RLIMIT_AS is
an address-space ceiling, not proof of total container memory safety.
"""
import os
from pathlib import Path
import resource
import sys
import stat

MAX_INPUT = 64 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
MAX_PIXELS = 40_000_000


def main():
    inherited = sys.argv[1] == '--fds'
    budget = int(sys.argv[5] if inherited else sys.argv[3])
    if not 64*1024*1024 <= budget <= 256*1024*1024:
        return 2
    resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    if inherited:
        input_fd, output_directory, target_name = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        if '/' in target_name or target_name in ('.','..'):
            return 2
        source = os.fdopen(os.dup(input_fd), 'rb')
    else:
        # Standalone QA invocation uses the same no-follow ancestor walk.
        source_path, target_path = Path(sys.argv[1]).absolute(), Path(sys.argv[2]).absolute()
        def directory_fd(path):
            fd = os.open(path.anchor, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                for component in path.parts[1:]:
                    child = os.open(component, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd); fd = child
                return fd
            except BaseException:
                os.close(fd); raise
        parent = directory_fd(source_path.parent)
        try: source = os.fdopen(os.open(source_path.name, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK, dir_fd=parent), 'rb')
        finally: os.close(parent)
        output_directory = directory_fd(target_path.parent)
        target_name = target_path.name
    info = os.fstat(source.fileno())
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INPUT:
        return 2
    # Reuse the exact pure JPEG/WebP header guard before decoder setup. This
    # module's top level imports only dataclasses; heavy app imports are local
    # to functions that this worker never calls.
    import importlib.util
    spec = importlib.util.spec_from_file_location('cover_header_guard', Path(__file__).resolve().parents[1]/'app'/'monthly_report_cover_images.py')
    guard = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = guard
    spec.loader.exec_module(guard)
    encoded = source.read(MAX_INPUT+1)
    header = guard.cover_codec_header(encoded)
    if header is not None and header.width * header.height > MAX_PIXELS:
        return 2
    del encoded
    source.seek(0)
    from PIL import Image, ImageOps
    # Registration uses an already installed, version-locked native decoder.
    # It does not loosen Pillow's truncation/bomb settings or call a delegate.
    from pillow_heif import register_heif_opener
    register_heif_opener(thumbnails=False)
    with Image.open(source) as image:
        if (image.format not in ('JPEG', 'PNG', 'WEBP', 'HEIF')
                or image.width * image.height > MAX_PIXELS
                or getattr(image, 'n_frames', 1) != 1):
            return 2
        if header is not None and (image.format,image.width,image.height)!=(header.format,header.width,header.height):
            return 2
        orientation = image.getexif().get(274, 1)
        image.thumbnail((1800,1400) if orientation in (5,6,7,8) else (1400,1800),
                        Image.Resampling.LANCZOS)
        oriented = ImageOps.exif_transpose(image)
        rgba = oriented.convert('RGBA')
        normalized = Image.new('RGB', rgba.size, 'white')
        normalized.paste(rgba, mask=rgba.getchannel('A'))
        # A successful process exit means a complete, flushed bounded file.
        # Parent still revalidates its contents before calling it recovered.
        output_fd = os.open(target_name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=output_directory)
        with os.fdopen(output_fd, 'wb') as output:
            normalized.save(output, format='JPEG', quality=82, optimize=True)
            output.flush()
            os.fsync(output.fileno())
    return 0


if __name__ == '__main__':
    try:
        status = main()
    except MemoryError:
        status = 3
    except (OSError, ValueError, TypeError, ImportError):
        status = 2
    # Do not emit raw input, metadata, paths or stack traces to report users.
    sys.exit(status)
