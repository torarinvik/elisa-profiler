#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef ELISA_PROFILE_TIMING
#define ELISA_PROFILE_TIMING 0
#endif

#if ELISA_PROFILE_TIMING
#include <time.h>
#endif

/*
 * The stage1 backend's -ftrace ABI is deliberately tiny: a function name and
 * source line for statement boundaries, plus an optional variable/value pair.
 * Keep the collector independent of the Elisa runtime so it can aggregate the
 * complete run instead of the runtime's bounded crash-debug ring.
 */
typedef struct {
    const char *function_name;
    const char *variable_name;
    uint32_t line;
    uint8_t kind;
    uint8_t is_signed;
    uint64_t count;
    uint64_t minimum;
    uint64_t maximum;
    uint64_t last;
    uint64_t inclusive_ns;
    uint64_t self_ns;
    uint64_t completed_calls;
    __uint128_t sum;
    __int128_t signed_sum;
    uint64_t interval_ns;
    uint64_t max_interval_ns;
} profile_entry;

enum {
    PROFILE_KIND_STATEMENT = 1,
    PROFILE_KIND_VALUE = 2,
    PROFILE_KIND_FUNCTION = 3,
    PROFILE_RECENT_CAPACITY = 256,
};

typedef struct {
    const char *function_name;
    const char *variable_name;
    uint32_t line;
    uint8_t kind;
    uint8_t is_signed;
    uint64_t value;
} profile_recent_entry;

static profile_entry *profile_table;
static size_t profile_capacity;
static size_t profile_size;
static uint64_t profile_event_count;
static uint64_t profile_dropped_count;
static pthread_mutex_t profile_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t profile_crash_dumped;
static volatile sig_atomic_t profile_dumped;
static profile_recent_entry profile_recent[PROFILE_RECENT_CAPACITY];
static uint64_t profile_recent_position;

#if ELISA_PROFILE_TIMING
#define PROFILE_CALL_STACK_CAPACITY 1024

typedef struct {
    const char *function_name;
    uint64_t start_ns;
    uint64_t child_ns;
} profile_call_frame;

static _Thread_local profile_call_frame profile_call_stack[PROFILE_CALL_STACK_CAPACITY];
static _Thread_local size_t profile_call_depth;
static _Thread_local size_t profile_call_overflow_depth;

static const char *profile_timing_function_name;
static const char *profile_timing_variable_name;
static uint32_t profile_timing_line;
static uint8_t profile_timing_kind;
static uint8_t profile_timing_is_signed;
static uint64_t profile_timing_last_ns;
static int profile_timing_have_last;

static uint64_t profile_now_ns(void) {
    struct timespec timestamp;
    if (clock_gettime(CLOCK_MONOTONIC, &timestamp) != 0) {
        return 0;
    }
    return (uint64_t)timestamp.tv_sec * UINT64_C(1000000000) +
           (uint64_t)timestamp.tv_nsec;
}
#endif

static uint64_t profile_hash(const char *function_name, const char *variable_name,
                             uint32_t line, uint8_t kind, uint8_t is_signed) {
    uintptr_t function_bits = (uintptr_t)function_name;
    uintptr_t variable_bits = (uintptr_t)variable_name;
    uint64_t hash = UINT64_C(1469598103934665603);
    hash ^= (uint64_t)function_bits;
    hash *= UINT64_C(1099511628211);
    hash ^= (uint64_t)variable_bits;
    hash *= UINT64_C(1099511628211);
    hash ^= line;
    hash *= UINT64_C(1099511628211);
    hash ^= kind;
    hash *= UINT64_C(1099511628211);
    hash ^= is_signed;
    return hash;
}

static int profile_key_matches(const profile_entry *entry, const char *function_name,
                               const char *variable_name, uint32_t line, uint8_t kind,
                               uint8_t is_signed) {
    return entry->function_name == function_name && entry->variable_name == variable_name &&
           entry->line == line && entry->kind == kind && entry->is_signed == is_signed;
}

static profile_entry *profile_find_locked(const char *function_name,
                                          const char *variable_name, uint32_t line,
                                          uint8_t kind, uint8_t is_signed) {
    if (profile_capacity == 0) {
        return NULL;
    }
    size_t slot = profile_hash(function_name, variable_name, line, kind, is_signed) &
                  (profile_capacity - 1);
    for (size_t probes = 0; probes < profile_capacity; ++probes) {
        profile_entry *entry = &profile_table[slot];
        if (entry->function_name == NULL) {
            return NULL;
        }
        if (profile_key_matches(entry, function_name, variable_name, line, kind, is_signed)) {
            return entry;
        }
        slot = (slot + 1) & (profile_capacity - 1);
    }
    return NULL;
}

