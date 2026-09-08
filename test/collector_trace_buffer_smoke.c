#include <stdint.h>
#include <pthread.h>

void elisa_trace_function_entry(const char *function_name, uint32_t line);
void elisa_trace_function_exit(const char *function_name, uint32_t line);
void elisa_trace_record(const char *function_name, uint32_t line);

static const char main_name[] = "trace-main";
static const char worker_name[] = "trace-worker";

static void *trace_worker(void *argument) {
    (void)argument;
    elisa_trace_function_entry(worker_name, 10);
    elisa_trace_record(worker_name, 11);
    elisa_trace_function_exit(worker_name, 10);
    return NULL;
}

int64_t elisa_profile_target_main(void) {
    pthread_t worker;
    elisa_trace_function_entry(main_name, 1);
    if (pthread_create(&worker, NULL, trace_worker, NULL) != 0) {
        return 1;
    }
    if (pthread_join(worker, NULL) != 0) {
        return 2;
    }
    elisa_trace_function_exit(main_name, 1);
    return 0;
}
