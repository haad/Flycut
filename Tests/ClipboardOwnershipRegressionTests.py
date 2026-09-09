#!/usr/bin/env python3
"""Actual transaction callbacks against an in-memory, generation-counted board."""
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture
FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import "AppController.h"
@interface AppController (OwnershipTest)
- (void)rememberFrontmostApplicationForPaste;
- (void)cancelPendingPasteCompletion;
@end
@interface MemoryBoard : NSObject
@property(retain) NSString *value;
@property NSInteger changeCount;
@property(copy) NSData *opaqueData;
@property BOOL writeFails;
@property BOOL changesDuringSnapshot;
@end
@implementation MemoryBoard
- (NSArray *)pasteboardItems {
    if (self.changesDuringSnapshot) { self.changeCount++; self.value=@"external copy"; }
    if (!self.value) return @[];
    NSPasteboardItem *item = [[[NSPasteboardItem alloc] init] autorelease];
    [item setString:self.value forType:NSPasteboardTypeString];
    if (self.opaqueData) [item setData:self.opaqueData forType:@"test.opaque-format"];
    return @[item];
}
- (NSInteger)declareTypes:(id)types owner:(id)owner { self.changeCount++; self.value=nil; self.opaqueData=nil; return self.changeCount; }
- (NSInteger)clearContents { return [self declareTypes:nil owner:nil]; }
- (BOOL)setString:(NSString *)value forType:(id)type { if (self.writeFails) return NO; self.value = [[value copy] autorelease]; return YES; }
- (NSString *)stringForType:(id)type { return self.value; }
- (BOOL)writeObjects:(NSArray *)items {
    self.value = [[items firstObject] stringForType:NSPasteboardTypeString]; self.opaqueData=[[items firstObject] dataForType:@"test.opaque-format"]; return YES;
}
@end
@interface OwnerTarget : NSObject
@property NSInteger activations;
@end
@implementation OwnerTarget
- (pid_t)processIdentifier { return 4242; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { self.activations++; return YES; }
@end
@interface OwnerOperator : NSObject
@property(retain) NSMutableString *selected;
@end
@implementation OwnerOperator
- (BOOL)setStackPositionToFirstItem { return YES; }
- (NSString *)getPasteFromStackPosition { return self.selected; }
- (BOOL)restoreStashedStore { return NO; }
// The image-aware bezel paste looks up the selected clipping first; this
// fixture's selection is a text clipping with the same contents.
- (FlycutClipping *)clippingAtStackPosition {
    NSString *text = [self getPasteFromStackPosition];
    return text ? [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:nil withAppBundleURL:nil withTimestamp:0] autorelease] : nil;
}
@end
@interface OwnerController : AppController
@property(retain) OwnerTarget *target;
@property NSInteger posts;
@property BOOL rejectPost;
@property(copy) NSString *postedText;
- (void)prepare:(MemoryBoard *)board operator:(OwnerOperator *)op;
- (id)payload;
@end
@implementation OwnerController
- (void)prepare:(MemoryBoard *)board operator:(OwnerOperator *)op {
    jcPasteboard=(id)[board retain]; flycutOperator=(id)[op retain];
}
- (id)payload {
    return [currentPasteTransaction respondsToSelector:NSSelectorFromString(@"selectedPayload")] ?
        [currentPasteTransaction valueForKey:@"selectedPayload"] : nil;
}
- (NSRunningApplication *)frontmostApplicationForPaste { return (id)self.target; }
- (void)showBezel { isBezelDisplayed=YES; }
- (void)hideApp { isBezelDisplayed=NO; }
- (void)fakeCommandV { abort(); }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)pid {
    if (self.rejectPost) return NO;
    self.posts++; self.postedText=[jcPasteboard stringForType:NSPasteboardTypeString]; return YES;
}
@end
int main(int argc, const char **argv) { @autoreleasepool {
    NSString *mode=@(argv[1]);
    MemoryBoard *board=[MemoryBoard new]; board.value=@"original";
    if ([mode isEqual:@"empty-cancel"]) board.value=nil;
    if ([mode isEqual:@"opaque-cancel"]) board.opaqueData=[@"opaque bytes" dataUsingEncoding:NSUTF8StringEncoding];
    board.writeFails=[mode isEqual:@"write-failed"];
    board.changesDuringSnapshot=[mode isEqual:@"snapshot-changed"];
    OwnerOperator *op=[OwnerOperator new]; op.selected=[NSMutableString stringWithString:@"selected"];
    OwnerController *c=[OwnerController new]; c.target=[OwnerTarget new]; [c prepare:board operator:op];
    c.rejectPost=[mode isEqual:@"post-rejected"];
    [c hitMainHotKey:nil]; [c metaKeysReleased];
    if ([mode isEqual:@"payload"]) {
        [op.selected setString:@"mutated store text"];
        if (![[c payload] isEqual:@"selected"]) { fprintf(stderr,"transaction did not copy immutable selected payload\n"); return 20; }
    } else if ([mode hasSuffix:@"cancel"]) [c cancelPendingPasteCompletion];
    else if ([mode isEqual:@"external"]) {
        [board declareTypes:nil owner:nil]; [board setString:@"external copy" forType:NSPasteboardTypeString];
    } else if ([mode isEqual:@"external-after-activation"]) {
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.51]];
        [board declareTypes:nil owner:nil]; [board setString:@"external copy" forType:NSPasteboardTypeString];
    }
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
    if ([mode isEqual:@"empty-cancel"]) {
        if (c.posts || board.value) return 25;
    } else if ([mode isEqual:@"opaque-cancel"]) {
        if (c.posts || ![board.value isEqual:@"original"] ||
            ![board.opaqueData isEqual:[@"opaque bytes" dataUsingEncoding:NSUTF8StringEncoding]]) return 26;
    } else if ([mode isEqual:@"write-failed"]) {
        if (c.posts || c.target.activations || ![board.value isEqual:@"original"]) return 27;
    } else if ([mode isEqual:@"external"] || [mode isEqual:@"external-after-activation"] || [mode isEqual:@"snapshot-changed"]) {
        if (c.posts || ![board.value isEqual:@"external copy"]) { fprintf(stderr,"external clipboard generation pasted or overwritten\n"); return 21; }
        if ([mode isEqual:@"external"] && c.target.activations) return 22;
    } else if ([mode isEqual:@"cancel"] || [mode isEqual:@"post-rejected"]) {
        if (c.posts || ![board.value isEqual:@"original"]) { fprintf(stderr,"cancel did not restore still-owned clipboard\n"); return 23; }
    } else if (c.posts!=1 || ![c.postedText isEqual:@"selected"]) return 24;
    printf("PASS clipboard ownership %s\n",argv[1]);
    [c release]; [op release]; [board release];
    return 0;
} }
'''
class ClipboardOwnershipRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'ClipboardOwnershipFixture')
    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
    def test_empty_clipboard_is_restored_on_cancel(self):
        self.check_mode('empty-cancel')
    def test_opaque_clipboard_representation_survives_cancel(self):
        self.check_mode('opaque-cancel')
    def test_failed_clipboard_write_cannot_activate_or_post(self):
        self.check_mode('write-failed')
    def test_generation_change_while_snapshotting_aborts_without_overwrite(self):
        self.check_mode('snapshot-changed')
    def test_rejected_post_restores_still_owned_clipboard(self):
        self.check_mode('post-rejected')
    def test_transaction_copies_selected_payload(self):
        self.check_mode('payload')
    def test_external_copy_cancels_before_target_activation(self):
        self.check_mode('external')
    def test_external_copy_after_activation_cancels_before_post(self):
        self.check_mode('external-after-activation')
    def test_cancel_restores_previous_clipboard_only_while_owned(self):
        self.check_mode('cancel')
if __name__ == '__main__':
    unittest.main()
