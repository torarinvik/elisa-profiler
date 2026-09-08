#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#ifndef ELISA_PROFILE_TIMING
#define ELISA_PROFILE_TIMING 0
#endif

#ifndef ELISA_PROFILE_CPU_TIMING
#define ELISA_PROFILE_CPU_TIMING 0
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
    uint64_t identity_id;
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

typedef struct {
    const char *caller_name;
    const char *callee_name;
    uint64_t caller_id;
    uint64_t callee_id;
    uint64_t call_events;
    uint64_t completed_calls;
    uint64_t inclusive_ns;
} profile_call_edge;

typedef struct {
    uint32_t kind;
    uint64_t address;
    uint64_t size;
    uint64_t old_address;
    uint64_t old_size;
    uint64_t arena;
    uint64_t region;
    uint64_t sequence;
    uint64_t thread_id;
    uint64_t timestamp_ns;
} profile_allocation_event;

typedef struct profile_call_path profile_call_path;

struct profile_call_path {
    profile_call_path *parent;
    const char *function_name;
    uint64_t function_id;
    uint64_t call_events;
    uint64_t completed_calls;
    uint64_t self_ns;
};

enum {
    PROFILE_KIND_STATEMENT = 1,
    PROFILE_KIND_VALUE = 2,
    PROFILE_KIND_FUNCTION = 3,
    PROFILE_ID_UNSET = 0,
    PROFILE_PROTOCOL_VERSION = 1,
    PROFILE_MODE_FULL = 0,
    PROFILE_MODE_FUNCTIONS = 1,
    PROFILE_MODE_STATEMENTS = 2,
    PROFILE_MODE_VALUES = 3,
    PROFILE_MODE_DIAGNOSTIC = 4,
    PROFILE_MODE_SAMPLES = 5,
    PROFILE_RECENT_CAPACITY = 256,
    PROFILE_CALL_STACK_CAPACITY = 1024,
    PROFILE_DEFAULT_LOCATION_LIMIT = 32768,
    PROFILE_DEFAULT_CALL_EDGE_LIMIT = 16384,
    PROFILE_DEFAULT_CALL_PATH_LIMIT = 32768,
    PROFILE_DEFAULT_CAPTURE_BYTE_LIMIT = 64 * 1024 * 1024,
    PROFILE_EVENT_TRACE_FIXED_BYTES = 64,
    PROFILE_INITIAL_THREAD_TRACE_CAPACITY = 64,
    PROFILE_FRAME_BUFFER_BYTES = 1024 * 1024,
    PROFILE_FRAME_HEADER_BYTES = 128,
    PROFILE_INITIAL_LOCATION_CAPACITY = 256,
    PROFILE_INITIAL_CALL_EDGE_CAPACITY = 64,
    PROFILE_INITIAL_CALL_PATH_CAPACITY = 64,
    PROFILE_INITIAL_ALLOCATION_CAPACITY = 128,
    PROFILE_CAPACITY_GROWTH_FACTOR = 2,
    PROFILE_TABLE_LOAD_NUMERATOR = 10,
    PROFILE_TABLE_LOAD_DENOMINATOR = 7,
    PROFILE_DECIMAL_DIGITS = 20,
    PROFILE_DECIMAL_BASE = 10,
    PROFILE_COUNTER_INCREMENT = 1,
    PROFILE_NANOS_PER_SECOND = 1000000000,
    PROFILE_MICROSECONDS_PER_SECOND = 1000000,
    PROFILE_HASH_NULL_MARKER = 255,
    PROFILE_HASH_ID_MARKER = 254,
    PROFILE_SIGNAL_MARKER_BUFFER_BYTES = 64 * 1024,
    PROFILE_SAMPLE_MARKER_BUFFER_BYTES = 64 * 1024,
    PROFILE_SAMPLE_FRAME_HEADER_BYTES = 128,
    PROFILE_DEFAULT_SAMPLE_PERIOD_MICROSECONDS = 1000,
    PROFILE_MIN_SAMPLE_PERIOD_MICROSECONDS = 100,
    PROFILE_MAX_SAMPLE_PERIOD_MICROSECONDS = 1000000,
    PROFILE_SAMPLE_HANDLER_IDLE = 0,
    PROFILE_SAMPLE_HANDLER_BUSY = 1,
    PROFILE_THREAD_LIFECYCLE_ACTIVE = 0,
    PROFILE_THREAD_LIFECYCLE_ENDED = 1,
    PROFILE_ALLOCATION_ALLOC = 1,
    PROFILE_ALLOCATION_REALLOC_IN_PLACE = 2,
    PROFILE_ALLOCATION_REALLOC_MOVE = 3,
    PROFILE_ALLOCATION_RECLAIM = 4,
    PROFILE_ALLOCATION_REGION_CREATE = 5,
    PROFILE_ALLOCATION_REGION_RESET = 6,
    PROFILE_ALLOCATION_REGION_TRIM = 7,
    PROFILE_ALLOCATION_REGION_FREE = 8,
    PROFILE_ALLOCATION_ARENA_ADOPT = 9,
    PROFILE_SAMPLE_SIGNAL = SIGPROF,
    PROFILE_COLLECTOR_FAILURE_STATUS = 126,
    PROFILE_COLLECTOR_STATUS_OK = 1,
    PROFILE_COLLECTOR_STATUS_SAMPLING_FAILURE = 2,
    PROFILE_COLLECTOR_STATUS_OUTPUT_FAILURE = 3,
    PROFILE_SIGNAL_EXIT_BASE = 128,
    PROFILE_EXIT_CODE_MASK = 0xff,
};

static const uint64_t PROFILE_FNV_OFFSET_BASIS = UINT64_C(14695981039346656037);
static const uint64_t PROFILE_FNV_PRIME = UINT64_C(1099511628211);
static const char PROFILE_CHILD_ENVIRONMENT[] = "ELISA_PROFILE_CHILD";
static const char PROFILE_FD_ENVIRONMENT[] = "ELISA_PROFILE_FD";
static const char PROFILE_STATUS_FD_ENVIRONMENT[] = "ELISA_PROFILE_STATUS_FD";
static const char PROFILE_FRAMED_ENVIRONMENT[] = "ELISA_PROFILE_FRAMED";
static const char PROFILE_THREAD_RECORDS_ENVIRONMENT[] = "ELISA_PROFILE_THREAD_RECORDS";
static const char PROFILE_MODE_ENVIRONMENT[] = "ELISA_PROFILE_MODE";
static const char PROFILE_EVENT_TRACE_ENVIRONMENT[] = "ELISA_PROFILE_EVENT_TRACE";
static const char PROFILE_EVENT_TRACE_LIMIT_ENVIRONMENT[] = "ELISA_PROFILE_EVENT_TRACE_LIMIT";
static const char PROFILE_SAMPLE_PERIOD_ENVIRONMENT[] = "ELISA_PROFILE_SAMPLE_PERIOD_US";
static const char PROFILE_SAMPLE_MODE_PREFIX[] = "sample:";
static const char PROFILE_MAX_LOCATIONS_ENVIRONMENT[] = "ELISA_PROFILE_MAX_LOCATIONS";
static const char PROFILE_MAX_CALL_EDGES_ENVIRONMENT[] = "ELISA_PROFILE_MAX_CALL_EDGES";
static const char PROFILE_MAX_STACKS_ENVIRONMENT[] = "ELISA_PROFILE_MAX_STACKS";
static const char PROFILE_MAX_CAPTURE_BYTES_ENVIRONMENT[] = "ELISA_PROFILE_MAX_CAPTURE_BYTES";
static const char PROFILE_RECENT_PATH_ENVIRONMENT[] = "ELISA_PROFILE_RECENT_PATH";
static const char *const PROFILE_INTERNAL_ENVIRONMENTS[] = {
    PROFILE_FD_ENVIRONMENT,
    PROFILE_STATUS_FD_ENVIRONMENT,
    PROFILE_FRAMED_ENVIRONMENT,
    PROFILE_THREAD_RECORDS_ENVIRONMENT,
    PROFILE_MODE_ENVIRONMENT,
    PROFILE_EVENT_TRACE_ENVIRONMENT,
    PROFILE_EVENT_TRACE_LIMIT_ENVIRONMENT,
    PROFILE_SAMPLE_PERIOD_ENVIRONMENT,
    PROFILE_MAX_LOCATIONS_ENVIRONMENT,
    PROFILE_MAX_CALL_EDGES_ENVIRONMENT,
    PROFILE_MAX_STACKS_ENVIRONMENT,
    PROFILE_MAX_CAPTURE_BYTES_ENVIRONMENT,
    PROFILE_RECENT_PATH_ENVIRONMENT,
};

typedef struct {
    const char *function_name;
    const char *variable_name;
    uint32_t line;
    uint8_t kind;
    uint8_t is_signed;
    uint64_t identity_id;
    uint64_t value;
} profile_recent_entry;

typedef struct {
    const char *function_name;
    const char *variable_name;
    uint32_t line;
    uint8_t kind;
    uint8_t is_signed;
    uint64_t identity_id;
    uint64_t value;
    uint64_t sequence;
    uint64_t thread_id;
    uint64_t timestamp_ns;
} profile_trace_event;

static profile_entry *profile_table;
static size_t profile_capacity;
static size_t profile_size;
static uint64_t profile_event_count;
static uint64_t profile_dropped_count;
static uint64_t profile_call_edge_dropped_count;
static uint64_t profile_call_path_dropped_count;
static uint64_t profile_location_limit;
static uint64_t profile_call_edge_limit;
static uint64_t profile_call_path_limit;
static int profile_budget_exceeded;
static uint64_t profile_capture_byte_limit;
static uint64_t profile_capture_bytes_used;
static uint64_t profile_capture_bytes_dropped;
static pthread_mutex_t profile_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t profile_crash_dumped;
static volatile sig_atomic_t profile_dumped;
static int profile_recent_path_enabled;
static profile_recent_entry profile_recent[PROFILE_RECENT_CAPACITY];
static uint64_t profile_recent_position;
static int profile_mode = PROFILE_MODE_FULL;

static profile_call_edge *profile_call_edges;
static size_t profile_call_edge_capacity;
static size_t profile_call_edge_size;
static profile_call_path **profile_call_paths;
static size_t profile_call_path_capacity;
static size_t profile_call_path_size;
static size_t profile_max_call_depth;
static uint64_t profile_stack_overflow_entries;
static FILE *profile_output_stream;
static pthread_once_t profile_output_once = PTHREAD_ONCE_INIT;
static pthread_key_t profile_thread_key;
static pthread_once_t profile_thread_key_once = PTHREAD_ONCE_INIT;
static int profile_thread_key_available;
static int profile_event_trace_enabled;
static uint64_t profile_event_trace_limit;
static uint64_t profile_event_trace_captured;
static uint64_t profile_event_trace_omitted;
static int profile_output_fd = STDERR_FILENO;
static int profile_status_fd = -1;
static volatile sig_atomic_t profile_output_write_failed;
static volatile sig_atomic_t profile_status_written;
static int profile_framing_enabled;
static uint64_t profile_frame_sequence;
static uint64_t profile_frame_dropped_count;
static int profile_thread_records_enabled;
static volatile sig_atomic_t profile_fork_child_disabled;
static int profile_child_profiling_enabled;
static char profile_frame_buffer[PROFILE_FRAME_BUFFER_BYTES];
static size_t profile_frame_length;
static int profile_frame_overflowed;
static char profile_signal_marker_buffer[PROFILE_SIGNAL_MARKER_BUFFER_BYTES];
static volatile sig_atomic_t profile_frame_write_in_progress;
static volatile sig_atomic_t profile_sampling_enabled;
static volatile sig_atomic_t profile_sample_count;
static volatile sig_atomic_t profile_sample_missed;
static volatile sig_atomic_t profile_sample_sequence;
static volatile sig_atomic_t profile_sample_handler_busy;
static uint64_t profile_sample_period_microseconds;
static int profile_sampling_setup_failed;
static char profile_sample_marker_buffer[PROFILE_SAMPLE_MARKER_BUFFER_BYTES];
static char profile_sample_frame_header[PROFILE_SAMPLE_FRAME_HEADER_BYTES];
#if defined(__APPLE__) || defined(__linux__)
static struct sigaction profile_previous_sample_action;
static int profile_previous_sample_action_valid;
enum {
    PROFILE_CRASH_SIGNAL_COUNT = 7,
};
static const int profile_crash_signals[PROFILE_CRASH_SIGNAL_COUNT] = {
    SIGABRT, SIGFPE, SIGILL, SIGSEGV, SIGBUS, SIGTERM, SIGINT,
};
static struct sigaction
    profile_previous_crash_actions[PROFILE_CRASH_SIGNAL_COUNT];
static volatile sig_atomic_t
    profile_previous_crash_action_valid[PROFILE_CRASH_SIGNAL_COUNT];
#endif

static uint64_t profile_saturating_add_u64(uint64_t left, uint64_t right);

static uint64_t profile_trace_timestamp_ns(void) {
    struct timespec timestamp;
    if (clock_gettime(CLOCK_MONOTONIC, &timestamp) != 0 || timestamp.tv_sec < 0 ||
        timestamp.tv_nsec < 0) {
        return 0;
    }
    uint64_t seconds = (uint64_t)timestamp.tv_sec;
    if (seconds > UINT64_MAX / PROFILE_NANOS_PER_SECOND) {
        return UINT64_MAX;
    }
    uint64_t result = seconds * PROFILE_NANOS_PER_SECOND;
    uint64_t nanoseconds = (uint64_t)timestamp.tv_nsec;
    return nanoseconds > UINT64_MAX - result ? UINT64_MAX : result + nanoseconds;
}

static __uint128_t profile_saturating_add_unsigned_sum(__uint128_t left,
                                                       uint64_t right) {
    const __uint128_t overflow = (__uint128_t)UINT64_MAX + 1;
    if (left >= overflow || (__uint128_t)right > overflow - left) {
        return overflow;
    }
    return left + right;
}

static __int128_t profile_saturating_add_signed_sum(__int128_t left,
                                                    int64_t right) {
    const __int128_t low = (__int128_t)INT64_MIN - 1;
    const __int128_t high = (__int128_t)INT64_MAX + 1;
    if (left <= low || left >= high) {
        return left <= low ? low : high;
    }
    if (right > 0 && left > high - (__int128_t)right) {
        return high;
    }
    if (right < 0 && left < low - (__int128_t)right) {
        return low;
    }
    return left + (__int128_t)right;
}

