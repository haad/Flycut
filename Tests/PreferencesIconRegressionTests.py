#!/usr/bin/env python3
"""Native regression tests for Flycut's Preferences toolbar icons."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFS_SOURCE = ROOT / "UKPrefsPanel" / "UKPrefsPanel.m"
PROJECT = ROOT / "Flycut.xcodeproj" / "project.pbxproj"
MAIN_MENU_XIB = ROOT / "English.lproj" / "MainMenu.xib"
LEGACY_PREFERENCES_ICONS = (
    "Resources/net.sf.jumpcut.preferences.general.tiff",
    "Resources/net.sf.jumpcut.preferences.hotkey.tiff",
    "Resources/net.sf.jumpcut.preferences.appearance.tiff",
    "Resources/net.sf.jumpcut.preferences.acknowledgements.tiff",
)

FIXTURE = r'''
#import <AppKit/AppKit.h>
#import "UKPrefsPanel.h"

@interface UKPrefsPanel (ToolbarIconTesting)
- (NSToolbarItem *)toolbar:(NSToolbar *)toolbar
       itemForItemIdentifier:(NSString *)itemIdentifier
    willBeInsertedIntoToolbar:(BOOL)willBeInserted;
@end

int main(void) {
    @autoreleasepool {
        NSArray *identifiers = @[
            @"net.sf.jumpcut.preferences.general.tiff",
            @"net.sf.jumpcut.preferences.hotkey.tiff",
            @"net.sf.jumpcut.preferences.appearance.tiff",
            @"com.generalarcade.flycut.32.png"
        ];
        NSArray *labels = @[@"General", @"Hotkeys", @"Appearance", @"Acknowledgements"];
        NSArray *symbolNames = @[@"gearshape", @"keyboard", @"paintpalette", @"person.2"];

        NSTabView *tabView = [[[NSTabView alloc] initWithFrame:NSMakeRect(0, 0, 640, 320)] autorelease];
        NSMutableDictionary *itemsList = [NSMutableDictionary dictionary];
        for (NSUInteger index = 0; index < [identifiers count]; index++) {
            NSTabViewItem *tab = [[[NSTabViewItem alloc] initWithIdentifier:identifiers[index]] autorelease];
            [tab setLabel:labels[index]];
            [tabView addTabViewItem:tab];
            itemsList[identifiers[index]] = labels[index];
        }

        UKPrefsPanel *panel = [[[UKPrefsPanel alloc] init] autorelease];
        [panel setTabView:tabView];
        [panel setValue:itemsList forKey:@"itemsList"];

        for (NSUInteger index = 0; index < [identifiers count]; index++) {
            NSToolbarItem *item = [panel toolbar:nil
                           itemForItemIdentifier:identifiers[index]
                        willBeInsertedIntoToolbar:YES];
            if (item == nil || [item image] == nil) {
                fprintf(stderr, "missing native toolbar image for %s\n", [labels[index] UTF8String]);
                return (int)(11 + index);
            }

            NSImage *expected = [NSImage imageWithSystemSymbolName:symbolNames[index]
                                           accessibilityDescription:labels[index]];
            if (expected == nil) {
                fprintf(stderr, "system symbol unavailable for %s\n", [labels[index] UTF8String]);
                return (int)(21 + index);
            }
            NSData *actualData = [[item image] TIFFRepresentation];
            NSData *expectedData = [expected TIFFRepresentation];
            if (actualData == nil || expectedData == nil || ![actualData isEqualToData:expectedData]) {
                fprintf(stderr, "wrong toolbar symbol for %s\n", [labels[index] UTF8String]);
                return (int)(31 + index);
            }
            if (![[item image] isTemplate]) {
                fprintf(stderr, "toolbar symbol is not a template for %s\n", [labels[index] UTF8String]);
                return (int)(41 + index);
            }
        }
    }
    return 0;
}
'''

SELECTION_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import "UKPrefsPanel.h"

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];

        NSArray *identifiers = @[
            @"net.sf.jumpcut.preferences.general.tiff",
            @"net.sf.jumpcut.preferences.appearance.tiff"
        ];
        NSArray *labels = @[@"General", @"Appearance"];

        NSWindow *window = [[[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 640, 320)
                      styleMask:NSWindowStyleMaskTitled
                        backing:NSBackingStoreBuffered
                          defer:NO] autorelease];
        NSTabView *tabView = [[[NSTabView alloc] initWithFrame:[[window contentView] bounds]] autorelease];
        [[window contentView] addSubview:tabView];

        for (NSUInteger index = 0; index < [identifiers count]; index++) {
            NSTabViewItem *tab = [[[NSTabViewItem alloc] initWithIdentifier:identifiers[index]] autorelease];
            [tab setLabel:labels[index]];
            NSView *view = [[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 640, 320)] autorelease];
            NSBox *box = [[[NSBox alloc] initWithFrame:[view bounds]] autorelease];
            [view addSubview:box];
            [tab setView:view];
            [tabView addTabViewItem:tab];
        }

        UKPrefsPanel *panel = [[[UKPrefsPanel alloc] init] autorelease];
        [panel setTabView:tabView];
        [panel awakeFromNib];

        NSToolbarItem *appearanceItem = nil;
        for (NSToolbarItem *item in [[window toolbar] items]) {
            if ([[item itemIdentifier] isEqualToString:identifiers[1]]) {
                appearanceItem = item;
                break;
            }
        }
        if (appearanceItem == nil) {
            fprintf(stderr, "appearance toolbar item missing\n");
            return 11;
        }

        [panel changePanes:appearanceItem];
        if (![[[tabView selectedTabViewItem] identifier] isEqualToString:identifiers[1]]) {
            fprintf(stderr, "appearance tab was not selected\n");
            return 12;
        }
        if (![[[window toolbar] selectedItemIdentifier] isEqualToString:identifiers[1]]) {
            fprintf(stderr, "toolbar selection did not follow appearance tab\n");
            return 13;
        }
    }
    return 0;
}
'''


class PreferencesIconRegressionTests(unittest.TestCase):
    def test_toolbar_uses_selected_native_system_symbols(self) -> None:
        expected_tabs = [
            ("General", "net.sf.jumpcut.preferences.general.tiff"),
            ("Hotkeys", "net.sf.jumpcut.preferences.hotkey.tiff"),
            ("Appearance", "net.sf.jumpcut.preferences.appearance.tiff"),
            ("Acknowledgements", "com.generalarcade.flycut.32.png"),
        ]
        if MAIN_MENU_XIB.exists():
            production_tabs = [
                (item.get("label"), item.get("identifier"))
                for item in ET.parse(MAIN_MENU_XIB).findall(".//tabViewItem")
            ]
            self.assertEqual(production_tabs, expected_tabs)
        else:
            # Upstream ships compiled NIBs. Read their keyed archives as data,
            # without instantiating AppController or touching user defaults.
            import plistlib
            # The primary keyed archive is a plist; optimized variants are not.
            nibs = [ROOT / "English.lproj/MainMenu.nib/keyedobjects.nib"]
            self.assertTrue(nibs[0].is_file(), "No production XIB or keyed NIB found")
            for nib in nibs:
                objects = plistlib.loads(nib.read_bytes())["$objects"]
                def resolve(value):
                    return objects[value.data] if isinstance(value, plistlib.UID) else value
                tab_views = [item for item in objects
                             if isinstance(item, dict) and "NSTabViewItems" in item]
                self.assertEqual(len(tab_views), 1)
                refs = resolve(tab_views[0]["NSTabViewItems"])["NS.objects"]
                production_tabs = [(resolve(resolve(ref)["NSLabel"]),
                                    resolve(resolve(ref)["NSIdentifier"])) for ref in refs]
                self.assertEqual(production_tabs, expected_tabs, str(nib))

        with tempfile.TemporaryDirectory(prefix="flycut-preferences-icons-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            fixture = temp / "PreferencesIconFixture.m"
            binary = temp / "PreferencesIconFixture"
            fixture.write_text(FIXTURE)

            build = subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "clang",
                    "-fno-objc-arc",
                    "-fblocks",
                    "-fmodules",
                    "-mmacosx-version-min=13.5",
                    "-arch",
                    "arm64",
                    "-I",
                    str(ROOT / "UKPrefsPanel"),
                    str(PREFS_SOURCE),
                    str(fixture),
                    "-framework",
                    "AppKit",
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            run = subprocess.run(
                [str(binary)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_toolbar_selection_follows_selected_preferences_pane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flycut-preferences-selection-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            fixture = temp / "PreferencesSelectionFixture.m"
            binary = temp / "PreferencesSelectionFixture"
            fixture.write_text(SELECTION_FIXTURE)

            build = subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "clang",
                    "-fno-objc-arc",
                    "-fblocks",
                    "-fmodules",
                    "-mmacosx-version-min=13.5",
                    "-arch",
                    "arm64",
                    "-I",
                    str(ROOT / "UKPrefsPanel"),
                    str(PREFS_SOURCE),
                    str(fixture),
                    "-framework",
                    "AppKit",
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            run = subprocess.run(
                [str(binary)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_legacy_preferences_raster_icons_are_removed(self) -> None:
        project = PROJECT.read_text()
        for relative_path in LEGACY_PREFERENCES_ICONS:
            icon = ROOT / relative_path
            self.assertFalse(icon.exists(), f"legacy raster icon remains: {relative_path}")
            self.assertNotIn(icon.name, project)

    def test_project_object_references_resolve(self) -> None:
        project = PROJECT.read_text()
        definitions = set(
            re.findall(r"^\s*([A-F0-9]{24})(?: /\*.*?\*/)? = \{", project, re.MULTILINE)
        )
        references = set(re.findall(r"\b[A-F0-9]{24}\b", project))
        self.assertEqual(references - definitions, set(), "dangling Xcode object references")


if __name__ == "__main__":
    unittest.main()
