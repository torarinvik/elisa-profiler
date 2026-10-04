#!/usr/bin/env bash
# Host build boundary only: CLI orchestration and profiling policy remain Elisa.
set -euo pipefail

if [[ $# -ne 6 ]]; then
    printf 'usage: build-native.sh COMPILER STAGE1 COMPILER_ROOT RUNTIME OPT_LEVEL OUTPUT\n' >&2
    exit 2
fi
compiler="$1"
stage1="$2"
compiler_root="$3"
runtime="$4"
opt_level="$5"
output="$6"
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
host_os="$(uname -s)"
case "$host_os" in
    Darwin|Linux) ;;
    *) printf 'native profiler host backend unsupported: %s\n' "$host_os" >&2; exit 2 ;;
esac
[[ -x "$compiler" && -x "$stage1" && -f "$runtime" ]] || {
    printf 'native profiler compiler or runtime is missing\n' >&2
    exit 2
}
mkdir -p -- "$(dirname -- "$output")"
work="$(mktemp -d "$(dirname -- "$output")/.native-build.XXXXXX")"
trap 'rm -r -- "$work"' EXIT
export ELISA_STAGE1_BIN="$stage1" ELISA_COMPILER_ROOT="$compiler_root" ELISA_RUNTIME_OBJ="$runtime"
if [[ "$host_os" == Darwin ]]; then
    # Retain the compiler's existing Mach-O executable path and freshness guard.
    "$compiler" -emit exe "$opt_level" -o "$work/elisa-profiler" "$root/src/profiler/main.elisa"
else
    export ELISA_HOST_LINUX=1
    case "$(uname -m)" in
        x86_64) export ELISA_HOST_X86_64=1 ;;
        *) printf 'Linux native profiler currently validated on x86_64 only\n' >&2; exit 2 ;;
    esac
    cc="${ELISA_CLANG:-clang}"
    # The pinned driver's executable linker is Mach-O-specific. Use its native
    # object emitter, then the host ELF linker; never fall back to stage0.
    "$compiler" -emit obj "$opt_level" -o "$work/profiler.o" "$root/src/profiler/main.elisa"
    "$cc" -O2 -c -o "$work/profile-hooks.o" "$compiler_root/test/parity/profile_hooks.c"
    "$cc" -no-pie -Wl,--gc-sections -o "$work/elisa-profiler" \
        "$work/profiler.o" "$work/profile-hooks.o" "$runtime" -lm
fi
# Publish only after both compilation and linking succeeded; preserve a working
# prior executable on failure. The temporary directory is on the same volume.
mv -- "$work/elisa-profiler" "$output"