static uint64_t profile_saturating_increment_u64(uint64_t value) {
    return profile_saturating_add_u64(value, PROFILE_COUNTER_INCREMENT);
}

static size_t profile_saturating_increment_size(size_t value) {
    return value == SIZE_MAX ? SIZE_MAX : value + PROFILE_COUNTER_INCREMENT;
}

static int profile_write_all(const char *buffer, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t written = write(profile_output_fd, buffer + offset, length - offset);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            profile_output_write_failed = 1;
            return 0;
        }
        if (written == 0) {
            profile_output_write_failed = 1;
            return 0;
        }
        offset += (size_t)written;
    }
    return 1;
}

static int profile_environment_is_true(const char *name) {
    const char *value = getenv(name);
    return value != NULL && strcmp(value, "1") == 0;
}

static void profile_clear_internal_environment(void) {
    if (profile_environment_is_true(PROFILE_CHILD_ENVIRONMENT)) {
        return;
    }
    for (size_t index = 0;
         index < sizeof(PROFILE_INTERNAL_ENVIRONMENTS) /
                    sizeof(PROFILE_INTERNAL_ENVIRONMENTS[0]);
         ++index) {
        (void)unsetenv(PROFILE_INTERNAL_ENVIRONMENTS[index]);
    }
}

static void profile_record_reset(void) {
    profile_frame_length = 0;
    profile_frame_overflowed = 0;
}

static void profile_record_append_bytes(const char *bytes, size_t length) {
    if (profile_frame_overflowed || profile_frame_length > PROFILE_FRAME_BUFFER_BYTES ||
        length > PROFILE_FRAME_BUFFER_BYTES - profile_frame_length) {
        profile_frame_overflowed = 1;
        return;
    }
    memcpy(profile_frame_buffer + profile_frame_length, bytes, length);
    profile_frame_length += length;
}

static void profile_record_append_text(const char *text) {
    profile_record_append_bytes(text, strlen(text));
}

static void profile_record_append_char(char value) {
    profile_record_append_bytes(&value, 1);
}

static void profile_record_append_uint64(uint64_t value) {
    char digits[PROFILE_DECIMAL_DIGITS + 1];
    int length = snprintf(digits, sizeof(digits), "%" PRIu64, value);
    if (length < 0) {
        profile_frame_overflowed = 1;
        return;
    }
    profile_record_append_bytes(digits, (size_t)length);
}

static void profile_record_append_int64(int64_t value) {
    char digits[PROFILE_DECIMAL_DIGITS + 2];
    int length = snprintf(digits, sizeof(digits), "%" PRId64, value);
    if (length < 0) {
        profile_frame_overflowed = 1;
        return;
    }
    profile_record_append_bytes(digits, (size_t)length);
}

static void profile_record_append_field(const char *value) {
    if (value == NULL) {
        profile_record_append_char('-');
        return;
    }
    for (const unsigned char *cursor = (const unsigned char *)value;
         *cursor != 0;
         ++cursor) {
        char output = (*cursor == '\t' || *cursor == '\n' || *cursor == '\r')
                          ? '_'
                          : (char)*cursor;
        profile_record_append_char(output);
    }
}

static uint64_t profile_frame_checksum(const char *bytes, size_t length) {
    uint64_t checksum = PROFILE_FNV_OFFSET_BASIS;
    for (size_t index = 0; index < length; ++index) {
        checksum ^= (unsigned char)bytes[index];
        checksum *= PROFILE_FNV_PRIME;
    }
    return checksum;
}

static void profile_record_emit(void) {
    if (profile_frame_overflowed) {
        profile_frame_dropped_count =
            profile_saturating_increment_u64(profile_frame_dropped_count);
        profile_budget_exceeded = 1;
        profile_capture_bytes_dropped = profile_saturating_add_u64(
            profile_capture_bytes_dropped, profile_frame_length);
        return;
    }
    if (!profile_framing_enabled) {
        profile_frame_write_in_progress = 1;
        int payload_written = profile_write_all(profile_frame_buffer, profile_frame_length);
        static const char newline[] = "\n";
        int newline_written = payload_written &&
                             profile_write_all(newline, sizeof(newline) - 1);
        if (!newline_written) {
            profile_budget_exceeded = 1;
        }
        profile_frame_write_in_progress = 0;
        return;
    }
    profile_frame_write_in_progress = 1;
    char header[PROFILE_FRAME_HEADER_BYTES];
    int header_length = snprintf(
        header, sizeof(header), "ELISA_PROFILE\t1\tframe\t%" PRIu64 "\t%zu\t%" PRIu64 "\t",
        profile_frame_sequence, profile_frame_length,
        profile_frame_checksum(profile_frame_buffer, profile_frame_length));
    if (header_length < 0 || (size_t)header_length >= sizeof(header)) {
        profile_frame_dropped_count =
            profile_saturating_increment_u64(profile_frame_dropped_count);
        profile_budget_exceeded = 1;
        profile_frame_write_in_progress = 0;
        return;
    }
    int header_written = profile_write_all(header, (size_t)header_length);
    int payload_written = header_written &&
                          profile_write_all(profile_frame_buffer, profile_frame_length);
    static const char newline[] = "\n";
    int newline_written = payload_written &&
                          profile_write_all(newline, sizeof(newline) - 1);
    if (!newline_written) {
        profile_frame_dropped_count =
            profile_saturating_increment_u64(profile_frame_dropped_count);
        profile_budget_exceeded = 1;
    }
    profile_frame_sequence =
        profile_saturating_increment_u64(profile_frame_sequence);
    profile_frame_write_in_progress = 0;
}

static int profile_status_write_all(const char *buffer, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t written = write(profile_status_fd, buffer + offset, length - offset);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            profile_output_write_failed = 1;
            return 0;
        }
        if (written == 0) {
            profile_output_write_failed = 1;
            return 0;
        }
        offset += (size_t)written;
    }
    return 1;
}

static void profile_write_status(void) {
    if (profile_status_fd < 0 || profile_status_written) {
        return;
    }
    profile_status_written = 1;
    static const char ok_status[] = "ELISA_PROFILE_STATUS\t1\tok\n";
    static const char sampling_failure_status[] =
        "ELISA_PROFILE_STATUS\t1\tfailure\t2\n";
    static const char output_failure_status[] =
        "ELISA_PROFILE_STATUS\t1\tfailure\t3\n";
    const char *status = profile_sampling_setup_failed
                             ? sampling_failure_status
                             : profile_output_write_failed
                                 ? output_failure_status
                                 : ok_status;
    (void)profile_status_write_all(status, strlen(status));
}

static void profile_record_begin(void) {
    profile_record_reset();
    profile_record_append_text("ELISA_PROFILE\t1\t");
}

static void profile_write_capture_begin(FILE *stream) {
    (void)stream;
    profile_record_begin();
    profile_record_append_text("begin\t");
    profile_record_append_uint64(PROFILE_PROTOCOL_VERSION);
    profile_record_emit();
}

static void profile_write_fallback_capture_begin(void) {
    profile_write_capture_begin(profile_output_stream);
    profile_clear_internal_environment();
}

static void profile_initialize_output(void) {
    profile_output_stream = stderr;
    profile_output_fd = STDERR_FILENO;
    profile_child_profiling_enabled =
        profile_environment_is_true(PROFILE_CHILD_ENVIRONMENT);
    const char *status_fd_text = getenv(PROFILE_STATUS_FD_ENVIRONMENT);
    if (status_fd_text != NULL && *status_fd_text != '\0') {
        char *status_end = NULL;
        long requested_status_fd = strtol(status_fd_text, &status_end, 10);
        if (status_end != status_fd_text && *status_end == '\0' &&
            requested_status_fd >= 0 && requested_status_fd <= INT_MAX) {
            int duplicate_status_fd = dup((int)requested_status_fd);
            if (duplicate_status_fd >= 0) {
                if (duplicate_status_fd != (int)requested_status_fd) {
                    (void)close((int)requested_status_fd);
                }
                profile_status_fd = duplicate_status_fd;
            }
        }
    }
    profile_framing_enabled = profile_environment_is_true(PROFILE_FRAMED_ENVIRONMENT);
    const char *fd_text = getenv(PROFILE_FD_ENVIRONMENT);
    if (fd_text == NULL || *fd_text == '\0') {
        profile_write_fallback_capture_begin();
        return;
    }
    char *end = NULL;
    long requested_fd = strtol(fd_text, &end, 10);
    if (end == fd_text || *end != '\0' || requested_fd < 0 || requested_fd > INT_MAX) {
        profile_write_fallback_capture_begin();
        return;
    }
    int duplicate_fd = dup((int)requested_fd);
    if (duplicate_fd < 0) {
        profile_write_fallback_capture_begin();
        return;
    }
    if (duplicate_fd != (int)requested_fd) {
        (void)close((int)requested_fd);
    }
    FILE *stream = fdopen(duplicate_fd, "w");
    if (stream == NULL) {
        close(duplicate_fd);
        profile_write_fallback_capture_begin();
        return;
    }
    (void)setvbuf(stream, NULL, _IONBF, 0);
    profile_output_fd = duplicate_fd;
    profile_output_stream = stream;
    profile_write_capture_begin(profile_output_stream);
    profile_clear_internal_environment();
}

static FILE *profile_output(void) {
    (void)pthread_once(&profile_output_once, profile_initialize_output);
    return profile_output_stream;
}

static void profile_after_fork_child(void) {
    if (profile_child_profiling_enabled) {
        return;
    }
    profile_fork_child_disabled = 1;
    if (profile_output_fd > STDERR_FILENO) {
        (void)close(profile_output_fd);
    }
    if (profile_status_fd >= 0) {
        (void)close(profile_status_fd);
    }
    profile_output_fd = -1;
    profile_status_fd = -1;
}

static void profile_register_fork_policy(void) {
    (void)pthread_atfork(NULL, NULL, profile_after_fork_child);
}

/* Keep the existing diagnostic formatting compact while allowing every
 * collector write to switch transports without changing the protocol. */
#undef stderr
#define stderr profile_output()

typedef struct profile_thread_state profile_thread_state;

struct profile_thread_state {
    profile_thread_state *next;
    uint64_t thread_id;
    uint64_t end_event;
    int lifecycle_ended;
    uint64_t event_count;
    uint64_t first_event;
    uint64_t last_event;
    uint64_t location_dropped;
    uint64_t call_edge_dropped;
    uint64_t stack_dropped;
    uint64_t trace_dropped;
    uint64_t bytes_dropped;
    profile_trace_event *trace_events;
    size_t trace_capacity;
    size_t trace_size;
    profile_allocation_event *allocation_events;
    size_t allocation_capacity;
    size_t allocation_size;
    uint64_t allocation_dropped;
#if ELISA_PROFILE_TIMING
    const char *timing_function_name;
    const char *timing_variable_name;
    uint32_t timing_line;
    uint8_t timing_kind;
    uint8_t timing_is_signed;
    uint64_t timing_identity_id;
    uint64_t timing_last_ns;
    int timing_have_last;
#endif
};

static profile_thread_state *profile_threads;
static uint64_t profile_thread_count;
static uint64_t profile_allocation_event_count;
static uint64_t profile_allocation_dropped_count;
static _Thread_local int profile_allocation_callback_busy;

static uint64_t profile_saturating_add_u64(uint64_t left, uint64_t right) {
    return UINT64_MAX - left < right ? UINT64_MAX : left + right;
}

static int profile_thread_trace_buffer_grow_locked(profile_thread_state *thread);

static int profile_reserve_bytes_locked(uint64_t bytes) {
    if (bytes > UINT64_MAX - profile_capture_bytes_used ||
        (profile_capture_byte_limit != 0 &&
         (profile_capture_bytes_used > profile_capture_byte_limit ||
          bytes > profile_capture_byte_limit - profile_capture_bytes_used))) {
        profile_capture_bytes_dropped =
            profile_saturating_add_u64(profile_capture_bytes_dropped, bytes);
        profile_budget_exceeded = 1;
        return 0;
    }
    profile_capture_bytes_used += bytes;
    return 1;
}

static void profile_release_bytes_locked(uint64_t bytes) {
    profile_capture_bytes_used = bytes > profile_capture_bytes_used
                                     ? 0
                                     : profile_capture_bytes_used - bytes;
}

static int profile_next_capacity(size_t current, size_t initial, size_t *next) {
    if (current == 0) {
        *next = initial;
        return 1;
    }
    if (current > SIZE_MAX / PROFILE_CAPACITY_GROWTH_FACTOR) {
        return 0;
    }
    *next = current * PROFILE_CAPACITY_GROWTH_FACTOR;
    return 1;
}

static int profile_allocation_bytes(size_t count, size_t element_size,
                                    uint64_t *bytes) {
    if (element_size != 0 && count > SIZE_MAX / element_size) {
        return 0;
    }
    size_t allocation = count * element_size;
    if ((uintmax_t)allocation > UINT64_MAX) {
        return 0;
    }
    *bytes = (uint64_t)allocation;
    return 1;
}

static int profile_table_requires_growth(size_t current_size, size_t capacity) {
    if (capacity == 0) {
        return 1;
    }
    size_t whole_capacity = capacity / PROFILE_TABLE_LOAD_NUMERATOR;
    size_t remainder = capacity % PROFILE_TABLE_LOAD_NUMERATOR;
    size_t threshold = whole_capacity * PROFILE_TABLE_LOAD_DENOMINATOR;
    if (remainder != 0) {
        threshold += (remainder * PROFILE_TABLE_LOAD_DENOMINATOR +
                      PROFILE_TABLE_LOAD_NUMERATOR - 1) /
                     PROFILE_TABLE_LOAD_NUMERATOR;
    }
    return current_size >= threshold - 1;
}

/* Trace strings are ABI data, not guaranteed to be interned by the compiler. */
static int profile_strings_equal(const char *left, const char *right) {
    if (left == right) {
        return 1;
    }
    if (left == NULL || right == NULL) {
        return 0;
    }
    return strcmp(left, right) == 0;
}

