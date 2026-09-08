# Allocation evidence and its current limits

Full and diagnostic captures collect bounded Elisa arena lifecycle records.
Other modes do not enable this collector. Records appear in each measured
`run.repetitions[].allocation_events` array; warmups are excluded. Offline
reports validate the records before displaying them.

Selecting full or diagnostic mode enables collection, but does not prove that
the target uses compatible hooks. Capture capabilities are `active` only when
at least one allocation lifecycle record or hook-drop counter was observed.
With neither, coverage is `unconfirmed` (`no_allocation_hook_evidence`), not a
zero-allocation measurement. Other collection modes report `disabled`.
These are capture-wide observations, not proof of complete coverage in every
repetition or every allocator. Text and HTML reports apply the same distinction,
including when loading older saved captures.

This is runtime hook evidence, not a heap census. The current implementation
does not compute logical live bytes, allocation lifetimes, or leaks. Peak RSS
remains an independent operating-system observation and must not be compared
with a sum of these event sizes as though they measured the same thing.

## Record contract

`kind` and `kind_code` identify the operation. `address`, `size_bytes`,
`old_address`, `old_size_bytes`, `arena`, `region`, `sequence`, `thread_id`,
and `timestamp_ns` are nonnegative uint64 values. `repetition` is positive and
must match the containing repetition. JSON readers must retain integer
precision; JavaScript `Number` cannot represent all these values exactly.

The wire records use version-1 capture framing, independently of hook ABI
versioning. The current runtime requests exact version 1 through
`elisa_profile_allocation_negotiate(uint32_t) -> uint32_t`. A reply of 1
permits calls to `elisa_profile_allocation_event_v1(uint32_t, uintptr_t,
size_t, uintptr_t, size_t, uintptr_t, size_t)`. Zero means unsupported; other
requested versions are rejected, not silently interpreted as version 1.
The ordinary executable shim returns zero and supplies a weak no-op v1 event
function. The collector supplies strong implementations. Negotiation is
allocation-free, stateless, and independent of the selected capture mode.

The collector retains the unversioned `elisa_profile_allocation_event` entry
point for older runtime objects. Such calls do not prove negotiation occurred.
New captures include an optional `allocation_hook_abi` object in each measured
repetition. Its boolean fields record successful `negotiated_v1`, `v1_calls`,
`legacy_calls`, and `rejected_version` observations. They can coexist when a
process contains multiple producers. The collector snapshots atomic evidence
flags when writing metadata; the flags are not event counts or a proof of
complete coverage. A v1 call does not itself prove negotiation occurred.
Older or interrupted captures can omit this object: absence means unknown,
not false. A rejected request means the producer requested an unsupported
version; the current collector supports exact version 1. The requested version
number is not retained. A target linked only to a no-op shim cannot report its
rejection to this collector.

The framed extension payload is `extension\tallocation_hook_abi\t1\tFLAGS`.
Bits 1, 2, 4, and 8 mean negotiated v1, legacy calls, rejected requests, and
v1 calls respectively. The v1 decoder requires one canonical integer from 0
through 15 and rejects duplicate v1 records. Unknown future extension versions
are ignored rather than interpreted using the v1 layout. Missing metadata,
including a dropped metadata frame, does not imply zero observations.

Live and offline text/HTML reports summarize these observations by measured
repetition, including the number with unavailable metadata. The category
counts can overlap; they are not allocation counts and must not be added as
if they partitioned the workload. Rejected-version evidence includes guidance
to use matching producer/collector versions. JSON preserves each repetition's
original flags rather than replacing them with the display summary.

`active` remains observed hook evidence, not an ABI-handshake claim. Do not
assume compatibility with an arbitrary prebuilt executable merely because
full mode was selected. Unsuccessful negotiation emits no v1 events.

| Code | Kind | Current emitted meaning |
| --- | --- | --- |
| 1 | `alloc` | An arena allocation returned `address` with the requested `size_bytes`. This also occurs inside a moved realloc. |
| 2 | `realloc_in_place` | Growth succeeded at the same address; old and new requested sizes are included. |
| 3 | `realloc_move` | Growth returned a different address. This follows the new `alloc` and any successful old-span `reclaim`; it is not another independent allocation. |
| 4 | `reclaim` | The old span entered the arena's reusable free list. The released address and requested size use the `old_*` fields. |
| 5 | `region_create` | A hooked allocation path created a backing region. Its capacity is recorded in bytes, not logical allocated bytes or RSS. |
| 6 | `region_reset` | The arena's block counts/free lists were reset. This affects the whole arena, not only the region index in the record. |
| 7 | `region_trim` | Blocks after the arena's current end were released. The record identifies the retained end index, not a list of freed allocations. |
| 8 | `region_free` | Arena cleanup detached its block chain. Repeated cleanup can emit this operation even when the chain was already empty. |
| 9 | `arena_adopt` | A child's nonempty block chain was transferred into a parent. `arena` identifies the destination parent; `old_address` identifies the consumed child arena, not an allocation. Older hooks emitted zero for the child, which means unavailable identity. |
| 10 | `region_rewind` | Rewind retained the region header in `address` and the bump offset in `size_bytes` within that region. Later regions were reset. The old fields are zero. This offset is not a logical live-byte total. Rewind to an empty mark emits `region_reset` instead. |

