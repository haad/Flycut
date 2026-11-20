#!/usr/bin/env python3
"""Keep the menu-bar native fixtures away from real preferences and the menu bar.

Every native fixture of the menu-bar test modules imports
Tests/Fixtures/FixtureIsolation.h. These tests pin that rule and check the
header itself: defaults stay in process memory, writes that reach a real
NSUserDefaults object stop the fixture, and the status-item stand-in is an
off-screen, non-activating panel that is never shown.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
ISOLATION_HEADER = FIXTURES / "FixtureIsolation.h"
FIXTURE_ISOLATION_EXIT = 86
MENU_BAR_TEST_MODULES = (
    ROOT / "Tests" / "MenuBarIconRegressionTests.py",
    ROOT / "Tests" / "MenuBarIconColorRegressionTests.py",
    ROOT / "Tests" / "StatusItemInteractionRegressionTests.py",
)
MENU_BAR_FIXTURE_FILES = (FIXTURES / "StatusItemWindowEventProbe.m",)
FORBIDDEN = (
    ("systemStatusBar", "creates a real menu-bar item"),
    ("initWithSuiteName", "opens a real preferences suite"),
    ("PersistentDomain", "writes a real preferences domain"),
    ("CFPreferences", "bypasses the in-memory defaults"),
)

PROBE = r'''
#import <AppKit/AppKit.h>
#import "FixtureIsolation.h"

static int Check(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    if (![defaults isMemberOfClass:[FCMemoryDefaults class]] ||
        defaults != [NSUserDefaults standardUserDefaults])
        return 10;
    [defaults registerDefaults:@{@"registered": @7}];
    if ([defaults integerForKey:@"registered"] != 7) return 11;
    [defaults setInteger:9 forKey:@"registered"];
    if ([defaults integerForKey:@"registered"] != 9) return 12;
    [defaults removeObjectForKey:@"registered"];
    if ([defaults integerForKey:@"registered"] != 7) return 13;
    [defaults setBool:YES forKey:@"flag"];
    if (![defaults boolForKey:@"flag"] || [defaults arrayForKey:@"flag"] != nil) return 14;
    [defaults setObject:@[@1, @2] forKey:@"list"];
    if ([[defaults arrayForKey:@"list"] count] != 2 || [defaults stringArrayForKey:@"list"] != nil)
        return 15;
    if (![[defaults valueForKey:@"list"] isEqual:[defaults objectForKey:@"list"]]) return 16;

    const char *required[] = {"setObject:forKey:", "removeObjectForKey:", "setBool:forKey:",
                              "setPersistentDomain:forName:", "removePersistentDomainForName:"};
    for (size_t index = 0; index < sizeof(required) / sizeof(required[0]); index++) {
        if (class_getMethodImplementation([NSUserDefaults class], sel_registerName(required[index])) !=
            (IMP)FCRealDefaultsWrite)
            return 17;
    }
    unsigned int count = 0;
    unsigned int trapped = 0;
    Method *methods = class_copyMethodList([NSUserDefaults class], &count);
    for (unsigned int index = 0; index < count; index++) {
        if (!FCIsPersistingDefaultsSelector(method_getName(methods[index])))
            continue;
        if (method_getImplementation(methods[index]) != (IMP)FCRealDefaultsWrite) {
            free(methods);
            return 18;
        }
        trapped++;
    }
    free(methods);

    [NSApplication sharedApplication];
    FCOffscreenStatusItem *item = [[[FCOffscreenStatusItem alloc] initWithLength:30.0] autorelease];
    NSWindow *host = [item hostWindow];
    if ([[item button] window] != host || [host windowNumber] <= 0) return 19;
    if ([host isVisible] || NSMaxX([host frame]) > -10000.0 || NSMaxY([host frame]) > -10000.0) return 20;
    if (([host styleMask] & NSWindowStyleMaskNonactivatingPanel) == 0 || [host canBecomeKeyWindow])
        return 21;
    printf("FIXTURE_ISOLATION_CHECK=PASS trapped=%u\n", trapped);
    return 0;
}

static int Trip(void)
{
    // Never attempt the real write unless the tripwire is installed.
    if (class_getMethodImplementation([NSUserDefaults class], @selector(setBool:forKey:)) !=
        (IMP)FCRealDefaultsWrite)
        return 30;
    NSUserDefaults *real = [[NSUserDefaults alloc] init];
    [real setBool:YES forKey:@"FixtureIsolationTripwire"];
    [real release];
    return 31;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc == 2 && strcmp(argv[1], "check") == 0)
            return Check();
        if (argc == 2 && strcmp(argv[1], "trip") == 0)
            return Trip();
    }
    return 2;
}
'''


def native_fixtures() -> list[tuple[str, str]]:
    fixtures = []
    for module in MENU_BAR_TEST_MODULES:
        for index, source in enumerate(re.findall(r"r'''(.*?)'''", module.read_text(), re.S)):
            if "int main(" in source:
                fixtures.append((f"{module.name}#{index}", source))
    for path in MENU_BAR_FIXTURE_FILES:
        fixtures.append((path.name, path.read_text()))
    return fixtures


class FixtureIsolationRegressionTests(unittest.TestCase):
    def test_menu_bar_native_fixtures_use_the_isolation_header(self) -> None:
        fixtures = native_fixtures()
        self.assertGreaterEqual(len(fixtures), 7)
        for name, source in fixtures:
            with self.subTest(fixture=name):
                self.assertTrue('#import "FixtureIsolation.h"' in source,
                                f"{name} does not import FixtureIsolation.h")
                self.assertIsNone(re.search(r"@interface\s+\w+\s*:\s*NSUserDefaults\b", source),
                                  f"{name} defines its own defaults class; use FCMemoryDefaults")
                for token, reason in FORBIDDEN:
                    self.assertFalse(token in source, f"{name} uses {token}, which {reason}")

    def test_isolation_header_keeps_defaults_in_memory_and_stops_real_writes(self) -> None:
        self.assertTrue(ISOLATION_HEADER.is_file())
        with tempfile.TemporaryDirectory(prefix="flycut-fixture-isolation-") as directory:
            source = pathlib.Path(directory) / "FixtureIsolationProbe.m"
            binary = pathlib.Path(directory) / "FixtureIsolationProbe"
            source.write_text(PROBE)
            build = subprocess.run(
                ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fblocks", "-fmodules",
                 "-mmacosx-version-min=13.5", "-arch", "arm64", "-I", str(FIXTURES),
                 str(source), "-framework", "AppKit", "-o", str(binary)],
                cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            check = subprocess.run([str(binary), "check"], cwd=ROOT, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn("FIXTURE_ISOLATION_CHECK=PASS", check.stdout)

            # Only reached when the check above proved the tripwire is installed.
            trip = subprocess.run([str(binary), "trip"], cwd=ROOT, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(trip.returncode, FIXTURE_ISOLATION_EXIT, trip.stdout + trip.stderr)
            self.assertIn("FixtureIsolation: -[NSUserDefaults setBool:forKey:] reached a real",
                          trip.stderr)


if __name__ == "__main__":
    unittest.main()