#if ELISA_PROFILE_TIMING
static void profile_account_previous_locked(uint64_t now_ns) {
    if (!profile_timing_have_last || now_ns == 0 || profile_timing_last_ns == 0 ||
        now_ns < profile_timing_last_ns) {
        profile_timing_last_ns = now_ns;
        return;
    }
    profile_entry *previous = profile_find_locked(
        profile_timing_function_name, profile_timing_variable_name,
        profile_timing_line, profile_timing_kind, profile_timing_is_signed);
    if (previous != NULL) {
        uint64_t interval_ns = now_ns - profile_timing_last_ns;
        previous->interval_ns += interval_ns;
        if (interval_ns > previous->max_interval_ns) {
            previous->max_interval_ns = interval_ns;
        }
    }
    profile_timing_last_ns = now_ns;
}
#endif

static int profile_grow_locked(void) {
    size_t new_capacity = profile_capacity == 0 ? 256 : profile_capacity * 2;
    profile_entry *new_table = calloc(new_capacity, sizeof(*new_table));
    if (new_table == NULL) {
        return 0;
    }

    for (size_t index = 0; index < profile_capacity; ++index) {
        profile_entry entry = profile_table[index];
        if (entry.function_name == NULL) {
            continue;
        }
        size_t slot = profile_hash(entry.function_name, entry.variable_name, entry.line,
                                   entry.kind, entry.is_signed) & (new_capacity - 1);
        while (new_table[slot].function_name != NULL) {
            slot = (slot + 1) & (new_capacity - 1);
        }
        new_table[slot] = entry;
    }

    free(profile_table);
    profile_table = new_table;
    profile_capacity = new_capacity;
    return 1;
}

static void profile_record(const char *function_name, uint32_t line,
                           const char *variable_name, uint64_t value, uint8_t kind,
                           uint8_t is_signed) {
    pthread_mutex_lock(&profile_lock);
#if ELISA_PROFILE_TIMING
    profile_account_previous_locked(profile_now_ns());
#endif
    ++profile_event_count;
    profile_recent[profile_recent_position % PROFILE_RECENT_CAPACITY] =
        (profile_recent_entry){
            .function_name = function_name,
            .variable_name = variable_name,
            .line = line,
            .kind = kind,
            .is_signed = is_signed,
            .value = value,
        };
    ++profile_recent_position;

    if (profile_capacity == 0 || (profile_size + 1) * 10 >= profile_capacity * 7) {
        if (!profile_grow_locked()) {
            ++profile_dropped_count;
#if ELISA_PROFILE_TIMING
            profile_timing_have_last = 0;
#endif
            pthread_mutex_unlock(&profile_lock);
            return;
        }
    }

    size_t slot = profile_hash(function_name, variable_name, line, kind, is_signed) & (profile_capacity - 1);
    while (profile_table[slot].function_name != NULL &&
           !profile_key_matches(&profile_table[slot], function_name, variable_name, line, kind, is_signed)) {
        slot = (slot + 1) & (profile_capacity - 1);
    }

    profile_entry *entry = &profile_table[slot];
    if (entry->function_name == NULL) {
        entry->function_name = function_name == NULL ? "<unknown>" : function_name;
        entry->variable_name = variable_name;
        entry->line = line;
        entry->kind = kind;
        entry->is_signed = is_signed;
        entry->minimum = value;
        entry->maximum = value;
        ++profile_size;
    }

    ++entry->count;
    if (kind == PROFILE_KIND_VALUE) {
        if (is_signed) {
            int64_t signed_value = (int64_t)value;
            if (signed_value < (int64_t)entry->minimum) {
                entry->minimum = value;
            }
            if (signed_value > (int64_t)entry->maximum) {
                entry->maximum = value;
            }
            entry->signed_sum += (__int128_t)signed_value;
        } else {
            if (value < entry->minimum) {
                entry->minimum = value;
            }
            if (value > entry->maximum) {
                entry->maximum = value;
            }
            entry->sum += value;
        }
        entry->last = value;
    }
#if ELISA_PROFILE_TIMING
    profile_timing_function_name = entry->function_name;
    profile_timing_variable_name = entry->variable_name;
    profile_timing_line = entry->line;
    profile_timing_kind = entry->kind;
    profile_timing_is_signed = entry->is_signed;
    profile_timing_have_last = 1;
#endif
    pthread_mutex_unlock(&profile_lock);
}

