#!/usr/bin/env python3
"""Preferences > General as an Xcode build of this tree's MainMenu.xib lays it out.

Without Xcode the tests load master's compiled MainMenu.nib (FLYCUT_TEST_RESOURCE_BUNDLE, a
built Flycut.app; they skip without one) and turn its General pane into the tree's XIB with
Tests/Fixtures/GeneralPaneXib.py before the builders run. Then -awakeFromNib's builders up to
-buildGeneralPermissionsPreferenceRow (read from AppController.m, in order), the real
-showPreferencePanel: (the window is never ordered in) and a pane change follow, with
UKPrefsPanel woken after AppController or before it (the NIB loader uses either order) and
with the three numbers stored or at their factory values (Restore Default arrows shown or not).
Defaults stay in memory (Tests/Fixtures/FixtureIsolation.h). Positions are alignment rects.

The "Check Accessibility Permissions" row (#20) is built at run time; the XIB's rows above it
must not run into it: its separator sits one section gap (16 pt) below the lowest control
shown, the pane is tall enough for it, and the window shows the whole pane. A run without
the XIB step checks that master's NIB keeps the row where it was.
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
sys.path.insert(0, str(FIXTURES))
import GeneralPaneXib  # noqa: E402

SECTION_GAP = 16


def awake_builders(last: str = "buildGeneralPermissionsPreferenceRow") -> list[str]:
    source = (ROOT / "AppController.m").read_text()
    start = source.index("- (void)awakeFromNib\n{")
    body = source[start:source.index("\n}\n", start)]
    names: list[str] = []
    for name in re.findall(r"\[self (build\w+)\]", body):
        if name not in names:
            names.append(name)
    return names[:names.index(last) + 1]


def compiled_nib() -> pathlib.Path | None:
    configured = os.environ.get("FLYCUT_TEST_RESOURCE_BUNDLE")
    nib = (pathlib.Path(configured) / "Contents" / "Resources" / "English.lproj" / "MainMenu.nib"
           if configured else ROOT / "English.lproj" / "MainMenu.nib")
    return nib if nib.is_dir() else None


FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "UKPrefsPanel.h"
#import "SGHotKeyCenter.h"
#import "FlycutOperator.h"
''' + GeneralPaneXib.APPLY_SOURCE + r'''
static void Noop(id self, SEL cmd) { (void)self; (void)cmd; }
static void NoopArg(id self, SEL cmd, id arg) { (void)self; (void)cmd; (void)arg; }
static BOOL FakeRegister(id self, SEL cmd, id hotKey) { (void)self; (void)cmd; (void)hotKey; return YES; }
static id AbortSharedStore(id self, SEL cmd) { (void)self; (void)cmd; fprintf(stderr, "image store reached\n"); _exit(98); }
static BOOL ForbiddenSave(id self, SEL cmd, id store, int index, id prefix)
{
    (void)self; (void)cmd; (void)store; (void)index; (void)prefix;
    fprintf(stderr, "-saveFromStore:atIndex:withPrefix: reached (writes files)\n");
    _exit(97);
}
static BOOL shown = NO;
static NSWindow *window;
static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; }
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? shown : NO; }
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender) { (void)cmd; (void)sender; if (self == window) shown = YES; }
static id FakeContents(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc;
    if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
// FCMemoryDefaults keeps no registration domain; the Restore Default arrows compare with it.
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static UKPrefsPanel *prefs;
static AppController *controller;

static void ChangePane(NSString *identifier)
{
    NSButton *sender = [[[NSButton alloc] init] autorelease];
    [sender setTag:[[prefs tabView] indexOfTabViewItemWithIdentifier:identifier]];
    [prefs changePanes:sender];
    [[window contentView] layoutSubtreeIfNeeded];
}

static NSArray *TopRect(NSRect r, NSView *pane)
{
    return @[@(NSMinX(r)), @(NSHeight([pane bounds]) - NSMaxY(r)), @(NSWidth(r)), @(NSHeight(r))];
}

static NSRect AlignmentIn(NSView *v, NSView *pane)
{
    return [pane convertRect:[v alignmentRectForFrame:[v frame]] fromView:[v superview]];
}

static NSString *Name(NSView *v)
{
    if ([v identifier] && ![[v identifier] hasPrefix:@"_NS"]) return [v identifier];
    NSString *text = GPXText(v);
    if ([text length]) return [text stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    return GPXBound(v) ?: NSStringFromClass([v class]);
}

// The General pane as shown: every view (alignment rect, top-based, in the pane), the
// permissions row's separator and button, the heights of pane, box and window content.
static NSDictionary *Measure(NSString *step)
{
    NSView *content = [window contentView];
    [content layoutSubtreeIfNeeded];
    NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
    NSBox *box = (NSBox *)[pane superview];
    NSMutableArray *views = [NSMutableArray array];
    NSDictionary *row = nil;
    for (NSView *v in [pane subviews]) {
        BOOL weight = [v respondsToSelector:@selector(font)] &&
            [[[[(NSControl *)v font] fontDescriptor] objectForKey:NSFontTraitsAttribute][NSFontWeightTrait] doubleValue] > 0.2;
        if ([[v identifier] isEqualToString:@"accessibilityPermissionsRow"]) {
            NSView *separator = nil, *button = nil;
            for (NSView *child in [v subviews]) {
                if ([child isKindOfClass:[NSBox class]]) separator = child;
                if ([child isKindOfClass:[NSButton class]]) button = child;
            }
            row = @{@"frame": @[@(NSMinX([v frame])), @(NSMinY([v frame])), @(NSWidth([v frame])), @(NSHeight([v frame]))],
                    @"separator": TopRect(AlignmentIn(separator, pane), pane), @"button": TopRect(AlignmentIn(button, pane), pane),
                    @"inPane": @(NSContainsRect([pane bounds], [v frame]))};
            continue;
        }
        [views addObject:@{@"name": Name(v), @"cls": NSStringFromClass([v class]), @"hidden": @([v isHiddenOrHasHiddenAncestor]),
                           @"bold": @(weight), @"align": TopRect(AlignmentIn(v, pane), pane),
                           @"font": [v respondsToSelector:@selector(font)] ? @([[(NSControl *)v font] pointSize]) : @0}];
    }
    NSRect boxInContent = [content convertRect:[box bounds] fromView:box];
    return @{@"step": step, @"views": views, @"row": row ?: [NSNull null], @"paneHeight": @(NSHeight([pane bounds])),
             @"boxHeight": @(NSHeight([box frame])), @"tabHeight": @(NSHeight([[prefs tabView] frame])),
             @"contentHeight": @(NSHeight([content frame])), @"windowWidth": @(NSWidth([window frame])),
             @"boxInContent": @(NSContainsRect([content bounds], boxInContent))};
}

static NSDictionary *gSpec;
static IMP prefsAwake;
static BOOL prefsFirst, hideLast;
static NSMutableArray *gProblems;

static void BeforeBuilders(void)
{
    NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
    if (gSpec) [gProblems addObjectsFromArray:GPXApply(pane, [prefs tabView], controller, gSpec)];
    if (hideLast) {
        // The lowest row hidden: "Save forgotten items to:", its folder button and checkboxes.
        [[window contentView] layoutSubtreeIfNeeded];
        NSRect band = AlignmentIn([controller valueForKey:@"autoSaveToLocationButton"], pane);
        for (NSView *v in [pane subviews]) {
            NSRect r = AlignmentIn(v, pane);
            if (NSMidY(r) >= NSMinY(band) - 1 && NSMidY(r) <= NSMaxY(band) + 1) [v setHidden:YES];
        }
    }
    if (prefsFirst) ((void (*)(id, SEL))prefsAwake)(prefs, @selector(awakeFromNib));
}

// argv: <bundle> <xib spec JSON path | -> <builders> <builders-first|prefs-first> <stored|factory> <shown|hide-last>
int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 7) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        gProblems = [[NSMutableArray alloc] init];
        if (strcmp(argv[2], "-") != 0) {
            gSpec = [[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]]
                                                     options:0 error:NULL] retain];
            if (gSpec == nil) return 4;
        }
        prefsFirst = strcmp(argv[4], "prefs-first") == 0;
        hideLast = strcmp(argv[6], "hide-last") == 0;
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
        prefsAwake = method_getImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)));
        method_setImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)), (IMP)Noop);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)NoopArg);
        Method updateMenu = class_getInstanceMethod([AppController class], NSSelectorFromString(@"updateMenu"));
        if (updateMenu) method_setImplementation(updateMenu, (IMP)Noop);
        Class imageStore = NSClassFromString(@"FlycutImageStore");
        if (imageStore) method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)AbortSharedStore);
        method_setImplementation(class_getInstanceMethod([FlycutOperator class], @selector(saveFromStore:atIndex:withPrefix:)), (IMP)ForbiddenSave);
        if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 5;
        [NSApplication sharedApplication];
        [[[FlycutOperator alloc] init] autorelease];     // registers the operator's defaults, as awakeFromNib does
        if (strcmp(argv[5], "stored") == 0) {
            NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
            [defaults setObject:@99 forKey:@"rememberNum"];
            [defaults setObject:@15 forKey:@"displayNum"];
            [defaults setObject:@25 forKey:@"favoritesRememberNum"];
        }
        NSNib *nib = [[NSNib alloc] initWithNibNamed:@"MainMenu" bundle:[NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]]];
        NSArray *objects = nil;
        if (![nib instantiateWithOwner:NSApp topLevelObjects:&objects]) return 10;
        [NSApp setDelegate:nil];
        for (id obj in objects) {
            if ([obj isKindOfClass:[AppController class]]) controller = obj;
            if ([obj isKindOfClass:[UKPrefsPanel class]]) prefs = obj;
        }
        if (!controller || !prefs) return 11;
        window = [controller valueForKey:@"prefsPanel"];
        [window setDelegate:nil];
        BeforeBuilders();
        if ([gProblems count]) {
            fprintf(stderr, "XIB step: %s\n", [[gProblems description] UTF8String]);
            return 12;
        }
        for (NSString *name in [[NSString stringWithUTF8String:argv[3]] componentsSeparatedByString:@","])
            if ([name length] && [controller respondsToSelector:NSSelectorFromString(name)])
                ((void (*)(id, SEL))objc_msgSend)(controller, NSSelectorFromString(name));
        if (!prefsFirst) {
            // UKPrefsPanel's -awakeFromNib after AppController's: its toolbar and -resizeToFit:.
            [prefs mapTabsToToolbar];
            ChangePane(@"net.sf.jumpcut.preferences.general.tiff");
        }
        method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
        method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeContents);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
        [controller showPreferencePanel:nil];
        NSDictionary *opened = Measure(@"opened");
        ChangePane(@"net.sf.jumpcut.preferences.hotkey.tiff");
        ChangePane(@"net.sf.jumpcut.preferences.general.tiff");
        NSDictionary *back = Measure(@"back from Hotkeys");
        NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"steps": @[opened, back]} options:NSJSONWritingSortedKeys error:nil];
        printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    }
    return 0;
}
'''


class PreferencesGeneralLayoutRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-GeneralLayout-")
        temp = pathlib.Path(cls.temp.name)
        cls.nib = compiled_nib()
        cls.bundle = temp / "TestResources.bundle"
        resources = cls.bundle / "Contents" / "Resources" / "English.lproj"
        resources.mkdir(parents=True)
        if cls.nib:
            shutil.copytree(cls.nib, resources / "MainMenu.nib")
        (cls.bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "org.flycut.tests.generallayout-resources", "CFBundlePackageType": "BNDL"}))
        cls.spec = temp / "xib.json"
        cls.spec.write_text(json.dumps(GeneralPaneXib.spec(ROOT / "English.lproj" / "MainMenu.xib")))
        sources = [ROOT / p for p in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
                   if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]
        fixture = temp / "GeneralLayout.m"
        fixture.write_text(FIXTURE)
        cls.binary = temp / "GeneralLayout"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules", "-DFLYCUT_MAC=1",
                   "-mmacosx-version-min=13.5", "-arch", "arm64", "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(fixture)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "ApplicationServices"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout[-3000:] + build.stderr[-3000:])
        cls.builders = ",".join(awake_builders())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def steps(self, xib: bool, order: str, values: str, rows: str = "shown") -> list[dict]:
        if self.nib is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        run = subprocess.run([str(self.binary), str(self.bundle), str(self.spec) if xib else "-", self.builders,
                              order, values, rows], cwd=ROOT, text=True, capture_output=True, timeout=120)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertTrue(reports, run.stdout[-1500:] + run.stderr[-1500:])
        steps = json.loads(reports[-1])["steps"]
        for s in steps:
            if not s["row"]:
                continue
            low = self.lowest(s)
            print(f"\n{'xib' if xib else 'nib'} {order} {values} {rows} {s['step']}: separator "
                  f"{s['row']['separator'][1] - low['bottom']:g} pt below '{low['name']}', row y {s['row']['frame'][1]:g}, "
                  f"pane {s['paneHeight']:g}, content {s['contentHeight']:g}, window width {s['windowWidth']:g}")
        return steps

    @staticmethod
    def lowest(step: dict) -> dict:
        shown = [v for v in step["views"] if not v["hidden"]]
        v = max(shown, key=lambda v: v["align"][1] + v["align"][3])
        return {"name": v["name"], "bottom": v["align"][1] + v["align"][3]}

    def check_row(self, step: dict, where: str) -> None:
        row = step["row"]
        self.assertIsNotNone(row, f"{where}: no permissions row")
        gap = row["separator"][1] - self.lowest(step)["bottom"]
        self.assertEqual(gap, SECTION_GAP, f"{where}: the separator is {gap:g} pt below the lowest control, not {SECTION_GAP}")
        for part in ("separator", "button"):
            r = row[part]
            for v in step["views"]:
                a = v["align"]
                if v["hidden"]:
                    continue
                self.assertFalse(a[1] < r[1] + r[3] and r[1] < a[1] + a[3] and a[0] < r[0] + r[2] and r[0] < a[0] + a[2],
                                 f"{where}: the permissions {part} runs into '{v['name']}'")
        self.assertTrue(row["inPane"], f"{where}: the permissions row is outside the General pane")
        self.assertTrue(step["boxInContent"], f"{where}: the window does not show the whole General pane")

    def test_permissions_row_sits_a_section_gap_below_the_xib_rows(self) -> None:
        for order in ("builders-first", "prefs-first"):
            for values in ("stored", "factory"):
                with self.subTest(order=order, values=values):
                    for s in self.steps(True, order, values):
                        where = f"XIB, {order}, {values}, {s['step']}"
                        self.check_row(s, where)
                        self.assertEqual(s["row"]["frame"][1], 8, f"{where}: the row is not at the pane's bottom")

    def test_hidden_controls_do_not_hold_the_permissions_row_down(self) -> None:
        for s in self.steps(True, "builders-first", "factory", "hide-last"):
            self.check_row(s, f"XIB, last row hidden, {s['step']}")

    def test_masters_nib_keeps_the_permissions_row_in_place(self) -> None:
        for s in self.steps(False, "builders-first", "stored"):
            where = f"master's NIB, {s['step']}"
            self.check_row(s, where)
            self.assertEqual(s["row"]["frame"][1], 8, where)
            self.assertEqual(s["paneHeight"], 520, f"{where}: the pane changed its height")


if __name__ == "__main__":
    unittest.main()
