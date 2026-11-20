#!/usr/bin/env python3
"""Regression tests for "Paste as plain text" (its global hotkey, Option-Shift-Command-V by default).

The hotkey pastes the CURRENT clipboard without formatting: Flycut puts the clipboard's
plain text alone on the pasteboard (offered lazily, marked transient), waits until the
hotkey's modifier keys are up, posts Command-V through the paste transaction's own path,
and puts the clipboard back once the target app has read the text, or after a timeout;
never over a newer copy, never as a new clipping.

The app fixture links the production AppController with the shared paste test environment
(preferences in memory, NSApp nil). The pasteboard is an in-memory, generation-counted
board holding real NSPasteboardItems, so a lazily provided type reaches the production
provider when the "target" reads it. The target, the frontmost-app lookup, the live
modifier state and the Command-V post are fixture stand-ins; SGHotKeyCenter registers
nothing. The policy fixture compiles FlycutPlainPaste.h alone.
"""
import pathlib
import re
import subprocess
import tempfile
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET = "FCPlainPasteMarker-7f3a"

POLICY_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import "FlycutPlainPaste.h"

static const NSUInteger ShiftCommand = NSEventModifierFlagShift | NSEventModifierFlagCommand;
static const NSUInteger ControlOptionCommand = NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand;

