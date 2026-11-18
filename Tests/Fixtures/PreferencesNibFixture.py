"""Shared NIB fixture for the Preferences tests (imported, not a test file itself).

Loads the production MainMenu NIB (the tree's compiled English.lproj/MainMenu.nib, or the
one of FLYCUT_TEST_RESOURCE_BUNDLE for trees that carry only MainMenu.xib) with
-[AppController awakeFromNib] and -[UKPrefsPanel awakeFromNib] swapped for no-ops, then
sends every -build... message that the production -[AppController awakeFromNib] sends
(read from AppController.m, in order), so code placed in such a builder runs as at launch.
FixtureIsolation.h keeps user defaults in memory; SGHotKeyCenter registration,
-updateMenu, the image store and the file-writing -saveFromStore:atIndex:withPrefix: are
replaced; the window is never ordered in.

A test class sets FIXTURE (Objective-C appended to PRELUDE, with its own main()) and
NAME. Modes listed in NO_NIB_MODES run without a NIB; the others skip when none is found.
"""
from __future__ import annotations

import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "Tests" / "Fixtures"


def method_body(source: str, signature: str) -> str:
    start = source.index(signature + "\n{")
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1


def awake_builders() -> list[str]:
    body = method_body((ROOT / "AppController.m").read_text(), "- (void)awakeFromNib")
    names: list[str] = []
    for name in re.findall(r"\[self (build\w+)\]", body):
        if name not in names:
            names.append(name)
    return names


def compiled_nib() -> pathlib.Path | None:
    configured = os.environ.get("FLYCUT_TEST_RESOURCE_BUNDLE")
    nib = (pathlib.Path(configured) / "Contents" / "Resources" / "English.lproj" / "MainMenu.nib"
           if configured else ROOT / "English.lproj" / "MainMenu.nib")
    return nib if nib.is_dir() else None


PRELUDE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "UKPrefsPanel.h"
#import "SGHotKeyCenter.h"
#import "SGHotKey.h"
#import "FlycutOperator.h"
#import "FlycutStore.h"
#import "FlycutClipping.h"

static void Noop(id self, SEL cmd) { (void)self; (void)cmd; }
static void NoopArg(id self, SEL cmd, id arg) { (void)self; (void)cmd; (void)arg; }
static BOOL FakeRegister(id self, SEL cmd, id hotKey) { (void)self; (void)cmd; (void)hotKey; return YES; }
static id AbortSharedStore(id self, SEL cmd) { fprintf(stderr, "image store reached\n"); _exit(98); }
static BOOL ForbiddenSave(id self, SEL cmd, id store, int index, id prefix) {
    fprintf(stderr, "-saveFromStore:atIndex:withPrefix: reached (writes files)\n"); _exit(97);
}

static NSWindow *window;
static UKPrefsPanel *prefs;
static AppController *controller;
static NSInteger generalPane = NSNotFound, hotkeysPane = NSNotFound, appearancePane = NSNotFound;

static void ChangePane(NSInteger index)
{
    NSButton *sender = [[[NSButton alloc] init] autorelease];
    [sender setTag:index];
    [prefs changePanes:sender];
    [[window contentView] layoutSubtreeIfNeeded];
}

static NSView *PaneView(NSInteger index)
{
    if (index == generalPane) {
        NSView *label = [controller valueForKey:@"savingSectionLabel"];
        if ([label superview] != nil) return [label superview];
    }
    if (index == appearancePane) {
        NSView *panel = [controller valueForKey:@"appearancePanel"];
        if (panel != nil) return panel;
    }
    return [[[prefs tabView] tabViewItemAtIndex:index] view];
}

static NSString *BoundKeyPath(NSView *view)
{
    for (NSString *name in @[NSValueBinding, NSSelectedIndexBinding, NSSelectedTagBinding, NSSelectedValueBinding, NSSelectedObjectBinding]) {
        NSString *keyPath = [[view infoForBinding:name] objectForKey:NSObservedKeyPathKey];
        if (keyPath != nil) return keyPath;
    }
    return nil;
}

static void SendBuilders(const char *list)
{
    for (NSString *name in [[NSString stringWithUTF8String:list] componentsSeparatedByString:@","]) {
        if ([name length] == 0) continue;
        SEL selector = NSSelectorFromString(name);
        if ([controller respondsToSelector:selector])
            ((void (*)(id, SEL))objc_msgSend)(controller, selector);
    }
}

// Runs once the NIB is loaded, before the builders (NULL: nothing). A case uses it to
// set up what a NIB compiled from a newer MainMenu.xib would have.
static void (*BeforeBuilders)(void);