void elisa_trace_record(const char *function_name, uint32_t line) {
    profile_record(function_name, line, NULL, 0, PROFILE_KIND_STATEMENT, 0);
}

void elisa_trace_function_entry(const char *function_name, uint32_t line) {
#if ELISA_PROFILE_TIMING
    if (profile_call_depth < PROFILE_CALL_STACK_CAPACITY) {
        profile_call_stack[profile_call_depth] = (profile_call_frame){
            .function_name = function_name,
            .start_ns = profile_now_ns(),
            .child_ns = 0,
        };
        ++profile_call_depth;
    } else {
        ++profile_call_overflow_depth;
    }
#endif
    profile_record(function_name, line, NULL, 0, PROFILE_KIND_FUNCTION, 0);
}

static void profile_record_completed_function(const char *function_name, uint32_t line) {
    pthread_mutex_lock(&profile_lock);
    profile_entry *entry = profile_find_locked(
        function_name, NULL, line, PROFILE_KIND_FUNCTION, 0);
    if (entry != NULL) {
        ++entry->completed_calls;
    }
    pthread_mutex_unlock(&profile_lock);
}

#if ELISA_PROFILE_TIMING
static uint64_t profile_saturating_add(uint64_t left, uint64_t right) {
    return UINT64_MAX - left < right ? UINT64_MAX : left + right;
}

static void profile_record_timed_function_exit(const char *function_name, uint32_t line) {
    if (profile_call_overflow_depth > 0) {
        --profile_call_overflow_depth;
        profile_record_completed_function(function_name, line);
        return;
    }
    if (profile_call_depth == 0) {
        profile_record_completed_function(function_name, line);
        return;
    }
    profile_call_frame *frame = &profile_call_stack[profile_call_depth - 1];
    if (frame->function_name != function_name) {
        /* A missing/foreign exit must not poison every later frame. */
        profile_call_depth = 0;
        profile_call_overflow_depth = 0;
        profile_record_completed_function(function_name, line);
        return;
    }
    uint64_t now_ns = profile_now_ns();
    uint64_t inclusive_ns = now_ns >= frame->start_ns ? now_ns - frame->start_ns : 0;
    uint64_t self_ns = inclusive_ns >= frame->child_ns ? inclusive_ns - frame->child_ns : 0;
    --profile_call_depth;
    if (profile_call_depth > 0) {
        profile_call_frame *parent = &profile_call_stack[profile_call_depth - 1];
        parent->child_ns = profile_saturating_add(parent->child_ns, inclusive_ns);
    }

    pthread_mutex_lock(&profile_lock);
    profile_entry *entry = profile_find_locked(
        function_name, NULL, line, PROFILE_KIND_FUNCTION, 0);
    if (entry != NULL) {
        ++entry->completed_calls;
        entry->inclusive_ns = profile_saturating_add(entry->inclusive_ns, inclusive_ns);
        entry->self_ns = profile_saturating_add(entry->self_ns, self_ns);
    }
    pthread_mutex_unlock(&profile_lock);
}
#endif

void elisa_trace_function_exit(const char *function_name, uint32_t line) {
#if ELISA_PROFILE_TIMING
    profile_record_timed_function_exit(function_name, line);
#else
    profile_record_completed_function(function_name, line);
#endif
}

void elisa_trace_record_value(const char *function_name, uint32_t line,
                              const char *variable_name, uint64_t value, uint32_t is_signed) {
    profile_record(function_name, line, variable_name, value, PROFILE_KIND_VALUE,
                   is_signed != 0 ? 1 : 0);
}

/* The instrumented program asks the normal runtime to install its crash
 * handler at function entry. The profiler owns that handler so it can dump
 * the full collector state instead of the runtime's bounded trace ring. */
void elisa_trace_install_fault_handler(void) {}

static int profile_entry_compare(const void *left_pointer, const void *right_pointer) {
    const profile_entry *left = *(const profile_entry *const *)left_pointer;
    const profile_entry *right = *(const profile_entry *const *)right_pointer;
    if (left->count != right->count) {
        return left->count < right->count ? 1 : -1;
    }
    if (left->line != right->line) {
        return left->line < right->line ? -1 : 1;
    }
    int function_order = strcmp(left->function_name, right->function_name);
    if (function_order != 0) {
        return function_order;
    }
    if (left->kind != right->kind) {
        return left->kind < right->kind ? -1 : 1;
    }
    if (left->variable_name == NULL && right->variable_name != NULL) {
        return -1;
    }
    if (left->variable_name != NULL && right->variable_name == NULL) {
        return 1;
    }
    if (left->variable_name != NULL) {
        int variable_order = strcmp(left->variable_name, right->variable_name);
        if (variable_order != 0) {
            return variable_order;
        }
    }
    if (left->is_signed != right->is_signed) {
        return left->is_signed < right->is_signed ? -1 : 1;
    }
    return 0;
}

