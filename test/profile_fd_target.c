#include <stdint.h>
#include <stdio.h>

extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);
extern void elisa_trace_record(const char *function_name, uint32_t line);

int64_t elisa_profile_target_main(void) {
    /* This must remain ordinary target stderr, not collector protocol. */
    fputs("ELISA_PROFILE\t1\tmeta\tspoofed\n", stderr);
    fputs("target diagnostic\n", stderr);
    elisa_trace_function_entry("main", 1);
    elisa_trace_record("main", 2);
    elisa_trace_function_exit("main", 1);
    return 0;
}
