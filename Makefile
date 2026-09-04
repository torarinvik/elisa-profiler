PROFILER_ROOT := $(abspath .)
COMPILER_WORKTREE ?= $(abspath ../elisa-compiler-worktrees/profiler)
STAGE0_CORE ?= $(CURDIR)/../../Go projects/structpy-tree
SEED_OPT_LEVEL ?= -O0
SEED_MAX_RSS_KB ?= 8388608
COMPILER_WRAPPER := $(PROFILER_ROOT)/scripts/elisa-compiler

.PHONY: compiler-status compiler-audit compiler-seed compiler-smoke collector-content-smoke runtime-abi-smoke timing-failure-smoke timing-mismatch-smoke profile-resource-smoke profile-fd-smoke profiler-smoke profile-aggregation-smoke profile-compare-smoke profile-protocol-smoke process-group-smoke test

compiler-status:
	@test -x "$(COMPILER_WORKTREE)/scripts/elisac_stage1.sh" || { echo "compiler worktree missing: $(COMPILER_WORKTREE)" >&2; exit 2; }
	@echo "compiler worktree: $(COMPILER_WORKTREE)"
	@git -C "$(COMPILER_WORKTREE)" status --short --branch
	@if test -x "$(COMPILER_WORKTREE)/bin/elisac-stage1"; then echo "stage1 product: ready"; else echo "stage1 product: missing (run make compiler-seed)"; fi

compiler-audit:
	@ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" "$(PROFILER_ROOT)/scripts/audit-compiler-branches.sh"

compiler-seed:
	ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" ELISA_STAGE0_CORE="$(STAGE0_CORE)" \
	ELISA_STAGE1_SEED_OPT_LEVEL="$(SEED_OPT_LEVEL)" ELISA_STAGE1_SEED_MAX_RSS_KB="$(SEED_MAX_RSS_KB)" \
	"$(COMPILER_WRAPPER)" --seed

compiler-smoke:
	@"$(PROFILER_ROOT)/test/compiler_smoke.sh"

collector-content-smoke:
	@"$(PROFILER_ROOT)/test/collector_content_smoke.sh"

runtime-abi-smoke:
	@"$(PROFILER_ROOT)/test/runtime_abi_smoke.sh"

timing-failure-smoke:
	@"$(PROFILER_ROOT)/test/timing_failure_smoke.sh"

timing-mismatch-smoke:
	@"$(PROFILER_ROOT)/test/timing_mismatch_smoke.sh"

profile-resource-smoke:
	@python3 "$(PROFILER_ROOT)/test/profile_resource_smoke.py"

profile-fd-smoke:
	@python3 "$(PROFILER_ROOT)/test/profile_fd_smoke.py"

profiler-smoke:
	@"$(PROFILER_ROOT)/test/profiler_smoke.sh"

profile-aggregation-smoke:
	@python3 "$(PROFILER_ROOT)/test/profile_aggregation_smoke.py"

profile-compare-smoke:
	@python3 "$(PROFILER_ROOT)/test/profile_compare_smoke.py"

profile-protocol-smoke:
	@python3 "$(PROFILER_ROOT)/test/profile_protocol_smoke.py"

process-group-smoke:
	@python3 "$(PROFILER_ROOT)/test/process_group_smoke.py"

test: compiler-audit compiler-smoke collector-content-smoke runtime-abi-smoke timing-failure-smoke timing-mismatch-smoke profile-resource-smoke profile-fd-smoke profiler-smoke profile-aggregation-smoke profile-compare-smoke profile-protocol-smoke process-group-smoke
