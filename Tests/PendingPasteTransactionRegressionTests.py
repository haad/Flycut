#!/usr/bin/env python3
"""Native regressions for delayed hotkey paste transactions."""

from __future__ import annotations

import unittest


FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import <Cocoa/Cocoa.h>
#import "AppController.h"

@interface AppController (PendingPasteTransactionTesting)
- (void)hitMainHotKey:(id)hotKey;
- (void)metaKeysReleased;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)processMenuClippingSelection:(id)sender;
- (void)rememberFrontmostApplicationForPaste;
- (void)showSearchWindow;
- (void)searchWindowItemSelected:(id)sender;
@end

@class FCPendingPasteController;

@interface FCPasteTarget : NSObject {
    pid_t _processIdentifier;
    pid_t _alternateProcessIdentifier;
    BOOL _terminated;
    BOOL _changesPIDAfterFirstRead;
    BOOL _reenterSameTargetSessionOnActivation;
    NSInteger _pidReadCount;
    FCPendingPasteController *_activationObserver;
    id _frontmostAfterActivation;
}
@property(nonatomic, assign) pid_t processIdentifier;
@property(nonatomic, assign) pid_t alternateProcessIdentifier;
@property(nonatomic, assign, getter=isTerminated) BOOL terminated;
@property(nonatomic, assign) BOOL changesPIDAfterFirstRead;
@property(nonatomic, assign) BOOL reenterSameTargetSessionOnActivation;
@property(nonatomic, assign) FCPendingPasteController *activationObserver;
@property(nonatomic, assign) id frontmostAfterActivation;
@end
@implementation FCPasteTarget
@synthesize alternateProcessIdentifier = _alternateProcessIdentifier;
@synthesize terminated = _terminated;
@synthesize changesPIDAfterFirstRead = _changesPIDAfterFirstRead;
@synthesize reenterSameTargetSessionOnActivation = _reenterSameTargetSessionOnActivation;
@synthesize activationObserver = _activationObserver;
@synthesize frontmostAfterActivation = _frontmostAfterActivation;
- (void)setProcessIdentifier:(pid_t)value { _processIdentifier = value; }
- (pid_t)processIdentifier {
    _pidReadCount += 1;
    if (_changesPIDAfterFirstRead && _pidReadCount > 1)
        return _alternateProcessIdentifier;
    return _processIdentifier;
}
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options {
    (void)options;
    _pidReadCount = 0;
    [_activationObserver targetDidActivate:(_frontmostAfterActivation ?: self)];
    if (_reenterSameTargetSessionOnActivation) {
        _reenterSameTargetSessionOnActivation = NO;
        [_activationObserver beginSecondSession:self];
    }
    return YES;
}
@end

@interface FCPasteOperator : NSObject {
    BOOL _contentAvailable;
}
@property(nonatomic, assign) BOOL contentAvailable;
@end
@implementation FCPasteOperator
@synthesize contentAvailable = _contentAvailable;
- (BOOL)setStackPositionToFirstItem { return YES; }
- (NSString *)getPasteFromStackPosition {
    return self.contentAvailable ? @"selected clipping" : nil;
}
- (BOOL)restoreStashedStore { return NO; }
- (int)jcListCount { return 1; }
- (id)clippingAtPosition:(int)position {
    static FlycutClipping *clipping;
    if (!clipping) { clipping = [FlycutClipping new]; [clipping setContents:@"selected clipping"]; }
    return clipping;
}
// The image-aware bezel paste looks up the selected clipping first; this
// fixture's selection is a text clipping with the same contents.
- (FlycutClipping *)clippingAtStackPosition {
    NSString *text = [self getPasteFromStackPosition];
    return text ? [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:nil withAppBundleURL:nil withTimestamp:0] autorelease] : nil;
}
@end

@interface FCSearchWindowStub : NSObject
@end
@implementation FCSearchWindowStub
- (void)makeKeyAndOrderFront:(id)sender { (void)sender; }
- (BOOL)makeFirstResponder:(id)responder { (void)responder; return YES; }
- (void)orderOut:(id)sender { (void)sender; }
@end

