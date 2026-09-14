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
    rep = dict(repetition=1, capture_complete=True, allocation_events=[e for e in events if not e.get('_layout')], region_layouts=[e for e in events if e.get('_layout')], **extra)
    return module.analyze({'run': {'repetitions': [rep]}})['repetitions'][0]

# Same address after reset is a new lifetime; backing stays retained until free.
r = run([event('region_create', 10, 1024), event('alloc', 100, 32),
         event('region_reset'), event('alloc', 100, 16), event('region_free')])
assert r['lifetime_status'] == 'available', r
assert r['metrics'] == dict(peak_logical_live_bytes=32, logical_live_bytes_at_capture_end=0,
                           peak_observed_backing_capacity_bytes=1024,
                           observed_backing_capacity_at_capture_end_bytes=0,
                           max_retained_backing_capacity_after_reset_bytes=1024,
                           peak_retained_capacity_on_reuse_bytes=1024,
                           mean_retained_capacity_on_reuse_bytes=1024,
                           last_retained_capacity_on_reuse_bytes=1024, observed_reuses=1)
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
    assert r['metrics'] is None and r['lifetime_reason']
    assert 'max_observed_lifetime_ns' not in r['sites'][0]
r = run([event('alloc', 100, 32)], allocation_events_dropped=1)
assert r['metrics'] is None
r = run([event('realloc_in_place', 100, 64, 100, 32)])
assert r['metrics'] is None
print('allocation site analysis PASS')

def layout(arena, index, header, data, capacity):
    return dict(_layout=True, arena=arena, region=index, header_address=header,
                data_address=data, capacity_bytes=capacity, repetition=1)
def owned(arena, kind, address=0, size=0, old=0):
    e = event(kind, address, size, old)
    e['arena'] = arena
    return e
r = run([owned(2, 'region_create', 20, 128), layout(2, 0, 20, 200, 128),
         owned(2, 'alloc', 200, 16), event('region_create', 10, 64),
         layout(1, 0, 10, 100, 64), event('alloc', 100, 8),
         layout(1, 0, 10, 100, 64), layout(1, 1, 20, 200, 128),
         event('arena_adopt', old=2), event('region_rewind', 10, 8),
         event('region_trim'), owned(2, 'region_free'), event('region_free')])
assert r['lifetime_status'] == 'available', r
assert r['metrics']['peak_logical_live_bytes'] == 24
assert r['metrics']['peak_observed_backing_capacity_bytes'] == 192, r
assert r['metrics']['observed_backing_capacity_at_capture_end_bytes'] == 0
assert r['sites'][0]['retired_count'] == 2
r = run([event('region_create', 10, 128), layout(1, 0, 10, 100, 128),
         event('alloc', 100, 16), event('alloc', 116, 16), event('region_rewind', 10, 16)])
assert r['lifetime_status'] == 'available' and r['metrics']['logical_live_bytes_at_capture_end'] == 16, r
r = run([event('region_create', 10, 128), layout(1, 0, 10, 100, 128),
         event('alloc', 100, 16), event('region_rewind', 10, 8)])
assert r['metrics'] is None and 'cuts through' in r['lifetime_reason'], r
print('adoption, trim and rewind analysis PASS')

# Trim between reset and reuse reduces retained capacity; newly allocated backing
# after reset is not retained capacity, even when creation precedes the allocation.
r = run([event('region_create', 10, 64), layout(1, 0, 10, 100, 64),
         event('alloc', 100, 8), dict(event('region_create', 20, 128), region=1),
         layout(1, 1, 20, 200, 128), event('region_reset'), event('region_trim'),
         dict(event('region_create', 30, 256), region=1), layout(1, 1, 30, 400, 256),
         dict(event('alloc', 400, 128), region=1), event('region_free')])
assert r['lifetime_status'] == 'available', r
assert r['metrics']['max_retained_backing_capacity_after_reset_bytes'] == 192
assert r['metrics']['peak_retained_capacity_on_reuse_bytes'] == 64
print('retention at reuse analysis PASS')
