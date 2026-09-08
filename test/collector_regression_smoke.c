#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>

static int fail_allocations;

static void regression_signal_handler(int signal_number) {
    (void)signal_number;
}

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
    assert(profile_saturating_increment_u64(UINT64_MAX) == UINT64_MAX);
    assert(profile_saturating_increment_size(SIZE_MAX) == SIZE_MAX);
    const __uint128_t unsigned_sum_overflow = (__uint128_t)UINT64_MAX + 1;
    assert(profile_saturating_add_unsigned_sum(UINT64_MAX, 1) == unsigned_sum_overflow);
    assert(profile_saturating_add_unsigned_sum(unsigned_sum_overflow, 1) == unsigned_sum_overflow);
    assert(profile_saturating_add_unsigned_sum(4, 5) == 9);
    const __int128_t signed_sum_low = (__int128_t)INT64_MIN - 1;
    const __int128_t signed_sum_high = (__int128_t)INT64_MAX + 1;
    assert(profile_saturating_add_signed_sum(INT64_MIN, -1) == signed_sum_low);
    assert(profile_saturating_add_signed_sum(signed_sum_low, 1) == signed_sum_low);
    assert(profile_saturating_add_signed_sum(INT64_MAX, 1) == signed_sum_high);
    assert(profile_saturating_add_signed_sum(signed_sum_high, -1) == signed_sum_high);
    assert(profile_saturating_add_signed_sum(-4, 5) == 1);
    const uint64_t stable_function_id = UINT64_C(42);
    assert(profile_named_identity_matches("left", "right", stable_function_id,
                                          stable_function_id));
    assert(!profile_named_identity_matches("left", "right", PROFILE_ID_UNSET,
                                           PROFILE_ID_UNSET));
    assert(profile_hash_identity(PROFILE_FNV_OFFSET_BASIS, "left", stable_function_id) ==
           profile_hash_identity(PROFILE_FNV_OFFSET_BASIS, "right", stable_function_id));
    assert(!profile_next_capacity(SIZE_MAX, PROFILE_INITIAL_LOCATION_CAPACITY,
                                   &next_capacity));
    assert(!profile_allocation_bytes(SIZE_MAX, sizeof(profile_entry),
                                     &allocation_bytes));
    assert(profile_table_requires_growth(SIZE_MAX, SIZE_MAX));
    struct sigaction previous_sigint;
    struct sigaction previous_sigterm;
    struct sigaction custom_action = {0};
    assert(sigemptyset(&custom_action.sa_mask) == 0);
    custom_action.sa_handler = regression_signal_handler;
    assert(sigaction(SIGINT, &custom_action, &previous_sigint) == 0);
    struct sigaction ignored_action = {0};
    assert(sigemptyset(&ignored_action.sa_mask) == 0);
    ignored_action.sa_handler = SIG_IGN;
    assert(sigaction(SIGTERM, &ignored_action, &previous_sigterm) == 0);
    profile_install_crash_handlers();
    const int sigint_index = profile_crash_signal_index(SIGINT);
    const int sigterm_index = profile_crash_signal_index(SIGTERM);
    assert(sigint_index >= 0 && sigterm_index >= 0);
    assert(profile_previous_crash_action_valid[sigint_index]);
    assert(profile_previous_crash_actions[sigint_index].sa_handler ==
           regression_signal_handler);
    assert(profile_previous_crash_action_valid[sigterm_index]);
    assert(profile_previous_crash_actions[sigterm_index].sa_handler == SIG_IGN);
    assert(sigaction(SIGINT, &previous_sigint, NULL) == 0);
    assert(sigaction(SIGTERM, &previous_sigterm, NULL) == 0);
    profile_register_fork_policy();
    pid_t fork_child = fork();
    assert(fork_child >= 0);
    if (fork_child == 0) {
        _exit(profile_fork_child_disabled ? EXIT_SUCCESS : EXIT_FAILURE);
    }
    int fork_status = 0;
    assert(waitpid(fork_child, &fork_status, 0) == fork_child);
    assert(WIFEXITED(fork_status));
    assert(WEXITSTATUS(fork_status) == EXIT_SUCCESS);
    assert(profile_fork_child_disabled == 0);
    profile_capture_byte_limit = 1;
    profile_capture_bytes_used = 2;
    assert(!profile_reserve_bytes_locked(1));
    profile_capture_byte_limit = 0;
    profile_capture_bytes_used = 0;
    profile_capture_bytes_dropped = 0;
    profile_budget_exceeded = 0;
    profile_frame_length = PROFILE_FRAME_BUFFER_BYTES + 1;
    profile_frame_overflowed = 0;
    profile_record_append_char('x');
    assert(profile_frame_overflowed);
    profile_record_reset();

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
                               PROFILE_KIND_STATEMENT, 0, PROFILE_ID_UNSET)->count == 2);
    profile_record_call_edge("caller", "callee", PROFILE_ID_UNSET, PROFILE_ID_UNSET);
    assert(profile_call_edge_dropped_count == 1);
    assert(profile_record_call_path(NULL, "callee", PROFILE_ID_UNSET) == NULL);
    assert(profile_call_path_dropped_count == 1);
    fail_allocations = 0;
    assert(profile_grow_call_paths_locked());
    fail_allocations = 1;
    assert(profile_record_call_path(NULL, "callee", PROFILE_ID_UNSET) == NULL);
    assert(profile_call_path_dropped_count == 2);
    fail_allocations = 0;
    const uint64_t allocation_events_before = profile_allocation_event_count;
    const size_t allocation_records_before =
        profile_current_thread == NULL ? 0 : profile_current_thread->allocation_size;
    elisa_profile_allocation_event(PROFILE_ALLOCATION_ALLOC,
                                    (uintptr_t)0x1000, 24,
                                    0, 0, (uintptr_t)0x2000, 3);
    assert(profile_allocation_event_count == allocation_events_before + 1);
    assert(profile_current_thread != NULL);
    assert(profile_current_thread->allocation_size == allocation_records_before + 1);
    assert(profile_current_thread->allocation_events[allocation_records_before].kind ==
           PROFILE_ALLOCATION_ALLOC);
    assert(profile_current_thread->allocation_events[allocation_records_before].size == 24);
    profile_mode = PROFILE_MODE_FUNCTIONS;
    elisa_profile_allocation_event(PROFILE_ALLOCATION_ALLOC,
                                    (uintptr_t)0x1001, 8,
                                    0, 0, (uintptr_t)0x2000, 3);
    assert(profile_allocation_event_count == allocation_events_before + 1);
    profile_mode = PROFILE_MODE_FULL;
    elisa_trace_record(NULL, repeat_line);
    elisa_trace_record(NULL, repeat_line);
    assert(profile_find_locked("<unknown>", NULL, repeat_line,
                               PROFILE_KIND_STATEMENT, 0, PROFILE_ID_UNSET)->count == 2);
    setenv("ELISA_PROFILE_MAX_LOCATIONS", "-1", 1);
    assert(profile_read_limit_environment("ELISA_PROFILE_MAX_LOCATIONS",
                                         PROFILE_DEFAULT_LOCATION_LIMIT) ==
           PROFILE_DEFAULT_LOCATION_LIMIT);
    setenv("ELISA_PROFILE_FD", "42", 1);
    setenv("ELISA_PROFILE_MODE", "functions", 1);
    setenv(PROFILE_CHILD_ENVIRONMENT, "1", 1);
    profile_clear_internal_environment();
    assert(getenv("ELISA_PROFILE_FD") != NULL);
    unsetenv(PROFILE_CHILD_ENVIRONMENT);
    profile_clear_internal_environment();
    assert(getenv("ELISA_PROFILE_FD") == NULL);
    assert(getenv("ELISA_PROFILE_MODE") == NULL);
    setenv("ELISA_PROFILE_FD", "not-a-descriptor", 1);
    setenv("ELISA_PROFILE_MODE", "functions", 1);
    profile_initialize_output();
    assert(getenv("ELISA_PROFILE_FD") == NULL);
    assert(getenv("ELISA_PROFILE_MODE") == NULL);
    puts("collector regression smoke OK");
    return 0;
}
