#!/usr/bin/env python3
"""Preferences > General: the frames in MainMenu.xib are where its constraints put the views.

Xcode lays a XIB out from its constraints; the frame each view has in the file is only where
the view stands until that layout runs, and Xcode flags a view whose frame is elsewhere as
misplaced until Update Frames moves it. A text edit of the XIB (a new row, a new title, a
changed constant) leaves the frames where they were, so this checks them.

Without Xcode the test loads master's compiled MainMenu.nib (FLYCUT_TEST_RESOURCE_BUNDLE, a
built Flycut.app; it skips without one) and lays this tree's XIB onto its General pane with
Tests/Fixtures/GeneralPaneXib.py: the XIB's titles, fonts and vertical constraints, its
horizontal constraints where they differ from the NIB's, the views the NIB lacks, and the pane
height. Then the pane is laid out alone, as Xcode does it: no
builder of -awakeFromNib runs, no Restore Default arrow, no permissions row. For every view of
the General box's content view the XIB's frame must be the laid-out frame (within 0.5 pt), on
both axes. The test also checks that the horizontal constraints laid out are exactly the XIB's
and the views' own size constraints the XIB's. The metrics are this Mac's (control sizes of macOS 27); an Xcode on an
older macOS may still show a view off by a point or two.
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
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
sys.path.insert(0, str(FIXTURES))
import GeneralPaneXib  # noqa: E402

XIB = ROOT / "English.lproj" / "MainMenu.xib"
TOLERANCE = 0.5


def compiled_nib() -> pathlib.Path | None:
    configured = os.environ.get("FLYCUT_TEST_RESOURCE_BUNDLE")
    nib = (pathlib.Path(configured) / "Contents" / "Resources" / "English.lproj" / "MainMenu.nib"
           if configured else ROOT / "English.lproj" / "MainMenu.nib")
    return nib if nib.is_dir() else None


FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "UKPrefsPanel.h"
#import "SGHotKeyCenter.h"
''' + GeneralPaneXib.APPLY_SOURCE + r'''
static void Noop(id self, SEL cmd) { (void)self; (void)cmd; }
static void NoopArg(id self, SEL cmd, id arg) { (void)self; (void)cmd; (void)arg; }
static BOOL FakeRegister(id self, SEL cmd, id hotKey) { (void)self; (void)cmd; (void)hotKey; return YES; }
static id AbortSharedStore(id self, SEL cmd) { (void)self; (void)cmd; fprintf(stderr, "image store reached\n"); _exit(98); }

static NSString *AttributeName(NSLayoutAttribute a)
{
    NSDictionary *names = @{@(NSLayoutAttributeLeft): @"left", @(NSLayoutAttributeRight): @"right",
                            @(NSLayoutAttributeTop): @"top", @(NSLayoutAttributeBottom): @"bottom",
                            @(NSLayoutAttributeLeading): @"leading", @(NSLayoutAttributeTrailing): @"trailing",
                            @(NSLayoutAttributeWidth): @"width", @(NSLayoutAttributeHeight): @"height",
                            @(NSLayoutAttributeCenterX): @"centerX", @(NSLayoutAttributeCenterY): @"centerY",
                            @(NSLayoutAttributeLastBaseline): @"lastBaseline", @(NSLayoutAttributeFirstBaseline): @"firstBaseline"};
    return names[@(a)] ?: @"";
}

static NSString *Relation(NSLayoutRelation r)
{
    return r == NSLayoutRelationGreaterThanOrEqual ? @"greaterThanOrEqual"
         : (r == NSLayoutRelationLessThanOrEqual ? @"lessThanOrEqual" : @"equal");
}

// A constraint in the XIB's terms: views by XIB id, the content view as SUPER.
static NSDictionary *Described(NSLayoutConstraint *k, NSDictionary *ids, NSView *content)
{
    id first = [k firstItem] == content ? @"SUPER" : ids[[NSValue valueWithPointer:[k firstItem]]];
    id second = [k secondItem] == nil ? [NSNull null]
              : ([k secondItem] == content ? @"SUPER" : ids[[NSValue valueWithPointer:[k secondItem]]]);
    return @{@"first": first ?: @"?", @"fa": AttributeName([k firstAttribute]),
             @"second": second ?: @"?", @"sa": [k secondItem] ? AttributeName([k secondAttribute]) : @"",
             @"rel": Relation([k relation]), @"m": @([k multiplier]), @"c": @([k constant]), @"prio": @([k priority])};
}

// argv: <bundle> <xib spec JSON>
int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 3) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        NSDictionary *spec = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]]
                                                             options:0 error:NULL];
        if (spec == nil) return 4;
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
        method_setImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)), (IMP)Noop);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)NoopArg);
        Class imageStore = NSClassFromString(@"FlycutImageStore");
        if (imageStore) method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)AbortSharedStore);
        [NSApplication sharedApplication];
        NSNib *nib = [[NSNib alloc] initWithNibNamed:@"MainMenu" bundle:[NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]]];
        NSArray *objects = nil;
        if (![nib instantiateWithOwner:NSApp topLevelObjects:&objects]) return 10;
        [NSApp setDelegate:nil];
        AppController *controller = nil;
        UKPrefsPanel *prefs = nil;
        for (id obj in objects) {
            if ([obj isKindOfClass:[AppController class]]) controller = obj;
            if ([obj isKindOfClass:[UKPrefsPanel class]]) prefs = obj;
        }
        if (!controller || !prefs) return 11;
        NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
        NSArray *problems = GPXApply(pane, [prefs tabView], controller, spec);
        if ([problems count]) { fprintf(stderr, "XIB step: %s\n", [[problems description] UTF8String]); return 12; }
        NSView *item = [[pane superview] superview];
        [item layoutSubtreeIfNeeded];

        NSMutableDictionary *views = [NSMutableDictionary dictionary];
        NSMutableDictionary *ids = [NSMutableDictionary dictionary];
        NSMutableSet *taken = [NSMutableSet set];
        for (NSDictionary *v in spec[@"views"]) {
            NSView *view = nil;
            for (NSView *c in [pane subviews]) if ([[c identifier] isEqualToString:[@"xib-" stringByAppendingString:v[@"id"]]]) view = c;
            if (view == nil) view = GPXFind(pane, controller, v, taken);
            if (view == nil) { fprintf(stderr, "lost %s\n", [v[@"id"] UTF8String]); return 13; }
            [taken addObject:[NSValue valueWithPointer:view]];
            ids[[NSValue valueWithPointer:view]] = v[@"id"];
            NSRect f = [view frame];
            views[v[@"id"]] = @[@(NSMinX(f)), @(NSMinY(f)), @(NSWidth(f)), @(NSHeight(f))];
        }
        // What lays the views out horizontally: the content view's constraints on other
        // attributes than vertical ones, and each view's own size constraints.
        NSMutableArray *horizontal = [NSMutableArray array];
        for (NSLayoutConstraint *k in [pane constraints])
            if ([k isMemberOfClass:[NSLayoutConstraint class]] && !GPXIsVertical([k firstAttribute]) && !GPXIsVertical([k secondAttribute]))
                [horizontal addObject:Described(k, ids, pane)];
        NSMutableArray *own = [NSMutableArray array];
        for (NSView *view in [pane subviews])
            for (NSLayoutConstraint *k in [view constraints])
                if ([k isMemberOfClass:[NSLayoutConstraint class]] && [k firstItem] == view && [k secondItem] == nil)
                    [own addObject:Described(k, ids, pane)];
        NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"views": views, @"horizontal": horizontal, @"own": own,
                                                                @"content": @[@(NSWidth([pane bounds])), @(NSHeight([pane bounds]))],
                                                                @"ambiguous": @([pane hasAmbiguousLayout])}
                                                       options:NSJSONWritingSortedKeys error:nil];
        printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    }
    return 0;
}
'''


def xib_general() -> tuple[ET.Element, dict[str, list[float]], list[dict]]:
    """The General content view, its subviews' frames by id and their own size constraints."""
    _, content, _ = GeneralPaneXib.general_pane(XIB)
    frames, own = {}, []
    for v in content.findall("subviews/*"):
        r = v.find("rect[@key='frame']")
        frames[v.get("id")] = [float(r.get(k)) for k in ("x", "y", "width", "height")]
        for c in v.findall("constraints/constraint"):
            if c.get("secondItem") is None and c.get("firstItem") in (None, v.get("id")):
                own.append({"first": v.get("id"), "fa": c.get("firstAttribute"), "rel": c.get("relation", "equal"),
                            "c": float(c.get("constant", 0)), "prio": float(c.get("priority", 1000))})
    return content, frames, own


