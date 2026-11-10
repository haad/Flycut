#!/usr/bin/env python3
"""Regression tests: one bezel selection pastes once, and every new selection pastes.

The fixture compiles the real AppController, FlycutOperator and engine sources and
drives the production hotkey, modifier-release, Return, double-click, Escape,
favorites-toggle and pasteFromStack methods. Only OS boundaries are replaced: user
defaults live in memory, the clipboard write and the synthetic Cmd-V are recorded
instead of performed, no screen is queried, and any access to the general
pasteboard, NSWorkspace or the
on-disk image store aborts the fixture. No app bundle is built, no NIB is loaded, NSApp is never
created and no input event is posted.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#import <string.h>
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutImageStore.h"

// ---- OS boundary: persistent preferences are replaced by an in-memory store ----
@interface FCMemoryDefaults : NSObject { NSMutableDictionary *_values; }
@end
@implementation FCMemoryDefaults
- (id)init { if ((self = [super init])) _values = [[NSMutableDictionary alloc] init]; return self; }
- (void)registerDefaults:(NSDictionary *)values {
    for (id key in values) if (_values[key] == nil) _values[key] = values[key];
}
- (id)objectForKey:(NSString *)key { return _values[key]; }
- (id)valueForKey:(NSString *)key { return _values[key]; }
- (NSString *)stringForKey:(NSString *)key { return _values[key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return _values[key]; }
- (NSArray *)arrayForKey:(NSString *)key { return _values[key]; }
- (NSInteger)integerForKey:(NSString *)key { return [_values[key] integerValue]; }
- (float)floatForKey:(NSString *)key { return [_values[key] floatValue]; }
- (double)doubleForKey:(NSString *)key { return [_values[key] doubleValue]; }
- (BOOL)boolForKey:(NSString *)key { return [_values[key] boolValue]; }
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) _values[key] = value; else [_values removeObjectForKey:key];
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (void)setInteger:(NSInteger)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (void)removeObjectForKey:(NSString *)key { [_values removeObjectForKey:key]; }
- (BOOL)synchronize { return YES; }
@end

static FCMemoryDefaults *memoryDefaults;
static id FCStandardDefaults(id object, SEL selector) { return memoryDefaults; }
// OS boundary: no display is queried; the bezel is positioned on an empty frame.
static id FCNoScreen(id object, SEL selector) { return nil; }
static id FCForbidden(id object, SEL selector) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: +[%s %s]\n",
            class_getName(object), sel_getName(selector));
    NSArray *stack = [NSThread callStackSymbols];
    for (NSUInteger i = 1; i < MIN((NSUInteger)8, [stack count]); i++)
        fprintf(stderr, "  %s\n", [stack[i] UTF8String]);
    abort();
}

static void InstallBoundaries(BOOL sticky) {
    memoryDefaults = [[FCMemoryDefaults alloc] init];
    method_setImplementation(class_getClassMethod([NSUserDefaults class], @selector(standardUserDefaults)),
                             (IMP)FCStandardDefaults);
    method_setImplementation(class_getClassMethod([NSScreen class], @selector(mainScreen)),
                             (IMP)FCNoScreen);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)),
                             (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)),
                             (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)),
                             (IMP)FCForbidden);
    [memoryDefaults setObject:@0 forKey:@"savePreference"];
    [memoryDefaults setObject:@NO forKey:@"saveForgottenClippings"];
    [memoryDefaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [memoryDefaults setObject:@(sticky) forKey:@"stickyBezel"];
}

@interface AppController (BezelDoublePasteTesting)
- (void)pasteFromStack;
- (void)metaKeysReleased;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)stackDown;
@end

@interface FCDoublePasteController : AppController {
    NSMutableArray *_placed;
    int _pastes;
}
- (void)installOperator:(FlycutOperator *)op;
- (NSArray *)placed;
- (int)pastes;
- (BOOL)bezelDisplayed;
@end

@implementation FCDoublePasteController
- (void)installOperator:(FlycutOperator *)op {
    flycutOperator = op;
    _placed = [[NSMutableArray alloc] init];
}
- (NSArray *)placed { return _placed; }
- (int)pastes { return _pastes; }
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
- (void)fixtureClippingAdded { }
// OS boundary: clipboard write.
- (void)addClipToPasteboard:(NSString *)text { [_placed addObject:text]; }
- (void)addImageClipToPasteboard:(FlycutClipping *)clipping { [_placed addObject:@"<image>"]; }
// OS boundary: Accessibility check and synthetic Cmd-V posting.
- (void)fakeCommandV { _pastes += 1; }
@end

static NSEvent *KeyEvent(unsigned short keyCode, NSString *characters) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown
                            location:NSZeroPoint
                       modifierFlags:0
                           timestamp:0
                        windowNumber:0
                             context:nil
                          characters:characters
         charactersIgnoringModifiers:characters
                           isARepeat:NO
                             keyCode:keyCode];
}
static NSEvent *ReturnKey(void) { return KeyEvent(36, @"\r"); }
static NSEvent *EscapeKey(void) { return KeyEvent(53, @"\033"); }
static NSEvent *FavoritesKey(void) { return KeyEvent(3, @"f"); }
static NSEvent *DoubleClick(void) {
    return [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp
                              location:NSZeroPoint
                         modifierFlags:0
                             timestamp:0
                          windowNumber:0
                               context:nil
                           eventNumber:0
                            clickCount:2
                              pressure:0];
}

static void RunLoopFor(NSTimeInterval seconds) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];
}

static int Report(const char *mode, FCDoublePasteController *controller, NSArray *expected, int expectedPastes) {
    NSArray *placed = [controller placed];
    printf("%s: placed=%s pastes=%d expected_placed=%s expected_pastes=%d\n", mode,
           [[placed componentsJoinedByString:@","] UTF8String], [controller pastes],
           [[expected componentsJoinedByString:@","] UTF8String], expectedPastes);
    if (![placed isEqualToArray:expected]) return 10;
    if ([controller pastes] != expectedPastes) return 11;
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        const char *mode = argv[1];
        BOOL sticky = strcmp(mode, "sticky-second-return") == 0;
        InstallBoundaries(sticky);

        FCDoublePasteController *controller = [[FCDoublePasteController alloc] init];
        FlycutOperator *op = [[FlycutOperator alloc] init];
        [op awakeFromNibDisplaying:10 withDisplayLength:40
                  withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
        [op addClipping:@"older" ofType:NSPasteboardTypeString fromApp:nil withAppBundleURL:nil
                 target:controller clippingAddedSelector:@selector(fixtureClippingAdded)];
        [op addClipping:@"newest" ofType:NSPasteboardTypeString fromApp:nil withAppBundleURL:nil
                 target:controller clippingAddedSelector:@selector(fixtureClippingAdded)];
        [controller installOperator:op];

        if (strcmp(mode, "release-then-return") == 0) {
            [controller hitMainHotKey:nil];
            [controller metaKeysReleased];
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest"], 1);
        }
        if (strcmp(mode, "return-then-release") == 0) {
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:ReturnKey()];
            [controller metaKeysReleased];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest"], 1);
        }
        if (strcmp(mode, "late-duplicate-same-selection") == 0) {
            // The duplicate confirmation arrives while the same bezel is still shown,
            // but later than any fixed time window (main thread was busy).
            [controller hitMainHotKey:nil];
            [controller metaKeysReleased];
            [NSThread sleepForTimeInterval:0.7];
            if (![controller bezelDisplayed]) return 20;
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest"], 1);
        }
        if (strcmp(mode, "new-selection-after-hide") == 0) {
            [controller hitMainHotKey:nil];
            [controller metaKeysReleased];
            RunLoopFor(0.25);                 // the first selection's bezel hides at 0.2 s
            if ([controller bezelDisplayed]) return 21;
            [controller hitMainHotKey:nil];   // a new, intentional selection
            if (![controller bezelDisplayed]) return 22;
            [controller stackDown];
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest", @"older"], 2);
        }
        if (strcmp(mode, "new-selection-by-release-after-hide") == 0) {
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.25);
            if ([controller bezelDisplayed]) return 21;
            [controller hitMainHotKey:nil];
            [controller stackDown];
            [controller metaKeysReleased];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest", @"older"], 2);
        }
        if (strcmp(mode, "escape-then-stale-confirm") == 0) {
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:EscapeKey()];
            if ([controller bezelDisplayed]) return 23;
            // Late deliveries for the cancelled selection must not paste it.
            [controller processBezelKeyDown:ReturnKey()];
            [controller metaKeysReleased];
            // A new selection after Escape still pastes.
            [controller hitMainHotKey:nil];
            [controller stackDown];
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"older"], 1);
        }
        if (strcmp(mode, "sticky-second-return") == 0) {
            [controller hitMainHotKey:nil];   // sticky: the bezel is pinned
            [controller metaKeysReleased];    // pinned bezels do not paste on release
            [controller processBezelKeyDown:ReturnKey()];
            [controller processBezelKeyDown:ReturnKey()];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest"], 1);
        }
        if (strcmp(mode, "double-click-then-return") == 0) {
            [controller hitMainHotKey:nil];
            [controller processBezelMouseEvents:DoubleClick()];   // confirms the selection
            [controller processBezelKeyDown:ReturnKey()];          // duplicate confirmations
            [controller metaKeysReleased];
            RunLoopFor(0.8);
            return Report(mode, controller, @[@"newest"], 1);
        }
        if (strcmp(mode, "favorites-toggle-then-duplicate") == 0) {
            [op toggleToFromFavoritesStore];
            [op addClipping:@"favorite" ofType:NSPasteboardTypeString fromApp:nil withAppBundleURL:nil
                     target:controller clippingAddedSelector:@selector(fixtureClippingAdded)];
            [op toggleToFromFavoritesStore];
            [controller hitMainHotKey:nil];
            // 'f' hides and shows the bezel again; it is still the same selection.
            [controller processBezelKeyDown:FavoritesKey()];
            if (![controller bezelDisplayed]) return 24;
            if (![op favoritesStoreIsSelected]) return 25;
            [controller processBezelKeyDown:ReturnKey()];
            [controller metaKeysReleased];
            RunLoopFor(0.8);
            int result = Report(mode, controller, @[@"favorite"], 1);
            if (result != 0) return result;
            if ([op favoritesStoreIsSelected]) return 26;   // the main store is back after the paste
            return 0;
        }
    }
    return 3;
}
'''

MODES = {
    "release-then-return": "modifier release followed by Return pasted one selection twice",
    "return-then-release": "Return followed by modifier release pasted one selection twice",
    "late-duplicate-same-selection": "a late duplicate of the same selection was pasted again",
    "new-selection-after-hide": "a new selection confirmed with Return was dropped",
    "new-selection-by-release-after-hide": "a new selection confirmed by modifier release was dropped",
    "escape-then-stale-confirm": "an Escape-cancelled selection pasted, or the next selection was dropped",
    "sticky-second-return": "a second Return on a pinned bezel pasted the selection twice",
    "double-click-then-return": "a double-click followed by Return and modifier release pasted the selection again",
    "favorites-toggle-then-duplicate": "after the favorites toggle the selection was not pasted exactly once",
}


def fixture_sources() -> list[pathlib.Path]:
    try:
        listed = subprocess.check_output(
            ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        listed = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.m")]
    return [
        ROOT / path
        for path in sorted(listed)
        if path != "main.m"
        and not path.startswith("FlycutHelper/")
        and not path.startswith("Tests/")
    ]


class BezelDoublePasteRegressionTests(unittest.TestCase):
    binary: pathlib.Path
    directory: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-bezel-double-paste-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "BezelDoublePasteFixture.m"
        cls.binary = temp / "BezelDoublePasteFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = [
            "/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
            "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
            "-include", str(ROOT / "Flycut_Prefix.pch"),
        ]
        for include_dir in sorted({ROOT, *(path.parent for path in sources)}):
            command.extend(["-I", str(include_dir)])
        command.extend(str(path) for path in sources)
        command.append(str(source))
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command.extend(["-framework", framework])
        command.extend(["-o", str(cls.binary)])
        cls.build = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def run_mode(self, mode: str) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        run = subprocess.run(
            [str(self.binary), mode], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        boundary = [line for line in run.stderr.splitlines() if "forbidden OS boundary" in line]
        self.assertEqual(
            run.returncode, 0,
            f"{MODES[mode]}; exit={run.returncode}; {run.stdout.strip()} {' '.join(boundary)}".strip(),
        )

    def test_modifier_release_then_return_pastes_once(self) -> None:
        self.run_mode("release-then-return")

    def test_return_then_modifier_release_pastes_once(self) -> None:
        self.run_mode("return-then-release")

    def test_late_duplicate_of_same_selection_is_ignored(self) -> None:
        self.run_mode("late-duplicate-same-selection")

    def test_new_selection_right_after_previous_paste_is_pasted(self) -> None:
        self.run_mode("new-selection-after-hide")

    def test_new_selection_confirmed_by_modifier_release_is_pasted(self) -> None:
        self.run_mode("new-selection-by-release-after-hide")

    def test_escape_cancels_selection_and_next_selection_pastes(self) -> None:
        self.run_mode("escape-then-stale-confirm")

    def test_pinned_bezel_second_return_pastes_once(self) -> None:
        self.run_mode("sticky-second-return")

    def test_double_click_confirmation_pastes_once(self) -> None:
        self.run_mode("double-click-then-return")

    def test_favorites_toggle_keeps_the_selection_and_pastes_once(self) -> None:
        self.run_mode("favorites-toggle-then-duplicate")


if __name__ == "__main__":
    unittest.main()
