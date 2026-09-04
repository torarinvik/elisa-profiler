#include <stdint.h>
#include <pthread.h>
#include <stdio.h>

extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);
extern void elisa_trace_record(const char *function_name, uint32_t line);

enum { worker_count = 32 };

static void *profile_worker(void *argument) {
    (void)argument;
    elisa_trace_function_entry("worker", 10);
    elisa_trace_record("worker", 11);
    elisa_trace_function_exit("worker", 10);
    return NULL;
}

int64_t elisa_profile_target_main(void) {
    /* This must remain ordinary target stderr, not collector protocol. */
    fputs("ELISA_PROFILE\t1\tmeta\tspoofed\n", stderr);
    fputs("target diagnostic\n", stderr);
    /* Start tracing from multiple workers so collector transport initialization
     * is exercised under genuine first-event contention. */
    pthread_t workers[worker_count];
    for (int index = 0; index < worker_count; ++index) {
        if (pthread_create(&workers[index], NULL, profile_worker, NULL) != 0) {
            return 2;
        }
    }
    for (int index = 0; index < worker_count; ++index) {
        if (pthread_join(workers[index], NULL) != 0) {
            return 3;
        }
    }
    return 0;
}
