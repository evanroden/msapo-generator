# Forward-message reference compatibility (Streamlit 1.61.1)

The pinned native client now advertises an empty `cached_message_hashes` list
from its first rerun request. This changes only the WebSocket connection's
advertisement getter. Native message decoding, ordering, cache storage and
expiration, widget values, rerun coalescing, and report approval remain unchanged.

Why: the server selects references from a request's cache snapshot. A preceding
run can finish after that request was sent and evict an advertised message before
its reference arrives. The native client throws on a missing reference and stops
ordered message delivery. The exact pinned cache classes reproduce this ordering;
the preserved Water failure establishes a cache miss and overlapping requests,
not the missing message's exact historical age.

There is no request acknowledgment in this protocol sufficient to safely release
a temporary cache lease or overlap-only suppression flag. Increasing cache age,
retaining advertised messages forever, retrying edits, and swallowing missing
references are not this repair.

## Delivery and resource limits

- New immutable frontend generation; all historical generated assets remain
  reconstructable and available. A new page load is required. Already-open old
  tabs and their in-flight references are not retroactively repaired.
- More repeated full message bytes may be sent. There are no additional requests
  or cache-lifetime extensions. This is **not** a claim of zero bandwidth cost.
- Inline image groups make that cost material. Six synthetic 1280×720 JPEG85
  images measured 5,580,271 bytes in the native component ForwardMsg, versus
  6,212 bytes using separately managed image URLs. This is native protobuf
  serialization evidence, not browser network or cache acceptance.
- Keep native browser Water, source, Training and Progress acceptance mandatory;
  verify the newly served entry and measure metadata-only WebSocket/HTTP byte
  totals with realistic images. Do not weaken the first-action assertions or
  add rescue retries.

## Reproducible checks

`tests/test_streamlit_forward_cache.py` executes exact native cache/advertisement
bodies with a failing-before control, native server reference selection, request
coalescing, fresh/same connection objects, source pin rejection, and immutable
previous-generation upgrade checks. These local checks do not substitute for
actual browser reconnection and report-output acceptance.
