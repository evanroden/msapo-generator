"""Compare real capped-container A34 resource probe logs (not browser metrics)."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def load(path):
    for line in Path(path).read_text().splitlines():
        if line.startswith('A34_RESULT:'):
            return json.loads(line[len('A34_RESULT:'):])
    raise ValueError(f'Missing completed synthetic A34 result: {path}')


def main(control_path, high_path):
    control, high = load(control_path), load(high_path)
    assert control['limit_bytes'] <= 512 * 1024**2
    assert high['limit_bytes'] >= 2 * 1024**3
    assert control['effective_workers'] == 1
    assert high['effective_workers'] == 2
    for record in (control, high):
        assert record['synthetic_only'] and record['original_sha256_preserved']
        assert record['memory_events_delta'].get('oom', 0) == 0
        assert record['memory_events_delta'].get('oom_kill', 0) == 0
        assert record['sampled_peak_cgroup_bytes'] < record['limit_bytes']
        for phase in ('cold', 'warm'):
            assert len(record[phase]['visitors']) == 2
            assert all(visitor['photo_count'] >= 8
                       for visitor in record[phase]['visitors'])
    comparison = {
        'control_peak_bytes': control['sampled_peak_cgroup_bytes'],
        'higher_peak_bytes': high['sampled_peak_cgroup_bytes'],
        'control_cold_seconds': control['cold']['makespan_seconds'],
        'higher_cold_seconds': high['cold']['makespan_seconds'],
        'control_warm_seconds': control['warm']['makespan_seconds'],
        'higher_warm_seconds': high['warm']['makespan_seconds'],
        'control_warm_max_queue_seconds': control['warm']['max_queue_seconds'],
        'higher_warm_max_queue_seconds': high['warm']['max_queue_seconds'],
    }
    print(json.dumps(comparison, indent=2))
    # A queue benefit is a deterministic admission outcome, not proof that
    # conversion or browser first-paint became faster. Do not block CI on
    # wall-clock speed, which changes with runner CPU contention.
    assert high['warm']['max_queue_seconds'] < control['warm']['max_queue_seconds']


if __name__ == '__main__':
    main(*sys.argv[1:])