static int Kind(NSArray *items, FlycutPlainPasteKind expected, int code)
{
    FlycutPlainPasteKind kind = FlycutPlainPasteKindForItems(items);
    if (kind != expected) {
        fprintf(stderr, "%s: kind %ld, expected %ld\n", [[items description] UTF8String], (long)kind, (long)expected);
        return code;
    }
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 2) return 2;
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        NSString *text = NSPasteboardTypeString, *rtf = NSPasteboardTypeRTF, *html = NSPasteboardTypeHTML;
        if ([mode isEqualToString:@"kinds"]) {
            int r = 0;
            if ((r = Kind(@[], FlycutPlainPasteNothing, 10))) return r;
            if ((r = Kind(@[@[NSPasteboardTypePNG]], FlycutPlainPasteNothing, 11))) return r;
            if ((r = Kind(@[@[NSPasteboardTypeTIFF, @"com.apple.flat-rtfd"]], FlycutPlainPasteNothing, 12))) return r;
            // Files copied in the Finder carry their names as text; that is no copied text.
            if ((r = Kind(@[@[NSPasteboardTypeFileURL, text, @"com.apple.icns"]], FlycutPlainPasteNothing, 13))) return r;
            if ((r = Kind(@[@[text], @[NSPasteboardTypeFileURL, text]], FlycutPlainPasteNothing, 14))) return r;
            // Plain text alone: the app's own paste already pastes it without formatting.
            if ((r = Kind(@[@[text]], FlycutPlainPasteAsIs, 20))) return r;
            if ((r = Kind(@[@[text, @"public.utf16-external-plain-text", @"NSStringPboardType"]], FlycutPlainPasteAsIs, 21))) return r;
            // A password manager's copy: plain text with markers; it is left untouched.
            if ((r = Kind(@[@[text, FlycutConcealedPasteboardType, @"org.nspasteboard.source"]], FlycutPlainPasteAsIs, 22))) return r;
            if ((r = Kind(@[@[text, @"com.agilebits.onepassword"]], FlycutPlainPasteAsIs, 23))) return r;
            // Formatting or anything unknown next to the text: replaced by the plain text.
            if ((r = Kind(@[@[text, rtf]], FlycutPlainPasteReplace, 30))) return r;
            if ((r = Kind(@[@[html, text, FlycutConcealedPasteboardType]], FlycutPlainPasteReplace, 31))) return r;
            if ((r = Kind(@[@[text, @"com.example.private-editor-data"]], FlycutPlainPasteReplace, 32))) return r;
            if ((r = Kind(@[@[text], @[text]], FlycutPlainPasteReplace, 33))) return r;
            if ((r = Kind(@[@[rtf], @[text]], FlycutPlainPasteReplace, 34))) return r;
            return 0;
        }
        if ([mode isEqualToString:@"collide"]) {
            if (!FlycutHotkeysCollide(9, ShiftCommand, 9, ShiftCommand)) return 40;
            // Only the four hotkey modifiers count (the recorder may add the function flag).
            if (!FlycutHotkeysCollide(9, ShiftCommand | NSEventModifierFlagFunction, 9, ShiftCommand)) return 41;
            if (FlycutHotkeysCollide(9, ShiftCommand, 9, ControlOptionCommand)) return 42;
            if (FlycutHotkeysCollide(9, ShiftCommand, 11, ShiftCommand)) return 43;
            if (FlycutHotkeysCollide(-1, 0, -1, 0)) return 44;  // two empty hotkeys use nothing
            return 0;
        }
        if ([mode isEqualToString:@"wanted"]) {
            // The bezel's and the search window's hotkeys win over the plain-text one.
            if (!FlycutPlainPasteHotkeyIsWanted(9, ShiftCommand, 9, ControlOptionCommand, 1, NSEventModifierFlagControl | NSEventModifierFlagShift)) return 50;
            if (FlycutPlainPasteHotkeyIsWanted(9, ShiftCommand, 9, ShiftCommand, 1, NSEventModifierFlagControl | NSEventModifierFlagShift)) return 51;
            if (FlycutPlainPasteHotkeyIsWanted(9, ShiftCommand, 9, ControlOptionCommand, 9, ShiftCommand)) return 52;
            if (FlycutPlainPasteHotkeyIsWanted(-1, 0, 9, ControlOptionCommand, 1, NSEventModifierFlagControl | NSEventModifierFlagShift)) return 53;
            if (!FlycutPlainPasteHotkeyIsWanted(9, ShiftCommand, -1, 0, -1, 0)) return 54;
            return 0;
        }
        return 3;
    }
}
'''

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import <objc/runtime.h>
#import <Carbon/Carbon.h>
#import "AppController.h"
#import "FlycutPlainPaste.h"
#import "FlycutHotkeyDefaults.h"
#import "SGHotKeyCenter.h"
#import "SGHotKey.h"
#import "SGKeyCombo.h"

@interface AppController (PlainPasteTest)
- (void)setClipboardTrackingPaused:(BOOL)paused;
- (void)hideSearchWindowPreservingPasteTransaction;
- (void)hitMainHotKey:(id)hotKey;
- (void)hitPlainPasteHotKey:(id)hotKey;
- (void)updatePlainPasteHotKeyRegistration;
- (NSEventModifierFlags)liveModifierFlags;
- (void)pollPB:(NSTimer *)timer;
- (BOOL)accessibilityIsTrusted;
- (NSDictionary *)scanMenuShortcutsOfProcess:(pid_t)pid;
- (NSNotificationCenter *)workspaceNotificationCenter;
@end

static int beeps;
void FCTestNSBeep(void) { beeps++; }

static NSString *const Secret = @"FCPlainPasteMarker-7f3a";
static NSString *const Transient = @"org.nspasteboard.TransientType";
static NSString *const Concealed = @"org.nspasteboard.ConcealedType";

// A generation-counted board holding real NSPasteboardItems: a lazily provided type is
// fetched from its provider when it is read, as from a real pasteboard.
@interface PlainBoard : NSObject
@property NSInteger changeCount;
@property(retain) NSMutableArray *items;
@property NSInteger stringReads;
// Mode poll-in-flight: a poll's read of the text, off the main thread, waits after reading
// until the test lets it go on.
@property(assign) dispatch_semaphore_t readStarted, readRelease;
@end
@implementation PlainBoard
- (id)init { if ((self = [super init])) _items = [NSMutableArray new]; return self; }
- (NSArray *)pasteboardItems { return [[self.items copy] autorelease]; }
- (NSArray *)types {
    NSMutableOrderedSet *types = [NSMutableOrderedSet orderedSet];
    for (NSPasteboardItem *item in self.items) [types addObjectsFromArray:[item types]];
    return [types array];
}
- (NSString *)availableTypeFromArray:(NSArray *)types {
    for (NSString *type in types) if ([[self types] containsObject:type]) return type;
    return nil;
}
- (NSInteger)clearContents { self.changeCount++; [self.items removeAllObjects]; return self.changeCount; }
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner { (void)types; (void)owner; return [self clearContents]; }
- (BOOL)writeObjects:(NSArray *)objects {
    for (id object in objects) {
        if (![object isKindOfClass:[NSPasteboardItem class]]) return NO;
        [self.items addObject:object];
    }
    return YES;
}
- (NSPasteboardItem *)itemWithType:(NSString *)type {
    for (NSPasteboardItem *item in self.items) if ([[item types] containsObject:type]) return item;
    return nil;
}
- (NSData *)dataForType:(NSString *)type { return [[self itemWithType:type] dataForType:type]; }
- (NSString *)stringForType:(NSString *)type {
    if ([type isEqualToString:NSPasteboardTypeString]) @synchronized (self) { self.stringReads++; }
    NSString *value = [[self itemWithType:type] stringForType:type];
    if (self.readStarted != NULL && ![NSThread isMainThread]) {
        dispatch_semaphore_signal(self.readStarted);
        dispatch_semaphore_wait(self.readRelease, DISPATCH_TIME_FOREVER);
    }
    return value;
}
- (BOOL)setData:(NSData *)data forType:(NSString *)type {
    if ([self.items count] == 0) [self.items addObject:[[NSPasteboardItem new] autorelease]];
    return [[self.items lastObject] setData:data forType:type];
}
- (BOOL)setString:(NSString *)string forType:(NSString *)type { return [self setData:[string dataUsingEncoding:NSUTF8StringEncoding] forType:type]; }
// Another app's copy: a new generation with these representations.
- (void)copyRepresentations:(NSDictionary *)representations {
    [self clearContents];
    NSPasteboardItem *item = [[NSPasteboardItem new] autorelease];
    for (NSString *type in representations) [item setData:representations[type] forType:type];
    [self.items addObject:item];
}
- (NSDictionary *)representations {
    NSMutableDictionary *all = [NSMutableDictionary dictionary];
    for (NSPasteboardItem *item in self.items) for (NSString *type in [item types]) all[type] = [item dataForType:type] ?: [NSData data];
    return all;
}
@end

@interface PlainTarget : NSObject
@property pid_t pid;
@end
@implementation PlainTarget
- (pid_t)processIdentifier { return self.pid; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { (void)options; return YES; }
- (NSString *)localizedName { return @"Target"; }
- (NSString *)bundleIdentifier { return @"org.example.target"; }
- (NSURL *)bundleURL { return nil; }
@end

@interface PlainOperator : NSObject
@property BOOL paused;
@property(retain) NSMutableArray *added;
@end
@implementation PlainOperator
- (id)init { if ((self = [super init])) _added = [NSMutableArray new]; return self; }
- (bool)storeDisabled { return self.paused; }
- (void)setDisableStoreTo:(bool)value { self.paused = value; }
- (void)applicationWillTerminate {}
// FlycutOperator's list query, answered with an empty history: these tests count what
// -addClipping: received.
- (NSArray *)clippingsInList:(FlycutList)list matching:(NSString *)search { (void)list; (void)search; return @[]; }
// As the shipped filter does by default: concealed and transient copies are skipped.
- (bool)shouldSkip:(NSString *)contents ofType:(NSString *)type fromAvailableTypes:(NSArray *)types {
    (void)contents; (void)type;
    return [types containsObject:Transient] || [types containsObject:Concealed];
}
- (bool)addClipping:(NSString *)contents ofType:(NSString *)type withRichData:(NSDictionary *)rich fromApp:(NSString *)app
    withAppBundleURL:(NSString *)url target:(id)target clippingAddedSelector:(SEL)selector {
    (void)type; (void)rich; (void)app; (void)url; (void)target; (void)selector;
    [self.added addObject:contents ?: @""];
    return YES;
}
- (bool)addClipping:(NSString *)contents ofType:(NSString *)type withRichData:(NSDictionary *)rich fromApp:(NSString *)app
    withAppBundleURL:(NSString *)url target:(id)target clippingAddedSelector:(SEL)selector
    fromClipboardGeneration:(NSInteger)generation {
    (void)generation;
    return [self addClipping:contents ofType:type withRichData:rich fromApp:app withAppBundleURL:url target:target clippingAddedSelector:selector];
}
- (bool)addClipping:(NSString *)contents ofType:(NSString *)type fromApp:(NSString *)app withAppBundleURL:(NSString *)url
    target:(id)target clippingAddedSelector:(SEL)selector {
    return [self addClipping:contents ofType:type withRichData:nil fromApp:app withAppBundleURL:url target:target clippingAddedSelector:selector];
}
- (BOOL)setStackPositionToFirstItem { return YES; }
- (BOOL)restoreStashedStore { return NO; }
- (int)jcListCount { return 0; }
- (BOOL)stackPositionIsInBounds { return NO; }
@end

@interface PlainController : AppController
@property(retain) PlainTarget *target;
@property NSInteger posts;
@property NSInteger heldReads;
@property NSInteger modifierReads;
@property NSInteger modifierReadsAtPost;
@property BOOL accessibilityDenied;
@property double targetReadDelay;  // < 0: the target never reads
@property(copy) NSString *pastedText;
@property(copy) NSArray *typesAtPost;
@property NSInteger changeCountAtPost;
@property BOOL searchWindowLeavesPasteAlone;
@end
@implementation PlainController
- (void)prepare:(PlainBoard *)board operator:(PlainOperator *)op seen:(BOOL)seen {
    jcPasteboard = (id)[board retain];
    flycutOperator = (id)[op retain];
    pbCount = [@(seen ? board.changeCount : board.changeCount - 1) retain];
    pbBlockCount = [@0 retain];
    // Seen: a poll decided on this copy (read through the runtime, so a tree without the
    // instance variable still builds and fails on an assertion).
    Ivar decided = class_getInstanceVariable([AppController class], "pbDecidedGeneration");
    if (decided) *(NSInteger *)((char *)self + ivar_getOffset(decided)) = seen ? board.changeCount : -1;
    // Accessibility counts as granted, as if asked at an activation (this fixture has none).
    Ivar trusted = class_getInstanceVariable([AppController class], "plainPasteAccessibilityTrusted");
    if (trusted) *(BOOL *)((char *)self + ivar_getOffset(trusted)) = YES;
}
// Mode launch-clipboard: the lines with which -awakeFromNib takes the clipboard it finds at
// launch, copied from AppController.m by the test (the pasteboard being this board).
- (void)observeClipboardAtLaunch:(PlainBoard *)board {
    (void)board;
/*LAUNCH_OBSERVATION*/
}
- (BOOL)ownsTransaction { return currentPasteTransaction != nil; }
- (NSInteger)blockedGeneration { return [pbBlockCount integerValue]; }
- (NSRunningApplication *)frontmostApplicationForPaste { return (id)self.target; }
// Launch watches the app in front's menus (MenuShortcutYieldRegressionTests): no real
// workspace or keyboard layout notifications and no Accessibility reads here; Accessibility
// counts as granted.
- (BOOL)accessibilityIsTrusted { return YES; }
- (NSDictionary *)scanMenuShortcutsOfProcess:(pid_t)pid {
    (void)pid;
    return @{@"read": @NO, @"complete": @NO, @"elements": @0, @"seconds": @0, @"shortcuts": @[]};
}
- (NSNotificationCenter *)workspaceNotificationCenter {
    static NSNotificationCenter *center;
    if (center == nil) center = [NSNotificationCenter new];
    return center;
}
- (NSNotificationCenter *)keyboardLayoutNotificationCenter { return [self workspaceNotificationCenter]; }
- (void)showBezel { isBezelDisplayed = YES; }
- (void)hideApp { isBezelDisplayed = NO; }
- (void)updateMenu {}
- (void)updateBezel {}
- (void)fakeCommandV { abort(); }
// Mode quit-during-borrow: hiding the search window no longer ends a paste.
- (void)hideSearchWindow {
    if (self.searchWindowLeavesPasteAlone) [self hideSearchWindowPreservingPasteTransaction];
    else [super hideSearchWindow];
}
// Waits until the clipboard reads queued so far are done; their commits are then on the
// main queue, not run yet.
- (void)waitForClipboardReads { dispatch_sync(clipboardReadQueue, ^{}); }
- (NSEventModifierFlags)liveModifierFlags {
    self.modifierReads++;
    return self.modifierReads <= self.heldReads ? (NSEventModifierFlagShift | NSEventModifierFlagCommand) : 0;
}
- (BOOL)postCommandVToProcessIdentifier:(pid_t)pid {
    if (pid != self.target.pid) abort();
    if (self.accessibilityDenied) return NO;
    self.posts++;
    self.typesAtPost = [jcPasteboard types];
    self.changeCountAtPost = [jcPasteboard changeCount];
    self.modifierReadsAtPost = self.modifierReads;
    if (self.targetReadDelay >= 0) [self performSelector:@selector(targetReads) withObject:nil afterDelay:self.targetReadDelay];
    return YES;
}
// The app pastes: it reads the plain text as any app does, through the pasteboard item.
- (void)targetReads {
    NSPasteboardItem *item = [[jcPasteboard pasteboardItems] firstObject];
    self.pastedText = [item stringForType:NSPasteboardTypeString];
}
@end

static void Spin(double seconds) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]]; }
static void SpinUntil(BOOL (^done)(void), double limit) {
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:limit];
    while (!done() && [end timeIntervalSinceNow] > 0) Spin(0.02);
}

static NSData *Bytes(NSString *s) { return [s dataUsingEncoding:NSUTF8StringEncoding]; }

static NSUInteger registrations, unregistrations;
static NSInteger registeredCode = -2;
static UInt32 registeredModifiers;
static SEL registeredAction;
static BOOL FakeRegister(id self, SEL cmd, SGHotKey *hotKey) {
    (void)self; (void)cmd;
    if ([[hotKey identifier] isEqual:@"plainPasteHotKey"]) {
        registrations++;
        registeredCode = [[hotKey keyCombo] keyCode];
        registeredModifiers = (UInt32)[[hotKey keyCombo] modifiers];
        registeredAction = [hotKey action];
    }
    return YES;
}
static void FakeUnregister(id self, SEL cmd, SGHotKey *hotKey) {
    (void)self; (void)cmd;
    if ([[hotKey identifier] isEqual:@"plainPasteHotKey"]) unregistrations++;
}

static BOOL SameSet(NSArray *a, NSArray *b) { return [[NSSet setWithArray:a] isEqualToSet:[NSSet setWithArray:b]]; }

static int Registration(PlainController *c, NSString *mode) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    // The factory plain-text combination, wherever FlycutHotkeyDefaults.h puts it.
    NSDictionary *factory = FlycutPlainPasteHotkeyDefault();
    if ([mode isEqual:@"register-default"]) {
        [c updatePlainPasteHotKeyRegistration];
        if (registrations != 1 || registeredCode != 9 || registeredModifiers != (optionKey | shiftKey | cmdKey)) {
            fprintf(stderr, "%lu registrations, code %ld modifiers 0x%x\n", (unsigned long)registrations, (long)registeredCode, registeredModifiers);
            return 60;
        }
        if (registeredAction != @selector(hitPlainPasteHotKey:)) return 61;
        [c updatePlainPasteHotKeyRegistration];  // nothing changed: no second registration
        if (registrations != 1 || unregistrations != 0) return 62;
        return 0;
    }
    if ([mode isEqual:@"register-equal-bezel"]) {
        [defaults setObject:factory forKey:FlycutMainHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        return registrations == 0 ? 0 : 63;
    }
    if ([mode isEqual:@"register-equal-search"]) {
        [defaults setObject:factory forKey:@"ShortcutRecorder searchHotkey"];
        [c updatePlainPasteHotKeyRegistration];
        return registrations == 0 ? 0 : 64;
    }
    if ([mode isEqual:@"register-empty"]) {
        [defaults setObject:FlycutHotkeyValue(-1, 0) forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        return registrations == 0 ? 0 : 65;
    }
    if ([mode isEqual:@"register-follows-bezel"]) {
        [defaults setObject:factory forKey:FlycutMainHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if (registrations != 0) return 66;
        [defaults setObject:nil forKey:FlycutMainHotkeyKey];  // back to the bezel's default
        [c updatePlainPasteHotKeyRegistration];
        if (registrations != 1 || unregistrations != 0) return 67;
        [defaults setObject:factory forKey:FlycutMainHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if (unregistrations != 1) return 68;
        return 0;
    }
    if ([mode isEqual:@"launch-registers"]) {
        [c applicationDidFinishLaunching:nil];
        return registrations == 1 && registeredCode == 9 ? 0 : 69;
    }
    return 4;
}

// A copy that a poll is still reading when the hotkey comes (poll-in-flight: the generation
// changes under the read, so that capture is dropped), or whose capture is still on its way to
// the main thread (poll-commit-after-hotkey). Either way it reaches the history exactly once.
static int PollRace(PlainController *c, PlainBoard *board, PlainOperator *op, NSString *mode) {
    BOOL inFlight = [mode isEqual:@"poll-in-flight"];
    if (inFlight) { board.readStarted = dispatch_semaphore_create(0); board.readRelease = dispatch_semaphore_create(0); }
    [c pollPB:nil];
    if (inFlight) {
        if (dispatch_semaphore_wait(board.readStarted, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC))) return 100;
        [c hitPlainPasteHotKey:nil];
        dispatch_semaphore_signal(board.readRelease);
        [c waitForClipboardReads];
        board.readStarted = NULL;
    } else {
        [c waitForClipboardReads];
        [c hitPlainPasteHotKey:nil];
    }
    SpinUntil(^BOOL { return c.posts > 0 && ![[board types] containsObject:Transient]; }, 3.0);
    if (c.posts != 1 || ![c.pastedText isEqual:Secret]) { fprintf(stderr, "posts %ld\n", (long)c.posts); return 101; }
    [c pollPB:nil];
    [c waitForClipboardReads];
    Spin(0.4);
    if (![op.added isEqual:@[Secret]]) {
        fprintf(stderr, "the copy reached the history %lu times\n", (unsigned long)[op.added count]);
        return 102;
    }
    return 0;
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)FakeUnregister);
    PlainBoard *board = [[PlainBoard new] autorelease];
    NSData *rtf = Bytes(@"{\\rtf1 bold}"), *html = Bytes(@"<b>bold</b>");
    NSDictionary *formatted = @{NSPasteboardTypeString: Bytes(Secret), NSPasteboardTypeRTF: rtf, NSPasteboardTypeHTML: html};
    NSDictionary *original = formatted;
    if ([mode isEqual:@"image"]) original = @{NSPasteboardTypePNG: Bytes(@"png bytes")};
    else if ([mode isEqual:@"files"]) original = @{NSPasteboardTypeFileURL: Bytes(@"file:///tmp/flycut-plain-paste-probe.txt"), NSPasteboardTypeString: Bytes(@"probe.txt")};
    else if ([mode isEqual:@"plain-only"]) original = @{NSPasteboardTypeString: Bytes(Secret)};
    else if ([mode isEqual:@"plain-only-concealed"]) original = @{NSPasteboardTypeString: Bytes(Secret), Concealed: [NSData data]};
    else if ([mode isEqual:@"concealed-formatted"]) original = @{NSPasteboardTypeString: Bytes(Secret), NSPasteboardTypeHTML: html, Concealed: [NSData data]};
    if ([mode isEqual:@"empty"]) [board clearContents]; else [board copyRepresentations:original];
    PlainOperator *op = [[PlainOperator new] autorelease];
    op.paused = [mode isEqual:@"paused"] || [mode isEqual:@"resume-during-borrow"] || [mode isEqual:@"resume-before-hotkey"];
    PlainController *c = [[PlainController new] autorelease];
    c.target = [[PlainTarget new] autorelease];
    c.target.pid = [mode isEqual:@"flycut-frontmost"] ? [[NSRunningApplication currentApplication] processIdentifier] : 4242;
    c.targetReadDelay = 0.02;
    [c prepare:board operator:op seen:!([mode isEqual:@"unseen-copy"] || [mode isEqual:@"own-write-unseen"] ||
                                       [mode isEqual:@"resume-during-borrow"] || [mode hasPrefix:@"poll-"] ||
                                       [mode isEqual:@"resume-before-hotkey"] || [mode isEqual:@"launch-clipboard"])];
    // The clipboard holds Flycut's own last paste (blocked), and Flycut has not polled since.
    if ([mode isEqual:@"own-write-unseen"]) [c setValue:@(board.changeCount) forKey:@"pbBlockCount"];
    if ([mode hasPrefix:@"register-"] || [mode isEqual:@"launch-registers"]) return Registration(c, mode);

    NSInteger before = board.changeCount;
    if ([mode isEqual:@"held"]) c.heldReads = 10;
    if ([mode isEqual:@"early-read"]) { c.heldReads = 15; c.targetReadDelay = -1; }
    if ([mode isEqual:@"held-too-long"] || [mode isEqual:@"poll-skips-own-write"]) c.heldReads = 1000000;
    if ([mode isEqual:@"ax-denied"]) c.accessibilityDenied = YES;
    if ([mode isEqual:@"read-late"]) c.targetReadDelay = 1.0;
    if ([mode isEqual:@"no-read"] || [mode isEqual:@"newer-copy"] || [mode isEqual:@"bezel-supersedes"] ||
        [mode isEqual:@"quit-during-borrow"]) c.targetReadDelay = -1;
    if ([mode isEqual:@"poll-in-flight"] || [mode isEqual:@"poll-commit-after-hotkey"]) return PollRace(c, board, op, mode);
    if ([mode isEqual:@"bezel-open"]) [c setValue:@YES forKey:@"isBezelDisplayed"];
    // The copy came while tracking was paused; tracking is resumed before the hotkey.
    if ([mode isEqual:@"resume-before-hotkey"]) [c setClipboardTrackingPaused:NO];
    if ([mode isEqual:@"launch-clipboard"]) {
        // Flycut starts with this copy on the clipboard, and its first poll runs.
        [c observeClipboardAtLaunch:board];
        [c pollPB:nil];
        [c waitForClipboardReads];
    }

    [c hitPlainPasteHotKey:nil];

    if ([mode isEqual:@"image"] || [mode isEqual:@"files"] || [mode isEqual:@"empty"] || [mode isEqual:@"bezel-open"] ||
        [mode isEqual:@"flycut-frontmost"]) {
        Spin(0.5);
        if (beeps != 1) { fprintf(stderr, "%d beeps\n", beeps); return 10; }
        if (c.posts != 0 || board.changeCount != before || [c ownsTransaction]) {
            fprintf(stderr, "posts %ld, generation %ld -> %ld\n", (long)c.posts, (long)before, (long)board.changeCount);
            return 11;
        }
        if (![[board representations] isEqual:([mode isEqual:@"empty"] ? @{} : original)]) return 12;
        return 0;
    }
    if ([mode isEqual:@"plain-only"] || [mode isEqual:@"plain-only-concealed"]) {
        SpinUntil(^BOOL { return c.pastedText != nil; }, 2.0);
        Spin(0.3);
        if (beeps != 0 || c.posts != 1) return 20;
        if (board.changeCount != before || ![[board representations] isEqual:original]) {
            fprintf(stderr, "a plain-text clipboard was rewritten\n");
            return 21;
        }
        if (![c.pastedText isEqual:Secret] || [c ownsTransaction]) return 22;
        return 0;
    }
    if ([mode isEqual:@"poll-skips-own-write"]) {
        Spin(0.2);
        if (![[board types] containsObject:Transient]) return 30;  // precondition: the plain text is placed
        [c pollPB:nil];
        Spin(0.4);
        if (board.stringReads != 0) { fprintf(stderr, "Flycut read its own plain-text item %ld times\n", (long)board.stringReads); return 31; }
        if ([op.added count] != 0) return 32;
        return 0;
    }
    if ([mode isEqual:@"held-too-long"]) {
        Spin(0.5);
        if (c.posts != 0 || ![[board types] containsObject:Transient]) return 40;
        Spin(3.2);
        if (c.posts != 0) return 41;
        if (![[board representations] isEqual:original] || [c ownsTransaction]) { fprintf(stderr, "not restored after the hotkey was held too long\n"); return 42; }
        return 0;
    }
    if ([mode isEqual:@"newer-copy"]) {
        SpinUntil(^BOOL { return c.posts > 0; }, 2.0);
        if (c.posts != 1) return 50;
        [board copyRepresentations:@{NSPasteboardTypeString: Bytes(@"newer copy")}];
        NSInteger newer = board.changeCount;
        Spin(3.3);
        if (board.changeCount != newer || ![[board representations] isEqual:@{NSPasteboardTypeString: Bytes(@"newer copy")}]) {
            fprintf(stderr, "the newer copy was overwritten\n");
            return 51;
        }
        if ([c ownsTransaction]) return 52;
        return 0;
    }
    if ([mode isEqual:@"bezel-supersedes"]) {
        SpinUntil(^BOOL { return c.posts > 0; }, 2.0);
        if (c.posts != 1 || ![[board types] containsObject:Transient]) return 55;
        [c hitMainHotKey:nil];
        if (![[board representations] isEqual:original]) { fprintf(stderr, "opening the bezel left the plain text on the clipboard\n"); return 56; }
        return 0;
    }
    if ([mode isEqual:@"twice"]) {
        // The hotkey again while the first paste still borrows the clipboard.
        c.targetReadDelay = -1;
        SpinUntil(^BOOL { return c.posts > 0; }, 2.0);
        c.targetReadDelay = 0.02;
        [c hitPlainPasteHotKey:nil];
        SpinUntil(^BOOL { return c.posts > 1 && ![[board types] containsObject:Transient]; }, 3.0);
        if (c.posts != 2 || !SameSet(c.typesAtPost, @[NSPasteboardTypeString, Transient])) {
            fprintf(stderr, "second paste: posts %ld types %s\n", (long)c.posts, [[c.typesAtPost description] UTF8String]);
            return 57;
        }
        if (![c.pastedText isEqual:Secret] || ![[board representations] isEqual:original] || [c ownsTransaction]) return 58;
        return 0;
    }
    if ([mode isEqual:@"read-late"]) {
        Spin(0.9);
        if (c.posts != 1 || ![[board types] containsObject:Transient]) { fprintf(stderr, "restored before the target read\n"); return 60; }
        // The read comes about 1.1 s after the hotkey; the clipboard goes back soon after
        // it, long before the 3 s timeout.
        Spin(1.1);
        if (![c.pastedText isEqual:Secret] || ![[board representations] isEqual:original]) { fprintf(stderr, "not restored soon after the read\n"); return 61; }
        return 0;
    }
    if ([mode isEqual:@"early-read"]) {
        // Another clipboard tool reads the plain text before Command-V; the target's own
        // read then goes unseen, so the clipboard waits for the timeout.
        Spin(0.1);
        NSPasteboardItem *item = [[board pasteboardItems] firstObject];
        if (![[item types] containsObject:Transient] || ![[item stringForType:NSPasteboardTypeString] isEqual:Secret]) return 62;
        SpinUntil(^BOOL { return c.posts > 0; }, 3.0);
        if (c.posts != 1 || !SameSet(c.typesAtPost, @[NSPasteboardTypeString, Transient])) { fprintf(stderr, "restored before the paste\n"); return 63; }
        Spin(1.0);
        if (![[board types] containsObject:Transient]) { fprintf(stderr, "an early read cut the wait short\n"); return 64; }
        SpinUntil(^BOOL { return ![[board types] containsObject:Transient]; }, 3.0);
        if (![[board representations] isEqual:original]) return 65;
        return 0;
    }
    if ([mode isEqual:@"no-read"]) {
        Spin(2.0);
        if (c.posts != 1 || ![[board types] containsObject:Transient]) { fprintf(stderr, "restored long before the timeout\n"); return 65; }
        SpinUntil(^BOOL { return ![[board types] containsObject:Transient]; }, 2.5);
        if (![[board representations] isEqual:original] || [c ownsTransaction]) { fprintf(stderr, "not restored after the timeout\n"); return 66; }
        return 0;
    }
    if ([mode isEqual:@"resume-during-borrow"]) {
        // The copy and the paste came while tracking was paused, and tracking is resumed while
        // the plain text is still borrowed: what Flycut puts back is still no new copy.
        SpinUntil(^BOOL { return c.posts > 0; }, 2.0);
        if (c.posts != 1 || ![[board types] containsObject:Transient]) return 110;
        [c setClipboardTrackingPaused:NO];
        SpinUntil(^BOOL { return ![[board types] containsObject:Transient]; }, 3.5);
        if (![[board representations] isEqual:original]) return 111;
        [c pollPB:nil];
        [c waitForClipboardReads];
        Spin(0.4);
        if ([op.added count] != 0) { fprintf(stderr, "a copy made while tracking was paused reached the history\n"); return 112; }
        return 0;
    }
    if ([mode isEqual:@"quit-during-borrow"]) {
        // Flycut quits while the plain text is borrowed: the clipboard goes back at once.
        SpinUntil(^BOOL { return c.posts > 0; }, 2.0);
        if (c.posts != 1 || ![[board types] containsObject:Transient]) return 115;
        c.searchWindowLeavesPasteAlone = YES;
        [c applicationWillTerminate:nil];
        if (![[board representations] isEqual:original] || [c ownsTransaction]) {
            fprintf(stderr, "quitting left the plain text on the clipboard\n");
            return 116;
        }
        return 0;
    }
    if ([mode isEqual:@"ax-denied"]) {
        SpinUntil(^BOOL { return ![c ownsTransaction]; }, 1.0);
        if (c.posts != 0) return 70;
        if (![[board representations] isEqual:original] || [c ownsTransaction]) { fprintf(stderr, "no paste, but the plain text stayed\n"); return 71; }
        return 0;
    }

    // formatted, concealed-formatted, held, unseen-copy, paused: a full plain-text paste.
    // Timers of a background test process can fire 0.1 s late; wait for the outcome.
    SpinUntil(^BOOL { return c.posts > 0 && ![[board types] containsObject:Transient]; }, 3.0);
    if (beeps != 0 || c.posts != 1) { fprintf(stderr, "beeps %d posts %ld\n", beeps, (long)c.posts); return 80; }
    NSArray *expected = [mode isEqual:@"concealed-formatted"] ? @[NSPasteboardTypeString, Transient, Concealed] : @[NSPasteboardTypeString, Transient];
    if (!SameSet(c.typesAtPost, expected)) { fprintf(stderr, "types at the paste: %s\n", [[c.typesAtPost description] UTF8String]); return 81; }
    if (![c.pastedText isEqual:Secret]) { fprintf(stderr, "the target read %s\n", c.pastedText ? "other text" : "nothing"); return 82; }
    if (c.changeCountAtPost != before + 1) return 83;
    if ([mode isEqual:@"held"] && c.modifierReadsAtPost != 11) { fprintf(stderr, "posted after %ld modifier reads\n", (long)c.modifierReadsAtPost); return 84; }
    if (![[board representations] isEqual:original]) { fprintf(stderr, "clipboard not restored: %s\n", [[[board types] description] UTF8String]); return 85; }
    if (board.changeCount != before + 2 || [c ownsTransaction]) return 86;
    if (board.stringReads != 0) return 87;  // Flycut never read the plain text it offered
    [c pollPB:nil];
    Spin(0.4);
    if ([mode isEqual:@"own-write-unseen"]) {
        // Flycut's own paste is no copy to capture, polled or not.
        if ([op.added count] != 0) { fprintf(stderr, "Flycut's own paste became a clipping again\n"); return 92; }
        if ([c blockedGeneration] != board.changeCount) return 93;
    } else if ([mode isEqual:@"unseen-copy"]) {
        // The copy right before the hotkey had not been captured yet; it is captured once now.
        if (![op.added isEqual:@[Secret]]) { fprintf(stderr, "added %s\n", [[op.added description] UTF8String]); return 88; }
        if ([c blockedGeneration] == board.changeCount) return 89;
    } else {
        if ([op.added count] != 0) { fprintf(stderr, "the restored clipboard became a new clipping\n"); return 90; }
        if (!op.paused && [c blockedGeneration] != board.changeCount) return 91;
    }
    return 0;
} }
'''


