#!/usr/bin/env python3
"""Favorites keep their order: pasting never moves a favorite, an equal save keeps its place.

"Move pasted item to top of stack" (pasteMovesToTop) reorders the history only. A favorite
pasted from the bezel's Favorites view (Return, or Enter, which only copies), text or image,
or chosen in the menu-bar list while the bezel shows them, stays where it is, and the
favorites' selection stays on it. A history clipping still moves to the top as before.
With the setting off, its factory default, Return and Enter change no order at all.

Saving a history clipping to the favorites (Shift-F) puts a new favorite on top. With
"Remove duplicates" on, a clipping equal to a favorite takes that favorite's place (as in
master, the saved copy replaces the equal one, but it is not moved to the top), so there
is no second copy, and it still leaves the history. Without "Remove duplicates" a second
copy goes on top, as in master. The saved store and the next launch keep the order.

The fixture compiles the real AppController, FlycutOperator, FlycutStore and the rest of
the app sources (git ls-files '*.m' minus main.m, FlycutHelper and Tests) and drives the
production -hitMainHotKey:, -processBezelKeyDown:, the menu-bar list's
-listController:didChooseClipping:inList: and -pollPB: on a real operator:
favorites are made with Shift-F in the bezel, copies arrive through the
clipboard poll.

Only OS boundaries are replaced. FixtureIsolation.h keeps user defaults in memory; the
pasteboard is an in-process object; NSWorkspace answers with no applications;
+[NSScreen mainScreen] is nil and NSApp stays nil. The bezel is a stand-in object that
records what it shows; like AppKit for a key window, it tells its delegate
(-windowDidResignKey:) when it is ordered out while key. Image files live in a memory
store. The general pasteboard, the status bar and -saveFromStore:atIndex:withPrefix:
(writes files) end the fixture if reached. No NIB is loaded, nothing is shown, and no
clipping contents are logged beyond the fixture's own made-up texts.

Every mode prints one "REPORT {json}" line and exits 0 when the behaviour is right,
10 when a check failed (each failed check is printed as "FAIL <what>"), 2x on setup.
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
#import "FlycutListPanel.h"

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
static BOOL FCForbiddenSave(id self, SEL _cmd, id store, int index, id prefix) {
    fprintf(stderr, "fixture reached -saveFromStore:atIndex:withPrefix: (writes files)\n");
    _exit(98);
}

@interface FCOrderController : AppController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard bezel:(FCFakeBezel *)fake;
- (BOOL)bezelDisplayed;
- (void)drainCaptures;
@end
@implementation FCOrderController
- (NSString *)alertWithMessageText:(NSString *)message informationText:(NSString *)information buttonsTexts:(NSArray *)buttons {
    return [buttons firstObject];
}
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

@interface AppController (FavoritesOrderTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)hitMainHotKey:(id)hotKey;
- (void)savePreferencesOnDict:(NSMutableDictionary *)dict;
- (void)windowDidResignKey:(NSNotification *)notification;
@end

static FCOrderController *controller;
static FlycutOperator *op;
static FCMemoryPasteboard *pasteboard;
static FCFakeBezel *fakeBezel;
static FlycutStore *historyStore, *favoritesStore;
static int failures;

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
    memset([rep bitmapData], 0x7f, (size_t)[rep bytesPerRow] * side);   // the same bytes on every call
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
static void Return(void) { Key(@"\r", 36, 0); Spin(0.7); }                          // paste
static void Enter(void) { Key(@"\x03", 8, NSEventModifierFlagControl); Spin(0.6); }  // copy only
static void SaveToFavorites(void) { Key(@"F", 3, NSEventModifierFlagShift); Spin(0.6); }

static NSString *Name(FlycutClipping *clipping) {
    if (clipping == nil) return @"<none>";
    if ([clipping isImageClipping])
        return [NSString stringWithFormat:@"<image %gx%g>", [clipping imageSize].width, [clipping imageSize].height];
    return [clipping contents] ?: @"<nil>";
}

static NSArray *Contents(FlycutStore *store) {
    NSMutableArray *out = [NSMutableArray array];
    for (int i = 0; i < [store jcListCount]; i++) [out addObject:Name([store clippingAtPosition:i])];
    return out;
}

static NSArray *Saved(NSString *key) {
    NSMutableArray *out = [NSMutableArray array];
    for (NSDictionary *entry in [[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"store"] objectForKey:key]) {
        if ([entry objectForKey:@"ImageHash"])
            [out addObject:[NSString stringWithFormat:@"<image %gx%g>", [[entry objectForKey:@"ImageWidth"] doubleValue],
                                                                   [[entry objectForKey:@"ImageHeight"] doubleValue]]];
        else
            [out addObject:[entry objectForKey:@"Contents"] ?: @"<nil>"];
    }
    return out;
}

static NSString *Selected(void) { return Name([op clippingAtStackPosition]); }
static int Pos(NSString *ivar) { return [[op valueForKey:ivar] intValue]; }

static NSString *Show(id value) {
    return [value isKindOfClass:[NSArray class]] ? [NSString stringWithFormat:@"[%@]", [value componentsJoinedByString:@", "]]
                                                 : [value description];
}

static void Expect(NSString *what, id actual, id expected) {
    if ([actual isEqual:expected]) return;
    failures++;
    fprintf(stderr, "FAIL %s: %s, expected %s\n", [what UTF8String], [Show(actual) UTF8String], [Show(expected) UTF8String]);
}

static NSMutableDictionary *report;
static void Observe(NSString *label) {
    report[label] = @{
        @"favoritesStoreIsSelected": @([op favoritesStoreIsSelected]),
        @"bezelDisplayed": @([controller bezelDisplayed]),
        @"stackPosition": @([op stackPosition]),
        @"favoritesStackPosition": @(Pos(@"favoritesStackPosition")),
        @"selected": Selected(),
        @"historyStore": Contents(historyStore),
        @"favoritesStore": Contents(favoritesStore),
        @"savedJcList": Saved(@"jcList"),
        @"savedFavoritesList": Saved(@"favoritesList"),
    };
}
static int Emit(int code) {
    report[@"exit"] = @(code);
    report[@"failures"] = @(failures);
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

static NSArray *Favorites0(void) { return @[@"fav-3", @"<image 2x2>", @"fav-1"]; }
static NSArray *History0(void) { return @[@"h3", @"h2", @"h1"]; }

// Starts like the app: three favorites made with Shift-F in the bezel (fav-1, an image,
// fav-3; the newest favorite is on top), then the history h1..h3. Saving "after each
// change", so the saved store follows every change. "Move pasted item to top" is on,
// except in the "pref-off-" modes (off is its factory default).
static int Setup(BOOL removeDuplicates, BOOL pasteMovesToTop) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    if (![defaults isMemberOfClass:[FCMemoryDefaults class]]) return 21;
    controller = [[FCOrderController alloc] init];
    op = [[FlycutOperator alloc] init];
    [defaults setObject:@2 forKey:@"savePreference"];
    [defaults setObject:@40 forKey:@"rememberNum"];
    [defaults setObject:@10 forKey:@"favoritesRememberNum"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@YES forKey:@"captureImages"];
    [defaults setObject:@NO forKey:@"downloadAnimatedGIFs"];
    [defaults setObject:@NO forKey:@"menuSelectionPastes"];   // the menu copies, nothing is pasted anywhere
    [defaults setObject:@(removeDuplicates) forKey:@"removeDuplicates"];
    [defaults setObject:@(pasteMovesToTop) forKey:@"pasteMovesToTop"];
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

    for (int i = 0; i < 3; i++) {
        if (i == 1) CopyImage(PNG(2)); else Copy(i == 0 ? @"fav-1" : @"fav-3");
        [controller hitMainHotKey:nil];
        SaveToFavorites();                           // its delayed -hideApp closes the bezel
    }
    Copy(@"h1"); Copy(@"h2"); Copy(@"h3");
    if (![Contents(historyStore) isEqualToArray:History0()]) return 23;
    if (![Contents(favoritesStore) isEqualToArray:Favorites0()]) return 24;
    if ([op favoritesStoreIsSelected] || [controller bezelDisplayed]) return 25;
    if ([imageStore->images count] != 1) return 26;
    Observe(@"0-setup");
    return 0;
}

// Opens the bezel on the favorites and selects the one at `index`.
static void SelectFavorite(int index) {
    [controller hitMainHotKey:nil];
    ToggleFavorites();
    for (int i = 0; i < index; i++) Down();
}

static void ExpectFavoritesKept(NSString *when) {
    Expect([when stringByAppendingString:@": favorites order"], Contents(favoritesStore), Favorites0());
    Expect([when stringByAppendingString:@": saved favorites order"], Saved(@"favoritesList"), Favorites0());
}

// After a paste from the Favorites view: the bezel is closed, the history is current
// again, and the favorites' selection is still the pasted favorite; the next Favorites
// view shows it.
static void ExpectSelectionOnFavorite(NSString *when, int index) {
    Expect([when stringByAppendingString:@": bezel closed, history current"],
           @([op favoritesStoreIsSelected] || [controller bezelDisplayed]), @NO);
    Expect([when stringByAppendingString:@": favorites selection"], @(Pos(@"favoritesStackPosition")), @(index));
    [controller hitMainHotKey:nil];
    ToggleFavorites();
    Expect([when stringByAppendingString:@": next Favorites view shows the pasted favorite"], Selected(),
           Favorites0()[index]);
    Escape();
}

static NSString *PasteboardText(void) { return [pasteboard stringForType:NSPasteboardTypeString] ?: @"<nil>"; }
static NSNumber *PasteboardHasImage(void) {
    return @([[pasteboard dataForType:NSPasteboardTypePNG] isEqual:PNG(2)]);
}

static NSArray *FavoritesAfterRelaunch(void) {
    // A new operator loads the saved store the way the next launch does.
    FlycutOperator *next = [[FlycutOperator alloc] init];
    [next awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
    return Contents([next valueForKey:@"favoritesStore"]);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        report = [[NSMutableDictionary alloc] init];
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        report[@"mode"] = mode;
        Install();
        BOOL removeDuplicates = [mode hasPrefix:@"save-"] && ![mode isEqualToString:@"save-equal-without-remove-duplicates"];
        if ([mode isEqualToString:@"order-survives-relaunch"]) removeDuplicates = YES;
        int failed = Setup(removeDuplicates, ![mode hasPrefix:@"pref-off-"]);
        if (failed) return Emit(failed);

        if ([mode isEqualToString:@"return-pastes-text-favorite-in-place"]) {
            SelectFavorite(2);
            Expect(@"precondition: fav-1 selected", Selected(), @"fav-1");
            Return();
            Observe(@"1-after-return");
            Expect(@"pasteboard", PasteboardText(), @"fav-1");
            ExpectFavoritesKept(@"after Return");
            Expect(@"history untouched", Contents(historyStore), History0());
            ExpectSelectionOnFavorite(@"after Return", 2);
        } else if ([mode isEqualToString:@"return-pastes-image-favorite-in-place"]) {
            SelectFavorite(1);
            Expect(@"precondition: the image selected", Selected(), @"<image 2x2>");
            Return();
            Observe(@"1-after-return");
            Expect(@"pasteboard holds the image", PasteboardHasImage(), @YES);
            ExpectFavoritesKept(@"after Return");
            Expect(@"history untouched", Contents(historyStore), History0());
            ExpectSelectionOnFavorite(@"after Return", 1);
        } else if ([mode isEqualToString:@"enter-copies-text-favorite-in-place"]) {
            SelectFavorite(2);
            Enter();
            Observe(@"1-after-enter");
            Expect(@"pasteboard", PasteboardText(), @"fav-1");
            ExpectFavoritesKept(@"after Enter");
            Expect(@"history untouched", Contents(historyStore), History0());
            ExpectSelectionOnFavorite(@"after Enter", 2);
        } else if ([mode isEqualToString:@"enter-copies-image-favorite-in-place"]) {
            SelectFavorite(1);
            Enter();
            Observe(@"1-after-enter");
            Expect(@"pasteboard holds the image", PasteboardHasImage(), @YES);
            ExpectFavoritesKept(@"after Enter");
            Expect(@"history untouched", Contents(historyStore), History0());
            ExpectSelectionOnFavorite(@"after Enter", 1);
        } else if ([mode isEqualToString:@"list-row-copies-favorite-in-place"]) {
            // A row of the menu-bar list, chosen while the bezel shows the favorites.
            SelectFavorite(0);
            FlycutClipping *favorite = [favoritesStore clippingAtPosition:2];
            [(id<FlycutListControllerDelegate>)controller listController:nil didChooseClipping:favorite
                                                                  inList:FlycutListFavorites];
            Observe(@"1-after-list-row");
            Expect(@"pasteboard", PasteboardText(), @"fav-1");
            ExpectFavoritesKept(@"after the list row");
            Expect(@"the bezel's selection stays", Selected(), @"fav-3");
            Escape();
        } else if ([mode isEqualToString:@"pref-off-history-return-keeps-order"] ||
                   [mode isEqualToString:@"pref-off-history-enter-keeps-order"]) {
            // "Move pasted item to top" off: pasting or copying a history text moves nothing.
            [controller hitMainHotKey:nil];
            Down(); Down();                              // h1
            BOOL enter = [mode hasPrefix:@"pref-off-history-enter"];
            if (enter) Enter(); else Return();
            Observe(@"1-after-key");
            NSString *when = enter ? @"after Enter on a history text" : @"after Return on a history text";
            Expect(@"pasteboard", PasteboardText(), @"h1");
            Expect([when stringByAppendingString:@": history order"], Contents(historyStore), History0());
            Expect([when stringByAppendingString:@": saved history order"], Saved(@"jcList"), History0());
            ExpectFavoritesKept(when);
        } else if ([mode isEqualToString:@"pref-off-favorite-return-keeps-order"] ||
                   [mode isEqualToString:@"pref-off-favorite-enter-keeps-order"]) {
            SelectFavorite(2);
            Expect(@"precondition: fav-1 selected", Selected(), @"fav-1");
            BOOL enter = [mode hasPrefix:@"pref-off-favorite-enter"];
            if (enter) Enter(); else Return();
            Observe(@"1-after-key");
            NSString *when = enter ? @"after Enter on a favorite" : @"after Return on a favorite";
            Expect(@"pasteboard", PasteboardText(), @"fav-1");
            ExpectFavoritesKept(when);
            Expect([when stringByAppendingString:@": history order"], Contents(historyStore), History0());
            Expect([when stringByAppendingString:@": saved history order"], Saved(@"jcList"), History0());
            ExpectSelectionOnFavorite(when, 2);
        } else if ([mode isEqualToString:@"history-return-moves-to-top"]) {
            [controller hitMainHotKey:nil];
            Down(); Down();                              // h1
            Return();
            Observe(@"1-after-return");
            Expect(@"pasteboard", PasteboardText(), @"h1");
            Expect(@"history: h1 moved to the top", Contents(historyStore), (@[@"h1", @"h3", @"h2"]));
            Expect(@"saved history", Saved(@"jcList"), (@[@"h1", @"h3", @"h2"]));
            Expect(@"history selection on the top", @([op stackPosition]), @0);
            ExpectFavoritesKept(@"after a history paste");
        } else if ([mode isEqualToString:@"history-enter-moves-image-to-top"] ||
                   [mode isEqualToString:@"history-return-leaves-image-in-place"]) {
            CopyImage(PNG(3)); Copy(@"h4");
            NSArray *history = @[@"h4", @"<image 3x3>", @"h3", @"h2", @"h1"];
            Expect(@"precondition: history", Contents(historyStore), history);
            [controller hitMainHotKey:nil];
            Down();                                      // the image
            BOOL enter = [mode hasPrefix:@"history-enter"];
            if (enter) Enter(); else Return();
            Observe(@"1-after-key");
            // As in master: Enter (-pasteStorePositionAndUpdate:) moves a history image to the
            // top with pasteMovesToTop; Return (-pasteFromStack's image branch) leaves it.
            Expect(@"history order", Contents(historyStore),
                   enter ? (@[@"<image 3x3>", @"h4", @"h3", @"h2", @"h1"]) : history);
            ExpectFavoritesKept(@"after a history image");
        } else if ([mode isEqualToString:@"save-equal-text-keeps-favorite-in-place"]) {
            Copy(@"fav-1");
            Expect(@"precondition: fav-1 copied into the history", Contents(historyStore), (@[@"fav-1", @"h3", @"h2", @"h1"]));
            FlycutClipping *copy = [[historyStore clippingAtPosition:0] retain];
            [controller hitMainHotKey:nil];
            SaveToFavorites();                           // Shift-F on the copy
            Observe(@"1-after-shift-f");
            ExpectFavoritesKept(@"after Shift-F of an equal text");
            Expect(@"the saved copy took the equal favorite's place", @([favoritesStore clippingAtPosition:2] == copy), @YES);
            Expect(@"the copy left the history", Contents(historyStore), History0());
            Expect(@"saved history", Saved(@"jcList"), History0());
            [copy release];
        } else if ([mode isEqualToString:@"save-equal-image-keeps-favorite-in-place"]) {
            CopyImage(PNG(2));
            Expect(@"precondition: the image copied into the history", Contents(historyStore),
                   (@[@"<image 2x2>", @"h3", @"h2", @"h1"]));
            FlycutClipping *copy = [[historyStore clippingAtPosition:0] retain];
            [controller hitMainHotKey:nil];
            SaveToFavorites();
            Observe(@"1-after-shift-f");
            ExpectFavoritesKept(@"after Shift-F of an equal image");
            Expect(@"the saved copy took the equal favorite's place", @([favoritesStore clippingAtPosition:1] == copy), @YES);
            Expect(@"the copy left the history", Contents(historyStore), History0());
            Expect(@"the image file stays", @([imageStore->images count]), @1);
            [copy release];
        } else if ([mode isEqualToString:@"save-equal-without-remove-duplicates"]) {
            Copy(@"fav-1");
            [controller hitMainHotKey:nil];
            SaveToFavorites();
            Observe(@"1-after-shift-f");
            // Master: without "Remove duplicates" a second copy goes on top.
            Expect(@"favorites: a second copy on top", Contents(favoritesStore), (@[@"fav-1", @"fav-3", @"<image 2x2>", @"fav-1"]));
            Expect(@"saved favorites", Saved(@"favoritesList"), (@[@"fav-1", @"fav-3", @"<image 2x2>", @"fav-1"]));
            Expect(@"the copy left the history", Contents(historyStore), History0());
        } else if ([mode isEqualToString:@"save-new-favorite-goes-to-top"]) {
            Copy(@"new");
            [controller hitMainHotKey:nil];
            SaveToFavorites();
            Observe(@"1-after-shift-f");
            Expect(@"favorites: the new one on top", Contents(favoritesStore), (@[@"new", @"fav-3", @"<image 2x2>", @"fav-1"]));
            Expect(@"saved favorites", Saved(@"favoritesList"), (@[@"new", @"fav-3", @"<image 2x2>", @"fav-1"]));
            Expect(@"it left the history", Contents(historyStore), History0());
        } else if ([mode isEqualToString:@"order-survives-relaunch"]) {
            SelectFavorite(2); Return();                 // paste fav-1
            SelectFavorite(1); Enter();                  // copy the image
            Copy(@"fav-1"); [controller hitMainHotKey:nil]; SaveToFavorites();   // an equal save
            Observe(@"1-after-use");
            ExpectFavoritesKept(@"after use");
            Expect(@"favorites after the next launch", FavoritesAfterRelaunch(), Favorites0());
        } else {
            return Emit(4);
        }
        return Emit(failures ? 10 : 0);
    }
}
'''

MODES = {
    "return-pastes-text-favorite-in-place":
        "Return on a text favorite moved it (pasteMovesToTop must apply to the history only)",
    "return-pastes-image-favorite-in-place": "Return on an image favorite moved it or lost the selection",
    "enter-copies-text-favorite-in-place": "Enter on a text favorite moved it to the top of the favorites",
    "enter-copies-image-favorite-in-place": "Enter on an image favorite moved it to the top of the favorites",
    "list-row-copies-favorite-in-place": "a favorite chosen in the menu-bar list moved to the top",
    "history-return-moves-to-top": "a history paste no longer moves the clipping to the top",
    "history-enter-moves-image-to-top": "Enter on a history image no longer moves it to the top",
    "history-return-leaves-image-in-place": "Return on a history image changed master's order",
    "pref-off-history-return-keeps-order":
        "with Move pasted item to top off, Return on a history text changed an order",
    "pref-off-history-enter-keeps-order":
        "with Move pasted item to top off, Enter on a history text changed an order",
    "pref-off-favorite-return-keeps-order": "with Move pasted item to top off, Return on a favorite changed an order",
    "pref-off-favorite-enter-keeps-order": "with Move pasted item to top off, Enter on a favorite changed an order",
    "save-equal-text-keeps-favorite-in-place":
        "Shift-F of a text equal to a favorite moved that favorite or added a copy",
    "save-equal-image-keeps-favorite-in-place":
        "Shift-F of an image equal to a favorite moved that favorite or added a copy",
    "save-equal-without-remove-duplicates": "without Remove duplicates Shift-F no longer adds a copy on top",
    "save-new-favorite-goes-to-top": "a new favorite no longer goes to the top",
    "order-survives-relaunch": "the favorites order changed by use or after a relaunch",
}


def fixture_sources() -> list[pathlib.Path]:
    listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
    return [ROOT / p for p in sorted(listed)
            if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]


class FavoritesOrderRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-favorites-order-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "FavoritesOrderFixture.m"
        cls.binary = temp / "FavoritesOrderFixture"
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
        fails = [line for line in run.stderr.splitlines() if line.startswith("FAIL ")]
        print(f"\n{mode}: exit={run.returncode} {reports[-1] if reports else '(no report)'}")
        self.assertEqual(run.returncode, 0, f"{MODES[mode]}; exit={run.returncode}; "
                         + ("\n".join(fails) if fails else run.stderr[-1500:]))

    def test_return_pastes_a_text_favorite_in_place(self) -> None:
        self.run_mode("return-pastes-text-favorite-in-place")

    def test_return_pastes_an_image_favorite_in_place(self) -> None:
        self.run_mode("return-pastes-image-favorite-in-place")

    def test_enter_copies_a_text_favorite_in_place(self) -> None:
        self.run_mode("enter-copies-text-favorite-in-place")

    def test_enter_copies_an_image_favorite_in_place(self) -> None:
        self.run_mode("enter-copies-image-favorite-in-place")

    def test_menu_bar_list_copies_a_favorite_in_place(self) -> None:
        self.run_mode("list-row-copies-favorite-in-place")

    def test_history_paste_still_moves_to_the_top(self) -> None:
        self.run_mode("history-return-moves-to-top")

    def test_history_image_enter_still_moves_to_the_top(self) -> None:
        self.run_mode("history-enter-moves-image-to-top")

    def test_history_image_return_keeps_masters_order(self) -> None:
        self.run_mode("history-return-leaves-image-in-place")

    def test_setting_off_return_on_a_history_text_keeps_every_order(self) -> None:
        self.run_mode("pref-off-history-return-keeps-order")

    def test_setting_off_enter_on_a_history_text_keeps_every_order(self) -> None:
        self.run_mode("pref-off-history-enter-keeps-order")

    def test_setting_off_return_on_a_favorite_keeps_every_order(self) -> None:
        self.run_mode("pref-off-favorite-return-keeps-order")

    def test_setting_off_enter_on_a_favorite_keeps_every_order(self) -> None:
        self.run_mode("pref-off-favorite-enter-keeps-order")

    def test_saving_an_equal_text_keeps_the_favorite_in_place(self) -> None:
        self.run_mode("save-equal-text-keeps-favorite-in-place")

    def test_saving_an_equal_image_keeps_the_favorite_in_place(self) -> None:
        self.run_mode("save-equal-image-keeps-favorite-in-place")

    def test_without_remove_duplicates_an_equal_save_adds_a_copy_on_top(self) -> None:
        self.run_mode("save-equal-without-remove-duplicates")

    def test_a_new_favorite_goes_to_the_top(self) -> None:
        self.run_mode("save-new-favorite-goes-to-top")

    def test_the_order_survives_use_and_relaunch(self) -> None:
        self.run_mode("order-survives-relaunch")


ENTER_HELP = ("**Enter** (Fn-Return): Copy the item currently displayed to the clipboard, closing the Bezel. "
              "If \"Move pasted item to top of stack\" is on in Preferences, a clipboard history item also moves "
              "to the front of the history; a favorite always keeps its place.")
FULL_FAVORITES_HELP = ("If the favorites are full (the Favorites number in Preferences), it drops the last one; "
                       "with the Favorites box of \"Save forgotten items to:\" checked, as it is by default, that "
                       "one is saved to a file first.")


class FavoritesOrderTextTests(unittest.TestCase):
    """The Preferences tooltip and the help say what the fixture above checks."""

    def test_tooltip_and_help_say_that_favorites_keep_their_order(self) -> None:
        import xml.etree.ElementTree as ET
        root = ET.parse(ROOT / "English.lproj" / "MainMenu.xib").getroot()
        buttons = [b for b in root.iter("button")
                   if any(x.get("keyPath") == "values.pasteMovesToTop" for x in b.iter("binding"))]
        self.assertEqual(len(buttons), 1, "one checkbox is bound to pasteMovesToTop")
        cell = buttons[0].find("buttonCell")
        self.assertEqual(cell.get("title"), "Move pasted item to top of stack", "the title stays (translations)")
        self.assertEqual(buttons[0].get("toolTip"),
                         "Applies to the clipboard history only. Favorites keep their order when you paste them.")
        help_text = (ROOT / "help.md").read_text()
        self.assertIn("pasting never changes the order of your favorites", help_text)
        self.assertIn("it replaces that favorite in its place instead of adding a second copy", help_text)
        self.assertIn(FULL_FAVORITES_HELP, help_text)
        enter = [line for line in help_text.splitlines() if line.startswith("**Enter** (Fn-Return): ")]
        self.assertEqual(enter, [ENTER_HELP], "the Enter paragraph, true with the setting on and off")


if __name__ == "__main__":
    unittest.main()