The sequence is collector-assigned across allocation callbacks in one process
and is separate from diagnostic trace sequence numbers. Buffers are per thread,
so serialized record order is not necessarily sequence order. Sequence numbers
and addresses are not identities across repetitions or separate processes.
Timestamps are monotonic nanoseconds, not wall-clock or CPU time.

Arena identity must be the reference value itself, not the address of the
callee's reference-parameter slot. Early hook builds used the latter spelling;
their cross-operation arena identities can be inconsistent and must not be used
to reconstruct lifetimes. The arena adoption regression checks allocation,
transfer, and cleanup identity agreement in current builds.

Tail growth consumes only the additional pointer-sized slots. The tail-capacity
regression grows an allocation within its current region and then to exact
capacity, checking that both operations keep the address and emit
`realloc_in_place` with consecutive old/new sizes. An earlier runtime compared
the full new size against unused capacity, causing false fixed-region overflow
or unnecessary relocation in chained arenas.

An explicitly included arena implementation must share the compiler's builtin
allocator entry points. Mixing linked-runtime allocation with a private realloc
implementation splits their reclaimed-span cache and can prevent reuse. The
reuse regression moves a non-tail allocation into a second region, then reuses
its original address in the first region and consumes the split remainder.
Both later allocation records must name that first region, not the current bump
region, and their sizes must sum to the original span. Splitting rebinds the
free-block reference explicitly and preserves the reusable-span count while a
remainder exists. Region indices after adoption
still need a separate identity/remapping contract.

The adopted-reuse fixture also checks a parent with its own region followed by
two child regions. After adoption, both halves of a reclaimed child span must
report parent region 1 rather than child-local region 0. The runtime reindexes
the combined chain during adoption; leaving child-local global indices caused
reuse/reclaim evidence to alias existing parent regions. The fixture verifies
addresses, sizes, transferred arena identity, and the new region index. This
does not yet supply a complete region-layout map for offline lifetime analysis.

The reset fixture records allocation, reset, replacement allocation, and cleanup
in sequence. The replacement can reuse the same backing address and size, but
it is a new logical lifetime: a future live-allocation table must not identify
allocations by address alone across reset boundaries. This fixture checks raw
event coverage; it does not establish live-byte accounting.

## Loss and collection boundaries

The collector uses fixed-width records, a shared capture-byte budget, and a
thread-local recursion guard. Formatting happens during the final dump, not
inside allocation callbacks. Independent callbacks still take a shared lock;
this is not yet a lock-free allocation profiler.

`allocation_events_dropped` reports collector allocation-buffer refusals.
General capture completeness and transport/budget diagnostics still apply:
a zero allocation-drop count does not prove that every runtime operation had
a hook or that the complete artifact survived. Recursive collector callbacks
are intentionally suppressed. Allocation callbacks after the final dump are
ignored, so late shutdown operations are outside that capture boundary.

## Prerequisites for lifetime accounting

### Region-layout transport under development

The collector exposes a separate exact-v1 negotiation function,
`elisa_profile_region_layout_negotiate(uint32_t)`, and
`elisa_profile_region_layout_v1(uintptr_t arena, size_t region,
uintptr_t header, uintptr_t data_base, size_t capacity_bytes)`.
Unsupported versions return zero. Layout is not a logical allocation.
Its wire payload is `extension\tregion_layout\t1`, followed by arena, region
index, header address, data-base address, capacity bytes, sequence, thread ID,
and monotonic timestamp, all decimal integers separated by tabs.

Layout records share bounded storage, the capture budget, and chronological
sequence with allocation evidence. Buffer refusals contribute to the existing
allocation-evidence drop counter. The record type is stored separately from
the allocation kind, so an allocation kind cannot masquerade as a layout.
Framed/unframed collector tests verify exact fields and distinguish the record
from allocation events. The Elisa decoder preserves v1 records in each
repetition's `region_layouts` array, separately from `allocation_events`.
Raw capture and offline artifact readers validate unsigned 64-bit fields,
nonzero arena/header identities, data addresses strictly beyond the header,
and capacity ranges that do not overflow. Offline records must belong to the
containing repetition and contain exactly the nine schema fields. Unknown
future layout versions remain forward-compatible and are ignored.

Native regression verifies schema validation and lossless offline JSON
preservation; protocol tests cover malformed fields and uint64 boundaries.
The compiler runtime emits layout on first bump allocation in an empty region,
on reclaimed-span reuse, and when adoption reindexes the parent chain. This
includes regions created up front by a region declaration, which need not
produce an allocation-path `region_create` event. Repeated layouts are valid
observations, not additional backing allocations. Adoption preserves header
and data addresses while changing arena ownership and region indices.

