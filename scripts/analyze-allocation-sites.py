#!/usr/bin/env python3
"""Analyze captured Elisa arena evidence, preserving exact integers.

Site traffic is observational. Lifetime accounting supports alloc, resize, move,
reclaim, reset, free, adoption, trim and rewind. Missing region-layout evidence
explicitly invalidates metrics that require physical span reconciliation. No last-use or leak claim is made.
"""
import argparse
import json
from pathlib import Path

LIMIT = 100000
RUNTIME_FILES = ('/elisacore_std/arena.elisa', '/elisacore_std/profiler_hooks.elisa')


def analyze(profile):
    functions = {r['identity_id']: r for r in profile.get('locations', []) if r['kind'] == 'function'}
    locations = {(r['repetition'], r.get('compiler_line')): r for r in profile.get('locations', [])}

    def site(event):
        frames = []
        for item in event.get('site_stack', '-').split(';'):
            if ':' in item:
                identity, line = map(int, item.split(':'))
                frames.append((identity, line))
        selected = next(((i, n) for i, n in reversed(frames)
                         if i != 0 and i in functions and functions[i].get('source')
                         and not functions[i]['source'].endswith(RUNTIME_FILES)), None)
        if selected is None and event.get('site_known') == 1:
            selected = event['site_function_id'], event['site_line']
        if selected is None:
            return 'unknown', {'function': None, 'source': None, 'line': None}
        identity, line = selected
        f = functions.get(identity, {})
        at = locations.get((event['repetition'], line), {})
        return f'{identity}:{line}', {'function': f.get('function'), 'function_id': identity,
                                      'compiler_line': line, 'source': at.get('source'), 'line': at.get('line')}

    output = {'kind': 'elisa_allocation_site_analysis', 'schema_version': 1,
              'scope': 'Observed arena allocations; lifetime ends at a recorded retirement, not inferred last use. Backing capacity is observed capacity, not RSS.',
              'repetitions': []}
    for rep in profile['run']['repetitions']:
        events = rep.get('allocation_events', [])
        layouts = rep.get('region_layouts', [])
        groups = {}
        for event in events[:LIMIT]:
            if event['kind'] not in ('alloc', 'realloc_in_place'):
                continue
            key, description = site(event)
            group = groups.setdefault(key, dict(description, allocation_count=0, requested_bytes=0,
                                                in_place_growth_bytes=0, retired_count=0, max_observed_lifetime_ns=0))
            if event['kind'] == 'alloc':
                group['allocation_count'] += 1
                group['requested_bytes'] += event['size_bytes']
            else:
                group['in_place_growth_bytes'] += max(0, event['size_bytes'] - event['old_size_bytes'])
        reason = None
        if not rep.get('capture_complete') or rep.get('timed_out') or rep.get('detail_budget_exceeded'):
            reason = 'incomplete capture'
        if any(rep.get(k, 0) for k in ('allocation_events_dropped', 'frame_dropped', 'trace_dropped', 'capture_bytes_dropped', 'trace_stack_overflow_entries')):
            reason = 'capture loss or stack overflow'
        if len(events) + len(layouts) > LIMIT:
            reason = 'analysis event bound exceeded'
        if not events:
            reason = 'no allocation evidence'
        live, retired, headers, views = {}, {}, {}, {}
        live_bytes = peak = peak_capacity = retained_at_reset = retained_on_reuse = 0
        awaiting_reuse = {}
        reuse_capacities = []
        sequence = -1
        timestamp = 0

        def close(key, event):
            nonlocal live_bytes
            entry = live.pop(key)
            live_bytes -= entry['size']
            group = groups[entry['site']]
            group['retired_count'] += 1
            group['max_observed_lifetime_ns'] = max(group['max_observed_lifetime_ns'], event['timestamp_ns'] - entry['start'])
            retired[key] = entry['size']

        def capacity():
            return sum(h['capacity'] for h in headers.values())

        def allocation_header(event):
            header = views.get((event['arena'], event['region']))
            if header is None:
                return None
            h = headers.get(header)
            if h is None or h['arena'] != event['arena']:
                raise ValueError('allocation region ownership mismatch')
            if h.get('data') is not None and not (h['data'] <= event['address'] and
                    event['address'] + event['size_bytes'] <= h['data'] + h['capacity']):
                raise ValueError('allocation outside reported region layout')
            return header

        def region_index(arena, header):
            indices = [index for (owner, index), value in views.items() if owner == arena and value == header]
            if len(indices) != 1:
                raise ValueError('missing or ambiguous region-chain position')
            return indices[0]

        def drop_headers(selected):
            for header in selected:
                del headers[header]
            for view in list(views):
                if views[view] in selected:
                    del views[view]

        try:
            if reason:
                raise ValueError(reason)
            ordered = sorted([(e, False) for e in events] + [(e, True) for e in layouts], key=lambda pair: pair[0]['sequence'])
            for event, is_layout in ordered:
                if event['sequence'] != sequence + 1 or event['timestamp_ns'] < timestamp:
                    raise ValueError('non-contiguous sequence or invalid monotonic timestamp')
                sequence, timestamp = event['sequence'], event['timestamp_ns']
                arena = event['arena']
                if is_layout:
                    header = event['header_address']
                    prior = headers.get(header)
                    if prior and prior['capacity'] != event['capacity_bytes']:
                        raise ValueError('region capacity changed without retirement')
                    if prior and prior.get('data') not in (None, event['data_address']):
                        raise ValueError('region data address changed')
                    # Adoption publishes the parent view before its transfer event.
                    # Keep physical ownership until that event and count capacity once.
                    headers[header] = dict(arena=prior['arena'] if prior else arena,
                                           capacity=event['capacity_bytes'], data=event['data_address'])
                    views[arena, event['region']] = header
                    peak_capacity = max(peak_capacity, capacity())
                    continue
                kind, address, size = event['kind'], event['address'], event['size_bytes']
                key = arena, address
                if kind == 'alloc':
                    if arena in awaiting_reuse:
                        retained = sum(headers[h]['capacity'] for h in awaiting_reuse[arena] if h in headers and headers[h]['arena'] == arena)
                        reuse_capacities.append(retained)
                        retained_on_reuse = max(retained_on_reuse, retained)
                        del awaiting_reuse[arena]
                    if size:  # Zero-byte requests carry no independently live span.
                        if not arena or not address or key in live:
                            raise ValueError('ambiguous allocation identity')
                        retired.pop(key, None)
                        site_key, _ = site(event)
                        live[key] = {'size': size, 'start': timestamp, 'site': site_key, 'header': allocation_header(event)}
                        live_bytes += size
                elif kind == 'realloc_in_place':
                    if key not in live or live[key]['size'] != event['old_size_bytes']:
                        raise ValueError('resize without matching allocation')
                    allocation_header(event)
                    live_bytes += size - live[key]['size']
                    live[key]['size'] = size
                elif kind == 'reclaim':
                    old = arena, event['old_address']
                    if event['old_size_bytes']:
                        if old not in live or live[old]['size'] != event['old_size_bytes']:
                            raise ValueError('reclaim without matching allocation')
                        close(old, event)
                elif kind == 'realloc_move':
                    old = arena, event['old_address']
                    if key not in live or live[key]['size'] != size:
                        raise ValueError('move without matching new allocation')
                    if old in live:
                        if live[old]['size'] != event['old_size_bytes']:
                            raise ValueError('move old-size mismatch')
                        close(old, event)
                    elif event['old_size_bytes'] and retired.get(old) != event['old_size_bytes']:
                        raise ValueError('move without matching old allocation')
                elif kind in ('region_reset', 'region_free'):
                    for old in list(live):
                        if old[0] == arena:
                            close(old, event)
                    retired = {k: v for k, v in retired.items() if k[0] != arena}
                    if kind == 'region_free':
                        awaiting_reuse.pop(arena, None)
                        drop_headers({h for h, value in headers.items() if value['arena'] == arena})
                    else:
                        awaiting_reuse[arena] = {h for h, value in headers.items() if value['arena'] == arena}
                        retained_at_reset = max(retained_at_reset, sum(h['capacity'] for h in headers.values() if h['arena'] == arena))
                elif kind == 'region_create':
                    if not arena or not address:
                        raise ValueError('missing backing-region identity')
                    if address in headers:
                        raise ValueError('backing region created twice without retirement')
                    headers[address] = dict(arena=arena, capacity=size, data=None)
                    views[arena, event['region']] = address
                elif kind == 'arena_adopt':
                    child = event['old_address']
                    if not child or child == arena:
                        raise ValueError('missing or invalid adoption source')
                    awaiting_reuse.pop(child, None)
                    transferred = {h for h, value in headers.items() if value['arena'] == child}
                    if not transferred:
                        raise ValueError('adoption without child-region evidence')
                    for header in transferred:
                        region_index(arena, header)
                        headers[header]['arena'] = arena
                    for old in list(live):
                        if old[0] == child:
                            destination = arena, old[1]
                            if destination in live or live[old]['header'] not in transferred:
                                raise ValueError('ambiguous adopted allocation')
                            live[destination] = live.pop(old)
                    for old in list(retired):
                        if old[0] == child:
                            retired[arena, old[1]] = retired.pop(old)
                    for view in list(views):
                        if view[0] == child:
                            del views[view]
                elif kind in ('region_rewind', 'region_trim'):
                    retained = views.get((arena, event['region']))
                    if retained not in headers or headers[retained]['arena'] != arena:
                        raise ValueError('missing retained-region layout')
                    if kind == 'region_rewind':
                        h = headers[retained]
                        if address != retained or h['data'] is None or size > h['capacity']:
                            raise ValueError('invalid rewind mark or missing layout')
                        boundary = h['data'] + size
                    later = {h for h, value in headers.items() if value['arena'] == arena
                             and region_index(arena, h) > event['region']}
                    for old in list(live):
                        if old[0] != arena:
                            continue
                        header = live[old]['header']
                        if header is None:
                            raise ValueError('lifetime boundary requires allocation layout')
                        if header in later:
                            close(old, event)
                        elif kind == 'region_rewind' and header == retained:
                            if old[1] >= boundary:
                                close(old, event)
                            elif old[1] + live[old]['size'] > boundary:
                                raise ValueError('rewind cuts through a live allocation')
                    if kind == 'region_trim':
                        drop_headers(later)
                else:
                    raise ValueError(f'unsupported lifecycle operation: {kind}')
                peak = max(peak, live_bytes)
                peak_capacity = max(peak_capacity, capacity())
        except ValueError as error:
            reason = str(error)
        metrics = None if reason else {'peak_logical_live_bytes': peak, 'logical_live_bytes_at_capture_end': live_bytes,
                                      'peak_observed_backing_capacity_bytes': peak_capacity,
                                      'observed_backing_capacity_at_capture_end_bytes': capacity(),
                                      'max_retained_backing_capacity_after_reset_bytes': retained_at_reset,
                                      'peak_retained_capacity_on_reuse_bytes': retained_on_reuse,
                                      'mean_retained_capacity_on_reuse_bytes': sum(reuse_capacities) / len(reuse_capacities) if reuse_capacities else 0,
                                      'last_retained_capacity_on_reuse_bytes': reuse_capacities[-1] if reuse_capacities else 0,
                                      'observed_reuses': len(reuse_capacities)}
        if reason:
            for group in groups.values():
                group.pop('retired_count')
                group.pop('max_observed_lifetime_ns')
        output['repetitions'].append({'repetition': rep['repetition'], 'lifetime_status': 'available' if not reason else 'unavailable',
                                      'lifetime_reason': reason, 'metrics': metrics,
                                      'traffic_truncated': len(events) > LIMIT,
                                      'sites': sorted(groups.values(), key=lambda g: g['requested_bytes'] + g['in_place_growth_bytes'], reverse=True)})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(analyze(json.loads(args.capture.read_text())), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')
