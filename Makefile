PROFILER_ROOT := $(abspath .)
COMPILER_WORKTREE ?= $(abspath ../elisa-compiler-worktrees/profiler)
STAGE0_CORE ?= $(CURDIR)/../../Go projects/structpy-tree
COMPILER_WRAPPER := $(PROFILER_ROOT)/scripts/elisa-compiler

.PHONY: compiler-status compiler-seed compiler-smoke profiler-smoke test

compiler-status:
	@test -x "$(COMPILER_WORKTREE)/scripts/elisac_stage1.sh" || { echo "compiler worktree missing: $(COMPILER_WORKTREE)" >&2; exit 2; }
	@echo "compiler worktree: $(COMPILER_WORKTREE)"
	@git -C "$(COMPILER_WORKTREE)" status --short --branch
	@if test -x "$(COMPILER_WORKTREE)/bin/elisac-stage1"; then echo "stage1 product: ready"; else echo "stage1 product: missing (run make compiler-seed)"; fi

compiler-seed:
	ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" ELISA_STAGE0_CORE="$(STAGE0_CORE)" "$(COMPILER_WRAPPER)" --seed

compiler-smoke:
	@"$(PROFILER_ROOT)/test/compiler_smoke.sh"

profiler-smoke:
	@"$(PROFILER_ROOT)/test/profiler_smoke.sh"

test: compiler-smoke profiler-smoke