def key(c: dict) -> tuple:
    return (c["first"], c["fa"], c.get("second") or "", c.get("sa") or "", c["rel"], round(float(c.get("m", 1)), 4),
            round(float(c["c"]), 2), round(float(c["prio"]), 1))


class PreferencesGeneralXibFramesTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.nib = compiled_nib()
        cls.report = None
        if cls.nib is None:
            return
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-GeneralXibFrames-")
        temp = pathlib.Path(cls.temp.name)
        bundle = temp / "TestResources.bundle"
        resources = bundle / "Contents" / "Resources" / "English.lproj"
        resources.mkdir(parents=True)
        shutil.copytree(cls.nib, resources / "MainMenu.nib")
        (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "org.flycut.tests.generalxibframes-resources", "CFBundlePackageType": "BNDL"}))
        cls.spec = GeneralPaneXib.spec(XIB)
        spec = temp / "xib.json"
        spec.write_text(json.dumps(cls.spec))
        sources = [ROOT / p for p in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
                   if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]
        fixture = temp / "GeneralXibFrames.m"
        fixture.write_text(FIXTURE)
        binary = temp / "GeneralXibFrames"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules", "-DFLYCUT_MAC=1",
                   "-mmacosx-version-min=13.5", "-arch", "arm64", "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(fixture)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "ApplicationServices", "CloudKit"):
            command += ["-framework", framework]
        command += ["-o", str(binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout[-3000:] + build.stderr[-3000:])
        run = subprocess.run([str(binary), str(bundle), str(spec)], cwd=ROOT, text=True, capture_output=True, timeout=120)
        cls.temp.cleanup()
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        if run.returncode != 0 or not reports:
            raise AssertionError(f"exit {run.returncode}: " + run.stdout[-1500:] + run.stderr[-1500:])
        cls.report = json.loads(reports[-1])

    def setUp(self) -> None:
        if self.nib is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")

    def test_every_general_frame_is_where_the_constraints_put_it(self) -> None:
        _, frames, _ = xib_general()
        self.assertFalse(self.report["ambiguous"], "the XIB's constraints leave the General pane ambiguous")
        self.assertEqual(sorted(frames), sorted(self.report["views"]), "views of the XIB and of the laid-out pane differ")
        off = []
        for vid, written in frames.items():
            laid = self.report["views"][vid]
            if any(abs(a - b) > TOLERANCE for a, b in zip(written, laid)):
                off.append(f"{vid}: frame x/y/w/h {written} in the XIB, {[round(v, 2) for v in laid]} laid out")
        print(f"\n{len(frames)} General views, {len(off)} off their constraints")
        self.assertEqual(off, [], f"{len(off)} of {len(frames)} General frames are off their constraints")

    def test_the_pane_is_as_large_as_the_xib_says(self) -> None:
        content, _, _ = xib_general()
        r = content.find("rect[@key='frame']")
        self.assertEqual([float(r.get("width")), float(r.get("height"))], self.report["content"],
                         "the General content view's frame differs from the laid-out pane")

    def test_the_horizontal_constraints_laid_out_are_the_xibs(self) -> None:
        _, _, own = xib_general()
        wanted = sorted(key(c) for c in self.spec["other"])
        laid = sorted(key(c) for c in self.report["horizontal"])
        self.assertEqual(laid, wanted, "x and width would come from other constraints than the XIB's")
        self.assertEqual(sorted(key({**c, "m": 1}) for c in self.report["own"]), sorted(key({**c, "m": 1}) for c in own),
                         "a view's own size constraints differ from the XIB's")


if __name__ == "__main__":
    unittest.main()
