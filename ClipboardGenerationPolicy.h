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

#ifdef __OBJC__
#import <Foundation/Foundation.h>

// A read of a copy's data can wait on a lazy provider (another device, an app that renders a
// promise). When the clipboard changes while it waits, a real pasteboard answers with the data
// of what the clipboard holds now (Flycut's own write for a choice) or with none, never with the
// copy's own. So a read that spans a clipboard change is never trusted: after every
// stringForType: and dataForType: of a copy, the clipboard must still hold the copy's generation.
// Once it does not, *changed is set, everything read for the copy is dropped and the copy gets
// no row; one fixed line is logged, without content.
static inline BOOL FCClipboardStillHoldsCopy(NSInteger changeCountAfterRead, NSInteger generation, BOOL *changed)
{
    if ( !*changed && changeCountAfterRead != generation ) {
        *changed = YES;
        NSLog(@"Clipboard read: the copy changed while it was read, so it is not taken in");
    }
    return !*changed;
}

// A catch-up poll (-[AppController captureClipboardChangeNow]) waits on the main thread, for a
// bounded time, for the clipboard reads that -pollPB: runs on its read queue. A read that ends
// in time hands its commit over, which runs at the end of the wait; one that ends later
// commits from the main queue, as for every poll. Either way each commit runs once, on the
// main thread.
@interface FCClipboardCatchUp : NSObject
+ (FCClipboardCatchUp *)catchUp;
- (void)readStarted;                                  // main thread, before the read is queued
- (void)readEndedWithCommit:(dispatch_block_t)commit; // read queue; nil: nothing to commit
- (void)waitUntil:(dispatch_time_t)deadline;          // main thread: wait, then run the commits
@end
#endif

#endif /* ClipboardGenerationPolicy_h */