@interface FCSearchFieldStub : NSObject
@end
@implementation FCSearchFieldStub
- (NSString *)stringValue { return @""; }
- (void)setStringValue:(NSString *)value { (void)value; }
@end

@interface FCSearchTableStub : NSObject
@end
@implementation FCSearchTableStub
- (NSInteger)selectedRow { return 0; }
- (NSInteger)clickedRow { return 0; }
@end

@interface FCPendingPasteController : AppController {
    FCPasteTarget *_target;
    NSInteger _pasteboardCount;
    NSInteger _globalPasteCount;
    NSInteger _targetedPasteCount;
    pid_t _lastPostedProcessIdentifier;
    NSInteger _hideCount;
    BOOL _focusStolen;
    BOOL _slowActivation;
    BOOL _activationNeverSettles;
    NSInteger _frontmostQueryCount;
    FCPasteTarget *_focusThief;
    id _frontmostOverride;
}
@property(nonatomic, retain) FCPasteTarget *target;
@property(nonatomic, assign) NSInteger pasteboardCount;
@property(nonatomic, assign) NSInteger globalPasteCount;
@property(nonatomic, assign) NSInteger targetedPasteCount;
@property(nonatomic, assign) pid_t lastPostedProcessIdentifier;
@property(nonatomic, assign) NSInteger hideCount;
@property(nonatomic, assign) BOOL focusStolen;
@property(nonatomic, assign) BOOL slowActivation;
@property(nonatomic, assign) BOOL activationNeverSettles;
@property(nonatomic, assign) NSInteger frontmostQueryCount;
@property(nonatomic, assign) FCPasteTarget *focusThief;
@property(nonatomic, assign) id frontmostOverride;
@end

@implementation FCPendingPasteController
@synthesize target = _target;
@synthesize pasteboardCount = _pasteboardCount;
@synthesize globalPasteCount = _globalPasteCount;
@synthesize targetedPasteCount = _targetedPasteCount;
@synthesize lastPostedProcessIdentifier = _lastPostedProcessIdentifier;
@synthesize hideCount = _hideCount;
@synthesize focusStolen = _focusStolen;
@synthesize slowActivation = _slowActivation;
@synthesize activationNeverSettles = _activationNeverSettles;
@synthesize frontmostQueryCount = _frontmostQueryCount;
@synthesize focusThief = _focusThief;
@synthesize frontmostOverride = _frontmostOverride;

