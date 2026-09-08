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

The dedicated compiler worktree supports opt-in `-fno-omit-frame-pointer`
preparation for native sampling experiments. Its LLVM policy, executable
answers, and macOS ARM64 frame setup are tested at O0–O3. This prerequisite
does not enable native sampling in the profiler: raw-address capture,
validated unwinding, and exact-artifact symbolization remain unimplemented.
Default target compilation and the capability matrix above are unchanged.
Compiler revision `2f8b2180` also passed the self-host gate: gen3 and gen4
objects were byte-identical, and gen3 emitted identical objects on all 40
repeat runs. These correctness checks do not measure sampling overhead.

A private Elisa Mach-O metadata indexer is also tested independently with
`make macho-smoke`. It reads thin little-endian 64-bit headers, UUID location,
and symbol/string-table ranges without copying image bytes. Unsupported formats,
truncation, duplicate metadata commands, invalid sizes, and overlapping tables
are handled explicitly; failed parses clear the output index. It is not a
complete Mach-O loader validator, address resolver, or native capture backend,
and is not yet connected to the profiler CLI.
Its symbol decoder preserves raw type, section, and 64-bit value fields and
returns borrowed name ranges without allocating strings. It checks table
bounds again before reading, handles the specified zero-index empty name,
and rejects invalid string offsets and missing terminators. Symbol values
are not yet resolved to runtime addresses or interpreted as function ranges.
Segment commands are also bounds-checked, including section-array sizing,
file ranges, and virtual-address overflow. The decoder exposes initial memory
protection and unslid virtual ranges with exclusive ends, including zero-fill
segments. Section contents remain unimplemented.

The private offline image mapper builds caller-region-owned segment maps once
from an exact image and a supplied runtime header address. Lookups allocate
nothing and do not reparse the image. Unsigned checked rebasing supports either
slide direction; overlaps, gaps, and non-executable ranges produce distinct
results instead of guessed symbols. Object files and high-VM layouts are not
supported by this mapper. Capturing and verifying runtime image identity and
load generations, resolving function ranges, and CLI integration remain pending.

The native collector's low-level signal and descriptor policy is currently a
POSIX implementation detail. Porting another host requires an audited FFI
adapter, an explicit capability entry, and focused ABI/cleanup tests before
the host is advertised as supported.
