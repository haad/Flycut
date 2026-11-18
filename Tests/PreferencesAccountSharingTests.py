#!/usr/bin/env python3
"""The General pane's "Other accounts on this Mac:" section (account sharing).

The section is built in code (no XIB change): a section label like "Saving:" and one
checkbox like "Remove duplicates", below the Saving section and above the "Check
Accessibility Permissions" row. The fixture loads the production NIB (master's compiled
MainMenu.nib for trees that carry only MainMenu.xib, see Tests/Fixtures/
PreferencesNibFixture.py) and sends the builders that -awakeFromNib sends; a baseline
run sends them without the new builder, so the geometry can be compared: every NIB
control keeps its distance from the top, the pane grows by exactly the section, the gap
above the permissions row stays, the other panes keep their height. Also checked: fonts and left edges taken from the
neighbours, the title fits, the binding, the action, the tooltip, the VoiceOver label
(control and cell), the key-view order and that the window follows the taller pane
when UKPrefsPanel has already sized it. Defaults stay in memory; the window is never
shown.

Where the section ends up once the window shows: in both orders the NIB loader may
wake AppController and UKPrefsPanel in, and with the three numbers changed so that
their Restore Default arrows show (as on a Mac in use), the real
-showPreferencePanel: (width fit, focus code), every other pane and back, and
closing and reopening: the label stays 16 pt below the Saving section, the section
above the permissions row, all of it inside the window and the General box. The
arrows are laid out by constraints; the fixture reads factory values back through a
registration-domain shim, without which every arrow stays hidden.

With the tree's MainMenu.xib laid onto that NIB (Tests/Fixtures/GeneralPaneXib.py) the
section follows the XIB's spacing: 16 pt below the Saving section, the checkbox 8 pt
below the label, and the permissions row 16 pt below the section.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase, ROOT  # noqa: E402
import GeneralPaneXib  # noqa: E402

TITLE = "Share copied text with other accounts on this Mac"
TOOLTIP = ("Text you copy also goes to Flycut in the other accounts on this Mac that turn this on too. "
           "Passwords Flycut recognizes and copies marked as private or temporary are never shared.")

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

static void FitGeneralFirst(void)
{
    // UKPrefsPanel's own -awakeFromNib ran before AppController's: toolbar made, General shown and fitted.
    [prefs mapTabsToToolbar];
    NSInteger general = [[prefs tabView] indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"];
    NSButton *sender = [[[NSButton alloc] init] autorelease];
    [sender setTag:general];
    [prefs changePanes:sender];
}

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

static BOOL Inside(NSRect r, NSRect bounds)
{
    return NSMinX(r) >= NSMinX(bounds) - 0.01 && NSMaxX(r) <= NSMaxX(bounds) + 0.01 &&
           NSMinY(r) >= NSMinY(bounds) - 0.01 && NSMaxY(r) <= NSMaxY(bounds) + 0.01;
}

// The General pane as the window shows it: the section's views (label and checkbox)
// against the window's content view and the General box, the label against the lowest
// other control, the section's bottom against the permissions row.
static NSDictionary *Placement(NSString *step)
{
    NSView *content = [window contentView];
    [content layoutSubtreeIfNeeded];
    NSView *pane = PaneView(generalPane);
    NSBox *box = (NSBox *)[pane superview];
    NSView *permissions = FindByIdentifier(pane, @"accessibilityPermissionsRow");
    NSMutableArray *section = [NSMutableArray array];
    CGFloat lowest = CGFLOAT_MAX, bottom = CGFLOAT_MAX, labelTop = -CGFLOAT_MAX;
    BOOL inContent = YES, inBox = YES;
    NSUInteger arrows = 0;
    for (NSView *v in [pane subviews]) {
        if ([[v identifier] hasPrefix:@"restoreDefault"] && ![v isHidden]) arrows++;
        if (v == permissions) continue;
        if (!InSection(v)) {
            if (![v isHidden]) lowest = MIN(lowest, NSMinY([v frame]));
            continue;
        }
        BOOL c = Inside([content convertRect:[v bounds] fromView:v], [content bounds]);
        BOOL b = Inside([box convertRect:[v bounds] fromView:v], [box bounds]);
        inContent = inContent && c;
        inBox = inBox && b;
        bottom = MIN(bottom, NSMinY([v frame]));
        if ([v identifier] == nil) labelTop = NSMaxY([v frame]);
        [section addObject:@{@"view": [v identifier] ?: @"label", @"frame": FrameOf([v frame]), @"inContent": @(c), @"inBox": @(b)}];
    }
    return @{@"step": step, @"selected": [[[prefs tabView] selectedTabViewItem] identifier] ?: @"",
             @"section": section, @"inContent": @(inContent), @"inBox": @(inBox),
             @"boxInContent": @(Inside([content convertRect:[box bounds] fromView:box], [content bounds])),
             @"labelBelowLowest": @(lowest - labelTop), @"aboveTheRow": @(bottom - NSMaxY([permissions frame])),
             @"belowTheSection": @(bottom - SeparatorTop(pane, permissions)),
             @"permissions": FrameOf([permissions frame]),
             @"permissionsInContent": FrameOf([content convertRect:[permissions bounds] fromView:permissions]),
             @"arrowsShown": @(arrows)};
}

// argv[4] "builders-first" (-[UKPrefsPanel awakeFromNib] after AppController's, its
// -resizeToFit: stood in for by a pane change) or "prefs-first" (the real
// -[UKPrefsPanel awakeFromNib] before the builders; the NIB loader uses either order),
// argv[5] "stored" (three numbers changed, as on a Mac in use) or "factory".
static int Placed(int argc, const char **argv)
{
    if (argc < 6) return 2;
    BOOL prefsFirst = strcmp(argv[4], "prefs-first") == 0;
    if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 6;
    if (strcmp(argv[5], "stored") == 0) {
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
    int failed = LoadNib(argc, argv);
    if (failed) return failed;
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
    [controller showPreferencePanel:nil];
    [steps addObject:Placement(@"reopened")];
    Emit(@{@"steps": steps});
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        NSString *mode = argc > 2 ? [NSString stringWithUTF8String:argv[2]] : @"";
        if ([mode isEqualToString:@"placed"]) return Placed(argc, argv);
        if ([mode isEqualToString:@"on"]) BeforeBuilders = ShareOn;
        if ([mode isEqualToString:@"fitted-first"]) BeforeBuilders = FitGeneralFirst;
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        NSView *pane = PaneView(generalPane);
        NSBox *box = (NSBox *)[pane superview];
        NSMutableDictionary *report = [NSMutableDictionary dictionary];
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
        NSTextField *label = (NSTextField *)FindByTitle(pane, @"Other accounts on this Mac:", [NSTextField class]);
        NSButton *checkbox = (NSButton *)FindByIdentifier(pane, @"accountSharingCheckbox");
        NSView *sticky = BoundTo(pane, @"values.stickyBezel");
        CGFloat lowest = CGFLOAT_MAX;
        for (NSView *v in [pane subviews]) {
            if (v == permissions || v == label || v == checkbox || [v isHidden]) continue;
            lowest = MIN(lowest, NSMinY([v frame]));
        }
        report[@"paneHeight"] = @(NSHeight([pane bounds]));
        report[@"contentHeight"] = @(NSHeight([[window contentView] frame]));
        report[@"boxHeight"] = @(NSHeight([box frame]));
        report[@"stickyTopDistance"] = @(NSHeight([pane bounds]) - NSMaxY([sticky frame]));
        report[@"lowestNib"] = @(lowest);
        report[@"permissions"] = FrameOf([permissions frame]);
        report[@"saving"] = FrameOf([saving frame]);
        report[@"reference"] = FrameOf([reference frame]);
        if (label == nil || checkbox == nil) {
            report[@"section"] = @NO;
            Emit(report);
            return 0;
        }
        report[@"section"] = @YES;
        report[@"label"] = FrameOf([label frame]);
        report[@"checkbox"] = FrameOf([checkbox frame]);
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
        // Key-view order: the controls of the pane in -nextKeyView order from the tab view.
        NSMutableArray *order = [NSMutableArray array];
        NSView *v = [[prefs tabView] nextKeyView];
        for (int steps = 0; v != nil && v != [prefs tabView] && steps < 500; steps++, v = [v nextKeyView]) {
            if ([v window] != window || [v isHiddenOrHasHiddenAncestor] || ![v isKindOfClass:[NSControl class]]) continue;
            NSString *name = v == checkbox ? @"share"
                : ([v isKindOfClass:[NSButton class]] ? [(NSButton *)v title] : NSStringFromClass([v class]));
            if (![order containsObject:name]) [order addObject:name];
        }
        report[@"keyOrder"] = order;
        report[@"favoritesTitle"] = [[controller valueForKey:@"forgottenFavoritesCheckbox"] title] ?: @"";
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

    def test_pane_grows_by_the_section_and_nothing_else_moves(self) -> None:
        base, r = self.baseline(), self.section("off")
        self.assertFalse(base["section"])
        grown = r["paneHeight"] - base["paneHeight"]
        self.assertEqual(grown, r["label"]["h"] + r["checkbox"]["h"] + 16 + 8)
        self.assertEqual(r["contentHeight"] - base["contentHeight"], grown, "the window does not follow the pane")
        self.assertEqual(r["stickyTopDistance"], base["stickyTopDistance"], "NIB controls moved")
        self.assertEqual(r["permissions"], base["permissions"], "the permissions row moved")
        base_gap = base["lowestNib"] - (base["permissions"]["y"] + base["permissions"]["h"])
        gap = r["checkbox"]["y"] - (r["permissions"]["y"] + r["permissions"]["h"])
        self.assertEqual(gap, base_gap, "the gap above the permissions row changed")
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

    def check_right_edge(self, s: dict, where: str) -> None:
        """The sharing checkbox, and the section's lines with it, end where General's other
        controls end once the window is fitted to them: the right edge of the permissions row,
        which spans the pane less its margins, within the point the fit rounds up."""
        box = next(v for v in s["section"] if v["view"] == "accountSharingCheckbox")["frame"]
        right = s["permissions"]["x"] + s["permissions"]["w"]
        self.assertLessEqual(abs(box["x"] + box["w"] - right), 1,
                             f"{where}: the sharing checkbox ends at {box['x'] + box['w']:g}, General's controls at {right:g}")

    def check_xib_spacing(self, s: dict, where: str) -> None:
        # Top down: the label, the checkbox, then the rows of the list (and the note line).
        views = sorted(s["section"], key=lambda v: -(v["frame"]["y"] + v["frame"]["h"]))
        gaps = [p["frame"]["y"] - (n["frame"]["y"] + n["frame"]["h"]) for p, n in zip(views, views[1:])]
        self.assertEqual(s["labelBelowLowest"], 16, f"{where}: the label is not 16 pt below the Saving section")
        self.assertEqual(gaps, [8] + [6] * (len(views) - 2), f"{where}: label -> checkbox 8 pt, row -> row 6 pt")
        self.assertEqual(s["belowTheSection"], 16, f"{where}: the permissions row is not 16 pt below the section")
        self.assertEqual(s["permissions"]["y"], 8, f"{where}: the permissions row left its place at the bottom")
        self.assertTrue(s["inContent"] and s["inBox"] and s["boxInContent"], f"{where}: {s['section']}")
        self.check_right_edge(s, where)

    def placed(self, order: str, values: str, xib: bool = False) -> list[dict]:
        if self.nib_source is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        run = subprocess.run([str(self.binary), str(self.bundle), "placed", self.builders, order, values],
                             cwd=ROOT, text=True, capture_output=True, timeout=90,
                             env=self.xib_env() if xib else None)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertTrue(reports, run.stdout[-1500:] + run.stderr[-1500:])
        steps = json.loads(reports[-1])["steps"]
        print(f"\nplaced {order} {values}: " + "; ".join(
            f"{s['step']}: label {s['labelBelowLowest']:g} below, {s['aboveTheRow']:g} above the row, "
            f"inside {s['inContent'] and s['inBox'] and s['boxInContent']}" for s in steps))
        return steps

    def check_placed(self, order: str) -> None:
        steps = self.placed(order, "stored")
        self.assertEqual([s["step"] for s in steps], ["opened", "back from Hotkeys", "back from Appearance",
                                                      "back from Acknowledgements", "reopened"])
        for s in steps:
            where = f"{order}, {s['step']}"
            self.assertEqual(s["arrowsShown"], 3, f"{where}: the changed numbers show no Restore Default arrows")
            self.assertEqual(s["selected"], "net.sf.jumpcut.preferences.general.tiff", where)
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

    def test_section_stays_in_place_with_restore_default_arrows_shown(self) -> None:
        self.check_placed("builders-first")

    def test_section_stays_in_place_when_ukprefspanel_wakes_first(self) -> None:
        self.check_placed("prefs-first")

    def test_section_follows_the_xibs_spacing(self) -> None:
        for order in ("builders-first", "prefs-first"):
            for values in ("stored", "factory"):
                for s in self.placed(order, values, xib=True):
                    self.check_xib_spacing(s, f"XIB, {order}, {values}, {s['step']}")

    def test_shown_restore_default_arrows_do_not_move_the_section(self) -> None:
        stored = self.placed("builders-first", "stored")
        factory = self.placed("builders-first", "factory")
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

    def test_tooltip_and_voiceover_label(self) -> None:
        r = self.section("off")
        self.assertEqual(r["tooltip"], TOOLTIP)
        self.assertNotIn("\u2014", r["tooltip"])
        self.assertEqual(r["axControl"], TITLE)
        self.assertEqual(r["axCell"], TITLE)

    def test_key_view_order_runs_through_the_checkbox(self) -> None:
        r = self.section("off")
        order = r["keyOrder"]
        self.assertIn("share", order)
        self.assertIn(r["favoritesTitle"], order)
        self.assertIn("Check Accessibility Permissions", order)
        share = order.index("share")
        self.assertEqual(order[share - 1], r["favoritesTitle"], order)
        self.assertEqual(order[share + 1], "Check Accessibility Permissions", order)


if __name__ == "__main__":
    unittest.main()
