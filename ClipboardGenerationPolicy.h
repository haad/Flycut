#ifndef ClipboardGenerationPolicy_h
#define ClipboardGenerationPolicy_h

#include <stdbool.h>
#include <stdint.h>

// A delayed clipboard read is valid only when the observed generation remains
// unchanged through the payload read, is not Flycut-authored, and capture is
// still enabled when the main-thread commit runs.
static inline bool FCShouldCommitClipboardRead(
    int64_t observedGeneration,
    int64_t generationAfterRead,
    int64_t blockedGeneration,
    bool captureDisabledAtCommit
) {
    return observedGeneration == generationAfterRead
        && observedGeneration != blockedGeneration
        && !captureDisabledAtCommit;
}

#endif /* ClipboardGenerationPolicy_h */