static uint64_t profile_hash_string(uint64_t hash, const char *value) {
    if (value == NULL) {
        hash ^= PROFILE_HASH_NULL_MARKER;
        hash *= PROFILE_FNV_PRIME;
        return hash;
    }
    for (const unsigned char *cursor = (const unsigned char *)value;
         *cursor != 0;
         ++cursor) {
        hash ^= *cursor;
        hash *= PROFILE_FNV_PRIME;
    }
    /* Apply one FNV step for the NUL terminator as a field separator. */
    hash *= PROFILE_FNV_PRIME;
    return hash;
}

/* Compiler-issued IDs are the hot-path identity. Names remain a compatibility
 * fallback for legacy callbacks and are retained for human-readable output. */
static uint64_t profile_hash_identity(uint64_t hash, const char *name,
                                      uint64_t identity_id) {
    if (identity_id != PROFILE_ID_UNSET) {
        hash ^= PROFILE_HASH_ID_MARKER;
        hash *= PROFILE_FNV_PRIME;
        hash ^= identity_id;
        hash *= PROFILE_FNV_PRIME;
        return hash;
    }
    return profile_hash_string(hash, name);
}

typedef struct {
    const char *function_name;
    const char *caller_name;
    profile_call_path *path;
    uint64_t function_id;
    uint64_t caller_id;
#if ELISA_PROFILE_TIMING
    uint64_t start_ns;
    uint64_t child_ns;
#endif
} profile_call_frame;

typedef struct profile_overflow_frame profile_overflow_frame;

struct profile_overflow_frame {
    const char *function_name;
    uint32_t line;
    uint64_t function_id;
    profile_overflow_frame *previous;
};

static _Thread_local profile_call_frame profile_call_stack[PROFILE_CALL_STACK_CAPACITY];
static _Thread_local size_t profile_call_depth;
static _Thread_local size_t profile_call_overflow_depth;
static _Thread_local profile_overflow_frame *profile_call_overflow_stack;
static _Thread_local size_t profile_call_overflow_untracked_depth;
static _Thread_local profile_thread_state *profile_current_thread;
static profile_thread_state *profile_get_thread_locked(void);
static void profile_initialize_thread_key(void);
static void profile_thread_key_destructor(void *value);

static void profile_push_overflow_frame(const char *function_name, uint32_t line,
                                        uint64_t function_id) {
    /* Once one allocation fails, keep later overflow entries untracked so a
     * known frame can never be placed above an unknown one. */
    if (profile_call_overflow_untracked_depth > 0) {
        profile_call_overflow_untracked_depth =
            profile_saturating_increment_size(profile_call_overflow_untracked_depth);
        return;
    }
    profile_overflow_frame *frame = malloc(sizeof(*frame));
    if (frame == NULL) {
        profile_call_overflow_untracked_depth = 1;
        return;
    }
    *frame = (profile_overflow_frame){
        .function_name = function_name,
        .line = line,
        .function_id = function_id,
        .previous = profile_call_overflow_stack,
    };
    profile_call_overflow_stack = frame;
}

static profile_overflow_frame *profile_pop_overflow_frame(void) {
    profile_overflow_frame *frame = profile_call_overflow_stack;
    if (frame != NULL) {
        profile_call_overflow_stack = frame->previous;
    }
    return frame;
}

static void profile_clear_overflow_frames(void) {
    while (profile_call_overflow_stack != NULL) {
        profile_overflow_frame *frame = profile_call_overflow_stack;
        profile_call_overflow_stack = frame->previous;
        free(frame);
    }
    profile_call_overflow_untracked_depth = 0;
    profile_call_overflow_depth = 0;
}

#if ELISA_PROFILE_TIMING
static uint64_t profile_now_ns(void) {
    struct timespec timestamp;
#if ELISA_PROFILE_CPU_TIMING
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &timestamp) != 0) {
#else
    if (clock_gettime(CLOCK_MONOTONIC, &timestamp) != 0) {
#endif
        return 0;
    }
    return (uint64_t)timestamp.tv_sec * PROFILE_NANOS_PER_SECOND +
           (uint64_t)timestamp.tv_nsec;
}
#endif

static uint64_t profile_hash(const char *function_name, const char *variable_name,
                             uint32_t line, uint8_t kind, uint8_t is_signed,
                             uint64_t identity_id) {
    uint64_t hash = PROFILE_FNV_OFFSET_BASIS;
    hash = profile_hash_identity(hash, function_name, identity_id);
    hash = profile_hash_string(hash, variable_name);
    hash ^= line;
    hash *= PROFILE_FNV_PRIME;
    hash ^= kind;
    hash *= PROFILE_FNV_PRIME;
    hash ^= is_signed;
    hash *= PROFILE_FNV_PRIME;
    hash ^= identity_id;
    hash *= PROFILE_FNV_PRIME;
    return hash;
}

static int profile_identity_matches(uint64_t left, uint64_t right) {
    return left == PROFILE_ID_UNSET && right == PROFILE_ID_UNSET
               ? 1
               : left != PROFILE_ID_UNSET && left == right;
}

static int profile_named_identity_matches(const char *left_name, const char *right_name,
                                          uint64_t left_id, uint64_t right_id) {
    if (!profile_identity_matches(left_id, right_id)) {
        return 0;
    }
    return left_id != PROFILE_ID_UNSET && right_id != PROFILE_ID_UNSET
               ? 1
               : profile_strings_equal(left_name, right_name);
}

static int profile_key_matches(const profile_entry *entry, const char *function_name,
                               const char *variable_name, uint32_t line, uint8_t kind,
                               uint8_t is_signed, uint64_t identity_id) {
    return profile_named_identity_matches(entry->function_name, function_name,
                                          entry->identity_id, identity_id) &&
           profile_strings_equal(entry->variable_name, variable_name) &&
           entry->line == line && entry->kind == kind && entry->is_signed == is_signed;
}

static profile_entry *profile_find_locked(const char *function_name,
                                          const char *variable_name, uint32_t line,
                                          uint8_t kind, uint8_t is_signed,
                                          uint64_t identity_id) {
    if (profile_capacity == 0) {
        return NULL;
    }
    size_t slot = profile_hash(function_name, variable_name, line, kind, is_signed,
                               identity_id) & (profile_capacity - 1);
    for (size_t probes = 0; probes < profile_capacity; ++probes) {
        profile_entry *entry = &profile_table[slot];
        if (entry->function_name == NULL) {
            return NULL;
        }
        if (profile_key_matches(entry, function_name, variable_name, line, kind,
                                is_signed, identity_id)) {
            return entry;
        }
        slot = (slot + 1) & (profile_capacity - 1);
    }
    return NULL;
}

static uint64_t profile_call_edge_hash(const char *caller_name, const char *callee_name,
                                       uint64_t caller_id, uint64_t callee_id) {
    uint64_t hash = PROFILE_FNV_OFFSET_BASIS;
    hash = profile_hash_identity(hash, caller_name, caller_id);
    hash = profile_hash_identity(hash, callee_name, callee_id);
    hash ^= caller_id;
    hash *= PROFILE_FNV_PRIME;
    hash ^= callee_id;
    hash *= PROFILE_FNV_PRIME;
    return hash;
}

static profile_call_edge *profile_find_call_edge_locked(const char *caller_name,
                                                         const char *callee_name,
                                                         uint64_t caller_id,
                                                         uint64_t callee_id) {
    if (profile_call_edge_capacity == 0) {
        return NULL;
    }
    size_t slot = profile_call_edge_hash(caller_name, callee_name, caller_id, callee_id) &
                  (profile_call_edge_capacity - 1);
    for (size_t probes = 0; probes < profile_call_edge_capacity; ++probes) {
        profile_call_edge *edge = &profile_call_edges[slot];
        if (edge->caller_name == NULL) {
            return NULL;
        }
        if (profile_named_identity_matches(edge->caller_name, caller_name,
                                           edge->caller_id, caller_id) &&
            profile_named_identity_matches(edge->callee_name, callee_name,
                                           edge->callee_id, callee_id)) {
            return edge;
        }
        slot = (slot + 1) & (profile_call_edge_capacity - 1);
    }
    return NULL;
}

static int profile_grow_call_edges_locked(void) {
    size_t new_capacity;
    uint64_t new_bytes;
    if (!profile_next_capacity(profile_call_edge_capacity,
                               PROFILE_INITIAL_CALL_EDGE_CAPACITY, &new_capacity) ||
        !profile_allocation_bytes(new_capacity, sizeof(*profile_call_edges), &new_bytes)) {
        return 0;
    }
    if (!profile_reserve_bytes_locked(new_bytes)) {
        return 0;
    }
    profile_call_edge *new_edges = calloc(new_capacity, sizeof(*new_edges));
    if (new_edges == NULL) {
        profile_release_bytes_locked(new_bytes);
        return 0;
    }
    for (size_t index = 0; index < profile_call_edge_capacity; ++index) {
        profile_call_edge edge = profile_call_edges[index];
        if (edge.caller_name == NULL) {
            continue;
        }
        size_t slot = profile_call_edge_hash(edge.caller_name, edge.callee_name,
                                             edge.caller_id, edge.callee_id) &
                      (new_capacity - 1);
        while (new_edges[slot].caller_name != NULL) {
            slot = (slot + 1) & (new_capacity - 1);
        }
        new_edges[slot] = edge;
    }
    uint64_t old_bytes = 0;
    (void)profile_allocation_bytes(profile_call_edge_capacity,
                                   sizeof(*profile_call_edges), &old_bytes);
    free(profile_call_edges);
    profile_release_bytes_locked(old_bytes);
    profile_call_edges = new_edges;
    profile_call_edge_capacity = new_capacity;
    return 1;
}

static void profile_record_call_edge(const char *caller_name, const char *callee_name,
                                     uint64_t caller_id, uint64_t callee_id) {
    if (caller_name == NULL || callee_name == NULL) {
        return;
    }
    pthread_mutex_lock(&profile_lock);
    profile_thread_state *thread = profile_get_thread_locked();
    profile_call_edge *existing = profile_find_call_edge_locked(
        caller_name, callee_name, caller_id, callee_id);
    if (existing != NULL) {
        existing->call_events =
            profile_saturating_increment_u64(existing->call_events);
        pthread_mutex_unlock(&profile_lock);
        return;
    }
    if (profile_call_edge_limit != 0 &&
        profile_call_edge_size >= profile_call_edge_limit) {
        profile_call_edge_dropped_count =
            profile_saturating_increment_u64(profile_call_edge_dropped_count);
        profile_budget_exceeded = 1;
        if (thread != NULL) {
            thread->call_edge_dropped =
                profile_saturating_increment_u64(thread->call_edge_dropped);
        }
        pthread_mutex_unlock(&profile_lock);
        return;
    }
    if (profile_table_requires_growth(profile_call_edge_size,
                                      profile_call_edge_capacity)) {
        if (!profile_grow_call_edges_locked()) {
            profile_call_edge_dropped_count =
                profile_saturating_increment_u64(profile_call_edge_dropped_count);
            if (thread != NULL) {
                thread->call_edge_dropped =
                    profile_saturating_increment_u64(thread->call_edge_dropped);
            }
            pthread_mutex_unlock(&profile_lock);
            return;
        }
    }
    size_t slot = profile_call_edge_hash(caller_name, callee_name, caller_id, callee_id) &
                  (profile_call_edge_capacity - 1);
    while (profile_call_edges[slot].caller_name != NULL &&
           !(profile_named_identity_matches(profile_call_edges[slot].caller_name, caller_name,
                                            profile_call_edges[slot].caller_id, caller_id) &&
             profile_named_identity_matches(profile_call_edges[slot].callee_name, callee_name,
                                            profile_call_edges[slot].callee_id, callee_id))) {
        slot = (slot + 1) & (profile_call_edge_capacity - 1);
    }
    profile_call_edge *edge = &profile_call_edges[slot];
    if (edge->caller_name == NULL) {
        edge->caller_name = caller_name;
        edge->callee_name = callee_name;
        edge->caller_id = caller_id;
        edge->callee_id = callee_id;
        profile_call_edge_size =
            profile_saturating_increment_size(profile_call_edge_size);
    }
    edge->call_events = profile_saturating_increment_u64(edge->call_events);
    pthread_mutex_unlock(&profile_lock);
}

static void profile_record_completed_call_edge(const char *caller_name,
                                                const char *callee_name,
                                                uint64_t caller_id,
                                                uint64_t callee_id,
                                                uint64_t inclusive_ns) {
    if (caller_name == NULL || callee_name == NULL) {
        return;
    }
    pthread_mutex_lock(&profile_lock);
    profile_call_edge *edge = profile_find_call_edge_locked(
        caller_name, callee_name, caller_id, callee_id);
    if (edge != NULL) {
        edge->completed_calls =
            profile_saturating_increment_u64(edge->completed_calls);
#if ELISA_PROFILE_TIMING
        edge->inclusive_ns = UINT64_MAX - edge->inclusive_ns < inclusive_ns
                                 ? UINT64_MAX
                                 : edge->inclusive_ns + inclusive_ns;
#else
        (void)inclusive_ns;
#endif
    }
    pthread_mutex_unlock(&profile_lock);
}

#if ELISA_PROFILE_TIMING
static uint64_t profile_saturating_add(uint64_t left, uint64_t right) {
    return UINT64_MAX - left < right ? UINT64_MAX : left + right;
}
#endif

static uint64_t profile_call_path_hash(const profile_call_path *parent,
                                       const char *function_name,
                                       uint64_t function_id) {
    uint64_t hash = PROFILE_FNV_OFFSET_BASIS;
    hash ^= (uint64_t)(uintptr_t)parent;
    hash *= PROFILE_FNV_PRIME;
    hash = profile_hash_identity(hash, function_name, function_id);
    return hash;
}

static int profile_grow_call_paths_locked(void) {
    size_t new_capacity;
    uint64_t new_bytes;
    if (!profile_next_capacity(profile_call_path_capacity,
                               PROFILE_INITIAL_CALL_PATH_CAPACITY, &new_capacity) ||
        !profile_allocation_bytes(new_capacity, sizeof(*profile_call_paths), &new_bytes)) {
        return 0;
    }
    if (!profile_reserve_bytes_locked(new_bytes)) {
        return 0;
    }
    profile_call_path **new_paths = calloc(new_capacity, sizeof(*new_paths));
    if (new_paths == NULL) {
        profile_release_bytes_locked(new_bytes);
        return 0;
    }
    for (size_t index = 0; index < profile_call_path_capacity; ++index) {
        profile_call_path *path = profile_call_paths[index];
        if (path == NULL) {
            continue;
        }
        size_t slot = profile_call_path_hash(path->parent, path->function_name,
                                             path->function_id) &
                      (new_capacity - 1);
        while (new_paths[slot] != NULL) {
            slot = (slot + 1) & (new_capacity - 1);
        }
        new_paths[slot] = path;
    }
    uint64_t old_bytes = 0;
    (void)profile_allocation_bytes(profile_call_path_capacity,
                                   sizeof(*profile_call_paths), &old_bytes);
    free(profile_call_paths);
    profile_release_bytes_locked(old_bytes);
    profile_call_paths = new_paths;
    profile_call_path_capacity = new_capacity;
    return 1;
}

