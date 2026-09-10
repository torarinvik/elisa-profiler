PROFILER_ROOT := $(abspath .)
COMPILER_WORKTREE ?= $(abspath ../elisa-compiler-worktrees/profiler)
STAGE0_CORE ?= $(CURDIR)/../../Go projects/structpy-tree
SEED_OPT_LEVEL ?= -O3
NATIVE_OPT_LEVEL ?= -O1
SEED_MAX_RSS_KB ?= 8388608
COMPILER_WRAPPER := $(PROFILER_ROOT)/scripts/elisa-compiler
NATIVE_PROFILER_BIN ?= $(PROFILER_ROOT)/bin/elisa-profiler
NATIVE_PROFILER_SOURCE := $(PROFILER_ROOT)/src/profiler/main.elisa
NATIVE_COMPILER_SCRIPT := $(COMPILER_WORKTREE)/scripts/elisac_stage1.sh
NATIVE_STAGE1_BIN := $(COMPILER_WORKTREE)/bin/elisac-stage1
NATIVE_RUNTIME_OBJECT := $(COMPILER_WORKTREE)/build/runtime/elisacore_runtime.o
COMPILER_BUILD_MANIFEST := $(COMPILER_WORKTREE)/build/compiler-build-manifest.json
# Prefer the checked-out stage0 source tree. A PATH-installed `~/.elisac`
# elisac-stage0 is a snapshot and can silently lag the compiler sources being
# seeded; callers may still override STAGE0_BIN or ELISACORE_BIN explicitly.
STAGE0_BIN ?= $(shell if test -x "$(STAGE0_CORE)/compiler/bin/elisac"; then printf '%s\n' "$(STAGE0_CORE)/compiler/bin/elisac"; else command -v elisac-stage0 2>/dev/null || true; fi)
NATIVE_SMOKE_TIMEOUT_SECONDS ?= 30

.PHONY: compiler-status compiler-audit compiler-ledger-smoke compiler-manifest-smoke compiler-seed compiler-smoke compiler-identity-smoke compiler-self-host-smoke profiler-native profiler-native-smoke sampling-smoke build-cache-smoke prebuilt-smoke native-timeout-smoke profile-budget-smoke profile-workload-compare-smoke benchmark-smoke baseline-smoke fixture-diversity-smoke metamorphic-smoke protocol-property-smoke legacy-fixture-smoke collector-strict-smoke collector-content-smoke collector-trace-buffer-smoke collector-identity-smoke collector-sanitizer-smoke collector-callback-benchmark runtime-abi-smoke timing-failure-smoke timing-mismatch-smoke overflow-mismatch-smoke progress-smoke path-remap-smoke source-stability-smoke bootstrap-path-smoke process-group-smoke test

compiler-status:
	@test -x "$(COMPILER_WORKTREE)/scripts/elisac_stage1.sh" || { echo "compiler worktree missing: $(COMPILER_WORKTREE)" >&2; exit 2; }
	@echo "compiler worktree: $(COMPILER_WORKTREE)"
	@git -C "$(COMPILER_WORKTREE)" status --short --branch
	@if test -x "$(COMPILER_WORKTREE)/bin/elisac-stage1"; then echo "stage1 product: ready"; else echo "stage1 product: missing (run make compiler-seed)"; fi

compiler-audit:
	@ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" "$(PROFILER_ROOT)/scripts/audit-compiler-branches.sh"

compiler-ledger-smoke: compiler-audit
	@python3 "$(PROFILER_ROOT)/test/compiler_ledger_smoke.py" "$(PROFILER_ROOT)/build/compiler-integration-ledger.json"

compiler-manifest-smoke: compiler-ledger-smoke
	@python3 "$(PROFILER_ROOT)/test/compiler_manifest_smoke.py" "$(COMPILER_BUILD_MANIFEST)" "$(PROFILER_ROOT)/scripts/compiler_build_manifest.py"

compiler-self-host-smoke: compiler-manifest-smoke
	@test -x "$(COMPILER_WORKTREE)/test/parity/self_host_gen3_smoke.sh" || { echo "compiler self-host smoke missing: $(COMPILER_WORKTREE)/test/parity/self_host_gen3_smoke.sh" >&2; exit 2; }
	@ELISA_STAGE1_BIN="$(NATIVE_STAGE1_BIN)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(COMPILER_WORKTREE)/test/parity/self_host_gen3_smoke.sh"

