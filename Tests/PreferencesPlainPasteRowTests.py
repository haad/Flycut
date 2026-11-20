#!/usr/bin/env python3
"""Regression tests for the "Paste as Plain Text" row of the Hotkeys pane.

The NIB gives the Hotkeys pane one recorder, the bezel's. The plain-text hotkey's row is built
in code under it (-buildPlainPasteHotkeyRow), like the search hotkey's row, and laid out with
the bezel's row by the pane's rules: the labels at the 16 pt margin in the labels' font and
centred on their recorders, the recorders on one column 8 pt after the longer label, each
ending 4 pt before its Restore Default arrow, 6 pt between the rows; the help text 6 pt under
both, from the recorders' column; 16 pt above and below; the pane grows to fit. A recorder refuses a
combination that another Flycut hotkey uses, and so does Restore Default. The help text of
MainMenu.xib speaks of both rows;
put into the NIB's field, it comes through the builders as written.

Runs against the production MainMenu NIB (Tests/Fixtures/PreferencesNibFixture.py; master's
compiled NIB via FLYCUT_TEST_RESOURCE_BUNDLE), the production AppController builders and
ShortcutRecorder; user defaults in memory ("stored" is read from their stored values, never
through -objectForKey:, which also answers from the registered defaults), no hotkey registered,
Accessibility counted as granted, NSBeep counted, the window never on screen.
The XIB text cases parse the tree's English.lproj/MainMenu.xib (no Xcode needed).
An arrow whose default another Flycut hotkey uses stays in view, dimmed, with the reason in
its tooltip; help.md says so.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tests" / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

XIB = ROOT / "English.lproj" / "MainMenu.xib"
# The Hotkeys pane's help text in MainMenu.xib, whole: it applies to both rows.
HOTKEYS_HELP = ("To change a hotkey, click its recorder and type another. To clear it, click the X. "
                "To go back to the default, click the arrow that appears next to a changed hotkey. "
                "Use of a hotkey claimed by another application can lead to unpredictable results.")
# help.md's paragraph on the Restore Default arrows, whole.
HELP_RESTORE = ('A setting that differs from its factory value shows a small round arrow next to it (tooltip '
                '"Restore Default"). Click the arrow to go back to the default; for the two "Save \u2026 to:" '
                'folders that is the Desktop. The arrow disappears once the default is back. While another '
                'Flycut hotkey uses the default of a hotkey, the arrow next to that hotkey is dimmed and its '
                'tooltip says why; give the other hotkey a different combination first.')


def xib_hotkeys_help() -> str:
    """The text field right of the Hotkeys pane's recorder in MainMenu.xib: its help text."""
    found = []
    for subviews in ET.parse(XIB).getroot().iter("subviews"):
        recorders = [v for v in subviews if v.get("customClass") == "SRRecorderControl"]
        if len(recorders) != 1:
            continue
        rect = recorders[0].find("rect")
        right = float(rect.get("x")) + float(rect.get("width"))
        for view in subviews:
            frame = view.find("rect")
            if view.tag == "textField" and frame is not None and float(frame.get("x")) >= right:
                cell = view.find("textFieldCell")
                title = cell.get("title")
                if title is None:
                    title = cell.find("string[@key='title']").text
                found.append(title)
    if len(found) != 1:
        raise AssertionError(f"expected one help text next to the Hotkeys recorder, found {len(found)}")
    return found[0]