Real native fixtures verify that emitted layouts precede and contain their
allocations, and that adoption preserves backing geometry. Unused regions and
other lifecycle paths are not yet comprehensively mapped. Map reconciliation
remains unfinished; these records do not establish complete lifetime metrics.
`collection_stack_acquire` now emits a layout and logical allocation for each
fresh or reused table stack. Dictionary/set reserve helpers emit `reclaim`
only after rehash has finished reading the old stack. This is logical table
retirement, not an OS free: backing remains available for ping-pong reuse.
Sizes describe claimed uintptr slots in bytes. Direct stack callers must
report retirement after their own last read through the same helper.

The focused reuse capture observes three claims and two retirements; the real
dictionary/set workload also produces claim, retirement, and layout records.
The retirement helper recognizes collection-stack table bases only. Initial
tables from other allocation paths and foreign/static tables are not retired
by that helper. Thus this closes stack-claim visibility, not complete collection
allocation accounting or the remaining lifetime reconciliation requirements.

### Lifetime-state engine

`src/profiler/allocation_lifetimes.elisa` provides the initial bounded Elisa
state engine, tested by `make allocation-lifetimes-smoke`. It assigns monotonic
generations independently of address reuse and implements logical allocation,
release, and arena reset. Capacity exhaustion, numeric overflow, duplicate live
identity, or a missing release freezes the state with an explicit quality code.
Frozen totals are not exact final totals and must not be presented as such.
The capacity bounds retained entries, including reusable retired slots; it is
not a limit on the total number of observed lifetimes.

The engine's in-place resize operation requires the recorded old size to
match, preserves generation and allocation count, and updates live/peak bytes.
Its cumulative allocated-byte counter counts initial requests plus positive
in-place growth; shrink does not subtract past traffic. A zero-size resize
retains the entry until an explicit release/reset. Overflow or inconsistent
old-size evidence freezes the state before changing size or byte totals.
These are analysis rules, not evidence that the runtime emits every resize:
the runtime's early-return shrink/zero path still needs hook coverage.

Moved realloc reconciliation consumes an already observed destination
allocation and the latest retained source generation. It retires a still-live
source or consumes its preceding release evidence; it never adds a third
allocation or repeats the destination's traffic. The temporary overlap of old
and new requests remains part of observed peak live bytes. Duplicate moves,
size mismatch, erased source history, and moves across reset boundaries
invalidate state. Retired slots may hold older instances of the same address,
so source selection uses generation order rather than table position.

Logical adoption transfers child ownership without changing generations,
allocation counts, or byte totals. A later child reset cannot release the
transferred allocations; parent release/reset can. Destination collisions and
self-adoption are rejected before changing any entry. Empty-child adoption is
valid. This state operation does not solve raw region-index remapping, and it
does not preserve pending realloc-release evidence across adoption boundaries.

The state engine also accepts a caller-verified half-open address range for
bulk logical release. It preflights all live entries, rejects partial overlaps
before mutation, limits release to the specified arena, and leaves cumulative
traffic and peak totals unchanged. Empty ranges are no-ops; zero-size entries
at the exclusive end are outside the range. This convention is not itself a
rewind interpretation: the reconciler still needs explicit region data-base
and boundary evidence, including how zero-size allocations relate to marks.
The current raw header/offset pair must not be treated as that complete map.

This engine is not connected to capture reports yet. Raw-event ordering,
realloc/adoption/rewind reconciliation, region identity, loss propagation,
lifetime distributions, and performance validation remain necessary before
that integration. No user-facing live-byte or leak claims are enabled by it.

Before enabling live-byte or lifetime claims, the following gaps need code and
independent allocator-oracle coverage:

- Allocation generations must distinguish reused addresses and arena headers.
- A moved realloc must reconcile its component events without double counting.
  An old span that cannot enter the free list can remain physically retained.
- Current `arena_realloc` returns immediately when the requested size does not
  grow, including zero-size requests. It emits no resize/free event in that path.
  Failed growth does not emit a success record and can terminate the target.
- Rewind records now expose the retained region and bump offset. Consumers still
  need to reconcile discarded allocations and reset later regions. Region creation
  through paths outside the hooked allocator must be inventoried before claiming
  complete backing capacity accounting. Older readers that only recognize event
  kinds 1–9 reject rewind records; framing version 1 is not ABI negotiation.
- Adoption now carries child identity but still needs a region-identity remapping contract.
  Reclaim and free-list reuse report the owning block index; adoption still needs
  to reconcile indices transferred from a different arena.
- Region-wide destruction, reset, and trim need explicit reconciliation rules
  for a bounded live-state table, with visible quality degradation after loss.
- Allocation sites, stacks, tasks, foreign allocators, and allocation sampling
  are not currently represented.

Live-at-end allocations, once implemented, will be retention evidence. Calling
them leaks requires separate ownership/lifetime proof.