static profile_call_path *profile_record_call_path(profile_call_path *parent,
                                                    const char *function_name,
                                                    uint64_t function_id) {
    if (function_name == NULL) {
        return NULL;
    }
    pthread_mutex_lock(&profile_lock);
    profile_thread_state *thread = profile_get_thread_locked();
    size_t existing_slot = profile_call_path_capacity == 0
                               ? 0
                               : profile_call_path_hash(parent, function_name, function_id) &
                                     (profile_call_path_capacity - 1);
    if (profile_call_path_capacity != 0) {
        while (profile_call_paths[existing_slot] != NULL &&
               !(profile_call_paths[existing_slot]->parent == parent &&
                 profile_named_identity_matches(profile_call_paths[existing_slot]->function_name,
                                                function_name,
                                                profile_call_paths[existing_slot]->function_id,
                                                function_id))) {
            existing_slot = (existing_slot + 1) & (profile_call_path_capacity - 1);
        }
        if (profile_call_paths[existing_slot] != NULL) {
            profile_call_paths[existing_slot]->call_events =
                profile_saturating_increment_u64(
                    profile_call_paths[existing_slot]->call_events);
            pthread_mutex_unlock(&profile_lock);
            return profile_call_paths[existing_slot];
        }
    }
    if (profile_call_path_limit != 0 &&
        profile_call_path_size >= profile_call_path_limit) {
        profile_call_path_dropped_count =
            profile_saturating_increment_u64(profile_call_path_dropped_count);
        profile_budget_exceeded = 1;
        if (thread != NULL) {
            thread->stack_dropped =
                profile_saturating_increment_u64(thread->stack_dropped);
        }
        pthread_mutex_unlock(&profile_lock);
        return NULL;
    }
    if (profile_table_requires_growth(profile_call_path_size,
                                      profile_call_path_capacity)) {
        if (!profile_grow_call_paths_locked()) {
            profile_call_path_dropped_count =
                profile_saturating_increment_u64(profile_call_path_dropped_count);
            if (thread != NULL) {
                thread->stack_dropped =
                    profile_saturating_increment_u64(thread->stack_dropped);
            }
            pthread_mutex_unlock(&profile_lock);
            return NULL;
        }
    }
    size_t slot = profile_call_path_hash(parent, function_name, function_id) &
                  (profile_call_path_capacity - 1);
    while (profile_call_paths[slot] != NULL &&
           !(profile_call_paths[slot]->parent == parent &&
             profile_named_identity_matches(profile_call_paths[slot]->function_name,
                                            function_name,
                                            profile_call_paths[slot]->function_id,
                                            function_id))) {
        slot = (slot + 1) & (profile_call_path_capacity - 1);
    }
    profile_call_path *path = profile_call_paths[slot];
    if (path == NULL) {
        if (!profile_reserve_bytes_locked(sizeof(*path))) {
            profile_call_path_dropped_count =
                profile_saturating_increment_u64(profile_call_path_dropped_count);
            if (thread != NULL) {
                thread->stack_dropped =
                    profile_saturating_increment_u64(thread->stack_dropped);
            }
            pthread_mutex_unlock(&profile_lock);
            return NULL;
        }
        path = calloc(1, sizeof(*path));
        if (path == NULL) {
            profile_release_bytes_locked(sizeof(*path));
            profile_call_path_dropped_count =
                profile_saturating_increment_u64(profile_call_path_dropped_count);
            if (thread != NULL) {
                thread->stack_dropped =
                    profile_saturating_increment_u64(thread->stack_dropped);
            }
            pthread_mutex_unlock(&profile_lock);
            return NULL;
        }
        path->parent = parent;
        path->function_name = function_name;
        path->function_id = function_id;
        profile_call_paths[slot] = path;
        profile_call_path_size =
            profile_saturating_increment_size(profile_call_path_size);
    }
    path->call_events = profile_saturating_increment_u64(path->call_events);
    pthread_mutex_unlock(&profile_lock);
    return path;
}

static void profile_record_completed_call_path(profile_call_path *path,
                                                uint64_t self_ns) {
    if (path == NULL) {
        return;
    }
    pthread_mutex_lock(&profile_lock);
    path->completed_calls =
        profile_saturating_increment_u64(path->completed_calls);
#if ELISA_PROFILE_TIMING
    path->self_ns = profile_saturating_add(path->self_ns, self_ns);
#else
    (void)self_ns;
#endif
    pthread_mutex_unlock(&profile_lock);
}

static profile_thread_state *profile_get_thread_locked(void) {
    if (profile_current_thread != NULL) {
        return profile_current_thread;
    }
    (void)pthread_once(&profile_thread_key_once, profile_initialize_thread_key);
    profile_thread_state *thread = NULL;
    if (!profile_reserve_bytes_locked(sizeof(*thread))) {
        return NULL;
    }
    thread = calloc(1, sizeof(*thread));
    if (thread == NULL) {
        profile_release_bytes_locked(sizeof(*thread));
        return NULL;
    }
    thread->next = profile_threads;
    thread->thread_id = profile_thread_count;
    profile_threads = thread;
    profile_current_thread = thread;
    if (profile_event_trace_enabled) {
        (void)profile_thread_trace_buffer_grow_locked(thread);
    }
    if (profile_thread_key_available) {
        (void)pthread_setspecific(profile_thread_key, thread);
    }
    profile_thread_count =
        profile_saturating_increment_u64(profile_thread_count);
    return thread;
}

static int profile_mode_allows_allocations(void) {
    return profile_mode == PROFILE_MODE_FULL || profile_mode == PROFILE_MODE_DIAGNOSTIC;
}

static int profile_allocation_buffer_grow_locked(profile_thread_state *thread) {
    size_t new_capacity;
    uint64_t new_bytes;
    if (thread == NULL ||
        !profile_next_capacity(thread->allocation_capacity,
                               PROFILE_INITIAL_ALLOCATION_CAPACITY,
                               &new_capacity) ||
        !profile_allocation_bytes(new_capacity,
                                  sizeof(*thread->allocation_events),
                                  &new_bytes) ||
        !profile_reserve_bytes_locked(new_bytes)) {
        return 0;
    }
    profile_allocation_event *new_events =
        calloc(new_capacity, sizeof(*new_events));
    if (new_events == NULL) {
        profile_release_bytes_locked(new_bytes);
        return 0;
    }
    if (thread->allocation_events != NULL && thread->allocation_size > 0) {
        memcpy(new_events, thread->allocation_events,
               thread->allocation_size * sizeof(*new_events));
    }
    uint64_t old_bytes = 0;
    (void)profile_allocation_bytes(thread->allocation_capacity,
                                   sizeof(*thread->allocation_events),
                                   &old_bytes);
    free(thread->allocation_events);
    profile_release_bytes_locked(old_bytes);
    thread->allocation_events = new_events;
    thread->allocation_capacity = new_capacity;
    return 1;
}

/* Strong override of the compiler runtime's weak no-op hook. The callback
 * records only fixed-width data; formatting, sorting, and protocol I/O wait
 * until profile_dump_body holds the collector lock. */
void elisa_profile_allocation_event(uint32_t kind, uintptr_t address,
                                     size_t size, uintptr_t old_address,
                                     size_t old_size, uintptr_t arena,
                                     size_t region) {
    if (profile_fork_child_disabled || !profile_mode_allows_allocations() ||
        profile_allocation_callback_busy) {
        return;
    }
    profile_allocation_callback_busy = 1;
    pthread_mutex_lock(&profile_lock);
    profile_thread_state *thread = profile_get_thread_locked();
    if (thread == NULL ||
        (thread->allocation_size >= thread->allocation_capacity &&
         !profile_allocation_buffer_grow_locked(thread))) {
        profile_allocation_dropped_count =
            profile_saturating_increment_u64(profile_allocation_dropped_count);
        profile_budget_exceeded = 1;
        if (thread != NULL) {
            thread->allocation_dropped =
                profile_saturating_increment_u64(thread->allocation_dropped);
        }
        pthread_mutex_unlock(&profile_lock);
        profile_allocation_callback_busy = 0;
        return;
    }
    profile_allocation_event *event =
        &thread->allocation_events[thread->allocation_size++];
    *event = (profile_allocation_event){
        .kind = kind,
        .address = (uint64_t)address,
        .size = (uint64_t)size,
        .old_address = (uint64_t)old_address,
        .old_size = (uint64_t)old_size,
        .arena = (uint64_t)arena,
        .region = (uint64_t)region,
        .sequence = profile_allocation_event_count,
        .thread_id = thread->thread_id,
        .timestamp_ns = profile_trace_timestamp_ns(),
    };
    profile_allocation_event_count =
        profile_saturating_increment_u64(profile_allocation_event_count);
    pthread_mutex_unlock(&profile_lock);
    profile_allocation_callback_busy = 0;
}

#if ELISA_PROFILE_TIMING
static uint64_t profile_now_ns_for_thread(const profile_thread_state *thread) {
#if ELISA_PROFILE_CPU_TIMING
    /* macOS does not expose pthread_getcpuclockid. Never use the dumping
     * thread's CPU clock to flush a different thread's timing cursor. */
    if (thread != profile_current_thread) {
        return 0;
    }
    return profile_now_ns();
#else
    (void)thread;
    return profile_now_ns();
#endif
}

static uint64_t profile_elapsed_ns(uint64_t start_ns, uint64_t end_ns) {
    if (start_ns == 0 || end_ns == 0 || end_ns < start_ns) {
        return 0;
    }
    return end_ns - start_ns;
}

static void profile_invalidate_timing_cursor(profile_thread_state *thread) {
    if (thread == NULL) {
        return;
    }
    thread->timing_last_ns = 0;
    thread->timing_have_last = 0;
}

static void profile_account_previous_locked(profile_thread_state *thread,
                                             uint64_t now_ns) {
    if (thread == NULL) {
        return;
    }
    /* A foreign thread cannot be queried on macOS in CPU-clock mode. Do not
     * invalidate its cursor while dumping from the main thread; its own next
     * trace event will account it using that worker's clock. A zero timestamp
     * on the current thread is a clock failure, so discard the unknown gap. */
    if (now_ns == 0) {
        if (thread == profile_current_thread) {
            profile_invalidate_timing_cursor(thread);
        }
        return;
    }
    if (!thread->timing_have_last || thread->timing_last_ns == 0 ||
        now_ns < thread->timing_last_ns) {
        thread->timing_last_ns = now_ns;
        return;
    }
    profile_entry *previous = profile_find_locked(
        thread->timing_function_name, thread->timing_variable_name,
        thread->timing_line, thread->timing_kind, thread->timing_is_signed,
        thread->timing_identity_id);
    if (previous != NULL) {
        uint64_t interval_ns = profile_elapsed_ns(thread->timing_last_ns, now_ns);
        previous->interval_ns = profile_saturating_add(previous->interval_ns, interval_ns);
        if (interval_ns > previous->max_interval_ns) {
            previous->max_interval_ns = interval_ns;
        }
    }
    thread->timing_last_ns = now_ns;
}

static void profile_close_timing_cursor(void) {
    uint64_t now_ns = profile_now_ns();
    pthread_mutex_lock(&profile_lock);
    profile_account_previous_locked(profile_current_thread, now_ns);
    profile_invalidate_timing_cursor(profile_current_thread);
    pthread_mutex_unlock(&profile_lock);
}
#endif

static void profile_thread_key_destructor(void *value) {
    profile_thread_state *thread = (profile_thread_state *)value;
    if (thread == NULL || profile_fork_child_disabled) {
        return;
    }
    pthread_mutex_lock(&profile_lock);
    if (!thread->lifecycle_ended) {
#if ELISA_PROFILE_TIMING
        if (!profile_dumped) {
            profile_account_previous_locked(thread, profile_now_ns_for_thread(thread));
        }
#endif
        thread->lifecycle_ended = PROFILE_THREAD_LIFECYCLE_ENDED;
        thread->end_event = profile_event_count;
    }
    if (thread == profile_current_thread) {
        profile_current_thread = NULL;
    }
    pthread_mutex_unlock(&profile_lock);
}

static void profile_initialize_thread_key(void) {
    profile_thread_key_available =
        pthread_key_create(&profile_thread_key, profile_thread_key_destructor) == 0;
}

static int profile_grow_locked(void) {
    size_t new_capacity;
    uint64_t new_bytes;
    if (!profile_next_capacity(profile_capacity, PROFILE_INITIAL_LOCATION_CAPACITY,
                               &new_capacity) ||
        !profile_allocation_bytes(new_capacity, sizeof(*profile_table), &new_bytes)) {
        return 0;
    }
    if (!profile_reserve_bytes_locked(new_bytes)) {
        return 0;
    }
    profile_entry *new_table = calloc(new_capacity, sizeof(*new_table));
    if (new_table == NULL) {
        profile_release_bytes_locked(new_bytes);
        return 0;
    }

    for (size_t index = 0; index < profile_capacity; ++index) {
        profile_entry entry = profile_table[index];
        if (entry.function_name == NULL) {
            continue;
        }
        size_t slot = profile_hash(entry.function_name, entry.variable_name, entry.line,
                                   entry.kind, entry.is_signed, entry.identity_id) &
                      (new_capacity - 1);
        while (new_table[slot].function_name != NULL) {
            slot = (slot + 1) & (new_capacity - 1);
        }
        new_table[slot] = entry;
    }

    uint64_t old_bytes = 0;
    (void)profile_allocation_bytes(profile_capacity, sizeof(*profile_table), &old_bytes);
    free(profile_table);
    profile_release_bytes_locked(old_bytes);
    profile_table = new_table;
    profile_capacity = new_capacity;
    return 1;
}

