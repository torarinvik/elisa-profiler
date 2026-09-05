# Compiler integration ledger

The profiler is built with the dedicated Elisa compiler worktree at
`../elisa-compiler-worktrees/profiler`, on branch `codex/profiler`. The compiler
worktree is intentionally separate from every source compiler checkout so profiler
experiments can repair compiler defects without modifying their owners.

The current compiler integration commit is:

```text
b88dbe6 merge: sync latest committed compiler fixes into profiler worktree
```

That merge contains the reviewed source and regression-test deltas found in the
compiler worktrees during the profiler setup, plus the later qualified-module
error-call lowering fix from `codex/wasm-sdk` (`22a0744`). The dedicated compiler
branch also contains the previously committed profiler-facing CLI fix (`770ec6f`)
and the complete committed ancestry of the local compiler branches, including
the `codex/wasm-sdk` tip `c033e9e` that advanced after the earlier `583c4927`
checkpoint. `make
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
`.DS_Store` were not imported; the Neural Workshop worktree had no compiler source
delta to import. The current ledger reports the Neural Workshop scope-binding
test and the structpy parser-machine files as new uncommitted candidate patches,
so they are explicitly pending review rather than assumed absent. Origin worktrees
remain untouched, including their uncommitted `.DS_Store` files.

## Current candidate dispositions

The generated ledger is the detailed record; its current classifications are:

- The main `Elisa-compiler` worktree has a mixed candidate: the relevant files
  already matching `codex/profiler` are an `equivalent-patch`, while its changed
  `c_header.elisa` and `.gitignore` require review. The affected subsystems are
  backend/parser/semantic and the listed effect, packed-store, and differential
  tests are the verification set.
- The temporary verification worktree is an `equivalent-patch` for the local
  region annotation and region-scope fixtures; it has not been rewritten or
  committed from this audit.
- The transpiler stage1 worktree has a distinct backend/parser candidate plus a
  breadth fixture; it remains `candidate-fix-needs-review`.
- The Neural Workshop scope-binding test and structpy parser-machine changes are
  distinct `candidate-fix-needs-review` entries. Their owners' worktrees remain
  byte-for-byte untouched.
- The effect, recovered-interop, dedicated-profiler, and Elisa UI worktrees have
  metadata-only changes and are classified `obsolete-noise-only`.

No uncommitted patch is imported automatically. A candidate closes only after an
independent diff review, its affected tests pass against stage0 and stage1, and a
destination commit records the source path and patch digest.

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