.PHONY: compiler-runtime-freshness-smoke
compiler-runtime-freshness-smoke:
	@bash "$(COMPILER_WORKTREE)/test/parity/runtime_object_freshness_smoke.sh"

test: compiler-runtime-freshness-smoke

.PHONY: allocation-lifetimes-smoke
allocation-lifetimes-smoke: compiler-manifest-smoke
	@mkdir -p "$(PROFILER_ROOT)/build"
	@ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O0 -o "$(PROFILER_ROOT)/build/allocation-lifetimes-smoke" \
		"$(PROFILER_ROOT)/test/allocation_lifetimes_smoke.elisa"
	@"$(PROFILER_ROOT)/build/allocation-lifetimes-smoke"

test: allocation-lifetimes-smoke

.PHONY: region-cache-oversize-smoke
region-cache-oversize-smoke:
	@mkdir -p "$(PROFILER_ROOT)/build"
	@ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O0 -o "$(PROFILER_ROOT)/build/region-cache-oversize-smoke" \
		"$(PROFILER_ROOT)/examples/region_cache_oversize_workload.elisa"
	@"$(PROFILER_ROOT)/build/region-cache-oversize-smoke"

test: region-cache-oversize-smoke

.PHONY: linkmap-smoke
.PHONY: external-link-smoke
.PHONY: benchmark-external-link-smoke
benchmark-external-link-smoke: profiler-native
	@"$(NATIVE_PROFILER_BIN)" benchmark test/benchmark_external_link.json --format json --output build/benchmark-external-link.json
	@set -eu; for fixture in empty nul; do \
		result=0; "$(NATIVE_PROFILER_BIN)" benchmark "test/benchmark_$${fixture}_link_rejected.json" --output "build/benchmark-$${fixture}-link-rejected.json" || result=$$?; \
		test "$$result" -eq 2; \
	done

LLVM_CONFIG ?= /opt/homebrew/opt/llvm/bin/llvm-config
external-link-smoke: profiler-native
	@set -eu; \
		llvm_libdir="$$("$(LLVM_CONFIG)" --libdir)"; \
		"$(NATIVE_PROFILER_BIN)" profile test/external_link_workload.elisa --mode functions \
			--link-arg "-L$$llvm_libdir" --link-arg -lLLVM --link-arg "-Wl,-rpath,$$llvm_libdir" \
			--format json --output build/external-link-smoke.json; \
		if "$(NATIVE_PROFILER_BIN)" profile test/external_link_workload.elisa --link-arg -lLLVM --cache-dir build/link-cache-rejected; then exit 1; fi; \
		if "$(NATIVE_PROFILER_BIN)" profile test/external_link_workload.elisa --link-arg; then exit 1; fi

linkmap-smoke:
	@mkdir -p "$(PROFILER_ROOT)/build"
	@set -e; for opt in 0 3; do \
		ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O$$opt -o "$(PROFILER_ROOT)/build/linkmap-smoke-O$$opt" \
		"$(PROFILER_ROOT)/test/linkmap_smoke.elisa"; \
		"$(PROFILER_ROOT)/build/linkmap-smoke-O$$opt" </dev/null; \
	done

test: linkmap-smoke

.PHONY: hash-smoke
.PHONY: confidence-smoke
confidence-smoke:
	@mkdir -p "$(PROFILER_ROOT)/build"
	@set -eu; for opt in 0 3; do \
		ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O$$opt -o "$(PROFILER_ROOT)/build/confidence-smoke-O$$opt" "$(PROFILER_ROOT)/test/confidence_smoke.elisa"; \
		"$(PROFILER_ROOT)/build/confidence-smoke-O$$opt"; \
	done

test: confidence-smoke

.PHONY: confidence-report-smoke
confidence-report-smoke: profiler-native
	@ELISA_STAGE1_BIN="$(NATIVE_STAGE1_BIN)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_PROFILER_BIN)" profile examples/hot_loop.elisa --mode functions --repeat 3 --format json --output build/confidence-report-smoke.json
	@jq -e '.run.execution_ci95_available == true and .run.execution_ci95_method == "student_t_conservative_v1"' build/confidence-report-smoke.json >/dev/null