static uint64_t profile_event_trace_bytes(const char *function_name,
                                          const char *variable_name) {
    uint64_t bytes = PROFILE_EVENT_TRACE_FIXED_BYTES;
    if (function_name != NULL) {
        bytes = profile_saturating_add_u64(bytes, strlen(function_name));
    }
    if (variable_name != NULL) {
        bytes = profile_saturating_add_u64(bytes, strlen(variable_name));
    }
    return bytes;
}

static int profile_thread_trace_buffer_grow_locked(profile_thread_state *thread) {
    if (thread == NULL) {
        return 0;
    }
    size_t new_capacity;
    uint64_t new_bytes;
    if (!profile_next_capacity(thread->trace_capacity,
                               PROFILE_INITIAL_THREAD_TRACE_CAPACITY,
                               &new_capacity) ||
        !profile_allocation_bytes(new_capacity, sizeof(*thread->trace_events),
                                   &new_bytes)) {
        return 0;
    }
    if (!profile_reserve_bytes_locked(new_bytes)) {
        return 0;
    }
    profile_trace_event *new_events = calloc(new_capacity, sizeof(*new_events));
    if (new_events == NULL) {
        profile_release_bytes_locked(new_bytes);
        profile_capture_bytes_dropped = profile_saturating_add_u64(
            profile_capture_bytes_dropped, new_bytes);
        profile_budget_exceeded = 1;
        return 0;
    }
    if (thread->trace_events != NULL && thread->trace_size > 0) {
        memcpy(new_events, thread->trace_events,
               thread->trace_size * sizeof(*new_events));
    }
    uint64_t old_bytes = 0;
    (void)profile_allocation_bytes(thread->trace_capacity,
                                   sizeof(*thread->trace_events), &old_bytes);
    free(thread->trace_events);
    profile_release_bytes_locked(old_bytes);
    thread->trace_events = new_events;
    thread->trace_capacity = new_capacity;
    return 1;
}

static int profile_thread_trace_append_locked(profile_thread_state *thread,
                                               const profile_trace_event *event) {
    if (thread == NULL || event == NULL) {
        return 0;
    }
    if (thread->trace_size >= thread->trace_capacity &&
        !profile_thread_trace_buffer_grow_locked(thread)) {
        return 0;
    }
    thread->trace_events[thread->trace_size++] = *event;
    return 1;
}

static void profile_note_trace_drop_locked(profile_thread_state *thread) {
    profile_event_trace_omitted =
        profile_saturating_increment_u64(profile_event_trace_omitted);
    if (thread != NULL) {
        thread->bytes_dropped =
            profile_saturating_increment_u64(thread->bytes_dropped);
        thread->trace_dropped =
            profile_saturating_increment_u64(thread->trace_dropped);
    }
}

static int profile_mode_allows_kind(uint8_t kind) {
    switch (profile_mode) {
    case PROFILE_MODE_SAMPLES:
        return 0;
    case PROFILE_MODE_FUNCTIONS:
        return kind == PROFILE_KIND_FUNCTION;
    case PROFILE_MODE_STATEMENTS:
        return kind == PROFILE_KIND_STATEMENT || kind == PROFILE_KIND_FUNCTION;
    case PROFILE_MODE_VALUES:
        return kind == PROFILE_KIND_VALUE || kind == PROFILE_KIND_FUNCTION;
    case PROFILE_MODE_DIAGNOSTIC:
    case PROFILE_MODE_FULL:
    default:
        return 1;
    }
}

static void profile_record(const char *function_name, uint32_t line,
                           const char *variable_name, uint64_t value, uint8_t kind,
                           uint8_t is_signed, size_t call_depth,
                           int stack_overflowed, uint64_t identity_id) {
    if (profile_fork_child_disabled) {
        return;
    }
    if (!profile_mode_allows_kind(kind)) {
        return;
    }
    function_name = function_name == NULL ? "<unknown>" : function_name;
    pthread_mutex_lock(&profile_lock);
    profile_thread_state *thread = profile_get_thread_locked();
#if !ELISA_PROFILE_TIMING
    (void)thread;
#endif
    if (thread != NULL) {
        if (thread->event_count == 0) {
            thread->first_event = profile_event_count;
        }
        thread->last_event = profile_event_count;
        thread->event_count =
            profile_saturating_increment_u64(thread->event_count);
    }
    if (call_depth > profile_max_call_depth) {
        profile_max_call_depth = call_depth;
    }
    if (stack_overflowed) {
        profile_stack_overflow_entries =
            profile_saturating_increment_u64(profile_stack_overflow_entries);
    }
#if ELISA_PROFILE_TIMING
    profile_account_previous_locked(thread, profile_now_ns());
#endif
    profile_event_count = profile_saturating_increment_u64(profile_event_count);
    profile_recent[profile_recent_position % PROFILE_RECENT_CAPACITY] =
        (profile_recent_entry){
            .function_name = function_name,
            .variable_name = variable_name,
            .line = line,
            .kind = kind,
            .is_signed = is_signed,
            .identity_id = identity_id,
            .value = value,
        };
    profile_recent_position =
        profile_saturating_increment_u64(profile_recent_position);
    int trace_allowed = profile_event_trace_enabled &&
                        (profile_event_trace_limit == 0 ||
                         profile_event_trace_captured < profile_event_trace_limit);
    if (trace_allowed) {
        uint64_t trace_bytes = profile_event_trace_bytes(function_name, variable_name);
        if (profile_reserve_bytes_locked(trace_bytes)) {
            profile_trace_event event = {
                .function_name = function_name,
                .variable_name = variable_name,
                .line = line,
                .kind = kind,
                .is_signed = is_signed,
                .identity_id = identity_id,
                .value = value,
                .sequence = profile_event_count - 1,
                .thread_id = thread == NULL ? 0 : thread->thread_id,
                .timestamp_ns = profile_trace_timestamp_ns(),
            };
            if (profile_thread_trace_append_locked(thread, &event)) {
                profile_event_trace_captured =
                    profile_saturating_increment_u64(profile_event_trace_captured);
            } else {
                profile_release_bytes_locked(trace_bytes);
                profile_capture_bytes_dropped = profile_saturating_add_u64(
                    profile_capture_bytes_dropped, trace_bytes);
                profile_budget_exceeded = 1;
                profile_note_trace_drop_locked(thread);
            }
        } else {
            profile_note_trace_drop_locked(thread);
        }
    } else if (profile_event_trace_enabled) {
        profile_note_trace_drop_locked(thread);
    }

    profile_entry *existing = profile_find_locked(
        function_name, variable_name, line, kind, is_signed, identity_id);
    if (existing == NULL && profile_location_limit != 0 &&
        profile_size >= profile_location_limit) {
        profile_dropped_count =
            profile_saturating_increment_u64(profile_dropped_count);
        profile_budget_exceeded = 1;
        if (thread != NULL) {
            thread->location_dropped =
                profile_saturating_increment_u64(thread->location_dropped);
        }
#if ELISA_PROFILE_TIMING
        if (thread != NULL) {
            thread->timing_have_last = 0;
        }
#endif
        pthread_mutex_unlock(&profile_lock);
        return;
    }
    if (existing == NULL && (profile_capacity == 0 ||
        (profile_size + 1) * PROFILE_TABLE_LOAD_NUMERATOR >=
            profile_capacity * PROFILE_TABLE_LOAD_DENOMINATOR)) {
        if (!profile_grow_locked()) {
            profile_dropped_count =
                profile_saturating_increment_u64(profile_dropped_count);
            if (thread != NULL) {
                thread->location_dropped =
                    profile_saturating_increment_u64(thread->location_dropped);
            }
#if ELISA_PROFILE_TIMING
            if (thread != NULL) {
                thread->timing_have_last = 0;
            }
#endif
            pthread_mutex_unlock(&profile_lock);
            return;
        }
    }

    size_t slot = profile_hash(function_name, variable_name, line, kind, is_signed,
                               identity_id) & (profile_capacity - 1);
    while (profile_table[slot].function_name != NULL &&
           !profile_key_matches(&profile_table[slot], function_name, variable_name, line,
                                kind, is_signed, identity_id)) {
        slot = (slot + 1) & (profile_capacity - 1);
    }

    profile_entry *entry = &profile_table[slot];
    if (entry->function_name == NULL) {
        entry->function_name = function_name == NULL ? "<unknown>" : function_name;
        entry->variable_name = variable_name;
        entry->line = line;
        entry->kind = kind;
        entry->is_signed = is_signed;
        entry->identity_id = identity_id;
        entry->minimum = value;
        entry->maximum = value;
        ++profile_size;
    }

    entry->count = profile_saturating_increment_u64(entry->count);
    if (kind == PROFILE_KIND_VALUE) {
        if (is_signed) {
            int64_t signed_value = (int64_t)value;
            if (signed_value < (int64_t)entry->minimum) {
                entry->minimum = value;
            }
            if (signed_value > (int64_t)entry->maximum) {
                entry->maximum = value;
            }
            entry->signed_sum = profile_saturating_add_signed_sum(
                entry->signed_sum, signed_value);
        } else {
            if (value < entry->minimum) {
                entry->minimum = value;
            }
            if (value > entry->maximum) {
                entry->maximum = value;
            }
            entry->sum = profile_saturating_add_unsigned_sum(entry->sum, value);
        }
        entry->last = value;
    }
#if ELISA_PROFILE_TIMING
    if (thread != NULL) {
        thread->timing_function_name = entry->function_name;
        thread->timing_variable_name = entry->variable_name;
        thread->timing_line = entry->line;
        thread->timing_kind = entry->kind;
        thread->timing_is_signed = entry->is_signed;
        thread->timing_identity_id = entry->identity_id;
        thread->timing_have_last = 1;
    }
#endif
    pthread_mutex_unlock(&profile_lock);
}

static int profile_function_matches(const char *expected_name, uint64_t expected_id,
                                    const char *actual_name, uint64_t actual_id) {
    return profile_named_identity_matches(expected_name, actual_name, expected_id, actual_id);
}

static void profile_record_function_entry(const char *function_name, uint32_t line,
                                           uint64_t function_id) {
    if (profile_fork_child_disabled) {
        return;
    }
    if (profile_mode == PROFILE_MODE_SAMPLES) {
        pthread_mutex_lock(&profile_lock);
        (void)profile_get_thread_locked();
        pthread_mutex_unlock(&profile_lock);
        if (profile_call_depth < PROFILE_CALL_STACK_CAPACITY) {
            profile_call_stack[profile_call_depth] = (profile_call_frame){
                .function_name = function_name,
                .function_id = function_id,
            };
            profile_call_depth = profile_saturating_increment_size(profile_call_depth);
        } else {
            profile_call_overflow_depth =
                profile_saturating_increment_size(profile_call_overflow_depth);
            profile_push_overflow_frame(function_name, line, function_id);
        }
        return;
    }
    const char *caller_name = NULL;
    uint64_t caller_id = PROFILE_ID_UNSET;
    profile_call_path *caller_path = NULL;
    int stack_overflowed = 0;
    if (profile_call_overflow_depth == 0 && profile_call_depth > 0) {
        caller_name = profile_call_stack[profile_call_depth - 1].function_name;
        caller_id = profile_call_stack[profile_call_depth - 1].function_id;
        caller_path = profile_call_stack[profile_call_depth - 1].path;
    }
    profile_record_call_edge(caller_name, function_name, caller_id, function_id);
    profile_call_path *path = NULL;
    if (profile_call_overflow_depth == 0 && profile_call_depth < PROFILE_CALL_STACK_CAPACITY) {
        path = profile_record_call_path(caller_path, function_name, function_id);
    }

#if ELISA_PROFILE_TIMING
    if (profile_call_depth < PROFILE_CALL_STACK_CAPACITY) {
        profile_call_stack[profile_call_depth] = (profile_call_frame){
            .function_name = function_name,
            .caller_name = caller_name,
            .path = path,
            .function_id = function_id,
            .caller_id = caller_id,
            .start_ns = profile_now_ns(),
            .child_ns = 0,
        };
        profile_call_depth = profile_saturating_increment_size(profile_call_depth);
    } else {
        profile_call_overflow_depth =
            profile_saturating_increment_size(profile_call_overflow_depth);
        profile_push_overflow_frame(function_name, line, function_id);
        stack_overflowed = 1;
    }
#else
    if (profile_call_depth < PROFILE_CALL_STACK_CAPACITY) {
        profile_call_stack[profile_call_depth] = (profile_call_frame){
            .function_name = function_name,
            .caller_name = caller_name,
            .path = path,
            .function_id = function_id,
            .caller_id = caller_id,
        };
        profile_call_depth = profile_saturating_increment_size(profile_call_depth);
    } else {
        profile_call_overflow_depth =
            profile_saturating_increment_size(profile_call_overflow_depth);
        profile_push_overflow_frame(function_name, line, function_id);
        stack_overflowed = 1;
    }
#endif
    profile_record(function_name, line, NULL, 0, PROFILE_KIND_FUNCTION, 0,
                   profile_call_depth, stack_overflowed, function_id);
}

static void profile_record_completed_function(const char *function_name, uint32_t line,
                                              uint64_t function_id) {
    pthread_mutex_lock(&profile_lock);
    profile_entry *entry = profile_find_locked(
        function_name, NULL, line, PROFILE_KIND_FUNCTION, 0, function_id);
    if (entry != NULL) {
        entry->completed_calls =
            profile_saturating_increment_u64(entry->completed_calls);
    }
    pthread_mutex_unlock(&profile_lock);
}

