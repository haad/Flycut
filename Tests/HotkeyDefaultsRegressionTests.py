#!/usr/bin/env python3
"""Regression tests for the factory hotkeys and their one-time carry-over.

New installs get the bezel on Control-Option-Command-V and "Paste as plain text" on
Option-Shift-Command-V (Apple's "Paste and Match Style"); Flycut no longer takes
Shift-Command-V. Whoever ran an earlier Flycut keeps Shift-Command-V for the bezel: the first
launch of this version stores it explicitly, once (FlycutCarryOverHotkeyDefaults in
FlycutHotkeyDefaults.h); the plain-text hotkey is left to its factory value, unless an earlier
user's bezel or search hotkey is on that combination: then it is stored empty.

Fixture A compiles only FlycutHotkeyDefaults.h with Tests/Fixtures/FixtureIsolation.h (user
defaults in memory). -persistentDomainForName: answers like NSUserDefaults': only the stored
values, and only for the defaults' own domain. Fixture B links the production AppController,
ShortcutRecorder and SGHotKeysLib sources; RegisterEventHotKey, UnregisterEventHotKey and
CopySymbolicHotKeys are defined by the fixture, so no global hotkey is registered. B also pins
the bezel's key handling with the new modifiers (no Shift/Command assumption).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"

SHIFT, CONTROL, OPTION, COMMAND = 1 << 17, 1 << 18, 1 << 19, 1 << 20

DEFAULTS_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import "FixtureIsolation.h"
#import "FlycutHotkeyDefaults.h"

static NSString *const Domain = @"org.flycut.tests.hotkey-carry-over";
static NSString *const Main = @"ShortcutRecorder mainHotkey";
static NSString *const Plain = @"ShortcutRecorder plainPasteHotkey";
static NSString *const MarkerKey = @"hotkeyDefaultsMigrationCompleted";
static const NSUInteger ShiftCommand = NSEventModifierFlagShift | NSEventModifierFlagCommand;
static const NSUInteger ControlOptionCommand = NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand;
static const NSUInteger OptionShiftCommand = NSEventModifierFlagOption | NSEventModifierFlagShift | NSEventModifierFlagCommand;

// Like NSUserDefaults: the stored values only, and only for the defaults' own domain.
static NSUInteger domainQueries;
static NSDictionary *PersistentDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    domainQueries++;
    if (![name isEqualToString:Domain]) return nil;
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static id Stored(NSString *key)
{
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    return [(NSDictionary *)object_getIvar([NSUserDefaults standardUserDefaults], ivar) objectForKey:key];
}

static NSString *Describe(id value) { return value == nil ? @"not stored" : [value description]; }

static BOOL Combo(id value, NSInteger code, NSUInteger flags)
{
    return [value isKindOfClass:[NSDictionary class]] && [value count] == 2 &&
           [[value objectForKey:@"keyCode"] integerValue] == code &&
           [[value objectForKey:@"modifierFlags"] unsignedIntegerValue] == flags;
}

// What -[AppController init] registers, then one launch's carry-over.
static void Launch(NSString *domain)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults registerDefaults:@{Main: FlycutBezelHotkeyDefault(), Plain: FlycutPlainPasteHotkeyDefault()}];
    FlycutCarryOverHotkeyDefaults(defaults, domain);
}

static void Store(NSDictionary *values)
{
    for (NSString *key in values) [[NSUserDefaults standardUserDefaults] setObject:values[key] forKey:key];
}

// expected: nil = not stored, else the stored combination (code, flags).
static int Expect(NSString *what, id main, id plain)
{
    id storedMain = Stored(Main), storedPlain = Stored(Plain);
    BOOL mainOK = main == nil ? storedMain == nil : Combo(storedMain, [main[0] integerValue], [main[1] unsignedIntegerValue]);
    BOOL plainOK = plain == nil ? storedPlain == nil : Combo(storedPlain, [plain[0] integerValue], [plain[1] unsignedIntegerValue]);
    if (!mainOK || !plainOK) {
        fprintf(stderr, "%s: main hotkey %s, plain-text hotkey %s\n", [what UTF8String], [Describe(storedMain) UTF8String],
                [Describe(storedPlain) UTF8String]);
        return 20;
    }
    if (![Stored(MarkerKey) isEqual:@YES]) { fprintf(stderr, "%s: marker %s\n", [what UTF8String], [Describe(Stored(MarkerKey)) UTF8String]); return 21; }
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 2) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        if (!class_addMethod([FCMemoryDefaults class], @selector(persistentDomainForName:), (IMP)PersistentDomain, "@@:@")) return 4;
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        NSArray *previous = @[@9, @(ShiftCommand)];
        NSArray *cleared = @[@(-1), @0];
        NSArray *custom = @[@11, @(NSEventModifierFlagControl | NSEventModifierFlagCommand)];
        NSDictionary *history = @{@"jcList": @[], @"favoritesList": @[]};

        if ([mode isEqualToString:@"factory"]) {
            if (!Combo(FlycutBezelHotkeyDefault(), 9, ControlOptionCommand)) { fprintf(stderr, "bezel default %s\n", [[FlycutBezelHotkeyDefault() description] UTF8String]); return 30; }
            if (!Combo(FlycutPlainPasteHotkeyDefault(), 9, OptionShiftCommand)) { fprintf(stderr, "plain default %s\n", [[FlycutPlainPasteHotkeyDefault() description] UTF8String]); return 31; }
            if (!Combo(FlycutPreviousBezelHotkey(), 9, 1179648)) return 32;
            // Since macOS 15 a global hotkey needs a modifier other than Shift and Option.
            for (NSDictionary *value in @[FlycutBezelHotkeyDefault(), FlycutPlainPasteHotkeyDefault()])
                if (!([[value objectForKey:@"modifierFlags"] unsignedIntegerValue] & (NSEventModifierFlagCommand | NSEventModifierFlagControl))) return 33;
            // A new install leaves Shift-Command-V to the apps.
            if (Combo(FlycutBezelHotkeyDefault(), 9, ShiftCommand) || Combo(FlycutPlainPasteHotkeyDefault(), 9, ShiftCommand)) return 34;
            return 0;
        }
        if ([mode isEqualToString:@"fresh"]) { Launch(Domain); return Expect(mode, nil, nil); }
        if ([mode isEqualToString:@"appkit-keys-only"]) {
            Store(@{@"NSStatusItem Preferred Position Item-0": @1234, @"NSWindow Frame Preferences": @"0 0 500 500 0 0 1440 900 "});
            Launch(Domain);
            return Expect(mode, nil, nil);
        }
        // macOS writes into an app's domain without the app running: System Settings stores a
        // per-app language as AppleLanguages, App Shortcuts as NSUserKeyEquivalents.
        if ([mode isEqualToString:@"system-keys-only"]) {
            Store(@{@"AppleLanguages": @[@"de-DE"], @"NSUserKeyEquivalents": @{@"Preferences...": @"@;"},
                    @"NSStatusItem Visible Item-0": @YES});
            Launch(Domain);
            return Expect(mode, nil, nil);
        }
        // A user of the sandboxed Flycut who declined the import: the sandbox migration, which
        // runs first at launch, stored only its marker.
        if ([mode isEqualToString:@"sandbox-import-declined"]) {
            Store(@{@"sandboxMigrationCompleted": @YES, @"AppleLanguages": @[@"de-DE"]});
            Launch(Domain);
            return Expect(mode, previous, nil);
        }
        // Earlier users: the bezel keeps Shift-Command-V; the plain-text hotkey is not stored,
        // so the factory Option-Shift-Command-V applies to them too.
        if ([mode isEqualToString:@"existing-history"]) { Store(@{@"store": history}); Launch(Domain); return Expect(mode, previous, nil); }
        if ([mode isEqualToString:@"existing-any-key"]) { Store(@{@"loadOnStartup": @NO}); Launch(Domain); return Expect(mode, previous, nil); }
        if ([mode isEqualToString:@"existing-custom-bezel"]) {
            Store(@{@"loadOnStartup": @YES, Main: FlycutHotkeyValue(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)});
            Launch(Domain);
            return Expect(mode, custom, nil);
        }
        if ([mode isEqualToString:@"existing-cleared-bezel"]) {
            Store(@{@"store": history, Main: FlycutHotkeyValue(-1, 0)});
            Launch(Domain);
            return Expect(mode, cleared, nil);
        }
        if ([mode isEqualToString:@"existing-plain-stored"]) {
            // A plain-text hotkey stored by a build that had one (or a cleared one) is left alone.
            Store(@{@"store": history, Plain: FlycutHotkeyValue(-1, 0)});
            Launch(Domain);
            return Expect(mode, previous, cleared);
        }
        // An earlier user who put the bezel or the search window on Option-Shift-Command-V keeps
        // it there; the plain-text hotkey starts empty, as a cleared one (only the four modifiers
        // count). Elsewhere, and on a later launch, nothing of this is stored.
        if ([mode isEqualToString:@"existing-bezel-on-plain-default"]) {
            Store(@{@"store": history, Main: FlycutHotkeyValue(9, OptionShiftCommand)});
            Launch(Domain);
            return Expect(mode, @[@9, @(OptionShiftCommand)], cleared);
        }
        if ([mode isEqualToString:@"existing-search-on-plain-default"]) {
            Store(@{@"loadOnStartup": @YES,
                    @"ShortcutRecorder searchHotkey": FlycutHotkeyValue(9, OptionShiftCommand | NSEventModifierFlagFunction)});
            Launch(Domain);
            return Expect(mode, previous, cleared);
        }
        if ([mode isEqualToString:@"existing-plain-stored-bezel-on-plain-default"]) {
            // A plain-text hotkey stored already is the user's: it is left alone.
            Store(@{@"store": history, Main: FlycutHotkeyValue(9, OptionShiftCommand), Plain: FlycutHotkeyValue(11, ShiftCommand)});
            Launch(Domain);
            return Expect(mode, @[@9, @(OptionShiftCommand)], @[@11, @(ShiftCommand)]);
        }
        if ([mode isEqualToString:@"existing-bezel-on-other-key"]) {
            // The same modifiers on another key are no clash.
            Store(@{@"store": history, Main: FlycutHotkeyValue(11, OptionShiftCommand)});
            Launch(Domain);
            return Expect(mode, @[@11, @(OptionShiftCommand)], nil);
        }
        if ([mode isEqualToString:@"bezel-on-plain-default-after-the-check"]) {
            Store(@{@"store": history});
            Launch(Domain);
            Store(@{Main: FlycutHotkeyValue(9, OptionShiftCommand)});  // recorded after the first launch
            Launch(Domain);
            return Expect(mode, @[@9, @(OptionShiftCommand)], nil);
        }
        if ([mode isEqualToString:@"second-launch-fresh"]) {
            Launch(Domain);
            Store(@{@"loadOnStartup": @NO, @"store": history});  // what the first launch and its use store
            Launch(Domain);
            return Expect(mode, nil, nil);
        }
        if ([mode isEqualToString:@"second-launch-existing"]) {
            Store(@{@"store": history});
            Launch(Domain);
            // The user then restores the bezel default: it is dropped from the user domain
            // (equal to the registered one).
            [[NSUserDefaults standardUserDefaults] removeObjectForKey:Main];
            Launch(Domain);
            return Expect(mode, nil, nil);
        }
        if ([mode isEqualToString:@"marker-already-set"]) {
            Store(@{@"store": history, MarkerKey: @YES});
            Launch(Domain);
            return Expect(mode, nil, nil);
        }
        if ([mode isEqualToString:@"other-domain"]) {
            // Only the defaults' own domain counts; another app's data is not this user's Flycut.
            Store(@{@"store": history});
            Launch(@"org.flycut.tests.some-other-domain");
            if (domainQueries == 0) return 40;
            return Expect(mode, nil, nil);
        }
        if ([mode isEqualToString:@"no-domain"]) { Store(@{@"store": history}); Launch(nil); return Expect(mode, nil, nil); }
        return 5;
    }
}
'''

APP_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#import <objc/runtime.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "BezelWindow.h"
#import "SRRecorderControl.h"
#import "FlycutHotkeyDefaults.h"

static NSString *const Domain = @"org.flycut.tests.hotkey-launch";
static UInt32 lastCode, lastModifiers;
static NSUInteger registrations;

// Bound by the linker instead of HIToolbox's: records, registers nothing.
OSStatus RegisterEventHotKey(UInt32 code, UInt32 modifiers, EventHotKeyID hotKeyID, EventTargetRef target,
                             OptionBits options, EventHotKeyRef *outRef)
{
    (void)hotKeyID; (void)target; (void)options;
    lastCode = code; lastModifiers = modifiers; registrations++;
    if (outRef) *outRef = (EventHotKeyRef)(uintptr_t)(0x1000 + registrations);
    return noErr;
}
OSStatus UnregisterEventHotKey(EventHotKeyRef hotKey) { (void)hotKey; return noErr; }
OSStatus CopySymbolicHotKeys(CFArrayRef *outHotKeyArray)
{
    *outHotKeyArray = CFArrayCreate(NULL, NULL, 0, &kCFTypeArrayCallBacks);
    return noErr;
}

static NSDictionary *PersistentDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:Domain]) return nil;
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}
static NSDictionary *RegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static NSUInteger ups, downs, cancels, releases;
static void CountUp(id self, SEL cmd) { (void)self; (void)cmd; ups++; }
static void CountDown(id self, SEL cmd) { (void)self; (void)cmd; downs++; }
static void CountCancel(id self, SEL cmd) { (void)self; (void)cmd; cancels++; }

@interface FCReleaseDelegate : NSObject <BezelWindowDelegate>
@end
@implementation FCReleaseDelegate
- (void)metaKeysReleased { releases++; }
- (void)processBezelKeyDown:(NSEvent *)event { (void)event; }
- (void)processBezelMouseEvents:(NSEvent *)event { (void)event; }
@end

static SRRecorderControl *MainRecorder(AppController *controller)
{
    SRRecorderControl *recorder = [[[SRRecorderControl alloc] initWithFrame:NSMakeRect(20, 20, 150, 22)] autorelease];
    [recorder setDelegate:controller];
    [controller setValue:recorder forKey:@"mainRecorder"];
    return recorder;
}

// -awakeFromNib's order: the carry-over, then the recorders are loaded (which registers).
static int LaunchRegisters(AppController *controller, UInt32 code, UInt32 modifiers)
{
    FlycutCarryOverHotkeyDefaults([NSUserDefaults standardUserDefaults], Domain);
    MainRecorder(controller);
    [controller performSelector:@selector(loadHotkeyRecorderCombos)];
    [controller toggleMainHotKey:[NSNull null]];
    if (lastCode != code || lastModifiers != modifiers) {
        fprintf(stderr, "bezel hotkey registered as code %u modifiers 0x%x, expected %u 0x%x\n", lastCode, lastModifiers, code, modifiers);
        return 50;
    }
    return 0;
}

static NSEvent *Key(unsigned short code, NSEventModifierFlags flags, NSString *chars)
{
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0 windowNumber:0
                             context:nil characters:chars charactersIgnoringModifiers:chars isARepeat:NO keyCode:code];
}

// With the bezel on Control-Option-Command-V: V again steps down, Shift-V steps back,
// Escape cancels, another press of the hotkey steps down.
static int BezelKeys(AppController *controller)
{
    SRRecorderControl *recorder = MainRecorder(controller);
    [recorder setKeyCombo:SRMakeKeyCombo(9, NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand)];
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(stackUp)), (IMP)CountUp);
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(stackDown)), (IMP)CountDown);
    method_setImplementation(class_getInstanceMethod([AppController class], NSSelectorFromString(@"cancelBezelSelection")), (IMP)CountCancel);
    NSEventModifierFlags held = NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand;
    [controller processBezelKeyDown:Key(9, held, @"v")];
    if (downs != 1 || ups != 0) return 60;
    [controller processBezelKeyDown:Key(9, held | NSEventModifierFlagShift, @"V")];
    if (ups != 1 || downs != 1) return 61;
    [controller processBezelKeyDown:Key(53, held, @"")];
    if (cancels != 1) return 62;
    [controller setValue:@YES forKey:@"isBezelDisplayed"];
    [controller hitMainHotKey:nil];
    if (downs != 2) return 63;
    return 0;
}

// Releasing the modifiers pastes only once none of the four is held, Control included.
static int BezelRelease(void)
{
    BezelWindow *bezel = [[BezelWindow alloc] initWithContentRect:NSMakeRect(-30000, -30000, 300, 200)
                                                        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered
                                                            defer:NO showSource:NO];
    FCReleaseDelegate *delegate = [[[FCReleaseDelegate alloc] init] autorelease];
    [bezel setDelegate:delegate];
    NSEventModifierFlags steps[] = {
        NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand,
        NSEventModifierFlagControl | NSEventModifierFlagOption,
        NSEventModifierFlagControl,
    };
    for (size_t i = 0; i < sizeof(steps) / sizeof(steps[0]); i++) {
        [bezel flagsChanged:[NSEvent keyEventWithType:NSEventTypeFlagsChanged location:NSZeroPoint modifierFlags:steps[i]
                                            timestamp:0 windowNumber:0 context:nil characters:@"" charactersIgnoringModifiers:@""
                                            isARepeat:NO keyCode:59]];
        if (releases != 0) { fprintf(stderr, "released with flags 0x%lx still held\n", (unsigned long)steps[i]); return 70; }
    }
    [bezel flagsChanged:[NSEvent keyEventWithType:NSEventTypeFlagsChanged location:NSZeroPoint modifierFlags:0 timestamp:0
                                     windowNumber:0 context:nil characters:@"" charactersIgnoringModifiers:@"" isARepeat:NO keyCode:59]];
    if (releases != 1) return 71;
    [bezel setDelegate:nil];
    [bezel release];
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 2) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        if (!class_addMethod([FCMemoryDefaults class], @selector(persistentDomainForName:), (IMP)PersistentDomain, "@@:@")) return 4;
        if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)RegistrationDomain, "@@:@")) return 4;
        [NSApplication sharedApplication];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        if ([mode isEqualToString:@"launch-existing"])
            [[NSUserDefaults standardUserDefaults] setObject:@{@"jcList": @[]} forKey:@"store"];
        AppController *controller = [[AppController alloc] init];
        if ([mode isEqualToString:@"registered"]) {
            NSDictionary *main = [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder mainHotkey"];
            NSDictionary *plain = [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder plainPasteHotkey"];
            if (![main isEqual:FlycutBezelHotkeyDefault()] || ![plain isEqual:FlycutPlainPasteHotkeyDefault()]) {
                fprintf(stderr, "registered bezel %s, plain %s\n", [[main description] UTF8String], [[plain description] UTF8String]);
                return 40;
            }
            return 0;
        }
        if ([mode isEqualToString:@"launch-fresh"]) return LaunchRegisters(controller, 9, controlKey | optionKey | cmdKey);
        if ([mode isEqualToString:@"launch-existing"]) return LaunchRegisters(controller, 9, shiftKey | cmdKey);
        if ([mode isEqualToString:@"bezel-keys"]) return BezelKeys(controller);
        if ([mode isEqualToString:@"bezel-release"]) return BezelRelease();
        return 5;
    }
}
'''


def method_body(source: str, signature: str) -> str:
    start = source.index(signature + "\n{")
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1


class HotkeyDefaultsRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-hotkey-defaults-")
        temp = pathlib.Path(cls.temp.name)
        base = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                "-mmacosx-version-min=13.5", "-arch", "arm64", "-I", str(ROOT), "-I", str(FIXTURES)]
        (temp / "Defaults.m").write_text(DEFAULTS_FIXTURE)
        cls.defaults_binary = temp / "Defaults"
        build = subprocess.run(base + [str(temp / "Defaults.m"), "-framework", "AppKit", "-o", str(cls.defaults_binary)],
                               cwd=ROOT, text=True, capture_output=True, timeout=240)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout + build.stderr)
        sources = [ROOT / path for path in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
                   if path != "main.m" and not path.startswith(("FlycutHelper/", "Tests/"))]
        (temp / "App.m").write_text(APP_FIXTURE)
        cls.app_binary = temp / "App"
        command = base + ["-DFLYCUT_MAC=1", "-w", "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({*(path.parent for path in sources)}):
            command += ["-I", str(include)]
        command += [str(path) for path in sources] + [str(temp / "App.m")]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command += ["-framework", framework]
        build = subprocess.run(command + ["-o", str(cls.app_binary)], cwd=ROOT, text=True, capture_output=True, timeout=300)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_defaults(self, mode: str) -> None:
        run = subprocess.run([str(self.defaults_binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def run_app(self, mode: str) -> None:
        run = subprocess.run([str(self.app_binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    # Factory values.
    def test_bezel_defaults_to_control_option_command_v_and_plain_paste_to_option_shift_command_v(self) -> None:
        self.run_defaults("factory")

    def test_app_controller_registers_both_factory_hotkeys(self) -> None:
        self.run_app("registered")

    # The one-time carry-over.
    def test_fresh_install_gets_the_new_defaults(self) -> None:
        self.run_defaults("fresh")

    def test_appkit_keys_alone_are_no_earlier_flycut(self) -> None:
        self.run_defaults("appkit-keys-only")

    def test_keys_macos_writes_for_any_app_are_no_earlier_flycut(self) -> None:
        self.run_defaults("system-keys-only")

    def test_a_declined_sandbox_import_counts_as_an_existing_user(self) -> None:
        self.run_defaults("sandbox-import-declined")

    def test_existing_history_keeps_shift_command_v_for_the_bezel(self) -> None:
        self.run_defaults("existing-history")

    def test_any_stored_flycut_key_counts_as_an_existing_user(self) -> None:
        self.run_defaults("existing-any-key")

    def test_a_custom_bezel_hotkey_is_kept(self) -> None:
        self.run_defaults("existing-custom-bezel")

    def test_a_cleared_bezel_hotkey_stays_cleared(self) -> None:
        self.run_defaults("existing-cleared-bezel")

    def test_a_stored_plain_paste_hotkey_is_left_alone(self) -> None:
        self.run_defaults("existing-plain-stored")

    def test_a_bezel_on_the_plain_paste_default_keeps_it_and_plain_paste_starts_empty(self) -> None:
        self.run_defaults("existing-bezel-on-plain-default")

    def test_a_search_hotkey_on_the_plain_paste_default_keeps_it_and_plain_paste_starts_empty(self) -> None:
        self.run_defaults("existing-search-on-plain-default")

    def test_a_stored_plain_paste_hotkey_stays_next_to_such_a_bezel(self) -> None:
        self.run_defaults("existing-plain-stored-bezel-on-plain-default")

    def test_a_bezel_on_another_key_with_the_same_modifiers_is_no_clash(self) -> None:
        self.run_defaults("existing-bezel-on-other-key")

    def test_a_bezel_moved_there_after_the_check_changes_nothing(self) -> None:
        self.run_defaults("bezel-on-plain-default-after-the-check")

    def test_second_launch_of_a_fresh_install_changes_nothing(self) -> None:
        self.run_defaults("second-launch-fresh")

    def test_second_launch_of_an_existing_install_changes_nothing(self) -> None:
        self.run_defaults("second-launch-existing")

    def test_marker_stops_the_carry_over(self) -> None:
        self.run_defaults("marker-already-set")

    def test_only_the_defaults_own_domain_counts(self) -> None:
        self.run_defaults("other-domain")

    def test_without_a_domain_name_nothing_is_carried_over(self) -> None:
        self.run_defaults("no-domain")

    # Launch path.
    def test_fresh_launch_registers_the_bezel_on_control_option_command_v(self) -> None:
        self.run_app("launch-fresh")

    def test_existing_launch_registers_the_bezel_on_shift_command_v(self) -> None:
        self.run_app("launch-existing")

    def test_carry_over_runs_before_the_recorders_are_loaded(self) -> None:
        body = method_body((ROOT / "AppController.m").read_text(), "- (void)awakeFromNib")
        call = "FlycutCarryOverHotkeyDefaults([NSUserDefaults standardUserDefaults], [[NSBundle mainBundle] bundleIdentifier]);"
        self.assertEqual(body.count("FlycutCarryOverHotkeyDefaults"), 1, "the carry-over must run exactly once per launch")
        self.assertIn(call, body)
        migration = body.index("[self checkAndPerformSandboxDataMigration];")
        at = body.index(call)
        # After the sandbox import (an earlier sandboxed Flycut's data counts), before anything
        # of this launch stores a value or loads a recorder.
        self.assertLess(migration, at)
        between = body[migration + len("[self checkAndPerformSandboxDataMigration];"):at]
        self.assertEqual(re.sub(r"\s|//[^\n]*", "", between), "", "code between the sandbox import and the carry-over")
        for later in ("[self buildAppearancesPreferencePanel];", "[self loadHotkeyRecorderCombos];",
                      "[FlycutOperator carryOverConcealedTypesSetting];", "forKey:@\"loadOnStartup\"]"):
            self.assertLess(at, body.index(later), later)

    def test_init_registers_the_factory_hotkeys_from_one_table(self) -> None:
        body = method_body((ROOT / "AppController.m").read_text(), "- (id)init")
        self.assertIn("FlycutBezelHotkeyDefault()", body)
        self.assertIn("FlycutPlainPasteHotkeyDefault()", body)
        self.assertNotIn("1179648", body)
        header = (ROOT / "FlycutHotkeyDefaults.h").read_text()
        # The plain-text default is one constant: one definition site for its combination.
        self.assertEqual(len(re.findall(r"FlycutPlainPasteHotkeyDefault\(void\)", header)), 1)

    # Bezel keys with the new modifiers.
    def test_bezel_keys_work_with_control_option_command(self) -> None:
        self.run_app("bezel-keys")

    def test_bezel_pastes_only_when_control_is_released_too(self) -> None:
        self.run_app("bezel-release")

    def test_docs_name_the_new_defaults_and_the_carry_over(self) -> None:
        readme = (ROOT / "readme.md").read_text()
        help_text = (ROOT / "help.md").read_text()
        self.assertRegex(readme, r"\|\s*Control\+Option\+Command\+V\s*\|\s*Open clipboard history \(bezel\)")
        self.assertNotRegex(readme, r"\|\s*Shift\+Command\+V\s*\|\s*Open clipboard history")
        self.assertIn("Press the Main Hotkey (Control-Option-Command-V by default)", help_text)
        self.assertNotIn("Main Hotkey (Shift-Command-V, by default)", help_text)
        self.assertNotIn("hold the command key", help_text)
        self.assertIn("\n\nIf you used Flycut before, your Main Hotkey stays as it was: Shift-Command-V, or the one you chose. "
                      "To move to the new default, click the arrow next to the Main Hotkey in Preferences.\n\n", help_text)
        self.assertIn("\n\nPress the Main Hotkey (Control-Option-Command-V by default) to access your clipboard history. "
                      "Or just click the Flycut icon in the menu bar.\n\n", help_text)


if __name__ == "__main__":
    unittest.main()