static void profile_print_field(const char *value) {
    /* Elisa identifiers cannot contain tabs/newlines; still keep the protocol safe. */
    if (value == NULL) {
        fputs("-", stderr);
        return;
    }
    for (const unsigned char *cursor = (const unsigned char *)value; *cursor != 0; ++cursor) {
        if (*cursor == '\t' || *cursor == '\n' || *cursor == '\r') {
            fputc('_', stderr);
        } else {
            fputc(*cursor, stderr);
        }
    }
}

static void profile_dump(void);
static void profile_dump_from_signal(void);

static void profile_dump_recent_path(void) {
    uint64_t start = profile_recent_position > PROFILE_RECENT_CAPACITY
                        ? profile_recent_position - PROFILE_RECENT_CAPACITY
                        : 0;
    for (uint64_t sequence = start; sequence < profile_recent_position; ++sequence) {
        const profile_recent_entry *entry =
            &profile_recent[sequence % PROFILE_RECENT_CAPACITY];
        fprintf(stderr, "ELISA_PROFILE\t1\tpath\t%" PRIu64 "\t%u\t",
                sequence - start, entry->kind);
        profile_print_field(entry->function_name);
        fprintf(stderr, "\t%" PRIu32 "\t", entry->line);
        profile_print_field(entry->variable_name);
        fprintf(stderr, "\t%u\t", entry->is_signed);
        if (entry->is_signed) {
            fprintf(stderr, "%" PRId64 "\n", (int64_t)entry->value);
        } else {
            fprintf(stderr, "%" PRIu64 "\n", entry->value);
        }
    }
}

static void profile_crash_handler(int signal_number) {
    if (!profile_crash_dumped) {
        profile_crash_dumped = 1;
        /*
         * This path is intentionally diagnostic rather than async-signal-safe:
         * preserving the trace is more useful than losing all profile data on
         * a target fault. The handler immediately restores the default action
         * and re-raises the original signal after dumping.
         */
        profile_dump_from_signal();
    }
    signal(signal_number, SIG_DFL);
    raise(signal_number);
}

static void profile_install_crash_handlers(void) {
    signal(SIGABRT, profile_crash_handler);
    signal(SIGFPE, profile_crash_handler);
    signal(SIGILL, profile_crash_handler);
    signal(SIGSEGV, profile_crash_handler);
    signal(SIGBUS, profile_crash_handler);
    signal(SIGTERM, profile_crash_handler);
    signal(SIGINT, profile_crash_handler);
}

