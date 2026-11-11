#!/usr/bin/env python3
"""Copies made while the bezel shows the Favorites list belong to the history.

The fixture compiles the real AppController, FlycutOperator, FlycutStore and the rest
of the app sources (git ls-files '*.m' minus main.m, FlycutHelper and Tests) and drives
the production -hitMainHotKey:, -processBezelKeyDown: and -pollPB: on a real operator,
the way a user and another application would: favorites are made with Shift-F in the
bezel, copies arrive through the clipboard poll.

Only OS boundaries are replaced. FixtureIsolation.h keeps user defaults in memory; the
pasteboard is an in-process object; NSWorkspace answers with no applications;
+[NSScreen mainScreen] is nil and NSApp stays nil. The bezel is a stand-in object that
records what it shows; like AppKit for a key window, it tells its delegate
(-windowDidResignKey:) when it is ordered out while key. Image files live in a memory
store. The general pasteboard, the status bar and -saveFromStore:atIndex:withPrefix:
(writes files) end the fixture if reached. No NIB is loaded, nothing is shown.

Every mode prints one "REPORT {json}" line with the observed stores and exits 0 when
the behaviour is right. Exit codes: 2x setup, 3x-7x the copy checks, 8x control.
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
#import <string.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutClipping.h"
#import "FlycutStore.h"
#import "FlycutImageStore.h"

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
- (void)copyData:(NSData *)data ofType:(NSString *)type;
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
// Copies made by another application.
- (void)copyText:(NSString *)text {
    changeCount++; [types release]; types = [@[NSPasteboardTypeString] retain];
    [values removeAllObjects]; values[NSPasteboardTypeString] = text;
}
- (void)copyData:(NSData *)data ofType:(NSString *)type {
    changeCount++; [types release]; types = [@[type] retain];
    [values removeAllObjects]; values[type] = data;
}
@end

// Image files are an OS boundary: the shared image store keeps them in memory.
@interface FCMemoryImageStore : NSObject {
@public
    NSMutableDictionary *images;
}
@end
@implementation FCMemoryImageStore
- (id)init { if ((self = [super init])) images = [[NSMutableDictionary alloc] init]; return self; }
- (NSString *)hashForData:(NSData *)data { return [NSString stringWithFormat:@"hash-%lu-%lu", (unsigned long)[data hash], (unsigned long)[data length]]; }
- (BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash { images[hash] = data; return YES; }
- (BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext { images[hash] = data; return YES; }
- (BOOL)saveMemoryOnlyImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext { images[hash] = data; return YES; }
- (void)persistMemoryOnlyImageForHash:(NSString *)hash { }
- (NSData *)imageDataForHash:(NSString *)hash { return images[hash]; }
- (NSString *)imageFilePathForHash:(NSString *)hash { return nil; }
- (void)deleteImageForHash:(NSString *)hash { [images removeObjectForKey:hash]; }
- (BOOL)hasImageForHash:(NSString *)hash { return images[hash] != nil; }
- (NSArray *)allStoredHashes { return [images allKeys]; }
- (void)removeEphemeralFiles { }
- (void)removeAllImages { [images removeAllObjects]; }
@end

// Stands in for the BezelWindow: records what it shows. Like AppKit for a key window,
// ordering it out while it is key tells its delegate that it resigned key first.
@interface FCFakeBezel : NSObject {
@public
    id delegate;
    BOOL key, visible, color;
    NSString *text;
    int orderOuts;
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
static FCMemoryImageStore *imageStore;
static id FCSharedWorkspace(id self, SEL _cmd) { return fakeWorkspace; }
static id FCSharedImageStore(id self, SEL _cmd) { return imageStore; }
static id FCNoScreen(id self, SEL _cmd) { return nil; }
static id FCNoImage(id self, SEL _cmd, NSString *name) { return nil; }
static id FCForbidden(id self, SEL _cmd) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: %s\n", sel_getName(_cmd));
    _exit(99);
}
static int forgottenFavoriteExports;
static BOOL countForgottenExports;
static BOOL FCForbiddenSave(id self, SEL _cmd, id store, int index, id prefix) {
    if (countForgottenExports && [prefix isEqual:@"Autosave "]) { forgottenFavoriteExports++; return YES; }   // never writes
    fprintf(stderr, "fixture reached -saveFromStore:atIndex:withPrefix: (writes files)\n");
    _exit(98);
}

@interface FCFavController : AppController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake;
- (BOOL)bezelDisplayed;
- (void)drainCaptures;
@end
@implementation FCFavController
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
@end

@interface AppController (FavoritesViewTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)hitMainHotKey:(id)hotKey;
- (void)savePreferencesOnDict:(NSMutableDictionary *)dict;
@end

static FCFavController *controller;
static FlycutOperator *op;
static FCMemoryPasteboard *pasteboard;
static FCFakeBezel *fakeBezel;
static FlycutStore *historyStore, *favoritesStore;

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

static NSData *PNG(int side) {
    NSBitmapImageRep *rep = [[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:side pixelsHigh:side
        bitsPerSample:8 samplesPerPixel:3 hasAlpha:NO isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace
        bytesPerRow:0 bitsPerPixel:0] autorelease];
    return [rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
}

static void CopyImage(NSData *png) {
    [pasteboard copyData:png ofType:NSPasteboardTypePNG];
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

static NSArray *Contents(FlycutStore *store) {
    NSMutableArray *out = [NSMutableArray array];
    for (int i = 0; i < [store jcListCount]; i++) {
        FlycutClipping *clipping = [store clippingAtPosition:i];
        [out addObject:[clipping isImageClipping] ? @"<image>" : ([clipping contents] ?: @"<nil>")];
    }
    return out;
}

static NSArray *Saved(NSString *key) {
    NSMutableArray *out = [NSMutableArray array];
    for (NSDictionary *entry in [[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"store"] objectForKey:key])
        [out addObject:[entry objectForKey:@"Contents"] ?: @"<nil>"];
    return out;
}

static NSString *Selected(void) {
    FlycutClipping *clipping = [op clippingAtStackPosition];
    if (clipping == nil) return @"<none>";
    return [clipping isImageClipping] ? @"<image>" : ([clipping contents] ?: @"<nil>");
}

static NSMutableDictionary *report;
static void Observe(NSString *label) {
    report[label] = @{
        @"favoritesStoreIsSelected": @([op favoritesStoreIsSelected]),
        @"bezelDisplayed": @([controller bezelDisplayed]),
        @"bezelText": fakeBezel->text ?: @"",
        @"bezelFavoritesColor": @(fakeBezel->color),
        @"stackPosition": @([op stackPosition]),
        @"selected": Selected(),
        @"historyStore": Contents(historyStore),
        @"favoritesStore": Contents(favoritesStore),
        @"savedJcList": Saved(@"jcList"),
        @"savedFavoritesList": Saved(@"favoritesList"),
    };
}
static int Emit(int code) {
    report[@"exit"] = @(code);
    NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
    printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    return code;
}

static void Install(void) {
    fakeWorkspace = [[FCFakeWorkspace alloc] init];
    imageStore = [[FCMemoryImageStore alloc] init];
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)), (IMP)FCSharedWorkspace);
    method_setImplementation(class_getClassMethod([NSScreen class], @selector(mainScreen)), (IMP)FCNoScreen);
    method_setImplementation(class_getClassMethod([NSImage class], @selector(imageNamed:)), (IMP)FCNoImage);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([NSStatusBar class], @selector(systemStatusBar)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)), (IMP)FCSharedImageStore);
    method_setImplementation(class_getInstanceMethod([FlycutOperator class], @selector(saveFromStore:atIndex:withPrefix:)),
                             (IMP)FCForbiddenSave);
}

// Starts like the app: two favorites (moved there with Shift-F in the bezel), then the
// history h1..h3. Saving "after each clip", so the saved store follows every change.
static int Setup(int favoritesLimit) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    if (![defaults isMemberOfClass:[FCMemoryDefaults class]]) return 21;
    controller = [[FCFavController alloc] init];
    op = [[FlycutOperator alloc] init];
    [defaults setObject:@2 forKey:@"savePreference"];
    [defaults setObject:@40 forKey:@"rememberNum"];
    [defaults setObject:@(favoritesLimit) forKey:@"favoritesRememberNum"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@(countForgottenExports) forKey:@"saveForgottenFavorites"];   // factory default is YES
    [defaults setObject:@YES forKey:@"captureImages"];
    [defaults setObject:@NO forKey:@"downloadAnimatedGIFs"];
    [defaults setObject:@NO forKey:@"pasteMovesToTop"];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
    [op setDelegate:(id)controller];
    [op setClippingsStoreDelegate:(id)controller];
    [op setFavoritesStoreDelegate:(id)controller];
    pasteboard = [[FCMemoryPasteboard alloc] init];
    fakeBezel = [[FCFakeBezel alloc] init];
    [controller installOperator:op pasteboard:pasteboard bezel:fakeBezel];
    historyStore = [op valueForKey:@"clippingStore"];
    favoritesStore = [op valueForKey:@"favoritesStore"];
    if (historyStore == nil || favoritesStore == nil || historyStore == favoritesStore) return 22;

    for (NSString *favorite in @[@"fav-1", @"fav-2"]) {
        Copy(favorite);
        [controller hitMainHotKey:nil];
        Key(@"F", 3, NSEventModifierFlagShift);    // Shift-F: move the selected clipping to Favorites
        Spin(0.6);                                   // its delayed -hideApp closes the bezel
    }
    Copy(@"h1"); Copy(@"h2"); Copy(@"h3");
    if (![Contents(historyStore) isEqualToArray:(@[@"h3", @"h2", @"h1"])]) return 23;
    if (![Contents(favoritesStore) isEqualToArray:(@[@"fav-2", @"fav-1"])]) return 24;
    if ([op favoritesStoreIsSelected] || [controller bezelDisplayed]) return 25;
    Observe(@"0-setup");
    return 0;
}

static int OpenFavoritesView(void) {
    [controller hitMainHotKey:nil];                  // the bezel opens on the history
    ToggleFavorites();                               // "f": show Favorites
    if (![op favoritesStoreIsSelected] || ![controller bezelDisplayed]) return 26;
    if (![Selected() isEqualToString:@"fav-2"]) return 27;
    return 0;
}

static BOOL FavoritesUnchanged(void) {
    return [Contents(favoritesStore) isEqualToArray:(@[@"fav-2", @"fav-1"])] &&
           [Saved(@"favoritesList") isEqualToArray:(@[@"fav-2", @"fav-1"])];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        report = [[NSMutableDictionary alloc] init];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        report[@"mode"] = mode;
        Install();
        countForgottenExports = [mode isEqualToString:@"copies-keep-full-favorites"];
        int failed = Setup(countForgottenExports ? 2 : 10);
        if (failed) return Emit(failed);
        if ((failed = OpenFavoritesView())) return Emit(failed);

        if ([mode isEqualToString:@"control-escape"]) {
            Escape();                                // Escape restores the history
            Copy(@"copied-after-escape");
            Observe(@"1-after-escape-and-copy");
            if ([op favoritesStoreIsSelected]) return Emit(81);
            if (![[Contents(historyStore) firstObject] isEqualToString:@"copied-after-escape"]) return Emit(82);
            if (!FavoritesUnchanged()) return Emit(83);
            return Emit(0);
        }
        if ([mode isEqualToString:@"copy-while-favorites-shown"]) {
            Copy(@"copied-while-favorites-shown");   // e.g. Universal Clipboard, a script, a pinned bezel
            Observe(@"1-copy-while-shown");
            if (![[Contents(historyStore) firstObject] isEqualToString:@"copied-while-favorites-shown"]) return Emit(31);
            if (!FavoritesUnchanged()) return Emit(32);
            if (![[Saved(@"jcList") firstObject] isEqualToString:@"copied-while-favorites-shown"]) return Emit(33);
            // The bezel still shows the favorite the user was looking at.
            if (![op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"fav-2"] ||
                ![fakeBezel->text isEqualToString:@"fav-2"]) return Emit(34);
            Escape();
            Observe(@"2-after-escape");
            if (![Contents(historyStore) isEqualToArray:(@[@"copied-while-favorites-shown", @"h3", @"h2", @"h1"])]) return Emit(35);
            if (!FavoritesUnchanged()) return Emit(36);
            return Emit(0);
        }
        if ([mode isEqualToString:@"image-while-favorites-shown"]) {
            Escape();
            [controller hitMainHotKey:nil];
            Down(); Down();                          // select h1 in the history
            ToggleFavorites();
            if (![op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"fav-2"]) return Emit(40);
            CopyImage(PNG(2));
            Observe(@"1-image-while-shown");
            if (![Contents(historyStore) isEqualToArray:(@[@"<image>", @"h3", @"h2", @"h1"])]) return Emit(41);
            if (!FavoritesUnchanged()) return Emit(42);
            if ([imageStore->images count] != 1) return Emit(43);
            if (![Selected() isEqualToString:@"fav-2"]) return Emit(44);
            ToggleFavorites();                       // back to the history: still on h1
            Observe(@"2-back-in-history");
            if ([op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"h1"]) return Emit(45);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"copy-equal-to-favorite"]) {
            Copy(@"fav-2");                          // the same text as the shown (top) favorite
            Observe(@"1-copy-equal-to-favorite");
            if (![[Contents(historyStore) firstObject] isEqualToString:@"fav-2"]) return Emit(51);
            if (!FavoritesUnchanged()) return Emit(52);
            Escape();
            return Emit(0);
        }
        if ([mode isEqualToString:@"selections-follow-their-lists"]) {
            Escape();
            [controller hitMainHotKey:nil];
            Down(); Down();                          // history: h1 selected
            ToggleFavorites();
            Down();                                  // favorites: fav-1 selected
            if (![Selected() isEqualToString:@"fav-1"]) return Emit(60);
            Copy(@"copied-while-favorites-shown");
            Observe(@"1-copy-while-shown");
            if (![[Contents(historyStore) firstObject] isEqualToString:@"copied-while-favorites-shown"]) return Emit(61);
            if (!FavoritesUnchanged()) return Emit(62);
            if (![Selected() isEqualToString:@"fav-1"] || ![fakeBezel->text isEqualToString:@"fav-1"]) return Emit(63);
            ToggleFavorites();                       // back to the history: the selection is still h1
            Observe(@"2-back-in-history");
            if ([op favoritesStoreIsSelected] || ![Selected() isEqualToString:@"h1"]) return Emit(64);
            Key(@"\r", 36, 0);                       // Return pastes the selection
            Spin(0.7);
            Observe(@"3-after-return");
            report[@"pasteboard"] = [pasteboard stringForType:NSPasteboardTypeString] ?: @"<nil>";
            if (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:@"h1"]) return Emit(65);
            return Emit(0);
        }
        if ([mode isEqualToString:@"copies-keep-full-favorites"]) {
            // Favorites limit 2 (full), "save forgotten favorites" on.
            Copy(@"copy-1"); Copy(@"copy-2");
            Observe(@"1-after-two-copies");
            report[@"forgottenFavoriteExports"] = @(forgottenFavoriteExports);
            if (!FavoritesUnchanged()) return Emit(71);
            if (forgottenFavoriteExports != 0) return Emit(72);
            if (![Contents(historyStore) isEqualToArray:(@[@"copy-2", @"copy-1", @"h3", @"h2", @"h1"])]) return Emit(73);
            Escape();
            return Emit(0);
        }
        return Emit(4);
    }
}
'''

MODES = {
    "control-escape": "harness control: Escape from the Favorites view must restore the history",
    "copy-while-favorites-shown": "a copy captured while the bezel showed Favorites did not go into the history",
    "image-while-favorites-shown": "an image copied while the bezel showed Favorites did not go into the history",
    "copy-equal-to-favorite": "a copy equal to the shown favorite was compared with the favorites, not the history",
    "selections-follow-their-lists": "a copy while Favorites were shown moved a selection or missed the history",
    "copies-keep-full-favorites": "copies made while Favorites were shown pushed a favorite out",
}


def fixture_sources() -> list[pathlib.Path]:
    listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
    return [ROOT / p for p in sorted(listed)
            if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]


class FavoritesViewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-favorites-view-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "FavoritesViewFixture.m"
        cls.binary = temp / "FavoritesViewFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
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

    def test_control_escape_restores_history(self) -> None:
        self.run_mode("control-escape")

    def test_copy_while_favorites_shown_goes_to_history(self) -> None:
        self.run_mode("copy-while-favorites-shown")

    def test_image_while_favorites_shown_goes_to_history(self) -> None:
        self.run_mode("image-while-favorites-shown")

    def test_copy_equal_to_shown_favorite_goes_to_history(self) -> None:
        self.run_mode("copy-equal-to-favorite")

    def test_selections_follow_their_own_lists(self) -> None:
        self.run_mode("selections-follow-their-lists")

    def test_copies_do_not_push_out_full_favorites(self) -> None:
        self.run_mode("copies-keep-full-favorites")


if __name__ == "__main__":
    unittest.main()