#if ELISA_PROFILE_TIMING
static void profile_record_timed_function_exit(const char *function_name, uint32_t line,
                                               uint64_t function_id) {
    if (profile_call_overflow_depth > 0) {
        profile_close_timing_cursor();
        --profile_call_overflow_depth;
        if (profile_call_overflow_untracked_depth > 0) {
            --profile_call_overflow_untracked_depth;
            return;
        }
        profile_overflow_frame *overflow_frame = profile_pop_overflow_frame();
        if (overflow_frame == NULL ||
            !profile_function_matches(overflow_frame->function_name,
                                      overflow_frame->function_id,
                                      function_name, function_id)) {
            free(overflow_frame);
            profile_call_depth = 0;
            profile_clear_overflow_frames();
            return;
        }
        profile_record_completed_function(overflow_frame->function_name, overflow_frame->line,
                                          overflow_frame->function_id);
        free(overflow_frame);
        return;
    }
    if (profile_call_depth == 0) {
        profile_invalidate_timing_cursor(profile_current_thread);
        return;
    }
    profile_call_frame *frame = &profile_call_stack[profile_call_depth - 1];
    if (!profile_function_matches(frame->function_name, frame->function_id,
                                  function_name, function_id)) {
        /* A missing/foreign exit must not poison every later frame. */
        profile_call_depth = 0;
        profile_call_overflow_depth = 0;
        profile_invalidate_timing_cursor(profile_current_thread);
        return;
    }
    const char *caller_name = frame->caller_name;
    uint64_t caller_id = frame->caller_id;
    uint64_t frame_function_id = frame->function_id;
    profile_call_path *path = frame->path;
    uint64_t now_ns = profile_now_ns();
    if (now_ns == 0) {
        profile_invalidate_timing_cursor(profile_current_thread);
    }
    uint64_t inclusive_ns = profile_elapsed_ns(frame->start_ns, now_ns);
    uint64_t self_ns = inclusive_ns >= frame->child_ns ? inclusive_ns - frame->child_ns : 0;
    --profile_call_depth;
    if (profile_call_depth > 0) {
        profile_call_frame *parent = &profile_call_stack[profile_call_depth - 1];
        parent->child_ns = profile_saturating_add(parent->child_ns, inclusive_ns);
    }

    pthread_mutex_lock(&profile_lock);
    /* Close the final location interval before the callee disappears. This
     * is essential for worker CPU timing: the worker's clock is unavailable
     * once the worker has returned, so the shutdown thread cannot recover its
     * final gap without this boundary flush. */
    profile_account_previous_locked(profile_current_thread, now_ns);
    profile_entry *entry = profile_find_locked(
        function_name, NULL, line, PROFILE_KIND_FUNCTION, 0, function_id);
    if (entry != NULL) {
        entry->completed_calls =
            profile_saturating_increment_u64(entry->completed_calls);
        entry->inclusive_ns = profile_saturating_add(entry->inclusive_ns, inclusive_ns);
        entry->self_ns = profile_saturating_add(entry->self_ns, self_ns);
    }
    profile_invalidate_timing_cursor(profile_current_thread);
    pthread_mutex_unlock(&profile_lock);
    profile_record_completed_call_path(path, self_ns);
    profile_record_completed_call_edge(caller_name, function_name, caller_id,
                                       frame_function_id, inclusive_ns);
}
#endif

#if !ELISA_PROFILE_TIMING
static void profile_record_untimed_function_exit(const char *function_name, uint32_t line,
                                                 uint64_t function_id) {
    if (profile_call_overflow_depth > 0) {
        --profile_call_overflow_depth;
        if (profile_call_overflow_untracked_depth > 0) {
            --profile_call_overflow_untracked_depth;
            return;
        }
        profile_overflow_frame *overflow_frame = profile_pop_overflow_frame();
        if (overflow_frame == NULL ||
            !profile_function_matches(overflow_frame->function_name,
                                      overflow_frame->function_id,
                                      function_name, function_id)) {
            free(overflow_frame);
            profile_call_depth = 0;
            profile_clear_overflow_frames();
            return;
        }
        profile_record_completed_function(overflow_frame->function_name, overflow_frame->line,
                                          overflow_frame->function_id);
        free(overflow_frame);
        return;
    }
    if (profile_call_depth == 0) {
        return;
    }
    profile_call_frame *frame = &profile_call_stack[profile_call_depth - 1];
    if (!profile_function_matches(frame->function_name, frame->function_id,
                                  function_name, function_id)) {
        profile_call_depth = 0;
        profile_call_overflow_depth = 0;
        return;
    }
    const char *caller_name = frame->caller_name;
    uint64_t caller_id = frame->caller_id;
    uint64_t frame_function_id = frame->function_id;
    profile_call_path *path = frame->path;
    --profile_call_depth;
    profile_record_completed_function(function_name, line, function_id);
    profile_record_completed_call_path(path, 0);
    profile_record_completed_call_edge(caller_name, function_name, caller_id,
                                       frame_function_id, 0);
}
#endif

static void profile_record_function_exit(const char *function_name, uint32_t line,
                                          uint64_t function_id) {
    if (profile_fork_child_disabled) {
        return;
    }
    if (profile_mode == PROFILE_MODE_SAMPLES) {
        if (profile_call_overflow_depth > 0) {
            --profile_call_overflow_depth;
            if (profile_call_overflow_untracked_depth > 0) {
                --profile_call_overflow_untracked_depth;
                return;
            }
            profile_overflow_frame *overflow_frame = profile_pop_overflow_frame();
            if (overflow_frame == NULL ||
                !profile_function_matches(overflow_frame->function_name,
                                          overflow_frame->function_id,
                                          function_name, function_id)) {
                free(overflow_frame);
                profile_call_depth = 0;
                profile_clear_overflow_frames();
                return;
            }
            free(overflow_frame);
            return;
        }
        if (profile_call_depth == 0) {
            return;
        }
        profile_call_frame *frame = &profile_call_stack[profile_call_depth - 1];
        if (!profile_function_matches(frame->function_name, frame->function_id,
                                      function_name, function_id)) {
            profile_call_depth = 0;
            profile_call_overflow_depth = 0;
            return;
        }
        --profile_call_depth;
        return;
    }
#if ELISA_PROFILE_TIMING
    profile_record_timed_function_exit(function_name, line, function_id);
#else
    profile_record_untimed_function_exit(function_name, line, function_id);
#endif
}

static void profile_record_value(const char *function_name, uint32_t line,
                                 const char *variable_name, uint64_t value,
                                 uint32_t is_signed, uint64_t identity_id) {
    profile_record(function_name, line, variable_name, value, PROFILE_KIND_VALUE,
                   is_signed != 0 ? 1 : 0, 0, 0, identity_id);
}

void elisa_trace_record(const char *function_name, uint32_t line) {
    profile_record(function_name, line, NULL, 0, PROFILE_KIND_STATEMENT, 0, 0, 0,
                   PROFILE_ID_UNSET);
}

void elisa_trace_record_id(const char *function_name, uint32_t line, uint64_t identity_id) {
    profile_record(function_name, line, NULL, 0, PROFILE_KIND_STATEMENT, 0, 0, 0,
                   identity_id);
}

void elisa_trace_function_entry(const char *function_name, uint32_t line) {
    profile_record_function_entry(function_name, line, PROFILE_ID_UNSET);
}

void elisa_trace_function_entry_id(const char *function_name, uint32_t line,
                                   uint64_t function_id) {
    profile_record_function_entry(function_name, line, function_id);
}

void elisa_trace_function_exit(const char *function_name, uint32_t line) {
    profile_record_function_exit(function_name, line, PROFILE_ID_UNSET);
}

void elisa_trace_function_exit_id(const char *function_name, uint32_t line,
                                  uint64_t function_id) {
    profile_record_function_exit(function_name, line, function_id);
}

void elisa_trace_record_value(const char *function_name, uint32_t line,
                              const char *variable_name, uint64_t value, uint32_t is_signed) {
    profile_record_value(function_name, line, variable_name, value, is_signed,
                         PROFILE_ID_UNSET);
}

void elisa_trace_record_value_id(const char *function_name, uint32_t line,
                                 const char *variable_name, uint64_t value,
                                 uint32_t is_signed, uint64_t identity_id) {
    profile_record_value(function_name, line, variable_name, value, is_signed, identity_id);
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

static int profile_call_edge_compare(const void *left_pointer, const void *right_pointer) {
    const profile_call_edge *left = *(const profile_call_edge *const *)left_pointer;
    const profile_call_edge *right = *(const profile_call_edge *const *)right_pointer;
    if (left->call_events != right->call_events) {
        return left->call_events < right->call_events ? 1 : -1;
    }
    int caller_order = strcmp(left->caller_name, right->caller_name);
    if (caller_order != 0) {
        return caller_order;
    }
    return strcmp(left->callee_name, right->callee_name);
}

static int profile_call_path_compare(const void *left_pointer, const void *right_pointer) {
    const profile_call_path *left = *(const profile_call_path *const *)left_pointer;
    const profile_call_path *right = *(const profile_call_path *const *)right_pointer;
#if ELISA_PROFILE_TIMING
    if (left->self_ns != right->self_ns) {
        return left->self_ns < right->self_ns ? 1 : -1;
    }
#endif
    if (left->call_events != right->call_events) {
        return left->call_events < right->call_events ? 1 : -1;
    }
    return strcmp(left->function_name, right->function_name);
}

static void profile_record_append_call_path(const profile_call_path *path) {
    const profile_call_path *nodes[PROFILE_CALL_STACK_CAPACITY];
    size_t depth = 0;
    for (const profile_call_path *node = path;
         node != NULL && depth < PROFILE_CALL_STACK_CAPACITY;
         node = node->parent) {
        nodes[depth++] = node;
    }
    for (size_t index = depth; index > 0; --index) {
        if (index != depth) {
            profile_record_append_char(';');
        }
        profile_record_append_field(nodes[index - 1]->function_name);
    }
}

static int profile_call_path_has_ids(const profile_call_path *path) {
    for (const profile_call_path *node = path;
         node != NULL;
         node = node->parent) {
        if (node->function_id != PROFILE_ID_UNSET) {
            return 1;
        }
    }
    return 0;
}

static void profile_record_append_call_path_ids(const profile_call_path *path) {
    const profile_call_path *nodes[PROFILE_CALL_STACK_CAPACITY];
    size_t depth = 0;
    for (const profile_call_path *node = path;
         node != NULL && depth < PROFILE_CALL_STACK_CAPACITY;
         node = node->parent) {
        nodes[depth++] = node;
    }
    for (size_t index = depth; index > 0; --index) {
        if (index != depth) {
            profile_record_append_char(';');
        }
        profile_record_append_uint64(nodes[index - 1]->function_id);
    }
}

static void profile_dump(void);

static void profile_dump_end(void) {
    profile_record_begin();
    profile_record_append_text("end\t");
    profile_record_append_uint64(PROFILE_PROTOCOL_VERSION);
    profile_record_emit();
}

static void profile_dump_trace_status(void) {
    profile_record_begin();
    profile_record_append_text("trace\t");
    profile_record_append_uint64(profile_event_trace_enabled ? 1U : 0U);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_event_trace_captured);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_event_trace_omitted);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_event_trace_limit);
    profile_record_emit();
}

static int profile_trace_event_compare(const void *left_pointer,
                                       const void *right_pointer) {
    const profile_trace_event *left = *(const profile_trace_event *const *)left_pointer;
    const profile_trace_event *right = *(const profile_trace_event *const *)right_pointer;
    if (left->sequence < right->sequence) {
        return -1;
    }
    if (left->sequence > right->sequence) {
        return 1;
    }
    return 0;
}

static void profile_dump_trace_event(const profile_trace_event *event) {
    profile_record_begin();
    profile_record_append_text("path\t");
    profile_record_append_uint64(event->sequence);
    profile_record_append_char('\t');
    profile_record_append_uint64(event->kind);
    profile_record_append_char('\t');
    profile_record_append_field(event->function_name);
    profile_record_append_char('\t');
    profile_record_append_uint64(event->line);
    profile_record_append_char('\t');
    profile_record_append_field(event->variable_name);
    profile_record_append_char('\t');
    profile_record_append_uint64(event->is_signed);
    profile_record_append_char('\t');
    if (event->is_signed) {
        profile_record_append_int64((int64_t)event->value);
    } else {
        profile_record_append_uint64(event->value);
    }
    if (event->identity_id != PROFILE_ID_UNSET) {
        profile_record_append_char('\t');
        profile_record_append_uint64(event->identity_id);
    } else {
        profile_record_append_char('\t');
        profile_record_append_uint64(PROFILE_ID_UNSET);
    }
    profile_record_append_char('\t');
    profile_record_append_uint64(event->thread_id);
    profile_record_append_char('\t');
    profile_record_append_uint64(event->timestamp_ns);
    profile_record_emit();
}

static void profile_dump_trace_records_per_thread(void) {
    for (const profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        for (size_t index = 0; index < thread->trace_size; ++index) {
            profile_dump_trace_event(&thread->trace_events[index]);
        }
    }
}

static void profile_dump_trace_records(void) {
    if (!profile_event_trace_enabled) {
        return;
    }
    size_t total = 0;
    int total_overflowed = 0;
    for (const profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        if (thread->trace_size > SIZE_MAX - total) {
            total_overflowed = 1;
            break;
        }
        total += thread->trace_size;
    }
    if (total == 0) {
        return;
    }
    if (total_overflowed) {
        profile_budget_exceeded = 1;
        profile_dump_trace_records_per_thread();
        return;
    }
    profile_trace_event **events = calloc(total, sizeof(*events));
    if (events == NULL) {
        profile_budget_exceeded = 1;
        profile_dump_trace_records_per_thread();
        return;
    }
    size_t event_index = 0;
    for (profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        for (size_t index = 0; index < thread->trace_size; ++index) {
            events[event_index++] = &thread->trace_events[index];
        }
    }
    qsort(events, event_index, sizeof(*events), profile_trace_event_compare);
    for (size_t index = 0; index < event_index; ++index) {
        profile_dump_trace_event(events[index]);
    }
    free(events);
}

static void profile_dump_thread_records(void) {
    if (!profile_thread_records_enabled) {
        return;
    }
    for (const profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        profile_record_begin();
        profile_record_append_text("thread\t");
        profile_record_append_uint64(thread->thread_id);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->event_count);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->location_dropped);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->call_edge_dropped);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->stack_dropped);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->trace_dropped);
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->bytes_dropped);
        profile_record_append_char('\t');
        if (thread->event_count == 0) {
            profile_record_append_char('-');
        } else {
            profile_record_append_uint64(thread->first_event);
        }
        profile_record_append_char('\t');
        if (thread->event_count == 0) {
            profile_record_append_char('-');
        } else {
            profile_record_append_uint64(thread->last_event);
        }
        profile_record_append_char('\t');
        profile_record_append_uint64(thread->lifecycle_ended
                                         ? PROFILE_THREAD_LIFECYCLE_ENDED
                                         : PROFILE_THREAD_LIFECYCLE_ACTIVE);
        profile_record_append_char('\t');
        if (thread->lifecycle_ended) {
            profile_record_append_uint64(thread->end_event);
        } else {
            profile_record_append_char('-');
        }
        profile_record_emit();
    }
}

