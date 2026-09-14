#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
void elisa_trace_function_entry_id(const char *, uint32_t, uint64_t);
void elisa_trace_function_exit_id(const char *, uint32_t, uint64_t);
void elisa_trace_record_id(const char *, uint32_t, uint64_t);
void elisa_profile_allocation_event_v1(uint32_t, uintptr_t, size_t, uintptr_t, size_t, uintptr_t, size_t);
static void allocation(uintptr_t address) {
    elisa_profile_allocation_event_v1(1, address, 32, 0, 0, 128, 256);
}
static void *worker(void *unused) {
    (void)unused;
    elisa_trace_function_entry_id("thread", 55, 1000);
    allocation(5);
    elisa_trace_function_exit_id("thread", 55, 1000);
    return NULL;
}
int64_t elisa_profile_target_main(void) {
    allocation(1); /* No stack is explicitly unknown. */
    elisa_trace_function_entry_id("outer", 10, UINT64_C(18446744073709551600));
    elisa_trace_record_id("outer", 12, 101);
    elisa_trace_function_entry_id("inner", 20, 200);
    elisa_trace_record_id("inner", 23, 201);
    allocation(2);
    elisa_trace_function_exit_id("inner", 20, 200);
    allocation(3); /* Restore outer's own last position. */
    elisa_trace_function_exit_id("outer", 10, UINT64_C(18446744073709551600));
    allocation(4);
    pthread_t thread;
    if (pthread_create(&thread, NULL, worker, NULL) || pthread_join(thread, NULL)) return 1;
    for (uint32_t i = 0; i < 10; ++i) elisa_trace_function_entry_id("deep", 50+i, 500+i);
    allocation(6);
    for (uint32_t i = 10; i > 0; --i) elisa_trace_function_exit_id("deep", 49+i, 499+i);
    allocation(7);
    return 0;
}
