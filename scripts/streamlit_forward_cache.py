"""Avoid stale client cache promises in the pinned Streamlit wire protocol.

A rerun's cached hash snapshot can outlive an intervening run completion's
cache eviction. Streamlit 1.61.1 has no request acknowledgment tying those
lifetimes together. Advertise no references from connection construction;
leave message decoding, normal cache expiration, and widget delivery native.
This trades repeat payload bandwidth for reference correctness. Existing tabs
must load the new immutable entry; there is no live transport mutation.
"""
from hashlib import sha256

INDEX_SHA256 = '2ca8d2fdc237ec568ac10b8aae70c21e28c9e25ea1924378f068f7a81af6fe6e'
ORIGINAL = b'getCachedMessageHashes(){return this.cache.getCachedMessageHashes()}async handleMessage(e)'
REPAIRED = b'getCachedMessageHashes(){return []}async handleMessage(e)'


def repair_forward_cache(raw):
    if sha256(raw).hexdigest() != INDEX_SHA256 or raw.count(ORIGINAL) != 1:
        raise RuntimeError('Unexpected locked ForwardMsg cache boundary; no bytes were changed.')
    return raw.replace(ORIGINAL, REPAIRED, 1)
