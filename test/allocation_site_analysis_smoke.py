#!/usr/bin/env python3
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('sites', Path(__file__).resolve().parents[1] / 'scripts/analyze-allocation-sites.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def event(kind, address=0, size=0, old=0, old_size=0):
    return dict(kind=kind, arena=1, region=0, address=address, size_bytes=size,
                old_address=old, old_size_bytes=old_size, repetition=1)

def run(events, **extra):
    for i, e in enumerate(events):
        e.update(sequence=i, timestamp_ns=10*i)
    rep = dict(repetition=1, capture_complete=True, allocation_events=events, **extra)
    return module.analyze({'run': {'repetitions': [rep]}})['repetitions'][0]

# Same address after reset is a new lifetime; backing stays retained until free.
r = run([event('region_create', 10, 1024), event('alloc', 100, 32),
         event('region_reset'), event('alloc', 100, 16), event('region_free')])
assert r['lifetime_status'] == 'available', r
assert r['metrics'] == dict(peak_logical_live_bytes=32, logical_live_bytes_at_capture_end=0,
                           peak_observed_backing_capacity_bytes=1024,
                           observed_backing_capacity_at_capture_end_bytes=0,
                           max_retained_backing_capacity_after_reset_bytes=1024)
assert r['sites'][0]['retired_count'] == 2
assert r['sites'][0]['max_observed_lifetime_ns'] == 10
# Moved realloc's preceding alloc is counted exactly once, including old reclaim.
r = run([event('alloc', 100, 32), event('alloc', 200, 64),
         event('reclaim', old=100, old_size=32), event('realloc_move', 200, 64, 100, 32),
         event('realloc_in_place', 200, 96, 200, 64), event('region_free')])
assert r['lifetime_status'] == 'available', r
assert r['sites'][0]['requested_bytes'] == 96
assert r['sites'][0]['in_place_growth_bytes'] == 32
assert r['metrics']['peak_logical_live_bytes'] == 96
for kind in ('region_rewind', 'region_trim', 'arena_adopt'):
    r = run([event('alloc', 100, 32), event(kind)])
    assert r['metrics'] is None and 'unsupported' in r['lifetime_reason']
    assert 'max_observed_lifetime_ns' not in r['sites'][0]
r = run([event('alloc', 100, 32)], allocation_events_dropped=1)
assert r['metrics'] is None
r = run([event('realloc_in_place', 100, 64, 100, 32)])
assert r['metrics'] is None
print('allocation site analysis PASS')