- (void)dealloc {
    [_target release];
    [super dealloc];
}
- (NSRunningApplication *)frontmostApplicationForPaste {
    self.frontmostQueryCount += 1;
    if (self.focusStolen) return (NSRunningApplication *)self.focusThief;
    if ((self.slowActivation || self.activationNeverSettles) && self.frontmostQueryCount == 2)
        return [NSRunningApplication currentApplication];
    if (self.slowActivation && self.frontmostQueryCount == 3) return nil;
    if (self.activationNeverSettles && self.frontmostQueryCount >= 3) return nil;
    if (self.frontmostOverride) return (NSRunningApplication *)self.frontmostOverride;
    return (NSRunningApplication *)self.target;
}
- (void)showBezel { isBezelDisplayed = YES; }
- (void)buildSearchWindow {
    searchWindow = (NSWindow *)[[FCSearchWindowStub alloc] init];
    searchWindowSearchField = (NSSearchField *)[[FCSearchFieldStub alloc] init];
    searchWindowTableView = (NSTableView *)[[FCSearchTableStub alloc] init];
}
- (void)updateSearchResults {
    [searchResults release];
    searchResults = [[NSArray arrayWithObject:@"selected clipping"] retain];
    [searchResultClippings release];
    searchResultClippings = [[NSArray arrayWithObject:[flycutOperator clippingAtPosition:0]] retain];
}
- (int)storePositionForMenuItem:(NSMenuItem *)menuItem { (void)menuItem; return 0; }
- (bool)pasteStorePositionAndUpdate:(int)position {
    (void)position;
    self.pasteboardCount += 1;
    return true;
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
- (void)fakeCommandV { self.globalPasteCount += 1; }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier {
    self.lastPostedProcessIdentifier = processIdentifier;
    self.targetedPasteCount += 1;
    return YES;
}
- (void)targetDidActivate:(id)frontmostApplication {
    self.focusStolen = NO;
    self.frontmostOverride = frontmostApplication;
}
- (void)stealFocus {
    self.focusStolen = YES;
    self.frontmostOverride = nil;
}
- (void)useFocusThiefAsFrontmost {
    self.focusStolen = NO;
    self.frontmostOverride = self.focusThief;
}
- (void)terminateTarget { self.target.terminated = YES; }
- (void)selectMenuItemWithoutImmediatePaste {
    [[NSUserDefaults standardUserDefaults] setBool:NO forKey:@"menuSelectionPastes"];
    NSMenuItem *item = [[[NSMenuItem alloc] initWithTitle:@"fixture"
                                                   action:nil
                                            keyEquivalent:@""] autorelease];
    [self processMenuClippingSelection:item];
}
- (void)beginSecondSession:(FCPasteTarget *)newTarget {
    self.target = newTarget;
    self.focusStolen = NO;
    self.frontmostOverride = nil;
    [self hitMainHotKey:nil];
}
- (void)beginSecondSessionAndRelease:(FCPasteTarget *)newTarget {
    isBezelDisplayed = NO;
    [self beginSecondSession:newTarget];
    [self performSelector:@selector(metaKeysReleased) withObject:nil afterDelay:0.05];
}
- (void)replaceRememberedTargetWithoutCancellation:(FCPasteTarget *)newTarget {
    self.target = newTarget;
    self.frontmostOverride = nil;
    [self rememberFrontmostApplicationForPaste];
}
- (BOOL)hasRememberedPasteTarget { return currentPasteTransaction != nil; }
- (BOOL)isSelectionDisplayed { return isBezelDisplayed; }
- (void)triggerEscape {
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown
                                      location:NSZeroPoint
                                 modifierFlags:0
                                     timestamp:0
                                  windowNumber:0
                                       context:nil
                                    characters:@""
                   charactersIgnoringModifiers:@""
                                     isARepeat:NO
                                       keyCode:53];
    [self processBezelKeyDown:event];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        [NSApplication sharedApplication];
        FCPendingPasteController *controller = [[FCPendingPasteController alloc] init];
        FCPasteTarget *target = [[FCPasteTarget alloc] init];
        target.processIdentifier = 101;
        FCPasteTarget *secondTarget = [[FCPasteTarget alloc] init];
        secondTarget.processIdentifier = 202;
        FCPasteOperator *operator = [[FCPasteOperator alloc] init];
        operator.contentAvailable = YES;
        controller.target = target;
        controller.focusThief = secondTarget;
        target.activationObserver = controller;
        target.frontmostAfterActivation = target;
        secondTarget.activationObserver = controller;
        secondTarget.frontmostAfterActivation = secondTarget;
        [controller setValue:operator forKey:@"flycutOperator"];

        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        if ([mode isEqualToString:@"slow-activation"])
            controller.slowActivation = YES;
        else if ([mode isEqualToString:@"activation-never-settles"])
            controller.activationNeverSettles = YES;
        else if ([mode isEqualToString:@"missing-content"])
            operator.contentAvailable = NO;
        else if ([mode isEqualToString:@"self-target"])
            target.processIdentifier = getpid();
        else if ([mode isEqualToString:@"mutable-pid"]) {
            secondTarget.processIdentifier = 101;
            target.alternateProcessIdentifier = 202;
            target.changesPIDAfterFirstRead = YES;
            target.frontmostAfterActivation = secondTarget;
        } else if ([mode isEqualToString:@"same-target-reentrant-overlap"]) {
            target.reenterSameTargetSessionOnActivation = YES;
        } else if ([mode isEqualToString:@"menu-selection"] ||
                   [mode isEqualToString:@"search-window-selection"] ||
                   [mode isEqualToString:@"search-window-cancel"])
            ;
        if ([mode isEqualToString:@"menu-selection"]) {
            [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"menuSelectionPastes"];
            NSMenuItem *item = [[[NSMenuItem alloc] initWithTitle:@"fixture"
                                                           action:nil
                                                    keyEquivalent:@""] autorelease];
            [controller processMenuClippingSelection:item];
        } else if ([mode isEqualToString:@"search-window-selection"]) {
            [controller showSearchWindow];
            [controller searchWindowItemSelected:nil];
        } else if ([mode isEqualToString:@"search-window-cancel"]) {
            [controller showSearchWindow];
            if (![controller hasRememberedPasteTarget]) return 44;
            [controller hideSearchWindow];
        } else {
            [controller hitMainHotKey:nil];
            [controller metaKeysReleased];
            if ([mode isEqualToString:@"duplicate-release"])
                [controller metaKeysReleased];
            if ([mode isEqualToString:@"late-duplicate-release"])
                [controller performSelector:@selector(metaKeysReleased) withObject:nil afterDelay:0.7];
        }
        if ([mode isEqualToString:@"escape"])
            [controller performSelector:@selector(triggerEscape) withObject:nil afterDelay:0.1];
        else if ([mode isEqualToString:@"focus-theft"])
            [controller performSelector:@selector(stealFocus) withObject:nil afterDelay:0.525];
        else if ([mode isEqualToString:@"pre-activation-focus-theft"])
            [controller performSelector:@selector(stealFocus) withObject:nil afterDelay:0.3];
        else if ([mode isEqualToString:@"overlap"])
            [controller performSelector:@selector(beginSecondSession:)
                              withObject:secondTarget
                              afterDelay:0.3];
        else if ([mode isEqualToString:@"overlap-after-activation"])
            [controller performSelector:@selector(beginSecondSession:)
                              withObject:secondTarget
                              afterDelay:0.525];
        else if ([mode isEqualToString:@"overlap-release"])
            [controller performSelector:@selector(beginSecondSessionAndRelease:)
                              withObject:secondTarget
                              afterDelay:0.1];
        else if ([mode isEqualToString:@"retarget"])
            [controller performSelector:@selector(replaceRememberedTargetWithoutCancellation:)
                              withObject:secondTarget
                              afterDelay:0.3];
        else if ([mode isEqualToString:@"terminated"])
            [controller performSelector:@selector(terminateTarget) withObject:nil afterDelay:0.3];
        else if ([mode isEqualToString:@"mutable-pid"])
            [controller performSelector:@selector(useFocusThiefAsFrontmost) withObject:nil afterDelay:0.3];
        else if ([mode isEqualToString:@"menu-selection-disabled-overlap"])
            [controller performSelector:@selector(selectMenuItemWithoutImmediatePaste)
                              withObject:nil
                              afterDelay:0.1];
        else if ([mode isEqualToString:@"slow-activation"])
            ;
        else if ([mode isEqualToString:@"activation-never-settles"])
            ;
        else if ([mode isEqualToString:@"missing-content"])
            ;
        else if ([mode isEqualToString:@"duplicate-release"] || [mode isEqualToString:@"late-duplicate-release"])
            ;
        else if ([mode isEqualToString:@"self-target"])
            ;
        else if ([mode isEqualToString:@"same-target-reentrant-overlap"])
            ;
        else if ([mode isEqualToString:@"menu-selection"])
            ;
        else if ([mode isEqualToString:@"search-window-selection"])
            ;
        else if ([mode isEqualToString:@"search-window-cancel"])
            ;
        else if ([mode isEqualToString:@"menu-selection-disabled-overlap"])
            ;
        else
            return 3;
        NSTimeInterval runDuration = [mode isEqualToString:@"activation-never-settles"] ? 3.0 : 1.5;
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:runDuration]];

        if ([mode isEqualToString:@"menu-selection"]) {
            if (controller.pasteboardCount != 1) return 31;
            if (controller.globalPasteCount != 0) return 32;
            if (controller.targetedPasteCount != 1) return 33;
            if (controller.lastPostedProcessIdentifier != 101) return 34;
        } else if ([mode isEqualToString:@"search-window-selection"]) {
            if (controller.pasteboardCount != 1) return 39;
            if (controller.globalPasteCount != 0) return 40;
            if (controller.targetedPasteCount != 1) return 41;
            if (controller.lastPostedProcessIdentifier != 101) return 42;
            if ([controller hasRememberedPasteTarget]) return 43;
        } else if ([mode isEqualToString:@"search-window-cancel"]) {
            if (controller.pasteboardCount != 0) return 45;
            if (controller.globalPasteCount != 0 || controller.targetedPasteCount != 0) return 46;
            if ([controller hasRememberedPasteTarget]) return 47;
        } else if ([mode isEqualToString:@"menu-selection-disabled-overlap"]) {
            if (controller.pasteboardCount != 2) return 35;
            if (controller.globalPasteCount != 0) return 36;
            if (controller.targetedPasteCount != 0) return 37;
            if ([controller hasRememberedPasteTarget]) return 38;
        } else if ([mode isEqualToString:@"overlap-release"] ||
            [mode isEqualToString:@"slow-activation"] ||
            [mode isEqualToString:@"mutable-pid"] ||
            [mode isEqualToString:@"duplicate-release"] || [mode isEqualToString:@"late-duplicate-release"]) {
            NSInteger expectedPasteboardCount = [mode isEqualToString:@"overlap-release"] ? 2 : 1;
            if (controller.pasteboardCount != expectedPasteboardCount) return 13;
            if (controller.globalPasteCount != 0) return 14;
            if (controller.targetedPasteCount != 1) return 15;
            if ([mode isEqualToString:@"mutable-pid"] && controller.lastPostedProcessIdentifier != 101)
                return 16;
            if ([mode isEqualToString:@"slow-activation"] && controller.frontmostQueryCount != 4)
                return 17;
        } else if ([mode isEqualToString:@"missing-content"]) {
            if (controller.pasteboardCount != 0) return 19;
            if (controller.globalPasteCount != 0 || controller.targetedPasteCount != 0) return 20;
            if ([controller hasRememberedPasteTarget]) return 21;
        } else if ([mode isEqualToString:@"same-target-reentrant-overlap"]) {
            if (controller.pasteboardCount != 1) return 22;
            if (controller.globalPasteCount != 0 || controller.targetedPasteCount != 0) return 23;
            if (![controller hasRememberedPasteTarget]) return 24;
            if (![controller isSelectionDisplayed]) return 25;
        } else {
            if (controller.pasteboardCount != 1) return 11;
            if (controller.globalPasteCount != 0 || controller.targetedPasteCount != 0) return 12;
        }
        NSInteger expectedHideCount =
            ([mode isEqualToString:@"menu-selection-disabled-overlap"] ||
             [mode isEqualToString:@"search-window-selection"] ||
             [mode isEqualToString:@"search-window-cancel"]) ? 0 : 1;
        if (controller.hideCount != expectedHideCount) return 18;
        if ([mode isEqualToString:@"activation-never-settles"] &&
            controller.frontmostQueryCount != 9) return 30 + (int)controller.frontmostQueryCount;

        [operator release];
        [secondTarget release];
        [target release];
        [controller release];
    }
    return 0;
}
'''


class PendingPasteTransactionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PasteNativeTestSupport import build_fixture
        cls.binary = build_fixture(FIXTURE, "PendingPasteFixture")

    def _run_fixture(self, mode):
        from PasteNativeTestSupport import run_fixture
        return run_fixture(self.binary, mode)

    def test_late_modifier_release_does_not_repeat_the_same_invocation(self):
        run = self._run_fixture("late-duplicate-release")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_escape_invalidates_a_delayed_modifier_release_paste(self) -> None:
        run = self._run_fixture("escape")
        self.assertEqual(
            run.returncode, 0,
            f"Escape allowed a delayed paste; exit={run.returncode}\n{run.stderr}",
        )

    def test_focus_theft_aborts_the_delayed_global_paste(self) -> None:
        run = self._run_fixture("focus-theft")
        self.assertEqual(
            run.returncode, 0,
            f"focus theft redirected a delayed paste; exit={run.returncode}\n{run.stderr}",
        )

    def test_focus_theft_before_activation_cannot_be_undone_by_reactivating_the_old_target(self) -> None:
        run = self._run_fixture("pre-activation-focus-theft")
        self.assertEqual(
            run.returncode, 0,
            f"pre-activation focus theft was overwritten by forced target activation; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_flycut_cannot_capture_itself_via_a_distinct_running_application_object(self) -> None:
        run = self._run_fixture("self-target")
        self.assertEqual(
            run.returncode, 0,
            f"Flycut captured its own PID as a paste target; exit={run.returncode}\n{run.stderr}",
        )

    def test_posting_uses_the_same_pid_value_that_was_frontmost_validated(self) -> None:
        run = self._run_fixture("mutable-pid")
        self.assertEqual(
            run.returncode, 0,
            f"paste posting re-read and changed the already validated PID; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_new_hotkey_session_invalidates_the_previous_delayed_paste(self) -> None:
        run = self._run_fixture("overlap")
        self.assertEqual(
            run.returncode, 0,
            f"a new selection inherited the previous delayed paste; exit={run.returncode}\n{run.stderr}",
        )

    def test_new_hotkey_session_can_complete_its_own_paste(self) -> None:
        run = self._run_fixture("overlap-release")
        self.assertEqual(
            run.returncode, 0,
            f"a new selection was suppressed by the previous selection; exit={run.returncode}\n{run.stderr}",
        )

    def test_delayed_callbacks_are_bound_to_their_original_target(self) -> None:
        run = self._run_fixture("retarget")
        self.assertEqual(
            run.returncode, 0,
            f"a delayed paste followed mutable target state; exit={run.returncode}\n{run.stderr}",
        )

    def test_terminated_target_aborts_the_delayed_paste(self) -> None:
        run = self._run_fixture("terminated")
        self.assertEqual(
            run.returncode, 0,
            f"a terminated target still received a delayed paste; exit={run.returncode}\n{run.stderr}",
        )

    def test_activation_gets_a_bounded_settle_window_before_paste(self) -> None:
        run = self._run_fixture("slow-activation")
        self.assertEqual(
            run.returncode, 0,
            f"a valid target was abandoned before activation settled; exit={run.returncode}\n{run.stderr}",
        )

    def test_activation_settle_polling_has_a_hard_retry_bound(self) -> None:
        run = self._run_fixture("activation-never-settles")
        self.assertEqual(
            run.returncode, 0,
            f"activation settling exceeded its retry bound; exit={run.returncode}\n{run.stderr}",
        )

    def test_missing_content_clears_the_transaction_without_pasting(self) -> None:
        run = self._run_fixture("missing-content")
        self.assertEqual(
            run.returncode, 0,
            f"missing clipping content left a live paste transaction; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_duplicate_modifier_release_pastes_exactly_once(self) -> None:
        run = self._run_fixture("duplicate-release")
        self.assertEqual(
            run.returncode, 0,
            f"duplicate modifier release caused zero or multiple pastes; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_new_session_cancels_a_post_callback_already_scheduled_after_activation(self) -> None:
        run = self._run_fixture("overlap-after-activation")
        self.assertEqual(
            run.returncode, 0,
            f"a new session inherited a post callback already scheduled after activation; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_reentrant_same_target_session_invalidates_the_callback_already_executing(self) -> None:
        run = self._run_fixture("same-target-reentrant-overlap")
        self.assertEqual(
            run.returncode, 0,
            f"an executing stale callback adopted a new session for the same object and PID; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_menu_selection_paste_is_bound_to_the_captured_target_pid(self) -> None:
        run = self._run_fixture("menu-selection")
        self.assertEqual(
            run.returncode, 0,
            f"menu selection used a global or wrong-PID paste instead of exactly one captured target; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_search_window_selection_is_bound_to_the_captured_target_pid(self) -> None:
        run = self._run_fixture("search-window-selection")
        self.assertEqual(
            run.returncode, 0,
            f"search-window selection used a global, duplicate, or wrong-PID paste; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_closing_search_window_cancels_its_pending_paste_transaction(self) -> None:
        run = self._run_fixture("search-window-cancel")
        self.assertEqual(
            run.returncode, 0,
            f"closing the search window left a live transaction or posted a paste; "
            f"exit={run.returncode}\n{run.stderr}",
        )

    def test_copy_only_menu_selection_cancels_an_older_delayed_paste(self) -> None:
        run = self._run_fixture("menu-selection-disabled-overlap")
        self.assertEqual(
            run.returncode, 0,
            f"copy-only menu selection allowed an older delayed paste to post the new clipboard value; "
            f"exit={run.returncode}\n{run.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
