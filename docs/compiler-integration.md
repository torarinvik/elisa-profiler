# Compiler integration ledger

The profiler is built with the dedicated Elisa compiler worktree at
`../elisa-compiler-worktrees/profiler`, on branch `codex/profiler`. The compiler
worktree is intentionally separate from every source compiler checkout so profiler
experiments can repair compiler defects without modifying their owners.

The current compiler integration commit is:

```text
583c492 merge: sync latest compiler fixes into profiler worktree
```

That merge contains the reviewed source and regression-test deltas found in the
compiler worktrees during the profiler setup, plus the later qualified-module
error-call lowering fix from `codex/wasm-sdk` (`22a0744`). The dedicated compiler
branch also contains the previously committed profiler-facing CLI fix (`770ec6f`)
and the complete committed ancestry of the local compiler branches. `make
compiler-audit` is the repeatable check that every local branch tip remains an
ancestor of the dedicated compiler branch.

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
delta to import; and the structpy parser machine sources had no net delta after the
conflict was reconciled. Origin worktrees remain untouched, including their
uncommitted `.DS_Store` files.

## Verification contract

Before changing the profiler compiler pin, run:

```sh
make compiler-audit
make compiler-seed
make compiler-smoke
make profiler-native-smoke
```

The native profiler itself remains Elisa code. The C collector is only the explicit
low-level ABI/runtime component used by the generated target and is not an alternate
profiler CLI or report implementation.
