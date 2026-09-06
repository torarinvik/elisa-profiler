#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifndef BENCHMARK_VARIANT
#define BENCHMARK_VARIANT -1
#endif

extern void elisa_trace_record(const char *function_name, uint32_t line);
extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);
extern void elisa_trace_record_value(const char *function_name, uint32_t line,
                                     const char *variable_name, uint64_t value,
                                     uint32_t is_signed);

enum {
    BENCHMARK_DEFAULT_ITERATIONS = 100000,
    BENCHMARK_DEFAULT_REPETITIONS = 5,
    BENCHMARK_LINE = 17,
    BENCHMARK_UNSIGNED_VALUE = 0,
};

static const int64_t BENCHMARK_NANOS_PER_SECOND = 1000000000;
static const char BENCHMARK_FUNCTION[] = "benchmark_function";
static const char BENCHMARK_VARIABLE[] = "benchmark_value";

typedef enum {
    BENCHMARK_EMPTY,
    BENCHMARK_COUNT,
    BENCHMARK_FUNCTION_TIMING,
    BENCHMARK_STATEMENT_TIMING,
    BENCHMARK_SCALAR,
    BENCHMARK_FULL,
} benchmark_variant;

typedef struct {
    const char *name;
    uint64_t callbacks_per_iteration;
    benchmark_variant variant;
} benchmark_definition;

static const benchmark_definition BENCHMARKS[] = {
    {"empty", 1, BENCHMARK_EMPTY},
    {"count-only", 1, BENCHMARK_COUNT},
    {"function-timing", 2, BENCHMARK_FUNCTION_TIMING},
    {"statement-timing", 1, BENCHMARK_STATEMENT_TIMING},
    {"scalar", 1, BENCHMARK_SCALAR},
    {"full-trace", 4, BENCHMARK_FULL},
};

static uint64_t benchmark_read_positive_environment(const char *name,
                                                     uint64_t fallback) {
    const char *text = getenv(name);
    if (text == NULL || *text == '\0') {
        return fallback;
    }
    char *end = NULL;
    errno = 0;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0' || value == 0) {
        return fallback;
    }
    return (uint64_t)value;
}

static uint64_t benchmark_elapsed_nanoseconds(struct timespec start,
                                               struct timespec finish) {
    if (finish.tv_nsec < start.tv_nsec) {
        finish.tv_sec -= 1;
        finish.tv_nsec += BENCHMARK_NANOS_PER_SECOND;
    }
    return (uint64_t)(finish.tv_sec - start.tv_sec) *
               (uint64_t)BENCHMARK_NANOS_PER_SECOND +
           (uint64_t)(finish.tv_nsec - start.tv_nsec);
}

__attribute__((noinline)) static void benchmark_empty_hook(void) {
    __asm__ volatile("" ::: "memory");
}

static void benchmark_invoke(benchmark_variant variant, uint64_t iteration) {
    switch (variant) {
    case BENCHMARK_EMPTY:
        benchmark_empty_hook();
        break;
    case BENCHMARK_COUNT:
        elisa_trace_record(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        break;
    case BENCHMARK_FUNCTION_TIMING:
        elisa_trace_function_entry(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        elisa_trace_function_exit(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        break;
    case BENCHMARK_STATEMENT_TIMING:
        elisa_trace_record(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        break;
    case BENCHMARK_SCALAR:
        elisa_trace_record_value(BENCHMARK_FUNCTION, BENCHMARK_LINE,
                                 BENCHMARK_VARIABLE, iteration,
                                 BENCHMARK_UNSIGNED_VALUE);
        break;
    case BENCHMARK_FULL:
        elisa_trace_function_entry(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        elisa_trace_record(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        elisa_trace_record_value(BENCHMARK_FUNCTION, BENCHMARK_LINE,
                                 BENCHMARK_VARIABLE, iteration,
                                 BENCHMARK_UNSIGNED_VALUE);
        elisa_trace_function_exit(BENCHMARK_FUNCTION, BENCHMARK_LINE);
        break;
    }
}

int64_t elisa_profile_target_main(int64_t argc, void *argv) {
    (void)argc;
    (void)argv;
    (void)setvbuf(stdout, NULL, _IONBF, 0);
    const uint64_t iterations = benchmark_read_positive_environment(
        "ELISA_CALLBACK_BENCHMARK_ITERATIONS", BENCHMARK_DEFAULT_ITERATIONS);
    const uint64_t repetitions = benchmark_read_positive_environment(
        "ELISA_CALLBACK_BENCHMARK_REPETITIONS", BENCHMARK_DEFAULT_REPETITIONS);
    const size_t benchmark_count = sizeof(BENCHMARKS) / sizeof(BENCHMARKS[0]);

#if BENCHMARK_VARIANT >= 0
    const size_t first_benchmark = BENCHMARK_VARIANT;
    const size_t last_benchmark = first_benchmark + 1;
#else
    const size_t first_benchmark = 0;
    const size_t last_benchmark = benchmark_count;
#endif
    for (size_t benchmark_index = first_benchmark; benchmark_index < last_benchmark;
         ++benchmark_index) {
        const benchmark_definition *definition = &BENCHMARKS[benchmark_index];
        for (uint64_t repetition = 0; repetition < repetitions; ++repetition) {
            struct timespec start;
            struct timespec finish;
            if (clock_gettime(CLOCK_MONOTONIC, &start) != 0) {
                return 1;
            }
            for (uint64_t iteration = 0; iteration < iterations; ++iteration) {
                benchmark_invoke(definition->variant, iteration);
            }
            if (clock_gettime(CLOCK_MONOTONIC, &finish) != 0) {
                return 1;
            }
            const uint64_t callbacks = iterations * definition->callbacks_per_iteration;
            const uint64_t elapsed = benchmark_elapsed_nanoseconds(start, finish);
            const uint64_t nanoseconds_per_callback =
                callbacks == 0 ? 0 : elapsed / callbacks;
            printf("%s\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",
                   definition->name, repetition, callbacks, elapsed,
                   nanoseconds_per_callback);
        }
    }
    return 0;
}
