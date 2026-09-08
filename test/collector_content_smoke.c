#include <stdint.h>
#include <stddef.h>
#include <assert.h>

uint32_t elisa_profile_region_layout_negotiate(uint32_t version);
void elisa_profile_region_layout_v1(uintptr_t arena, size_t region,
                                  uintptr_t header, uintptr_t data_base, size_t capacity);
enum { REGION_ABI_V1 = 1, REGION_ABI_UNSUPPORTED = 0, REGION_INDEX = 3, REGION_CAPACITY = 4096 };
static const uintptr_t region_arena = 0x1000;
static const uintptr_t region_header = 0x2000;
static const uintptr_t region_data = 0x2040;

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
    assert(elisa_profile_region_layout_negotiate(REGION_ABI_V1) == REGION_ABI_V1);
    assert(elisa_profile_region_layout_negotiate(REGION_ABI_UNSUPPORTED) == REGION_ABI_UNSUPPORTED);
    assert(elisa_profile_region_layout_negotiate(UINT32_MAX) == REGION_ABI_UNSUPPORTED);
    elisa_profile_region_layout_v1(region_arena, REGION_INDEX, region_header, region_data, REGION_CAPACITY);
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
