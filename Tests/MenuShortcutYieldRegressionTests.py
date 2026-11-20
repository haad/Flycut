#!/usr/bin/env python3
"""Regression tests for "Paste as plain text" giving way to the app in front.

When one of the frontmost app's menu commands uses the plain-text hotkey's keys (Apple's
"Paste and Match Style" on Option-Shift-Command-V in TextEdit, Mail, Notes and Safari, the
Finder's "Paste Exactly"), Flycut releases the hotkey while that app is in front, so the app's
own command runs; it takes the hotkey back when an app without such a command comes forward.
Flycut learns this by reading the app's menu bar through the Accessibility API, key-equivalent
attributes only (FlycutMenuShortcuts.h), on each activation, off the main thread, within a
time budget, cached per process, and only while the hotkey can be registered at all. A failed or
cut-short read keeps Flycut's hotkey, unless an earlier complete read of the same process found
the app's command. The hotkey's key is matched by what it types with Command in the current
keyboard layout. Without Accessibility Flycut neither reads menus nor takes the hotkey.

The policy fixture compiles FlycutMenuShortcuts.h alone; its scanner runs over a fake menu tree
whose reader records every attribute asked for, and whose items carry titles that must never
be asked for. Its time budget runs on a virtual clock that each fake read moves on; the AX
reader's two calls are redirected to fakes by compile flags. The app fixture links the production AppController with the shared paste test
environment: the workspace notification centre, the menu read and the Accessibility check are
stand-ins, and SGHotKeyCenter registers nothing. The keyboard layout calls are redirected by
compile flags to a fake that hands out an installed layout, for this process only; the Mac's
input source is never changed.

The AX encodings used below are the ones the menus of TextEdit, Finder, Terminal and Firefox
report (read-only scan, key equivalents only): AXMenuItemCmdModifiers 0 = Command, 1 = Shift,
2 = Option, 4 = Control, 8 = no Command; AXMenuItemCmdChar is upper case.
"""
import pathlib
import re
import subprocess
import tempfile
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWED_ATTRIBUTES = {'kAXMenuBarAttribute', 'kAXChildrenAttribute', 'kAXMenuItemCmdCharAttribute',
                      'kAXMenuItemCmdVirtualKeyAttribute', 'kAXMenuItemCmdModifiersAttribute'}
TITLE = 'FCMenuTitleMarker-51d2'

POLICY_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import "FlycutMenuShortcuts.h"

static const NSUInteger Cmd = NSEventModifierFlagCommand, Shift = NSEventModifierFlagShift,
    Opt = NSEventModifierFlagOption, Ctrl = NSEventModifierFlagControl;
static const NSUInteger OptShiftCmd = NSEventModifierFlagOption | NSEventModifierFlagShift | NSEventModifierFlagCommand;

// One menu item's key equivalent as AX reports it: character, virtual key, modifiers.
static NSArray *Item(id c, id k, id m) { return @[c ?: [NSNull null], k ?: [NSNull null], m ?: [NSNull null]]; }
static NSArray *V(NSInteger m) { return Item(@"V", nil, @(m)); }

static int Match(NSArray *item, NSUInteger flags, BOOL expected, int code)
{
    if (FlycutMenuShortcutIsHotkey(item, 9, @"v", flags) != expected) {
        fprintf(stderr, "%s against flags 0x%lx: expected %d\n", [[item description] UTF8String], (unsigned long)flags, expected);
        return code;
    }
    return 0;
}

// The key equivalents on V of each app's menus (other keys left out; they never match).
static NSDictionary *Apps(void)
{
    return @{
        // Paste, Paste and Match Style, Paste Style, Paste Ruler
        @"TextEdit": @[V(0), V(3), V(2), V(4), Item(@"S", nil, @0)],
        // Paste, Move Item Here, Paste Exactly
        @"Finder": @[V(0), V(2), V(3)],
        // Paste, Paste as Quotation, Paste and Match Style
        @"Mail": @[V(0), V(1), V(3)],
        @"Notes": @[V(0), V(3)],
        @"Safari": @[V(0), V(3)],
        // Paste, Paste Escaped Text, Paste Selection, Paste Selection Escaped
        @"Terminal": @[V(0), V(4), V(1), V(5)],
        @"Firefox": @[V(0)],
        // VS Code's menus: Paste only (its Markdown preview is a keybinding, not a menu item)
        @"Code": @[V(0), Item(@"P", nil, @1)],
    };
}

// A fake menu tree. Every node has a title the scanner must never ask for.
@interface Node : NSObject
@property(retain) NSArray *children;
@property(retain) NSArray *shortcut;
@end
@implementation Node
@end

static Node *Tree(NSUInteger menus, NSUInteger itemsPerMenu, NSArray *special, NSUInteger specialMenu)
{
    Node *bar = [[Node new] autorelease];
    NSMutableArray *barItems = [NSMutableArray array];
    for (NSUInteger m = 0; m < menus; m++) {
        Node *barItem = [[Node new] autorelease], *menu = [[Node new] autorelease];
        NSMutableArray *items = [NSMutableArray array];
        for (NSUInteger i = 0; i < itemsPerMenu; i++) {
            Node *item = [[Node new] autorelease];
            item.shortcut = Item(@"K", nil, @0);
            [items addObject:item];
        }
        // The special items come first in their menu.
        if (m == specialMenu) for (NSArray *s in special) { Node *item = [[Node new] autorelease]; item.shortcut = s; [items insertObject:item atIndex:0]; }
        menu.children = items;
        barItem.children = @[menu];
        [barItems addObject:barItem];
    }
    bar.children = barItems;
    Node *app = [[Node new] autorelease];
    app.children = @[bar];  // reached only through AXMenuBar
    return app;
}

static NSMutableSet *asked;
static double delayPerElement;
// The scan measures its budget with -[NSProcessInfo systemUptime]. The fixture answers it
// from a clock that only the fake reads move, so the budget cases give the same result on a
// busy machine: real sleeps there took so long that the budget ran out before the first menu.
static NSTimeInterval virtualUptime = 1000.0;
static NSTimeInterval VirtualUptime(id self, SEL cmd) { (void)self; (void)cmd; return virtualUptime; }
static BOOL failMenuBar;
static NSUInteger reads;

