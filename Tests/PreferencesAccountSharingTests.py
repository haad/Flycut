#!/usr/bin/env python3
"""The General pane's "Other accounts on this Mac:" section (account sharing).

The section is built in code (no XIB change): a section label like "Saving:", one
checkbox like "Remove duplicates" and below it a line with the column headers "Send"
and "Receive" and one line per other login account of this Mac: its name, indented
like the sub-options under "Passwords:", and two checkboxes without a title in the
two columns, each centred under its header; "Receive" ends where the fields above end
(the text fields, folder buttons and number field beside the Restore Default arrows).
The section sits below the Saving section and above the "Check Accessibility
Permissions" row. The fixture loads the
production NIB (master's compiled MainMenu.nib for trees that carry only
MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py) and sends the builders
that -awakeFromNib sends; a baseline run sends them without the new builder, so the
geometry can be compared: every NIB control keeps its distance from the top, the
pane grows by exactly the section, the gap above the permissions row stays, the
other panes keep their height. Also checked: fonts and left edges taken from the
neighbours, the titles fit, the binding, the actions, the tooltips, the VoiceOver
labels (control and cell: "Send to <name>", "Receive from <name>"), the key-view
order, the checkboxes' state (the two stored lists, disabled and the names greyed
while sharing is off), that clicking them stores each list by GeneratedUID, that a
click that cannot be stored is undone in both columns, and that the window follows
the taller pane when UKPrefsPanel has already sized it.

Where the section ends up once the window shows: with 0, 1, 2, 3 or 6 other accounts,
in both orders the NIB loader may wake AppController and UKPrefsPanel in, and with
the three numbers changed so that their Restore Default arrows show (as on a Mac in
use), the real -showPreferencePanel: (width fit, focus code), every other pane and
back, and closing and reopening: the label stays 16 pt below the Saving section, the
section above the permissions row, all of it inside the window and the General box.
The arrows are laid out by constraints; the fixture reads factory values back through
a registration-domain shim, without which every arrow stays hidden.

The account list is the fixture's (dummy names "Account A", "Account B" and this
account as "Account Self", which must not be listed); the real accounts are never
read. Defaults stay in memory; the window is never shown.

With the tree's MainMenu.xib laid onto that NIB (Tests/Fixtures/GeneralPaneXib.py) the
section follows the XIB's spacing: 16 pt below the Saving section, the checkbox 8 pt
below the label, the lines of the list (headers, accounts) 6 pt apart, and the
permissions row 16 pt below the section.

The note line under the list ("Sharing is unavailable: ...") takes room only while it
shows: hidden, the permissions row is 16 pt below the last line of the list; shown
(a stand-in service reports an inbox error while the window is open), the note sits
one row gap below that line, the pane is taller by the note's line, the permissions
row 16 pt below the note; hidden again, the pane is as before.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase, ROOT  # noqa: E402
import GeneralPaneXib  # noqa: E402

TITLE = "Share copied text with these accounts:"
TOOLTIP = ("Text you copy goes to the accounts checked under Send; text copied in the accounts checked under Receive "
           "comes here. Each of those accounts must turn this on too: to send to one, check Send here and Receive for "
           "this account there; to receive from one, check Receive here and Send for this account there. "
           "Passwords Flycut recognizes and copies marked as private or temporary are never shared.")
# A dummy account name longer than the name column.
LONG_NAME = "Example Account With A Rather Long Full Name That Goes On And On"
NONE = "No other accounts on this Mac"
STEPS = ["opened", "back from Hotkeys", "back from Appearance", "back from Acknowledgements", "reopened"]
UNREAD = "The accounts on this Mac cannot be read right now"
READ_STEPS = ["reopened", "read, back from Hotkeys", "read, reopened"]
NOTE_STEPS = ["note shown", "note shown, back from Hotkeys", "note hidden again"]


def send_tooltip(name: str) -> str:
    return f"Send copied text to {name}. It gets there once {name} turns sharing on too and checks Receive for this account."


def receive_tooltip(name: str) -> str:
    return (f"Receive copied text from {name}. It comes here once {name} turns sharing on too "
            f"and checks Send for this account.")


SEND_KEY = "shareClippingsSendAccountIDs"
RECEIVE_KEY = "shareClippingsReceiveAccountIDs"


FIXTURE = r'''
static NSView *FindByTitle(NSView *pane, NSString *title, Class kind)
{
    for (NSView *v in [pane subviews]) {
        NSString *t = [v isKindOfClass:[NSButton class]] ? [(NSButton *)v title]
                    : ([v isKindOfClass:[NSTextField class]] ? [(NSTextField *)v stringValue] : nil);
        if ([v isKindOfClass:kind] && [t isEqualToString:title]) return v;
    }
    return nil;
}

static NSView *FindByIdentifier(NSView *pane, NSString *identifier)
{
    for (NSView *v in [pane subviews]) if ([[v identifier] isEqualToString:identifier]) return v;
    return nil;
}

static NSArray *Views(NSView *pane, NSString *identifier)
{
    NSMutableArray *views = [NSMutableArray array];
    for (NSView *v in [pane subviews]) if ([[v identifier] isEqualToString:identifier]) [views addObject:v];
    [views sortUsingComparator:^NSComparisonResult(NSView *a, NSView *b) {
        return NSMinY([a frame]) > NSMinY([b frame]) ? NSOrderedAscending : (NSMinY([a frame]) < NSMinY([b frame]) ? NSOrderedDescending
               : NSOrderedSame);
    }];
    return views;
}

// The account lines: the names (labels), top down.
static NSArray *AccountRows(NSView *pane) { return Views(pane, @"accountSharingAccountName"); }
static NSArray *SendBoxes(NSView *pane) { return Views(pane, @"accountSharingSend"); }
static NSArray *ReceiveBoxes(NSView *pane) { return Views(pane, @"accountSharingReceive"); }

static NSView *BoundTo(NSView *pane, NSString *keyPath)
{
    for (NSView *v in [pane subviews]) if ([BoundKeyPath(v) isEqualToString:keyPath]) return v;
    return nil;
}

static NSDictionary *FrameOf(NSRect r)
{
    return @{@"x": @(NSMinX(r)), @"y": @(NSMinY(r)), @"w": @(NSWidth(r)), @"h": @(NSHeight(r))};
}

static void ShareOn(void) { [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"shareClippingsAcrossAccounts"]; }

// Stands in for the account-share service: running, with an inbox error code.
@interface FCStubShareService : NSObject {
@public
    NSInteger code;
}
@end
@implementation FCStubShareService
- (BOOL)running { return YES; }
- (NSInteger)inboxErrorCode { return code; }
@end

// While gLookupFails is YES the account lookup fails: +localLoginAccounts answers nil,
// as when the directory query fails; otherwise it lists FixtureLoginAccounts.
static BOOL gLookupFails = NO;
static NSArray *SwitchableLookup(id self, SEL cmd) { (void)self; (void)cmd; return gLookupFails ? nil : (FixtureLoginAccounts ?: @[]); }
static void (*gThenBeforeBuilders)(void);
static void InstallSwitchableLookup(void)
{
    method_setImplementation(class_getClassMethod(NSClassFromString(@"FlycutAccountShareService"), NSSelectorFromString(@"localLoginAccounts")),
                             (IMP)SwitchableLookup);
    if (gThenBeforeBuilders) gThenBeforeBuilders();
}

static void FitGeneralFirst(void)
{
    // UKPrefsPanel's own -awakeFromNib ran before AppController's: toolbar made, General shown and fitted.
    [prefs mapTabsToToolbar];
    NSInteger general = [[prefs tabView] indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"];
    NSButton *sender = [[[NSButton alloc] init] autorelease];
    [sender setTag:general];
    [prefs changePanes:sender];
}

// A stored list (GeneratedUIDs) as the fixture accounts' UIDs.
static NSArray *ChosenIn(NSString *key)
{
    NSMutableArray *uids = [NSMutableArray array];
    for (NSString *guid in [[NSUserDefaults standardUserDefaults] objectForKey:key] ?: @[])
        for (NSDictionary *account in FixtureLoginAccounts)
            if ([account[@"guid"] isEqualToString:guid]) [uids addObject:account[@"uid"]];
    return [uids sortedArrayUsingSelector:@selector(compare:)];
}

// The two stored lists as they are (GeneratedUIDs).
static NSDictionary *StoredLists(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    return @{@"send": [defaults objectForKey:@"shareClippingsSendAccountIDs"] ?: [NSNull null],
             @"receive": [defaults objectForKey:@"shareClippingsReceiveAccountIDs"] ?: [NSNull null]};
}

static NSDictionary *Chosen(void)
{
    return @{@"send": ChosenIn(@"shareClippingsSendAccountIDs"), @"receive": ChosenIn(@"shareClippingsReceiveAccountIDs")};
}

// The text colour of a label: the pane's label colour, the disabled one, or something else.
static NSString *ColorName(NSTextField *field)
{
    NSColor *color = [field textColor];
    if ([color isEqual:[[controller valueForKey:@"savingSectionLabel"] textColor]]) return @"label";
    if ([color isEqual:[NSColor disabledControlTextColor]]) return @"disabled";
    return [color description] ?: @"none";
}

static NSDictionary *BoxReport(NSButton *box, NSButton *reference)
{
    NSRect a = [box alignmentRectForFrame:[box frame]];
    return @{@"title": [box title], @"frame": FrameOf([box frame]), @"midX": @(NSMidX(a)), @"state": @([box state]),
             @"enabled": @([box isEnabled]), @"tag": @([box tag]), @"axControl": [box accessibilityLabel] ?: @"",
             @"axCell": [[box cell] accessibilityLabel] ?: @"", @"tooltip": [box toolTip] ?: @"",
             @"action": NSStringFromSelector([box action]) ?: @"", @"targetIsController": @([box target] == controller),
             @"fontSame": @([[box font] isEqual:[reference font]]),
             @"fits": @([box intrinsicContentSize].width <= NSWidth([box frame]) + 0.5)};
}

static NSDictionary *LabelReport(NSTextField *label, NSButton *reference)
{
    NSRect a = [label alignmentRectForFrame:[label frame]];
    return @{@"text": [label stringValue], @"frame": FrameOf([label frame]), @"align": FrameOf(a), @"midX": @(NSMidX(a)),
             @"tag": @([label tag]), @"color": ColorName(label), @"fontSame": @([[label font] isEqual:[reference font]]),
             @"tooltip": [label toolTip] ?: @"", @"lineBreak": @([label lineBreakMode]),
             @"axValue": [[label accessibilityValue] description] ?: @"",
             @"intrinsicW": @([label intrinsicContentSize].width),
             // A label draws its text inside its alignment rect (2 pt in from each side).
             // The text must fit there, not only the intrinsic width in the frame: a
             // left-aligned label's intrinsic width leaves those 2 pt out, so a label made
             // exactly that wide cuts off the end of its text.
             @"textW": @([[label stringValue] sizeWithAttributes:@{NSFontAttributeName: [label font]}].width),
             @"fits": @([label intrinsicContentSize].width <= NSWidth([label frame]) + 0.5
                        && [[label stringValue] sizeWithAttributes:@{NSFontAttributeName: [label font]}].width <= NSWidth(a) + 0.5)};
}

static NSDictionary *RowReport(NSView *pane, NSUInteger i, NSButton *reference)
{
    return @{@"title": [AccountRows(pane)[i] stringValue], @"name": LabelReport(AccountRows(pane)[i], reference),
             @"send": BoxReport(SendBoxes(pane)[i], reference), @"receive": BoxReport(ReceiveBoxes(pane)[i], reference)};
}

// Where General's Restore Default arrows end as drawn: each arrow is shown and enabled for
// a moment and cached on its own (offscreen, twice the resolution); the rightmost column with
// ink (alpha above 0.1) counts, in the pane's coordinates.
static CGFloat ArrowInkRight(NSView *pane)
{
    CGFloat right = 0;
    for (NSView *v in [pane subviews]) {
        if (![v isKindOfClass:[NSButton class]] || ![[v identifier] hasPrefix:@"restoreDefault"]) continue;
        NSButton *arrow = (NSButton *)v;
        BOOL hidden = [arrow isHidden], enabled = [arrow isEnabled];
        [arrow setHidden:NO];
        [arrow setEnabled:YES];
        NSRect b = [arrow bounds];
        NSBitmapImageRep *rep = [[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:(NSInteger)(NSWidth(b) * 2)
            pixelsHigh:(NSInteger)(NSHeight(b) * 2) bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO
            colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0] autorelease];
        [rep setSize:b.size];
        [arrow cacheDisplayInRect:b toBitmapImageRep:rep];
        [arrow setEnabled:enabled];
        [arrow setHidden:hidden];
        NSInteger inked = -1;
        for (NSInteger x = [rep pixelsWide] - 1; x >= 0 && inked < 0; x--)
            for (NSInteger y = 0; y < [rep pixelsHigh] && inked < 0; y++)
                if ([[rep colorAtX:x y:y] alphaComponent] > 0.1) inked = x;
        if (inked < 0) continue;
        NSRect ink = NSMakeRect(NSMinX(b), NSMinY(b), (inked + 1) / 2.0, NSHeight(b));
        right = MAX(right, NSMaxX([pane convertRect:ink fromView:arrow]));
    }
    return right;
}

static NSDictionary *HeaderReport(NSView *pane, NSButton *reference)
{
    NSTextField *send = (NSTextField *)FindByIdentifier(pane, @"accountSharingSendHeader");
    NSTextField *receive = (NSTextField *)FindByIdentifier(pane, @"accountSharingReceiveHeader");
    if (send == nil && receive == nil) return nil;
    return @{@"send": send ? LabelReport(send, reference) : [NSNull null], @"receive": receive ? LabelReport(receive, reference) : [NSNull null]};
}

// The right edges (alignment rects) of the fields the Restore Default arrows stand beside
// above the section: the two password fields, the Favorites number field and both folder
// buttons, found by binding and outlet.
static NSDictionary *FieldsRight(NSView *pane)
{
    NSMutableDictionary *edges = [NSMutableDictionary dictionary];
    for (NSString *key in @[@"skipPboardTypesList", @"skipPasswordLengthsList", @"favoritesRememberNum"])
        for (NSView *v in [pane subviews])
            if ([v isKindOfClass:[NSTextField class]] && [BoundKeyPath(v) isEqualToString:[@"values." stringByAppendingString:key]])
                edges[key] = @(NSMaxX([v alignmentRectForFrame:[v frame]]));
    for (NSString *outlet in @[@"saveToLocationButton", @"autoSaveToLocationButton"]) {
        NSView *v = [controller valueForKey:outlet];
        if ([v superview] == pane) edges[outlet] = @(NSMaxX([v alignmentRectForFrame:[v frame]]));
    }
    return edges;
}

// A step a case puts into the builder list before the sharing section: every Restore
// Default arrow of General gets 4 pt wider. Each starts where it did, beside its field, so
// the fields stay where they are while the arrows' frames and the symbols drawn in them
// end further right.
@interface AppController (FixtureWiderArrows)
- (void)fixtureWidenRestoreArrows;
@end
@implementation AppController (FixtureWiderArrows)
- (void)fixtureWidenRestoreArrows
{
    NSView *pane = [[self valueForKey:@"savingSectionLabel"] superview];
    for (NSLayoutConstraint *c in [pane constraints])
        if ([c firstAttribute] == NSLayoutAttributeWidth && [c secondItem] == nil &&
            [[(NSView *)[c firstItem] identifier] hasPrefix:@"restoreDefault"])
            [c setConstant:[c constant] + 4];
    [pane layoutSubtreeIfNeeded];
}
@end

// ---- "placed": where the section is once the window shows, with Restore Default arrows shown.

// FCMemoryDefaults keeps no registration domain of its own; this reads back what was
// registered, as NSUserDefaults does. The Restore Default arrows compare against it:
// without it every arrow stays hidden, whatever is stored.
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static IMP prefsAwake;
static void PrefsAwakeFirst(void) { ((void (*)(id, SEL))prefsAwake)(prefs, @selector(awakeFromNib)); }

// FLYCUT_GENERAL_XIB_SPEC: the tree's MainMenu.xib laid onto the NIB's General pane before
// the builders (Tests/Fixtures/GeneralPaneXib.py), as an Xcode build of it shows the pane.
static BOOL xibThenPrefs;
static void ApplyXibFirst(void)
{
    NSDictionary *spec = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:
        [NSString stringWithUTF8String:getenv("FLYCUT_GENERAL_XIB_SPEC")]] options:0 error:NULL];
    NSArray *problems = spec ? GPXApply([[controller valueForKey:@"savingSectionLabel"] superview], [prefs tabView],
                                        controller, spec) : @[@"no spec"];
    if ([problems count]) {
        fprintf(stderr, "XIB step: %s\n", [[problems description] UTF8String]);
        _exit(12);
    }
    if (xibThenPrefs) PrefsAwakeFirst();
}

static BOOL shown = NO;
static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; }
static id FakeAcknowledgements(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc; if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? shown : NO; }
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender)
{
    (void)cmd; (void)sender;
    if (self != window) return;
    // As the window becomes visible AppKit picks a first responder; the focus code of
    // -showPreferencePanel: then hands the focus back to the window.
    SEL pick = NSSelectorFromString(@"_setUpFirstResponderBeforeBecomingVisible");
    if ([self respondsToSelector:pick]) ((void (*)(id, SEL))objc_msgSend)(self, pick);
    shown = YES;
}
static void FakeClose(NSWindow *self, SEL cmd)
{
    (void)cmd;
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowWillCloseNotification object:self];
    shown = NO;
}

static BOOL InSection(NSView *v)
{
    return [[v identifier] hasPrefix:@"accountSharing"] ||
           ([v isKindOfClass:[NSTextField class]] && [[(NSTextField *)v stringValue] isEqualToString:@"Other accounts on this Mac:"]);
}

// Top of the permissions row's separator (its alignment rect) in the pane.
static CGFloat SeparatorTop(NSView *pane, NSView *row)
{
    for (NSView *v in [row subviews])
        if ([v isKindOfClass:[NSBox class]])
            return NSMaxY([pane convertRect:[v alignmentRectForFrame:[v frame]] fromView:row]);
    return NAN;
}

// The list's lines (account rows, the "no other accounts" line, the note) by alignment
// rect against the indented checkbox column ("Diagnostics: save data type, not
// content") and the sharing checkbox: where their boxes and texts start and end.
static NSDictionary *ListEdges(NSView *pane)
{
    NSView *column = BoundTo(pane, @"values.revealPasteboardTypes");
    NSView *checkbox = FindByIdentifier(pane, @"accountSharingCheckbox");
    NSMutableArray *lines = [NSMutableArray array];
    for (NSView *v in [pane subviews]) {
        if (![[v identifier] hasPrefix:@"accountSharing"] || v == checkbox) continue;
        NSRect a = [v alignmentRectForFrame:[v frame]];
        [lines addObject:@{@"view": [v identifier], @"x": @(NSMinX(a)), @"maxX": @(NSMaxX(a)), @"midX": @(NSMidX(a)),
                           @"frameX": @(NSMinX([v frame])), @"frameMaxX": @(NSMaxX([v frame])), @"y": @(NSMinY([v frame])),
                           @"hidden": @([v isHidden])}];
    }
    return @{@"column": @(NSMinX([column alignmentRectForFrame:[column frame]])),
             @"maxX": @(NSMaxX([checkbox alignmentRectForFrame:[checkbox frame]])), @"lines": lines};
}

static BOOL Inside(NSRect r, NSRect bounds)
{
    return NSMinX(r) >= NSMinX(bounds) - 0.01 && NSMaxX(r) <= NSMaxX(bounds) + 0.01 &&
           NSMinY(r) >= NSMinY(bounds) - 0.01 && NSMaxY(r) <= NSMaxY(bounds) + 0.01;
}

// The General pane as the window shows it: the section's views (label, checkbox, account
// rows or the "no other accounts" line, the note line, shown or not) against the window's
// content view and the General box, the label against the lowest other control, the
// section's bottom against the permissions row.
static NSDictionary *Placement(NSString *step)
{
    NSView *content = [window contentView];
    [content layoutSubtreeIfNeeded];
    NSView *pane = PaneView(generalPane);
    NSBox *box = (NSBox *)[pane superview];
    NSView *permissions = FindByIdentifier(pane, @"accessibilityPermissionsRow");
    NSMutableArray *section = [NSMutableArray array];
    CGFloat lowest = CGFLOAT_MAX, bottom = CGFLOAT_MAX, labelTop = -CGFLOAT_MAX, lastLine = CGFLOAT_MAX;
    NSView *note = FindByIdentifier(pane, @"accountSharingStatus");
    BOOL inContent = YES, inBox = YES;
    NSUInteger arrows = 0;
    CGFloat arrowsRight = 0;     // the right edge of the arrow column: the arrows' frames, shown or not
    for (NSView *v in [pane subviews]) {
        if ([[v identifier] hasPrefix:@"restoreDefault"] && ![v isHidden]) arrows++;
        if ([[v identifier] hasPrefix:@"restoreDefault"]) arrowsRight = MAX(arrowsRight, NSMaxX([v frame]));
        if (v == permissions) continue;
        if (!InSection(v)) {
            if (![v isHidden]) lowest = MIN(lowest, NSMinY([v frame]));
            continue;
        }
        BOOL c = Inside([content convertRect:[v bounds] fromView:v], [content bounds]);
        BOOL b = Inside([box convertRect:[v bounds] fromView:v], [box bounds]);
        inContent = inContent && c;
        inBox = inBox && b;
        // A hidden note takes no room: the section ends at its last shown line.
        if (![v isHidden]) bottom = MIN(bottom, NSMinY([v frame]));
        if (![v isHidden] && v != note) lastLine = MIN(lastLine, NSMinY([v frame]));
        if ([v identifier] == nil) labelTop = NSMaxY([v frame]);
        [section addObject:@{@"view": [v identifier] ?: @"label", @"frame": FrameOf([v frame]), @"inContent": @(c), @"inBox": @(b),
                             @"hidden": @([v isHidden])}];
    }
    return @{@"step": step, @"selected": [[[prefs tabView] selectedTabViewItem] identifier] ?: @"",
             @"section": section, @"inContent": @(inContent), @"inBox": @(inBox),
             @"boxInContent": @(Inside([content convertRect:[box bounds] fromView:box], [content bounds])),
             @"labelBelowLowest": @(lowest - labelTop), @"aboveTheRow": @(bottom - NSMaxY([permissions frame])),
             @"belowTheSection": @(bottom - SeparatorTop(pane, permissions)),
             @"permissions": FrameOf([permissions frame]),
             @"permissionsInContent": FrameOf([content convertRect:[permissions bounds] fromView:permissions]),
             @"rows": @([AccountRows(pane) count]), @"none": @(FindByIdentifier(pane, @"accountSharingNoAccounts") != nil),
             @"edges": ListEdges(pane),
             @"unread": @(FindByIdentifier(pane, @"accountSharingAccountsUnread") != nil),
             @"unreadText": [(NSTextField *)FindByIdentifier(pane, @"accountSharingAccountsUnread") stringValue] ?: @"",
             @"arrowsShown": @(arrows), @"arrowsRight": @(arrowsRight), @"arrowsInkRight": @(ArrowInkRight(pane)), @"paneHeight": @(NSHeight([pane bounds])), @"windowWidth": @(NSWidth([window frame])),
             @"fieldsRight": FieldsRight(pane),
             @"savingMaxX": @(NSMaxX([[controller valueForKey:@"savingSectionLabel"] frame])),
             @"contentHeight": @(NSHeight([content frame])), @"lastLine": @(lastLine),
             @"note": note ? @{@"frame": FrameOf([note frame]), @"hidden": @([note isHidden]), @"text": [(NSTextField *)note stringValue]}
                           : [NSNull null]};
}

// argv[4] the number of other accounts, argv[5] "builders-first" (-[UKPrefsPanel awakeFromNib]
// after AppController's, its -resizeToFit: stood in for by a pane change) or "prefs-first"
// (the real -[UKPrefsPanel awakeFromNib] before the builders; the NIB loader uses either
// order), argv[6] "stored" (three numbers changed, as on a Mac in use) or "factory",
// argv[7] "note" (optional): then, with the window open, a stand-in service reports an
// inbox error (the note shows), the pane changes and back, and the error goes again.
static int Placed(int argc, const char **argv)
{
    if (argc < 7) return 2;
    int count = atoi(argv[4]);
    BOOL prefsFirst = strcmp(argv[5], "prefs-first") == 0;
    NSMutableArray *accounts = [NSMutableArray arrayWithObject:@{@"uid": @(getuid()), @"name": @"Account Self",
                                                                  @"guid": @"0F0F0F0F-0000-4000-8000-0000000000FF"}];
    for (int i = 1; i <= count; i++)
        [accounts addObject:@{@"uid": @(7000 + i), @"name": [NSString stringWithFormat:@"Account %c", 'A' + i - 1],
                              @"guid": [NSString stringWithFormat:@"0F0F0F0F-0000-4000-8000-%012d", 7000 + i]}];
    FixtureLoginAccounts = [accounts retain];
    if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 6;
    if (strcmp(argv[6], "stored") == 0) {
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setObject:@99 forKey:@"rememberNum"];
        [defaults setObject:@15 forKey:@"displayNum"];
        [defaults setObject:@25 forKey:@"favoritesRememberNum"];
    }
    prefsAwake = method_getImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)));
    if (prefsFirst) BeforeBuilders = PrefsAwakeFirst;
    if (getenv("FLYCUT_GENERAL_XIB_SPEC")) {
        xibThenPrefs = prefsFirst;
        BeforeBuilders = ApplyXibFirst;
    }
    // argv[7] "unread": the account lookup fails until the window was closed once, and an
    // inbox error shows the note all along (the rebuilt section must give its line back too).
    BOOL unread = argc > 7 && strcmp(argv[7], "unread") == 0;
    if (unread) {
        gThenBeforeBuilders = BeforeBuilders;
        BeforeBuilders = InstallSwitchableLookup;
        gLookupFails = YES;
    }
    int failed = LoadNib(argc, argv);
    if (failed) return failed;
    FCStubShareService *unreadStub = nil;
    if (unread) {
        unreadStub = [[[FCStubShareService alloc] init] autorelease];
        unreadStub->code = 3;
        [controller setValue:unreadStub forKey:@"accountShareService"];
        [controller performSelector:@selector(accountShareServiceDidChangeState:) withObject:unreadStub];
    }
    if (!prefsFirst) ChangePane(generalPane);
    method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
    method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeAcknowledgements);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(close)), (IMP)FakeClose);
    NSMutableArray *steps = [NSMutableArray array];
    [controller showPreferencePanel:nil];
    [steps addObject:Placement(@"opened")];
    NSTabView *tabs = [prefs tabView];
    for (NSInteger i = 0; i < [tabs numberOfTabViewItems]; i++) {
        if (i == generalPane) continue;
        ChangePane(i);
        ChangePane(generalPane);
        [steps addObject:Placement([@"back from " stringByAppendingString:[[tabs tabViewItemAtIndex:i] label]])];
    }
    [window close];
    if (unread) gLookupFails = NO;   // the lookup works again before the window opens next
    [controller showPreferencePanel:nil];
    [steps addObject:Placement(@"reopened")];
    if (unread) {
        ChangePane(hotkeysPane);
        ChangePane(generalPane);
        [steps addObject:Placement(@"read, back from Hotkeys")];
        [window close];
        [controller showPreferencePanel:nil];
        [steps addObject:Placement(@"read, reopened")];
        [controller setValue:nil forKey:@"accountShareService"];
    }
    if (argc > 7 && strcmp(argv[7], "note") == 0) {
        FCStubShareService *stub = [[[FCStubShareService alloc] init] autorelease];
        [controller setValue:stub forKey:@"accountShareService"];
        stub->code = 3;
        [controller performSelector:@selector(accountShareServiceDidChangeState:) withObject:stub];
        [steps addObject:Placement(@"note shown")];
        ChangePane(hotkeysPane);
        ChangePane(generalPane);
        [steps addObject:Placement(@"note shown, back from Hotkeys")];
        stub->code = 0;
        [controller performSelector:@selector(accountShareServiceDidChangeState:) withObject:stub];
        [steps addObject:Placement(@"note hidden again")];
        [controller setValue:nil forKey:@"accountShareService"];
    }
    Emit(@{@"steps": steps});
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        NSString *mode = argc > 2 ? [NSString stringWithUTF8String:argv[2]] : @"";
        if ([mode isEqualToString:@"placed"]) return Placed(argc, argv);
        if (![mode isEqualToString:@"none"])
            FixtureLoginAccounts = [@[@{@"uid": @7001, @"name": [mode isEqualToString:@"long-name"] ? @"Example Account With A Rather Long Full Name That Goes On And On" : @"Account A",
                                        @"guid": @"0F0F0F0F-0000-4000-8000-000000007001"},
                                      @{@"uid": @(getuid()), @"name": @"Account Self", @"guid": @"0F0F0F0F-0000-4000-8000-0000000000FF"},
                                      @{@"uid": @7002, @"name": @"Account B", @"guid": @"0F0F0F0F-0000-4000-8000-000000007002"}] retain];
        // Account B is stored in the send list only.
        [[NSUserDefaults standardUserDefaults] setObject:@[@"0F0F0F0F-0000-4000-8000-000000007002"] forKey:@"shareClippingsSendAccountIDs"];
        [[NSUserDefaults standardUserDefaults] setObject:@[] forKey:@"shareClippingsReceiveAccountIDs"];
        if ([mode isEqualToString:@"on"]) BeforeBuilders = ShareOn;
        if ([mode isEqualToString:@"fitted-first"]) BeforeBuilders = FitGeneralFirst;
        if ([mode isEqualToString:@"click-unread"]) BeforeBuilders = InstallSwitchableLookup;
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        NSView *pane = PaneView(generalPane);
        NSBox *box = (NSBox *)[pane superview];
        NSMutableDictionary *report = [NSMutableDictionary dictionary];
        if ([mode isEqualToString:@"narrower"]) {
            // The pane gets 40 pt narrower (a window fitted to narrower content): the
            // section keeps its place and its width, as the arrows and the NIB's controls do.
            NSMutableArray *views = [NSMutableArray arrayWithObject:[controller valueForKey:@"accountSharingLabel"]];
            for (NSView *v in [pane subviews])
                if ([[v identifier] hasPrefix:@"accountSharing"]) [views addObject:v];
            NSMutableArray *before = [NSMutableArray array], *after = [NSMutableArray array];
            for (NSView *v in views) [before addObject:@{@"view": [v identifier] ?: @"label", @"frame": FrameOf([v frame])}];
            [box setFrameSize:NSMakeSize(NSWidth([box frame]) - 40, NSHeight([box frame]))];
            for (NSView *v in views) [after addObject:@{@"view": [v identifier] ?: @"label", @"frame": FrameOf([v frame])}];
            report[@"before"] = before;
            report[@"after"] = after;
            report[@"paneWidths"] = @[@(NSWidth([pane frame]) + 40), @(NSWidth([pane frame]))];
            report[@"section"] = @(FindByIdentifier(pane, @"accountSharingCheckbox") != nil);
            Emit(report);
            return 0;
        }
        if ([mode isEqualToString:@"fitted-first"]) {
            // No further pane change: the builder itself must have fitted the window.
            report[@"contentHeight"] = @(NSHeight([[window contentView] frame]));
            report[@"boxHeight"] = @(NSHeight([box frame]));
            report[@"section"] = @(FindByIdentifier(pane, @"accountSharingCheckbox") != nil);
            Emit(report);
            return 0;
        }
        ChangePane(appearancePane);
        report[@"appearanceHeight"] = @(NSHeight([[window contentView] frame]));
        ChangePane(hotkeysPane);
        report[@"hotkeysHeight"] = @(NSHeight([[window contentView] frame]));
        ChangePane(generalPane);
        NSTextField *saving = [controller valueForKey:@"savingSectionLabel"];
        NSView *permissions = FindByIdentifier(pane, @"accessibilityPermissionsRow");
        NSButton *reference = (NSButton *)BoundTo(pane, @"values.removeDuplicates");
        NSButton *below = (NSButton *)BoundTo(pane, @"values.pasteMovesToTop");
        NSButton *suboption = (NSButton *)BoundTo(pane, @"values.revealPasteboardTypes");
        NSTextField *label = (NSTextField *)FindByTitle(pane, @"Other accounts on this Mac:", [NSTextField class]);
        NSButton *checkbox = (NSButton *)FindByIdentifier(pane, @"accountSharingCheckbox");
        NSTextField *none = (NSTextField *)FindByIdentifier(pane, @"accountSharingNoAccounts");
        NSTextField *status = (NSTextField *)FindByIdentifier(pane, @"accountSharingStatus");
        NSArray *rows = AccountRows(pane), *sends = SendBoxes(pane), *receives = ReceiveBoxes(pane);
        NSView *sticky = BoundTo(pane, @"values.stickyBezel");
        CGFloat lowest = CGFLOAT_MAX;
        for (NSView *v in [pane subviews]) {
            if (v == permissions || v == label || [[v identifier] hasPrefix:@"accountSharing"] || [v isHidden]) continue;
            lowest = MIN(lowest, NSMinY([v frame]));
        }
        report[@"paneHeight"] = @(NSHeight([pane bounds]));
        report[@"windowWidth"] = @(NSWidth([window frame]));
        // The right edge of General's Restore Default arrow column (the arrows' frames, shown or not).
        CGFloat arrowsRight = 0;
        for (NSView *v in [pane subviews])
            if ([v isKindOfClass:[NSButton class]] && [[v identifier] hasPrefix:@"restoreDefault"])
                arrowsRight = MAX(arrowsRight, NSMaxX([v frame]));
        report[@"arrowsRight"] = @(arrowsRight);
        report[@"arrowsInkRight"] = @(ArrowInkRight(pane));
        report[@"fieldsRight"] = FieldsRight(pane);
        report[@"contentHeight"] = @(NSHeight([[window contentView] frame]));
        report[@"boxHeight"] = @(NSHeight([box frame]));
        report[@"stickyTopDistance"] = @(NSHeight([pane bounds]) - NSMaxY([sticky frame]));
        report[@"lowestNib"] = @(lowest);
        report[@"permissions"] = FrameOf([permissions frame]);
        report[@"saving"] = FrameOf([saving frame]);
        report[@"reference"] = FrameOf([reference frame]);
        report[@"below"] = FrameOf([below frame]);
        report[@"suboption"] = FrameOf([suboption frame]);
        report[@"suboptionAlign"] = FrameOf([suboption alignmentRectForFrame:[suboption frame]]);
        if (label == nil || checkbox == nil) {
            report[@"section"] = @NO;
            Emit(report);
            return 0;
        }
        report[@"section"] = @YES;
        report[@"label"] = FrameOf([label frame]);
        report[@"checkbox"] = FrameOf([checkbox frame]);
        report[@"checkboxAlign"] = FrameOf([checkbox alignmentRectForFrame:[checkbox frame]]);
        report[@"labelFontSame"] = @([[label font] isEqual:[saving font]]);
        report[@"labelColorSame"] = @([[label textColor] isEqual:[saving textColor]]);
        report[@"checkboxFontSame"] = @([[checkbox font] isEqual:[reference font]]);
        report[@"title"] = [checkbox title];
        report[@"fits"] = @([checkbox intrinsicContentSize].width <= NSWidth([checkbox frame]) + 0.5
                            && [label intrinsicContentSize].width <= NSWidth([label frame]) + 0.5);
        report[@"state"] = @([checkbox state]);
        report[@"tooltip"] = [checkbox toolTip] ?: @"";
        report[@"axControl"] = [checkbox accessibilityLabel] ?: @"";
        report[@"axCell"] = [[checkbox cell] accessibilityLabel] ?: @"";
        NSDictionary *binding = [checkbox infoForBinding:NSValueBinding];
        report[@"bindingKeyPath"] = binding[NSObservedKeyPathKey] ?: @"";
        report[@"bindingToDefaults"] = @(binding[NSObservedObjectKey] == [NSUserDefaultsController sharedUserDefaultsController]);
        report[@"action"] = NSStringFromSelector([checkbox action]) ?: @"";
        report[@"targetIsController"] = @([checkbox target] == controller);
        NSMutableArray *rowReports = [NSMutableArray array];
        report[@"lineCounts"] = @[@([rows count]), @([sends count]), @([receives count])];
        for (NSUInteger i = 0; i < [rows count] && i < [sends count] && i < [receives count]; i++)
            [rowReports addObject:RowReport(pane, i, reference)];
        report[@"rows"] = rowReports;
        report[@"headers"] = HeaderReport(pane, reference) ?: [NSNull null];
        if (none != nil)
            report[@"none"] = @{@"text": [none stringValue], @"frame": FrameOf([none frame]),
                                @"align": FrameOf([none alignmentRectForFrame:[none frame]]),
                                @"fontSame": @([[none font] isEqual:[reference font]]),
                                @"colorSame": @([[none textColor] isEqual:[saving textColor]]),
                                @"fits": @([none intrinsicContentSize].width <= NSWidth([none frame]) + 0.5)};
        if (status != nil) {
            NSMutableArray *notes = [NSMutableArray array];
            if ([mode isEqualToString:@"status"]) {
                FCStubShareService *stub = [[[FCStubShareService alloc] init] autorelease];
                [controller setValue:stub forKey:@"accountShareService"];
                for (NSNumber *code in @[@2, @3, @7, @0]) {
                    stub->code = [code integerValue];
                    [controller performSelector:@selector(accountShareServiceDidChangeState:) withObject:stub];
                    [notes addObject:@{@"code": code, @"text": [status stringValue], @"hidden": @([status isHidden]),
                                       @"fits": @([status intrinsicContentSize].width <= NSWidth([status frame]) + 0.5),
                                       @"paneHeight": @(NSHeight([pane bounds])), @"frame": FrameOf([status frame]),
                                       @"permissions": FrameOf([permissions frame])}];
                }
                [controller setValue:nil forKey:@"accountShareService"];
            }
            report[@"status"] = @{@"frame": FrameOf([status frame]), @"hidden": @([status isHidden]), @"text": [status stringValue],
                                  @"align": FrameOf([status alignmentRectForFrame:[status frame]]),
                                  @"fontSame": @([[status font] isEqual:[reference font]]), @"notes": notes};
        }
        // Key-view order: the controls of the pane in -nextKeyView order from the tab view.
        NSMutableArray *order = [NSMutableArray array];
        NSView *v = [[prefs tabView] nextKeyView];
        for (int steps = 0; v != nil && v != [prefs tabView] && steps < 500; steps++, v = [v nextKeyView]) {
            if ([v window] != window || [v isHiddenOrHasHiddenAncestor] || ![v isKindOfClass:[NSControl class]]) continue;
            // Tab never stops at a label (a text field that can be neither edited nor selected).
            if ([v isKindOfClass:[NSTextField class]] && ![(NSTextField *)v isEditable] && ![(NSTextField *)v isSelectable]) continue;
            NSUInteger i;
            NSString *name = v == checkbox ? @"share"
                : ((i = [sends indexOfObject:v]) != NSNotFound ? [@"send:" stringByAppendingString:[rows[i] stringValue]]
                : ((i = [receives indexOfObject:v]) != NSNotFound ? [@"receive:" stringByAppendingString:[rows[i] stringValue]]
                : ([rows containsObject:v] ? [@"name:" stringByAppendingString:[(NSTextField *)v stringValue]]
                : ([[v identifier] hasPrefix:@"accountSharing"] ? [v identifier]
                : ([v isKindOfClass:[NSButton class]] ? [(NSButton *)v title] : NSStringFromClass([v class]))))));
            if (![order containsObject:name]) [order addObject:name];
        }
        report[@"keyOrder"] = order;
        report[@"favoritesTitle"] = [[controller valueForKey:@"forgottenFavoritesCheckbox"] title] ?: @"";
        NSString *(^colors)(void) = ^NSString *{
            NSMutableSet *set = [NSMutableSet set];
            for (NSTextField *name in rows) [set addObject:ColorName(name)];
            for (NSString *h in @[@"accountSharingSendHeader", @"accountSharingReceiveHeader"])
                if (FindByIdentifier(pane, h)) [set addObject:ColorName((NSTextField *)FindByIdentifier(pane, h))];
            return [[[set allObjects] sortedArrayUsingSelector:@selector(compare:)] componentsJoinedByString:@","];
        };
        BOOL (^enabled)(BOOL) = ^BOOL(BOOL all) {
            BOOL any = NO, every = YES;
            for (NSButton *b in [sends arrayByAddingObjectsFromArray:receives]) { any = any || [b isEnabled]; every = every && [b isEnabled]; }
            return all ? every : any;
        };
        report[@"textColors"] = colors();
        if ([mode isEqualToString:@"click"] && [rows count] == 2) {
            // Clicks as a user makes them: sharing on, then Send and Receive for Account A on, then
            // Send for Account B off, then sharing off.
            NSMutableArray *steps = [NSMutableArray array];
            [checkbox performClick:nil];
            [steps addObject:@{@"share": @([[NSUserDefaults standardUserDefaults] boolForKey:@"shareClippingsAcrossAccounts"]),
                               @"enabled": @(enabled(YES)), @"colors": colors(), @"chosen": Chosen()}];
            [sends[0] performClick:nil];
            [steps addObject:@{@"sendA": @([sends[0] state]), @"receiveA": @([receives[0] state]), @"chosen": Chosen()}];
            [receives[0] performClick:nil];
            [steps addObject:@{@"sendA": @([sends[0] state]), @"receiveA": @([receives[0] state]), @"chosen": Chosen()}];
            [sends[1] performClick:nil];
            [steps addObject:@{@"sendB": @([sends[1] state]), @"receiveB": @([receives[1] state]), @"chosen": Chosen()}];
            [checkbox performClick:nil];
            [steps addObject:@{@"share": @([[NSUserDefaults standardUserDefaults] boolForKey:@"shareClippingsAcrossAccounts"]),
                               @"enabled": @(enabled(NO)), @"colors": colors(), @"chosen": Chosen(),
                               @"states": @[@([sends[0] state]), @([receives[0] state]), @([sends[1] state]), @([receives[1] state])]}];
            report[@"clicks"] = steps;
        }
        if ([mode isEqualToString:@"click-unread"] && [rows count] == 2) {
            // The account lookup fails while the window is open: a click on a row cannot be
            // stored; the rows keep showing the choice, also when sharing goes off and on.
            [checkbox performClick:nil];
            NSDictionary *stored = [StoredLists() retain];
            gLookupFails = YES;
            for (NSButton *b in @[sends[0], sends[1], receives[0], receives[1]]) [b performClick:nil];
            NSArray *(^states)(void) = ^NSArray *{
                return @[@([sends[0] state]), @([receives[0] state]), @([sends[1] state]), @([receives[1] state])];
            };
            NSArray *clicked = states();
            [checkbox performClick:nil];
            [checkbox performClick:nil];
            report[@"unreadClicks"] = @{@"clicked": clicked, @"toggled": states(), @"storedSame": @([StoredLists() isEqual:stored])};
            gLookupFails = NO;
            [stored release];
        }
        if ([mode isEqualToString:@"click-gone"] && [rows count] == 2) {
            // Account A is deleted while the window is open: a click on its row cannot be
            // stored (no login account has its UID now), so the row must not stay checked.
            [checkbox performClick:nil];
            NSDictionary *stored = [StoredLists() retain];
            NSArray *left = @[FixtureLoginAccounts[1], FixtureLoginAccounts[2]];
            [FixtureLoginAccounts release];
            FixtureLoginAccounts = [left retain];
            [sends[0] performClick:nil];
            [receives[0] performClick:nil];
            report[@"gone"] = @{@"states": @[@([sends[0] state]), @([receives[0] state]), @([sends[1] state]), @([receives[1] state])],
                                @"storedSame": @([StoredLists() isEqual:stored])};
            [stored release];
        }
        Emit(report);
    }
    return 0;
}
'''


class PreferencesAccountSharingTests(PreferencesNibCase):
    FIXTURE = GeneralPaneXib.APPLY_SOURCE + FIXTURE
    NAME = "PreferencesAccountSharing"

    def report(self, mode: str, builders: str | None = None) -> dict:
        if self.nib_source is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        run = subprocess.run([str(self.binary), str(self.bundle), mode, builders or self.builders], cwd=ROOT,
                             text=True, capture_output=True, timeout=90)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertTrue(reports, run.stdout[-1500:] + run.stderr[-1500:])
        print(f"\n{mode}: {reports[-1]}")
        return json.loads(reports[-1])

    def section(self, mode: str) -> dict:
        r = self.report(mode)
        self.assertTrue(r["section"], "no 'Other accounts on this Mac:' section with the sharing checkbox")
        return r

    def column_right(self, r: dict, where: str = "") -> float:
        """Where the Receive column ends: where the fields above the section end (alignment
        rects), the two password fields, the Favorites number field and both folder buttons,
        which the Restore Default arrows stand beside. They share that edge, left of the
        arrows' frames and of the symbols drawn in them."""
        fields = r["fieldsRight"]
        self.assertEqual(sorted(fields), sorted(["skipPboardTypesList", "skipPasswordLengthsList", "favoritesRememberNum",
                                                 "saveToLocationButton", "autoSaveToLocationButton"]),
                         f"{where}: a field above the section is missing")
        self.assertEqual(len(set(fields.values())), 1, f"{where}: the fields above the section do not end at one edge: {fields}")
        right = next(iter(fields.values()))
        self.assertGreater(r["arrowsInkRight"], right, f"{where}: the Restore Default arrows do not stand right of the fields")
        self.assertLess(r["arrowsInkRight"], r["arrowsRight"], f"{where}: the arrows' symbols are not narrower than their frames")
        return right

    def test_receive_column_ends_flush_with_the_fields_above(self) -> None:
        """"Receive" (its header's alignment rect) ends exactly where the fields above end, also
        when the arrows beside them are wider (their frames and symbols end further right, the
        fields stay): the edge comes from the fields, not from the arrows. Send keeps its column
        8 pt left of Receive's, so it moves by the same amount; both headers fill their columns,
        which are as wide as the wider header (whole points), the checkboxes are centred under
        them and each name ends 8 pt before Send."""
        wider = self.builders.replace("buildGeneralAccountSharingSection",
                                      "fixtureWidenRestoreArrows,buildGeneralAccountSharingSection")
        self.assertNotEqual(wider, self.builders, "the sharing section is not built")
        runs = {"as built": self.section("off"), "wider arrows": self.report("off", wider)}
        normal, widened = runs["as built"], runs["wider arrows"]
        self.assertEqual(widened["fieldsRight"], normal["fieldsRight"], "wider arrows moved the fields")
        self.assertEqual(widened["arrowsRight"] - normal["arrowsRight"], 4, "the arrows did not get wider")
        self.assertGreater(widened["arrowsInkRight"], normal["arrowsInkRight"], "the arrows' symbols did not move right")
        for where, r in runs.items():
            right = self.column_right(r, where)
            send, receive = r["headers"]["send"], r["headers"]["receive"]
            width = math.ceil(max(send["textW"], receive["textW"]))
            self.assertEqual(receive["align"]["x"] + receive["align"]["w"], right,
                             f"{where}: 'Receive' ends at {receive['align']['x'] + receive['align']['w']:g}, the fields at {right:g}")
            self.assertEqual((receive["align"]["x"], receive["align"]["w"]), (right - width, width),
                             f"{where}: 'Receive' does not fill its column")
            self.assertEqual((send["align"]["x"], send["align"]["w"]), (right - 2 * width - 8, width),
                             f"{where}: 'Send' does not stand 8 pt left of the Receive column")
            for row in r["rows"]:
                self.assertLessEqual(abs(row["send"]["midX"] - (right - width - 8 - width / 2)), 0.5,
                                     f"{where}: the Send checkbox is not centred under 'Send'")
                self.assertLessEqual(abs(row["receive"]["midX"] - (right - width / 2)), 0.5,
                                     f"{where}: the Receive checkbox is not centred under 'Receive'")
                self.assertEqual(row["name"]["align"]["x"] + row["name"]["align"]["w"], right - 2 * width - 16,
                                 f"{where}: the name does not end 8 pt before Send")

    def baseline(self) -> dict:
        builders = ",".join(b for b in self.builders.split(",") if b != "buildGeneralAccountSharingSection")
        return self.report("baseline", builders)

    def test_section_sits_below_saving_with_the_neighbours_look(self) -> None:
        r = self.section("off")
        self.assertEqual(r["title"], TITLE)
        self.assertEqual(r["label"]["x"], r["saving"]["x"])
        self.assertEqual(r["label"]["h"], r["saving"]["h"])
        self.assertTrue(r["labelFontSame"] and r["labelColorSame"], "the section label does not look like 'Saving:'")
        self.assertEqual(r["checkbox"]["x"], r["reference"]["x"])
        self.assertEqual(r["checkbox"]["h"], r["reference"]["h"])
        self.assertTrue(r["checkboxFontSame"], "the checkbox does not use the pane's checkbox font")
        self.assertTrue(r["fits"], "a title is cut off")
        label_top = r["label"]["y"] + r["label"]["h"]
        self.assertEqual(r["lowestNib"] - label_top, 16, "label 16 pt below the Saving section")
        self.assertEqual(r["label"]["y"] - (r["checkbox"]["y"] + r["checkbox"]["h"]), 8, "checkbox 8 pt below the label")

    def test_one_line_per_other_account_with_a_send_and_a_receive_checkbox(self) -> None:
        r = self.section("off")
        self.assertEqual(r["lineCounts"], [2, 2, 2], "one name, one Send and one Receive checkbox per account")
        rows = r["rows"]
        self.assertEqual([row["title"] for row in rows], ["Account A", "Account B"], "this account is not listed")
        pitch = r["reference"]["y"] - r["below"]["y"]
        self.assertEqual(pitch, 20)
        headers = r["headers"]
        self.assertIsNotNone(headers, "no Send and Receive column headers")
        send, receive = headers["send"], headers["receive"]
        self.assertEqual((send["text"], receive["text"]), ("Send", "Receive"))
        for h in (send, receive):
            self.assertEqual(h["frame"]["y"], r["checkbox"]["y"] - pitch, "the headers are one line below the checkbox")
            self.assertEqual(h["frame"]["h"], r["reference"]["h"])
            self.assertTrue(h["fontSame"] and h["fits"], h)
        # Two columns as wide as the wider header (whole points), 8 pt apart, "Receive"
        # ending where the fields above end; each header fills its column, its text centred.
        right = self.column_right(r)
        width = math.ceil(max(send["textW"], receive["textW"]))
        send_mid, receive_mid = right - width - 8 - width / 2, right - width / 2
        self.assertEqual(receive["align"]["x"] + receive["align"]["w"], right, "'Receive' does not end with the fields above")
        self.assertLessEqual(abs(receive["midX"] - receive_mid), 0.5, "'Receive' is not centred in its column")
        self.assertLessEqual(abs(send["midX"] - send_mid), 0.5, "'Send' is not centred in its column")
        for i, row in enumerate(rows):
            name, box_s, box_r = row["name"], row["send"], row["receive"]
            y = r["checkbox"]["y"] - pitch * (i + 2)
            self.assertEqual((name["frame"]["y"], box_s["frame"]["y"], box_r["frame"]["y"]), (y, y, y),
                             "a line's name and checkboxes are not on the line below the one above")
            for v in (name, box_s, box_r):
                self.assertEqual(v["frame"]["h"], r["reference"]["h"])
                self.assertTrue(v["fontSame"] and v["fits"], v)
            self.assertEqual(name["align"]["x"], r["suboptionAlign"]["x"], "names are indented like 'Diagnostics: save data type, not content'")
            self.assertEqual(right - 2 * width - 16, name["align"]["x"] + name["align"]["w"], "the name ends 8 pt before Send")
            self.assertLessEqual(abs(box_s["midX"] - send_mid), 0.5, "the Send checkbox is not centred under 'Send'")
            self.assertLessEqual(abs(box_r["midX"] - receive_mid), 0.5, "the Receive checkbox is not centred under 'Receive'")
            self.assertEqual((box_s["title"], box_r["title"]), ("", ""), "the checkboxes carry the name as a title")
            self.assertEqual((name["tag"], box_s["tag"], box_r["tag"]), (7001 + i,) * 3)
            self.assertEqual((box_s["action"], box_r["action"]), ("toggleSendToAccount:", "toggleReceiveFromAccount:"))
            self.assertTrue(box_s["targetIsController"] and box_r["targetIsController"])

    def test_a_long_name_is_shortened_before_send_and_widens_nothing(self) -> None:
        short, long = self.section("off"), self.section("long-name")
        self.assertEqual(long["windowWidth"], short["windowWidth"], "a long account name widens the window")
        rows = {row["name"]["tag"]: row for row in long["rows"]}
        short_rows = {row["name"]["tag"]: row for row in short["rows"]}
        name = rows[7001]["name"]
        self.assertEqual(name["text"], LONG_NAME)
        self.assertEqual(name["frame"], short_rows[7001]["name"]["frame"], "the name column is not fixed")
        self.assertGreater(name["textW"], name["align"]["w"], "the dummy name is not longer than the column")
        self.assertEqual(name["lineBreak"], 4, "the name is not shortened with an ellipsis at its end")
        self.assertEqual(name["tooltip"], LONG_NAME, "the full name is not in the tooltip")
        self.assertEqual(name["axValue"], LONG_NAME, "VoiceOver does not get the full name")
        self.assertEqual(short_rows[7002]["name"]["tooltip"], "Account B")
        for key in ("send", "receive"):
            self.assertEqual(rows[7001][key]["frame"], short_rows[7001][key]["frame"], "a long name moves a checkbox")
        self.assertEqual(rows[7001]["send"]["axControl"], "Send to " + LONG_NAME)

    def test_the_section_keeps_its_place_when_the_pane_gets_narrower(self) -> None:
        r = self.section("narrower")
        self.assertLess(r["paneWidths"][1], r["paneWidths"][0], "the pane did not get narrower")
        moved = [(b["view"], b["frame"], a["frame"]) for b, a in zip(r["before"], r["after"]) if b["frame"] != a["frame"]]
        self.assertEqual(moved, [], "a view of the section moved or changed its width with the pane")

    def test_checkboxes_show_the_stored_lists_and_are_off_until_sharing_is_on(self) -> None:
        off, on = self.section("off"), self.section("on")
        self.assertEqual([(row["send"]["state"], row["receive"]["state"]) for row in off["rows"]], [(0, 0), (1, 0)],
                         "Account B is in the stored send list only")
        self.assertEqual({(row["send"]["enabled"], row["receive"]["enabled"]) for row in off["rows"]}, {(False, False)},
                         "the checkboxes are disabled while sharing is off")
        self.assertEqual(off["textColors"], "disabled", "names and headers are not greyed while sharing is off")
        self.assertEqual({(row["send"]["enabled"], row["receive"]["enabled"]) for row in on["rows"]}, {(True, True)})
        self.assertEqual(on["textColors"], "label", "names and headers do not look like the pane's labels while sharing is on")
        self.assertEqual([(row["send"]["state"], row["receive"]["state"]) for row in on["rows"]], [(0, 0), (1, 0)])

    def test_clicks_store_each_list_and_follow_the_checkbox(self) -> None:
        r = self.section("click")
        self.assertIn("clicks", r, "no two account lines with Send and Receive checkboxes to click")
        steps = r["clicks"]
        self.assertEqual(steps[0], {"share": True, "enabled": True, "colors": "label", "chosen": {"send": [7002], "receive": []}})
        self.assertEqual(steps[1], {"sendA": 1, "receiveA": 0, "chosen": {"send": [7001, 7002], "receive": []}})
        self.assertEqual(steps[2], {"sendA": 1, "receiveA": 1, "chosen": {"send": [7001, 7002], "receive": [7001]}})
        self.assertEqual(steps[3], {"sendB": 0, "receiveB": 0, "chosen": {"send": [7001], "receive": [7001]}})
        self.assertEqual(steps[4], {"share": False, "enabled": False, "colors": "disabled",
                                    "chosen": {"send": [7001], "receive": [7001]}, "states": [1, 1, 0, 0]},
                         "the choice is kept while off")

    def test_a_click_that_cannot_be_stored_leaves_the_checkboxes_as_stored(self) -> None:
        r = self.section("click-gone")
        self.assertIn("gone", r, "no two account lines with Send and Receive checkboxes to click")
        self.assertEqual(r["gone"], {"states": [0, 0, 1, 0], "storedSame": True},
                         "a click on a deleted account's Send or Receive stores nothing, so it must not show checked")

    def test_while_the_accounts_cannot_be_read_a_click_is_undone(self) -> None:
        r = self.section("click-unread")
        self.assertIn("unreadClicks", r, "no two account lines with Send and Receive checkboxes to click")
        self.assertEqual(r["unreadClicks"], {"clicked": [0, 0, 1, 0], "toggled": [0, 0, 1, 0], "storedSame": True},
                         "while the accounts cannot be read both columns must keep showing the stored lists")

    def test_no_other_account_shows_a_line_instead_of_the_list(self) -> None:
        r = self.section("none")
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["lineCounts"], [0, 0, 0])
        self.assertIsNone(r["headers"], "column headers without any account")
        self.assertEqual(r["none"]["text"], NONE)
        # Its text starts at the indented checkboxes' box and ends with the checkbox above it:
        # alignment rects, since a label's text sits 2 pt inside its frame.
        self.assertEqual(r["none"]["align"]["x"], r["suboptionAlign"]["x"], "the text does not start at the checkboxes' edge")
        self.assertEqual(r["none"]["align"]["x"] + r["none"]["align"]["w"], r["checkboxAlign"]["x"] + r["checkboxAlign"]["w"])
        self.assertEqual(r["none"]["frame"]["y"], r["checkbox"]["y"] - 20)
        self.assertTrue(r["none"]["fontSame"] and r["none"]["colorSame"] and r["none"]["fits"], r["none"])

    def test_a_line_below_the_list_says_why_sharing_is_unavailable(self) -> None:
        r = self.section("status")
        self.assertIn("status", r, "no note line in the section")
        status = r["status"]
        self.assertTrue(r["rows"], "no account lines")
        last = r["rows"][-1]["name"]["frame"]["y"]
        # Its text starts at the account rows' boxes and ends with the checkbox: alignment rects.
        self.assertEqual(status["align"]["x"], r["suboptionAlign"]["x"], "the note's text does not start at the rows' boxes")
        self.assertEqual(status["frame"]["y"], last - 20, "one line below the last account")
        self.assertEqual(status["align"]["x"] + status["align"]["w"], r["checkboxAlign"]["x"] + r["checkboxAlign"]["w"])
        self.assertTrue(status["fontSame"])
        self.assertEqual([(n["code"], n["hidden"]) for n in status["notes"]], [(2, False), (3, False), (7, False), (0, True)])
        self.assertEqual([n["text"] for n in status["notes"][:3]], [
            "Sharing is unavailable: /Users/Shared cannot be opened.",
            "Sharing is unavailable: its folder in /Users/Shared is taken.",
            "Sharing is unavailable: its folder could not be set up."])
        self.assertTrue(all(n["fits"] for n in status["notes"]), status["notes"])
        # The pane has the note's line only while it shows; the permissions row keeps its place.
        self.assertEqual([n["paneHeight"] - r["paneHeight"] for n in status["notes"]], [20, 20, 20, 0],
                         "the pane does not grow by the note's line while it shows, and back")
        self.assertEqual({json.dumps(n["permissions"]) for n in status["notes"]}, {json.dumps(r["permissions"])})
        off = self.section("off")
        self.assertTrue(off["status"]["hidden"], "no note while nothing is wrong")

    def test_pane_grows_by_the_section_and_nothing_else_moves(self) -> None:
        base = self.baseline()
        self.assertFalse(base["section"])
        base_gap = base["lowestNib"] - (base["permissions"]["y"] + base["permissions"]["h"])
        # The headers and the account lines (or the "no other accounts" line); a hidden note takes no line.
        for mode, lines in (("off", 3), ("none", 1)):
            r = self.section(mode)
            grown = r["paneHeight"] - base["paneHeight"]
            self.assertEqual(grown, r["label"]["h"] + r["checkbox"]["h"] + 16 + 8 + 20 * lines, mode)
            self.assertEqual(r["contentHeight"] - base["contentHeight"], grown, "the window does not follow the pane")
            self.assertEqual(r["stickyTopDistance"], base["stickyTopDistance"], "NIB controls moved")
            self.assertEqual(r["permissions"], base["permissions"], "the permissions row moved")
            bottom = r["checkbox"]["y"] - 20 * lines
            gap = bottom - (r["permissions"]["y"] + r["permissions"]["h"])
            self.assertEqual(gap, base_gap, f"{mode}: the gap above the permissions row changed")
            self.assertEqual((r["appearanceHeight"], r["hotkeysHeight"]), (base["appearanceHeight"], base["hotkeysHeight"]),
                             "another pane changed its height")

    def test_window_follows_when_the_pane_was_fitted_before_the_builder(self) -> None:
        r = self.report("fitted-first")
        self.assertTrue(r["section"], "no sharing checkbox")
        self.assertEqual(r["contentHeight"], r["boxHeight"])

    def xib_env(self) -> dict:
        spec = pathlib.Path(self.temp.name) / "xib.json"
        if not spec.exists():
            spec.write_text(json.dumps(GeneralPaneXib.spec(ROOT / "English.lproj" / "MainMenu.xib")))
        return dict(os.environ, FLYCUT_GENERAL_XIB_SPEC=str(spec))

    def check_list_edges(self, s: dict, where: str) -> None:
        """By alignment rect (a checkbox's box, a label's text): every line of the list starts at
        the indented checkboxes' edge; the "no other accounts", "cannot be read" and note lines and
        end with the sharing checkbox; the Receive column ends where the fields above end
        (exactly); both columns are as wide as the wider header (whole points) and 8 pt apart,
        each name ends 8 pt before the Send column; each
        header and checkbox is centred in its column (within 0.5 pt: whole points), each
        checkbox on its name's line; nothing reaches further right than the pane's labels."""
        edges = s["edges"]
        lines = edges["lines"]
        self.assertTrue(lines, f"{where}: no lines")
        by: dict = {}
        for line in lines:
            by.setdefault(line["view"], []).append(line)
            if line["view"] in ("accountSharingAccountName", "accountSharingNoAccounts", "accountSharingAccountsUnread",
                                "accountSharingStatus"):
                self.assertEqual(line["x"], edges["column"], f"{where}: {line['view']} starts off the checkboxes' edge: {line}")
            if line["view"] in ("accountSharingNoAccounts", "accountSharingAccountsUnread", "accountSharingStatus"):
                self.assertEqual(line["maxX"], edges["maxX"], f"{where}: {line['view']} ends off the checkbox's edge: {line}")
            self.assertLessEqual(line["frameMaxX"], s["savingMaxX"] + 0.01, f"{where}: {line['view']} reaches past the labels")
        names = by.get("accountSharingAccountName", [])
        self.assertEqual((len(by.get("accountSharingSend", [])), len(by.get("accountSharingReceive", []))),
                         (len(names), len(names)), f"{where}: not one Send and one Receive checkbox per name")
        headers = len(by.get("accountSharingSendHeader", [])) + len(by.get("accountSharingReceiveHeader", []))
        self.assertEqual(headers, 2 if names else 0, f"{where}: column headers")
        if not names:
            return
        send, receive = by["accountSharingSendHeader"][0], by["accountSharingReceiveHeader"][0]
        self.assertEqual(send["y"], receive["y"], f"{where}: the headers are not on one line")
        width = math.ceil(max(send["maxX"] - send["x"], receive["maxX"] - receive["x"]))
        right = self.column_right(s, where)
        self.assertTrue(right < s["arrowsRight"] <= edges["maxX"] + 0.5,
                        f"{where}: no arrow column right of the fields and left of the checkbox's edge")
        send_mid, receive_mid = right - width - 8 - width / 2, right - width / 2
        self.assertEqual(receive["maxX"], right, f"{where}: 'Receive' does not end where the fields above end")
        for header, mid in ((send, send_mid), (receive, receive_mid)):
            self.assertLessEqual(abs(header["midX"] - mid), 0.5, f"{where}: {header['view']} is not centred in its column")
        for name in names:
            self.assertEqual(right - 2 * width - 16, name["maxX"], f"{where}: a name does not end 8 pt before the Send column")
            line = [l for l in lines if l["y"] == name["y"]]
            self.assertEqual(sorted(l["view"] for l in line), ["accountSharingAccountName", "accountSharingReceive",
                                                              "accountSharingSend"], f"{where}: a line is not name, Send, Receive")
        for box in by["accountSharingSend"]:
            self.assertLessEqual(abs(box["midX"] - send_mid), 0.5, f"{where}: a Send checkbox is off its column")
        for box in by["accountSharingReceive"]:
            self.assertLessEqual(abs(box["midX"] - receive_mid), 0.5, f"{where}: a Receive checkbox is off its column")

    def check_right_edge(self, s: dict, where: str) -> None:
        """The sharing checkbox, and the section's lines with it, end where General's other
        controls end once the window is fitted to them: the right edge of the permissions row,
        which spans the pane less its margins, within the point the fit rounds up."""
        box = next(v for v in s["section"] if v["view"] == "accountSharingCheckbox")["frame"]
        right = s["permissions"]["x"] + s["permissions"]["w"]
        self.assertLessEqual(abs(box["x"] + box["w"] - right), 1,
                             f"{where}: the sharing checkbox ends at {box['x'] + box['w']:g}, General's controls at {right:g}")

    def check_xib_spacing(self, s: dict, where: str) -> None:
        # Top down, line by line: the label, the checkbox, then the lines of the list (headers,
        # accounts, and the note while it shows); the views of one line share their frame.
        views = [v for v in s["section"] if not v["hidden"]]
        rows: dict = {}
        for v in views:
            rows.setdefault(v["frame"]["y"], []).append(v)
        for y, line in rows.items():
            self.assertEqual({v["frame"]["h"] for v in line}.__len__(), 1, f"{where}: views of one line differ in height: {line}")
        ordered = sorted(rows.values(), key=lambda line: -(line[0]["frame"]["y"] + line[0]["frame"]["h"]))
        gaps = [p[0]["frame"]["y"] - (n[0]["frame"]["y"] + n[0]["frame"]["h"]) for p, n in zip(ordered, ordered[1:])]
        self.assertEqual(s["labelBelowLowest"], 16, f"{where}: the label is not 16 pt below the Saving section")
        self.assertEqual(gaps, [8] + [6] * (len(ordered) - 2), f"{where}: label -> checkbox 8 pt, line -> line 6 pt")
        self.assertEqual(s["belowTheSection"], 16, f"{where}: the permissions row is not 16 pt below the section")
        self.assertEqual(s["permissions"]["y"], 8, f"{where}: the permissions row left its place at the bottom")
        self.assertTrue(s["inContent"] and s["inBox"] and s["boxInContent"], f"{where}: {s['section']}")
        self.check_right_edge(s, where)
        self.check_list_edges(s, where)

    def placed(self, accounts: int, order: str, values: str, xib: bool = False, note: bool = False,
               unread: bool = False) -> list[dict]:
        if self.nib_source is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        run = subprocess.run([str(self.binary), str(self.bundle), "placed", self.builders, str(accounts), order, values,
                              *(["note"] if note else []), *(["unread"] if unread else [])],
                             cwd=ROOT, text=True, capture_output=True, timeout=90,
                             env=self.xib_env() if xib else None)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertTrue(reports, run.stdout[-1500:] + run.stderr[-1500:])
        steps = json.loads(reports[-1])["steps"]
        print(f"\nplaced {accounts} {order} {values}: " + "; ".join(
            f"{s['step']}: label {s['labelBelowLowest']:g} below, {s['aboveTheRow']:g} above the row, "
            f"inside {s['inContent'] and s['inBox'] and s['boxInContent']}" for s in steps))
        return steps

    def check_note(self, steps: list[dict], where: str, row_gap: float) -> None:
        """The note steps of a "placed ... note" run against the hidden note before them."""
        hidden = steps[STEPS.index("reopened")]
        line = hidden["note"]["frame"]["h"] + row_gap
        self.assertTrue(hidden["note"]["hidden"], f"{where}: a note shows before any error")
        self.assertEqual(hidden["belowTheSection"], 16, f"{where}: hidden note, the permissions row is not 16 pt below the list")
        for s in steps[len(STEPS):]:
            w = f"{where}, {s['step']}"
            self.check_list_edges(s, w)
            self.assertEqual(s["permissions"]["y"], 8, f"{w}: the permissions row left its place at the bottom")
            self.assertTrue(s["inContent"] and s["inBox"] and s["boxInContent"], f"{w}: {s['section']}")
            if s["step"].startswith("note shown"):
                note = s["note"]["frame"]
                self.assertFalse(s["note"]["hidden"], w)
                self.assertTrue(s["note"]["text"].startswith("Sharing is unavailable: "), w)
                self.assertEqual(s["lastLine"] - (note["y"] + note["h"]), row_gap, f"{w}: the note is not one row gap below the list")
                self.assertEqual(s["belowTheSection"], 16, f"{w}: the permissions row is not 16 pt below the note")
                self.assertEqual(s["paneHeight"] - hidden["paneHeight"], line, f"{w}: the pane did not grow by the note's line")
                self.assertEqual(s["contentHeight"] - hidden["contentHeight"], line, f"{w}: the window does not follow")
            else:
                self.assertTrue(s["note"]["hidden"], w)
                self.assertEqual((s["paneHeight"], s["contentHeight"], s["belowTheSection"]),
                                 (hidden["paneHeight"], hidden["contentHeight"], 16), f"{w}: the pane did not give the line back")
                self.assertEqual([v["frame"] for v in s["section"]], [v["frame"] for v in hidden["section"]], w)

    def check_placed(self, order: str) -> None:
        widths = set()
        for accounts in (0, 1, 2, 3, 6):
            with self.subTest(accounts=accounts):
                steps = self.placed(accounts, order, "stored", note=True)
                widths |= {s["windowWidth"] for s in steps}
                self.assertEqual([s["step"] for s in steps], STEPS + NOTE_STEPS)
                # master's NIB: the rows 20 pt apart, 4 pt between their alignment rects
                self.check_note(steps, f"NIB, {accounts} other accounts, {order}", 4)
                for s in steps[:len(STEPS)]:
                    where = f"{accounts} other accounts, {order}, {s['step']}"
                    self.assertEqual(s["arrowsShown"], 3, f"{where}: the changed numbers show no Restore Default arrows")
                    self.assertEqual(s["selected"], "net.sf.jumpcut.preferences.general.tiff", where)
                    self.assertEqual((s["rows"], s["none"]), (accounts, accounts == 0), where)
                    self.assertEqual(s["labelBelowLowest"], 16,
                                     f"{where}: 'Other accounts on this Mac:' is not 16 pt below the Saving section")
                    self.assertEqual(s["belowTheSection"], 16,
                                     f"{where}: the permissions row is not 16 pt below the section")
                    self.assertGreaterEqual(s["aboveTheRow"], 0,
                                            f"{where}: the section reaches into the Check Accessibility Permissions row")
                    self.assertTrue(s["inContent"], f"{where}: part of the section is outside the window: {s['section']}")
                    self.assertTrue(s["inBox"], f"{where}: part of the section is outside the General box: {s['section']}")
                    self.assertTrue(s["boxInContent"], f"{where}: the window does not show the whole General pane")
                    self.assertEqual((s["permissions"]["y"], s["permissionsInContent"]["y"]), (8, 8),
                                     f"{where}: the permissions row left its place at the bottom")
                    self.check_right_edge(s, where)
                    self.check_list_edges(s, where)
        if not widths:
            self.skipTest("nothing placed (no NIB fixture)")
        self.assertEqual(len(widths), 1, f"the window's width changes with the account list: {sorted(widths)}")

    def check_nib_place(self, s: dict, where: str) -> None:
        self.assertEqual(s["labelBelowLowest"], 16, f"{where}: the label is not 16 pt below the Saving section")
        self.assertEqual(s["belowTheSection"], 16, f"{where}: the permissions row is not 16 pt below the section")
        self.assertGreaterEqual(s["aboveTheRow"], 0, f"{where}: the section reaches into the permissions row")
        self.assertTrue(s["inContent"] and s["inBox"] and s["boxInContent"], f"{where}: {s['section']}")
        self.check_right_edge(s, where)
        self.assertEqual((s["permissions"]["y"], s["permissionsInContent"]["y"]), (8, 8),
                         f"{where}: the permissions row left its place at the bottom")
        self.check_right_edge(s, where)
        self.check_list_edges(s, where)

    def test_accounts_that_cannot_be_read_are_listed_when_the_window_opens_again(self) -> None:
        for accounts in (0, 3):
            for order in ("builders-first", "prefs-first"):
                for xib in (False, True):
                    with self.subTest(accounts=accounts, order=order, xib=xib):
                        where = f"{'XIB' if xib else 'NIB'}, {accounts} other accounts, {order}"
                        steps = self.placed(accounts, order, "stored", xib=xib, unread=True)
                        self.assertEqual([s["step"] for s in steps], STEPS + READ_STEPS[1:])
                        built = self.placed(accounts, order, "stored", xib=xib, note=True)
                        shown = built[[s["step"] for s in built].index("note shown")]
                        for s in steps:
                            w = f"{where}, {s['step']}"
                            read = s["step"] in READ_STEPS
                            self.assertEqual((s["rows"], s["none"], s["unread"]),
                                             (accounts if read else 0, read and accounts == 0, not read),
                                             f"{w}: the accounts are not listed once they can be read" if read
                                             else f"{w}: a failed lookup is not said as such")
                            if not read:
                                self.assertEqual(s["unreadText"], UNREAD, w)
                            self.assertFalse(s["note"]["hidden"], f"{w}: the note is gone")
                            if xib:
                                self.check_xib_spacing(s, w)
                            else:
                                self.check_nib_place(s, w)
                            if read:
                                self.assertEqual([v["frame"] for v in s["section"]], [v["frame"] for v in shown["section"]],
                                                 f"{w}: the section is not as when it is built with the accounts")
                                self.assertEqual((s["paneHeight"], s["contentHeight"]), (shown["paneHeight"], shown["contentHeight"]),
                                                 f"{w}: the pane or the window is not as tall as when built with the accounts")

    def test_section_stays_in_place_with_restore_default_arrows_shown(self) -> None:
        self.check_placed("builders-first")

    def test_section_stays_in_place_when_ukprefspanel_wakes_first(self) -> None:
        self.check_placed("prefs-first")

    def test_section_follows_the_xibs_spacing(self) -> None:
        for accounts in (0, 1, 2, 3, 6):
            for order in ("builders-first", "prefs-first"):
                for values in ("stored", "factory"):
                    with self.subTest(accounts=accounts, order=order, values=values):
                        steps = self.placed(accounts, order, values, xib=True, note=True)
                        self.assertEqual([s["step"] for s in steps], STEPS + NOTE_STEPS)
                        for s in steps:
                            self.check_xib_spacing(s, f"XIB, {accounts} other accounts, {order}, {values}, {s['step']}")
                        self.check_note(steps, f"XIB, {accounts} other accounts, {order}, {values}", 6)

    def test_hidden_note_takes_no_room_with_factory_values_on_masters_nib(self) -> None:
        for accounts in (0, 1, 2, 3, 6):
            with self.subTest(accounts=accounts):
                steps = self.placed(accounts, "builders-first", "factory", note=True)
                self.assertEqual({s["arrowsShown"] for s in steps}, {0}, "factory values show an arrow")
                self.check_note(steps, f"NIB, {accounts} other accounts, factory", 4)

    def test_shown_restore_default_arrows_do_not_move_the_section(self) -> None:
        for accounts in (0, 3):
            with self.subTest(accounts=accounts):
                stored = self.placed(accounts, "builders-first", "stored")
                factory = self.placed(accounts, "builders-first", "factory")
                self.assertEqual({s["arrowsShown"] for s in factory}, {0}, "factory values show an arrow")
                self.assertEqual([s["section"] for s in stored], [s["section"] for s in factory],
                                 "the section is elsewhere when the number fields show their Restore Default arrows")

    def test_checkbox_is_bound_off_by_default_and_toggles_sharing(self) -> None:
        off, on = self.section("off"), self.section("on")
        self.assertEqual(off["state"], 0)
        self.assertEqual(on["state"], 1)
        self.assertEqual(off["bindingKeyPath"], "values.shareClippingsAcrossAccounts")
        self.assertTrue(off["bindingToDefaults"])
        self.assertEqual(off["action"], "toggleShareClippingsAcrossAccounts:")
        self.assertTrue(off["targetIsController"])

    def test_tooltips_and_voiceover_labels(self) -> None:
        r = self.section("off")
        self.assertEqual(r["tooltip"], TOOLTIP)
        self.assertEqual(r["axControl"], TITLE)
        self.assertEqual(r["axCell"], TITLE)
        texts = [r["tooltip"]]
        for row in r["rows"]:
            name = row["title"]
            self.assertEqual((row["send"]["axControl"], row["send"]["axCell"]), (f"Send to {name}",) * 2,
                             "VoiceOver does not say what the Send checkbox does")
            self.assertEqual((row["receive"]["axControl"], row["receive"]["axCell"]), (f"Receive from {name}",) * 2,
                             "VoiceOver does not say what the Receive checkbox does")
            self.assertEqual(row["send"]["tooltip"], send_tooltip(name))
            self.assertEqual(row["receive"]["tooltip"], receive_tooltip(name))
            texts += [row["send"]["tooltip"], row["receive"]["tooltip"]]
        for text in texts:
            self.assertNotIn("\u2014", text)

    def test_key_view_order_runs_through_the_checkbox_and_the_accounts(self) -> None:
        r = self.section("off")
        order = r["keyOrder"]
        self.assertIn("share", order)
        self.assertIn(r["favoritesTitle"], order)
        self.assertIn("Check Accessibility Permissions", order)
        share = order.index("share")
        self.assertEqual(order[share - 1], r["favoritesTitle"], order)
        self.assertEqual(order[share + 1:share + 6], ["send:Account A", "receive:Account A", "send:Account B", "receive:Account B",
                                                      "Check Accessibility Permissions"], order)

        none = self.section("none")["keyOrder"]
        self.assertEqual(none[none.index("share") + 1], "Check Accessibility Permissions", none)


if __name__ == "__main__":
    unittest.main()
