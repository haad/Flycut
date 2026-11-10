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
- (void)processBezelKeyDown:(NSEvent *)event;
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
@property pid_t pid;
@property BOOL refusesActivation;
@end
@implementation OwnerTarget
- (pid_t)processIdentifier { return self.pid ? self.pid : 4242; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { self.activations++; return !self.refusesActivation; }
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
// The bezel's copy-only action ("move to top") resolves the stack position as a
// store position through the real -pasteStorePositionAndUpdate:.
- (BOOL)stackPositionIsInBounds { return YES; }
- (int)stackPosition { return 0; }
- (int)jcListCount { return 1; }
- (FlycutClipping *)clippingAtIndex:(int)index { return [self clippingAtStackPosition]; }
- (NSString *)getPasteFromIndex:(int)index { return self.selected; }
@end
@interface OwnerController : AppController
@property(retain) OwnerTarget *target;
@property(retain) OwnerTarget *frontmostOverride;
@property BOOL otherAppFrontmostAfterActivation;
@property NSInteger posts;
@property NSInteger postAttempts;
@property BOOL rejectPost;
@property(copy) NSString *postedText;
- (void)prepare:(MemoryBoard *)board operator:(OwnerOperator *)op;
- (id)payload;
- (BOOL)ownsTransaction;
@end
@implementation OwnerController
- (void)prepare:(MemoryBoard *)board operator:(OwnerOperator *)op {
    jcPasteboard=(id)[board retain]; flycutOperator=(id)[op retain];
}
- (id)payload {
    return [currentPasteTransaction respondsToSelector:NSSelectorFromString(@"selectedPayload")] ?
        [currentPasteTransaction valueForKey:@"selectedPayload"] : nil;
}
- (BOOL)ownsTransaction { return currentPasteTransaction != nil; }
- (NSRunningApplication *)frontmostApplicationForPaste {
    if (self.otherAppFrontmostAfterActivation && self.target.activations > 0) return (id)self.frontmostOverride;
    if (self.frontmostOverride && !self.otherAppFrontmostAfterActivation) return (id)self.frontmostOverride;
    return (id)self.target;
}
- (void)showBezel { isBezelDisplayed=YES; }
- (void)hideApp { isBezelDisplayed=NO; }
- (void)updateMenu {} // status-menu UI only
- (void)fakeCommandV { abort(); }
// Posting boundary. NO models a post that is refused: no Accessibility access, no
// resolvable paste key or no event could be created; nothing reaches the target.
- (BOOL)postCommandVToProcessIdentifier:(pid_t)pid {
    self.postAttempts++;
    if (self.rejectPost) return NO;
    self.posts++; self.postedText=[jcPasteboard stringForType:NSPasteboardTypeString]; return YES;
}
@end
static NSEvent *BezelKey(NSString *characters, unsigned short keyCode) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
        windowNumber:0 context:nil characters:characters charactersIgnoringModifiers:characters
        isARepeat:NO keyCode:keyCode];
}
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
    c.target.refusesActivation=[mode isEqual:@"activation-refused"];
    OwnerTarget *otherApp=[[OwnerTarget new] autorelease]; otherApp.pid=5151;
    c.otherAppFrontmostAfterActivation=[mode isEqual:@"focus-left-after-activation"];
    if (c.otherAppFrontmostAfterActivation) c.frontmostOverride=otherApp;
    if ([mode hasPrefix:@"copy-only"]) {
        // Bezel copy-only action: the clipping goes to the clipboard and no paste follows.
        [c hitMainHotKey:nil];
        [c processBezelKeyDown:BezelKey(@"\x03", 8)];
        if (![board.value isEqual:@"selected"]) { fprintf(stderr,"copy-only action did not copy\n"); return 30; }
        if ([mode isEqual:@"copy-only-escape"]) [c processBezelKeyDown:BezelKey(@"", 53)];
        else if ([mode isEqual:@"copy-only-release"]) [c metaKeysReleased];
        else if ([mode isEqual:@"copy-only-hotkey"]) {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
            [c hitMainHotKey:nil];
        } else return 3;
    } else {
        [c hitMainHotKey:nil]; [c metaKeysReleased];
        if ([mode isEqual:@"focus-left"]) c.frontmostOverride=otherApp; // before the 0.5 s completion
        if ([mode isEqual:@"superseded"]) // a new selection after the bezel hid, before the post
            [c performSelector:@selector(hitMainHotKey:) withObject:nil afterDelay:0.3];
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
    } else if ([mode isEqual:@"cancel"] || [mode isEqual:@"superseded"]) {
        if (c.postAttempts || ![board.value isEqual:@"original"]) { fprintf(stderr,"cancel did not restore still-owned clipboard\n"); return 23; }
    } else if ([mode isEqual:@"post-rejected"] || [mode isEqual:@"activation-refused"] ||
               [mode isEqual:@"focus-left"] || [mode isEqual:@"focus-left-after-activation"]) {
        // The paste could not be delivered, but nobody cancelled the selection.
        NSInteger activations=[mode isEqual:@"focus-left"] ? 0 : 1;
        NSInteger attempts=[mode isEqual:@"post-rejected"] ? 1 : 0;
        if (c.posts || c.postAttempts!=attempts || c.target.activations!=activations) {
            fprintf(stderr,"unexpected paste path: posts=%ld attempts=%ld activations=%ld\n",
                (long)c.posts,(long)c.postAttempts,(long)c.target.activations); return 28;
        }
        if (![board.value isEqual:@"selected"] || [c ownsTransaction]) {
            fprintf(stderr,"undelivered paste rolled the selection off the clipboard: %s\n",[board.value UTF8String]); return 29;
        }
    } else if ([mode isEqual:@"copy-only-hotkey"] || [mode isEqual:@"copy-only-escape"]) {
        if (c.postAttempts || ![board.value isEqual:@"selected"]) {
            fprintf(stderr,"copy-only bezel action was rolled back: %s\n",[board.value UTF8String]); return 31;
        }
    } else if ([mode isEqual:@"copy-only-release"]) {
        if (c.posts!=1 || ![c.postedText isEqual:@"selected"] || ![board.value isEqual:@"selected"] || [c ownsTransaction]) return 32;
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
    def test_rejected_post_leaves_selection_on_clipboard(self):
        self.check_mode('post-rejected')
    def test_refused_reactivation_leaves_selection_on_clipboard(self):
        self.check_mode('activation-refused')
    def test_focus_change_before_activation_leaves_selection_on_clipboard(self):
        self.check_mode('focus-left')
    def test_focus_change_after_activation_leaves_selection_on_clipboard(self):
        self.check_mode('focus-left-after-activation')
    def test_copy_only_bezel_action_survives_the_next_hotkey(self):
        self.check_mode('copy-only-hotkey')
    def test_copy_only_bezel_action_survives_escape(self):
        self.check_mode('copy-only-escape')
    def test_copy_only_bezel_action_then_release_pastes_the_copy_once(self):
        self.check_mode('copy-only-release')
    def test_superseding_hotkey_restores_still_owned_clipboard(self):
        self.check_mode('superseded')
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
