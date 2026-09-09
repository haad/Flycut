#!/usr/bin/env python3
"""Regression tests for Flycut's adaptive clipboard-tracking menu-bar UI."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
APP_HEADER = ROOT / "AppController.h"
ICON_HEADER = ROOT / "FlycutMenuIcon.h"
ICON_SOURCE = ROOT / "FlycutMenuIcon.m"
PROJECT = ROOT / "Flycut.xcodeproj" / "project.pbxproj"


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    # A matching forward declaration is not the method implementation.
    while ";" in source[start:brace]:
        start = source.index(signature, start + len(signature))
        brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated method: {signature}")


class MenuBarIconRegressionTests(unittest.TestCase):
    def test_clipping_stack_images_are_distinct_menu_bar_templates(self) -> None:
        fixture = r'''
#import <AppKit/AppKit.h>
#import "FlycutMenuIcon.h"

int main(void) {
    @autoreleasepool {
        NSImage *active = [FlycutMenuIcon imageForPaused:NO];
        NSImage *paused = [FlycutMenuIcon imageForPaused:YES];
        if (active == nil || paused == nil) return 1;
        if (![active isTemplate] || ![paused isTemplate]) return 2;
        if (!NSEqualSizes([active size], [paused size])) return 3;
        if ([active size].height > 18.0 || [active size].width > 24.0) return 4;
        if ([active size].height < 16.0 || [active size].width < 16.0) return 5;
        NSData *activeData = [active TIFFRepresentation];
        NSData *pausedData = [paused TIFFRepresentation];
        if (activeData == nil || pausedData == nil) return 6;
        if ([activeData isEqualToData:pausedData]) return 7;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="flycut-menu-icon-") as tmp:
            tmp_path = pathlib.Path(tmp)
            source = tmp_path / "MenuBarIconFixture.m"
            binary = tmp_path / "MenuBarIconFixture"
            source.write_text(fixture)
            compile_result = subprocess.run(
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
                    str(ROOT),
                    str(source),
                    str(ICON_SOURCE),
                    "-framework",
                    "AppKit",
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(binary)], text=True, capture_output=True, timeout=30
            )
            self.assertEqual(
                run_result.returncode,
                0,
                run_result.stdout + run_result.stderr,
            )

    def test_active_has_writing_lines_while_paused_has_only_slash(self) -> None:
        source = ICON_SOURCE.read_text()
        method = method_body(source, "+(NSImage *)imageForPaused:(BOOL)paused tintColor:")

        self.assertIn("DrawClippingStackPages", method)
        self.assertRegex(
            method,
            r"if\s*\(\s*!paused\s*\)\s*\{[^}]*DrawClippingTextLines",
        )
        self.assertRegex(
            method,
            r"if\s*\(\s*paused\s*\)\s*\{[^}]*DrawPauseSlash",
        )
        self.assertIn("setTemplate:tintColor == nil", method)

    def test_pause_slash_rises_from_bottom_left_to_top_right(self) -> None:
        source = ICON_SOURCE.read_text()
        icon_factory = method_body(source, "+(NSImage *)imageForPaused:(BOOL)paused tintColor:")
        slash = method_body(source, "static void DrawPauseSlash")

        # imageWithSize:flipped:NO uses the standard AppKit coordinate system:
        # y increases upward, so these endpoints rise from bottom-left to top-right.
        self.assertIn("flipped:NO", icon_factory)
        self.assertRegex(
            slash,
            r"moveToPoint:NSMakePoint\(\s*2\.3\s*,\s*2\.3\s*\)",
        )
        self.assertRegex(
            slash,
            r"lineToPoint:NSMakePoint\(\s*15\.7\s*,\s*15\.7\s*\)",
        )

    def test_controller_uses_operator_state_for_icon_and_menu_text(self) -> None:
        source = APP_CONTROLLER.read_text()
        header = APP_HEADER.read_text()
        setter = method_body(source, "-(void)setClipboardTrackingPaused:")
        toggle = method_body(source, "-(IBAction)toggleClipboardTracking:")
        icon = method_body(source, "-(void)updateMenuBarIcon")
        menu_text = method_body(source, "-(void)updateClipboardTrackingMenuItem")

        self.assertIn("[flycutOperator setDisableStoreTo:paused]", setter)
        self.assertIn("[self updateMenuBarIcon]", setter)
        self.assertIn("[self updateClipboardTrackingMenuItem]", setter)
        self.assertIn("[flycutOperator storeDisabled]", toggle)
        self.assertIn("[flycutOperator storeDisabled]", icon)
        self.assertIn("[FlycutMenuIcon imageForPaused:paused tintColor:tintColor]", icon)
        self.assertIn("statusItem.button.contentTintColor = nil", icon)
        self.assertIn("[flycutOperator storeDisabled]", menu_text)
        self.assertIn('@"Pause Clipboard Tracking"', source)
        self.assertIn('@"Resume Clipboard Tracking"', source)
        self.assertNotIn("statusItemShowsDisabled", header)

    def test_option_click_does_not_sample_modifiers_during_menu_tracking(self) -> None:
        source = APP_CONTROLLER.read_text()
        header = APP_HEADER.read_text()
        will_open = method_body(source, "-(void)menuWillOpen:")

        self.assertNotIn("[NSEvent modifierFlags]", will_open)
        self.assertNotIn("[NSApp currentEvent]", will_open)
        self.assertNotIn("NSEventModifierFlagOption", will_open)
        self.assertNotIn("toggleClipboardTracking", will_open)
        self.assertNotIn("cancelTracking", will_open)
        self.assertIn("statusItemMouseDownMonitor", header)
        self.assertIn("addLocalMonitorForEventsMatchingMask", source)
        self.assertIn("removeMonitor:statusItemMouseDownMonitor", source)

    def test_option_click_uses_live_modifier_state_when_appkit_drops_event_flags(self) -> None:
        fixture = r'''
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import "AppController.h"

CGEventFlags FCTestCGEventSourceFlagsState(CGEventSourceStateID stateID) {
    return stateID == kCGEventSourceStateCombinedSessionState
        ? kCGEventFlagMaskAlternate
        : 0;
}

@interface AppController (StatusItemTesting)
- (void)handleStatusItemEvent:(NSEvent *)event;
- (void)showStatusItemMenu;
@end

@interface FCStatusItemTestController : AppController {
    NSUInteger _toggleCount;
    NSUInteger _menuCount;
}
@property(nonatomic, assign) NSUInteger toggleCount;
@property(nonatomic, assign) NSUInteger menuCount;
@end

@implementation FCStatusItemTestController
@synthesize toggleCount = _toggleCount;
@synthesize menuCount = _menuCount;
- (IBAction)toggleClipboardTracking:(id)sender {
    (void)sender;
    self.toggleCount += 1;
}
- (void)showStatusItemMenu {
    self.menuCount += 1;
}
@end

int main(void) {
    @autoreleasepool {
        FCStatusItemTestController *controller = [[FCStatusItemTestController alloc] init];
        NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown
                                             location:NSZeroPoint
                                        modifierFlags:0
                                            timestamp:0
                                         windowNumber:0
                                              context:nil
                                          eventNumber:1
                                           clickCount:1
                                             pressure:1.0];
        [controller handleStatusItemEvent:event];
        if (controller.toggleCount != 1) return 10;
        if (controller.menuCount != 0) return 11;
        [controller release];
    }
    return 0;
}
'''
        relative_sources = [
            pathlib.Path(path)
            for path in subprocess.check_output(
                ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True
            ).splitlines()
            if path != "main.m"
            and not path.startswith("FlycutHelper/")
            and not path.startswith("Tests/")
        ]
        icon_source = pathlib.Path("FlycutMenuIcon.m")
        if icon_source not in relative_sources:
            relative_sources.append(icon_source)
        sources = [ROOT / path for path in relative_sources]
        include_dirs = sorted({ROOT, *(path.parent for path in sources)})

        with tempfile.TemporaryDirectory(prefix="flycut-option-click-") as directory:
            source = pathlib.Path(directory) / "OptionClickFixture.m"
            binary = pathlib.Path(directory) / "OptionClickFixture"
            source.write_text(fixture)
            command = [
                "/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak",
                "-fblocks", "-fmodules", "-DFLYCUT_MAC=1",
                "-DCGEventSourceFlagsState=FCTestCGEventSourceFlagsState",
                "-mmacosx-version-min=13.5", "-arch", "arm64",
                "-include", str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(path) for path in sources)
            command.append(str(source))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])
            build = subprocess.run(
                command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=300,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30,
            )
            self.assertEqual(
                run.returncode, 0,
                f"Option-click did not use the live modifier state; exit={run.returncode}\n{run.stderr}",
            )

    def test_background_capture_does_not_call_removed_icon_toggle(self):
        source = (ROOT / "AppController.m").read_text()
        self.assertEqual(source.count("[self toggleMenuIconDisabled]"), 0)

    def test_pause_resume_menu_item_is_visible_and_dynamic(self):
        source = APP_CONTROLLER.read_text()
        header = APP_HEADER.read_text()
        setup = method_body(source, "-(void)setupClipboardTrackingMenuItem")

        self.assertIn("clipboardTrackingMenuItem", header)
        self.assertIn("initWithTitle:@\"Pause Clipboard Tracking\"", setup)
        self.assertIn("@selector(toggleClipboardTracking:)", setup)
        self.assertIn("insertItem:clipboardTrackingMenuItem", setup)
        self.assertIn("[self updateClipboardTrackingMenuItem]", setup)

    def test_obsolete_scissors_style_preference_is_removed(self) -> None:
        source = APP_CONTROLLER.read_text()
        for obsolete in (
            "System scissors",
            "Bold system scissors",
            "White scissors",
            "Black scissors",
            "pause.circle",
            'imageWithSystemSymbolName:@"scissors"',
        ):
            self.assertNotIn(obsolete, source)
        self.assertNotIn("switchMenuIcon:", source)

    def test_icon_implementation_is_part_of_the_xcode_target(self) -> None:
        project = PROJECT.read_text()
        self.assertGreaterEqual(len(re.findall(r"FlycutMenuIcon\.m", project)), 3)
        self.assertGreaterEqual(len(re.findall(r"FlycutMenuIcon\.h", project)), 2)


if __name__ == "__main__":
    unittest.main()