static void profile_dump_allocation_records(void) {
    for (const profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        for (size_t index = 0; index < thread->allocation_size; ++index) {
            const profile_allocation_event *event =
                &thread->allocation_events[index];
            profile_record_begin();
            profile_record_append_text("allocation\t");
            profile_record_append_uint64(event->kind);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->address);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->size);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->old_address);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->old_size);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->arena);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->region);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->sequence);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->thread_id);
            profile_record_append_char('\t');
            profile_record_append_uint64(event->timestamp_ns);
            profile_record_emit();
        }
    }
}

static void profile_dump_metadata(size_t location_count) {
    profile_record_begin();
    profile_record_append_text("meta\t");
    profile_record_append_uint64(profile_event_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(location_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_dropped_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_max_call_depth);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_stack_overflow_entries);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_thread_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_location_limit);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_call_edge_limit);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_call_path_limit);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_budget_exceeded);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_call_edge_dropped_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_call_path_dropped_count);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_capture_byte_limit);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_capture_bytes_used);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_capture_bytes_dropped);
    if (profile_framing_enabled) {
        profile_record_append_char('\t');
        profile_record_append_uint64(profile_frame_dropped_count);
    }
    profile_record_append_char('\t');
    profile_record_append_uint64((uint64_t)profile_sample_count);
    profile_record_append_char('\t');
    profile_record_append_uint64((uint64_t)profile_sample_missed);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_sample_period_microseconds);
    profile_record_append_char('\t');
    profile_record_append_uint64((uint64_t)profile_sampling_setup_failed);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_allocation_dropped_count);
    profile_record_emit();
}

static void profile_dump_recent_path(void) {
    uint64_t start = profile_recent_position > PROFILE_RECENT_CAPACITY
                        ? profile_recent_position - PROFILE_RECENT_CAPACITY
                        : 0;
    for (uint64_t sequence = start; sequence < profile_recent_position; ++sequence) {
        const profile_recent_entry *entry =
            &profile_recent[sequence % PROFILE_RECENT_CAPACITY];
        profile_record_begin();
        profile_record_append_text("path\t");
        profile_record_append_uint64(sequence - start);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->kind);
        profile_record_append_char('\t');
        profile_record_append_field(entry->function_name);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->line);
        profile_record_append_char('\t');
        profile_record_append_field(entry->variable_name);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->is_signed);
        profile_record_append_char('\t');
        if (entry->is_signed) {
            profile_record_append_int64((int64_t)entry->value);
        } else {
            profile_record_append_uint64(entry->value);
        }
        if (entry->identity_id != PROFILE_ID_UNSET) {
            profile_record_append_char('\t');
            profile_record_append_uint64(entry->identity_id);
        }
        profile_record_emit();
    }
}

static void profile_dump_active_stack(void) {
    if (profile_call_depth == 0 && profile_call_overflow_depth == 0) {
        return;
    }
    profile_record_begin();
    profile_record_append_text("active\t");
    profile_record_append_uint64(profile_call_depth);
    profile_record_append_char('\t');
    profile_record_append_uint64(profile_call_overflow_depth);
    profile_record_append_char('\t');
    if (profile_call_depth == 0) {
        profile_record_append_char('-');
    } else {
        for (size_t index = 0; index < profile_call_depth; ++index) {
            if (index != 0) {
                profile_record_append_char(';');
            }
            profile_record_append_field(profile_call_stack[index].function_name);
        }
    }
    profile_record_emit();
}

static size_t profile_signal_append_literal(char *buffer, size_t offset,
                                            size_t capacity, const char *literal) {
    while (*literal != '\0' && offset < capacity) {
        buffer[offset++] = *literal++;
    }
    return offset;
}

static size_t profile_signal_append_uint(char *buffer, size_t offset,
                                         size_t capacity, uint64_t value) {
    char digits[PROFILE_DECIMAL_DIGITS];
    size_t count = 0;
    do {
        digits[count++] = (char)('0' + value % PROFILE_DECIMAL_BASE);
        value /= PROFILE_DECIMAL_BASE;
    } while (value != 0U && count < sizeof(digits));
    while (count > 0 && offset < capacity) {
        buffer[offset++] = digits[--count];
    }
    return offset;
}

static size_t profile_signal_append_field(char *buffer, size_t offset,
                                           size_t capacity, const char *value) {
    if (value == NULL) {
        return profile_signal_append_literal(buffer, offset, capacity, "-");
    }
    while (*value != '\0' && offset < capacity) {
        char output = (*value == '\t' || *value == '\n' || *value == '\r')
                          ? '_'
                          : *value;
        buffer[offset++] = output;
        ++value;
    }
    return offset;
}

static size_t profile_signal_append_active_stack(char *buffer, size_t offset,
                                                 size_t capacity) {
    offset = profile_signal_append_literal(buffer, offset, capacity, "\t");
    offset = profile_signal_append_uint(buffer, offset, capacity,
                                        (unsigned int)profile_call_depth);
    offset = profile_signal_append_literal(buffer, offset, capacity, "\t");
    offset = profile_signal_append_uint(buffer, offset, capacity,
                                        (unsigned int)profile_call_overflow_depth);
    offset = profile_signal_append_literal(buffer, offset, capacity, "\t");
    if (profile_call_depth == 0) {
        return profile_signal_append_literal(buffer, offset, capacity, "-");
    }
    for (size_t index = 0; index < profile_call_depth; ++index) {
        if (index != 0) {
            offset = profile_signal_append_literal(buffer, offset, capacity, ";");
        }
        offset = profile_signal_append_field(
            buffer, offset, capacity, profile_call_stack[index].function_name);
    }
    return offset;
}

static void profile_signal_increment(volatile sig_atomic_t *value) {
    if (*value < SIG_ATOMIC_MAX) {
        ++*value;
    }
}

static int profile_signal_write_all(const char *buffer, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t written = write(profile_output_fd, buffer + offset, length - offset);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            profile_output_write_failed = 1;
            return 0;
        }
        if (written == 0) {
            profile_output_write_failed = 1;
            return 0;
        }
        offset += (size_t)written;
    }
    return 1;
}

static void profile_write_sample_marker(void) {
    if (profile_fork_child_disabled || !profile_sampling_enabled || profile_frame_write_in_progress) {
        profile_signal_increment(&profile_sample_missed);
        return;
    }
    /* ITIMER_PROF may deliver SIGPROF to more than one busy worker. The marker
     * buffers and frame sequence are process-wide, so never let two handlers
     * interleave their construction or writes. A lock-free compiler atomic is
     * usable from a signal handler; a pthread mutex is not. Contenders become
     * explicit missed samples instead of corrupting the capture stream. */
    if (!__sync_bool_compare_and_swap(
            &profile_sample_handler_busy,
            PROFILE_SAMPLE_HANDLER_IDLE,
            PROFILE_SAMPLE_HANDLER_BUSY)) {
        profile_signal_increment(&profile_sample_missed);
        return;
    }
    char *buffer = profile_sample_marker_buffer;
    size_t payload_offset = 0;
    payload_offset = profile_signal_append_literal(
        buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES,
        "ELISA_PROFILE\t1\tsample\t");
    payload_offset = profile_signal_append_uint(
        buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES,
        (unsigned int)profile_sample_sequence);
    payload_offset = profile_signal_append_literal(
        buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES, "\t");
    const profile_thread_state *thread = profile_current_thread;
    if (thread == NULL) {
        payload_offset = profile_signal_append_literal(
            buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES, "-");
    } else {
        payload_offset = profile_signal_append_uint(
            buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES,
            (unsigned int)thread->thread_id);
    }
    payload_offset = profile_signal_append_active_stack(
        buffer, payload_offset, PROFILE_SAMPLE_MARKER_BUFFER_BYTES);
    if (payload_offset == 0 || payload_offset >= PROFILE_SAMPLE_MARKER_BUFFER_BYTES) {
        goto sample_missed;
    }
    uint64_t checksum = PROFILE_FNV_OFFSET_BASIS;
    for (size_t index = 0; index < payload_offset; ++index) {
        checksum = (checksum ^ (unsigned char)buffer[index]) * PROFILE_FNV_PRIME;
    }
    size_t header_offset = 0;
    header_offset = profile_signal_append_literal(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, "ELISA_PROFILE\t1\tframe\t");
    header_offset = profile_signal_append_uint(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, profile_frame_sequence);
    header_offset = profile_signal_append_literal(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, "\t");
    header_offset = profile_signal_append_uint(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, (uint64_t)payload_offset);
    header_offset = profile_signal_append_literal(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, "\t");
    header_offset = profile_signal_append_uint(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, checksum);
    header_offset = profile_signal_append_literal(
        profile_sample_frame_header, header_offset,
        PROFILE_SAMPLE_FRAME_HEADER_BYTES, "\t");
    if (header_offset == 0 || header_offset >= PROFILE_SAMPLE_FRAME_HEADER_BYTES ||
        !profile_signal_write_all(profile_sample_frame_header, header_offset) ||
        !profile_signal_write_all(buffer, payload_offset) ||
        !profile_signal_write_all("\n", 1)) {
        goto sample_missed;
    }
    profile_signal_increment(&profile_sample_count);
    profile_signal_increment(&profile_sample_sequence);
    profile_frame_sequence = profile_saturating_increment_u64(profile_frame_sequence);
    profile_sample_handler_busy = PROFILE_SAMPLE_HANDLER_IDLE;
    return;

sample_missed:
    profile_signal_increment(&profile_sample_missed);
    profile_sample_handler_busy = PROFILE_SAMPLE_HANDLER_IDLE;
}

static void profile_sampling_handler(int signal_number) {
    (void)signal_number;
    profile_write_sample_marker();
}

static int profile_start_sampling(uint64_t period_microseconds) {
#if defined(__APPLE__) || defined(__linux__)
    if (period_microseconds < PROFILE_MIN_SAMPLE_PERIOD_MICROSECONDS ||
        period_microseconds > PROFILE_MAX_SAMPLE_PERIOD_MICROSECONDS) {
        profile_sampling_setup_failed = 1;
        return 0;
    }
    struct sigaction sample_action = {0};
    sample_action.sa_handler = profile_sampling_handler;
    if (sigemptyset(&sample_action.sa_mask) != 0 ||
        sigaction(PROFILE_SAMPLE_SIGNAL, &sample_action,
                  &profile_previous_sample_action) != 0) {
        profile_sampling_setup_failed = 1;
        return 0;
    }
    struct itimerval timer = {0};
    timer.it_value.tv_sec =
        (time_t)(period_microseconds / PROFILE_MICROSECONDS_PER_SECOND);
    timer.it_value.tv_usec =
        (suseconds_t)(period_microseconds % PROFILE_MICROSECONDS_PER_SECOND);
    timer.it_interval = timer.it_value;
    profile_sample_period_microseconds = period_microseconds;
    profile_sampling_enabled = 1;
    if (setitimer(ITIMER_PROF, &timer, NULL) != 0) {
        profile_sampling_enabled = 0;
        (void)sigaction(PROFILE_SAMPLE_SIGNAL,
                        &profile_previous_sample_action, NULL);
        profile_sampling_setup_failed = 1;
        return 0;
    }
    profile_previous_sample_action_valid = 1;
    return 1;
#else
    (void)period_microseconds;
    profile_sampling_setup_failed = 1;
    return 0;
#endif
}

static void profile_stop_sampling(void) {
#if defined(__APPLE__) || defined(__linux__)
    if (profile_sampling_enabled) {
        struct itimerval timer = {0};
        (void)setitimer(ITIMER_PROF, &timer, NULL);
    }
#endif
    profile_sampling_enabled = 0;
#if defined(__APPLE__) || defined(__linux__)
    if (profile_previous_sample_action_valid) {
        (void)sigaction(PROFILE_SAMPLE_SIGNAL,
                        &profile_previous_sample_action, NULL);
        profile_previous_sample_action_valid = 0;
    }
#endif
}

static void profile_write_crash_marker(int signal_number) {
    char *buffer = profile_signal_marker_buffer;
    size_t offset = 0;
    if (profile_frame_write_in_progress) {
        offset = profile_signal_append_literal(buffer, offset, PROFILE_SIGNAL_MARKER_BUFFER_BYTES, "\n");
    }
    offset = profile_signal_append_literal(
        buffer, offset, PROFILE_SIGNAL_MARKER_BUFFER_BYTES, "ELISA_PROFILE\t1\tcrash\t");
    offset = profile_signal_append_uint(
        buffer, offset, PROFILE_SIGNAL_MARKER_BUFFER_BYTES, (unsigned int)signal_number);
    offset = profile_signal_append_active_stack(buffer, offset, PROFILE_SIGNAL_MARKER_BUFFER_BYTES);
    offset = profile_signal_append_literal(buffer, offset, PROFILE_SIGNAL_MARKER_BUFFER_BYTES, "\n");
    (void)profile_signal_write_all(buffer, offset);
}

static int profile_crash_signal_index(int signal_number) {
#if defined(__APPLE__) || defined(__linux__)
    for (int index = 0; index < PROFILE_CRASH_SIGNAL_COUNT; ++index) {
        if (profile_crash_signals[index] == signal_number) {
            return index;
        }
    }
#else
    (void)signal_number;
#endif
    return -1;
}

static void profile_crash_handler(int signal_number) {
    int action_index = profile_crash_signal_index(signal_number);
#if defined(__APPLE__) || defined(__linux__)
    struct sigaction previous_action = {0};
    if (action_index >= 0 &&
        profile_previous_crash_action_valid[action_index]) {
        previous_action = profile_previous_crash_actions[action_index];
    } else {
        previous_action.sa_handler = SIG_DFL;
    }
    if (previous_action.sa_handler == SIG_IGN) {
        if (action_index >= 0) {
            (void)sigaction(signal_number, &previous_action, NULL);
        }
        return;
    }
#endif
    if (!profile_crash_dumped) {
        profile_crash_dumped = 1;
        profile_write_crash_marker(signal_number);
    }
#if defined(__APPLE__) || defined(__linux__)
    (void)sigaction(signal_number, &previous_action, NULL);
#else
    (void)signal(signal_number, SIG_DFL);
#endif
    (void)raise(signal_number);
#if defined(__APPLE__) || defined(__linux__)
    if (previous_action.sa_handler == SIG_DFL) {
        _exit(PROFILE_SIGNAL_EXIT_BASE + signal_number);
    }
#else
    _exit(PROFILE_SIGNAL_EXIT_BASE + signal_number);
#endif
}

