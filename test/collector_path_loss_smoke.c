#include <stdint.h>

void elisa_trace_function_entry(const char *, uint32_t);
void elisa_trace_function_exit(const char *, uint32_t);

enum { ROOT_LINE = 1, CHILD_LINE = 2 };

int64_t elisa_profile_target_main(void) {
    elisa_trace_function_entry("root", ROOT_LINE);
    elisa_trace_function_entry("child", CHILD_LINE);
    /* With one retained path, this is root;child;root, not another root. */
    elisa_trace_function_entry("root", ROOT_LINE);
    elisa_trace_function_exit("root", ROOT_LINE);
    elisa_trace_function_exit("child", CHILD_LINE);
    elisa_trace_function_exit("root", ROOT_LINE);
    /* A genuine later root must still update the retained path. */
    elisa_trace_function_entry("root", ROOT_LINE);
    elisa_trace_function_exit("root", ROOT_LINE);
    return 0;
}
