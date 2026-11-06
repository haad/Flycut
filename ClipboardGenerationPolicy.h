#ifndef ClipboardGenerationPolicy_h
#define ClipboardGenerationPolicy_h

#include <stdbool.h>
#include <stdint.h>

// A delayed clipboard read is valid only when the observed generation remains
// unchanged through the payload read, is not Flycut-authored, capture is still
// enabled when the main-thread commit runs, and capture has not been paused
// since the read started. Pausing advances the capture epoch, so a read that was
// in flight stays discarded even when capture is resumed before it finishes.
static inline bool FCShouldCommitClipboardRead(
    int64_t observedGeneration,
    int64_t generationAfterRead,
    int64_t blockedGeneration,
    uint64_t observedCaptureEpoch,
    uint64_t captureEpochAtCommit,
    bool captureDisabledAtCommit
) {
    return observedGeneration == generationAfterRead
        && observedGeneration != blockedGeneration
        && observedCaptureEpoch == captureEpochAtCommit
        && !captureDisabledAtCommit;
}

#endif /* ClipboardGenerationPolicy_h */
