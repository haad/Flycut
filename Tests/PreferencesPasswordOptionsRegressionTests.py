#!/usr/bin/env python3
"""Preferences > General, "Passwords & privacy:": what "Don't save passwords" greys out.

The master checkbox "Don't save passwords" (skipPasswordFields) gates only the length &
complexity check in -[FlycutOperator shouldSkip:ofType:fromAvailableTypes:]; the data-type
filters (skipPboardTypes with its list, skipConcealedTypes) apply on their own, so that turning
the master off never starts saving content the source app marked as confidential. The pane says
the same: while the master is off, "by length & complexity:" and its field are greyed out
(disabled); the rows of "Skip by data type:" stay enabled. A list field is greyed out as well
while its own checkbox is off (the lengths field needs both switches, the types field its
checkbox), because the list does nothing then. A field's Restore Default arrow is greyed out
with the field (it stays hidden at the factory value).

The bindings are made in code (-buildGeneralPasswordOptionStates), so they hold with master's
compiled NIB too. Without Xcode the test loads that NIB (FLYCUT_TEST_RESOURCE_BUNDLE, a built
Flycut.app; it skips without one) and lays the tree's XIB onto its General pane with
Tests/Fixtures/GeneralPaneXib.py before -awakeFromNib's builders run. Defaults stay in memory
(Tests/Fixtures/FixtureIsolation.h); a click on a checkbox goes through its value binding.
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
sys.path.insert(0, str(FIXTURES))
import GeneralPaneXib  # noqa: E402
from PreferencesNibFixture import awake_builders  # noqa: E402

KEYS = ("skipPasswordFields", "skipPasswordLengths", "skipPasswordLengthsList", "skipPboardTypes", "skipPboardTypesList",
        "skipConcealedTypes", "revealPasteboardTypes")


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
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static UKPrefsPanel *prefs;
static AppController *controller;

static NSControl *Bound(NSView *pane, NSString *key)
{
    NSString *keyPath = [@"values." stringByAppendingString:key];
    for (NSView *v in [pane subviews])
        if ([v isKindOfClass:[NSControl class]] &&
            [[[v infoForBinding:NSValueBinding] objectForKey:NSObservedKeyPathKey] isEqualToString:keyPath])
            return (NSControl *)v;
    return nil;
}

static NSView *appearance;
static NSButton *BoundCheckbox(NSView *view, NSString *keyPath)
{
    if ([view isKindOfClass:[NSButton class]] &&
        [[[view infoForBinding:NSValueBinding] objectForKey:NSObservedKeyPathKey] isEqualToString:keyPath])
        return (NSButton *)view;
    for (NSView *child in [view subviews]) {
        NSButton *found = BoundCheckbox(child, keyPath);
        if (found) return found;
    }
    return nil;
}

static NSView *WithIdentifier(NSView *view, NSString *identifier)
{
    if ([[view identifier] isEqualToString:identifier]) return view;
    for (NSView *child in [view subviews]) {
        NSView *found = WithIdentifier(child, identifier);
        if (found) return found;
    }
    return nil;
}

static NSDictionary *States(NSView *pane)
{
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    // The Appearance pane's capture options (rows built in code).
    for (NSString *key in @[@"captureImages", @"downloadAnimatedGIFs"]) {
        NSButton *box = BoundCheckbox(appearance, key);   // rows built in code bind to the defaults
        out[key] = box ? @{@"enabled": @([box isEnabled])} : @{@"missing": @YES};
    }
    // The Restore Default arrows of the two list fields.
    for (NSString *key in @[@"skipPasswordLengthsList", @"skipPboardTypesList"]) {
        NSString *identifier = [@"restoreDefault" stringByAppendingString:
            [[[key substringToIndex:1] uppercaseString] stringByAppendingString:[key substringFromIndex:1]]];
        NSView *arrow = WithIdentifier(pane, identifier);
        out[[@"arrow:" stringByAppendingString:key]] = [arrow isKindOfClass:[NSButton class]]
            ? @{@"enabled": @([(NSButton *)arrow isEnabled]), @"hidden": @([arrow isHidden])} : @{@"missing": @YES};
    }
    for (NSString *key in @[@"skipPasswordFields", @"skipPasswordLengths", @"skipPasswordLengthsList", @"skipPboardTypes",
                            @"skipPboardTypesList", @"skipConcealedTypes", @"revealPasteboardTypes"]) {
        NSControl *c = Bound(pane, key);
        NSRect a = c ? [c alignmentRectForFrame:[c frame]] : NSZeroRect;
        out[key] = c ? @{@"enabled": @([c isEnabled]), @"value": [[NSUserDefaults standardUserDefaults] objectForKey:key] ?: [NSNull null],
                         @"minX": @(NSMinX(a)), @"maxX": @(NSMaxX(a))}
                     : @{@"missing": @YES};
    }
    return out;
}

// argv: <bundle> <xib spec JSON path | -> <builders> <key=YES|NO,...> <key to click after showing | ->
int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 6) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        NSDictionary *spec = nil;
        if (strcmp(argv[2], "-") != 0) {
            spec = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]]
                                                   options:0 error:NULL];
            if (spec == nil) return 4;
        }
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
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
        for (NSString *pair in [[NSString stringWithUTF8String:argv[4]] componentsSeparatedByString:@","]) {
            NSArray *kv = [pair componentsSeparatedByString:@"="];
            if ([kv count] == 2 && [kv[0] hasSuffix:@"List"])
                [[NSUserDefaults standardUserDefaults] setObject:kv[1] forKey:kv[0]];
            else if ([kv count] == 2)
                [[NSUserDefaults standardUserDefaults] setBool:[kv[1] isEqualToString:@"YES"] forKey:kv[0]];
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
        appearance = [controller valueForKey:@"appearancePanel"];
        [window setDelegate:nil];
        NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
        if (spec) {
            NSArray *problems = GPXApply(pane, [prefs tabView], controller, spec);
            if ([problems count]) { fprintf(stderr, "XIB step: %s\n", [[problems description] UTF8String]); return 12; }
        }
        for (NSString *name in [[NSString stringWithUTF8String:argv[3]] componentsSeparatedByString:@","])
            if ([name length] && [controller respondsToSelector:NSSelectorFromString(name)])
                ((void (*)(id, SEL))objc_msgSend)(controller, NSSelectorFromString(name));
        [prefs mapTabsToToolbar];
        method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
        method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeContents);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
        [controller showPreferencePanel:nil];
        NSMutableArray *steps = [NSMutableArray arrayWithObject:States(pane)];
        if (strcmp(argv[5], "-") != 0) {
            NSControl *box = Bound(pane, [NSString stringWithUTF8String:argv[5]]);
            if (box == nil) box = BoundCheckbox(appearance, [NSString stringWithUTF8String:argv[5]]);
            if (![box isKindOfClass:[NSButton class]]) return 13;
            for (int i = 0; i < 2; i++) {      // off and on again (or on and off), as a click does
                [(NSButton *)box performClick:nil];
                [steps addObject:States(pane)];
            }
        }
        NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"steps": steps} options:NSJSONWritingSortedKeys error:nil];
        printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    }
    return 0;
}
'''


class PreferencesPasswordOptionsRegressionTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-PasswordOptions-")
        temp = pathlib.Path(cls.temp.name)
        cls.nib = compiled_nib()
        cls.bundle = temp / "TestResources.bundle"
        resources = cls.bundle / "Contents" / "Resources" / "English.lproj"
        resources.mkdir(parents=True)
        if cls.nib:
            shutil.copytree(cls.nib, resources / "MainMenu.nib")
        (cls.bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "org.flycut.tests.passwordoptions-resources", "CFBundlePackageType": "BNDL"}))
        cls.spec = temp / "xib.json"
        cls.spec.write_text(json.dumps(GeneralPaneXib.spec(ROOT / "English.lproj" / "MainMenu.xib")))
        sources = [ROOT / p for p in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
                   if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]
        fixture = temp / "PasswordOptions.m"
        fixture.write_text(FIXTURE)
        cls.binary = temp / "PasswordOptions"
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

    def run_case(self, values: dict[str, bool], click: str | None = None, xib: bool = True) -> list[dict]:
        if self.nib is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        stored = ",".join(f"{k}={v}" if isinstance(v, str) else f"{k}={'YES' if v else 'NO'}" for k, v in values.items())
        run = subprocess.run([str(self.binary), str(self.bundle), str(self.spec) if xib else "-", self.builders, stored,
                              click or "-"], cwd=ROOT, text=True, capture_output=True, timeout=120)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertTrue(reports, run.stdout[-1500:] + run.stderr[-1500:])
        steps = json.loads(reports[-1])["steps"]
        for i, s in enumerate(steps):
            print(f"\n{stored} {click or ''} step {i}: " + ", ".join(
                f"{k} {'-' if s[k].get('missing') else ('on' if s[k]['enabled'] else 'GREY')}" for k in KEYS))
        return steps

    def enabled(self, step: dict, key: str) -> bool:
        self.assertNotIn("missing", step[key], f"no control bound to {key} in General")
        return step[key]["enabled"]

    def test_master_off_greys_out_the_length_row_only(self) -> None:
        step = self.run_case({"skipPasswordFields": False, "skipPasswordLengths": True, "skipPboardTypes": True,
                              "skipConcealedTypes": True})[0]
        self.assertTrue(self.enabled(step, "skipPasswordFields"), "the master checkbox itself must stay enabled")
        self.assertFalse(self.enabled(step, "skipPasswordLengths"),
                         "\"by length & complexity:\" is enabled with \"Don't save passwords\" off")
        self.assertFalse(self.enabled(step, "skipPasswordLengthsList"),
                         "the lengths field is enabled with \"Don't save passwords\" off")
        for key in ("skipPboardTypes", "skipPboardTypesList", "skipConcealedTypes", "revealPasteboardTypes"):
            self.assertTrue(self.enabled(step, key), f"{key} is greyed out with \"Don't save passwords\" off, "
                                                     "but it applies on its own")

    def test_master_on_enables_the_length_row(self) -> None:
        step = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True})[0]
        self.assertTrue(self.enabled(step, "skipPasswordLengths"), "\"by length & complexity:\" is greyed out with the master on")
        self.assertTrue(self.enabled(step, "skipPasswordLengthsList"), "the lengths field is greyed out with both switches on")

    def test_a_list_field_is_greyed_out_while_its_own_checkbox_is_off(self) -> None:
        step = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": False, "skipPboardTypes": False})[0]
        self.assertTrue(self.enabled(step, "skipPasswordLengths"))
        self.assertFalse(self.enabled(step, "skipPasswordLengthsList"), "the lengths field is enabled with its checkbox off")
        self.assertTrue(self.enabled(step, "skipPboardTypes"))
        self.assertFalse(self.enabled(step, "skipPboardTypesList"), "the types field is enabled with its checkbox off")
        self.assertTrue(self.enabled(step, "skipConcealedTypes"), "the concealed option does not depend on the types checkbox")

    def test_a_greyed_fields_restore_arrow_is_greyed_out_too(self) -> None:
        # Both lists differ from the factory value, so both arrows show.
        lists = {"skipPasswordLengthsList": "12 20", "skipPboardTypesList": "PasswordPboardType example.type"}
        step = self.run_case({"skipPasswordFields": False, "skipPasswordLengths": True, "skipPboardTypes": False, **lists})[0]
        for key in ("skipPasswordLengthsList", "skipPboardTypesList"):
            self.assertFalse(step["arrow:" + key].get("hidden", True), f"{key}: its arrow is hidden at a changed value")
            self.assertFalse(self.enabled(step, "arrow:" + key), f"{key}: its arrow is enabled while the field is greyed out")
        step = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True, **lists})[0]
        for key in ("skipPasswordLengthsList", "skipPboardTypesList"):
            self.assertTrue(self.enabled(step, "arrow:" + key), f"{key}: its arrow is greyed out with the field enabled")

    def test_clicking_a_switch_greys_and_restores_the_arrow(self) -> None:
        steps = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True,
                               "skipPboardTypesList": "PasswordPboardType example.type"}, click="skipPboardTypes")
        self.assertEqual([self.enabled(s, "arrow:skipPboardTypesList") for s in steps], [True, False, True])
        self.assertEqual([self.enabled(s, "skipPboardTypesList") for s in steps], [True, False, True])

    FILTERS = ("skipPasswordFields", "skipPasswordLengths", "skipPasswordLengthsList", "skipPboardTypes",
               "skipPboardTypesList", "skipConcealedTypes")

    def test_diagnostics_greys_out_every_filter(self) -> None:
        # Diagnostics records the copy's types before any filter runs: no filter does anything.
        lists = {"skipPasswordLengthsList": "12 20", "skipPboardTypesList": "PasswordPboardType example.type"}
        step = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True,
                              "skipConcealedTypes": True, "revealPasteboardTypes": True, **lists})[0]
        for key in self.FILTERS:
            self.assertFalse(self.enabled(step, key), f"{key} is enabled while Diagnostics is on")
        for key in ("skipPasswordLengthsList", "skipPboardTypesList"):
            self.assertFalse(self.enabled(step, "arrow:" + key), f"{key}: its arrow is enabled while Diagnostics is on")
        self.assertTrue(self.enabled(step, "revealPasteboardTypes"), "Diagnostics itself must stay enabled")

    def test_clicking_diagnostics_greys_and_restores_the_filters(self) -> None:
        steps = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True,
                               "skipConcealedTypes": True, "revealPasteboardTypes": False}, click="revealPasteboardTypes")
        self.assertEqual([s["revealPasteboardTypes"]["value"] for s in steps], [False, True, False])
        for key in self.FILTERS:
            self.assertEqual([self.enabled(s, key) for s in steps], [True, False, True], f"{key} did not follow Diagnostics")
        for key in ("captureImages", "downloadAnimatedGIFs"):
            self.assertEqual([self.enabled(s, key) for s in steps], [True, False, True], f"{key} did not follow Diagnostics")

    def test_gif_download_is_greyed_out_while_image_capture_is_off(self) -> None:
        steps = self.run_case({"captureImages": True, "downloadAnimatedGIFs": True}, click="captureImages")
        self.assertEqual([self.enabled(s, "downloadAnimatedGIFs") for s in steps], [True, False, True])
        self.assertEqual([self.enabled(s, "captureImages") for s in steps], [True, True, True])

    def test_clicking_the_master_greys_and_restores_the_length_row(self) -> None:
        steps = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True},
                              click="skipPasswordFields")
        self.assertEqual([s["skipPasswordFields"]["value"] for s in steps], [True, False, True])
        self.assertEqual([self.enabled(s, "skipPasswordLengths") for s in steps], [True, False, True])
        self.assertEqual([self.enabled(s, "skipPasswordLengthsList") for s in steps], [True, False, True])
        for key in ("skipPboardTypes", "skipPboardTypesList", "skipConcealedTypes", "revealPasteboardTypes"):
            self.assertEqual([self.enabled(s, key) for s in steps], [True, True, True], f"{key} followed the master")

    def test_each_list_field_stands_on_its_groups_column(self) -> None:
        # Fields behind checkboxes that start at the same x (one group) share a column, 8 pt after
        # the wider checkbox; a field in another group (its checkbox starts elsewhere, as in a
        # "Skip by data type:" group right of its label) starts 8 pt after its own checkbox.
        s = self.run_case({"skipPasswordFields": True, "skipPasswordLengths": True, "skipPboardTypes": True})[0]
        boxes = {k: s[k] for k in ("skipPboardTypes", "skipPasswordLengths")}
        fields = {"skipPboardTypes": s["skipPboardTypesList"], "skipPasswordLengths": s["skipPasswordLengthsList"]}
        for k in boxes:
            self.assertNotIn("missing", boxes[k])
            self.assertNotIn("missing", fields[k])
        gaps = {k: fields[k]["minX"] - boxes[k]["maxX"] for k in boxes}
        if abs(boxes["skipPboardTypes"]["minX"] - boxes["skipPasswordLengths"]["minX"]) <= 0.5:
            self.assertAlmostEqual(fields["skipPboardTypes"]["minX"], fields["skipPasswordLengths"]["minX"], delta=0.5,
                                   msg="list fields of one group do not share a column")
            self.assertAlmostEqual(min(gaps.values()), 8, delta=0.5, msg=f"column gap {gaps}")
        else:
            for k, gap in gaps.items():
                self.assertAlmostEqual(gap, 8, delta=0.5, msg=f"{k}: its field is {gap:g} pt after its checkbox, "
                                                              "not 8 (pulled onto another group's column)")

    def test_masters_nib_greys_out_the_same_rows(self) -> None:
        # A test build without the XIB step shows master's NIB: the bindings come from code, so it
        # greys out the same rows (master's NIB has no concealed checkbox).
        step = self.run_case({"skipPasswordFields": False, "skipPasswordLengths": True, "skipPboardTypes": True}, xib=False)[0]
        self.assertFalse(self.enabled(step, "skipPasswordLengths"))
        self.assertFalse(self.enabled(step, "skipPasswordLengthsList"))
        for key in ("skipPboardTypes", "skipPboardTypesList", "revealPasteboardTypes"):
            self.assertTrue(self.enabled(step, key), f"{key} is greyed out with the master off")


if __name__ == "__main__":
    unittest.main()
