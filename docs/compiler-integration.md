# Compiler integration ledger

The profiler is built with the dedicated Elisa compiler worktree at
`../elisa-compiler-worktrees/profiler`, on branch `codex/profiler`. The compiler
worktree is intentionally separate from every source compiler checkout so profiler
experiments can repair compiler defects without modifying their owners.

The current compiler integration commit is:

```text
8636a9d3 test: guard gen2 self-host construction
```

The dedicated branch contains the reviewed source and regression-test deltas
found in the compiler worktrees during profiler setup, the qualified-module
error-call lowering fix from `codex/wasm-sdk`, and the later packed-header
storage fix from the main compiler checkout. The `codex/wasm-sdk` tip
`4f368a66` is included through merge `330633ea`; `d8cadbb1` then corrects
generated C-header accounting for inline dynamic-AoS common fields versus
side-table common fields and records the packed side-table offsets accurately.
`5028591f` fixes the parity harness defaults so a compiler worktree nested
under `elisa-compiler-worktrees/` resolves the sibling stage0 checkout at
`../../../Go projects/structpy-tree` instead of the nonexistent path under
`Elisa Projects/`. The dedicated compiler branch also contains the previously
committed profiler-facing CLI fix and the complete committed ancestry of the
local compiler branches. `make
compiler-audit` is the repeatable check that every local branch tip remains an
ancestor of the dedicated compiler branch. It also writes the ignored
`build/compiler-integration-ledger.json` file atomically. The ledger is the
authoritative observation for that audit run: it records the UTC observation
time, dedicated HEAD, local branch tips, fetched-or-cached remote refs, every
registered worktree, porcelain status records, relevant untracked files, and a
content digest for each dirty patch.

Remote refresh is best effort. A successful `git fetch --all --prune` marks
remote refs as `refreshed`; a disconnected or failing refresh leaves the refs
marked `cached` and records the command status and output. Set
`ELISA_COMPILER_AUDIT_FETCH=0` only for an explicitly offline audit.

Worktree dispositions are deliberately narrow:

- `clean` has no uncommitted status records.
- `ignored-no-source-delta` contains only known desktop metadata such as
  `.DS_Store` and is not treated as a compiler fix.
- `pending-source-patch` contains uncommitted compiler or test source and needs
  review before import.
- `pending-non-source-patch` contains other uncommitted material and needs an
  explicit disposition.

An ancestry match proves only that a commit is reachable. It does not prove
semantic equivalence for a dirty patch, a conflict resolution, or the binary
currently on disk. Those require a reviewed import commit and the compiler
build manifest/provenance checks described below.

After a successful seed, the profiler Makefile writes
`../elisa-compiler-worktrees/profiler/build/compiler-build-manifest.json`. This
manifest is content-addressed over the compiler inputs and records the source
commit, relevant dirty-source digest, stage0/stage1/runtime hashes, seed and
native flags, LLVM tool versions and hashes, architecture, and discovered trace
ABI symbols/capabilities. `compiler-manifest-smoke` validates the current
artifact and proves that changing a build flag invalidates the identity. A
failed or interrupted seed cannot replace the existing binary or manifest:
seed outputs use private temporary names and are published only after the
complete image links successfully.

## Imported changes

The following source-level deltas were copied into the dedicated worktree without
mutating their original worktrees:

- The main `Elisa-compiler` checkout: condition code generation, effect identity and
  operator parsing, control-block and machine-statement parsing, abstract-effect and
  packed-store checking, effect-handler parity coverage, packed-store differential
  cases, dotted-handler negative fixtures, and the new-region probe.
- The temporary compiler verification worktree: local-region annotation checking,
  region-scope parity coverage, and its new-region probe.
- The transpiler stage1 worktree: module code generation, packed-register and type
  table code generation, machine-statement and aggregate-type parsing, and breadth
  object-emission coverage.
- The wasm SDK compiler branch: qualified module error-call lowering and its
  parity/reproduction fixtures, merged as committed source rather than copied
  over the sibling worktree.

The other audited worktrees were inspected as well. Worktrees whose only delta was
`.DS_Store` were not imported; the Neural Workshop worktree had no missing compiler
source delta to import. The current ledger still reports dirty owner worktrees as
pending because the audit intentionally does not infer equivalence from a dirty
checkout. Independent content review found that the Neural Workshop
scope-binding test is already present in the dedicated checkout; the structpy
parser-machine changes are represented by the newer machine-parser implementation
and its diagnostic fixture; and the transpiler-stage1 source deltas are already
represented by newer or equivalent dedicated implementations. No additional
source patch was missing, so none of those owner worktrees was rewritten. Origin
worktrees remain untouched, including their uncommitted `.DS_Store` files.

## Current candidate dispositions

The generated ledger is the detailed record; its current classifications are:

- The main `Elisa-compiler` worktree has a mixed candidate: the relevant files
  already matching `codex/profiler` are an `equivalent-patch`; its packed-header
  `c_header.elisa` fix was independently reviewed, parity-tested, and imported
  as `d8cadbb1`. Its unrelated `.gitignore` change remains unimported. The
  affected subsystems are backend/parser/semantic and packed-header emission;
  the listed effect, packed-store, and differential tests are the verification
  set.
- The temporary verification worktree is an `equivalent-patch` for the local
  region annotation and region-scope fixtures; it has not been rewritten or
  committed from this audit.
- The transpiler stage1 worktree has a distinct backend/parser candidate plus a
  breadth fixture. Content review found the behavior already represented by
  newer or equivalent implementations in the dedicated checkout; the dirty
  owner patch remains an audit `candidate-fix-needs-review` entry because the
  owner worktree itself is still dirty.
- The Neural Workshop scope-binding test and structpy parser-machine changes
  are likewise already represented in the dedicated checkout. Their dirty
  owner entries remain `candidate-fix-needs-review` for provenance purposes;
  the owners' worktrees remain byte-for-byte untouched.
- The effect, recovered-interop, dedicated-profiler, and Elisa UI worktrees have
  metadata-only changes and are classified `obsolete-noise-only`.

No uncommitted patch is imported automatically. A candidate closes only after an
independent diff review, its affected tests pass against stage0 and stage1, and a
destination commit records the source path and patch digest. The packed-header
candidate is the exception now closed by `d8cadbb1`; the source checkout itself
was not rewritten.

## Verification contract

Before changing the profiler compiler pin, run:

```sh
make compiler-audit
make compiler-ledger-smoke
make compiler-manifest-smoke
make compiler-seed
make compiler-smoke
make profiler-native-smoke
```

The native profiler itself remains Elisa code. The C collector is only the explicit
low-level ABI/runtime component used by the generated target and is not an alternate
profiler CLI or report implementation.

The compiler bootstrap fixed-point check is exposed separately as
`make compiler-self-host-smoke`. It runs the dedicated compiler's gen2/gen3 gate,
including the fixed-blocker probes, compiler self-compilation, byte-level gen3/gen4
fixed-point comparison, and repeated gen3 determinism probes. The compiler gate now
bounds every probe class, not only the large compiler-source requests: a host loader
stall is reported as a timeout with retained diagnostics instead of hanging the
profiler integration suite. Gen2 construction is also RSS-guarded by compiler
commit `8636a9d3`, so an oversized self-host build reports a bounded failure
instead of surfacing only as process status 137. This target is intentionally
separate from the ordinary native-profiler smoke because it is a high-memory
compiler validation and may be skipped or retried when the macOS loader is
unhealthy.
