#include <stdint.h>
#include <time.h>

extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);
extern void elisa_trace_record(const char *function_name, uint32_t line);

enum { EXPECTED_ENTRY_CLOCK_READS = 1 };
static unsigned clock_reads;

/* Make every collector clock read fail. The runtime must report zero timing,
 * never interpret a missing timestamp as an epoch-relative duration. */
int clock_gettime(clockid_t clock_id, struct timespec *timestamp) {
    (void)clock_id;
    (void)timestamp;
    ++clock_reads;
    return -1;
}

int64_t elisa_profile_target_main(void) {
    unsigned before_entry = clock_reads;
    elisa_trace_function_entry("main", 1);
    if (clock_reads - before_entry != EXPECTED_ENTRY_CLOCK_READS) {
        return 1;
    }
    elisa_trace_record("main", 2);
    elisa_trace_function_exit("main", 1);
    return 0;
}