static NSArray *FakeRead(id element, NSArray *attributes)
{
    reads++;
    [asked addObjectsFromArray:attributes];
    virtualUptime += delayPerElement;  // a slow element read, on the scan's clock
    Node *node = element;
    NSMutableArray *values = [NSMutableArray array];
    for (NSString *attribute in attributes) {
        id value = [NSNull null];
        if ([attribute isEqual:(NSString *)kAXMenuBarAttribute]) {
            if (failMenuBar) return nil;
            value = [node.children firstObject] ?: [NSNull null];
        } else if ([attribute isEqual:(NSString *)kAXChildrenAttribute]) {
            value = node.shortcut == nil ? (node.children ?: @[]) : [NSNull null];
        } else if ([attribute isEqual:(NSString *)kAXMenuItemCmdCharAttribute]) {
            value = node.shortcut ? node.shortcut[0] : [NSNull null];
        } else if ([attribute isEqual:(NSString *)kAXMenuItemCmdVirtualKeyAttribute]) {
            value = node.shortcut ? node.shortcut[1] : [NSNull null];
        } else if ([attribute isEqual:(NSString *)kAXMenuItemCmdModifiersAttribute]) {
            value = node.shortcut ? node.shortcut[2] : [NSNull null];
        } else if ([attribute isEqual:@"AXTitle"]) {
            value = @"FCMenuTitleMarker-51d2";
        }
        [values addObject:value];
    }
    return values;
}

// FlycutAXReadMenuValues' two AX calls, redirected here by compile flags.
static float lastTimeout = -1;
static CFArrayRef answer;
static AXError answerError = kAXErrorSuccess;
AXError FCTestSetMessagingTimeout(AXUIElementRef element, float timeout) { (void)element; lastTimeout = timeout; return kAXErrorSuccess; }
AXError FCTestCopyMultipleAttributeValues(AXUIElementRef element, CFArrayRef attributes, AXCopyMultipleAttributeOptions options,
                                          CFArrayRef *values)
{
    (void)element; (void)attributes; (void)options;
    if (answerError != kAXErrorSuccess) return answerError;
    *values = (CFArrayRef)CFRetain(answer);
    return kAXErrorSuccess;
}