def launch_observation(source: str) -> str:
    """The lines of -awakeFromNib that take the clipboard found at launch: from its
    jcPasteboard assignment to the next blank line, reading the fixture's board."""
    body = method_body(source, '- (void)awakeFromNib')
    start = body.index('    jcPasteboard = [NSPasteboard generalPasteboard];')
    lines = body[start:body.index('\n\n', start)]
    if 'pbCount = ' not in lines:
        raise AssertionError('-awakeFromNib no longer takes the launch clipboard there')
    return lines.replace('[NSPasteboard generalPasteboard]', '(id)board')


def method_body(source: str, signature: str) -> str:
    """One method's implementation: its signature followed by the opening brace (a
    declaration ends with a semicolon instead)."""
    match = re.search(re.escape(signature) + r"\s*\{", source)
    start = match.start()
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1


class PlainPasteRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = FIXTURE.replace('/*LAUNCH_OBSERVATION*/', launch_observation((ROOT / 'AppController.m').read_text()))
        cls.binary = build_fixture(fixture, 'PlainPasteFixture', extra_flags=('-DNSBeep=FCTestNSBeep',))
        cls.temp = tempfile.TemporaryDirectory(prefix='flycut-plain-policy-')
        source = pathlib.Path(cls.temp.name) / 'Policy.m'
        source.write_text(POLICY_FIXTURE)
        cls.policy = pathlib.Path(cls.temp.name) / 'Policy'
        build = subprocess.run(['/usr/bin/xcrun', 'clang', '-fobjc-arc', '-fmodules', '-mmacosx-version-min=13.5', '-arch', 'arm64',
                                '-I', str(ROOT), str(source), '-framework', 'AppKit', '-o', str(cls.policy)],
                               cwd=ROOT, text=True, capture_output=True, timeout=240)
        if build.returncode:
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, mode):
        run = run_fixture(self.binary, mode)
        output = run.stdout + run.stderr
        self.assertEqual(run.returncode, 0, output)
        # Clipboard contents never reach a log line.
        self.assertNotIn(SECRET, output)

    def check_policy(self, mode):
        run = subprocess.run([str(self.policy), mode], cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    # What the clipboard holds decides what happens.
    def test_kinds_of_clipboard(self):
        self.check_policy('kinds')

    def test_formatted_text_is_pasted_as_plain_text_and_the_clipboard_comes_back(self):
        self.check('formatted')

    def test_plain_text_alone_is_pasted_without_touching_the_clipboard(self):
        self.check('plain-only')

    def test_a_password_managers_copy_is_never_rewritten(self):
        self.check('plain-only-concealed')

    def test_a_concealed_formatted_copy_stays_concealed_while_borrowed(self):
        self.check('concealed-formatted')

    def test_an_image_does_nothing_but_beep(self):
        self.check('image')

    def test_copied_files_do_nothing_but_beep(self):
        self.check('files')

    def test_an_empty_clipboard_does_nothing_but_beep(self):
        self.check('empty')

    # Timing of the paste and of the restore.
    def test_command_v_waits_until_the_modifiers_are_released(self):
        self.check('held')

    def test_held_modifiers_cancel_after_a_limit_and_restore(self):
        self.check('held-too-long')

    def test_restore_waits_for_the_target_apps_read(self):
        self.check('read-late')

    def test_a_read_before_the_paste_does_not_count_as_the_paste(self):
        self.check('early-read')

    def test_restore_after_a_timeout_when_nothing_reads(self):
        self.check('no-read')

    def test_a_newer_copy_is_never_overwritten(self):
        self.check('newer-copy')

    def test_without_a_posted_paste_the_clipboard_comes_back_at_once(self):
        self.check('ax-denied')

    def test_opening_the_bezel_restores_the_clipboard_at_once(self):
        self.check('bezel-supersedes')

    # History and privacy.
    def test_flycut_never_reads_or_captures_its_own_plain_text(self):
        self.check('poll-skips-own-write')

    def test_an_uncaptured_copy_is_captured_once_after_the_restore(self):
        self.check('unseen-copy')

    def test_flycuts_own_paste_is_not_captured_after_the_restore(self):
        self.check('own-write-unseen')

    def test_the_hotkey_again_pastes_the_original_clipboard_as_plain_text(self):
        self.check('twice')

    def test_paused_tracking_still_pastes_and_captures_nothing(self):
        self.check('paused')

    def test_resuming_tracking_during_the_paste_captures_nothing(self):
        self.check('resume-during-borrow')

    def test_a_copy_made_while_paused_stays_out_when_tracking_resumed_before_the_paste(self):
        self.check('resume-before-hotkey')

    def test_the_clipboard_found_at_launch_stays_out_after_the_paste(self):
        self.check('launch-clipboard')

    def test_a_copy_still_being_read_by_a_poll_reaches_the_history_once(self):
        self.check('poll-in-flight')

    def test_a_capture_on_its_way_to_the_main_thread_is_not_added_again(self):
        self.check('poll-commit-after-hotkey')

    def test_quitting_during_the_paste_puts_the_clipboard_back(self):
        self.check('quit-during-borrow')

    def test_nothing_while_the_bezel_is_open(self):
        self.check('bezel-open')

    def test_nothing_when_flycut_itself_is_frontmost(self):
        self.check('flycut-frontmost')

    # Registration.
    def test_hotkeys_collide_only_on_the_same_key_and_modifiers(self):
        self.check_policy('collide')

    def test_the_bezel_and_search_hotkeys_win_over_the_plain_text_one(self):
        self.check_policy('wanted')

    def test_the_factory_hotkey_is_registered(self):
        self.check('register-default')

    def test_not_registered_on_the_bezels_hotkey(self):
        self.check('register-equal-bezel')

    def test_not_registered_on_the_search_hotkey(self):
        self.check('register-equal-search')

    def test_an_empty_hotkey_is_not_registered(self):
        self.check('register-empty')

    def test_registration_follows_the_bezels_hotkey(self):
        self.check('register-follows-bezel')

    def test_registered_at_launch(self):
        self.check('launch-registers')

    def test_one_place_decides_the_registration(self):
        source = (ROOT / 'AppController.m').read_text()
        self.assertEqual(source.count('initWithIdentifier:@"plainPasteHotKey"'), 1)
        body = method_body(source, '- (void)updatePlainPasteHotKeyRegistration')
        self.assertIn('initWithIdentifier:@"plainPasteHotKey"', body)
        self.assertIn('FlycutPlainPasteHotkeyIsWanted(', body)
        delegate = method_body(source, '- (void)shortcutRecorder:(SRRecorderControl *)aRecorder keyComboDidChange:(KeyCombo)newKeyCombo')
        self.assertIn('[self updatePlainPasteHotKeyRegistration];', delegate)
        quit = method_body(source, '- (void)applicationWillTerminate:(NSNotification *)notification')
        self.assertIn('unregisterHotKey: plainPasteHotKey', quit.replace('unregisterHotKey:plainPasteHotKey', 'unregisterHotKey: plainPasteHotKey'))

    def test_help_describes_the_plain_text_paste(self):
        help_text = (ROOT / 'help.md').read_text()
        source = (ROOT / 'AppController.m').read_text()
        section = help_text[help_text.index('**Paste as Plain Text**'):help_text.index('**Text Formatting**')]
        paragraphs = [p for p in section.split('\n\n')[1:] if p.strip()]
        self.assertEqual(paragraphs[0],
                         'Press the Paste as Plain Text hotkey (Option-Shift-Command-V by default, the shortcut Apple uses for '
                         '"Paste and Match Style") to paste what is on the clipboard now, without its formatting such as fonts, '
                         'colors and links, into the app you are working in. Command-V still pastes it with its formatting. '
                         'You can change or clear it under Hotkeys in Preferences.')
        self.assertEqual(paragraphs[1],
                         'For formatted text, Flycut puts the plain text on the clipboard for the paste and then puts back what '
                         'you had copied: right after the app has read the plain text, or after three seconds if no app reads '
                         'it. If you copy something else in the meantime, your new copy stays. Neither the plain text nor what '
                         'Flycut puts back is added to your clipboard history; a copy you made just before is added once, as '
                         'usual. Text without formatting, such as a password from a password manager, is pasted as it is, and '
                         'the clipboard is not touched. If the clipboard holds no text (a picture, files from the Finder, or '
                         'nothing), you hear the alert sound and nothing is pasted. The hotkey works while clipboard tracking '
                         'is paused and needs the same Accessibility permission as pasting from the Bezel; while the Bezel, the '
                         'search window or the clipping list is open, it only plays the alert sound.')
        self.assertEqual(paragraphs[2],
                         'Putting back what you had copied counts as a new copy for other apps: a password manager that '
                         'clears the clipboard after a while may no longer clear its copy if that copy also had formatting, '
                         'a copy from a private window in Safari or Chrome no longer expires, another clipboard manager may '
                         'record it once more, and the app you copied from is no longer the owner of the clipboard.')
        self.assertEqual(paragraphs[3],
                         'Flycut leaves this hotkey to the app in front when one of that app\'s menu commands uses the same '
                         'keys: in TextEdit, Mail, Notes and Safari, Option-Shift-Command-V stays their own "Paste and Match '
                         'Style", and in the Finder its "Paste Exactly". In apps without such a command, such as Terminal, '
                         'Firefox and VS Code, Flycut\'s paste runs. To know, Flycut reads the keyboard shortcuts in the menus '
                         'of the app in front each time an app comes to the front, never the menu titles; this needs the '
                         'Accessibility permission. Without it Flycut cannot paste, so it leaves this hotkey to the apps; '
                         'once you allow it, Flycut takes the hotkey the next time you switch to another app.')
        self.assertEqual(paragraphs[4],
                         'Shortcuts that are not in an app\'s menus are invisible to Flycut, such as those of web pages (Google '
                         'Docs) or VS Code\'s own keybindings; there, Flycut\'s hotkey wins while it is set. The first time an '
                         'app comes to the front after it or Flycut started, reading its menus takes a moment (up to a quarter '
                         'of a second in the apps tried), and a key press in that moment still goes to Flycut. If an app '
                         'changes its menus while it is in front, Flycut notices the next time the app comes to the front.')
        self.assertEqual(paragraphs[5],
                         'On a new install Flycut no longer uses Shift-Command-V, so it does what each app makes of it again: '
                         'the paste without formatting of Google Docs, Chrome and Firefox, "Paste as Quotation" in Mail, '
                         '"Paste Selection" in Terminal and the Markdown preview in VS Code. If you used Flycut before and '
                         'Shift-Command-V opens your Bezel, it stays that way, and Paste as Plain Text is on '
                         'Option-Shift-Command-V for you too. If your Main Hotkey or Search Hotkey already was '
                         'Option-Shift-Command-V, it stays there, and Paste as Plain Text starts without a hotkey.')
        self.assertEqual(len(paragraphs), 6)
        readme = (ROOT / 'readme.md').read_text()
        self.assertRegex(readme, r"\|\s*Option\+Shift\+Command\+V\s*\|\s*Paste the clipboard as plain text\s*\|")
        # "three seconds" is the restore timeout.
        self.assertIn('static const NSTimeInterval kPlainPasteReadTimeout = 3.0;', source)

    def test_the_temporary_item_is_marked_transient(self):
        header = (ROOT / 'FlycutPlainPaste.h').read_text()
        self.assertIn('FlycutTransientPasteboardType = @"org.nspasteboard.TransientType"', header)
        self.assertIn('FlycutConcealedPasteboardType = @"org.nspasteboard.ConcealedType"', header)


if __name__ == '__main__':
    unittest.main()
