#!/usr/bin/env python3
"""PR7-LIFECYCLE-001: real placement/teardown/retry, inert OS boundaries.

Self-contained in Tests: no evidence-directory source or generated probe needed.
The original independent probe's 0.85-second waits and real hotkey/release entry
points are retained. Board hooks also cover reentrant newer generations, including
one cleared during restoration, so a nil-current check alone cannot hide new UI.
"""
import json
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import "AppController.h"
@interface AppController (FailureRecoveryTesting)
- (void)cancelPendingPasteCompletion;
@end

@interface RecoveryBoard : NSObject
@property(copy) NSString *value;
@property NSInteger changeCount;
@property BOOL writeFails;
@property BOOL changesDuringSnapshot;
@property(copy) void (^snapshotHook)(void);
@property(copy) void (^writeHook)(void);
@property(copy) void (^restoreHook)(void);
@end
@implementation RecoveryBoard
- (NSArray *)pasteboardItems {
    if (self.snapshotHook) {
        void (^hook)(void) = [self.snapshotHook copy]; self.snapshotHook=nil;
        hook(); [hook release];
    }
    if (self.changesDuringSnapshot) { self.changeCount++; self.value=@"external copy"; }
    if (!self.value) return @[];
    NSPasteboardItem *item=[[[NSPasteboardItem alloc] init] autorelease];
    [item setString:self.value forType:NSPasteboardTypeString];
    return @[item];
}
- (NSInteger)declareTypes:(id)types owner:(id)owner {
    self.changeCount++; self.value=nil; return self.changeCount;
}
- (NSInteger)clearContents { return [self declareTypes:nil owner:nil]; }
- (BOOL)setString:(NSString *)value forType:(id)type {
    BOOL fail=self.writeFails;
    if (self.writeHook) {
        void (^hook)(void) = [self.writeHook copy]; self.writeHook=nil;
        hook(); [hook release];
    }
    if (fail) return NO;
    self.value=value; return YES;
}
- (NSString *)stringForType:(id)type { return self.value; }
- (BOOL)writeObjects:(NSArray *)items {
    self.value=[[items firstObject] stringForType:NSPasteboardTypeString];
    if (self.restoreHook) {
        void (^hook)(void) = [self.restoreHook copy]; self.restoreHook=nil;
        hook(); [hook release];
    }
    return YES;
}
- (void)dealloc {
    [_value release]; [_snapshotHook release]; [_writeHook release]; [_restoreHook release];
    [super dealloc];
}
@end
@interface RecoveryTarget : NSObject
@property NSInteger activations;
@end
@implementation RecoveryTarget
- (pid_t)processIdentifier { return 4242; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { self.activations++; return YES; }
@end
@interface RecoveryOperator : NSObject
@property(copy) NSString *selected;
@end
@implementation RecoveryOperator
- (BOOL)setStackPositionToFirstItem { return YES; }
- (NSString *)getPasteFromStackPosition { return self.selected; }
- (BOOL)restoreStashedStore { return NO; }
- (int)stackPosition { return 0; }
- (int)jcListCount { return 1; }
- (BOOL)setStackPositionToOneLessRecent { return NO; }
- (void)dealloc { [_selected release]; [super dealloc]; }
// The image-aware bezel paste looks up the selected clipping first; this
// fixture's selection is a text clipping with the same contents.
- (FlycutClipping *)clippingAtStackPosition {
    NSString *text = [self getPasteFromStackPosition];
    return text ? [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:nil withAppBundleURL:nil withTimestamp:0] autorelease] : nil;
}
@end
@interface RecoveryController : AppController
@property(retain) RecoveryTarget *target;
@property NSInteger posts;
@property NSInteger hides;
@property(copy) NSString *postedText;
- (void)prepare:(RecoveryBoard *)board operator:(RecoveryOperator *)op;
- (BOOL)displayed;
- (BOOL)ownsTransaction;
- (NSUInteger)generation;
@end
@implementation RecoveryController
- (void)prepare:(RecoveryBoard *)board operator:(RecoveryOperator *)op {
    jcPasteboard=(id)[board retain]; flycutOperator=(id)[op retain];
}
- (NSRunningApplication *)frontmostApplicationForPaste { return (id)self.target; }
- (void)showBezel { isBezelDisplayed=YES; }
// Execute production hideApp/hideBezel. NSApp is nil via the test-only forced
// include and bezel is never allocated; this does not hide an actual application.
- (void)hideApp { self.hides++; [super hideApp]; }
- (BOOL)displayed { return isBezelDisplayed; }
- (BOOL)ownsTransaction { return currentPasteTransaction!=nil; }
- (NSUInteger)generation { return nextPasteTransactionGeneration; }
- (void)fakeCommandV { abort(); }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)pid {
    if (pid!=4242) abort();
    self.posts++; self.postedText=[jcPasteboard stringForType:NSPasteboardTypeString]; return YES;
}
- (void)dealloc { [_target release]; [_postedText release]; [super dealloc]; }
@end
static void settle(void) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.85]];
}
int main(int argc, const char **argv) { @autoreleasepool {
    NSString *mode=@(argv[1]);
    BOOL healthy=[mode isEqual:@"healthy-retry"];
    BOOL reentrant=[mode hasPrefix:@"newer-"];
    BOOL clearNewer=[mode hasSuffix:@"-cleared"];
    RecoveryBoard *board=[RecoveryBoard new]; board.value=@"original";
    board.writeFails=[mode isEqual:@"write-failed-retry"] || [mode hasPrefix:@"newer-write"] || [mode hasPrefix:@"newer-restore"];
    board.changesDuringSnapshot=[mode isEqual:@"snapshot-changed-retry"];
    RecoveryOperator *op=[RecoveryOperator new]; op.selected=@"first selection";
    RecoveryController *c=[RecoveryController new]; c.target=[[[RecoveryTarget alloc] init] autorelease];
    [c prepare:board operator:op];
    if (reentrant) {
        void (^openNewer)(void) = ^{
            board.writeFails=NO; board.changesDuringSnapshot=NO;
            [c hideApp]; [c hitMainHotKey:nil];
            // A newer generation can be cleared reentrantly too. Its UI must not
            // be mistaken for the old failed selection merely because current=nil.
            if (clearNewer) [c cancelPendingPasteCompletion];
        };
        if ([mode hasPrefix:@"newer-snapshot"]) board.snapshotHook=openNewer;
        else if ([mode hasPrefix:@"newer-write"]) board.writeHook=openNewer;
        else board.restoreHook=openNewer;
    }
    [c hitMainHotKey:nil]; NSUInteger firstGeneration=[c generation];
    [c metaKeysReleased]; settle();
    BOOL displayedAfterFirst=[c displayed], ownedAfterFirst=[c ownsTransaction];
    NSInteger firstPosts=c.posts, firstActivations=c.target.activations, firstHides=c.hides;
    BOOL clipboardPreserved=healthy ? [board.value isEqual:@"first selection"] :
        [board.value isEqual:([mode isEqual:@"snapshot-changed-retry"] ? @"external copy" : @"original")];
    BOOL newerGeneration=[c generation]!=firstGeneration;
    // Clearing a transient condition alone must NEVER restart cancelled work.
    board.writeFails=NO; board.changesDuringSnapshot=NO; settle();
    NSInteger idlePosts=c.posts, idleActivations=c.target.activations;
    BOOL idleDisplayStable=[c displayed]==displayedAfterFirst;
    if (reentrant && !clearNewer) {
        // Explicit release completes the newer selection, not the failed one.
        op.selected=@"explicit retry"; [c metaKeysReleased];
    } else {
        if (clearNewer) [c hideApp]; // explicit dismissal of that separate cancellation
        op.selected=@"explicit retry"; [c hitMainHotKey:nil]; [c metaKeysReleased];
    }
    settle();
    NSInteger expectedPosts=healthy ? 2 : 1;
    BOOL recovered=c.posts==expectedPosts && c.target.activations==expectedPosts &&
        ![c displayed] && ![c ownsTransaction] && [c.postedText isEqual:@"explicit retry"];
    // Duplicate/late modifier releases cannot paste the cancelled selection or
    // repeat the successful retry, even beyond the former completion window.
    [c metaKeysReleased]; [c metaKeysReleased]; settle();
    BOOL onceOnly=c.posts==expectedPosts && c.target.activations==expectedPosts;
    NSDictionary *receipt=@{@"mode":mode,@"displayed_after_first":@(displayedAfterFirst),
        @"transaction_after_first":@(ownedAfterFirst),@"first_posts":@(firstPosts),
        @"first_activations":@(firstActivations),@"first_hides":@(firstHides),
        @"clipboard_preserved":@(clipboardPreserved),@"newer_generation":@(newerGeneration),
        @"idle_posts":@(idlePosts),@"idle_activations":@(idleActivations),
        @"idle_display_stable":@(idleDisplayStable),@"recovered":@(recovered),@"once_only":@(onceOnly)};
    NSData *json=[NSJSONSerialization dataWithJSONObject:receipt options:0 error:nil];
    fwrite([json bytes],1,[json length],stdout); fputs("\n",stdout);
    BOOL firstState = reentrant ? (displayedAfterFirst && ownedAfterFirst==!clearNewer && newerGeneration && firstHides==1) :
        (!displayedAfterFirst && !ownedAfterFirst && !newerGeneration && firstHides==1);
    NSInteger expectedFirst=healthy ? 1 : 0;
    BOOL success=firstState && firstPosts==expectedFirst && firstActivations==expectedFirst &&
        clipboardPreserved && idlePosts==expectedFirst && idleActivations==expectedFirst &&
        idleDisplayStable && recovered && onceOnly;
    [c release]; [op release]; [board release];
    return success ? 0 : 86;
} }
'''


class FailureRecoveryRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'FailureRecoveryFixture')

    def check_mode(self, mode):
        result = run_fixture(self.binary, mode)
        observed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, json.dumps(observed, indent=2)+result.stderr)

    def test_write_failure_tears_down_and_requires_explicit_retry(self):
        self.check_mode('write-failed-retry')

    def test_snapshot_change_tears_down_and_requires_explicit_retry(self):
        self.check_mode('snapshot-changed-retry')

    def test_healthy_invocations_remain_independent(self):
        self.check_mode('healthy-retry')

    def test_stale_snapshot_failure_preserves_newer_selection(self):
        self.check_mode('newer-snapshot-current')

    def test_stale_snapshot_failure_preserves_newer_cleared_generation(self):
        self.check_mode('newer-snapshot-cleared')

    def test_stale_write_failure_preserves_newer_selection(self):
        self.check_mode('newer-write-current')

    def test_stale_write_failure_preserves_newer_cleared_generation(self):
        self.check_mode('newer-write-cleared')

    def test_reentrant_restore_preserves_newer_selection(self):
        self.check_mode('newer-restore-current')

    def test_reentrant_restore_preserves_newer_cleared_generation(self):
        self.check_mode('newer-restore-cleared')


if __name__ == '__main__':
    unittest.main()