hash-smoke: compiler-manifest-smoke
	@mkdir -p "$(PROFILER_ROOT)/build"
	@ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O0 -o "$(PROFILER_ROOT)/build/hash-smoke" \
		"$(PROFILER_ROOT)/test/hash_smoke.elisa"
	@"$(PROFILER_ROOT)/build/hash-smoke"

.PHONY: macho-smoke
macho-smoke: compiler-manifest-smoke
	@mkdir -p "$(PROFILER_ROOT)/build"
	@ELISA_STAGE1_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_STAGE1_BIN)" -emit exe -O1 -o "$(PROFILER_ROOT)/build/macho-smoke" \
		"$(PROFILER_ROOT)/test/macho_smoke.elisa"
	@"$(PROFILER_ROOT)/build/macho-smoke" </dev/null
	@if test "$$(uname -s)" = Darwin; then \
		"$(PROFILER_ROOT)/build/macho-smoke" <"$(PROFILER_ROOT)/build/macho-smoke" >"$(PROFILER_ROOT)/build/macho-starts.actual"; \
	fi

# Optional independent oracle: pass LLVM_OBJDUMP when LLVM is not on PATH.
LLVM_OBJDUMP ?= llvm-objdump
.PHONY: macho-oracle-smoke
macho-oracle-smoke: macho-smoke
	@test "$$(uname -s)" = Darwin
	@"$(LLVM_OBJDUMP)" --macho --function-starts=addrs "$(PROFILER_ROOT)/build/macho-smoke" >"$(PROFILER_ROOT)/build/macho-starts.llvm-header"
	@tail -n +2 "$(PROFILER_ROOT)/build/macho-starts.llvm-header" >"$(PROFILER_ROOT)/build/macho-starts.expected"
	@diff -u "$(PROFILER_ROOT)/build/macho-starts.expected" "$(PROFILER_ROOT)/build/macho-starts.actual"

test: hash-smoke macho-smoke

compiler-seed:
	ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" ELISA_STAGE0_CORE="$(STAGE0_CORE)" \
	ELISACORE_BIN="$${ELISACORE_BIN:-$(STAGE0_BIN)}" \
	ELISA_STAGE1_SEED_OPT_LEVEL="$(SEED_OPT_LEVEL)" ELISA_STAGE1_SEED_MAX_RSS_KB="$(SEED_MAX_RSS_KB)" \
	"$(COMPILER_WRAPPER)" --seed
	@stage0="$${ELISACORE_BIN:-$(STAGE0_BIN)}"; \
		if test -n "$$stage0"; then \
			python3 "$(PROFILER_ROOT)/scripts/compiler_build_manifest.py" --compiler-root "$(COMPILER_WORKTREE)" \
			--stage1 "$(NATIVE_STAGE1_BIN)" --runtime "$(NATIVE_RUNTIME_OBJECT)" --output "$(COMPILER_BUILD_MANIFEST)" \
			--seed-opt-level="$(SEED_OPT_LEVEL)" --seed-max-rss-kb "$(SEED_MAX_RSS_KB)" --stage0 "$$stage0"; \
		else \
			python3 "$(PROFILER_ROOT)/scripts/compiler_build_manifest.py" --compiler-root "$(COMPILER_WORKTREE)" \
			--stage1 "$(NATIVE_STAGE1_BIN)" --runtime "$(NATIVE_RUNTIME_OBJECT)" --output "$(COMPILER_BUILD_MANIFEST)" \
			--seed-opt-level="$(SEED_OPT_LEVEL)" --seed-max-rss-kb "$(SEED_MAX_RSS_KB)"; \
		fi

