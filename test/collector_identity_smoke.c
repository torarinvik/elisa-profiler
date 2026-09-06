#include <stdint.h>

void elisa_trace_function_entry_id(const char *function_name, uint32_t line,
                                   uint64_t function_id);
void elisa_trace_function_exit_id(const char *function_name, uint32_t line,
                                  uint64_t function_id);
void elisa_trace_record_id(const char *function_name, uint32_t line,
                           uint64_t identity_id);
void elisa_trace_record_value_id(const char *function_name, uint32_t line,
                                 const char *variable_name, uint64_t value,
                                 uint32_t is_signed, uint64_t identity_id);

int64_t elisa_profile_target_main(void) {
    elisa_trace_function_entry_id("identified_main", 10, UINT64_C(1001));
    elisa_trace_record_id("identified_main", 12, UINT64_C(1002));
    elisa_trace_record_value_id("identified_main", 13, "counter", 7, 0,
                                UINT64_C(1003));
    elisa_trace_function_entry_id("identified_worker", 20, UINT64_C(1004));
    elisa_trace_function_exit_id("identified_worker", 20, UINT64_C(1004));
    elisa_trace_function_exit_id("identified_main", 10, UINT64_C(1001));
    return 0;
}
