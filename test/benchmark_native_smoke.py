#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
spec = importlib.util.spec_from_file_location('bench', Path(__file__).resolve().parents[1]/'scripts/benchmark-native.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    for name,body in [('slow','exec sleep 1')]:
        p=root/name
        p.write_text('#!/bin/sh\n'+body+'\n')
        p.chmod(0o755)
    cat=Path(shutil.which('cat'))
    r=module.benchmark(cat,cat,b'42\n',3,1,30,1)
    assert len(r['samples']) == 6
    assert {s['pair'] for s in r['samples']} == {0,1,2}
    assert r['summary']['wall_ms']['baseline_median'] > 0
    for name,reason in [('true','output mismatch'),('false','exited 1')]:
        try:
            module.benchmark(cat,Path(shutil.which(name)),b'42\n',1,0,30,1)
            raise AssertionError('invalid benchmark accepted')
        except RuntimeError as error:
            assert reason in str(error)
    try:
        module.measure(root/'slow',b'',0.01)
        raise AssertionError('timeout ignored')
    except subprocess.TimeoutExpired:
        pass
print('uninstrumented paired benchmark PASS')
