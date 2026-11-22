#!/usr/bin/env python3
"""Command-W closes the Preferences window, as it closes the front window everywhere on the Mac.

On the Mac, Command-W is the Close item of an app's File menu. Flycut is a menu-bar app without a
main menu: MainMenu.xib's application object has no mainMenu outlet, and its hidden Edit menu is a
submenu of the status menu, which AppKit asks for key equivalents only while that menu is open.
So no Close command reached any Flycut window; the search window and the clipping list handle
their own Command keys, and Preferences did not, so Command-W only beeped there.

Preferences now handles Command-W itself, through a local key-down monitor added the first time
it opens: for a Command-W (Command alone) aimed at the Preferences window, its controls get the
key first, as they would from a menu, and if none takes it the window closes as with its close
button. A hotkey recorder that is recording takes Command-W as its new hotkey and the window stays
open. Other windows (the search window with its own Command-W, a sheet such as the folder chooser)
and other keys pass on unchanged. A main menu with File > Close would also reach the About window,
but ShortcutRecorder's validator reads the main menu, so Command-W could then no longer be recorded
as a hotkey (it would refuse it with an alert); that is why the key is handled here.

The fixture loads the production NIB (Tests/Fixtures/PreferencesNibFixture.py), opens Preferences
through the real -showPreferencePanel: (never ordered in) and delivers key events as AppKit does:
the app's local key-down monitors first, in the order they were added, then the window's key
equivalents. +[NSEvent addLocalMonitorForEventsMatchingMask:handler:] and -[NSEvent window] are
replaced to capture the monitors and to aim an event at a window. Real key presses are not posted.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

FIXTURE = r'''
static BOOL gVisible = NO;
static int gCloses = 0, gSearchHides = 0;
static NSWindow *gEventWindow = nil;
static NSMutableArray *gKeyMonitors = nil;

static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; }
static id FakeAcknowledgements(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc; if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? gVisible : NO; }
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender) { (void)cmd; (void)sender; if (self == window) gVisible = YES; }
static void FakeClose(NSWindow *self, SEL cmd)
{
    (void)cmd;
    if (self != window) return;
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowWillCloseNotification object:self];
    gCloses++;
    gVisible = NO;
}
static void FakeHideSearchWindow(id self, SEL cmd) { (void)self; (void)cmd; gSearchHides++; }
static NSWindow *FakeEventWindow(NSEvent *self, SEL cmd) { (void)self; (void)cmd; return gEventWindow; }
static id FakeAddLocalMonitor(id self, SEL cmd, NSEventMask mask, NSEvent *(^handler)(NSEvent *))
{
    (void)self; (void)cmd;
    if (mask & NSEventMaskKeyDown)
        [gKeyMonitors addObject:[[handler copy] autorelease]];
    return [[[NSObject alloc] init] autorelease];
}

static NSEvent *Key(NSString *characters, unsigned short keyCode, NSEventModifierFlags flags)
{
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0 windowNumber:0
                             context:nil characters:characters charactersIgnoringModifiers:characters isARepeat:NO keyCode:keyCode];
}
static NSEvent *CommandW(void) { return Key(@"w", 13, NSEventModifierFlagCommand); }

// As AppKit delivers a key-down to a window: the app's local monitors, then (for a key
// with Command) the window's key equivalents. *passed says whether the monitors let it on.
static BOOL Deliver(NSEvent *event, NSWindow *target, BOOL *passed)
{
    gEventWindow = target;
    NSEvent *original = event;
    for (NSEvent *(^handler)(NSEvent *) in [[gKeyMonitors copy] autorelease]) {
        event = handler(event);
        if (event == nil) break;
    }
    if (passed) *passed = event == original;
    if (event == nil) return YES;
    return ([event modifierFlags] & NSEventModifierFlagCommand) ? [target performKeyEquivalent:event] : NO;
}

static NSMutableDictionary *report;
static int Fail(int code, NSString *what) { report[@"failure"] = what; Emit(report); return code; }

int main(int argc, const char **argv)
{
    @autoreleasepool {
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        report = [NSMutableDictionary dictionaryWithObject:mode forKey:@"mode"];
        gKeyMonitors = [[NSMutableArray alloc] init];
        method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
        method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeAcknowledgements);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(close)), (IMP)FakeClose);
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(hideSearchWindow)), (IMP)FakeHideSearchWindow);
        method_setImplementation(class_getInstanceMethod([NSEvent class], @selector(window)), (IMP)FakeEventWindow);
        method_setImplementation(class_getClassMethod([NSEvent class], @selector(addLocalMonitorForEventsMatchingMask:handler:)), (IMP)FakeAddLocalMonitor);
        ChangePane(generalPane);

        [controller showPreferencePanel:nil];
        report[@"keyMonitors"] = @([gKeyMonitors count]);
        if (!gVisible) return Fail(20, @"Preferences did not open");

        if ([mode isEqualToString:@"closes"]) {
            BOOL handled = Deliver(CommandW(), window, NULL);
            report[@"handled"] = @(handled);
            if (gCloses != 1 || gVisible)
                return Fail(21, [NSString stringWithFormat:@"Command-W left Preferences open (%d closes, %lu key monitors, handled %d)",
                                 gCloses, (unsigned long)[gKeyMonitors count], handled]);
            if (!handled) return Fail(22, @"Preferences closed, but the key went on to beep");
        } else if ([mode isEqualToString:@"closes-from-a-field"]) {
            // The focus in a text field (the field editor is the first responder).
            NSTextField *field = nil;
            for (NSView *view in [[[controller valueForKey:@"savingSectionLabel"] superview] subviews])
                if ([view isKindOfClass:[NSTextField class]] && [(NSTextField *)view isEditable]) field = (NSTextField *)view;
            if (field == nil || ![window makeFirstResponder:field] || ![[window firstResponder] isKindOfClass:[NSText class]])
                return Fail(23, @"no editable General field takes the focus");
            Deliver(CommandW(), window, NULL);
            if (gCloses != 1 || gVisible) return Fail(24, [NSString stringWithFormat:@"Command-W in a text field left Preferences open (%d closes)", gCloses]);
        } else if ([mode isEqualToString:@"other-keys-pass"]) {
            NSArray *keys = @[Key(@"w", 13, NSEventModifierFlagCommand | NSEventModifierFlagShift), Key(@"w", 13, NSEventModifierFlagCommand | NSEventModifierFlagOption),
                              Key(@"w", 13, NSEventModifierFlagCommand | NSEventModifierFlagControl), Key(@"w", 13, 0), Key(@"q", 12, NSEventModifierFlagCommand)];
            for (NSEvent *key in keys) {
                BOOL passed = NO;
                Deliver(key, window, &passed);
                if (!passed || gCloses != 0 || !gVisible)
                    return Fail(25, [NSString stringWithFormat:@"%@ with flags %lx did not pass on unchanged or closed Preferences (%d closes)",
                                     [key charactersIgnoringModifiers], (unsigned long)[key modifierFlags], gCloses]);
            }
            // Command-W aimed at another window (a sheet on Preferences, the bezel, ...) passes on too.
            NSWindow *other = [[[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 100, 100) styleMask:NSWindowStyleMaskTitled
                                                             backing:NSBackingStoreBuffered defer:YES] autorelease];
            gEventWindow = other;
            NSEvent *sent = CommandW(), *out = sent;
            for (NSEvent *(^handler)(NSEvent *) in gKeyMonitors) { out = handler(out); if (out == nil) break; }
            BOOL passed = out == sent;
            if (!passed || gCloses != 0 || !gVisible)
                return Fail(26, [NSString stringWithFormat:@"Command-W for another window did not pass on unchanged (%d closes)", gCloses]);
        } else if ([mode isEqualToString:@"recording-keeps-the-key"]) {
            ChangePane(hotkeysPane);
            SRRecorderControl *recorder = [controller valueForKey:@"mainRecorder"];
            if (recorder == nil || ![window makeFirstResponder:recorder]) return Fail(27, @"the main hotkey recorder does not take the focus");
            if (![recorder performKeyEquivalent:Key(@" ", 49, 0)] || ![[[recorder cell] valueForKey:@"isRecording"] boolValue])
                return Fail(28, @"Space does not start recording");
            BOOL handled = Deliver(CommandW(), window, NULL);
            KeyCombo combo = [recorder keyCombo];
            report[@"recorded"] = @{@"code": @(combo.code), @"flags": @(combo.flags)};
            if (gCloses != 0 || !gVisible)
                return Fail(29, [NSString stringWithFormat:@"Command-W closed Preferences while the hotkey recorder was recording (%d closes)", gCloses]);
            if (!handled || combo.code != 13 || !(combo.flags & NSEventModifierFlagCommand))
                return Fail(30, [NSString stringWithFormat:@"the recording recorder did not take Command-W (code %ld, flags %lx)", (long)combo.code, (unsigned long)combo.flags]);
        } else if ([mode isEqualToString:@"search-window-keeps-its-key"]) {
            Class searchClass = NSClassFromString(@"SearchWindow");
            if (searchClass == Nil) return Fail(31, @"no SearchWindow class");
            NSWindow *search = [[[searchClass alloc] initWithContentRect:NSMakeRect(0, 0, 200, 100) styleMask:NSWindowStyleMaskTitled
                                                                backing:NSBackingStoreBuffered defer:YES] autorelease];
            [search setValue:controller forKey:@"appController"];
            BOOL passed = NO;
            BOOL handled = Deliver(CommandW(), search, &passed);
            if (!passed || !handled || gSearchHides != 1 || gCloses != 0 || !gVisible)
                return Fail(32, [NSString stringWithFormat:@"Command-W in the search window: passed %d, handled %d, %d hides, %d closes of Preferences",
                                 passed, handled, gSearchHides, gCloses]);
        } else if ([mode isEqualToString:@"added-once"]) {
            for (int i = 0; i < 3; i++) { [window close]; [controller showPreferencePanel:nil]; [controller showPreferencePanel:nil]; }
            report[@"keyMonitors"] = @([gKeyMonitors count]);
            if ([gKeyMonitors count] != 1)
                return Fail(33, [NSString stringWithFormat:@"%lu key-down monitors after opening Preferences seven times, not 1", (unsigned long)[gKeyMonitors count]]);
            Deliver(CommandW(), window, NULL);
            if (gCloses != 4 || gVisible) return Fail(34, [NSString stringWithFormat:@"Command-W after reopening: %d closes", gCloses]);
        } else {
            return 4;
        }
        Emit(report);
        return 0;
    }
}
'''


class PreferencesCloseKeyRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "CloseKey"

    def test_command_w_closes_preferences(self) -> None:
        self.run_mode("closes", "Command-W does not close Preferences")

    def test_command_w_closes_preferences_from_a_text_field(self) -> None:
        self.run_mode("closes-from-a-field", "Command-W does not close Preferences while a text field has the focus")

    def test_other_keys_and_other_windows_pass_on(self) -> None:
        self.run_mode("other-keys-pass", "a key other than Command-W, or Command-W for another window, is taken or closes Preferences")

    def test_a_recording_hotkey_recorder_takes_command_w(self) -> None:
        self.run_mode("recording-keeps-the-key", "Command-W closes Preferences while a hotkey recorder records, or the recorder misses it")

    def test_the_search_window_keeps_its_command_w(self) -> None:
        self.run_mode("search-window-keeps-its-key", "the search window's own Command-W no longer hides it, or closes Preferences")

    def test_the_key_handling_is_added_once(self) -> None:
        self.run_mode("added-once", "opening Preferences again adds another key-down monitor, or Command-W stops working")


if __name__ == "__main__":
    unittest.main()
