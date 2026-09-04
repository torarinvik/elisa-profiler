#include <stdint.h>
#include <stdlib.h>
#include <string.h>

extern void elisa_trace_function_entry(const char *function_name, uint32_t line);
extern void elisa_trace_function_exit(const char *function_name, uint32_t line);

enum { OVERFLOW_DEPTH = 1025 };

int64_t elisa_profile_target_main(void) {
    const char *mode = getenv("ELISA_OVERFLOW_MODE");
    int mismatch = mode != NULL && strcmp(mode, "mismatch") == 0;
    for (int depth = 0; depth < OVERFLOW_DEPTH; ++depth) {
        elisa_trace_function_entry("deep", 1);
    }
    if (mismatch) {
        elisa_trace_function_exit("foreign", 1);
    } else {
        elisa_trace_function_exit("deep", 1);
    }
    for (int depth = 1; depth < OVERFLOW_DEPTH; ++depth) {
        elisa_trace_function_exit("deep", 1);
    }
    return 0;
}
