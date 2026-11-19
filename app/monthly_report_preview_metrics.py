"""Optional phase timing for cold Monthly previews, without report/source data.

Enable MSAPO_PREVIEW_TIMINGS=1 in a synthetic QA run. Disabled by default;
neither keys, owners, file paths nor client content enter the timing log.
"""
from contextlib import contextmanager
from functools import wraps
import logging
import os
import sys
from time import perf_counter, process_time

_LOG = logging.getLogger(__name__)


def _rss_kib():
    if sys.platform != "linux":
        return -1
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


@contextmanager
def phase(name):
    if os.environ.get("MSAPO_PREVIEW_TIMINGS") != "1":
        yield
        return
    start_wall, start_cpu = perf_counter(), process_time()
    try:
        yield
    finally:
        _LOG.warning(
            "monthly_preview_phase=%s wall_ms=%.1f cpu_ms=%.1f peak_rss_kib=%d",
            name, (perf_counter() - start_wall) * 1000,
            (process_time() - start_cpu) * 1000, _rss_kib(),
        )


def measured(name):
    def decorate(fn):
        @wraps(fn)
        def timed(*args, **kwargs):
            with phase(name):
                return fn(*args, **kwargs)
        return timed
    return decorate