static BOOL Yields(NSDictionary *scan, NSUInteger flags)
{
    return FlycutPlainPasteYieldsToApp(NO, [scan[@"read"] boolValue] ? scan[@"shortcuts"] : nil, 9, @"v", flags);
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 2) return 2;
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        method_setImplementation(class_getInstanceMethod(object_getClass([NSProcessInfo processInfo]), @selector(systemUptime)), (IMP)VirtualUptime);
        if ([[NSProcessInfo processInfo] systemUptime] != virtualUptime) return 3;
        asked = [[NSMutableSet set] retain];
        FlycutMenuValuesReader reader = ^NSArray *(id element, NSArray *attributes) { return FakeRead(element, attributes); };
        if ([mode isEqualToString:@"modifiers"]) {
            if (FlycutCocoaFlagsForAXMenuModifiers(0) != Cmd) return 10;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierShift) != (Cmd | Shift)) return 11;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierOption) != (Cmd | Opt)) return 12;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierControl) != (Cmd | Ctrl)) return 13;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierShift | kAXMenuItemModifierOption) != OptShiftCmd) return 14;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierNoCommand) != 0) return 15;
            if (FlycutCocoaFlagsForAXMenuModifiers(kAXMenuItemModifierNoCommand | kAXMenuItemModifierShift | kAXMenuItemModifierOption) != (Shift | Opt)) return 16;
            return 0;
        }
        if ([mode isEqualToString:@"encodings"]) {
            int r;
            if ((r = Match(V(3), OptShiftCmd, YES, 20))) return r;
            if ((r = Match(Item(@"v", nil, @3), OptShiftCmd, YES, 21))) return r;   // the character's case does not matter
            if ((r = Match(V(0), OptShiftCmd, NO, 22))) return r;                    // Paste
            if ((r = Match(V(1), OptShiftCmd, NO, 23))) return r;                    // Shift-Command-V
            if ((r = Match(V(1), Shift | Cmd, YES, 24))) return r;
            if ((r = Match(V(2), OptShiftCmd, NO, 25))) return r;
            if ((r = Match(V(7), OptShiftCmd, NO, 26))) return r;                    // Control too
            if ((r = Match(V(8 | 3), OptShiftCmd, NO, 27))) return r;                // no Command
            if ((r = Match(V(8 | 3), Opt | Shift, YES, 28))) return r;
            if ((r = Match(Item(@"V", nil, nil), Cmd, YES, 29))) return r;           // no modifiers attribute: Command alone
            if ((r = Match(Item(nil, @9, @3), OptShiftCmd, YES, 30))) return r;      // a virtual key instead of a character
            if ((r = Match(Item(nil, @8, @3), OptShiftCmd, NO, 31))) return r;
            if ((r = Match(Item(@"B", nil, @3), OptShiftCmd, NO, 32))) return r;
            if ((r = Match(Item(@"", nil, @3), OptShiftCmd, NO, 33))) return r;
            if ((r = Match(Item(nil, nil, @3), OptShiftCmd, NO, 34))) return r;
            if ((r = Match(V(3), OptShiftCmd | NSEventModifierFlagFunction, YES, 35))) return r;  // only the four modifiers count
            if (FlycutMenuShortcutIsHotkey(V(3), -1, nil, 0)) return 36;            // an empty hotkey matches nothing
            if (FlycutMenuShortcutIsHotkey(V(3), 9, nil, OptShiftCmd)) return 37;    // no character for the key: no match by character
            if (!FlycutMenuShortcutIsHotkey(Item(@"V", @9, @3), 9, nil, OptShiftCmd)) return 38;
            if (FlycutMenuShortcutIsHotkey(@[@"V"], 9, @"v", OptShiftCmd)) return 39; // malformed entry
            return 0;
        }
        if ([mode isEqualToString:@"apps"]) {
            NSDictionary *apps = Apps();
            NSSet *keep = [NSSet setWithObjects:@"TextEdit", @"Finder", @"Mail", @"Notes", @"Safari", nil];
            for (NSString *app in apps) {
                BOOL yields = FlycutPlainPasteYieldsToApp(NO, apps[app], 9, @"v", OptShiftCmd);
                if (yields != [keep containsObject:app]) { fprintf(stderr, "%s: yields %d\n", [app UTF8String], yields); return 40; }
            }
            // On Shift-Command-V Flycut would give way to Terminal's Paste Selection and Mail's quote.
            for (NSString *app in apps) {
                BOOL yields = FlycutPlainPasteYieldsToApp(NO, apps[app], 9, @"v", Shift | Cmd);
                if (yields != ([app isEqual:@"Terminal"] || [app isEqual:@"Mail"])) { fprintf(stderr, "%s on shift: %d\n", [app UTF8String], yields); return 41; }
            }
            return 0;
        }
        if ([mode isEqualToString:@"decision"]) {
            NSArray *textEdit = Apps()[@"TextEdit"];
            if (!FlycutPlainPasteYieldsToApp(NO, textEdit, 9, @"v", OptShiftCmd)) return 50;
            if (FlycutPlainPasteYieldsToApp(YES, textEdit, 9, @"v", OptShiftCmd)) return 51;  // Flycut in front
            if (FlycutPlainPasteYieldsToApp(NO, nil, 9, @"v", OptShiftCmd)) return 52;        // menus not read
            if (FlycutPlainPasteYieldsToApp(NO, @[], 9, @"v", OptShiftCmd)) return 53;
            if (FlycutPlainPasteYieldsToApp(NO, textEdit, -1, nil, 0)) return 54;
            return 0;
        }
        if ([mode isEqualToString:@"scan"]) {
            Node *app = Tree(8, 20, @[V(3)], 2);
            NSDictionary *scan = FlycutScanMenuShortcuts(app, reader, 5.0, 4000);
            if (![scan[@"read"] boolValue] || ![scan[@"complete"] boolValue]) return 60;
            // menu bar + 8 bar items + 8 menus + 161 items
            if ([scan[@"elements"] unsignedIntegerValue] != 1 + 8 + 8 + 161) { fprintf(stderr, "elements %s\n", [[scan[@"elements"] description] UTF8String]); return 61; }
            if ([scan[@"shortcuts"] count] != 161) return 62;
            if (!Yields(scan, OptShiftCmd) || Yields(scan, Shift | Cmd)) return 63;
            if (![scan[@"seconds"] isKindOfClass:[NSNumber class]]) return 64;
            return 0;
        }
        if ([mode isEqualToString:@"attributes"]) {
            FlycutScanMenuShortcuts(Tree(3, 5, @[V(3)], 1), reader, 5.0, 4000);
            NSSet *allowed = [NSSet setWithObjects:(NSString *)kAXMenuBarAttribute, (NSString *)kAXChildrenAttribute,
                              (NSString *)kAXMenuItemCmdCharAttribute, (NSString *)kAXMenuItemCmdVirtualKeyAttribute,
                              (NSString *)kAXMenuItemCmdModifiersAttribute, nil];
            if (![asked isSubsetOfSet:allowed]) { fprintf(stderr, "asked for %s\n", [[asked description] UTF8String]); return 70; }
            if (![[NSSet setWithArray:FlycutMenuScanAttributes()] isSubsetOfSet:allowed] || [FlycutMenuScanAttributes() count] != 4) return 71;
            // One read per element: the scan asks for all of an element's attributes at once.
            if (reads != 1 + 1 + 3 + 3 + 16) { fprintf(stderr, "%lu reads\n", (unsigned long)reads); return 72; }
            return 0;
        }
        if ([mode isEqualToString:@"budget"]) {
            delayPerElement = 0.005;
            Node *app = Tree(10, 30, @[V(3)], 9);  // the match is in the last menu
            double start = [[NSProcessInfo processInfo] systemUptime];
            NSDictionary *scan = FlycutScanMenuShortcuts(app, reader, 0.1, 4000);
            double took = [[NSProcessInfo processInfo] systemUptime] - start;
            if (![scan[@"read"] boolValue] || [scan[@"complete"] boolValue]) return 80;
            if (took > 0.1 + 0.05) { fprintf(stderr, "took %.3f s\n", took); return 81; }
            if ([scan[@"elements"] unsignedIntegerValue] >= 300) return 82;
            // Cut short before the match: Flycut keeps its hotkey.
            if (Yields(scan, OptShiftCmd)) return 83;
            return 0;
        }
        if ([mode isEqualToString:@"budget-after-match"]) {
            delayPerElement = 0.005;
            Node *app = Tree(10, 30, @[V(3)], 0);  // the match is in the first menu
            NSDictionary *scan = FlycutScanMenuShortcuts(app, reader, 0.1, 4000);
            if ([scan[@"complete"] boolValue]) return 85;
            // What was read before the budget ran out counts: the app has the command.
            if (!Yields(scan, OptShiftCmd)) return 86;
            return 0;
        }
        if ([mode isEqualToString:@"limit"]) {
            NSDictionary *scan = FlycutScanMenuShortcuts(Tree(20, 300, @[V(3)], 19), reader, 30.0, 1000);
            if ([scan[@"complete"] boolValue] || [scan[@"elements"] unsignedIntegerValue] != 1000) return 90;
            if (Yields(scan, OptShiftCmd)) return 91;
            return 0;
        }
        if ([mode isEqualToString:@"ax-reader"]) {
            // A missing attribute comes back as an AXValue wrapping its error: NSNull. Other
            // values pass as they are, the copied array is released, a failed request is nil.
            AXError noValue = kAXErrorNoValue;
            CGPoint point = CGPointZero;
            AXValueRef missing = AXValueCreate(kAXValueTypeAXError, &noValue), other = AXValueCreate(kAXValueTypeCGPoint, &point);
            NSArray *values = @[(id)missing, @"V", @3, (id)other];
            answer = (CFArrayRef)values;
            CFIndex before = CFGetRetainCount(answer);
            NSArray *read = FlycutAXReadMenuValues(@"element", FlycutMenuScanAttributes());
            if (lastTimeout != FlycutMenuScanMessagingTimeout) return 100;
            if ([read count] != 4 || read[0] != [NSNull null] || ![read[1] isEqual:@"V"] || ![read[2] isEqual:@3] ||
                read[3] != (id)other) { fprintf(stderr, "read %s\n", [[read description] UTF8String]); return 101; }
            if (CFGetRetainCount(answer) != before) return 102;
            answerError = kAXErrorCannotComplete;
            if (FlycutAXReadMenuValues(@"element", FlycutMenuScanAttributes()) != nil) return 103;
            CFRelease(missing);
            CFRelease(other);
            return 0;
        }
        if ([mode isEqualToString:@"fail"]) {
            failMenuBar = YES;
            NSDictionary *scan = FlycutScanMenuShortcuts(Tree(3, 3, @[V(3)], 0), reader, 5.0, 4000);
            if ([scan[@"read"] boolValue] || [scan[@"elements"] unsignedIntegerValue] != 0) return 95;
            if (Yields(scan, OptShiftCmd)) return 96;
            NSDictionary *none = FlycutScanMenuShortcuts([[Node new] autorelease], reader, 5.0, 4000);  // no menu bar
            if ([none[@"read"] boolValue]) return 97;
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
#import "FlycutHotkeyDefaults.h"
#import "FlycutMenuShortcuts.h"
#import "SGHotKeyCenter.h"
#import "SGHotKey.h"
#import "SGKeyCombo.h"

void FCTestNSBeep(void) {}

@interface AppController (MenuYieldTest)
- (void)updatePlainPasteHotKeyRegistration;
- (void)watchFrontmostApplicationMenus;
- (NSDictionary *)scanMenuShortcutsOfProcess:(pid_t)pid;
- (BOOL)accessibilityIsTrusted;
- (NSNotificationCenter *)workspaceNotificationCenter;
- (NSRunningApplication *)frontmostApplicationForPaste;
@end

@interface FakeApp : NSObject
@property pid_t pid;
@property(copy) NSString *bundle;
@end
@implementation FakeApp
- (pid_t)processIdentifier { return self.pid; }
- (NSString *)bundleIdentifier { return self.bundle; }
- (NSURL *)bundleURL { return nil; }
- (BOOL)isTerminated { return NO; }
- (NSString *)localizedName { return @"FCMenuTitleMarker-51d2"; }
@end

static NSArray *V(NSInteger m) { return @[@"V", [NSNull null], @(m)]; }

// The keyboard layout. TISCopyCurrentKeyboardLayoutInputSource (and ShortcutRecorder's
// TISCopyCurrentKeyboardInputSource) are redirected here by compile flags: a case picks an
// installed layout for this process; the Mac's own input source is never changed.
static NSString *layoutID = @"com.apple.keylayout.US";
static TISInputSourceRef layoutSource;
static CFIndex layoutBaseline;
static NSUInteger layoutCopies;
TISInputSourceRef FCTestKeyboardLayout(void) {
    if (layoutSource == NULL) {
        CFArrayRef list = TISCreateInputSourceList((CFDictionaryRef)@{(NSString *)kTISPropertyInputSourceID: layoutID}, true);
        if (list == NULL || CFArrayGetCount(list) != 1) { fprintf(stderr, "no keyboard layout %s\n", [layoutID UTF8String]); exit(7); }
        layoutSource = (TISInputSourceRef)CFRetain(CFArrayGetValueAtIndex(list, 0));
        CFRelease(list);
        layoutBaseline = CFGetRetainCount(layoutSource);
    }
    layoutCopies++;
    return (TISInputSourceRef)CFRetain(layoutSource);  // a Copy: the caller releases it
}
static void UseLayout(NSString *identifier) {
    if (layoutSource != NULL) CFRelease(layoutSource);
    layoutSource = NULL;
    layoutID = identifier;
    FCTestKeyboardLayout();
    CFRelease(layoutSource);
}

static NSUInteger trustQueries;
static NSUInteger plainRegistrations, plainUnregistrations, otherUnregistrations;
static BOOL registeredOffMain;
static BOOL FakeRegister(id self, SEL cmd, SGHotKey *hotKey) {
    (void)self; (void)cmd;
    if (![NSThread isMainThread]) registeredOffMain = YES;
    if ([[hotKey identifier] isEqual:@"plainPasteHotKey"]) plainRegistrations++;
    return YES;
}
static void FakeUnregister(id self, SEL cmd, SGHotKey *hotKey) {
    (void)self; (void)cmd;
    if (![NSThread isMainThread]) registeredOffMain = YES;
    if ([[hotKey identifier] isEqual:@"plainPasteHotKey"]) plainUnregistrations++;
    else otherUnregistrations++;
}

@interface YieldController : AppController
@property(retain) NSNotificationCenter *center;
@property(retain) NSNotificationCenter *layoutCenter;  // the distributed center's stand-in
@property(retain) FakeApp *front;
@property BOOL untrusted;
@property(retain) NSMutableArray *scanned;
@property(retain) NSCondition *gate;
@property BOOL gateOpen;
@property(retain) NSMutableSet *failing;
@property(retain) NSMutableSet *cutShort;
@property(retain) NSMutableSet *withoutCommand;
@end
@implementation YieldController
- (NSNotificationCenter *)workspaceNotificationCenter { return self.center; }
- (NSNotificationCenter *)keyboardLayoutNotificationCenter { return self.layoutCenter; }
// Another process selects another input source: the distributed notification arrives,
// here from a thread other than the main one.
- (void)postLayoutChangeOffMain {
    dispatch_semaphore_t posted = dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        [self.layoutCenter postNotificationName:(NSString *)kTISNotifySelectedKeyboardInputSourceChanged object:nil];
        dispatch_semaphore_signal(posted);
    });
    dispatch_semaphore_wait(posted, DISPATCH_TIME_FOREVER);
    dispatch_release(posted);
}
- (NSRunningApplication *)frontmostApplicationForPaste { return (id)self.front; }
- (BOOL)accessibilityIsTrusted { trustQueries++; return !self.untrusted; }
- (void)updateMenu {}
// The menus of the fake apps, by process: a scan runs off the main thread, as in Flycut.
- (NSDictionary *)scanMenuShortcutsOfProcess:(pid_t)pid {
    if ([NSThread isMainThread]) abort();
    @synchronized (self) { [self.scanned addObject:@(pid)]; }
    @synchronized (self) { if ([self.failing containsObject:@(pid)]) return @{@"read": @NO, @"complete": @NO, @"elements": @0, @"seconds": @0.1, @"shortcuts": @[]}; }
    @synchronized (self) { if ([self.cutShort containsObject:@(pid)]) return @{@"read": @YES, @"complete": @NO, @"elements": @900, @"seconds": @0.5, @"shortcuts": @[V(0)]}; }
    @synchronized (self) { if ([self.withoutCommand containsObject:@(pid)]) return @{@"read": @YES, @"complete": @YES, @"elements": @300, @"seconds": @0.05, @"shortcuts": @[V(0)]}; }
    if (pid == 105) {  // a slow app: its scan ends when the test opens the gate
        [self.gate lock];
        while (!self.gateOpen) [self.gate wait];
        [self.gate unlock];
        return @{@"read": @YES, @"complete": @YES, @"elements": @40, @"seconds": @0.2, @"shortcuts": @[V(0), V(3)]};
    }
    if (pid == 101 || pid == 104) return @{@"read": @YES, @"complete": @YES, @"elements": @366, @"seconds": @0.05, @"shortcuts": @[V(0), V(3), V(2), V(4), V(6)]};
    if (pid == 102) return @{@"read": @YES, @"complete": @YES, @"elements": @361, @"seconds": @0.05, @"shortcuts": @[V(0), V(4), V(1), V(5)]};
    if (pid == 103) return @{@"read": @NO, @"complete": @NO, @"elements": @0, @"seconds": @0.001, @"shortcuts": @[]};
    if (pid == 106) return @{@"read": @YES, @"complete": @NO, @"elements": @1200, @"seconds": @0.5, @"shortcuts": @[V(0)]};
    return @{@"read": @YES, @"complete": @YES, @"elements": @10, @"seconds": @0.01, @"shortcuts": @[]};
}
- (BOOL)plainRegistered { return [self valueForKey:@"plainPasteHotKey"] != nil; }
- (void)activate:(FakeApp *)app {
    self.front = app;
    [self.center postNotificationName:NSWorkspaceDidActivateApplicationNotification object:nil
                             userInfo:@{NSWorkspaceApplicationKey: app}];
}
@end