# Instrument targets, not the profiler's own hashing/decoding loops. Self tracing
# invokes runtime trace hooks during preparation and severely distorts CLI cost.
profiler-native:
	@test -x "$(NATIVE_COMPILER_SCRIPT)" || { echo "stage1 compiler wrapper missing: $(NATIVE_COMPILER_SCRIPT)" >&2; exit 2; }
	@test -x "$(NATIVE_STAGE1_BIN)" || { echo "stage1 compiler missing: $(NATIVE_STAGE1_BIN) (run make compiler-seed)" >&2; exit 2; }
	@test -f "$(NATIVE_RUNTIME_OBJECT)" || { echo "runtime object missing: $(NATIVE_RUNTIME_OBJECT) (run $(COMPILER_WORKTREE)/scripts/build_runtime_object.sh)" >&2; exit 2; }
	@mkdir -p "$(PROFILER_ROOT)/bin"
	@set -eu; native_build="$$(mktemp -d "$(PROFILER_ROOT)/bin/.native-build.XXXXXX")"; \
		trap 'rm -rf "$$native_build"' EXIT; \
		ELISA_STAGE1_BIN="$(NATIVE_STAGE1_BIN)" ELISA_COMPILER_ROOT="$(COMPILER_WORKTREE)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_COMPILER_SCRIPT)" -emit exe "$(NATIVE_OPT_LEVEL)" -o "$$native_build/elisa-profiler" "$(NATIVE_PROFILER_SOURCE)"; \
		mv "$$native_build/elisa-profiler" "$(NATIVE_PROFILER_BIN)"
# Building a profiler does not rebuild its compiler. Only compiler-seed may
# record seed provenance; ambient stage0 paths/flags are not build evidence.
	@echo "native profiler: $(NATIVE_PROFILER_BIN)"

.PHONY: profiler-provenance-smoke
.PHONY: profile-compiler-digest-smoke
profile-compiler-digest-smoke: profiler-native
	@ELISA_STAGE1_BIN="$(NATIVE_STAGE1_BIN)" ELISA_RUNTIME_OBJ="$(NATIVE_RUNTIME_OBJECT)" \
		"$(NATIVE_PROFILER_BIN)" profile examples/hot_loop.elisa --mode functions --format json --output build/compiler-digest-smoke.json
	@test "$$(jq -r '.compiler.stage1_sha256' build/compiler-digest-smoke.json)" = "$$(shasum -a 256 "$(NATIVE_STAGE1_BIN)" | awk '{print $$1}')"
	@test "$$(jq -r '.compiler.runtime_object_sha256' build/compiler-digest-smoke.json)" = "$$(shasum -a 256 "$(NATIVE_RUNTIME_OBJECT)" | awk '{print $$1}')"

profiler-provenance-smoke:
	@set -eu; manifest_copy="$$(mktemp)"; trap 'rm -f "$$manifest_copy"' EXIT; \
		cp "$(COMPILER_BUILD_MANIFEST)" "$$manifest_copy"; \
		$(MAKE) profiler-native; \
		cmp "$$manifest_copy" "$(COMPILER_BUILD_MANIFEST)"

