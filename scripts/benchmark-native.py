#!/usr/bin/env python3
"""Paired, uninstrumented execution timing alongside instrumented profiles.

Inputs must be ordinary executables. Compilation is excluded; stdout/stderr and
successful exit are required to agree. CPU includes child user+system time.
Wall time includes launch/exit overhead, so use workloads lasting tens of ms.
"""
import argparse
import hashlib
import json
import pathlib
import random
import resource
import statistics
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def measure(binary, data, timeout):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    result = subprocess.run([str(binary)], input=data, capture_output=True, timeout=timeout)
    elapsed = time.perf_counter_ns() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if result.returncode != 0:
        raise RuntimeError(f'{binary.name} exited {result.returncode}')
    return dict(wall_ms=elapsed / 1e6,
                cpu_ms=1000 * (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime),
                stdout_sha256=digest(result.stdout), stderr_sha256=digest(result.stderr))


def benchmark(baseline, candidate, data, repeat, warmup, timeout, seed):
    binaries = {'baseline': baseline, 'candidate': candidate}
    identity = None
    samples = []
    rng = random.Random(seed)
    for pair in range(-warmup, repeat):
        order = ['baseline', 'candidate']
        if rng.randrange(2):
            order.reverse()
        for name in order:
            result = measure(binaries[name], data, timeout)
            output = result['stdout_sha256'], result['stderr_sha256']
            if identity is None:
                identity = output
            if output != identity:
                raise RuntimeError(f'output mismatch in {name}, pair {pair}')
            if pair >= 0:
                samples.append(dict(pair=pair, variant=name, **result))
    summary = {}
    for key in ('wall_ms', 'cpu_ms'):
        a = [s[key] for s in samples if s['variant'] == 'baseline']
        b = [s[key] for s in samples if s['variant'] == 'candidate']
        summary[key] = dict(baseline_median=statistics.median(a),
                            candidate_median=statistics.median(b),
                            candidate_over_baseline=statistics.median(b)/statistics.median(a) if statistics.median(a) else None,
                            baseline_min=min(a), baseline_max=max(a), candidate_min=min(b), candidate_max=max(b))
    return dict(schema_version=1, measurement='uninstrumented_child_execution',
                limits=['wall time includes process startup and shutdown',
                        'CPU is aggregate child user plus system time',
                        'paired random order does not eliminate host load or thermal noise',
                        'instrumented profiles must be collected separately'],
                seed=seed, repeat=repeat, warmup=warmup, stdin_sha256=digest(data),
                binaries={k: dict(path=str(v), sha256=digest(v.read_bytes())) for k,v in binaries.items()},
                samples=samples, summary=summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=pathlib.Path, required=True)
    parser.add_argument('--candidate', type=pathlib.Path, required=True)
    parser.add_argument('--stdin', type=pathlib.Path)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--repeat', type=int, default=15)
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--seed', type=int, default=20260914)
    args = parser.parse_args()
    if args.repeat < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error('repeat and timeout must be positive; warmup must be nonnegative')
    result = benchmark(args.baseline.resolve(), args.candidate.resolve(),
                       args.stdin.read_bytes() if args.stdin else b'',
                       args.repeat, args.warmup, args.timeout, args.seed)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
