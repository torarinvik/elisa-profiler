# Host capability matrix

`elisa-profiler doctor --format json` is the machine-readable source of truth
for the capabilities available on the current host. This matrix describes the
current native implementation, not a promise that every future platform has
the same backend.

| Capability | macOS arm64/x86_64 | Linux arm64/x86_64 | Other hosts |
| --- | --- | --- | --- |
| Launch profiling | supported through direct `execv` | supported through direct `execv` | unsupported unless the native ABI is ported |
| Wall timing | `CLOCK_MONOTONIC` | `CLOCK_MONOTONIC` | unavailable until the clock binding is verified |
| CPU sampling | experimental `SIGPROF` + `ITIMER_PROF`; instrumented Elisa frames only | experimental `SIGPROF` + `ITIMER_PROF`; instrumented Elisa frames only | unsupported |
| User/kernel sample split | not emitted | not emitted | unsupported |
| Attach to an existing process | unsupported | unsupported | unsupported |
| Native unwind and symbolization | unsupported; no raw address stream | unsupported; no raw address stream | unsupported |
| Allocation lifecycle | unsupported until compiler/runtime hooks exist | unsupported until compiler/runtime hooks exist | unsupported |
| Task/wait lifecycle | unsupported until runtime scheduler hooks exist | unsupported until runtime scheduler hooks exist | unsupported |

Sampling setup can still fail for an individual target. A report must use the
capture's `sampling_detail` and `sampling_setup_failed` fields rather than infer
support from the host name. Likewise, unsupported allocation/task fields are
reported as unavailable, never as zero.

The native collector's low-level signal and descriptor policy is currently a
POSIX implementation detail. Porting another host requires an audited FFI
adapter, an explicit capability entry, and focused ABI/cleanup tests before
the host is advertised as supported.
