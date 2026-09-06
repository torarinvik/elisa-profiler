#include <stdint.h>

void elisa_trace_function_entry(const char *function_name, uint32_t line);
void elisa_trace_function_exit(const char *function_name, uint32_t line);
void elisa_trace_record(const char *function_name, uint32_t line);
void elisa_trace_record_value(const char *function_name, uint32_t line,
                              const char *variable_name, uint64_t value,
                              uint32_t is_signed);

static const char main_name_a[] = "main";
static const char main_name_b[] = {'m', 'a', 'i', 'n', '\0'};
static const char worker_name_a[] = "worker";
static const char worker_name_b[] = {'w', 'o', 'r', 'k', 'e', 'r', '\0'};
static const char value_name_a[] = "value";
static const char value_name_b[] = {'v', 'a', 'l', 'u', 'e', '\0'};

int64_t elisa_profile_target_main(void) {
    elisa_trace_function_entry(main_name_a, 1);
    elisa_trace_record(main_name_a, 2);
    elisa_trace_record(main_name_b, 2);
    elisa_trace_record_value(main_name_a, 4, value_name_a, 1, 0);
    elisa_trace_record_value(main_name_b, 4, value_name_b, 2, 0);
    elisa_trace_record_value(main_name_a, 4, value_name_a, UINT64_MAX, 0);
    elisa_trace_function_entry(worker_name_a, 3);
    elisa_trace_function_exit(worker_name_b, 3);
    elisa_trace_function_exit(main_name_b, 1);
    return 0;
}
