#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

static int fail_allocations;

static void *regression_calloc(size_t count, size_t size) {
    if (fail_allocations) {
        return NULL;
    }
    if (size != 0 && count > SIZE_MAX / size) {
        return NULL;
    }
    size_t bytes = count * size;
    void *allocation = malloc(bytes == 0 ? 1 : bytes);
    if (allocation != NULL) {
        memset(allocation, 0, bytes == 0 ? 1 : bytes);
    }
    return allocation;
}

#define calloc regression_calloc
#define main collector_embedded_main
#include "../scripts/profiler_runtime.c"
#undef main
#undef calloc

int64_t elisa_profile_target_main(int64_t argc, void *argv) {
    (void)argc;
    (void)argv;
    return 0;
}

int main(void) {
    size_t next_capacity = 0;
    uint64_t allocation_bytes = 0;
    assert(!profile_next_capacity(SIZE_MAX, PROFILE_INITIAL_LOCATION_CAPACITY,
                                   &next_capacity));
    assert(!profile_allocation_bytes(SIZE_MAX, sizeof(profile_entry),
                                     &allocation_bytes));
    assert(profile_table_requires_growth(SIZE_MAX, SIZE_MAX));
    profile_capture_byte_limit = 1;
    profile_capture_bytes_used = 2;
    assert(!profile_reserve_bytes_locked(1));
    profile_capture_byte_limit = 0;
    profile_capture_bytes_used = 0;
    profile_capture_bytes_dropped = 0;
    profile_budget_exceeded = 0;

    const uint32_t repeat_line = 1;
    const size_t entries_before_growth =
        (PROFILE_INITIAL_LOCATION_CAPACITY * PROFILE_TABLE_LOAD_DENOMINATOR - 1) /
        PROFILE_TABLE_LOAD_NUMERATOR;
    for (uint32_t line = repeat_line; line <= entries_before_growth; ++line) {
        elisa_trace_record("repeat", line);
    }
    assert(profile_capacity == PROFILE_INITIAL_LOCATION_CAPACITY);
    fail_allocations = 1;
    elisa_trace_record("repeat", repeat_line);
    assert(profile_dropped_count == 0);
    assert(profile_find_locked("repeat", NULL, repeat_line,
                               PROFILE_KIND_STATEMENT, 0)->count == 2);
    profile_record_call_edge("caller", "callee");
    assert(profile_call_edge_dropped_count == 1);
    assert(profile_record_call_path(NULL, "callee") == NULL);
    assert(profile_call_path_dropped_count == 1);
    fail_allocations = 0;
    assert(profile_grow_call_paths_locked());
    fail_allocations = 1;
    assert(profile_record_call_path(NULL, "callee") == NULL);
    assert(profile_call_path_dropped_count == 2);
    fail_allocations = 0;
    elisa_trace_record(NULL, repeat_line);
    elisa_trace_record(NULL, repeat_line);
    assert(profile_find_locked("<unknown>", NULL, repeat_line,
                               PROFILE_KIND_STATEMENT, 0)->count == 2);
    setenv("ELISA_PROFILE_MAX_LOCATIONS", "-1", 1);
    assert(profile_read_limit_environment("ELISA_PROFILE_MAX_LOCATIONS",
                                         PROFILE_DEFAULT_LOCATION_LIMIT) ==
           PROFILE_DEFAULT_LOCATION_LIMIT);
    puts("collector regression smoke OK");
    return 0;
}