FIXTURE = r'''
#import <Carbon/Carbon.h>
#import "SRRecorderControl.h"
#import "SRCommon.h"
#import "SGKeyCombo.h"
#import "FlycutHotkeyDefaults.h"
#import "FlycutPlainPaste.h"

@interface AppController (PlainPasteRowTest)
- (void)loadHotkeyRecorderCombos;
- (void)updateRestoreDefaultButtons;
- (IBAction)restoreDefault:(id)sender;
- (void)updatePlainPasteHotKeyRegistration;
@end

static int beeps;
void FCTestNSBeep(void) { beeps++; }

// What the user domain holds: FCMemoryDefaults' stored values, never the registered default.
static id Stored(NSString *key)
{
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    if (ivar == NULL) abort();
    return [(NSDictionary *)object_getIvar([NSUserDefaults standardUserDefaults], ivar) objectForKey:key];
}

static NSView *FindIn(NSView *root, BOOL (^match)(NSView *))
{
    for (NSView *view in [root subviews]) {
        if (match(view)) return view;
        NSView *found = FindIn(view, match);
        if (found) return found;
    }
    return nil;
}

static NSTextField *Label(NSView *pane, NSString *text)
{
    return (NSTextField *)FindIn(pane, ^BOOL(NSView *v) {
        return [v isKindOfClass:[NSTextField class]] && [[[(NSTextField *)v stringValue] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] isEqualToString:text];
    });
}

static NSButton *Arrow(NSView *pane, NSString *identifier)
{
    return (NSButton *)FindIn(pane, ^BOOL(NSView *v) { return [[v identifier] isEqualToString:identifier]; });
}

static NSTextField *HelpText(NSView *pane)
{
    return (NSTextField *)FindIn(pane, ^BOOL(NSView *v) {
        return [v isKindOfClass:[NSTextField class]] && [[(NSTextField *)v stringValue] hasPrefix:@"To change "];
    });
}

static BOOL Near(CGFloat a, CGFloat b) { return fabs(a - b) <= 1.0; }

static NSString *const TakenToolTip = @"The default is used by another Flycut hotkey";

// An arrow in view that can be clicked shows the plain tooltip.
static BOOL ClickableArrow(NSButton *arrow)
{
    return arrow != nil && ![arrow isHidden] && [arrow isEnabled] && [[arrow toolTip] isEqualToString:@"Restore Default"];
}

// FCMemoryDefaults answers -volatileDomainForName: with the process's empty registration
// domain; the Restore Default arrows read the factory hotkeys from there.
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

// An AppController instance variable, nil if the class has none (no exception, so a tree
// without the row fails on an assertion).
static id ControllerIvar(const char *name)
{
    Ivar ivar = class_getInstanceVariable([AppController class], name);
    return ivar ? object_getIvar(controller, ivar) : nil;
}

static NSDictionary *Value(KeyCombo combo) { return FlycutHotkeyValue(combo.code, combo.flags); }

// The NIB's own geometry, read before the builders run: the label's offset from the
// bezel's recorder and the recorder's distance from the pane's top.
static CGFloat nibLabelOffset = NAN, nibTopMargin = NAN;
static void ReadNibGeometry(void)
{
    SRRecorderControl *main = ControllerIvar("mainRecorder");
    NSView *pane = [main superview];
    for (NSView *view in [pane subviews])
        if ([view isKindOfClass:[NSTextField class]] && NSMaxX([view frame]) <= NSMinX([main frame]))
            nibLabelOffset = NSMidY([view frame]) - NSMidY([main frame]);
    nibTopMargin = NSHeight([pane bounds]) - NSMaxY([main frame]);
}

// Mode "xib-help": MainMenu.xib's help text (argv[4]) goes into the NIB's help field before
// the builders run, as an Xcode build of the XIB would load it.
static NSString *xibHelp;
static BOOL xibHelpSet;
static void ReadNibGeometryWithXibHelp(void)
{
    ReadNibGeometry();
    SRRecorderControl *main = ControllerIvar("mainRecorder");
    for (NSView *view in [[main superview] subviews])
        if ([view isKindOfClass:[NSTextField class]] && NSMinX([view frame]) >= NSMaxX([main frame])) {
            [(NSTextField *)view setStringValue:xibHelp];
            xibHelpSet = YES;
        }
}

static int Prepare(int argc, const char **argv, NSDictionary *stored)
{
    BeforeBuilders = xibHelp ? ReadNibGeometryWithXibHelp : ReadNibGeometry;
    if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 6;
    for (NSString *key in stored) [[NSUserDefaults standardUserDefaults] setObject:stored[key] forKey:key];
    int failed = LoadNib(argc, argv);
    if (failed) return failed;
    // Accessibility counts as granted, as if asked at an activation (the fixture has none).
    Ivar trusted = class_getInstanceVariable([AppController class], "plainPasteAccessibilityTrusted");
    if (trusted) *(BOOL *)((char *)controller + ivar_getOffset(trusted)) = YES;
    [controller loadHotkeyRecorderCombos];
    ChangePane(hotkeysPane);
    return 0;
}

static int Row(void)
{
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view];
    SRRecorderControl *main = ControllerIvar("mainRecorder"), *plain = ControllerIvar("plainPasteRecorder");
    if (plain == nil || [plain superview] != [main superview]) return 20;
    NSView *box = [main superview];
    NSTextField *mainLabel = Label(pane, @"Main Hotkey:"), *plainLabel = Label(pane, @"Paste as Plain Text:");
    NSTextField *help = HelpText(pane);
    NSButton *mainArrow = Arrow(pane, @"restoreDefaultMainHotkey"), *plainArrow = Arrow(pane, @"restoreDefaultPlainPasteHotkey");
    if (!mainLabel || !plainLabel || !help || !mainArrow || !plainArrow) return 21;
    if ([plainLabel superview] != box || [plainArrow superview] != box || [help superview] != box) return 22;
    Emit(@{@"main": NSStringFromRect([main frame]), @"plain": NSStringFromRect([plain frame]),
           @"mainLabel": NSStringFromRect([mainLabel frame]), @"plainLabel": NSStringFromRect([plainLabel frame]),
           @"help": NSStringFromRect([help frame]), @"box": NSStringFromRect([box bounds]),
           @"mainArrow": NSStringFromRect([mainArrow frame]), @"plainArrow": NSStringFromRect([plainArrow frame])});
    // The label reads like the NIB's and fits in full.
    if (![[plainLabel font] isEqual:[mainLabel font]] || ![[plainLabel textColor] isEqual:[mainLabel textColor]]) return 23;
    if (NSWidth([plainLabel frame]) < ceil([plainLabel fittingSize].width) || NSWidth([mainLabel frame]) < ceil([mainLabel fittingSize].width)) return 24;
    // Columns: labels, recorders, arrows.
    if (!Near(NSMinX([plainLabel frame]), NSMinX([mainLabel frame]))) return 25;
    if (!Near(NSMinX([plain frame]), NSMinX([main frame])) || !Near(NSWidth([plain frame]), NSWidth([main frame])) ||
        !Near(NSHeight([plain frame]), NSHeight([main frame]))) return 26;
    if (!Near(NSMinX([plainArrow frame]), NSMinX([mainArrow frame]))) return 27;
    // The recorders start 8 pt after the longer label's text (alignment rects).
    NSRect mainEdges = [mainLabel alignmentRectForFrame:[mainLabel frame]], plainEdges = [plainLabel alignmentRectForFrame:[plainLabel frame]];
    NSRect helpEdges = [help alignmentRectForFrame:[help frame]];
    if (!Near(NSMinX([main frame]), MAX(NSMaxX(mainEdges), NSMaxX(plainEdges)) + 8)) {
        fprintf(stderr, "recorders at %.1f, labels end at %.1f and %.1f\n", NSMinX([main frame]), NSMaxX(mainEdges), NSMaxX(plainEdges));
        return 28;
    }
    // Each label and each arrow is centred on its recorder, the second row is 6 pt under the
    // first, and the first is 16 pt under the pane's top.
    if (!Near(NSMidY(mainEdges), NSMidY([main frame])) || !Near(NSMidY(plainEdges), NSMidY([plain frame]))) {
        fprintf(stderr, "label centres %.1f and %.1f, recorders %.1f and %.1f\n", NSMidY(mainEdges), NSMidY(plainEdges),
                NSMidY([main frame]), NSMidY([plain frame]));
        return 29;
    }
    if (!Near(NSHeight([box bounds]) - NSMaxY([main frame]), 16)) return 43;
    if (!Near(NSMidY([plainArrow frame]), NSMidY([plain frame]))) return 30;
    CGFloat rowGap = NSMinY([main frame]) - NSMaxY([plain frame]);
    if (!Near(rowGap, 6)) { fprintf(stderr, "row gap %.1f\n", rowGap); return 31; }
    // The help text is 6 pt under both rows, from the recorders' column, in full.
    CGFloat helpGap = NSMinY([plain frame]) - NSMaxY(helpEdges);
    if (!Near(helpGap, 6)) { fprintf(stderr, "help gap %.1f\n", helpGap); return 32; }
    if (!Near(NSMinX(helpEdges), NSMinX([main frame]))) return 33;
    if (NSHeight([help frame]) < ceil([[help cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([help frame]), CGFLOAT_MAX)].height)) return 34;
    // Everything inside the pane, with room below.
    for (NSView *view in @[main, plain, mainLabel, plainLabel, help, mainArrow, plainArrow])
        if (!NSContainsRect(NSInsetRect([box bounds], 0, 0), [view frame])) { fprintf(stderr, "%s outside\n", [NSStringFromRect([view frame]) UTF8String]); return 35; }
    if (!Near(NSMinY(helpEdges), 16)) { fprintf(stderr, "help ends %.1f pt above the pane's bottom\n", NSMinY(helpEdges)); return 36; }
    // No two of them overlap.
    NSArray *views = @[main, plain, mainLabel, plainLabel, help, mainArrow, plainArrow];
    for (NSUInteger i = 0; i < [views count]; i++)
        for (NSUInteger j = i + 1; j < [views count]; j++)
            if (NSIntersectsRect([views[i] frame], [views[j] frame])) { fprintf(stderr, "views %lu and %lu overlap\n", (unsigned long)i, (unsigned long)j); return 37; }
    // The window shows the whole pane (UKPrefsPanel sizes it to the box).
    NSView *outer = [box superview];
    if (!Near(NSHeight([outer frame]), NSHeight([[window contentView] frame]))) {
        fprintf(stderr, "box %.1f, window content %.1f\n", NSHeight([outer frame]), NSHeight([[window contentView] frame]));
        return 38;
    }
    // VoiceOver and Tab.
    if (![[plain accessibilityLabel] isEqualToString:@"Paste as plain text hotkey"] || [[plain accessibilityHelp] length] == 0) return 39;
    if (![[plainArrow accessibilityLabel] isEqualToString:@"Restore default paste as plain text hotkey"]) return 40;
    // Tab from the bezel's recorder goes to this one next (the arrows are hidden at the factory
    // values). UKPrefsPanel recalculated the loop as the pane came up; offscreen no view can
    // become key, so the loop is walked by -nextKeyView and -acceptsFirstResponder.
    NSView *next = [main nextKeyView];
    for (int i = 0; i < 50 && next != nil && next != main; i++) {
        if ([next window] == window && ![next isHiddenOrHasHiddenAncestor] && [next acceptsFirstResponder]) break;
        next = [next nextKeyView];
    }
    if (next != plain) { fprintf(stderr, "Tab from the main recorder goes to %s\n", [[next description] UTF8String]); return 41; }
    return 0;
}

static int Shows(BOOL stored)
{
    SRRecorderControl *plain = ControllerIvar("plainPasteRecorder");
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view];
    NSButton *arrow = Arrow(pane, @"restoreDefaultPlainPasteHotkey");
    [controller updateRestoreDefaultButtons];
    NSDictionary *expected = stored ? FlycutHotkeyValue(9, NSEventModifierFlagShift | NSEventModifierFlagCommand) : FlycutPlainPasteHotkeyDefault();
    if (![Value([plain keyCombo]) isEqual:expected]) { fprintf(stderr, "shows %s\n", [[Value([plain keyCombo]) description] UTF8String]); return 50; }
    if ([arrow isHidden] == stored) { fprintf(stderr, "arrow hidden %d\n", [arrow isHidden]); return 51; }
    return 0;
}

static int Record(void)
{
    SRRecorderControl *plain = ControllerIvar("plainPasteRecorder");
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    KeyCombo shiftCommandV = SRMakeKeyCombo(9, NSEventModifierFlagShift | NSEventModifierFlagCommand);
    [plain setKeyCombo:shiftCommandV];
    [controller shortcutRecorder:plain keyComboDidChange:shiftCommandV];
    if (![Stored(FlycutPlainPasteHotkeyKey) isEqual:Value(shiftCommandV)]) return 60;
    SGHotKey *hotKey = ControllerIvar("plainPasteHotKey");
    if (hotKey == nil || [[hotKey keyCombo] keyCode] != 9 || [[hotKey keyCombo] modifiers] != (shiftKey | cmdKey)) return 61;
    // Clearing the field stores no hotkey and releases it.
    KeyCombo none = SRMakeKeyCombo(ShortcutRecorderEmptyCode, ShortcutRecorderEmptyFlags);
    [plain setKeyCombo:none];
    [controller shortcutRecorder:plain keyComboDidChange:none];
    if ([[Stored(FlycutPlainPasteHotkeyKey) objectForKey:@"keyCode"] integerValue] != -1) return 62;
    if (ControllerIvar("plainPasteHotKey") != nil) return 63;
    // The factory combination again: nothing stored, the registered default applies.
    NSDictionary *factory = FlycutPlainPasteHotkeyDefault();
    KeyCombo back = SRMakeKeyCombo([factory[@"keyCode"] integerValue], [factory[@"modifierFlags"] unsignedIntegerValue]);
    [plain setKeyCombo:back];
    [controller shortcutRecorder:plain keyComboDidChange:back];
    if (Stored(FlycutPlainPasteHotkeyKey) != nil) { fprintf(stderr, "the factory hotkey was stored\n"); return 64; }
    if (![[defaults objectForKey:FlycutPlainPasteHotkeyKey] isEqual:factory]) return 59;
    if (ControllerIvar("plainPasteHotKey") == nil) return 65;
    return 0;
}

static int Restore(void)
{
    SRRecorderControl *plain = ControllerIvar("plainPasteRecorder");
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view];
    NSButton *arrow = Arrow(pane, @"restoreDefaultPlainPasteHotkey");
    [controller updateRestoreDefaultButtons];
    if (!ClickableArrow(arrow)) return 70;
    [controller restoreDefault:arrow];
    if (![Value([plain keyCombo]) isEqual:FlycutPlainPasteHotkeyDefault()]) { fprintf(stderr, "restored to %s\n", [[Value([plain keyCombo]) description] UTF8String]); return 71; }
    if (Stored(FlycutPlainPasteHotkeyKey) != nil) return 72;
    if (![arrow isHidden]) return 73;
    SGHotKey *hotKey = ControllerIvar("plainPasteHotKey");
    if (hotKey == nil || [[hotKey keyCombo] modifiers] != (optionKey | shiftKey | cmdKey)) return 74;
    return 0;
}

// While another Flycut hotkey uses its factory combination, a Restore Default arrow stays in
// view, dimmed, and its tooltip says why; the other arrow can still be clicked. Pressed anyway
// (-restoreDefault:), it refuses, as the recorder refuses a recorded one: neither hotkey
// changes, nothing is stored, the alert sound plays and the arrow stays dimmed.
static int RestoreTaken(NSString *identifier)
{
    SRRecorderControl *main = ControllerIvar("mainRecorder"), *plain = ControllerIvar("plainPasteRecorder");
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view];
    NSButton *arrow = Arrow(pane, identifier);
    NSButton *other = Arrow(pane, [identifier isEqualToString:@"restoreDefaultMainHotkey"] ? @"restoreDefaultPlainPasteHotkey"
                                                                                       : @"restoreDefaultMainHotkey");
    [controller updatePlainPasteHotKeyRegistration];
    [controller updateRestoreDefaultButtons];
    if (arrow == nil || [arrow isHidden]) return 75;
    if ([arrow isEnabled]) { fprintf(stderr, "the arrow can be clicked although its default is taken\n"); return 94; }
    if (![[arrow toolTip] isEqualToString:TakenToolTip]) { fprintf(stderr, "tooltip %s\n", [[arrow toolTip] UTF8String]); return 95; }
    if (!ClickableArrow(other)) { fprintf(stderr, "the other arrow is not clickable\n"); return 91; }
    SGHotKey *registered = ControllerIvar("plainPasteHotKey");
    if (registered == nil) return 92;
    NSDictionary *mainBefore = Value([main keyCombo]), *plainBefore = Value([plain keyCombo]);
    id storedMain = Stored(FlycutMainHotkeyKey), storedPlain = Stored(FlycutPlainPasteHotkeyKey);
    [controller restoreDefault:arrow];
    if (![Value([main keyCombo]) isEqual:mainBefore] || ![Value([plain keyCombo]) isEqual:plainBefore]) {
        fprintf(stderr, "restored over another Flycut hotkey: main %s, plain %s\n", [[Value([main keyCombo]) description] UTF8String],
                [[Value([plain keyCombo]) description] UTF8String]);
        return 76;
    }
    if (![Stored(FlycutMainHotkeyKey) isEqual:storedMain] || ![Stored(FlycutPlainPasteHotkeyKey) isEqual:storedPlain]) return 77;
    if (beeps != 1) { fprintf(stderr, "%d beeps\n", beeps); return 78; }
    [controller updateRestoreDefaultButtons];
    if ([arrow isHidden] || [arrow isEnabled] || ![[arrow toolTip] isEqualToString:TakenToolTip]) return 79;
    SGHotKey *after = ControllerIvar("plainPasteHotKey");
    if (after == nil || [[after keyCombo] keyCode] != [[registered keyCombo] keyCode] ||
        [[after keyCombo] modifiers] != [[registered keyCombo] modifiers]) return 93;
    return 0;
}

// The bezel and Paste as Plain Text swapped: the bezel's arrow is dimmed until Paste as Plain
// Text moves to its own default; then it can be clicked and restores the bezel's.
static int RestoreFreed(void)
{
    SRRecorderControl *main = ControllerIvar("mainRecorder"), *plain = ControllerIvar("plainPasteRecorder");
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view];
    NSButton *mainArrow = Arrow(pane, @"restoreDefaultMainHotkey");
    [controller updateRestoreDefaultButtons];
    if (mainArrow == nil || [mainArrow isHidden] || [mainArrow isEnabled]) return 96;
    NSDictionary *factory = FlycutPlainPasteHotkeyDefault();
    KeyCombo own = SRMakeKeyCombo([factory[@"keyCode"] integerValue], [factory[@"modifierFlags"] unsignedIntegerValue]);
    [plain setKeyCombo:own];
    [controller shortcutRecorder:plain keyComboDidChange:own];
    if (!ClickableArrow(mainArrow)) {
        fprintf(stderr, "freed: hidden %d enabled %d tooltip %s\n", [mainArrow isHidden], [mainArrow isEnabled], [[mainArrow toolTip] UTF8String]);
        return 97;
    }
    [controller restoreDefault:mainArrow];
    if (![Value([main keyCombo]) isEqual:FlycutBezelHotkeyDefault()] || Stored(FlycutMainHotkeyKey) != nil || beeps != 0) return 98;
    if (![mainArrow isHidden]) return 99;
    return 0;
}

static int Taken(void)
{
    SRRecorderControl *main = ControllerIvar("mainRecorder"), *plain = ControllerIvar("plainPasteRecorder");
    SRRecorderControl *search = ControllerIvar("searchRecorder");
    if (search == nil) return 80;
    KeyCombo mainCombo = [main keyCombo], plainCombo = [plain keyCombo], searchCombo = [search keyCombo];
    NSString *reason = nil;
    if (![controller shortcutRecorder:plain isKeyCode:mainCombo.code andFlagsTaken:mainCombo.flags reason:&reason]) return 81;
    if (![reason isEqualToString:@"it is Flycut's Main Hotkey"]) { fprintf(stderr, "reason %s\n", [reason UTF8String]); return 82; }
    reason = nil;
    if (![controller shortcutRecorder:main isKeyCode:plainCombo.code andFlagsTaken:plainCombo.flags reason:&reason]) return 83;
    if (![reason isEqualToString:@"it is Flycut's Paste as Plain Text hotkey"]) return 84;
    reason = nil;
    if (![controller shortcutRecorder:plain isKeyCode:searchCombo.code andFlagsTaken:searchCombo.flags reason:&reason]) return 85;
    if (![reason isEqualToString:@"it is Flycut's search hotkey"]) return 86;
    if (![controller shortcutRecorder:search isKeyCode:plainCombo.code andFlagsTaken:plainCombo.flags reason:NULL]) return 87;
    // A recorder's own combination, and one no Flycut hotkey uses, are free.
    if ([controller shortcutRecorder:plain isKeyCode:plainCombo.code andFlagsTaken:plainCombo.flags reason:NULL]) return 88;
    if ([controller shortcutRecorder:plain isKeyCode:11 andFlagsTaken:NSEventModifierFlagControl | NSEventModifierFlagCommand reason:NULL]) return 89;
    // Only the four modifiers count.
    if (![controller shortcutRecorder:plain isKeyCode:mainCombo.code andFlagsTaken:mainCombo.flags | NSEventModifierFlagFunction reason:NULL]) return 90;
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 4) return 2;
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        NSDictionary *custom = @{FlycutPlainPasteHotkeyKey: FlycutHotkeyValue(9, NSEventModifierFlagShift | NSEventModifierFlagCommand)};
        BOOL stored = [mode isEqualToString:@"shows-stored"] || [mode isEqualToString:@"restore"];
        if ([mode isEqualToString:@"xib-help"]) {
            if (argc < 5) return 2;
            xibHelp = [NSString stringWithUTF8String:argv[4]];
        }
        NSUInteger shiftCommand = NSEventModifierFlagShift | NSEventModifierFlagCommand;
        NSDictionary *swapped = nil;
        if ([mode isEqualToString:@"restore-taken-main"] || [mode isEqualToString:@"restore-taken-freed"])  // the bezel's default is Paste as Plain Text's now
            swapped = @{FlycutMainHotkeyKey: FlycutHotkeyValue(9, shiftCommand), FlycutPlainPasteHotkeyKey: FlycutBezelHotkeyDefault()};
        if ([mode isEqualToString:@"restore-taken-plain"])  // Paste as Plain Text's default is the bezel's now
            swapped = @{FlycutMainHotkeyKey: FlycutPlainPasteHotkeyDefault(), FlycutPlainPasteHotkeyKey: FlycutHotkeyValue(9, shiftCommand)};
        int failed = Prepare(argc, argv, swapped ?: (stored ? custom : @{}));
        if (failed) return failed;
        if ([mode isEqualToString:@"row"]) return Row();
        if ([mode isEqualToString:@"shows-default"]) return Shows(NO);
        if ([mode isEqualToString:@"shows-stored"]) return Shows(YES);
        if ([mode isEqualToString:@"record"]) return Record();
        if ([mode isEqualToString:@"restore"]) return Restore();
        if ([mode isEqualToString:@"taken"]) return Taken();
        if ([mode isEqualToString:@"restore-taken-main"]) return RestoreTaken(@"restoreDefaultMainHotkey");
        if ([mode isEqualToString:@"restore-taken-plain"]) return RestoreTaken(@"restoreDefaultPlainPasteHotkey");
        if ([mode isEqualToString:@"restore-taken-freed"]) return RestoreFreed();
        if ([mode isEqualToString:@"xib-help"]) {
            if (!xibHelpSet) return 44;
            NSTextField *help = HelpText([[[prefs tabView] tabViewItemAtIndex:hotkeysPane] view]);
            if (![[help stringValue] isEqualToString:xibHelp]) {
                fprintf(stderr, "shown: %s\n", [[help stringValue] UTF8String]);
                return 45;
            }
            return Row();
        }
        return 5;
    }
}
'''


class PreferencesPlainPasteRowTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "PlainPasteRowFixture"
    EXTRA_CFLAGS = ("-DNSBeep=FCTestNSBeep",)

    def test_the_row_lines_up_with_the_main_hotkey(self) -> None:
        self.run_mode("row", "the Paste as Plain Text row's layout")

    def test_the_recorder_shows_the_factory_hotkey(self) -> None:
        self.run_mode("shows-default", "the factory combination, arrow hidden")

    def test_the_recorder_shows_a_stored_hotkey(self) -> None:
        self.run_mode("shows-stored", "a stored combination, arrow shown")

    def test_recording_stores_and_registers_the_hotkey(self) -> None:
        self.run_mode("record", "recording, clearing and the factory value")

    def test_the_arrow_restores_the_factory_hotkey(self) -> None:
        self.run_mode("restore", "Restore Default")

    def test_a_combination_of_another_flycut_hotkey_is_refused(self) -> None:
        self.run_mode("taken", "one combination, one Flycut hotkey")

    def test_restore_default_refuses_the_bezel_default_paste_as_plain_text_uses(self) -> None:
        self.run_mode("restore-taken-main", "Restore Default of the Main Hotkey onto Paste as Plain Text's keys")

    def test_restore_default_refuses_the_plain_paste_default_the_bezel_uses(self) -> None:
        self.run_mode("restore-taken-plain", "Restore Default of Paste as Plain Text onto the Main Hotkey's keys")

    def test_a_dimmed_arrow_can_be_clicked_once_the_other_hotkey_moves(self) -> None:
        self.run_mode("restore-taken-freed", "the bezel's arrow after Paste as Plain Text left its default")

    def test_help_says_when_a_restore_arrow_is_dimmed(self) -> None:
        help_text = (ROOT / "help.md").read_text()
        paragraphs = [p for p in help_text.split("\n\n") if p.startswith("A setting that differs from its factory value")]
        self.assertEqual(paragraphs, [HELP_RESTORE])

    def test_help_names_where_to_change_it(self) -> None:
        help_text = (ROOT / "help.md").read_text()
        self.assertIn("You can change or clear it under Hotkeys in Preferences.", help_text)

    def test_the_xib_help_text_comes_through_the_builders_as_written(self) -> None:
        self.run_mode("xib-help", "MainMenu.xib's help text, unchanged and laid out under both rows",
                      (xib_hotkeys_help(),))


class HotkeysHelpTextTests(unittest.TestCase):
    def test_the_xib_help_text_speaks_of_both_hotkeys(self) -> None:
        self.assertEqual(xib_hotkeys_help(), HOTKEYS_HELP)


if __name__ == "__main__":
    unittest.main()