static void profile_install_crash_handlers(void) {
#if defined(__APPLE__) || defined(__linux__)
    for (int index = 0; index < PROFILE_CRASH_SIGNAL_COUNT; ++index) {
        struct sigaction action = {0};
        if (sigemptyset(&action.sa_mask) != 0) {
            continue;
        }
        action.sa_handler = profile_crash_handler;
        if (sigaction(profile_crash_signals[index], &action,
                      &profile_previous_crash_actions[index]) == 0) {
            profile_previous_crash_action_valid[index] = 1;
        }
    }
#else
    (void)signal(SIGABRT, profile_crash_handler);
    (void)signal(SIGFPE, profile_crash_handler);
    (void)signal(SIGILL, profile_crash_handler);
    (void)signal(SIGSEGV, profile_crash_handler);
    (void)signal(SIGBUS, profile_crash_handler);
    (void)signal(SIGTERM, profile_crash_handler);
    (void)signal(SIGINT, profile_crash_handler);
#endif
}

static void profile_dump_body(void) {
    if (profile_dumped) {
        return;
    }
#if ELISA_PROFILE_TIMING
    /* A worker can finish after its final trace event. Keep every thread's
     * cursor alive so its trailing interval is attributed before shutdown. */
    for (profile_thread_state *thread = profile_threads;
         thread != NULL;
         thread = thread->next) {
        if (!thread->lifecycle_ended) {
            profile_account_previous_locked(thread, profile_now_ns_for_thread(thread));
        }
    }
#endif
    profile_dumped = 1;
    size_t count = profile_size;
    profile_entry **entries = calloc(count == 0 ? 1 : count, sizeof(*entries));
    if (entries == NULL) {
        profile_dropped_count =
            profile_saturating_increment_u64(profile_dropped_count);
        profile_dump_metadata(0);
        profile_dump_trace_status();
        profile_dump_trace_records();
        profile_dump_thread_records();
        profile_dump_allocation_records();
        if (!profile_event_trace_enabled &&
            (profile_crash_dumped || profile_recent_path_enabled)) {
            profile_dump_recent_path();
        }
        if (profile_crash_dumped) {
            profile_dump_active_stack();
        }
        profile_dump_end();
        return;
    }

    size_t output_count = 0;
    for (size_t index = 0; index < profile_capacity; ++index) {
        if (profile_table[index].function_name != NULL) {
            if (output_count >= count) {
                profile_budget_exceeded = 1;
                profile_dropped_count = profile_saturating_add_u64(
                    profile_dropped_count, 1);
                break;
            }
            entries[output_count++] = &profile_table[index];
        }
    }
    qsort(entries, output_count, sizeof(*entries), profile_entry_compare);
    profile_dump_metadata(output_count);
    profile_dump_trace_status();
    profile_dump_trace_records();
    profile_dump_thread_records();
    profile_dump_allocation_records();
    for (size_t index = 0; index < output_count; ++index) {
        const profile_entry *entry = entries[index];
        profile_record_begin();
        profile_record_append_text("location\t");
        profile_record_append_uint64(entry->kind);
        profile_record_append_char('\t');
        profile_record_append_field(entry->function_name);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->line);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->count);
        profile_record_append_char('\t');
        profile_record_append_field(entry->variable_name);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->is_signed);
        profile_record_append_char('\t');
        if (entry->kind == PROFILE_KIND_FUNCTION) {
            profile_record_append_uint64(entry->inclusive_ns);
            profile_record_append_char('\t');
            profile_record_append_uint64(entry->self_ns);
            profile_record_append_char('\t');
            profile_record_append_uint64(entry->completed_calls);
        } else if (entry->is_signed) {
            profile_record_append_int64((int64_t)entry->minimum);
            profile_record_append_char('\t');
            profile_record_append_int64((int64_t)entry->maximum);
            profile_record_append_char('\t');
            if (entry->signed_sum > (__int128_t)INT64_MAX ||
                entry->signed_sum < (__int128_t)INT64_MIN) {
                profile_record_append_text("overflow");
            } else {
                profile_record_append_int64((int64_t)entry->signed_sum);
            }
        } else {
            profile_record_append_uint64(entry->minimum);
            profile_record_append_char('\t');
            profile_record_append_uint64(entry->maximum);
            profile_record_append_char('\t');
            if (entry->sum > UINT64_MAX) {
                profile_record_append_text("overflow");
            } else {
                profile_record_append_uint64((uint64_t)entry->sum);
            }
        }
        profile_record_append_char('\t');
        if (entry->is_signed) {
            profile_record_append_int64((int64_t)entry->last);
        } else {
            profile_record_append_uint64(entry->last);
        }
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->interval_ns);
        profile_record_append_char('\t');
        profile_record_append_uint64(entry->max_interval_ns);
        if (entry->identity_id != PROFILE_ID_UNSET) {
            profile_record_append_char('\t');
            profile_record_append_uint64(entry->identity_id);
        }
        profile_record_emit();
    }
    profile_call_edge **call_edges = calloc(
        profile_call_edge_size == 0 ? 1 : profile_call_edge_size, sizeof(*call_edges));
    if (call_edges != NULL) {
        size_t call_output_count = 0;
        for (size_t index = 0; index < profile_call_edge_capacity; ++index) {
            if (profile_call_edges[index].caller_name != NULL) {
                if (call_output_count >= profile_call_edge_size) {
                    profile_budget_exceeded = 1;
                    profile_call_edge_dropped_count = profile_saturating_add_u64(
                        profile_call_edge_dropped_count, 1);
                    break;
                }
                call_edges[call_output_count++] = &profile_call_edges[index];
            }
        }
        qsort(call_edges, call_output_count, sizeof(*call_edges), profile_call_edge_compare);
        for (size_t index = 0; index < call_output_count; ++index) {
            const profile_call_edge *edge = call_edges[index];
            profile_record_begin();
            profile_record_append_text("call\t");
            profile_record_append_field(edge->caller_name);
            profile_record_append_char('\t');
            profile_record_append_field(edge->callee_name);
            profile_record_append_char('\t');
            profile_record_append_uint64(edge->call_events);
            profile_record_append_char('\t');
            profile_record_append_uint64(edge->completed_calls);
            profile_record_append_char('\t');
            profile_record_append_uint64(edge->inclusive_ns);
            if (edge->caller_id != PROFILE_ID_UNSET ||
                edge->callee_id != PROFILE_ID_UNSET) {
                profile_record_append_char('\t');
                profile_record_append_uint64(edge->caller_id);
                profile_record_append_char('\t');
                profile_record_append_uint64(edge->callee_id);
            }
            profile_record_emit();
        }
        free(call_edges);
    }
    profile_call_path **paths = calloc(
        profile_call_path_size == 0 ? 1 : profile_call_path_size, sizeof(*paths));
    if (paths != NULL) {
        size_t path_output_count = 0;
        for (size_t index = 0; index < profile_call_path_capacity; ++index) {
            if (profile_call_paths[index] != NULL) {
                if (path_output_count >= profile_call_path_size) {
                    profile_budget_exceeded = 1;
                    profile_call_path_dropped_count = profile_saturating_add_u64(
                        profile_call_path_dropped_count, 1);
                    break;
                }
                paths[path_output_count++] = profile_call_paths[index];
            }
        }
        qsort(paths, path_output_count, sizeof(*paths), profile_call_path_compare);
        for (size_t index = 0; index < path_output_count; ++index) {
            const profile_call_path *path = paths[index];
            profile_record_begin();
            profile_record_append_text("stack\t");
            profile_record_append_call_path(path);
            profile_record_append_char('\t');
            profile_record_append_uint64(path->call_events);
            profile_record_append_char('\t');
            profile_record_append_uint64(path->completed_calls);
            profile_record_append_char('\t');
            profile_record_append_uint64(path->self_ns);
            if (profile_call_path_has_ids(path)) {
                profile_record_append_char('\t');
                profile_record_append_call_path_ids(path);
            }
            profile_record_emit();
        }
        free(paths);
    }
    free(entries);
    if (!profile_event_trace_enabled &&
        (profile_crash_dumped || profile_recent_path_enabled)) {
        profile_dump_recent_path();
    }
    if (profile_crash_dumped) {
        profile_dump_active_stack();
    }
    profile_dump_end();
}

static void profile_dump(void) {
    if (profile_fork_child_disabled) {
        return;
    }
    profile_stop_sampling();
    pthread_mutex_lock(&profile_lock);
    profile_dump_body();
    pthread_mutex_unlock(&profile_lock);
    profile_write_status();
}

#ifndef ELISA_PROFILE_NO_MAIN
/* The Elisa entry point may be the legacy no-argument form or the argv-aware
 * form. The generated legacy entry ignores the extra platform arguments at
 * this ABI boundary; the explicit prototype keeps the strict collector build
 * warning-free while argv-aware targets receive the real values. */
extern int64_t elisa_profile_target_main(int64_t argc, void *argv);

static uint64_t profile_read_uint64_environment(const char *name) {
    const char *text = getenv(name);
    if (text == NULL || *text == '\0' || *text < '0' || *text > '9') {
        return 0;
    }
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0' || value > UINT64_MAX) {
        return 0;
    }
    return (uint64_t)value;
}

static uint64_t profile_read_sample_period_from_mode(const char *mode) {
    const size_t prefix_length = sizeof(PROFILE_SAMPLE_MODE_PREFIX) - 1;
    if (mode == NULL || strncmp(mode, PROFILE_SAMPLE_MODE_PREFIX, prefix_length) != 0) {
        return 0;
    }
    const char *text = mode + prefix_length;
    if (*text == '\0') {
        return 0;
    }
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0' || value > UINT64_MAX) {
        return 0;
    }
    if (value < PROFILE_MIN_SAMPLE_PERIOD_MICROSECONDS ||
        value > PROFILE_MAX_SAMPLE_PERIOD_MICROSECONDS) {
        return 0;
    }
    return (uint64_t)value;
}

static uint64_t profile_read_limit_environment(const char *name, uint64_t fallback) {
    const char *text = getenv(name);
    if (text == NULL || *text == '\0') {
        return fallback;
    }
    for (const char *cursor = text; *cursor != '\0'; ++cursor) {
        if (*cursor < '0' || *cursor > '9') {
            return fallback;
        }
    }
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0' || value > UINT64_MAX) {
        return fallback;
    }
    return (uint64_t)value;
}

int main(int argc, char **argv) {
    const char *recent_path = getenv(PROFILE_RECENT_PATH_ENVIRONMENT);
    profile_recent_path_enabled = recent_path != NULL && strcmp(recent_path, "1") == 0;
    const char *mode = getenv(PROFILE_MODE_ENVIRONMENT);
    if (mode != NULL) {
        if (strcmp(mode, "functions") == 0) {
            profile_mode = PROFILE_MODE_FUNCTIONS;
        } else if (strcmp(mode, "statements") == 0) {
            profile_mode = PROFILE_MODE_STATEMENTS;
        } else if (strcmp(mode, "values") == 0) {
            profile_mode = PROFILE_MODE_VALUES;
        } else if (strcmp(mode, "diagnostic") == 0) {
            profile_mode = PROFILE_MODE_DIAGNOSTIC;
        } else if (strcmp(mode, "sample") == 0 || strcmp(mode, "sampling") == 0 ||
                   strncmp(mode, PROFILE_SAMPLE_MODE_PREFIX, sizeof(PROFILE_SAMPLE_MODE_PREFIX) - 1) == 0) {
            profile_mode = PROFILE_MODE_SAMPLES;
        }
    }
    uint64_t sample_period = PROFILE_DEFAULT_SAMPLE_PERIOD_MICROSECONDS;
    if (profile_mode == PROFILE_MODE_SAMPLES) {
        sample_period = profile_read_limit_environment(
            PROFILE_SAMPLE_PERIOD_ENVIRONMENT,
            PROFILE_DEFAULT_SAMPLE_PERIOD_MICROSECONDS);
        uint64_t mode_sample_period = profile_read_sample_period_from_mode(mode);
        if (mode_sample_period != 0) {
            sample_period = mode_sample_period;
        }
    }
    const char *event_trace = getenv(PROFILE_EVENT_TRACE_ENVIRONMENT);
    profile_event_trace_enabled = event_trace != NULL && strcmp(event_trace, "1") == 0;
    const char *thread_records = getenv(PROFILE_THREAD_RECORDS_ENVIRONMENT);
    profile_thread_records_enabled = thread_records != NULL && strcmp(thread_records, "1") == 0;
    profile_event_trace_limit = profile_read_uint64_environment(
        PROFILE_EVENT_TRACE_LIMIT_ENVIRONMENT);
    profile_location_limit = profile_read_limit_environment(
        PROFILE_MAX_LOCATIONS_ENVIRONMENT, PROFILE_DEFAULT_LOCATION_LIMIT);
    profile_call_edge_limit = profile_read_limit_environment(
        PROFILE_MAX_CALL_EDGES_ENVIRONMENT, PROFILE_DEFAULT_CALL_EDGE_LIMIT);
    profile_call_path_limit = profile_read_limit_environment(
        PROFILE_MAX_STACKS_ENVIRONMENT, PROFILE_DEFAULT_CALL_PATH_LIMIT);
    profile_capture_byte_limit = profile_read_limit_environment(
        PROFILE_MAX_CAPTURE_BYTES_ENVIRONMENT, PROFILE_DEFAULT_CAPTURE_BYTE_LIMIT);
    (void)profile_output();
    profile_register_fork_policy();
    profile_install_crash_handlers();
    if (profile_mode == PROFILE_MODE_SAMPLES) {
        if (!profile_start_sampling(sample_period)) {
            profile_sampling_setup_failed = 1;
        }
    }
    atexit(profile_dump);
    int64_t result = elisa_profile_target_main((int64_t)argc, argv);
    profile_dump();
    /* The native toolchain may link this collector without a CRT startup
     * object, so returning from main would return into the dyld entry frame.
     * Exit explicitly after the final dump to make the collector's ABI
     * independent of the host linker's startup policy. */
    _exit((int)(result & PROFILE_EXIT_CODE_MASK));
}
#endif

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
void *va_copy(void *source) {
    return source;
}
void va_end(void *argument) { (void)argument; }
