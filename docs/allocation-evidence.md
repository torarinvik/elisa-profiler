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