profiler-native-smoke: profiler-native
	@set -eu; native_work="$$(mktemp -d)"; trap 'rm -rf "$$native_work"' EXIT; \
		native_run() { ELISA_NATIVE_COMMAND_TIMEOUT_SECONDS="$(NATIVE_SMOKE_TIMEOUT_SECONDS)" python3 "$(PROFILER_ROOT)/test/run_bounded_command.py" "$$@"; }; \
		native_run "$(NATIVE_PROFILER_BIN)" doctor --format json --output "$$native_work/doctor.json"; \
		grep -Fq '"ok":true' "$$native_work/doctor.json"; \
		grep -Fq '"compiler_manifest":true' "$$native_work/doctor.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/hot_loop.elisa" --event-trace --max-event-trace-events 10 --format json --output "$$native_work/report.json"; \
		test -s "$$native_work/report.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" record "$(PROFILER_ROOT)/examples/hot_loop.elisa" --format json --output "$$native_work/record.json" --artifact-output "$$native_work/profile.elisaprof"; \
		python3 "$(PROFILER_ROOT)/test/profile_artifact_smoke.py" "$$native_work/profile.elisaprof"; \
		if native_run "$(NATIVE_PROFILER_BIN)" record "$(PROFILER_ROOT)/examples/hot_loop.elisa" --format json --artifact-output "$$native_work/rejected.elisaprof" --max-artifact-bytes 1; then echo "artifact budget unexpectedly accepted oversized output" >&2; exit 1; fi; \
		test ! -e "$$native_work/rejected.elisaprof"; \
		test -s "$$native_work/profile.elisaprof.manifest.json"; \
		grep -Fq '"state":"complete"' "$$native_work/profile.elisaprof.manifest.json"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/capture-manifest.schema.json" "$$native_work/profile.elisaprof.manifest.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/profile.elisaprof" --format json --output "$$native_work/artifact-report.json"; \
		cmp -s "$$native_work/record.json" "$$native_work/artifact-report.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/profile.elisaprof" --format folded --output "$$native_work/artifact.folded"; \
		grep -Fq 'main' "$$native_work/artifact.folded"; \
		native_run "$(NATIVE_PROFILER_BIN)" compare "$$native_work/profile.elisaprof" "$$native_work/profile.elisaprof" --format json --output "$$native_work/artifact-comparison.json"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile-comparison.schema.json" "$$native_work/artifact-comparison.json"; \
		grep -Fq '"locations":[{' "$$native_work/report.json"; \
		grep -Fq '"call_edges":[{' "$$native_work/report.json"; \
		grep -Fq '"stacks":[{' "$$native_work/report.json"; \
		grep -Fq '"random_seed_source":"not_controlled"' "$$native_work/report.json"; \
		grep -Fq '"event_trace":[{' "$$native_work/report.json"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile.schema.json" "$$native_work/report.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/report.json" --format json --output "$$native_work/offline.json"; \
		cmp -s "$$native_work/report.json" "$$native_work/offline.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/report.json" --format text --output "$$native_work/offline.txt"; \
		grep -Fq 'Elisa profiler' "$$native_work/offline.txt"; \
		grep -Fq 'statement events:' "$$native_work/offline.txt"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/report.json" --format folded --output "$$native_work/offline.folded"; \
		grep -Fq 'main' "$$native_work/offline.folded"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/report.json" --format speedscope --output "$$native_work/offline.speedscope.json"; \
		python3 "$(PROFILER_ROOT)/test/speedscope_smoke.py" "$$native_work/offline.speedscope.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" report "$$native_work/report.json" --format html --output "$$native_work/offline.html"; \
		grep -Fq '<!doctype html>' "$$native_work/offline.html"; \
		grep -Fq 'Native Elisa offline renderer' "$$native_work/offline.html"; \
		grep -Fq 'Outcome' "$$native_work/offline.html"; \
		grep -Fq 'Source SHA-256' "$$native_work/offline.html"; \
		grep -Fq 'source_tree_sha256' "$$native_work/offline.html"; \
		grep -Fq 'Capture completeness' "$$native_work/offline.html"; \
		grep -Fq 'Flame graph' "$$native_work/offline.html"; \
		grep -Fq 'flame-filter' "$$native_work/offline.html"; \
		grep -Fq 'function-root-weights' "$$native_work/offline.html"; \
		grep -Fq 'Mean execution' "$$native_work/offline.html"; \
		grep -Fq 'Peak RSS' "$$native_work/offline.html"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/hot_loop.elisa" --recent-path --format json --output "$$native_work/recent.json"; \
		grep -Fq '"recent_events":[{' "$$native_work/recent.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/hot_loop.elisa" --format folded --output "$$native_work/hot-loop.folded"; \
		grep -Fq 'main' "$$native_work/hot-loop.folded"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/hot_loop.elisa" --format html --output "$$native_work/hot-loop.html"; \
		grep -Fq '<!doctype html>' "$$native_work/hot-loop.html"; \
		grep -Fq 'Hotspots' "$$native_work/hot-loop.html"; \
		grep -Fq 'Source SHA-256' "$$native_work/hot-loop.html"; \
		grep -Fq 'Source tree SHA-256' "$$native_work/hot-loop.html"; \
		grep -Fq 'Capture completeness' "$$native_work/hot-loop.html"; \
		grep -Fq 'Flame graph' "$$native_work/hot-loop.html"; \
		grep -Fq 'flame-filter' "$$native_work/hot-loop.html"; \
		grep -Fq 'function-filter' "$$native_work/hot-loop.html"; \
		! grep -Fq "row.addEventListener(" "$$native_work/hot-loop.html"; \
		grep -Fq 'observed folded root self time' "$$native_work/hot-loop.html"; \
		grep -Fq 'edge-filter' "$$native_work/hot-loop.html"; \
		grep -Fq 'location-filter' "$$native_work/hot-loop.html"; \
		grep -Fq 'View filters are stored locally on this device.' "$$native_work/hot-loop.html"; \
		grep -Fq 'elisa-profiler:view-state:v1' "$$native_work/hot-loop.html"; \
		grep -Fq 'Clear saved filters' "$$native_work/hot-loop.html"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/hot_loop.elisa" --format speedscope --output "$$native_work/hot-loop.speedscope.json"; \
		python3 "$(PROFILER_ROOT)/test/speedscope_smoke.py" "$$native_work/hot-loop.speedscope.json"; \
		! grep -Fq 'native-transition' "$$native_work/report.json"; \
		grep -Fq '"branch":"' "$$native_work/report.json"; \
		grep -Fq '"commit":"' "$$native_work/report.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/native_stderr_probe.elisa" --format json --output "$$native_work/stderr-probe.json" 2>"$$native_work/stderr-probe.log"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile.schema.json" "$$native_work/stderr-probe.json"; \
		grep -Fq '"program_stdout":"target stdout\n"' "$$native_work/stderr-probe.json"; \
		grep -Fq '"program_stdout_truncated":false' "$$native_work/stderr-probe.json"; \
		grep -Fq '"program_stderr":"ELISA_PROFILE\t1\tmeta\tspoofed\n"' "$$native_work/stderr-probe.json"; \
		grep -Fq '"program_stderr_truncated":false' "$$native_work/stderr-probe.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/native_stderr_probe.elisa" --format text --output "$$native_work/output-probe.txt"; \
		grep -Fq 'program stdout:' "$$native_work/output-probe.txt"; \
		grep -Fq 'program stderr:' "$$native_work/output-probe.txt"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/native_stderr_probe.elisa" --format html --output "$$native_work/output-probe.html"; \
		grep -Fq 'Target output' "$$native_work/output-probe.html"; \
		grep -Fq 'target stdout' "$$native_work/output-probe.html"; \
		! grep -Fq 'malformed native protocol' "$$native_work/stderr-probe.log"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/native_launch_probe.elisa" --cwd "$$native_work" --stdin "$(PROFILER_ROOT)/README.md" --env ELISA_PROFILER_LAUNCH=enabled --random-seed 42 --format json --output "$$native_work/launch-probe.json"; \
		grep -Fq '"random_seed":"42"' "$$native_work/launch-probe.json"; \
		test -s "$$native_work/native-launch-cwd-marker.txt"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile.schema.json" "$$native_work/launch-probe.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" profile "$(PROFILER_ROOT)/examples/native_argv_probe.elisa" --format json --output "$$native_work/argv-probe.json" -- --alpha "two words"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile.schema.json" "$$native_work/argv-probe.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" compare "$$native_work/report.json" "$$native_work/report.json" --format json --output "$$native_work/comparison.json"; \
		python3 "$(PROFILER_ROOT)/test/profile_schema_smoke.py" "$(PROFILER_ROOT)/docs/profile-comparison.schema.json" "$$native_work/comparison.json"; \
		python3 "$(PROFILER_ROOT)/test/native_compare_smoke.py" "$$native_work/comparison.json"; \
		native_run "$(NATIVE_PROFILER_BIN)" compare "$$native_work/report.json" "$$native_work/report.json" --format text --output "$$native_work/comparison.txt"; \
		grep -Fq 'Elisa profile comparison' "$$native_work/comparison.txt"; \
		grep -Fq 'wall mean:' "$$native_work/comparison.txt"

profile-budget-smoke: profiler-native
	@"$(PROFILER_ROOT)/test/profile_budget_smoke.sh"

profile-workload-compare-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/profile_workload_compare_smoke.py" "$(NATIVE_PROFILER_BIN)"

benchmark-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/benchmark_smoke.py"

baseline-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/baseline_smoke.py"

fixture-diversity-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/fixture_diversity_smoke.py" "$(NATIVE_PROFILER_BIN)"

metamorphic-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/metamorphic_smoke.py" "$(NATIVE_PROFILER_BIN)"

protocol-property-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/protocol_property_smoke.py" "$(NATIVE_PROFILER_BIN)"

legacy-fixture-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/legacy_fixture_smoke.py" "$(NATIVE_PROFILER_BIN)"

sampling-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/sampling_smoke.py" "$(NATIVE_PROFILER_BIN)"

build-cache-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/build_cache_smoke.py" "$(NATIVE_PROFILER_BIN)"

prebuilt-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/prebuilt_smoke.py" "$(NATIVE_PROFILER_BIN)"

native-timeout-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/native_timeout_smoke.py" "$(NATIVE_PROFILER_BIN)"

.PHONY: native-regression-smoke recovery-smoke
native-regression-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/native_regression_smoke.py"

recovery-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/recovery_smoke.py" "$(NATIVE_PROFILER_BIN)"

test: native-regression-smoke metamorphic-smoke legacy-fixture-smoke

.PHONY: collector-regression-smoke
collector-regression-smoke:
	@set -eu; regression_work="$$(mktemp -d "$${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-regression.XXXXXX")"; trap 'rm -rf "$$regression_work"' EXIT; \
		"$${ELISA_CLANG:-clang}" -std=c11 -O2 -fno-builtin -pthread \
		-o "$$regression_work/collector" "$(PROFILER_ROOT)/test/collector_regression_smoke.c"; \
		"$$regression_work/collector"

test: collector-regression-smoke

compiler-smoke:
	@"$(PROFILER_ROOT)/test/compiler_smoke.sh"

compiler-identity-smoke: compiler-manifest-smoke
	@"$(PROFILER_ROOT)/test/compiler_identity_smoke.sh"

collector-content-smoke:
	@"$(PROFILER_ROOT)/test/collector_content_smoke.sh"

collector-trace-buffer-smoke:
	@"$(PROFILER_ROOT)/test/collector_trace_buffer_smoke.sh"

collector-identity-smoke:
	@"$(PROFILER_ROOT)/test/collector_identity_smoke.sh"

collector-sanitizer-smoke:
	@"$(PROFILER_ROOT)/test/collector_sanitizer_smoke.sh"

collector-callback-benchmark:
	@"$(PROFILER_ROOT)/test/collector_callback_benchmark.sh"

collector-strict-smoke:
	@set -eu; \
		"$${ELISA_CLANG:-clang}" -std=c11 -Wall -Wextra -Wpedantic -Werror -fno-builtin -pthread \
			-fsyntax-only "$(PROFILER_ROOT)/scripts/profiler_runtime.c"; \
		echo "collector strict compile OK"

runtime-abi-smoke:
	@"$(PROFILER_ROOT)/test/runtime_abi_smoke.sh"

timing-failure-smoke:
	@"$(PROFILER_ROOT)/test/timing_failure_smoke.sh"

timing-mismatch-smoke:
	@"$(PROFILER_ROOT)/test/timing_mismatch_smoke.sh"

overflow-mismatch-smoke:
	@"$(PROFILER_ROOT)/test/overflow_mismatch_smoke.sh"

progress-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/progress_smoke.py" "$(NATIVE_PROFILER_BIN)"

path-remap-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/path_remap_smoke.py" "$(NATIVE_PROFILER_BIN)"

source-stability-smoke: profiler-native
	@python3 "$(PROFILER_ROOT)/test/source_stability_smoke.py" "$(NATIVE_PROFILER_BIN)"

bootstrap-path-smoke: profiler-native
	@"$(PROFILER_ROOT)/test/bootstrap_path_smoke.sh"

process-group-smoke:
	@python3 "$(PROFILER_ROOT)/test/process_group_smoke.py"

test: compiler-self-host-smoke compiler-smoke compiler-identity-smoke profiler-native-smoke sampling-smoke build-cache-smoke prebuilt-smoke native-timeout-smoke recovery-smoke protocol-property-smoke profile-budget-smoke profile-workload-compare-smoke benchmark-smoke baseline-smoke fixture-diversity-smoke metamorphic-smoke collector-content-smoke collector-trace-buffer-smoke collector-identity-smoke collector-sanitizer-smoke collector-strict-smoke runtime-abi-smoke timing-failure-smoke timing-mismatch-smoke overflow-mismatch-smoke progress-smoke path-remap-smoke source-stability-smoke bootstrap-path-smoke process-group-smoke
