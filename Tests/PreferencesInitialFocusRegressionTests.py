#!/usr/bin/env python3
"""Opening Preferences, again and again, leaves no field with a focus ring.

When a window becomes visible AppKit makes the first view of its key-view loop that can
take the focus (a text field, never a checkbox without Full Keyboard Access) the first
responder, or keeps the one of the last opening. Before the General pane's three numbers
were typeable, that was the "Password data types" field far down the pane; with them it is
the "Remember" field at the top, in the capsule look, so Preferences opened with a blue
ring round a field the user had not chosen. -[AppController showPreferencePanel:] hands the
first responder back to the window once the window is shown, so the ring appears only
after a click or Tab, and an already open window keeps what the user chose.

The fixture loads the production NIB (master's compiled MainMenu.nib for trees that carry
only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py), sends the builders that
-awakeFromNib sends and calls the real -showPreferencePanel:. The window is never ordered
in: -makeKeyAndOrderFront: is replaced by what AppKit does to the first responder when a
window becomes visible (the private -_setUpFirstResponderBeforeBecomingVisible, found on
this macOS; the case fails if it is missing instead of passing without it), and
-isVisible and -close follow that. Tab from a window without a first responder is
approximated by the private -_selectFirstKeyView. The pixels of the ring are not
reproduced here (offscreen windows draw none), only who is first responder.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

FIXTURE = r'''
static BOOL gVisible = NO;
static int gShows = 0, gActivations = 0;
static SEL gBecomeVisible, gSelectFirst;

static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; gActivations++; }
static id FakeAcknowledgements(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc; if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? gVisible : NO; }
// What AppKit does to the first responder when a window is ordered in and was not visible.
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender)
{
    (void)cmd; (void)sender;
    gShows++;
    if (self != window) return;
    if (!gVisible) ((void (*)(id, SEL))objc_msgSend)(self, gBecomeVisible);
    gVisible = YES;
}
static void FakeClose(NSWindow *self, SEL cmd)
{
    (void)cmd;
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowWillCloseNotification object:self];
    gVisible = NO;     // -close orders the window out; the first responder is left as it was
}

static NSTextField *FieldLabelled(NSView *root, NSString *label)
{
    if ([root isKindOfClass:[NSTextField class]] && [(NSTextField *)root isEditable] &&
        [[root accessibilityLabel] isEqualToString:label]) return (NSTextField *)root;
    for (NSView *sub in [root subviews]) {
        NSTextField *found = FieldLabelled(sub, label);
        if (found) return found;
    }
    return nil;
}

static NSString *Describe(id responder)
{
    if (responder == nil) return @"nothing";
    if (responder == window) return @"the window";
    if ([responder isKindOfClass:[NSText class]]) {
        id owner = [(NSText *)responder delegate];
        return [NSString stringWithFormat:@"the editor of the %@ field \"%@\"", NSStringFromClass([owner class]),
                [owner respondsToSelector:@selector(accessibilityLabel)] ? [owner accessibilityLabel] : @""];
    }
    return NSStringFromClass([responder class]);
}

static NSMutableDictionary *report;

static int Fail(int code, NSString *what)
{
    report[@"failure"] = what;
    Emit(report);
    return code;
}

// The user clicks a field of the shown General pane.
static BOOL Focus(NSTextField *field)
{
    return [window makeFirstResponder:field] && [window firstResponder] != window;
}

static NSTextField *Remember(void) { return FieldLabelled([window contentView], @"Remember"); }
static NSTextField *PasswordTypes(void) { return FieldLabelled([window contentView], @"Password data types"); }

int main(int argc, const char **argv)
{
    @autoreleasepool {
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        report = [NSMutableDictionary dictionaryWithObject:[NSString stringWithUTF8String:argv[2]] forKey:@"mode"];
        NSString *mode = [NSString stringWithUTF8String:argv[2]];

        gBecomeVisible = NSSelectorFromString(@"_setUpFirstResponderBeforeBecomingVisible");
        gSelectFirst = NSSelectorFromString(@"_selectFirstKeyView");
        if (![window respondsToSelector:gBecomeVisible] || ![window respondsToSelector:gSelectFirst])
            return Fail(20, @"this macOS has no AppKit first-responder step to stand in for ordering the window in");
        method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
        method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeAcknowledgements);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(close)), (IMP)FakeClose);
        ChangePane(generalPane);     // stands in for -[UKPrefsPanel awakeFromNib]
        if (Remember() == nil || PasswordTypes() == nil) return Fail(21, @"the General pane lacks the Remember or the Password data types field");

        if ([mode isEqualToString:@"first-opening"]) {
            [controller showPreferencePanel:nil];
            report[@"firstResponder"] = Describe([window firstResponder]);
            report[@"shown"] = @(gShows);
            if (gShows != 1) return Fail(22, @"-showPreferencePanel: did not order the window in once");
            if ([window firstResponder] != window) return Fail(30, [NSString stringWithFormat:@"the first responder after opening is %@, not the window", Describe([window firstResponder])]);
        } else if ([mode isEqualToString:@"reopened-after-remember"] || [mode isEqualToString:@"reopened-after-password-types"]) {
            BOOL remember = [mode isEqualToString:@"reopened-after-remember"];
            [controller showPreferencePanel:nil];
            if (!Focus(remember ? Remember() : PasswordTypes())) return Fail(23, @"the field did not take the focus");
            [window close];
            report[@"afterClose"] = Describe([window firstResponder]);
            [controller showPreferencePanel:nil];
            report[@"firstResponder"] = Describe([window firstResponder]);
            if ([window firstResponder] != window) return Fail(31, [NSString stringWithFormat:@"after closing with the focus in a field, opening again makes %@ the first responder", Describe([window firstResponder])]);
        } else if ([mode isEqualToString:@"opened-again-with-nothing-chosen"]) {
            [controller showPreferencePanel:nil];
            [window close];
            [controller showPreferencePanel:nil];
            report[@"firstResponder"] = Describe([window firstResponder]);
            if ([window firstResponder] != window) return Fail(32, [NSString stringWithFormat:@"the second opening makes %@ the first responder", Describe([window firstResponder])]);
        } else if ([mode isEqualToString:@"tab-enters-the-first-field"]) {
            [controller showPreferencePanel:nil];
            [window makeFirstResponder:nil];                             // nothing focused, however opening got there
            ((void (*)(id, SEL))objc_msgSend)(window, gSelectFirst);     // Tab with nothing focused
            report[@"afterTab"] = Describe([window firstResponder]);
            id editor = [window firstResponder];
            if (![editor isKindOfClass:[NSText class]] || [(NSText *)editor delegate] != Remember())
                return Fail(33, [NSString stringWithFormat:@"Tab after opening reaches %@, not the Remember field", Describe(editor)]);
        } else if ([mode isEqualToString:@"voiceover-focus"]) {
            [controller showPreferencePanel:nil];
            id focused = [window accessibilityFocusedUIElement];
            report[@"accessibilityFocused"] = focused == window ? @"the window" : NSStringFromClass([focused class]);
            if (focused != window) return Fail(34, @"VoiceOver's focus after opening is not the window");
            // The fields stay reachable for VoiceOver by name once they are focused.
            [window makeFirstResponder:Remember()];
            id named = [window accessibilityFocusedUIElement];
            if (![[named accessibilityLabel] isEqualToString:@"Remember"]) return Fail(35, @"a clicked Remember field is not VoiceOver's focus by name");
        } else if ([mode isEqualToString:@"open-window-keeps-the-focus"]) {
            [controller showPreferencePanel:nil];
            if (!Focus(Remember())) return Fail(23, @"Remember did not take the focus");
            NSText *editor = (NSText *)[window firstResponder];
            [editor setString:@"123"];
            [controller showPreferencePanel:nil];      // Preferences chosen again while open
            report[@"firstResponder"] = Describe([window firstResponder]);
            if ([window firstResponder] != editor) return Fail(36, [NSString stringWithFormat:@"choosing Preferences again took the focus from the Remember field (now %@)", Describe([window firstResponder])]);
            if (![[editor string] isEqualToString:@"123"]) return Fail(37, @"the typed text was lost");
        } else {
            return 4;
        }
        Emit(report);
        return 0;
    }
}
'''


class PreferencesInitialFocusRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "InitialFocus"

    def test_first_opening_leaves_nothing_focused(self) -> None:
        self.run_mode("first-opening", "opening Preferences focuses a field (blue ring) before the user chose one")

    def test_reopening_after_remember_was_focused_leaves_nothing_focused(self) -> None:
        self.run_mode("reopened-after-remember", "opening Preferences again focuses a field after Remember was focused")

    def test_reopening_after_another_field_was_focused_leaves_nothing_focused(self) -> None:
        self.run_mode("reopened-after-password-types", "opening Preferences again brings back the focus of the field the user left")

    def test_second_opening_without_any_click_leaves_nothing_focused(self) -> None:
        self.run_mode("opened-again-with-nothing-chosen", "opening Preferences a second time focuses a field")

    def test_tab_after_opening_enters_the_first_field(self) -> None:
        self.run_mode("tab-enters-the-first-field", "the key-view loop no longer lets Tab enter the first field")

    def test_voiceover_focus_after_opening_is_the_window(self) -> None:
        self.run_mode("voiceover-focus", "VoiceOver's focus after opening is a field or not nameable")

    def test_choosing_preferences_again_keeps_the_focus_of_an_open_window(self) -> None:
        self.run_mode("open-window-keeps-the-focus", "choosing Preferences while open takes the user's focus away")


if __name__ == "__main__":
    unittest.main()
