#!/usr/bin/env python3
"""Native regression tests for the factory default of the search hotkey.

The fixture links the production AppController, ShortcutRecorder and
SGHotKeysLib sources. Tests/Fixtures/FixtureIsolation.h keeps user defaults in
process memory. RegisterEventHotKey, UnregisterEventHotKey and
CopySymbolicHotKeys are defined by the fixture itself, so the linker binds
SGHotKeyCenter and SRValidator to these recorders: no global hotkey is
registered and the result does not depend on this Mac's system shortcuts.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"

FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#import <objc/runtime.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "SRRecorderControl.h"
#import "SRRecorderCell.h"
#import "SRCommon.h"

static UInt32 registeredCodes[8], registeredModifiers[8];
static NSUInteger registrations;

// Bound by the linker instead of HIToolbox's: records, registers nothing.
OSStatus RegisterEventHotKey(UInt32 code, UInt32 modifiers, EventHotKeyID hotKeyID, EventTargetRef target,
                             OptionBits options, EventHotKeyRef *outRef)
{
    (void)hotKeyID; (void)target; (void)options;
    if (registrations < 8) {
        registeredCodes[registrations] = code;
        registeredModifiers[registrations] = modifiers;
    }
    registrations++;
    if (outRef) *outRef = (EventHotKeyRef)(uintptr_t)(0x1000 + registrations);
    return noErr;
}

OSStatus UnregisterEventHotKey(EventHotKeyRef hotKey)
{
    (void)hotKey;
    return noErr;
}

// No system shortcut is taken: the recorder's own rules decide.
OSStatus CopySymbolicHotKeys(CFArrayRef *outHotKeyArray)
{
    *outHotKeyArray = CFArrayCreate(NULL, NULL, 0, &kCFTypeArrayCallBacks);
    return noErr;
}

static const NSUInteger ControlShift = NSEventModifierFlagControl | NSEventModifierFlagShift;

static SRRecorderControl *MakeRecorder(AppController *controller)
{
    SRRecorderControl *recorder = [[[SRRecorderControl alloc] initWithFrame:NSMakeRect(20, 20, 256, 22)] autorelease];
    [recorder setDelegate:controller];
    [controller setValue:recorder forKey:@"searchRecorder"];
    return recorder;
}

static NSDictionary *SearchDefault(void)
{
    return [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder searchHotkey"];
}

// What -awakeFromNib does with the stored value at launch.
static void LoadSearchCombo(SRRecorderControl *recorder)
{
    NSDictionary *value = SearchDefault();
    if (value)
        [recorder setKeyCombo:SRMakeKeyCombo([[value objectForKey:@"keyCode"] intValue],
                                             [[value objectForKey:@"modifierFlags"] intValue])];
}

static int FactoryDefault(AppController *controller)
{
    (void)controller;
    NSDictionary *search = SearchDefault();
    NSDictionary *main = [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder mainHotkey"];
    if ([[search objectForKey:@"keyCode"] integerValue] != 1 ||
        [[search objectForKey:@"modifierFlags"] unsignedIntegerValue] != ControlShift ||
        [search count] != 2) {
        fprintf(stderr, "registered search default is %s, expected keyCode 1 (S) with Control-Shift\n",
                [[search description] UTF8String]);
        return 20;
    }
    if (ControlShift != 393216 || ([[search objectForKey:@"modifierFlags"] unsignedIntegerValue] & NSEventModifierFlagCommand))
        return 21;
    // Same storage format as the main hotkey: Cocoa modifier flags (Shift-Command = 1179648).
    if ([[main objectForKey:@"keyCode"] integerValue] != 9 ||
        [[main objectForKey:@"modifierFlags"] unsignedIntegerValue] != (NSEventModifierFlagShift | NSEventModifierFlagCommand) ||
        [[main objectForKey:@"modifierFlags"] unsignedIntegerValue] != 1179648)
        return 22;
    return 0;
}

static int Display(AppController *controller)
{
    SRRecorderControl *recorder = MakeRecorder(controller);
    [recorder setKeyCombo:SRMakeKeyCombo(1, ControlShift)];
    if ([recorder keyCombo].code != 1 || [recorder keyCombo].flags != ControlShift) return 30;
    NSString *key = SRStringForKeyCode(1);
    NSString *shown = [recorder keyComboString];
    if ([key length] == 0 || ![shown isEqualToString:[@"\u2303\u21e7" stringByAppendingString:key]] ||
        [shown rangeOfString:@"\u2318"].location != NSNotFound) {
        fprintf(stderr, "recorder shows %s for Control-Shift-%s\n", [shown UTF8String], [key UTF8String]);
        return 31;
    }
    return 0;
}

// The user records Control-Shift-S in the field: the recorder accepts a
// combination without Command, stores it and registers it as a hotkey.
static int Record(AppController *controller)
{
    SRRecorderControl *recorder = MakeRecorder(controller);
    NSWindow *window = [[[NSWindow alloc] initWithContentRect:NSMakeRect(-30000, -30000, 300, 60)
                                                    styleMask:NSWindowStyleMaskBorderless
                                                      backing:NSBackingStoreBuffered defer:NO] autorelease];
    [window setReleasedWhenClosed:NO];
    [[window contentView] addSubview:recorder];
    [recorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagCommand | NSEventModifierFlagControl)];
    if (![window makeFirstResponder:recorder]) return 40;
    NSEvent *space = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
                                  windowNumber:[window windowNumber] context:nil characters:@" "
                   charactersIgnoringModifiers:@" " isARepeat:NO keyCode:49];
    [recorder keyDown:space];
    if (![[[recorder cell] valueForKey:@"isRecording"] boolValue]) return 41;
    NSUInteger before = registrations;
    NSEvent *combo = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:ControlShift timestamp:0
                                  windowNumber:[window windowNumber] context:nil characters:@"\x13"
                   charactersIgnoringModifiers:@"S" isARepeat:NO keyCode:1];
    [recorder performKeyEquivalent:combo];
    if ([recorder keyCombo].code != 1 || ([recorder keyCombo].flags & ~NSEventModifierFlagFunction) != ControlShift) {
        fprintf(stderr, "recorded combo is code %ld flags %lu\n", (long)[recorder keyCombo].code,
                (unsigned long)[recorder keyCombo].flags);
        return 42;
    }
    if (registrations != before + 1 || registeredCodes[before] != 1 ||
        registeredModifiers[before] != (controlKey | shiftKey)) {
        fprintf(stderr, "registered %lu hotkeys, last code %u modifiers 0x%x\n", (unsigned long)(registrations - before),
                registeredCodes[before], registeredModifiers[before]);
        return 43;
    }
    NSDictionary *stored = SearchDefault();
    if ([[stored objectForKey:@"keyCode"] integerValue] != 1 ||
        [[stored objectForKey:@"modifierFlags"] unsignedIntegerValue] != ControlShift)
        return 44;
    return 0;
}

// At launch the factory default goes through SGHotKeyCenter with Carbon flags.
static int LaunchRegisters(AppController *controller)
{
    SRRecorderControl *recorder = MakeRecorder(controller);
    LoadSearchCombo(recorder);
    NSUInteger before = registrations;
    [controller toggleSearchHotKey:[NSNull null]];
    if (registrations != before + 1) {
        fprintf(stderr, "the default search hotkey was not registered (%lu registrations)\n", (unsigned long)(registrations - before));
        return 50;
    }
    UInt32 modifiers = registeredModifiers[before];
    if (registeredCodes[before] != 1 || modifiers != (controlKey | shiftKey) || (modifiers & cmdKey)) {
        fprintf(stderr, "registered code %u modifiers 0x%x, expected 1 and controlKey|shiftKey 0x%x\n",
                registeredCodes[before], modifiers, (unsigned)(controlKey | shiftKey));
        return 51;
    }
    // Since macOS 15 a global hotkey needs a modifier other than Shift and Option.
    if (!(modifiers & (controlKey | cmdKey))) return 52;
    return 0;
}

// Users who cleared or changed the shortcut keep their stored value.
static int StoredValueWins(AppController *controller, NSDictionary *stored, NSInteger expectedCode, NSUInteger expectedRegistrations)
{
    SRRecorderControl *recorder = MakeRecorder(controller);
    LoadSearchCombo(recorder);
    if ([recorder keyCombo].code != expectedCode) {
        fprintf(stderr, "stored %s, recorder shows code %ld\n", [[stored description] UTF8String], (long)[recorder keyCombo].code);
        return 60;
    }
    NSUInteger before = registrations;
    [controller toggleSearchHotKey:[NSNull null]];
    if (registrations - before != expectedRegistrations) return 61;
    NSDictionary *now = SearchDefault();
    if ([[now objectForKey:@"keyCode"] integerValue] != [[stored objectForKey:@"keyCode"] integerValue] ||
        [[now objectForKey:@"modifierFlags"] unsignedIntegerValue] != [[stored objectForKey:@"modifierFlags"] unsignedIntegerValue])
        return 62;
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 2) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        [NSApplication sharedApplication];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        NSDictionary *cleared = @{@"keyCode": @(-1), @"modifierFlags": @0};
        NSDictionary *custom = @{@"keyCode": @11, @"modifierFlags": @(NSEventModifierFlagCommand | NSEventModifierFlagControl)};
        // A value the user stored earlier is in the user domain before launch.
        if ([mode isEqualToString:@"cleared"])
            [[NSUserDefaults standardUserDefaults] setObject:cleared forKey:@"ShortcutRecorder searchHotkey"];
        if ([mode isEqualToString:@"custom"])
            [[NSUserDefaults standardUserDefaults] setObject:custom forKey:@"ShortcutRecorder searchHotkey"];
        AppController *controller = [[AppController alloc] init];
        if ([mode isEqualToString:@"factory-default"]) return FactoryDefault(controller);
        if ([mode isEqualToString:@"display"]) return Display(controller);
        if ([mode isEqualToString:@"record"]) return Record(controller);
        if ([mode isEqualToString:@"launch"]) return LaunchRegisters(controller);
        if ([mode isEqualToString:@"cleared"]) return StoredValueWins(controller, cleared, -1, 0);
        if ([mode isEqualToString:@"custom"]) return StoredValueWins(controller, custom, 11, 1);
        return 4;
    }
}
'''


class SearchHotkeyDefaultRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-search-hotkey-")
        temp = pathlib.Path(cls.temp.name)
        sources = [
            ROOT / path
            for path in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
            if path != "main.m" and not path.startswith(("FlycutHelper/", "Tests/"))
        ]
        fixture = temp / "SearchHotkeyFixture.m"
        fixture.write_text(FIXTURE)
        cls.binary = temp / "SearchHotkeyFixture"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64", "-w",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, *(path.parent for path in sources)}):
            command += ["-I", str(include)]
        command += [str(path) for path in sources] + [str(fixture)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_mode(self, mode: str) -> None:
        run = subprocess.run([str(self.binary), mode], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_fixture_cannot_register_real_hotkeys(self) -> None:
        imported = subprocess.run(["/usr/bin/nm", "-u", str(self.binary)], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.split()
        for symbol in ("_RegisterEventHotKey", "_UnregisterEventHotKey", "_CopySymbolicHotKeys"):
            self.assertNotIn(symbol, imported)

    def test_search_hotkey_defaults_to_control_shift_s(self) -> None:
        self.run_mode("factory-default")

    def test_default_is_registered_with_carbon_control_and_shift(self) -> None:
        self.run_mode("launch")

    def test_recorder_shows_a_combination_without_command(self) -> None:
        self.run_mode("display")

    def test_recorder_accepts_and_registers_control_shift_s(self) -> None:
        self.run_mode("record")

    def test_a_cleared_shortcut_stays_cleared(self) -> None:
        self.run_mode("cleared")

    def test_a_custom_shortcut_is_kept(self) -> None:
        self.run_mode("custom")

    def test_docs_name_the_default(self) -> None:
        readme = (ROOT / "readme.md").read_text()
        help_text = (ROOT / "help.md").read_text()
        self.assertRegex(readme, r"\|\s*Control\+Shift\+S\s*\|\s*Open search window")
        self.assertIn("Control-Shift-S", help_text)
        for text in (readme, help_text, (ROOT / "AppController.m").read_text()):
            self.assertNotRegex(text, r"(?i)colou?r picker in iWork")


if __name__ == "__main__":
    unittest.main()
