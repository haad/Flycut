#!/usr/bin/env python3
"""The menu-bar list while it is open, driven through the real AppController.

- Pausing or resuming capture while the list is open (Option-click on the status item,
  the Pause command, any other call) retitles the list's Pause row at once.
- A clipping that lands while the list is open (a capture already in flight) is listed at
  once; the highlighted entry stays highlighted and the list keeps its scroll position.
  While the bezel shows the favorites, such a copy is listed first in the history, below
  the favorites.
- Press on the status item, drag into the list and release on a row chooses the row, as
  in a native menu; a plain click leaves the list open.
- Quitting (-applicationWillTerminate:) closes the list first, so image files of rows
  deleted in the list are deleted, and then saves the stores.
- A second click on the status item (button action, left or right mouse-down) closes the
  open list, and a press is answered once. The press may close the list on another path
  before the status item's handler sees it: the panel loses key focus
  (-windowDidResignKey:), another application becomes active, or, on macOS 27, the menu bar
  (MenuBarAgent) takes the press, so the list's global mouse-down monitor sees it as
  another application's event, and hands it to Flycut about 50 ms later (modelled as a
  mouse-down stamped then, and as the button's action). Such a press must leave the list
  closed, through the mouse-down monitor and through the button's action; the global
  monitor leaves a press on the status item to the status item. A press that the monitor
  answered does nothing more as the button's action. A press long after the list closed,
  or stamped 0, opens it again; so does a click on the status item after a press
  elsewhere closed the list.
- A click on the status item while the bezel is shown: the list's panel takes key focus
  from the bezel, which closes the bezel. When it showed the favorites, the history is the
  current list again. Flycut is not hidden then, which would close the list again, and
  capture stays frozen until the list closes. Without the list, the bezel losing key focus
  still hides Flycut.

The fixture compiles the real AppController, FlycutOperator, list and engine sources.
Only OS boundaries are replaced: FixtureIsolation.h keeps defaults in memory and gives
an off-screen status item; the list opens off screen (never ordered in); clipboard writes
are recorded; the image store is an in-memory stand-in that records deletions; the
general pasteboard aborts the fixture. The bezel is a stand-in object that records what it
shows and, like AppKit for a key window, tells its delegate when it loses key focus:
ordered out while key, or the list's panel becoming key as the list opens. Hiding Flycut
(-[NSApplication hide:]) is counted, never performed; like AppKit, it takes key focus from
the open list's panel. Mouse events for the press-drag-release case are
NSEvent objects put into this process's own event queue (-[NSApplication
postEvent:atStart:]); nothing is posted to the system. The live modifier state the status
item handler reads (CGEventSourceFlagsState) is redirected to "no key down", so keys held
elsewhere in the session cannot turn a click into Option-click. NSWorkspace's notification
center is a private one, so another application becoming active in the session cannot
close the list (it closes on NSWorkspaceDidActivateApplicationNotification). Activation and window
ordering are counted and never performed. The list's global mouse-down monitor is not
installed in the system: its handler is kept and called with a press in screen coordinates.
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
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutImageStore.h"
#import "FlycutListPanel.h"

static NSMutableArray *gLog;   // "delete:<hash>", "save", "ephemeral"
static int gActivations, gOrderFront;

static id FCForbidden(id object, SEL selector) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: +[%s %s]\n", class_getName(object), sel_getName(selector));
    abort();
}
static void FCCountActivation(id self, SEL _cmd, ...) { gActivations++; }
static BOOL FCCountActivationBOOL(id self, SEL _cmd, ...) { gActivations++; return NO; }
static void FCCountOrderFront(id self, SEL _cmd, ...) { gOrderFront++; }
// Stands in for the BezelWindow: records what it shows. Like AppKit for a key window, it
// tells its delegate (-windowDidResignKey:) when it loses key focus.
@interface FCFakeBezel : NSObject {
@public
    id delegate;
    BOOL key, visible, color;
}
- (void)resignKey;
@end
@implementation FCFakeBezel
- (NSRect)frame { return NSMakeRect(0, 0, 400, 300); }
- (void)setFrame:(NSRect)frame display:(BOOL)display { }
- (void)setCollectionBehavior:(NSWindowCollectionBehavior)behavior { }
- (void)makeKeyAndOrderFront:(id)sender { visible = YES; key = YES; }
- (void)resignKey {
    if (!key) return;
    key = NO;
    [delegate windowDidResignKey:[NSNotification notificationWithName:NSWindowDidResignKeyNotification object:self]];
}
- (void)orderOut:(id)sender { visible = NO; [self resignKey]; }
- (void)setColor:(BOOL)value { color = value; }
- (void)setText:(NSString *)value { }
- (void)setImage:(NSImage *)image { }
- (void)setCharString:(NSString *)value { }
- (void)setSource:(NSString *)value { }
- (void)setDate:(NSString *)value { }
- (void)setSourceIcon:(NSImage *)icon { }
- (void)setAlpha:(float)value { }
- (void)trueCenter { }
@end
static FCFakeBezel *gBezel;

// The status item opens the list below itself on screen; here it opens off screen. The
// real opening then makes the list's panel key, so a key bezel resigns. With gRealOpening
// the real -openBelowRect:onScreen: runs (the panel is placed but never ordered in: window
// ordering is counted), so the list installs its global mouse-down monitor, whose handler
// the fixture keeps and calls as AppKit would for another application's mouse-down.
static FlycutListController *gOpenList;
static BOOL gRealOpening;
static int gRealOpenings;
static IMP gOpenBelowRect;
static void FCOpenOffscreen(id self, SEL _cmd, NSRect anchor, NSScreen *screen) {
    gOpenList = (FlycutListController *)self;
    if (gRealOpening) {
        gRealOpenings++;
        ((void (*)(id, SEL, NSRect, NSScreen *))gOpenBelowRect)(self, _cmd, anchor, screen);
    } else {
        [(FlycutListController *)self openOffscreenWithMaximumListHeight:2000];
    }
    [gBezel resignKey];
}
static void (^gGlobalHandler)(NSEvent *);
static id gGlobalMonitorToken;
static IMP gRemoveMonitor;
static id FCAddGlobalMonitor(id self, SEL _cmd, NSEventMask mask, void (^handler)(NSEvent *)) {
    [gGlobalHandler release];
    gGlobalHandler = [handler copy];
    if (gGlobalMonitorToken == nil) gGlobalMonitorToken = [[NSObject alloc] init];
    return gGlobalMonitorToken;
}
static void FCRemoveMonitor(id self, SEL _cmd, id monitor) {
    if (monitor == gGlobalMonitorToken) { [gGlobalHandler release]; gGlobalHandler = nil; return; }
    ((void (*)(id, SEL, id))gRemoveMonitor)(self, _cmd, monitor);
}

// -[NSApplication hide:] is counted, never performed. Like AppKit, hiding the app takes key
// focus from its key window: the open list's panel resigns, which closes the list.
static int gHides;
static void FCHide(id self, SEL _cmd, id sender) {
    gHides++;
    if ([gOpenList isOpen])
        [gOpenList windowDidResignKey:[NSNotification notificationWithName:NSWindowDidResignKeyNotification object:[gOpenList panel]]];
}

@interface FCMemoryImageStore : NSObject
@end
@implementation FCMemoryImageStore
- (NSData *)imageDataForHash:(NSString *)hash { return nil; }
- (NSString *)imageFilePathForHash:(NSString *)hash { return nil; }
- (BOOL)hasImageForHash:(NSString *)hash { return YES; }
- (void)persistMemoryOnlyImageForHash:(NSString *)hash {}
- (void)deleteImageForHash:(NSString *)hash { [gLog addObject:[@"delete:" stringByAppendingString:hash]]; }
- (void)removeEphemeralFiles { [gLog addObject:@"ephemeral"]; }
- (void)removeAllImages { fprintf(stderr, "fixture removed all images\n"); abort(); }
@end
static FCMemoryImageStore *gImageStore;
static id FCMemorySharedStore(id object, SEL selector) { return gImageStore; }

static NSNotificationCenter *gWorkspaceCenter;
static id FCWorkspaceCenter(id self, SEL _cmd) { return gWorkspaceCenter; }

static IMP gSaveEngine;
static void FCLoggedSaveEngine(id self, SEL _cmd) { [gLog addObject:@"save"]; ((void (*)(id, SEL))gSaveEngine)(self, _cmd); }

static void Swizzle(Class cls, SEL selector, IMP imp) {
    Method m = class_getInstanceMethod(cls, selector);
    if (m == NULL) { fprintf(stderr, "no method %s\n", sel_getName(selector)); abort(); }
    method_setImplementation(m, imp);
}

static void InstallBoundaries(void) {
    gLog = [[NSMutableArray alloc] init];
    gImageStore = [[FCMemoryImageStore alloc] init];
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)), (IMP)FCMemorySharedStore);
    Swizzle([NSApplication class], @selector(activateIgnoringOtherApps:), (IMP)FCCountActivation);
    Swizzle([NSApplication class], sel_registerName("activate"), (IMP)FCCountActivation);
    Swizzle([NSApplication class], @selector(unhide:), (IMP)FCCountActivation);
    Swizzle([NSRunningApplication class], @selector(activateWithOptions:), (IMP)FCCountActivationBOOL);
    Swizzle([NSWindow class], @selector(orderFront:), (IMP)FCCountOrderFront);
    Swizzle([NSWindow class], @selector(makeKeyAndOrderFront:), (IMP)FCCountOrderFront);
    Swizzle([NSWindow class], @selector(orderFrontRegardless), (IMP)FCCountOrderFront);
    gOpenBelowRect = method_getImplementation(class_getInstanceMethod([FlycutListController class], @selector(openBelowRect:onScreen:)));
    Swizzle([FlycutListController class], @selector(openBelowRect:onScreen:), (IMP)FCOpenOffscreen);
    method_setImplementation(class_getClassMethod([NSEvent class], @selector(addGlobalMonitorForEventsMatchingMask:handler:)),
                             (IMP)FCAddGlobalMonitor);
    gRemoveMonitor = method_setImplementation(class_getClassMethod([NSEvent class], @selector(removeMonitor:)), (IMP)FCRemoveMonitor);
    // Applications activating elsewhere in the session must not reach the list.
    gWorkspaceCenter = [[NSNotificationCenter alloc] init];
    Swizzle([NSWorkspace class], @selector(notificationCenter), (IMP)FCWorkspaceCenter);
    Swizzle([NSApplication class], @selector(hide:), (IMP)FCHide);
    Method save = class_getInstanceMethod([FlycutOperator class], @selector(saveEngine));
    gSaveEngine = method_setImplementation(save, (IMP)FCLoggedSaveEngine);
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setObject:@1 forKey:@"savePreference"];          // save on quit only
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@NO forKey:@"menuSelectionPastes"];    // copy only: nothing is pasted anywhere
    [defaults setObject:@20 forKey:@"displayNum"];
}

@interface AppController (MenuListOpenStateTesting)
- (void)setupClipboardTrackingMenuItem;
- (void)handleStatusItemEvent:(NSEvent *)event;
- (IBAction)statusItemButtonPressed:(id)sender;
- (IBAction)toggleClipboardTracking:(id)sender;
- (void)clippingWasAdded;
- (void)hitMainHotKey:(id)hotKey;
- (void)processBezelKeyDown:(NSEvent *)event;
@end

@interface FCStateController : AppController {
    NSMutableArray *_placed;
    FCOffscreenStatusItem *_item;
}
- (void)installOperator:(FlycutOperator *)op;
- (void)installBezel:(FCFakeBezel *)fake;
- (FlycutListController *)list;
- (FCOffscreenStatusItem *)item;
- (NSArray *)placed;
- (BOOL)bezelDisplayed;
- (BOOL)bezelPinned;
- (BOOL)captureFrozen;
@end

@implementation FCStateController
- (void)installOperator:(FlycutOperator *)op {
    flycutOperator = op;
    _placed = [[NSMutableArray alloc] init];
    _item = [[FCOffscreenStatusItem alloc] initWithLength:24];
    statusItem = (NSStatusItem *)_item;
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Menu"];
    NSMenuItem *search = [[[NSMenuItem alloc] initWithTitle:@"Search..." action:NULL keyEquivalent:@"f"] autorelease];
    [menu addItem:search];
    [menu addItem:[NSMenuItem separatorItem]];
    [[menu addItemWithTitle:@"Clear All" action:@selector(clearClippingList:) keyEquivalent:@""] setTarget:self];
    [[menu addItemWithTitle:@"Merge All" action:@selector(mergeClippingList:) keyEquivalent:@""] setTarget:self];
    [[menu addItemWithTitle:@"Preferences\u2026" action:@selector(showPreferencePanel:) keyEquivalent:@","] setTarget:self];
    [menu addItem:[NSMenuItem separatorItem]];
    [[menu addItemWithTitle:@"Quit" action:@selector(terminate:) keyEquivalent:@""] setTarget:nil];
    jcMenu = menu;
    [self setupClipboardTrackingMenuItem];   // inserts Pause before Preferences, as at launch
}
- (void)installBezel:(FCFakeBezel *)fake { bezel = (id)fake; fake->delegate = self; }
- (FlycutListController *)list { return listController; }
- (FCOffscreenStatusItem *)item { return _item; }
- (NSArray *)placed { return _placed; }
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
- (BOOL)bezelPinned { return isBezelPinned; }
- (BOOL)captureFrozen { return isMenuOpen; }
// OS boundary: the frontmost application (read when the bezel opens).
- (NSRunningApplication *)frontmostApplicationForPaste { return nil; }
// OS boundaries: clipboard writes are recorded; the clipboard is never polled.
- (void)addClipToPasteboard:(NSString *)text { [_placed addObject:text]; }
- (void)addClipToPasteboard:(NSString *)text withRichData:(NSDictionary *)richData { [_placed addObject:text]; }
- (BOOL)addImageClipToPasteboard:(FlycutClipping *)clipping { [_placed addObject:[clipping imageHash]]; return YES; }
- (void)pollPB:(NSTimer *)timer {}
@end

static FlycutClipping *Text(NSString *text, NSInteger timestamp) {
    return [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString withDisplayLength:40
                                withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:timestamp] autorelease];
}
static FlycutClipping *Image(NSString *hash, NSInteger timestamp) {
    return [[[FlycutClipping alloc] initWithImageHash:hash withImageSize:NSMakeSize(4, 4) withImageType:NSPasteboardTypePNG
                                    withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil
                                        withTimestamp:timestamp] autorelease];
}

// history: newest first, 40 entries h0..h39 (h3 an image) so the list scrolls.
static FCStateController *Make(FlycutOperator **outOp) {
    FCStateController *controller = [[FCStateController alloc] init];
    FlycutOperator *op = [[FlycutOperator alloc] init];
    [op awakeFromNibDisplaying:20 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
    FlycutStore *history = [op valueForKey:@"clippingStore"];
    [history setRememberNum:99];
    for (int i = 39; i >= 0; i--)
        [history addClipping:i == 3 ? Image(@"img3", 1000 - i) : Text([NSString stringWithFormat:@"h%d", i], 1000 - i)];
    [[op valueForKey:@"favoritesStore"] addClipping:Text(@"f0", 500)];
    [controller installOperator:op];
    *outOp = op;
    return controller;
}

static NSArray *CommandRows(FlycutListController *list) {
    NSMutableArray *rows = [NSMutableArray array];
    NSMutableArray *queue = [NSMutableArray arrayWithObject:[[list panel] contentView]];
    Class rowClass = NSClassFromString(@"FlycutListCommandRow");
    while ([queue count]) {
        NSView *view = [queue objectAtIndex:0];
        [queue removeObjectAtIndex:0];
        if ([view isKindOfClass:rowClass]) [rows addObject:view];
        [queue addObjectsFromArray:[view subviews]];
    }
    return rows;
}
static NSString *RowTitles(FlycutListController *list) {
    NSMutableArray *titles = [NSMutableArray array];
    for (NSView *row in CommandRows(list))
        [titles addObject:[NSString stringWithFormat:@"%@|%@", [[row valueForKey:@"titleField"] stringValue], [row accessibilityLabel]]];
    return [titles componentsJoinedByString:@","];
}
static NSString *Highlighted(FlycutListController *list) {
    NSInteger row = [list highlightedRow];
    NSArray *rows = [[list clipList] rows];
    if (row < 0 || row >= (NSInteger)[rows count]) return @"(none)";
    FlycutClipping *c = [[rows objectAtIndex:row] clipping];
    return [c isImageClipping] ? [c imageHash] : [c contents];
}
static NSPoint ScreenPointOfRow(FlycutListController *list, NSInteger row) {
    NSTableView *table = [list tableView];
    NSRect rect = [table rectOfRow:row];
    NSPoint inWindow = [table convertPoint:NSMakePoint(NSMidX(rect), NSMidY(rect)) toView:nil];
    return [[list panel] convertPointToScreen:inWindow];
}
static NSPoint ScreenPointOfCommand(FlycutListController *list, NSString *title) {
    for (NSView *row in CommandRows(list))
        if ([[[row valueForKey:@"item"] title] isEqualToString:title]) {
            NSPoint inWindow = [row convertPoint:NSMakePoint(NSMidX([row bounds]), NSMidY([row bounds])) toView:nil];
            return [[list panel] convertPointToScreen:inWindow];
        }
    return NSMakePoint(-1, -1);
}
// A mouse event made now, with the time stamp a real one carries (seconds since startup).
static NSEvent *MouseAt(NSEventType type, NSPoint screen, NSEventModifierFlags flags, NSTimeInterval timestamp) {
    return [NSEvent mouseEventWithType:type location:screen modifierFlags:flags
                             timestamp:timestamp windowNumber:0 context:nil
                           eventNumber:0 clickCount:1 pressure:type == NSEventTypeLeftMouseUp ? 0 : 1];
}
static NSEvent *Mouse(NSEventType type, NSPoint screen, NSEventModifierFlags flags) {
    return MouseAt(type, screen, flags, [[NSProcessInfo processInfo] systemUptime]);
}
static NSTimeInterval Now(void) { return [[NSProcessInfo processInfo] systemUptime]; }
// The status item's frame on screen (the off-screen button's).
static NSRect StatusItemFrame(FCStateController *c) {
    NSStatusBarButton *button = [[c item] button];
    return [[button window] convertRectToScreen:[button convertRect:[button bounds] toView:nil]];
}
// AppKit tells the panel's delegate that the panel lost key focus.
static void PanelLosesKeyFocus(FlycutListController *list) {
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowDidResignKeyNotification object:[list panel]];
}
static void Post(NSEvent *event) { [NSApp postEvent:event atStart:NO]; }
static NSEvent *KeyEvent(NSString *characters, unsigned short keyCode) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
                             context:nil characters:characters charactersIgnoringModifiers:characters isARepeat:NO keyCode:keyCode];
}
static void DrainEvents(void) {
    while ([NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES] != nil) {}
}
// A click on the status item; its release lands outside the list (a plain click).
static void ClickStatusItem(FCStateController *c) {
    Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
    [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
    DrainEvents();
}
// The status item handler also reads the live modifier keys (CGEventSourceFlagsState is
// redirected here at compile time): the session's real keyboard, which other software may
// be using, must not decide whether a click pauses. Only the event's own flags count.
CGEventFlags FCTestCGEventSourceFlagsState(CGEventSourceStateID stateID) { return 0; }

static int failures;
static void Expect(BOOL ok, const char *what, NSString *detail) {
    if (ok) { printf("PASS: %s\n", what); return; }
    failures++;
    fprintf(stderr, "FAIL: %s -- %s\n", what, [detail ?: @"" UTF8String]);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        const char *mode = argv[1];
        InstallBoundaries();
        FlycutOperator *op = nil;
        FCStateController *c = Make(&op);

        if (strcmp(mode, "pause-while-open") == 0) {
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            if (![list isOpen]) { fprintf(stderr, "FAIL setup: the list did not open\n"); return 20; }
            Expect([RowTitles(list) containsString:@"Pause Clipboard Tracking|Pause Clipboard Tracking"], "the list opens with the Pause row", RowTitles(list));
            NSEvent *optionClick = Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, NSEventModifierFlagOption);
            [c handleStatusItemEvent:optionClick];
            Expect([op storeDisabled], "Option-click on the status item pauses capture", nil);
            Expect([list isOpen], "and leaves the list open", nil);
            Expect([RowTitles(list) containsString:@"Resume Clipboard Tracking|Resume Clipboard Tracking"],
                   "the open list's row says Resume at once (text and VoiceOver)", RowTitles(list));
            [c toggleClipboardTracking:nil];
            Expect(![op storeDisabled] && [RowTitles(list) containsString:@"Pause Clipboard Tracking|Pause Clipboard Tracking"],
                   "resuming by any other call retitles the row back to Pause", RowTitles(list));
            [c handleStatusItemEvent:optionClick];
            [list close];
            [c statusItemButtonPressed:nil];
            Expect([RowTitles(list) containsString:@"Resume Clipboard Tracking"], "reopened while paused, the row says Resume", RowTitles(list));
            [list close];
        } else if (strcmp(mode, "capture-while-open") == 0) {
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            NSClipView *clip = [[[list tableView] enclosingScrollView] contentView];
            [clip scrollToPoint:NSMakePoint(0, 240)];
            [[[list tableView] enclosingScrollView] reflectScrolledClipView:clip];
            [list setHighlightedRow:20];
            NSString *before = Highlighted(list);
            NSInteger rows = (NSInteger)[[[list clipList] rows] count];
            CGFloat offset = NSMinY([clip bounds]);
            // A capture that was already being read when the list opened lands now.
            [op addClipping:@"arrived while open" ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil
                     target:c clippingAddedSelector:@selector(clippingWasAdded)];
            NSArray *now = [[list clipList] rows];
            BOOL listed = NO;
            for (id row in now) if ([[[row clipping] contents] isEqual:@"arrived while open"]) listed = YES;
            Expect(listed && (NSInteger)[now count] == rows + 1 && (NSInteger)[[list tableView] numberOfRows] == rows + 1,
                   "the clipping is listed at once", [NSString stringWithFormat:@"%lu rows", (unsigned long)[now count]]);
            Expect([Highlighted(list) isEqual:before] && [list highlightedRow] == 21, "the highlight stays on the same clipping",
                   [NSString stringWithFormat:@"%@ at %ld (was %@)", Highlighted(list), (long)[list highlightedRow], before]);
            Expect(NSMinY([clip bounds]) == offset, "the list keeps its scroll position",
                   [NSString stringWithFormat:@"%g (was %g)", NSMinY([clip bounds]), offset]);
            Expect([list isOpen], "the list stays open", nil);
            [list close];
        } else if (strcmp(mode, "capture-while-bezel-shows-favorites") == 0) {
            // The bezel's "f" key swaps the favorites in as the current store
            // (-toggleToFromFavoritesStore). A copy still goes into the history then, so
            // the list shows it first in the history, below the favorites, not among them.
            NSArray *favorites = [op clippingsInList:FlycutListFavorites matching:nil];
            [op toggleToFromFavoritesStore];
            if (![op favoritesStoreIsSelected]) { fprintf(stderr, "FAIL setup: the favorites are not shown\n"); return 22; }
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            [op addClipping:@"copied while favorites are shown" ofType:NSPasteboardTypeString fromApp:@"Fixture"
                withAppBundleURL:nil target:c clippingAddedSelector:@selector(clippingWasAdded)];
            FlycutClipListRow *firstHistory = nil, *listed = nil;
            for (FlycutClipListRow *row in [[list clipList] rows]) {
                if (firstHistory == nil && [row list] == FlycutListHistory) firstHistory = row;
                if ([[[row clipping] contents] isEqual:@"copied while favorites are shown"]) listed = row;
            }
            Expect(listed != nil && listed == firstHistory, "the copy is listed at once, first in the history",
                   [NSString stringWithFormat:@"%@ in list %ld", [[listed clipping] contents], (long)[listed list]]);
            Expect([[op clippingsInList:FlycutListFavorites matching:nil] isEqualToArray:favorites],
                   "the favorites are unchanged", [[op clippingsInList:FlycutListFavorites matching:nil] description]);
            Expect([op favoritesStoreIsSelected], "the bezel still shows the favorites", nil);
            [list close];
            [op toggleToFromFavoritesStore];
            Expect([[[op clippingAtPosition:0] contents] isEqual:@"copied while favorites are shown"],
                   "back on the history, the copy is its newest clipping", [[op clippingAtPosition:0] contents]);
        } else if (strcmp(mode, "press-drag-release") == 0) {
            // Where the rows are: the list opens at the same off-screen place each time.
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            NSInteger row = 8;
            FlycutClipping *expected = [[[[list clipList] rows] objectAtIndex:row] clipping];
            NSPoint over = ScreenPointOfRow(list, row), over2 = ScreenPointOfRow(list, row + 1);
            [list close];
            Post(Mouse(NSEventTypeLeftMouseDragged, over2, 0));
            Post(Mouse(NSEventTypeLeftMouseDragged, over, 0));
            Post(Mouse(NSEventTypeLeftMouseUp, over, 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            Expect(![list isOpen], "releasing on a row after a press on the status item closes the list", nil);
            Expect([[c placed] isEqual:@[[expected contents]]], "and copies the row under the pointer",
                   [[c placed] description]);
            DrainEvents();
            // A plain click: the release lands on the status item (outside the list), the list stays open.
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            Expect([list isOpen] && [[c placed] count] == 1, "a click on the status item leaves the list open, nothing chosen", nil);
            NSPoint pause = ScreenPointOfCommand(list, @"Pause Clipboard Tracking");
            [list close];
            DrainEvents();
            // Releasing on a command row runs it (Pause), like a menu item.
            Post(Mouse(NSEventTypeLeftMouseDragged, pause, 0));
            Post(Mouse(NSEventTypeLeftMouseUp, pause, 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            Expect(![list isOpen] && [op storeDisabled], "releasing on a command row runs the command", nil);
            DrainEvents();
        } else if (strcmp(mode, "second-click-closes") == 0) {
            // A second click on the status item closes the open list, as with a menu: by
            // the button's action (keyboard, VoiceOver) and by a mouse-down on the item.
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            Expect([list isOpen], "the button's action opens the list", nil);
            [c statusItemButtonPressed:nil];
            Expect(![list isOpen], "the button's action again closes it", nil);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));   // the first click's release
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            Expect([list isOpen], "a click on the status item opens the list", nil);
            DrainEvents();
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            Expect(![list isOpen], "a second click closes it", nil);
            DrainEvents();
            Post(Mouse(NSEventTypeRightMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeRightMouseDown, NSZeroPoint, 0)];
            Expect([list isOpen], "a right click opens it", nil);
            DrainEvents();
            [c handleStatusItemEvent:Mouse(NSEventTypeRightMouseDown, NSZeroPoint, 0)];
            Expect(![list isOpen] && [[c placed] count] == 0, "a second right click closes it, nothing chosen", nil);
            DrainEvents();
        } else if (strcmp(mode, "second-click-after-focus-loss") == 0) {
            // The order on screen: the press on the status item takes key focus from the
            // list's panel, AppKit sends it -windowDidResignKey: (the list closes), and
            // then the press reaches the status item's mouse-down monitor. The press found
            // the list open, so it is the second click: the list stays closed.
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));   // the first click's release
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            FlycutListController *list = [c list];
            Expect([list isOpen], "a click on the status item opens the list", nil);
            DrainEvents();
            NSEvent *press = Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));   // its release, on the status item
            PanelLosesKeyFocus(list);
            [c handleStatusItemEvent:press];
            DrainEvents();
            Expect(![list isOpen] && ![c captureFrozen],
                   "a second click whose press first takes key focus from the list leaves it closed", nil);
            // The same when another application becoming active closes the list as the press arrives.
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            DrainEvents();
            Expect([list isOpen], "a later click opens it again", nil);
            press = Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [gWorkspaceCenter postNotificationName:NSWorkspaceDidActivateApplicationNotification object:nil];
            [c handleStatusItemEvent:press];
            DrainEvents();
            Expect(![list isOpen], "a second click that another app's activation closed first leaves it closed", nil);
            // The right button.
            Post(Mouse(NSEventTypeRightMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeRightMouseDown, NSZeroPoint, 0)];
            DrainEvents();
            press = Mouse(NSEventTypeRightMouseDown, NSZeroPoint, 0);
            Post(Mouse(NSEventTypeRightMouseUp, NSMakePoint(-20000, -20000), 0));
            PanelLosesKeyFocus(list);
            [c handleStatusItemEvent:press];
            DrainEvents();
            Expect(![list isOpen] && [[c placed] count] == 0, "the same with the right button, nothing chosen", nil);
            // A press long after the list closed (a click elsewhere a second earlier) opens it.
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            DrainEvents();
            PanelLosesKeyFocus(list);
            if ([list isOpen]) { fprintf(stderr, "FAIL setup: losing key focus did not close the list\n"); return 25; }
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, Now() + 1.0)];
            DrainEvents();
            Expect([list isOpen], "a press after the list closed earlier opens it", nil);
            // A press stamped 0 (an event a test driver made without a time stamp) is not
            // the press that closed the list a moment ago: it opens the list (review 10, O1).
            PanelLosesKeyFocus(list);
            if ([list isOpen]) { fprintf(stderr, "FAIL setup: losing key focus did not close the list\n"); return 27; }
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, 0)];
            DrainEvents();
            Expect([list isOpen], "a press with time stamp 0 after the list closed opens it", nil);
            [list close];
        } else if (strcmp(mode, "second-click-handed-over-by-the-menu-bar") == 0) {
            // macOS 27 hosts status items in the menu bar's process (MenuBarAgent): it takes
            // the press, so the list's global mouse-down monitor sees it as another
            // application's event, and it hands the press to Flycut about 50 ms later (system
            // log of the build-9 sight test: the list closed, the menu bar's navigate action
            // came 50 ms later, the list opened again 62 ms after the close). Modelled here as
            // a mouse-down stamped then; the action path is the next mode. The list opens for
            // real here (placed, never ordered in), so its global monitor is installed; its
            // handler is called as AppKit calls it, with a press in screen coordinates.
            gRealOpening = YES;
            ClickStatusItem(c);
            FlycutListController *list = [c list];
            if (![list isOpen] || gGlobalHandler == nil) { fprintf(stderr, "FAIL setup: the list did not open with its global monitor\n"); return 26; }
            NSRect item = StatusItemFrame(c);
            NSTimeInterval pressed = Now();
            gGlobalHandler(MouseAt(NSEventTypeLeftMouseDown, NSMakePoint(NSMidX(item), NSMidY(item)), 0, pressed));
            Expect([list isOpen], "the global monitor leaves a press on the status item to the status item", nil);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, pressed + 0.05)];
            DrainEvents();
            Expect(![list isOpen], "the press the menu bar hands over 50 ms later closes the list, which stays closed", nil);
            // As in the system log, Flycut's panel also loses key focus; handed over 50 ms
            // after that close, the press leaves the list closed.
            ClickStatusItem(c);
            if (![list isOpen] || gGlobalHandler == nil) { fprintf(stderr, "FAIL setup: the list did not open for the key focus case\n"); return 34; }
            gGlobalHandler(MouseAt(NSEventTypeLeftMouseDown, NSMakePoint(NSMidX(item), NSMidY(item)), 0, Now()));
            PanelLosesKeyFocus(list);
            if ([list isOpen]) { fprintf(stderr, "FAIL setup: losing key focus did not close the list\n"); return 35; }
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, Now() + 0.05)];
            DrainEvents();
            Expect(![list isOpen] && ![c captureFrozen],
                   "a press that took key focus from the list on its way through the menu bar leaves it closed", nil);
            // A press the global monitor took for one beside the status item (the menu bar's
            // hit area is its own) closes the list; handed over, it must not open it again.
            ClickStatusItem(c);
            if (![list isOpen] || gGlobalHandler == nil) { fprintf(stderr, "FAIL setup: the list did not open again\n"); return 28; }
            pressed = Now();
            gGlobalHandler(MouseAt(NSEventTypeLeftMouseDown, NSMakePoint(NSMaxX(item) + 3, NSMidY(item)), 0, pressed));
            Expect(![list isOpen], "a press in the menu bar beside the status item closes the list", nil);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, pressed + 0.05)];
            DrainEvents();
            Expect(![list isOpen], "handed to the status item, that press does not open the list again", nil);
            // A press elsewhere (another application's window) closes the list; a click on
            // the status item after it opens the list again.
            ClickStatusItem(c);
            if (![list isOpen] || gGlobalHandler == nil) { fprintf(stderr, "FAIL setup: the list did not open a third time\n"); return 29; }
            pressed = Now();
            gGlobalHandler(MouseAt(NSEventTypeLeftMouseDown, NSMakePoint(NSMidX(item), NSMinY(item) - 300), 0, pressed));
            Expect(![list isOpen], "a press elsewhere closes the list", nil);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:MouseAt(NSEventTypeLeftMouseDown, NSZeroPoint, 0, pressed + 0.05)];
            DrainEvents();
            Expect([list isOpen], "a click on the status item after a press elsewhere opens the list", nil);
            [list close];
            Expect(gGlobalHandler == nil, "closing removes the global monitor", nil);
        } else if (strcmp(mode, "second-click-through-the-action") == 0) {
            // The button's action is the path a press takes when the mouse-down monitor does
            // not see it (and the path of VoiceOver's press). One press is answered once: a
            // press that closed the list on one path must not open it on the other.
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            if (![list isOpen]) { fprintf(stderr, "FAIL setup: the action did not open the list\n"); return 30; }
            PanelLosesKeyFocus(list);
            [c statusItemButtonPressed:nil];
            Expect(![list isOpen], "a press that first took key focus from the list leaves it closed as the button's action", nil);
            [c statusItemButtonPressed:nil];
            Expect([list isOpen], "the next press opens it", nil);
            [gWorkspaceCenter postNotificationName:NSWorkspaceDidActivateApplicationNotification object:nil];
            [c statusItemButtonPressed:nil];
            Expect(![list isOpen], "the same when another app's activation closed it first", nil);
            // The press the mouse-down monitor answered, arriving again as the button's action
            // (in the same dispatch of that mouse-down, before anything else runs).
            [c statusItemButtonPressed:nil];
            if (![list isOpen]) { fprintf(stderr, "FAIL setup: the action did not open the list again\n"); return 31; }
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            if ([list isOpen]) { fprintf(stderr, "FAIL setup: the second click did not close the list\n"); return 32; }
            [c statusItemButtonPressed:nil];
            DrainEvents();
            Expect(![list isOpen], "a press the monitor answered by closing the list does not open it as the action", nil);
            Post(Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000), 0));
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];
            if (![list isOpen]) { fprintf(stderr, "FAIL setup: the click did not open the list\n"); return 33; }
            [c statusItemButtonPressed:nil];
            DrainEvents();
            Expect([list isOpen], "a press the monitor answered by opening the list does not close it as the action", nil);
            // A moment later the action is a press of its own again.
            [NSThread sleepForTimeInterval:0.6];
            [c statusItemButtonPressed:nil];
            Expect(![list isOpen], "a moment later the action closes the list", nil);
        } else if (strcmp(mode, "list-opens-while-pinned-bezel-shows-favorites") == 0) {
            // The bezel pinned on the favorites (hotkey, "f", Space), then a click on the
            // status item: the list's panel takes key focus, the bezel resigns and closes
            // (-windowDidResignKey: -> -hideApp), and its Favorites view ends with it.
            FCFakeBezel *fake = [[FCFakeBezel alloc] init];
            gBezel = fake;
            [c installBezel:fake];
            NSArray *favorites = [op clippingsInList:FlycutListFavorites matching:nil];
            [c hitMainHotKey:nil];
            [c processBezelKeyDown:KeyEvent(@"f", 3)];
            [c processBezelKeyDown:KeyEvent(@" ", 49)];
            if (![op favoritesStoreIsSelected] || ![c bezelDisplayed] || ![c bezelPinned] || !fake->key || !fake->color) {
                fprintf(stderr, "FAIL setup: the bezel is not pinned on the favorites\n"); return 23;
            }
            ClickStatusItem(c);
            FlycutListController *list = [c list];
            Expect(![c bezelDisplayed] && !fake->visible, "the bezel closes when the list takes key focus", nil);
            Expect(![op favoritesStoreIsSelected], "its Favorites view ends: the history is the current list again", nil);
            Expect(!fake->color, "the bezel no longer has the favorites colour", nil);
            Expect([[op clippingsInList:FlycutListFavorites matching:nil] isEqualToArray:favorites], "the favorites are unchanged",
                   [[op clippingsInList:FlycutListFavorites matching:nil] description]);
            if ([list isOpen]) [list close];
            [op addClipping:@"copied after the list" ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil
                     target:c clippingAddedSelector:@selector(clippingWasAdded)];
            Expect([[[op clippingAtPosition:0] contents] isEqual:@"copied after the list"] &&
                   [[[[op clippingsInList:FlycutListHistory matching:nil] firstObject] contents] isEqual:@"copied after the list"],
                   "a later copy is the current list's newest clipping, in the history", [[op clippingAtPosition:0] contents]);
            [c hitMainHotKey:nil];
            Expect(![op favoritesStoreIsSelected] && !fake->color, "the next hotkey opens the bezel on the history", nil);
            [c processBezelKeyDown:KeyEvent(@"", 53)];          // Escape
        } else if (strcmp(mode, "list-opened-over-the-bezel-stays-open") == 0) {
            FCFakeBezel *fake = [[FCFakeBezel alloc] init];
            gBezel = fake;
            [c installBezel:fake];
            // Control: the pinned bezel losing key focus to another application's window
            // closes it and hides Flycut, as on master.
            [c hitMainHotKey:nil];
            [c processBezelKeyDown:KeyEvent(@" ", 49)];
            [fake resignKey];
            Expect(![c bezelDisplayed] && gHides == 1, "control: the bezel losing key focus elsewhere hides Flycut",
                   [NSString stringWithFormat:@"%d hides", gHides]);
            // A click on the status item while the pinned bezel is shown.
            [c hitMainHotKey:nil];
            [c processBezelKeyDown:KeyEvent(@" ", 49)];
            if (![c bezelDisplayed] || ![c bezelPinned] || !fake->key) { fprintf(stderr, "FAIL setup: the bezel is not pinned\n"); return 24; }
            ClickStatusItem(c);
            FlycutListController *list = [c list];
            Expect(![c bezelDisplayed] && !fake->visible, "the bezel closes when the list takes key focus", nil);
            Expect([list isOpen], "the list stays open", nil);
            Expect(gHides == 1, "Flycut is not hidden while the list is open", [NSString stringWithFormat:@"%d hides", gHides]);
            Expect([c captureFrozen], "capture stays frozen while the list is open", nil);
            [c handleStatusItemEvent:Mouse(NSEventTypeLeftMouseDown, NSZeroPoint, 0)];   // a second click
            DrainEvents();
            Expect(![list isOpen] && ![c captureFrozen], "a second click closes the list and ends the freeze", nil);
        } else if (strcmp(mode, "quit-flushes-and-saves") == 0) {
            [c statusItemButtonPressed:nil];
            FlycutListController *list = [c list];
            FlycutClipping *image = [[op clippingsInList:FlycutListHistory matching:nil] objectAtIndex:3];
            if (![image isImageClipping] || ![[list clipList] deleteClipping:image]) { fprintf(stderr, "FAIL setup: no image row deleted\n"); return 21; }
            Expect([gLog count] == 0, "the image file is kept while the list is open", [gLog description]);
            [c applicationWillTerminate:nil];
            Expect(![list isOpen], "quitting closes the list", nil);
            Expect([gLog containsObject:@"delete:img3"], "quitting deletes the image of the row deleted in the list", [gLog description]);
            NSUInteger deleted = [gLog indexOfObject:@"delete:img3"], saved = [gLog indexOfObject:@"save"];
            Expect(saved != NSNotFound && deleted < saved, "the image goes before the stores are saved", [gLog description]);
            NSArray *jcList = [[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"store"] objectForKey:@"jcList"];
            Expect([jcList count] == 39, "the saved history lacks the deleted row and keeps the others",
                   [NSString stringWithFormat:@"%lu", (unsigned long)[jcList count]]);
        } else {
            return 3;
        }
        Expect(gActivations == 0, "Flycut never activated", [NSString stringWithFormat:@"%d", gActivations]);
        // The real openings (gRealOpening) ask for key and front once each; it is counted, never performed.
        Expect(gOrderFront == gRealOpenings && ![[[c list] panel] isVisible], "no window was ordered on screen",
               [NSString stringWithFormat:@"%d (real openings %d)", gOrderFront, gRealOpenings]);
        printf("%s: %s\n", mode, failures ? "FAIL" : "PASS");
        return failures ? 10 : 0;
    }
}
'''

MODES = {
    "pause-while-open": "pausing or resuming while the list is open must retitle its Pause row at once",
    "capture-while-open": "a clipping landing while the list is open must be listed, keeping highlight and scroll position",
    "capture-while-bezel-shows-favorites": "a copy made while the bezel shows the favorites must be listed in the history",
    "press-drag-release": "press on the status item, drag and release on a row must choose it like a menu",
    "quit-flushes-and-saves": "quitting must close the list (deleting its deferred images) and then save",
    "second-click-closes": "a second click on the status item must close the open list",
    "second-click-after-focus-loss":
        "a second click whose press closed the list first (focus loss, app switch) must leave it closed",
    "second-click-handed-over-by-the-menu-bar":
        "a press the menu bar hands over after the list's global monitor saw it must close the list and keep it closed",
    "second-click-through-the-action":
        "a press that closed the list on one path must not open it as the button's action (one press, one answer)",
    "list-opens-while-pinned-bezel-shows-favorites":
        "the list opening while a pinned bezel shows the favorites must end the Favorites view",
    "list-opened-over-the-bezel-stays-open":
        "a status-item click while the bezel is shown must leave the list open, Flycut not hidden",
}


def fixture_sources() -> list[pathlib.Path]:
    try:
        listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True,
                                         stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError):
        listed = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.m")]
    return [ROOT / path for path in sorted(listed)
            if path != "main.m" and not path.startswith("FlycutHelper/") and not path.startswith("Tests/")]


class MenuListOpenStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-menu-list-open-state-")
        cls.addClassCleanup(cls.directory.cleanup)
        temp = pathlib.Path(cls.directory.name)
        source = temp / "MenuListOpenStateFixture.m"
        cls.binary = temp / "MenuListOpenStateFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-DCGEventSourceFlagsState=FCTestCGEventSourceFlagsState",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include_dir in sorted({ROOT, ROOT / "Tests" / "Fixtures", *(path.parent for path in sources)}):
            command.extend(["-I", str(include_dir)])
        command.extend(str(path) for path in sources)
        command.append(str(source))
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command.extend(["-framework", framework])
        command.extend(["-o", str(cls.binary)])
        cls.build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)

    def run_mode(self, mode: str) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-4000:])
        run = subprocess.run([str(self.binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, f"{MODES[mode]}; exit={run.returncode}\n{run.stdout}{run.stderr}")

    def test_pause_changes_while_open_retitle_the_pause_row(self) -> None:
        self.run_mode("pause-while-open")

    def test_clipping_landing_while_open_is_listed_keeping_highlight_and_scroll(self) -> None:
        self.run_mode("capture-while-open")

    def test_copy_while_the_bezel_shows_favorites_is_listed_in_the_history(self) -> None:
        self.run_mode("capture-while-bezel-shows-favorites")

    def test_press_drag_release_from_the_status_item_chooses_the_row(self) -> None:
        self.run_mode("press-drag-release")

    def test_quit_closes_the_list_deletes_its_images_and_saves(self) -> None:
        self.run_mode("quit-flushes-and-saves")

    def test_second_click_on_the_status_item_closes_the_list(self) -> None:
        # Not verifiable on screen in the first live run (synthetic clicks stopped reaching
        # status items), so it is driven here through the real handlers.
        self.run_mode("second-click-closes")

    def test_second_click_that_first_takes_key_focus_leaves_the_list_closed(self) -> None:
        # The user's sight test of build 8: a real second click reopened the list.
        self.run_mode("second-click-after-focus-loss")

    def test_second_click_handed_over_by_the_menu_bar_leaves_the_list_closed(self) -> None:
        # The user's sight test of build 9 (macOS 27): the list closed at the second click
        # and opened again at once; the system log shows the menu bar taking the press.
        self.run_mode("second-click-handed-over-by-the-menu-bar")

    def test_one_press_on_the_monitor_and_the_action_is_answered_once(self) -> None:
        self.run_mode("second-click-through-the-action")

    def test_list_opening_while_the_pinned_bezel_shows_favorites_restores_the_history(self) -> None:
        self.run_mode("list-opens-while-pinned-bezel-shows-favorites")

    def test_status_item_click_while_the_bezel_is_shown_keeps_the_list_open(self) -> None:
        self.run_mode("list-opened-over-the-bezel-stays-open")


if __name__ == "__main__":
    unittest.main(verbosity=2)
