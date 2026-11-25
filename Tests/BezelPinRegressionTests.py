#!/usr/bin/env python3
"""A pinned bezel stays pinned and open when "f" switches between history and Favorites.

The bezel is pinned with Space, with a right click, or by the "sticky bezel" preference.
A pinned bezel stays open when the hotkey's modifier keys are released, so nothing is
pasted until Return or a double click. Pressing "f" there shows the other list. It must
not end the pin (the next modifier release would paste and close the bezel), must not
hide Flycut, and must keep each list's own selection. What must keep working: "f" in an
unpinned bezel, then releasing the keys, pastes the shown favorite; a real close of the
pinned bezel (another window takes key focus) still closes it, ends its Favorites view,
hides Flycut and ends the pin.

The fixture compiles the real AppController, FlycutOperator, FlycutStore and the rest of
the app sources (git ls-files '*.m' minus main.m, FlycutHelper and Tests) and drives the
production -hitMainHotKey:, -processBezelKeyDown:, -processBezelMouseEvents:,
-metaKeysReleased and -pollPB: on a real operator. Favorites are made with Shift-F in
the bezel, copies arrive through the clipboard poll.

Only OS boundaries are replaced. FixtureIsolation.h keeps user defaults in memory; the
pasteboard is an in-process object; NSWorkspace answers with no applications;
+[NSScreen mainScreen] is nil. NSApp exists with the "prohibited" activation policy (no
Dock icon, no menu bar); hiding and activating Flycut are counted and never performed.
Synthetic Cmd-V keystrokes are counted and never posted. The bezel is a stand-in object
that records what it shows; like AppKit for a key window, it tells its delegate
(-windowDidResignKey:) when it is ordered out while key. The general pasteboard, the
status bar, the image store and -saveFromStore:atIndex:withPrefix: (writes files) end
the fixture if reached. No NIB is loaded, no window is created, nothing is shown.

Every mode prints one "REPORT {json}" line with the observed state and exits 0 when the
behaviour is right. Exit codes: 2x setup, 3x Space pin, 4x right-click pin, 5x sticky
bezel, 6x unpinned "f" (must keep working), 7x real close of a pinned bezel after "f"
(must keep working).
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
void FCFixtureBeep(void) { }   // NSBeep, built with -DNSBeep=FCFixtureBeep: never played
#import <string.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutClipping.h"
#import "FlycutStore.h"

@interface FCFakeWorkspace : NSObject
@end
@implementation FCFakeWorkspace
- (NSArray *)runningApplications { return @[]; }
- (NSRunningApplication *)frontmostApplication { return nil; }
@end

// An in-process pasteboard: generations, types, string/data per type.
@interface FCMemoryPasteboard : NSObject {
@public
    NSInteger changeCount;
    NSArray *types;
    NSMutableDictionary *values;
}
- (void)copyText:(NSString *)text;
@end
@implementation FCMemoryPasteboard
- (id)init {
    if ((self = [super init])) { changeCount = 100; types = [@[] retain]; values = [[NSMutableDictionary alloc] init]; }
    return self;
}
- (NSInteger)changeCount { return changeCount; }
- (NSArray *)types { return types; }
- (NSString *)availableTypeFromArray:(NSArray *)candidates {
    for (NSString *candidate in candidates) if ([types containsObject:candidate]) return candidate;
    return nil;
}
- (NSString *)stringForType:(NSString *)type { id v = values[type]; return [v isKindOfClass:[NSString class]] ? v : nil; }
- (NSData *)dataForType:(NSString *)type { id v = values[type]; return [v isKindOfClass:[NSData class]] ? v : nil; }
- (void)addType:(NSString *)type {
    if ([types containsObject:type]) return;
    NSArray *next = [[types arrayByAddingObject:type] retain]; [types release]; types = next;
}
- (NSInteger)declareTypes:(NSArray *)newTypes owner:(id)owner {
    changeCount++; [types release]; types = [newTypes copy]; [values removeAllObjects]; return changeCount;
}
- (NSInteger)clearContents { changeCount++; [types release]; types = [@[] retain]; [values removeAllObjects]; return changeCount; }
- (BOOL)setString:(NSString *)s forType:(NSString *)t { if (!s) return NO; values[t] = [[s copy] autorelease]; [self addType:t]; return YES; }
- (BOOL)setData:(NSData *)d forType:(NSString *)t { if (!d) return NO; values[t] = [[d copy] autorelease]; [self addType:t]; return YES; }
- (NSArray *)pasteboardItems { return @[]; }
- (BOOL)writeObjects:(NSArray *)objects { return NO; }
// A copy made by another application.
- (void)copyText:(NSString *)text {
    changeCount++; [types release]; types = [@[NSPasteboardTypeString] retain];
    [values removeAllObjects]; values[NSPasteboardTypeString] = text;
}
@end

// Stands in for the BezelWindow: records what it shows. Like AppKit for a key window,
// ordering it out while it is key tells its delegate that it resigned key first.
@interface FCFakeBezel : NSObject {
@public
    id delegate;
    BOOL key, visible, color;
    NSString *text;
    int orderOuts, resignedKey;
}
@end
@implementation FCFakeBezel
- (NSRect)frame { return NSMakeRect(0, 0, 400, 300); }
- (void)setFrame:(NSRect)frame display:(BOOL)display { }
- (void)setCollectionBehavior:(NSWindowCollectionBehavior)behavior { }
- (void)makeKeyAndOrderFront:(id)sender { visible = YES; key = YES; }
- (void)orderOut:(id)sender {
    orderOuts++;
    visible = NO;
    if (key) {
        key = NO;
        resignedKey++;
        [delegate windowDidResignKey:[NSNotification notificationWithName:NSWindowDidResignKeyNotification object:self]];
    }
}
- (void)setColor:(BOOL)value { color = value; }
- (void)setText:(NSString *)value { [text release]; text = [value copy]; }
- (void)setImage:(NSImage *)image { [text release]; text = [@"<image>" copy]; }
- (void)setCharString:(NSString *)value { }
- (void)setSource:(NSString *)value { }
- (void)setDate:(NSString *)value { }
- (void)setSourceIcon:(NSImage *)icon { }
- (void)setAlpha:(float)value { }
- (void)trueCenter { }
@end

static FCFakeWorkspace *fakeWorkspace;
static id FCSharedWorkspace(id self, SEL _cmd) { return fakeWorkspace; }
static id FCNoScreen(id self, SEL _cmd) { return nil; }
static id FCNoImage(id self, SEL _cmd, NSString *name) { return nil; }
static id FCForbidden(id self, SEL _cmd) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: %s\n", sel_getName(_cmd));
    _exit(99);
}
static BOOL FCForbiddenSave(id self, SEL _cmd, id store, int index, id prefix) {
    fprintf(stderr, "fixture reached -saveFromStore:atIndex:withPrefix: (writes files)\n");
    _exit(98);
}
// Hiding and activating Flycut are counted, never performed.
static int appHides, activations;
static void FCCountHide(id self, SEL _cmd, id sender) { appHides++; }
static void FCCountActivation(id self, SEL _cmd, ...) { activations++; }
static BOOL FCCountActivationBOOL(id self, SEL _cmd, ...) { activations++; return NO; }
static void Swizzle(Class cls, SEL selector, IMP imp) {
    Method m = class_getInstanceMethod(cls, selector);
    if (m != NULL) method_setImplementation(m, imp);
}

static int pasteKeystrokes, hideAppCalls;

@interface FCPinController : AppController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake;
- (BOOL)bezelDisplayed;
- (BOOL)bezelPinned;
- (void)drainCaptures;
@end
@implementation FCPinController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake {
    flycutOperator = op;
    jcPasteboard = (id)pasteboard;
    bezel = (id)fake;
    fake->delegate = self;
    pbCount = [[NSNumber numberWithInteger:pasteboard->changeCount] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
}
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
- (BOOL)bezelPinned { return isBezelPinned; }
- (void)drainCaptures {
    __block BOOL drained = NO;
    dispatch_async(clipboardReadQueue, ^{ dispatch_async(dispatch_get_main_queue(), ^{ drained = YES; }); });
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5.0];
    while (!drained && [limit timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}
// Observation only: counts the production -hideApp and then runs it.
- (void)hideApp { hideAppCalls++; [super hideApp]; }
// Synthetic keystrokes are an OS boundary: counted, never posted.
- (void)fakeCommandV { pasteKeystrokes++; }
- (void)fakeKey:(NSNumber *)keyCode withCommandFlag:(BOOL)setFlag { pasteKeystrokes++; }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier { pasteKeystrokes++; return YES; }
@end

@interface AppController (BezelPinTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)processBezelMouseEvents:(NSEvent *)event;
- (void)hitMainHotKey:(id)hotKey;
- (void)savePreferencesOnDict:(NSMutableDictionary *)dict;
- (void)metaKeysReleased;
- (void)windowDidResignKey:(NSNotification *)notification;
- (void)hideApp;
@end

static FCPinController *controller;
static FlycutOperator *op;
static FCMemoryPasteboard *pasteboard;
static FCFakeBezel *fakeBezel;
static FlycutStore *historyStore, *favoritesStore;
static NSInteger lastCopyChangeCount;

static void Spin(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([until timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}

static void Copy(NSString *text) {
    [pasteboard copyText:text];
    lastCopyChangeCount = pasteboard->changeCount;
    [controller pollPB:nil];
    [controller drainCaptures];
}

static void Key(NSString *characters, unsigned short keyCode, NSEventModifierFlags flags) {
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags
                                     timestamp:0 windowNumber:0 context:nil characters:characters
                   charactersIgnoringModifiers:characters isARepeat:NO keyCode:keyCode];
    [controller processBezelKeyDown:event];
}
static void Escape(void) { Key(@"", 53, 0); }
static void Down(void) { Key(@"j", 38, 0); }
static void ToggleFavorites(void) { Key(@"f", 3, 0); }
static void PinWithSpace(void) { Key(@" ", 49, 0); }
static void PinWithRightClick(void) {
    NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeRightMouseUp location:NSZeroPoint modifierFlags:0
                                       timestamp:0 windowNumber:0 context:nil eventNumber:0 clickCount:1 pressure:0];
    [controller processBezelMouseEvents:event];
}
// The user lets go of the hotkey's modifier keys (BezelWindow -flagsChanged:), then the
// delayed paste steps (0.2 s, 0.5 s) get their time.
static void ReleaseModifiers(void) {
    [controller metaKeysReleased];
    Spin(0.8);
}
// Another window takes key focus (Preferences, a click into another application): the
// key bezel resigns, and AppKit tells its delegate.
static BOOL OtherWindowBecomesKey(void) {
    if (!fakeBezel->key) return NO;
    fakeBezel->key = NO;
    fakeBezel->resignedKey++;
    [controller windowDidResignKey:[NSNotification notificationWithName:NSWindowDidResignKeyNotification object:fakeBezel]];
    return YES;
}

static NSArray *Contents(FlycutStore *store) {
    NSMutableArray *out = [NSMutableArray array];
    for (int i = 0; i < [store jcListCount]; i++) [out addObject:[store clippingContentsAtPosition:i] ?: @"<nil>"];
    return out;
}
static NSString *Selected(void) {
    FlycutClipping *clipping = [op clippingAtStackPosition];
    return clipping ? ([clipping contents] ?: @"<nil>") : @"<none>";
}
static NSString *PasteboardText(void) { return [pasteboard stringForType:NSPasteboardTypeString] ?: @"<nil>"; }
// Flycut wrote a selection to the clipboard or sent the paste keystroke.
static BOOL Pasted(void) { return pasteboard->changeCount != lastCopyChangeCount || pasteKeystrokes != 0; }
static BOOL Open(void) { return [controller bezelDisplayed] && fakeBezel->visible && fakeBezel->key; }

static NSMutableDictionary *report;
static void Observe(NSString *label) {
    report[label] = @{
        @"bezelDisplayed": @([controller bezelDisplayed]),
        @"bezelVisible": @(fakeBezel->visible),
        @"bezelKey": @(fakeBezel->key),
        @"bezelPinned": @([controller bezelPinned]),
        @"bezelText": fakeBezel->text ?: @"",
        @"bezelFavoritesColor": @(fakeBezel->color),
        @"bezelOrderOuts": @(fakeBezel->orderOuts),
        @"bezelResignedKey": @(fakeBezel->resignedKey),
        @"favoritesStoreIsSelected": @([op favoritesStoreIsSelected]),
        @"selected": Selected(),
        @"historyStore": Contents(historyStore),
        @"favoritesStore": Contents(favoritesStore),
        @"pasteboard": PasteboardText(),
        @"pasted": @(Pasted()),
        @"pasteKeystrokes": @(pasteKeystrokes),
        @"hideAppCalls": @(hideAppCalls),
        @"appHides": @(appHides),
    };
}
static int Emit(int code) {
    report[@"exit"] = @(code);
    report[@"activations"] = @(activations);
    NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
    printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    return code;
}

static void Install(void) {
    // NSApp first: nothing below may run with a faked NSWorkspace while AppKit sets up.
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
    Swizzle([NSApplication class], @selector(hide:), (IMP)FCCountHide);
    Swizzle([NSApplication class], @selector(unhide:), (IMP)FCCountActivation);
    Swizzle([NSApplication class], @selector(activateIgnoringOtherApps:), (IMP)FCCountActivation);
    Swizzle([NSApplication class], sel_registerName("activate"), (IMP)FCCountActivation);
    Swizzle([NSRunningApplication class], @selector(activateWithOptions:), (IMP)FCCountActivationBOOL);
    fakeWorkspace = [[FCFakeWorkspace alloc] init];
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)), (IMP)FCSharedWorkspace);
    method_setImplementation(class_getClassMethod([NSScreen class], @selector(mainScreen)), (IMP)FCNoScreen);
    method_setImplementation(class_getClassMethod([NSImage class], @selector(imageNamed:)), (IMP)FCNoImage);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([NSStatusBar class], @selector(systemStatusBar)), (IMP)FCForbidden);
    Class imageStore = NSClassFromString(@"FlycutImageStore");
    method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)FCForbidden);
    method_setImplementation(class_getInstanceMethod([FlycutOperator class], @selector(saveFromStore:atIndex:withPrefix:)),
                             (IMP)FCForbiddenSave);
}

// Starts like the app: two favorites (moved there with Shift-F in the bezel), then the
// history h1..h3.
static int Setup(BOOL sticky) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    if (![defaults isMemberOfClass:[FCMemoryDefaults class]]) return 21;
    if (NSApp == nil) return 22;
    controller = [[FCPinController alloc] init];
    op = [[FlycutOperator alloc] init];
    [defaults setObject:@1 forKey:@"savePreference"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@NO forKey:@"captureImages"];
    [defaults setObject:@NO forKey:@"pasteMovesToTop"];
    [defaults setObject:@NO forKey:@"stickyBezel"];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
    [op setDelegate:(id)controller];
    [op setClippingsStoreDelegate:(id)controller];
    [op setFavoritesStoreDelegate:(id)controller];
    pasteboard = [[FCMemoryPasteboard alloc] init];
    fakeBezel = [[FCFakeBezel alloc] init];
    [controller installOperator:op pasteboard:pasteboard bezel:fakeBezel];
    historyStore = [op valueForKey:@"clippingStore"];
    favoritesStore = [op valueForKey:@"favoritesStore"];
    if (historyStore == nil || favoritesStore == nil || historyStore == favoritesStore) return 23;

    for (NSString *favorite in @[@"fav-1", @"fav-2"]) {
        Copy(favorite);
        [controller hitMainHotKey:nil];
        Key(@"F", 3, NSEventModifierFlagShift);    // Shift-F: move the selected clipping to Favorites
        Spin(0.6);                                   // its delayed -hideApp closes the bezel
    }
    Copy(@"h1"); Copy(@"h2"); Copy(@"h3");
    if (![Contents(historyStore) isEqualToArray:(@[@"h3", @"h2", @"h1"])]) return 24;
    if (![Contents(favoritesStore) isEqualToArray:(@[@"fav-2", @"fav-1"])]) return 25;
    if ([op favoritesStoreIsSelected] || [controller bezelDisplayed] || Pasted()) return 26;
    [defaults setObject:@(sticky) forKey:@"stickyBezel"];
    // From here on, count only what the case itself does.
    appHides = 0; hideAppCalls = 0; activations = 0;
    fakeBezel->orderOuts = 0; fakeBezel->resignedKey = 0;
    Observe(@"0-setup");
    return 0;
}

// The bezel is open and pinned on the history. "f" shows Favorites, "f" shows the history
// again; the bezel stays open, pinned and key, nothing is pasted when the keys are
// released, Flycut is not hidden, and each list keeps its own selection.
static int CheckFKeepsPin(int base) {
    Observe(@"1-pinned");
    if (!Open() || [op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"h3"]) return base;
    ReleaseModifiers();                              // pinned: releasing the keys pastes nothing
    if (Pasted() || !Open()) return base;            // precondition: the pin works before "f"

    ToggleFavorites();                               // "f": show Favorites
    Observe(@"2-after-f");
    if (!Open()) return base + 1;
    if (![op favoritesStoreIsSelected] || !fakeBezel->color || ![Selected() isEqualToString:@"fav-2"] ||
        ![fakeBezel->text isEqualToString:@"fav-2"]) return base + 2;
    ReleaseModifiers();                              // the user lets go of the keys
    Observe(@"3-after-release");
    if (Pasted()) return base + 3;                   // the pin was gone: the favorite was pasted
    if (!Open() || ![op favoritesStoreIsSelected]) return base + 4;
    if (appHides != 0) return base + 5;              // Flycut was hidden

    Down();                                          // Favorites: fav-1
    ToggleFavorites();                               // the history again, on its own selection
    ReleaseModifiers();
    Observe(@"4-history-again");
    if (!Open() || [op favoritesStoreIsSelected] || fakeBezel->color || ![Selected() isEqualToString:@"h3"] ||
        Pasted() || appHides != 0) return base + 6;
    ToggleFavorites();                               // Favorites again, still on fav-1
    ReleaseModifiers();
    Observe(@"5-favorites-again");
    if (!Open() || ![op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"fav-1"] ||
        ![fakeBezel->text isEqualToString:@"fav-1"] || Pasted() || appHides != 0) return base + 7;

    Escape();                                        // Escape closes it; the history is current again
    Spin(0.3);
    Observe(@"6-after-escape");
    if ([controller bezelDisplayed] || fakeBezel->visible || [op favoritesStoreIsSelected] || Pasted()) return base + 8;
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        report = [[NSMutableDictionary alloc] init];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        report[@"mode"] = mode;
        Install();
        BOOL sticky = [mode isEqualToString:@"sticky-bezel-then-f"];
        int failed = Setup(sticky);
        if (failed) return Emit(failed);

        if ([mode isEqualToString:@"space-pin-then-f"]) {
            [controller hitMainHotKey:nil];          // the bezel opens on the history
            PinWithSpace();
            return Emit(CheckFKeepsPin(30));
        }
        if ([mode isEqualToString:@"right-click-pin-then-f"]) {
            [controller hitMainHotKey:nil];
            PinWithRightClick();
            return Emit(CheckFKeepsPin(40));
        }
        if ([mode isEqualToString:@"sticky-bezel-then-f"]) {
            [controller hitMainHotKey:nil];          // "sticky bezel": opens pinned
            return Emit(CheckFKeepsPin(50));
        }
        if ([mode isEqualToString:@"unpinned-f-then-release-pastes"]) {
            [controller hitMainHotKey:nil];          // not pinned
            ToggleFavorites();
            Observe(@"1-after-f");
            if (!Open() || ![op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"fav-2"]) return Emit(60);
            ReleaseModifiers();                      // releasing the keys pastes the shown favorite
            Observe(@"2-after-release");
            if (![PasteboardText() isEqualToString:@"fav-2"]) return Emit(61);
            if ([controller bezelDisplayed] || fakeBezel->visible) return Emit(62);
            if ([op favoritesStoreIsSelected]) return Emit(63);
            [controller hitMainHotKey:nil];          // the next bezel opens on the history
            Observe(@"3-next-bezel");
            if ([op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"h3"]) return Emit(64);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"pinned-f-then-focus-loss-closes"]) {
            [controller hitMainHotKey:nil];
            PinWithSpace();
            ToggleFavorites();
            Observe(@"1-after-f");
            if (![controller bezelDisplayed] || ![op favoritesStoreIsSelected]) return Emit(70);
            int hidesBefore = appHides;
            if (!OtherWindowBecomesKey()) return Emit(70);   // a click into another app's window
            Spin(0.3);
            Observe(@"2-after-focus-loss");
            if ([controller bezelDisplayed] || fakeBezel->visible) return Emit(71);
            if ([op favoritesStoreIsSelected] || fakeBezel->color) return Emit(72);   // the Favorites view ended
            if (appHides != hidesBefore + 1) return Emit(73);                         // Flycut is hidden as before
            if (Pasted()) return Emit(74);
            [controller hitMainHotKey:nil];          // the next bezel: history, and no longer pinned
            Observe(@"3-next-bezel");
            if (!Open() || [op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"h3"]) return Emit(75);
            ReleaseModifiers();
            Observe(@"4-after-release");
            if (![PasteboardText() isEqualToString:@"h3"] || [controller bezelDisplayed]) return Emit(76);
            return Emit(0);
        }
        return Emit(4);
    }
}
'''

MODES = {
    "space-pin-then-f": "f in a bezel pinned with Space ended the pin, closed it or hid Flycut",
    "right-click-pin-then-f": "f in a bezel pinned with a right click ended the pin, closed it or hid Flycut",
    "sticky-bezel-then-f": "f in a sticky bezel ended the pin, closed it or hid Flycut",
    "unpinned-f-then-release-pastes": "f in an unpinned bezel, then releasing the keys, no longer pastes the favorite",
    "pinned-f-then-focus-loss-closes": "focus loss of a pinned bezel after f no longer closes it and ends its pin",
}


def fixture_sources() -> list[pathlib.Path]:
    listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
    return [ROOT / p for p in sorted(listed)
            if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]


class BezelPinRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-bezel-pin-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "BezelPinFixture.m"
        cls.binary = temp / "BezelPinFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-DNSBeep=FCFixtureBeep", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(source)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        cls.build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def run_mode(self, mode: str) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-4000:])
        run = subprocess.run([str(self.binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        print(f"\n{mode}: exit={run.returncode} {reports[-1] if reports else '(no report)'}")
        self.assertEqual(run.returncode, 0, f"{MODES[mode]}; exit={run.returncode}; "
                         f"{reports[-1] if reports else run.stderr[-1500:]}")

    def test_f_keeps_a_space_pinned_bezel_pinned(self) -> None:
        self.run_mode("space-pin-then-f")

    def test_f_keeps_a_right_click_pinned_bezel_pinned(self) -> None:
        self.run_mode("right-click-pin-then-f")

    def test_f_keeps_a_sticky_bezel_pinned(self) -> None:
        self.run_mode("sticky-bezel-then-f")

    def test_unpinned_f_then_release_still_pastes_the_favorite(self) -> None:
        self.run_mode("unpinned-f-then-release-pastes")

    def test_focus_loss_still_closes_a_pinned_bezel_after_f(self) -> None:
        self.run_mode("pinned-f-then-focus-loss-closes")


if __name__ == "__main__":
    unittest.main()
