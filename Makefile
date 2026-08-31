PROFILER_ROOT := $(abspath .)
COMPILER_WORKTREE ?= $(abspath ../elisa-compiler-worktrees/profiler)
STAGE0_CORE ?= $(CURDIR)/../../Go projects/structpy-tree
SEED_OPT_LEVEL ?= -O0
SEED_MAX_RSS_KB ?= 8388608
COMPILER_WRAPPER := $(PROFILER_ROOT)/scripts/elisa-compiler

.PHONY: compiler-status compiler-seed compiler-smoke profiler-smoke process-group-smoke test

compiler-status:
	@test -x "$(COMPILER_WORKTREE)/scripts/elisac_stage1.sh" || { echo "compiler worktree missing: $(COMPILER_WORKTREE)" >&2; exit 2; }
	@echo "compiler worktree: $(COMPILER_WORKTREE)"
	@git -C "$(COMPILER_WORKTREE)" status --short --branch
	@if test -x "$(COMPILER_WORKTREE)/bin/elisac-stage1"; then echo "stage1 product: ready"; else echo "stage1 product: missing (run make compiler-seed)"; fi

compiler-seed:
	ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" ELISA_STAGE0_CORE="$(STAGE0_CORE)" \
	ELISA_STAGE1_SEED_OPT_LEVEL="$(SEED_OPT_LEVEL)" ELISA_STAGE1_SEED_MAX_RSS_KB="$(SEED_MAX_RSS_KB)" \
	"$(COMPILER_WRAPPER)" --seed

compiler-smoke:
	@"$(PROFILER_ROOT)/test/compiler_smoke.sh"

profiler-smoke:
	@"$(PROFILER_ROOT)/test/profiler_smoke.sh"

process-group-smoke:
	@python3 "$(PROFILER_ROOT)/test/process_group_smoke.py"

test: compiler-smoke profiler-smoke process-group-smoke