// The account-sharing section lists this Mac's login accounts. In these fixtures
// it lists FixtureLoginAccounts (dummy names, none by default), never the real
// ones: +[FlycutAccountShareService localLoginAccounts] is replaced before any
// builder runs.
static NSArray *FixtureLoginAccounts = nil;
static NSArray *FixtureLocalLoginAccounts(id self, SEL cmd) { (void)self; (void)cmd; return FixtureLoginAccounts ?: @[]; }

static void InstallBoundaries(void)
{
    Class share = NSClassFromString(@"FlycutAccountShareService");
    Method accounts = share ? class_getClassMethod(share, NSSelectorFromString(@"localLoginAccounts")) : NULL;
    if (accounts) method_setImplementation(accounts, (IMP)FixtureLocalLoginAccounts);
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
    method_setImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)), (IMP)Noop);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
    method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)NoopArg);
    Method updateMenu = class_getInstanceMethod([AppController class], NSSelectorFromString(@"updateMenu"));
    if (updateMenu) method_setImplementation(updateMenu, (IMP)Noop);
    Class imageStore = NSClassFromString(@"FlycutImageStore");
    if (imageStore) method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)AbortSharedStore);
    method_setImplementation(class_getInstanceMethod([FlycutOperator class], @selector(saveFromStore:atIndex:withPrefix:)), (IMP)ForbiddenSave);
    [NSApplication sharedApplication];
    [[[FlycutOperator alloc] init] autorelease];     // registers the operator's defaults, as awakeFromNib does
}

// argv[1] bundle with Contents/Resources/English.lproj/MainMenu.nib, argv[2] mode,
// argv[3] comma-separated builder selectors from -awakeFromNib, argv[4...] the case's own.
static int LoadNib(int argc, const char **argv)
{
    if (argc < 4) return 2;
    if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
    InstallBoundaries();
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
    if (BeforeBuilders) BeforeBuilders();
    SendBuilders(argv[3]);
    [prefs mapTabsToToolbar];
    NSTabView *tabs = [prefs tabView];
    generalPane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"];
    hotkeysPane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.hotkey.tiff"];
    appearancePane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.appearance.tiff"];
    if (generalPane == NSNotFound || hotkeysPane == NSNotFound || appearancePane == NSNotFound) return 12;
    return 0;
}

static void Emit(NSDictionary *report)
{
    NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
    printf("REPORT %s\n", [[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] autorelease] UTF8String]);
    fflush(stdout);
}
'''


class PreferencesNibCase(unittest.TestCase):
    """Builds PRELUDE + FIXTURE once per class against the tree's app sources."""

    FIXTURE = ""
    NAME = "PreferencesNibFixture"
    NO_NIB_MODES: tuple[str, ...] = ()
    # Extra compiler flags for every source of the fixture binary (production code included).
    EXTRA_CFLAGS: tuple[str, ...] = ()

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix=f"flycut-{cls.NAME}-")
        temp = pathlib.Path(cls.temp.name)
        cls.bundle = temp / "TestResources.bundle"
        nib = compiled_nib()
        cls.nib_source = str(nib) if nib else None
        resources = cls.bundle / "Contents" / "Resources" / "English.lproj"
        resources.mkdir(parents=True)
        if nib:
            shutil.copytree(nib, resources / "MainMenu.nib")
        (cls.bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": f"org.flycut.tests.{cls.NAME.lower()}-resources", "CFBundlePackageType": "BNDL"}))
        sources = [ROOT / p for p in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
                   if p != "main.m" and not p.startswith(("FlycutHelper/", "Tests/"))]
        fixture = temp / f"{cls.NAME}.m"
        fixture.write_text(PRELUDE + cls.FIXTURE)
        cls.binary = temp / cls.NAME
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules", "-DFLYCUT_MAC=1",
                   "-mmacosx-version-min=13.5", "-arch", "arm64", "-include", str(ROOT / "Flycut_Prefix.pch"),
                   *cls.EXTRA_CFLAGS]
        for include in sorted({ROOT, FIXTURES, *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(fixture)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
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

    def run_mode(self, mode: str, message: str, extra: tuple[str, ...] = ()) -> None:
        if mode not in self.NO_NIB_MODES and self.nib_source is None:
            self.skipTest("no compiled MainMenu.nib; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        run = subprocess.run([str(self.binary), str(self.bundle), mode, self.builders, *extra], cwd=ROOT, text=True,
                             capture_output=True, timeout=90)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        print(f"\n{mode}: exit={run.returncode} nib={self.nib_source} "
              f"{reports[-1] if reports else '(no report)'}")
        self.assertEqual(run.returncode, 0, f"{message}; exit={run.returncode}; "
                         f"{reports[-1] if reports else (run.stdout[-1500:] + run.stderr[-1500:])}")
