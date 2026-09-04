#include <stdint.h>
#include <time.h>

extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);
extern void elisa_trace_record(const char *function_name, uint32_t line);

int64_t elisa_profile_target_main(void) {
    elisa_trace_function_entry("main", 1);
    elisa_trace_record("main", 2);
    /* Simulate a foreign/missing exit from generated instrumentation. */
    elisa_trace_function_exit("foreign", 3);
    struct timespec delay = {0, 20 * 1000 * 1000};
    (void)nanosleep(&delay, NULL);
    elisa_trace_record("main", 4);
    elisa_trace_function_exit("main", 1);
    return 0;
}
