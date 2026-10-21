"""Constant-space synthetic wire size counters; never retain payloads."""
class WireTotals:
    def __init__(self):
        self.values = {d: dict(frames=0, bytes=0, maximum=0, references=0)
                       for d in ('sent', 'received')}

    def frame(self, direction, raw):
        if direction not in self.values or not isinstance(raw, bytes):
            return
        item = self.values[direction]
        item['frames'] += 1
        item['bytes'] += len(raw)
        item['maximum'] = max(item['maximum'], len(raw))

    def kind(self, direction, kind):
        if direction in self.values and kind == 'ref_hash':
            self.values[direction]['references'] += 1

    def snapshot(self):
        return {direction: dict(values) for direction, values in self.values.items()}
