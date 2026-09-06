# Compiler integration ledger

The profiler is built with the dedicated Elisa compiler worktree at
`../elisa-compiler-worktrees/profiler`, on branch `codex/profiler`. The compiler
worktree is intentionally separate from every source compiler checkout so profiler
experiments can repair compiler defects without modifying their owners.

The current compiler integration commit is:

```text
1cf1815f Merge branch 'work' into codex/profiler
```

The dedicated branch contains the reviewed source and regression-test deltas
found across the compiler worktrees, including the packed-header, nested-module,
qualified-`usize`, stage0-path, qualified-error-recovery, lexical-error-family,
stable-module-identity, bounded self-host, scope-binding, machine-start
fallback, lmut-threading/parity, region-owned-return, storage-invalidation,
and process-tree termination fixes. All 11 local compiler branch tips are
reachable from the dedicated branch.

The audit is authoritative for branch/worktree provenance. The latest offline
ledger records 11 local branches, 11 registered worktrees, nine dirty
worktrees, and four pending source-bearing worktrees. The source candidates
were reviewed path-by-path against the dedicated checkout: the main `work`
checkout, the transpiler stage1 checkout, the Neural Workshop checkout, and
the structpy checkout. Compatible deltas were imported where they
were independently verifiable; the remaining dirty portions are either already
superseded or AST-incompatible. All owner worktrees remain untouched.

The stage1 product was freshly reseeded from `1cf1815f` with the canonical
stage0 compiler and its usable build manifest was regenerated. The audit and
manifest are current. The full gate passes as
`DYLD_SHARED_REGION=avoid TMPDIR=/tmp make test`, including self-host stages
A through D, compiler smoke, native profiler/report/artifact/comparison
smokes, collector/ABI checks, timeout/recovery checks, and cleanup checks. A
normal run under concurrent compiler corpus jobs can hit a macOS dynamic-loader
stall in `_dyld_start` before the profiler enters its main code; the explicit
`DYLD_SHARED_REGION=avoid` setting is a verification workaround for that host
condition and is not part of the profiler contract.

Historical checkpoints below retain earlier commit and test evidence for the
build pipeline, but must not be read as proof of the current stage1 identity.

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
ABI symbols/capabilities, including the optional compiler-issued stable-ID
callbacks used by the profiler when present. `compiler-manifest-smoke` validates the current
artifact and proves that changing a build flag invalidates the identity. A
failed or interrupted seed cannot replace the existing binary or manifest:
seed outputs use private temporary names and are published only after the
complete image links successfully.

The native profiler invokes `scripts/elisac_stage1.sh` for each profiled target
and passes `ELISA_STAGE1_BIN` through that wrapper. This is intentional: the
wrapper translates profiler-facing options such as `-ftrace`; invoking the
stage1 binary directly can produce an uninstrumented target while still
returning a successful object build. `ELISA_COMPILER_SCRIPT` overrides the
wrapper for source-stability and compiler-integration tests.

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
- The wasm SDK compiler branch: qualified module error-call lowering plus its
  packed/effect/semantic-gate and self-host regression fixes, merged through
  committed ancestry rather than copied over the sibling worktree.

The other audited worktrees were inspected as well. Worktrees whose only delta was
`.DS_Store` were not imported; the Neural Workshop worktree had no missing compiler
source delta to import. The current ledger still reports dirty owner worktrees as
pending because the audit intentionally does not infer equivalence from a dirty
checkout. Independent content review found that the Neural Workshop
scope-binding test is already present in the dedicated checkout; the structpy
parser-machine changes are represented by the newer machine-parser implementation;
the compatible machine-start fallback and storage-invalidation diagnostic fixture
were imported as `2dbf556c`, the region-return checker was imported as
`321527c0`, the default-storage diagnostic correction was committed as
`f8b7474e`, and the process-tree termination fix was merged from `6052bf65`.
The remaining dirty patch references AST
variants absent from the dedicated compiler and was not copied. The transpiler-
stage1 source deltas are already represented by newer or equivalent dedicated
implementations. The remaining main-checkout path differences were likewise either superseded in the dedicated
worktree or were the nested parity-script path fix committed as `88f09c8d`. No
additional compiler source patch was missing, so none of those owner worktrees
was rewritten. Origin worktrees remain untouched, including their uncommitted
`.DS_Store` files and generated binary noise.

## Current candidate dispositions

The generated ledger is the detailed record; its current classifications are:

- The main `Elisa-compiler` worktree has a mixed candidate: its packed-header
  `c_header.elisa` fix was independently reviewed, parity-tested, and imported
  as `d8cadbb1`, and its later semantic/parser/backend source patch was
  independently reviewed and imported as `46c0671c`. Its remaining owner
  checkout changes are either already represented by equivalent/newer
  dedicated content or are test-path hygiene committed as `88f09c8d`; the
  owner checkout remains untouched. The affected subsystems
  are backend/parser/semantic and packed-header emission; diagnostics,
  semantic-acceptance, internal-differential, and native profiler gates are the
  verification set.
- The transpiler stage1 worktree has a dirty layout/state candidate. The
  dedicated checkout already has the more advanced packed-layout and parser
  implementation, so the owner patch was not copied or rewritten.
- The Neural Workshop worktree has an older scope-binding robustness candidate;
  the dedicated scope-binding smoke path is already more advanced, so the owner
  patch was not copied or rewritten.
- The structpy worktree has a dirty parser-machine candidate that refers to AST
  variants not present in the current dedicated parser. Its compatible
  machine-start fallback and diagnostic fixture were imported as `2dbf556c`,
  while the incompatible `Ast::Stmt.AugAssign`/`AsRefAssign` portions were
  rejected; the owner worktree was not changed.
- The missing temporary verification worktree is recorded as pending non-source
  provenance only. It contributes no importable source delta.
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

For the current `1cf1815f` integration, the audit, ledger, manifest, compiler,
native profiler, and full profiler gates pass with the loader workaround above.
Keep the self-host gate in the
verification contract: it is the required evidence that the local compiler
remains a fixed point and deterministic after future compiler changes.

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