static void profile_dump_body(void) {
    if (profile_dumped) {
        return;
    }
#if ELISA_PROFILE_TIMING
    profile_account_previous_locked(profile_now_ns());
#endif
    profile_dumped = 1;
    size_t count = profile_size;
    profile_entry **entries = calloc(count == 0 ? 1 : count, sizeof(*entries));
    if (entries == NULL) {
        ++profile_dropped_count;
        fprintf(stderr, "ELISA_PROFILE\t1\tmeta\t%" PRIu64 "\t0\t%" PRIu64 "\n",
                profile_event_count, profile_dropped_count);
        if (profile_crash_dumped) {
            profile_dump_recent_path();
        }
        return;
    }

    size_t output_count = 0;
    for (size_t index = 0; index < profile_capacity; ++index) {
        if (profile_table[index].function_name != NULL) {
            entries[output_count++] = &profile_table[index];
        }
    }
    qsort(entries, output_count, sizeof(*entries), profile_entry_compare);
    fprintf(stderr, "ELISA_PROFILE\t1\tmeta\t%" PRIu64 "\t%zu\t%" PRIu64 "\n",
            profile_event_count, output_count, profile_dropped_count);
    for (size_t index = 0; index < output_count; ++index) {
        const profile_entry *entry = entries[index];
        fprintf(stderr, "ELISA_PROFILE\t1\tlocation\t%u\t", entry->kind);
        profile_print_field(entry->function_name);
        fprintf(stderr, "\t%" PRIu32 "\t%" PRIu64 "\t", entry->line, entry->count);
        profile_print_field(entry->variable_name);
        fprintf(stderr, "\t%u\t", entry->is_signed);
        if (entry->kind == PROFILE_KIND_FUNCTION) {
            fprintf(stderr, "%" PRIu64 "\t%" PRIu64 "\t%" PRIu64,
                    entry->inclusive_ns, entry->self_ns, entry->completed_calls);
        } else if (entry->is_signed) {
            fprintf(stderr, "%" PRId64 "\t%" PRId64 "\t",
                    (int64_t)entry->minimum, (int64_t)entry->maximum);
            if (entry->signed_sum > (__int128_t)INT64_MAX ||
                entry->signed_sum < (__int128_t)INT64_MIN) {
                fputs("overflow", stderr);
            } else {
                fprintf(stderr, "%" PRId64, (int64_t)entry->signed_sum);
            }
        } else {
            fprintf(stderr, "%" PRIu64 "\t%" PRIu64 "\t", entry->minimum, entry->maximum);
            if (entry->sum > UINT64_MAX) {
                fputs("overflow", stderr);
            } else {
                fprintf(stderr, "%" PRIu64, (uint64_t)entry->sum);
            }
        }
        if (entry->is_signed) {
            fprintf(stderr, "\t%" PRId64, (int64_t)entry->last);
        } else {
            fprintf(stderr, "\t%" PRIu64, entry->last);
        }
        fprintf(stderr, "\t%" PRIu64 "\t%" PRIu64 "\n",
                entry->interval_ns, entry->max_interval_ns);
    }
    free(entries);
    if (profile_crash_dumped) {
        profile_dump_recent_path();
    }
}

static void profile_dump(void) {
    pthread_mutex_lock(&profile_lock);
    profile_dump_body();
    pthread_mutex_unlock(&profile_lock);
}

static void profile_dump_from_signal(void) {
    if (profile_dumped) {
        return;
    }
    /*
     * A timeout or fault may interrupt the collector while it owns the mutex.
     * Never wait for that mutex from a signal handler. The unlocked fallback
     * can observe one in-flight update, but preserves a usable partial report
     * and then restores the original signal disposition.
     */
    if (pthread_mutex_trylock(&profile_lock) == 0) {
        profile_dump_body();
        pthread_mutex_unlock(&profile_lock);
    } else {
        profile_dump_body();
    }
}

extern int64_t elisa_profile_target_main(void);

int main(void) {
    profile_install_crash_handlers();
    atexit(profile_dump);
    int64_t result = elisa_profile_target_main();
    profile_dump();
    return (int)(result & 0xff);
}

/* Optional runtime hooks. The standalone runtime object keeps these unresolved
 * because embedding hosts may provide richer implementations. A profiler run
 * needs deterministic no-op/fallback behavior for code that does not use them. */
void *elisa_native_callback_ptr(uint8_t *name) {
    (void)name;
    return NULL;
}
uint32_t elisa_native_callback_call_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; return fallback;
}
int32_t elisa_native_callback_call_i32_voidp(uint8_t *name, void *arg, int32_t fallback) {
    (void)name; (void)arg; return fallback;
}
uintptr_t elisa_native_callback_call_usize_voidp(uint8_t *name, void *arg, uintptr_t fallback) {
    (void)name; (void)arg; return fallback;
}
intptr_t elisa_native_callback_call_isize_voidp(uint8_t *name, void *arg, intptr_t fallback) {
    (void)name; (void)arg; return fallback;
}
uint32_t elisa_native_callback_spawn_join_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; return fallback;
}
void *elisa_native_callback_context_new_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; (void)fallback; return NULL;
}
void *elisa_native_callback_context_entry_u32_voidp(void) { return NULL; }
int32_t elisa_native_callback_context_start_u32_voidp(void *ctx, uintptr_t *thread) {
    (void)ctx; (void)thread; return -1;
}
uint32_t elisa_native_callback_context_join_u32_voidp(uintptr_t handle, void *ctx, uint32_t fallback) {
    (void)handle; (void)ctx; return fallback;
}
uint32_t elisa_native_callback_context_spawn_join_u32_voidp(void *ctx, uint32_t fallback) {
    (void)ctx; return fallback;
}
uint32_t elisa_native_callback_context_result_u32(void *ctx, uint32_t fallback) {
    (void)ctx; return fallback;
}
void elisa_native_callback_context_free(void *ctx) { (void)ctx; }
void va_copy(void *destination, void *source) {
    (void)destination; (void)source;
}
void va_end(void *argument) { (void)argument; }
