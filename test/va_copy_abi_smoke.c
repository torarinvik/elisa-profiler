#include <stddef.h>

extern void *va_copy(void *source);
extern void va_end(void *argument);

int main(void) {
    int marker = 0;
    void *copy = va_copy(&marker);
    if (copy != &marker) {
        return 1;
    }
    va_end(copy);
    return 0;
}
