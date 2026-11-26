#!/usr/bin/env python3
"""The counter under the bezel's text says which list it counts and whether it is pinned.

The bezel shows "2 of 12" below the clipping. "f" switches it between the history and
the Favorites; the counter then marks the Favorites view with a grey star ("1 of 2" +
U+2605 BLACK STAR, a text glyph drawn in the counter's grey, not the yellow emoji
U+2B50), so the switch is visible beyond the bezel's colour. The history gets no mark.
While the bezel is pinned (Space, a right click, or the "sticky bezel" preference) the
counter keeps saying "(pinned)" whatever key moves the selection: on master the arrow
keys, the number keys, Home, End, Page Up and Down and "f" rewrote it without the pin.
An empty list says "Empty", in the Favorites view with the star.

The fixture compiles the real AppController, FlycutOperator, FlycutStore and the rest of
the app sources (git ls-files '*.m' minus main.m, FlycutHelper and Tests) and drives the
production -hitMainHotKey:, -processBezelKeyDown: and -processBezelMouseEvents: on a real
operator. Favorites are made with Shift-F in the bezel, copies arrive through the
clipboard poll. Only OS boundaries are replaced: FixtureIsolation.h keeps user defaults
in memory; the pasteboard is an in-process object; NSWorkspace answers with no
applications; +[NSScreen mainScreen] is nil; NSApp exists with the "prohibited"
activation policy; hiding and activating Flycut are counted and never performed;
synthetic Cmd-V keystrokes are counted and never posted. The bezel is a stand-in object
that records every counter text it is given. The general pasteboard, the status bar, the
image store and -saveFromStore:atIndex:withPrefix: (writes files) end the fixture if
reached. No NIB is loaded, no window is created there.

A second fixture creates the real BezelWindow (never ordered on screen, defaults in
memory), gives it a Favorites counter and draws its counter field offscreen: the star's
pixels must be as grey as the digits' (no colour glyph), and the font AppKit uses for the
star must not be Apple Color Emoji.

Every mode prints "REPORT {json}" with the counters it saw and exits 0 when they are
right. Exit codes: 2x setup, 3x history, 4x Favorites, 5x pinned with Space, 6x pinned
with a right click, 7x sticky bezel, 8x empty Favorites, 9x the real BezelWindow.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
STAR = "\u2605"

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
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
- (void)copyText:(NSString *)text {
    changeCount++; [types release]; types = [@[NSPasteboardTypeString] retain];
    [values removeAllObjects]; values[NSPasteboardTypeString] = text;
}
@end

// Stands in for the BezelWindow: records the counter texts (-setCharString:) it is
// given. Like AppKit for a key window, ordering it out while key resigns key first.
@interface FCFakeBezel : NSObject {
@public
    id delegate;
    BOOL key, visible, color;
    NSString *counter;
}
@end
@implementation FCFakeBezel
- (NSRect)frame { return NSMakeRect(0, 0, 400, 300); }
- (void)setFrame:(NSRect)frame display:(BOOL)display { }
- (void)setCollectionBehavior:(NSWindowCollectionBehavior)behavior { }
- (void)makeKeyAndOrderFront:(id)sender { visible = YES; key = YES; }
- (void)orderOut:(id)sender {
    visible = NO;
    if (key) {
        key = NO;
        [delegate windowDidResignKey:[NSNotification notificationWithName:NSWindowDidResignKeyNotification object:self]];
    }
}
- (void)setColor:(BOOL)value { color = value; }
- (void)setText:(NSString *)value { }
- (void)setImage:(NSImage *)image { }
- (void)setCharString:(NSString *)value { [counter release]; counter = [value copy]; }
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
static int appHides, activations;
static void FCCountHide(id self, SEL _cmd, id sender) { appHides++; }
static void FCCountActivation(id self, SEL _cmd, ...) { activations++; }
static BOOL FCCountActivationBOOL(id self, SEL _cmd, ...) { activations++; return NO; }
static void Swizzle(Class cls, SEL selector, IMP imp) {
    Method m = class_getInstanceMethod(cls, selector);
    if (m != NULL) method_setImplementation(m, imp);
}

static int pasteKeystrokes;

@interface FCCounterController : AppController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake;
- (BOOL)bezelDisplayed;
- (void)drainCaptures;
@end
@implementation FCCounterController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake {
    flycutOperator = op;
    jcPasteboard = (id)pasteboard;
    bezel = (id)fake;
    fake->delegate = self;
    pbCount = [[NSNumber numberWithInteger:pasteboard->changeCount] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
}
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
- (void)drainCaptures {
    __block BOOL drained = NO;
    dispatch_async(clipboardReadQueue, ^{ dispatch_async(dispatch_get_main_queue(), ^{ drained = YES; }); });
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5.0];
    while (!drained && [limit timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}
- (void)fakeCommandV { pasteKeystrokes++; }
- (void)fakeKey:(NSNumber *)keyCode withCommandFlag:(BOOL)setFlag { pasteKeystrokes++; }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier { pasteKeystrokes++; return YES; }
@end

@interface AppController (BezelCounterTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)processBezelMouseEvents:(NSEvent *)event;
- (void)hitMainHotKey:(id)hotKey;
- (void)savePreferencesOnDict:(NSMutableDictionary *)dict;
- (void)windowDidResignKey:(NSNotification *)notification;
@end

static FCCounterController *controller;
static FlycutOperator *op;
static FCMemoryPasteboard *pasteboard;
static FCFakeBezel *fakeBezel;
static NSMutableArray *seen;   // "<step>: <counter>"

static void Spin(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([until timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}
static void Copy(NSString *text) {
    [pasteboard copyText:text];
    [controller pollPB:nil];
    [controller drainCaptures];
}
static void Key(NSString *characters, unsigned short keyCode, NSEventModifierFlags flags) {
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags
                                     timestamp:0 windowNumber:0 context:nil characters:characters
                   charactersIgnoringModifiers:characters isARepeat:NO keyCode:keyCode];
    [controller processBezelKeyDown:event];
}
static NSString *Fn(unichar key) { return [NSString stringWithCharacters:&key length:1]; }
static void Escape(void) { Key(@"", 53, 0); }
static void Down(void) { Key(Fn(NSDownArrowFunctionKey), 125, NSEventModifierFlagFunction); }
static void Up(void) { Key(Fn(NSUpArrowFunctionKey), 126, NSEventModifierFlagFunction); }
static void End(void) { Key(Fn(NSEndFunctionKey), 119, NSEventModifierFlagFunction); }
static void Home(void) { Key(Fn(NSHomeFunctionKey), 115, NSEventModifierFlagFunction); }
static void PageDown(void) { Key(Fn(NSPageDownFunctionKey), 121, NSEventModifierFlagFunction); }
static void Number(NSString *digit) { Key(digit, 18, 0); }
static void ToggleFavorites(void) { Key(@"f", 3, 0); }
static void PinWithSpace(void) { Key(@" ", 49, 0); }
static void PinWithRightClick(void) {
    NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeRightMouseUp location:NSZeroPoint modifierFlags:0
                                       timestamp:0 windowNumber:0 context:nil eventNumber:0 clickCount:1 pressure:0];
    [controller processBezelMouseEvents:event];
}

static NSMutableDictionary *report;
static int Emit(int code) {
    report[@"exit"] = @(code);
    report[@"seen"] = seen;
    report[@"activations"] = @(activations);
    report[@"pasteKeystrokes"] = @(pasteKeystrokes);
    NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
    printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    return code;
}
// The counter after a step must read exactly `expected`.
static BOOL Counter(NSString *step, NSString *expected) {
    NSString *now = fakeBezel->counter ?: @"<none>";
    [seen addObject:[NSString stringWithFormat:@"%@: %@", step, now]];
    if ([now isEqualToString:expected]) return YES;
    report[@"failedStep"] = step;
    report[@"expected"] = expected;
    report[@"got"] = now;
    return NO;
}
#define STAR @"\u2605"

static void Install(void) {
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

// Two favorites (Shift-F in the bezel) unless `noFavorites`, then the history h1..h3.
static int Setup(BOOL sticky, BOOL noFavorites) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    if (![defaults isMemberOfClass:[FCMemoryDefaults class]]) return 21;
    controller = [[FCCounterController alloc] init];
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
    if (!noFavorites) {
        for (NSString *favorite in @[@"fav-1", @"fav-2"]) {
            Copy(favorite);
            [controller hitMainHotKey:nil];
            Key(@"F", 3, NSEventModifierFlagShift);   // Shift-F: move the selected clipping to Favorites
            Spin(0.6);                                  // its delayed -hideApp closes the bezel
        }
    }
    Copy(@"h1"); Copy(@"h2"); Copy(@"h3");
    if ([op jcListCount] != 3 || [op favoritesStoreIsSelected] || [controller bezelDisplayed]) return 22;
    [defaults setObject:@(sticky) forKey:@"stickyBezel"];
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        report = [[NSMutableDictionary alloc] init];
        seen = [[NSMutableArray alloc] init];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        report[@"mode"] = mode;
        Install();
        int failed = Setup([mode isEqualToString:@"sticky-bezel"], [mode isEqualToString:@"empty-favorites"]);
        if (failed) return Emit(failed);

        if ([mode isEqualToString:@"history"]) {
            // Must keep working: the history's counter as on master, no mark.
            [controller hitMainHotKey:nil];
            if (!Counter(@"open", @"1 of 3")) return Emit(30);
            Down();
            if (!Counter(@"down", @"2 of 3")) return Emit(31);
            Number(@"3");
            if (!Counter(@"number 3", @"3 of 3")) return Emit(32);
            Up();
            if (!Counter(@"up", @"2 of 3")) return Emit(33);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"favorites"]) {
            [controller hitMainHotKey:nil];
            Down();                                       // history: h2
            ToggleFavorites();
            if (!Counter(@"f", @"1 of 2 " STAR)) return Emit(40);
            Down();
            if (!Counter(@"down", @"2 of 2 " STAR)) return Emit(41);
            Home();
            if (!Counter(@"home", @"1 of 2 " STAR)) return Emit(42);
            ToggleFavorites();                            // the history again, on its own selection
            if (!Counter(@"f again", @"2 of 3")) return Emit(43);
            Escape();
            [controller hitMainHotKey:nil];               // a new bezel opens on the history
            if (!Counter(@"reopened", @"1 of 3")) return Emit(44);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"space-pin"]) {
            [controller hitMainHotKey:nil];
            PinWithSpace();
            if (!Counter(@"space", @"1 of 3 (pinned)")) return Emit(50);
            Down();
            if (!Counter(@"down", @"2 of 3 (pinned)")) return Emit(51);
            Number(@"1");
            if (!Counter(@"number 1", @"1 of 3 (pinned)")) return Emit(52);
            End();
            if (!Counter(@"end", @"3 of 3 (pinned)")) return Emit(53);
            ToggleFavorites();
            if (!Counter(@"f", @"1 of 2 " STAR @" (pinned)")) return Emit(54);
            PageDown();
            if (!Counter(@"page down", @"2 of 2 " STAR @" (pinned)")) return Emit(55);
            ToggleFavorites();
            if (!Counter(@"f again", @"3 of 3 (pinned)")) return Emit(56);
            Escape();
            Spin(0.3);
            [controller hitMainHotKey:nil];               // closed: the next bezel is not pinned
            if (!Counter(@"reopened", @"1 of 3")) return Emit(57);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"right-click-pin"]) {
            [controller hitMainHotKey:nil];
            Down();
            PinWithRightClick();
            if (!Counter(@"right click", @"2 of 3 (pinned)")) return Emit(60);
            Up();
            if (!Counter(@"up", @"1 of 3 (pinned)")) return Emit(61);
            ToggleFavorites();
            if (!Counter(@"f", @"1 of 2 " STAR @" (pinned)")) return Emit(62);
            PinWithRightClick();                           // pinning again changes nothing
            if (!Counter(@"right click again", @"1 of 2 " STAR @" (pinned)")) return Emit(63);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"sticky-bezel"]) {
            // "Sticky bezel": the bezel opens pinned, and its counter says so.
            [controller hitMainHotKey:nil];
            if (!Counter(@"open", @"1 of 3 (pinned)")) return Emit(70);
            Down();
            if (!Counter(@"down", @"2 of 3 (pinned)")) return Emit(71);
            ToggleFavorites();
            if (!Counter(@"f", @"1 of 2 " STAR @" (pinned)")) return Emit(72);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"empty-favorites"]) {
            [controller hitMainHotKey:nil];
            ToggleFavorites();                            // no favorites yet
            if (!Counter(@"f", @"Empty " STAR)) return Emit(80);
            PinWithSpace();
            if (!Counter(@"space", @"Empty " STAR @" (pinned)")) return Emit(81);
            ToggleFavorites();
            if (!Counter(@"f again", @"1 of 3 (pinned)")) return Emit(82);
            Escape();
            return Emit(0);
        }
        return Emit(4);
    }
}
'''

# The real BezelWindow, never ordered in: the counter's star is drawn in the counter's
# grey, not as a colour glyph.
WINDOW_FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <CoreText/CoreText.h>
#import "FixtureIsolation.h"
#import "BezelWindow.h"

static int Fail(int code, NSString *what) { printf("REPORT {\"exit\": %d, \"why\": \"%s\"}\n", code, [what UTF8String]); return code; }

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return Fail(90, @"defaults not in memory");
        BezelWindow *window = [[BezelWindow alloc] initWithContentRect:NSMakeRect(0, 0, 500, 320) styleMask:0
                                                               backing:NSBackingStoreBuffered defer:NO showSource:YES];
        NSString *star = @"\u2605";
        [window setCharString:[@"1 of 2 " stringByAppendingString:star]];
        RoundRecTextField *field = [window valueForKey:@"charField"];
        NSTextField *text = [field textField];
        if (![[text stringValue] hasSuffix:star]) return Fail(91, @"counter not set");
        // The font the counter's text uses for the star (CoreText picks a fallback when
        // the field's font lacks the glyph).
        CTFontRef base = (CTFontRef)[text font];
        CFStringRef glyph = (CFStringRef)star;
        CTFontRef used = CTFontCreateForString(base, glyph, CFRangeMake(0, 1));
        NSString *family = [(NSString *)CTFontCopyFamilyName(used) autorelease];
        CFRelease(used);
        if ([family rangeOfString:@"Emoji" options:NSCaseInsensitiveSearch].location != NSNotFound)
            return Fail(92, [@"star drawn with " stringByAppendingString:family]);
        // Draw the counter field offscreen and compare the star's pixels with the digits'.
        [[window contentView] layoutSubtreeIfNeeded];
        [text sizeToFit];
        NSRect bounds = [text bounds];
        NSBitmapImageRep *rep = [text bitmapImageRepForCachingDisplayInRect:bounds];
        [text cacheDisplayInRect:bounds toBitmapImageRep:rep];
        NSInteger width = [rep pixelsWide], height = [rep pixelsHigh];
        double maxChroma = 0; NSInteger inked = 0;
        for (NSInteger y = 0; y < height; y++)
            for (NSInteger x = 0; x < width; x++) {
                NSColor *c = [[rep colorAtX:x y:y] colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
                if ([c alphaComponent] < 0.25) continue;
                inked++;
                double r = [c redComponent], g = [c greenComponent], b = [c blueComponent];
                double chroma = MAX(r, MAX(g, b)) - MIN(r, MIN(g, b));
                if (chroma > maxChroma) maxChroma = chroma;
            }
        printf("REPORT {\"exit\": %d, \"family\": \"%s\", \"inked\": %ld, \"maxChroma\": %.3f, \"size\": \"%ldx%ld\"}\n",
               inked > 20 && maxChroma <= 0.08 ? 0 : 93, [family UTF8String], (long)inked, maxChroma, (long)width, (long)height);
        return inked > 20 && maxChroma <= 0.08 ? 0 : 93;
    }
}
'''

MODES = {
    "history": "the history's counter changed or got a mark",
    "favorites": "the counter does not mark the Favorites view with a grey star",
    "space-pin": "a bezel pinned with Space lost \"(pinned)\" in its counter",
    "right-click-pin": "a bezel pinned with a right click lost \"(pinned)\" in its counter",
    "sticky-bezel": "a sticky bezel's counter does not say \"(pinned)\"",
    "empty-favorites": "an empty Favorites view does not show the star",
}


def fixture_sources() -> list[pathlib.Path]:
    listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
    return [ROOT / p for p in sorted(listed)
            if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]


def compile_fixture(source: pathlib.Path, binary: pathlib.Path, sources: list[pathlib.Path]) -> subprocess.CompletedProcess:
    command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
               "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
               "-include", str(ROOT / "Flycut_Prefix.pch")]
    for include in sorted({ROOT, FIXTURES, ROOT / "UI", *(p.parent for p in sources)}):
        command += ["-I", str(include)]
    command += [str(p) for p in sources] + [str(source)]
    for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit", "CoreText"):
        command += ["-framework", framework]
    command += ["-o", str(binary)]
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)


class BezelCounterRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-bezel-counter-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "BezelCounterFixture.m"
        source.write_text(FIXTURE)
        cls.binary = temp / "BezelCounterFixture"
        cls.build = compile_fixture(source, cls.binary, fixture_sources())
        window_source = temp / "BezelCounterWindowFixture.m"
        window_source.write_text(WINDOW_FIXTURE)
        cls.window_binary = temp / "BezelCounterWindowFixture"
        cls.window_build = compile_fixture(window_source, cls.window_binary,
                                           [ROOT / "UI" / name for name in
                                            ("BezelWindow.m", "RoundRecTextField.m", "RoundRecBezierPath.m")])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def run_binary(self, binary: pathlib.Path, build: subprocess.CompletedProcess, *args: str) -> tuple[int, str]:
        self.assertEqual(build.returncode, 0, build.stderr[-4000:])
        run = subprocess.run([str(binary), *args], cwd=ROOT, text=True, capture_output=True, timeout=60)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        report = reports[-1] if reports else run.stderr[-1500:]
        print(f"\n{' '.join(args) or binary.name}: exit={run.returncode} {report}")
        return run.returncode, report

    def run_mode(self, mode: str) -> None:
        code, report = self.run_binary(self.binary, self.build, mode)
        self.assertEqual(code, 0, f"{MODES[mode]}; exit={code}; {report}")

    def test_history_counter_is_unchanged(self) -> None:
        self.run_mode("history")

    def test_favorites_view_shows_a_star_in_the_counter(self) -> None:
        self.run_mode("favorites")

    def test_space_pinned_counter_keeps_pinned(self) -> None:
        self.run_mode("space-pin")

    def test_right_click_pinned_counter_keeps_pinned(self) -> None:
        self.run_mode("right-click-pin")

    def test_sticky_bezel_counter_says_pinned(self) -> None:
        self.run_mode("sticky-bezel")

    def test_empty_favorites_counter_shows_the_star(self) -> None:
        self.run_mode("empty-favorites")

    def test_counter_star_is_a_grey_text_glyph_in_the_real_bezel(self) -> None:
        code, report = self.run_binary(self.window_binary, self.window_build)
        self.assertEqual(code, 0, f"the counter's star is not drawn in the counter's grey; {report}")

    def test_counter_uses_the_black_star_not_the_emoji(self) -> None:
        source = (ROOT / "AppController.m").read_text()
        self.assertIn("\\u2605", source)
        for emoji in ("\\u2B50", "\\u2b50", "\u2b50", "\\uFE0F", "\\ufe0f"):
            self.assertNotIn(emoji, source)


if __name__ == "__main__":
    unittest.main()
