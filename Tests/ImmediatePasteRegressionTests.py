#!/usr/bin/env python3
"""Native regression test for modifier-release paste completion."""

from __future__ import annotations

import unittest




class ImmediatePasteRegressionTests(unittest.TestCase):
    def test_modifier_release_reactivates_original_app_and_pastes_exactly_once(self) -> None:
        fixture = r'''
#include "PasteTestEnvironmentImplementation.h"
#import <Cocoa/Cocoa.h>
#import "AppController.h"

@interface AppController (ImmediatePasteTesting)
- (void)hitMainHotKey:(id)hotKey;
- (void)metaKeysReleased;
@end

@interface FCPasteTarget : NSObject {
    NSInteger _activationCount;
    pid_t _processIdentifier;
    BOOL _terminated;
}
@property(nonatomic, assign) NSInteger activationCount;
@property(nonatomic, assign) pid_t processIdentifier;
@property(nonatomic, assign, getter=isTerminated) BOOL terminated;
@end

@implementation FCPasteTarget
@synthesize activationCount = _activationCount;
@synthesize processIdentifier = _processIdentifier;
@synthesize terminated = _terminated;
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options {
    self.activationCount += 1;
    return YES;
}
@end

@interface FCPasteOperator : NSObject
@end

@implementation FCPasteOperator
- (BOOL)setStackPositionToFirstItem { return YES; }
- (NSString *)getPasteFromStackPosition { return @"selected clipping"; }
- (BOOL)restoreStashedStore { return NO; }
// The image-aware bezel paste looks up the selected clipping first; this
// fixture's selection is a text clipping with the same contents.
- (FlycutClipping *)clippingAtStackPosition {
    NSString *text = [self getPasteFromStackPosition];
    return text ? [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:nil withAppBundleURL:nil withTimestamp:0] autorelease] : nil;
}
@end

@interface FCImmediatePasteController : AppController {
    FCPasteTarget *_target;
    NSInteger _pasteboardCount;
    NSInteger _hideCount;
    NSInteger _syntheticPasteCount;
    BOOL _pasteObservedAfterActivation;
    BOOL _pasteWasTargeted;
    BOOL _pasteObservedAfterHide;
}
@property(nonatomic, retain) FCPasteTarget *target;
@property(nonatomic, assign) NSInteger pasteboardCount;
@property(nonatomic, assign) NSInteger hideCount;
@property(nonatomic, assign) NSInteger syntheticPasteCount;
@property(nonatomic, assign) BOOL pasteObservedAfterActivation;
@property(nonatomic, assign) BOOL pasteWasTargeted;
@property(nonatomic, assign) BOOL pasteObservedAfterHide;
@end

@implementation FCImmediatePasteController
@synthesize target = _target;
@synthesize pasteboardCount = _pasteboardCount;
@synthesize hideCount = _hideCount;
@synthesize syntheticPasteCount = _syntheticPasteCount;
@synthesize pasteObservedAfterActivation = _pasteObservedAfterActivation;
@synthesize pasteWasTargeted = _pasteWasTargeted;
@synthesize pasteObservedAfterHide = _pasteObservedAfterHide;

- (void)dealloc {
    [_target release];
    [super dealloc];
}

- (NSRunningApplication *)frontmostApplicationForPaste {
    return (NSRunningApplication *)self.target;
}

- (void)showBezel {
    isBezelDisplayed = YES;
}

// Clipboard effects are injected here; ClipboardOwnershipRegressionTests exercises
// the actual placement, generation fence and restore code with an in-memory board.
- (BOOL)pasteboardIsOwnedByTransaction:(id)transaction { return YES; }
- (void)addClipToPasteboard:(NSString *)content {
    if ([content isEqualToString:@"selected clipping"])
        self.pasteboardCount += 1;
}

- (void)hideApp {
    self.hideCount += 1;
    isBezelDisplayed = NO;
    isBezelPinned = NO;
}

- (void)fakeCommandV {
    self.syntheticPasteCount += 1;
    self.pasteObservedAfterActivation = self.target.activationCount == 1;
    self.pasteObservedAfterHide = self.hideCount == 1;
}
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier {
    self.syntheticPasteCount += 1;
    self.pasteObservedAfterActivation = self.target.activationCount == 1;
    self.pasteWasTargeted = processIdentifier == self.target.processIdentifier;
    self.pasteObservedAfterHide = self.hideCount == 1;
    return YES;
}
@end

int main(void) {
    @autoreleasepool {
        FCImmediatePasteController *controller = [[FCImmediatePasteController alloc] init];
        FCPasteTarget *target = [[FCPasteTarget alloc] init];
        target.processIdentifier = 101;
        FCPasteOperator *operator = [[FCPasteOperator alloc] init];
        controller.target = target;
        [controller setValue:operator forKey:@"flycutOperator"];

        [controller hitMainHotKey:nil];
        [controller metaKeysReleased];
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:3.0];
        while (controller.syntheticPasteCount == 0 && [deadline timeIntervalSinceNow] > 0) {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }

        if (controller.pasteboardCount != 1) return 11;
        if (controller.hideCount != 1) return 12;
        if (target.activationCount != 1) return 13;
        if (controller.syntheticPasteCount != 1) return 14;
        if (!controller.pasteObservedAfterActivation) return 15;
        if (!controller.pasteWasTargeted) return 16;
        if (!controller.pasteObservedAfterHide) return 17;

        [operator release];
        [target release];
        [controller release];
    }
    return 0;
}
'''
        from PasteNativeTestSupport import build_fixture, run_fixture
        binary = build_fixture(fixture, "ImmediatePasteFixture")
        run = run_fixture(binary, "normal")
        self.assertEqual(run.returncode, 0,
            f"modifier release did not complete one paste in the original app; "
            f"exit={run.returncode}\n{run.stderr}")



if __name__ == "__main__":
    unittest.main()