static FakeApp *App(pid_t pid, NSString *bundle) { FakeApp *a = [[FakeApp new] autorelease]; a.pid = pid; a.bundle = bundle; return a; }

static void Spin(double seconds) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]]; }
static NSUInteger Scans(YieldController *c, pid_t pid) {
    NSUInteger n = 0;
    @synchronized (c) { for (NSNumber *p in c.scanned) if ([p intValue] == pid) n++; }
    return n;
}
// Waits until the scans of an app have come back to the main thread.
static void Settle(YieldController *c, pid_t pid, NSUInteger scans) {
    for (int i = 0; i < 200 && Scans(c, pid) < scans; i++) Spin(0.01);
    Spin(0.1);
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)FakeUnregister);
    YieldController *c = [[YieldController new] autorelease];
    c.center = [[NSNotificationCenter new] autorelease];
    c.layoutCenter = [[NSNotificationCenter new] autorelease];
    c.scanned = [NSMutableArray array];
    c.gate = [[NSCondition new] autorelease];
    c.failing = [NSMutableSet set];
    c.cutShort = [NSMutableSet set];
    c.withoutCommand = [NSMutableSet set];
    UseLayout(@"com.apple.keylayout.US");
    FakeApp *textEdit = App(101, @"com.apple.TextEdit"), *terminal = App(102, @"com.apple.Terminal");
    FakeApp *failing = App(103, @"org.example.failing"), *slow = App(105, @"org.example.slow");
    FakeApp *cut = App(106, @"org.example.huge-menus");
    FakeApp *flycut = App([[NSProcessInfo processInfo] processIdentifier], @"com.generalarcade.flycut");
    c.front = terminal;
    c.untrusted = [mode isEqual:@"untrusted"];

    if ([mode isEqual:@"launch"]) {
        [c applicationDidFinishLaunching:nil];
        Settle(c, 102, 1);
        if (Scans(c, 102) != 1 || ![c plainRegistered]) return 10;  // the app in front at launch is read
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered]) { fprintf(stderr, "launch did not watch activations\n"); return 11; }
        return 0;
    }
    if ([mode isEqual:@"untrusted"]) {
        // Without Accessibility Flycut cannot paste: it neither takes the hotkey nor reads menus.
        [c updatePlainPasteHotKeyRegistration];
        [c watchFrontmostApplicationMenus];
        [c activate:textEdit];
        Spin(0.3);
        if ([c.scanned count] != 0) { fprintf(stderr, "menus read without Accessibility access\n"); return 40; }
        if ([c plainRegistered] || plainRegistrations != 0) { fprintf(stderr, "registered without Accessibility access\n"); return 41; }
        // Allowed later: taken at the next activation, and that app's menus are read.
        c.untrusted = NO;
        [c activate:terminal];
        Settle(c, 102, 1);
        if (![c plainRegistered] || Scans(c, 102) != 1) return 42;
        // Taken away again: released at the next activation, nothing read.
        c.untrusted = YES;
        [c activate:textEdit];
        Spin(0.3);
        if ([c plainRegistered] || Scans(c, 101) != 0) return 48;
        // Asked at activations only: recorder changes and finished reads do not ask again.
        NSUInteger asked = trustQueries;
        for (int i = 0; i < 3; i++) [c updatePlainPasteHotKeyRegistration];
        if (trustQueries != asked) { fprintf(stderr, "Accessibility asked %lu times outside activations\n", (unsigned long)(trustQueries - asked)); return 49; }
        return 0;
    }
    [c updatePlainPasteHotKeyRegistration];
    [c watchFrontmostApplicationMenus];
    Settle(c, 102, 1);
    if (![c plainRegistered] || plainRegistrations != 1) { fprintf(stderr, "Terminal in front: registered %d\n", [c plainRegistered]); return 12; }

    if ([mode isEqual:@"yield"]) {
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered] || plainUnregistrations != 1) { fprintf(stderr, "TextEdit in front: still registered\n"); return 20; }
        [c activate:terminal];
        // Terminal's menus are known: Flycut takes the hotkey back at once, before the new read.
        if (![c plainRegistered]) { fprintf(stderr, "not back at once for a known app\n"); return 21; }
        Settle(c, 102, 2);
        if (![c plainRegistered] || Scans(c, 102) != 2) return 22;  // read again on each activation
        [c activate:textEdit];
        if ([c plainRegistered]) { fprintf(stderr, "a known app's command did not get the key at once\n"); return 23; }
        Settle(c, 101, 2);
        if ([c plainRegistered] || plainRegistrations != 2 || plainUnregistrations != 2) {
            fprintf(stderr, "%lu registrations, %lu unregistrations\n", (unsigned long)plainRegistrations, (unsigned long)plainUnregistrations);
            return 24;
        }
        return 0;
    }
    if ([mode isEqual:@"bezel-never-yields"]) {
        // TextEdit's menus also have Control-Option-Command-V (the bezel's): it stays Flycut's.
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered]) return 25;
        if (otherUnregistrations != 0) { fprintf(stderr, "another hotkey was released\n"); return 26; }
        return 0;
    }
    if ([mode isEqual:@"failed-read"]) {
        [c activate:failing];
        Settle(c, 103, 1);
        if (![c plainRegistered] || plainUnregistrations != 0) return 30;
        return 0;
    }
    if ([mode isEqual:@"failed-reread"]) {
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered]) return 33;
        [c activate:terminal];
        Settle(c, 102, 2);
        // TextEdit's menus cannot be read this time: the last complete read still counts.
        @synchronized (c) { [c.failing addObject:@101]; }
        [c activate:textEdit];
        Settle(c, 101, 2);
        if ([c plainRegistered]) { fprintf(stderr, "a failed read dropped the last complete one\n"); return 34; }
        // A read cut short keeps it as well.
        @synchronized (c) { [c.failing removeObject:@101]; [c.cutShort addObject:@101]; }
        [c activate:terminal];
        Settle(c, 102, 3);
        [c activate:textEdit];
        Settle(c, 101, 3);
        if ([c plainRegistered]) { fprintf(stderr, "a cut-short read replaced the last complete one\n"); return 37; }
        // A complete read replaces it: TextEdit's menus without the command now.
        @synchronized (c) { [c.cutShort removeObject:@101]; [c.withoutCommand addObject:@101]; }
        [c activate:terminal];
        Settle(c, 102, 4);
        [c activate:textEdit];
        Settle(c, 101, 4);
        if (![c plainRegistered]) { fprintf(stderr, "a complete read did not replace the earlier one\n"); return 38; }
        return 0;
    }
    if ([mode isEqual:@"cut-short"]) {
        [c activate:cut];
        Settle(c, 106, 1);
        if (![c plainRegistered] || plainUnregistrations != 0) return 32;
        return 0;
    }
    if ([mode isEqual:@"flycut-in-front"]) {
        [c activate:textEdit];
        Settle(c, 101, 1);
        [c activate:flycut];
        Spin(0.3);
        if (![c plainRegistered]) { fprintf(stderr, "no hotkey while Flycut is in front\n"); return 35; }
        if (Scans(c, flycut.pid) != 0) { fprintf(stderr, "Flycut read its own menus\n"); return 36; }
        return 0;
    }
    if ([mode isEqual:@"not-wanted"]) {
        // A cleared plain-text hotkey, or one on the bezel's keys, needs no menus: none are read.
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setObject:FlycutHotkeyValue(-1, 0) forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if ([c plainRegistered]) return 57;
        [c activate:textEdit];
        Spin(0.3);
        if (Scans(c, 101) != 0) { fprintf(stderr, "menus read for a cleared hotkey\n"); return 58; }
        [defaults setObject:FlycutBezelHotkeyDefault() forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        [c activate:terminal];
        Spin(0.3);
        if (Scans(c, 102) != 1 || [c plainRegistered]) { fprintf(stderr, "menus read for a hotkey the bezel's wins over\n"); return 59; }
        // Wanted again: the app in front is read at once, not only at its next activation.
        [defaults setObject:FlycutPlainPasteHotkeyDefault() forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if (![c plainRegistered]) return 60;
        Settle(c, 102, 2);
        if (Scans(c, 102) != 2) { fprintf(stderr, "the app in front was not read when the hotkey came back\n"); return 61; }
        // Once per activation.
        [c updatePlainPasteHotKeyRegistration];
        Spin(0.2);
        if (Scans(c, 102) != 2) return 62;
        return 0;
    }
    if ([mode isEqual:@"layouts"]) {
        // Russian, Greek and Hebrew layouts and "Dvorak - QWERTY Command" type a Latin v with
        // Command on the V key: TextEdit's Paste and Match Style is on the hotkey's key there and
        // keeps it. Plain Dvorak types k there (its v is on another key): Flycut keeps it.
        NSArray *cases = @[@[@"com.apple.keylayout.US", @YES], @[@"com.apple.keylayout.Russian", @YES],
                           @[@"com.apple.keylayout.Greek", @YES], @[@"com.apple.keylayout.Hebrew", @YES],
                           @[@"com.apple.keylayout.DVORAK-QWERTYCMD", @YES], @[@"com.apple.keylayout.Dvorak", @NO]];
        NSUInteger round = 0;
        for (NSArray *one in cases) {
            round++;
            UseLayout(one[0]);
            layoutCopies = 0;
            [c activate:textEdit];
            Settle(c, 101, round);
            if ([c plainRegistered] == [one[1] boolValue]) {
                fprintf(stderr, "%s: registered %d with TextEdit in front\n", [one[0] UTF8String], [c plainRegistered]);
                return 63;
            }
            if (layoutCopies == 0) { fprintf(stderr, "%s: the keyboard layout was not asked\n", [one[0] UTF8String]); return 64; }
            [c activate:terminal];
            Settle(c, 102, round + 1);
            if (![c plainRegistered]) return 65;
        }
        return 0;
    }
    if ([mode isEqual:@"layout-change"]) {
        // TextEdit in front keeps its Paste and Match Style on the V key. The user picks
        // Dvorak (k on that key, v elsewhere) while TextEdit stays in front: Flycut takes the
        // hotkey at once, on the main thread, from what it read before; back to US, it gives
        // way again.
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered]) return 70;
        UseLayout(@"com.apple.keylayout.Dvorak");
        [c postLayoutChangeOffMain];
        for (int i = 0; i < 100 && ![c plainRegistered]; i++) Spin(0.01);
        if (![c plainRegistered]) { fprintf(stderr, "a keyboard layout change was not noticed\n"); return 71; }
        if (registeredOffMain) { fprintf(stderr, "registered off the main thread\n"); return 72; }
        UseLayout(@"com.apple.keylayout.US");
        [c postLayoutChangeOffMain];
        for (int i = 0; i < 100 && [c plainRegistered]; i++) Spin(0.01);
        if ([c plainRegistered] || registeredOffMain) return 73;
        if (Scans(c, 101) != 1) { fprintf(stderr, "a layout change read the menus again\n"); return 74; }
        // Once Flycut quits, a layout change takes no hotkey.
        [c applicationWillTerminate:nil];
        UseLayout(@"com.apple.keylayout.Dvorak");
        [c postLayoutChangeOffMain];
        Spin(0.3);
        if ([c plainRegistered]) { fprintf(stderr, "a layout change after quitting took the hotkey\n"); return 75; }
        return 0;
    }
    if ([mode isEqual:@"layout-released"]) {
        // Every look at the keyboard layout gives its reference back.
        for (int i = 0; i < 5; i++) {
            [c activate:textEdit];
            Settle(c, 101, i + 1);
            [c activate:terminal];
            Settle(c, 102, i + 2);
        }
        if (layoutCopies == 0) return 66;
        if (CFGetRetainCount(layoutSource) != layoutBaseline) {
            fprintf(stderr, "%lu looks, %ld references kept\n", (unsigned long)layoutCopies, (long)(CFGetRetainCount(layoutSource) - layoutBaseline));
            return 67;
        }
        return 0;
    }
    if ([mode isEqual:@"stale"]) {
        // The slow app's menus (with the command) come back after Terminal is in front again.
        [c activate:slow];
        for (int i = 0; i < 100 && Scans(c, 105) == 0; i++) Spin(0.01);
        if (Scans(c, 105) != 1) return 43;
        // Meanwhile TextEdit and then Terminal come forward: TextEdit's read, not begun yet,
        // is dropped; Terminal is known and registered at once.
        [c activate:textEdit];
        [c activate:terminal];
        if (![c plainRegistered]) return 44;
        [c.gate lock]; c.gateOpen = YES; [c.gate broadcast]; [c.gate unlock];
        Settle(c, 102, 2);
        if (![c plainRegistered]) { fprintf(stderr, "a stale read released the hotkey\n"); return 45; }
        if (Scans(c, 101) != 0) { fprintf(stderr, "a superseded read ran\n"); return 47; }
        // Its result is kept for that app.
        [c activate:slow];
        if ([c plainRegistered]) return 46;
        return 0;
    }
    if ([mode isEqual:@"hotkey-change"]) {
        // Terminal has Shift-Command-V (Paste Selection). Recording that combination for the
        // plain-text paste makes Flycut give way at once, from what it read before.
        [[NSUserDefaults standardUserDefaults] setObject:FlycutHotkeyValue(9, NSEventModifierFlagShift | NSEventModifierFlagCommand)
                                                  forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if ([c plainRegistered]) return 50;
        if (Scans(c, 102) != 1) return 51;
        [[NSUserDefaults standardUserDefaults] setObject:FlycutPlainPasteHotkeyDefault() forKey:FlycutPlainPasteHotkeyKey];
        [c updatePlainPasteHotKeyRegistration];
        if (![c plainRegistered]) return 52;
        return 0;
    }
    if ([mode isEqual:@"terminated"]) {
        [c activate:textEdit];
        Settle(c, 101, 1);
        if ([c plainRegistered]) return 55;
        [c.center postNotificationName:NSWorkspaceDidTerminateApplicationNotification object:nil
                              userInfo:@{NSWorkspaceApplicationKey: textEdit}];
        // A new process with the same number is not TextEdit: what was read is gone with it.
        FakeApp *reused = App(101, @"com.apple.TextEdit");
        c.front = reused;
        [c.center postNotificationName:NSWorkspaceDidActivateApplicationNotification object:nil
                              userInfo:@{NSWorkspaceApplicationKey: reused}];
        if (![c plainRegistered]) { fprintf(stderr, "a terminated app's menus applied to a new process\n"); return 56; }
        return 0;
    }
    return 4;
} }
'''


def method_body(source: str, signature: str) -> str:
    match = re.search(re.escape(signature) + r"\s*\{", source)
    assert match is not None, signature
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


def menu_section(source: str) -> str:
    start = source.index('#pragma mark - Plain-text hotkey and the apps\' own menus')
    end = source.index('#pragma mark', start + 10)
    return source[start:end]


class MenuShortcutYieldRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'MenuYieldFixture', extra_flags=(
            '-DNSBeep=FCTestNSBeep', '-DTISCopyCurrentKeyboardLayoutInputSource=FCTestKeyboardLayout',
            '-DTISCopyCurrentKeyboardInputSource=FCTestKeyboardLayout'))
        cls.temp = tempfile.TemporaryDirectory(prefix='flycut-menu-policy-')
        source = pathlib.Path(cls.temp.name) / 'Policy.m'
        source.write_text(POLICY_FIXTURE)
        cls.policy = pathlib.Path(cls.temp.name) / 'Policy'
        build = subprocess.run(['/usr/bin/xcrun', 'clang', '-fno-objc-arc', '-fobjc-weak', '-fblocks', '-fmodules',
                                '-mmacosx-version-min=13.5', '-arch', 'arm64', '-I', str(ROOT),
                                '-DAXUIElementSetMessagingTimeout=FCTestSetMessagingTimeout',
                                '-DAXUIElementCopyMultipleAttributeValues=FCTestCopyMultipleAttributeValues', str(source),
                                '-framework', 'AppKit', '-framework', 'ApplicationServices', '-framework', 'Carbon',
                                '-o', str(cls.policy)],
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
        self.assertNotIn(TITLE, output)
        return output

    def check_policy(self, mode):
        run = subprocess.run([str(self.policy), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn(TITLE, run.stdout + run.stderr)

    # The decision.
    def test_ax_modifier_encoding(self):
        self.check_policy('modifiers')

    def test_menu_key_equivalents_match_only_the_exact_combination(self):
        self.check_policy('encodings')

    def test_apps_with_paste_and_match_style_keep_their_command(self):
        self.check_policy('apps')

    def test_no_yield_for_flycut_or_unread_menus(self):
        self.check_policy('decision')

    # The menu read.
    def test_the_scan_collects_every_key_equivalent(self):
        self.check_policy('scan')

    def test_the_scan_asks_only_for_key_equivalent_attributes(self):
        self.check_policy('attributes')

    def test_the_scan_stops_at_its_time_budget_and_keeps_flycuts_hotkey(self):
        self.check_policy('budget')

    def test_a_match_read_before_the_budget_ran_out_counts(self):
        self.check_policy('budget-after-match')

    def test_the_scan_stops_at_its_element_limit(self):
        self.check_policy('limit')

    def test_a_failed_read_keeps_flycuts_hotkey(self):
        self.check_policy('fail')

    def test_the_ax_reader_maps_a_missing_attribute_to_null(self):
        self.check_policy('ax-reader')

    def test_only_key_equivalent_attributes_appear_in_the_source(self):
        header = (ROOT / 'FlycutMenuShortcuts.h').read_text()
        section = menu_section((ROOT / 'AppController.m').read_text())
        for name, text in (('FlycutMenuShortcuts.h', header), ('AppController.m menu section', section)):
            self.assertLessEqual(set(re.findall(r'\bkAX\w*Attribute\b', text)), ALLOWED_ATTRIBUTES, name)
            self.assertEqual(re.findall(r'["\']AX[A-Z]\w*["\']', text), [], name)
            for call in ('AXUIElementCopyAttributeNames', 'AXUIElementCopyAttributeValue(', 'AXUIElementCopyParameterizedAttributeValue',
                         'kAXTitleAttribute', 'kAXValueAttribute', 'kAXDescriptionAttribute', 'localizedName'):
                self.assertNotIn(call, text, name)
        reader = method_body(header, 'static inline NSArray *FlycutAXReadMenuValues(id element, NSArray *attributes)')
        self.assertIn('AXUIElementSetMessagingTimeout(', reader)
        self.assertIn('AXUIElementCopyMultipleAttributeValues(', reader)

    # Flycut's hotkey and the app in front.
    def test_the_hotkey_follows_the_app_in_front(self):
        self.check('yield')

    def test_the_bezel_hotkey_never_gives_way(self):
        self.check('bezel-never-yields')

    def test_a_failed_read_keeps_the_hotkey_and_logs_no_titles(self):
        output = self.check('failed-read')
        lines = [l for l in output.splitlines() if 'Menu shortcut check' in l]
        self.assertEqual(len(lines), 1, output)
        self.assertRegex(lines[0], r'Menu shortcut check for org\.example\.failing: menus not read '
                                   r'\(\d+ ms, 0 menu elements\); Flycut keeps its hotkey$')

    def test_a_failed_or_cut_short_new_read_keeps_the_last_complete_one(self):
        self.check('failed-reread')

    def test_a_cut_short_read_without_the_command_keeps_the_hotkey(self):
        output = self.check('cut-short')
        self.assertRegex(output, r'Menu shortcut check for org\.example\.huge-menus: cut short '
                                 r'\(\d+ ms, 1200 menu elements\); Flycut keeps its hotkey')

    def test_flycut_in_front_keeps_the_hotkey_and_is_not_read(self):
        self.check('flycut-in-front')

    def test_without_accessibility_access_flycut_neither_reads_nor_takes_the_hotkey(self):
        self.check('untrusted')

    def test_no_menus_are_read_while_the_hotkey_is_not_wanted(self):
        self.check('not-wanted')

    def test_layouts_that_type_latin_letters_with_command_keep_the_apps_command(self):
        self.check('layouts')

    def test_every_look_at_the_keyboard_layout_releases_it(self):
        self.check('layout-released')

    def test_a_keyboard_layout_change_decides_again(self):
        self.check('layout-change')

    def test_the_layout_is_read_without_dead_key_processing(self):
        # UCKeyTranslate takes its options as a mask; kUCKeyTranslateNoDeadKeysBit is the
        # bit's number (0), which turns dead-key processing on. For the display action the
        # character comes out the same either way, so the source is checked.
        helper = method_body((ROOT / 'FlycutMenuShortcuts.h').read_text(),
                             'static inline NSString *FlycutMenuCharacterForKeyCode(NSInteger keyCode)')
        self.assertIn('kUCKeyTranslateNoDeadKeysMask', helper)
        self.assertNotIn('kUCKeyTranslateNoDeadKeysBit', helper)

    def test_the_hotkey_character_comes_from_the_command_layout(self):
        section = menu_section((ROOT / 'AppController.m').read_text())
        self.assertNotIn('SRCharacterForKeyCodeAndCocoaFlags', section)
        self.assertEqual(section.count('FlycutMenuCharacterForKeyCode(plain.code)'), 2)
        helper = method_body((ROOT / 'FlycutMenuShortcuts.h').read_text(),
                             'static inline NSString *FlycutMenuCharacterForKeyCode(NSInteger keyCode)')
        self.assertIn('TISCopyCurrentKeyboardLayoutInputSource()', helper)
        self.assertIn('(cmdKey >> 8) & 0xFF', helper)
        self.assertIn('CFRelease(source);', helper)

    def test_a_read_for_an_app_no_longer_in_front_changes_nothing(self):
        self.check('stale')

    def test_a_new_hotkey_is_checked_against_what_was_read(self):
        self.check('hotkey-change')

    def test_a_terminated_apps_menus_are_forgotten(self):
        self.check('terminated')

    def test_launch_watches_the_app_in_front(self):
        self.check('launch')

    def test_the_registration_is_the_one_place_that_yields(self):
        source = (ROOT / 'AppController.m').read_text()
        update = method_body(source, '- (void)updatePlainPasteHotKeyRegistration')
        self.assertIn('[self plainPasteHotkeyYieldsToFrontmostApplication:plain]', update)
        self.assertEqual(source.count('plainPasteHotkeyYieldsToFrontmostApplication:'), 3)  # declaration, definition, one call
        main = method_body(source, '- (IBAction)toggleMainHotKey:(id)sender')
        self.assertNotIn('Yields', main)
        launch = method_body(source, '- (void)applicationDidFinishLaunching:(NSNotification *)notification')
        self.assertIn('[self watchFrontmostApplicationMenus];', launch)
        scan = method_body(source, '- (NSDictionary *)scanMenuShortcutsOfProcess:(pid_t)pid')
        self.assertIn('FlycutScanMenuShortcuts(', scan)
        self.assertIn('kFlycutMenuScanBudget', scan)
        self.assertIn('CFRelease(', scan)


if __name__ == '__main__':
    unittest.main()
