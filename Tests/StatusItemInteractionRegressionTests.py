#!/usr/bin/env python3
"""Regression tests for reliable status-item mouse-button routing."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
APP_HEADER = ROOT / "AppController.h"


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


class StatusItemInteractionRegressionTests(unittest.TestCase):
    def test_status_button_routes_left_and_right_mouse_down_before_menu_tracking(self) -> None:
        source = APP_CONTROLLER.read_text()
        header = APP_HEADER.read_text()
        awake = method_body(source, "- (void)awakeFromNib")
        configure = method_body(source, "-(void)configureStatusItemInteraction")
        button_action = method_body(source, "-(IBAction)statusItemButtonPressed:")
        self.assertIn("-(NSEvent *)handleStatusItemMouseDown:", source)
        mouse_filter = method_body(source, "-(NSEvent *)handleStatusItemMouseDown:")
        will_open = method_body(source, "-(void)menuWillOpen:")
        dealloc = method_body(source, "- (void) dealloc")

        self.assertIn("[self configureStatusItemInteraction]", awake)
        self.assertIn("[statusItem setMenu:nil]", configure)
        self.assertIn("[button setTarget:self]", configure)
        self.assertIn("@selector(statusItemButtonPressed:)", configure)
        self.assertIn("NSEventMaskLeftMouseDown", configure)
        self.assertIn("NSEventMaskRightMouseDown", configure)
        self.assertNotIn("NSEventMaskLeftMouseUp", configure)
        self.assertNotIn("NSEventMaskRightMouseUp", configure)
        self.assertIn("statusItemMouseDownMonitor", header)
        self.assertIn("addLocalMonitorForEventsMatchingMask", configure)
        self.assertIn("[event window] != [button window]", mouse_filter)
        self.assertIn("NSPointInRect", mouse_filter)
        self.assertIn("return nil", mouse_filter)
        self.assertNotIn("currentEvent", button_action)
        self.assertIn("[self showStatusItemMenu]", button_action)
        self.assertIn("removeMonitor:statusItemMouseDownMonitor", dealloc)

        self.assertNotIn("[NSEvent modifierFlags]", will_open)
        self.assertNotIn("toggleClipboardTracking", will_open)
        self.assertNotIn("cancelTracking", will_open)

    def test_event_bound_handler_treats_option_left_and_right_click_identically(self) -> None:
        fixture = r'''
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import "AppController.h"

CGEventFlags FCTestCGEventSourceFlagsState(CGEventSourceStateID stateID) {
    (void)stateID;
    return 0;
}

@interface AppController (StatusItemInteractionTesting)
- (void)handleStatusItemEvent:(NSEvent *)event;
- (void)showStatusItemMenu;
@end

@interface FCStatusItemInteractionController : AppController {
    NSInteger _toggleCount;
    NSInteger _menuCount;
}
@property(nonatomic, assign) NSInteger toggleCount;
@property(nonatomic, assign) NSInteger menuCount;
@end

@implementation FCStatusItemInteractionController
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

static NSEvent *MouseDown(NSEventType type, NSEventModifierFlags flags, NSInteger eventNumber) {
    return [NSEvent mouseEventWithType:type
                             location:NSZeroPoint
                        modifierFlags:flags
                            timestamp:(NSTimeInterval)eventNumber
                         windowNumber:0
                              context:nil
                          eventNumber:eventNumber
                           clickCount:1
                             pressure:1.0];
}

static int VerifyEvent(NSEvent *event, NSInteger expectedToggles, NSInteger expectedMenus) {
    FCStatusItemInteractionController *controller = [[FCStatusItemInteractionController alloc] init];
    if (![controller respondsToSelector:@selector(handleStatusItemEvent:)]) {
        [controller release];
        return 10;
    }

    [controller handleStatusItemEvent:event];
    int result = 0;
    if (controller.toggleCount != expectedToggles)
        result = 20;
    else if (controller.menuCount != expectedMenus)
        result = 21;
    [controller release];
    return result;
}

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];

        int result = VerifyEvent(MouseDown(NSEventTypeRightMouseDown,
                                           NSEventModifierFlagOption, 1), 1, 0);
        if (result != 0) return 100 + result;

        result = VerifyEvent(MouseDown(NSEventTypeLeftMouseDown,
                                       NSEventModifierFlagOption, 2), 1, 0);
        if (result != 0) return 200 + result;

        result = VerifyEvent(MouseDown(NSEventTypeRightMouseDown, 0, 3), 0, 1);
        if (result != 0) return 300 + result;

        result = VerifyEvent(MouseDown(NSEventTypeLeftMouseDown, 0, 4), 0, 1);
        if (result != 0) return 400 + result;

        // Programmatic and Accessibility activation has no mouse event but must
        // retain the ordinary menu-opening behavior.
        result = VerifyEvent(nil, 0, 1);
        if (result != 0) return 500 + result;
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

        with tempfile.TemporaryDirectory(prefix="flycut-status-item-interaction-") as directory:
            source = pathlib.Path(directory) / "StatusItemInteractionFixture.m"
            binary = pathlib.Path(directory) / "StatusItemInteractionFixture"
            source.write_text(fixture)
            command = [
                "/usr/bin/xcrun",
                "clang",
                "-fno-objc-arc",
                "-fobjc-weak",
                "-fblocks",
                "-fmodules",
                "-DFLYCUT_MAC=1",
                "-DCGEventSourceFlagsState=FCTestCGEventSourceFlagsState",
                "-mmacosx-version-min=13.5",
                "-arch",
                "arm64",
                "-include",
                str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(path) for path in sources)
            command.append(str(source))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])

            build = subprocess.run(
                command,
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
            self.assertEqual(
                run.returncode,
                0,
                f"status-item event matrix failed with exit {run.returncode}\n{run.stderr}",
            )

    def test_real_status_button_tracks_each_mouse_button_once(self) -> None:
        fixture_source = ROOT / "Tests" / "Fixtures" / "StatusItemWindowEventProbe.m"
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

        with tempfile.TemporaryDirectory(prefix="flycut-status-button-window-event-") as directory:
            binary = pathlib.Path(directory) / "StatusItemWindowEventProbe"
            command = [
                "/usr/bin/xcrun",
                "clang",
                "-fno-objc-arc",
                "-fobjc-weak",
                "-fblocks",
                "-fmodules",
                "-DFLYCUT_MAC=1",
                "-mmacosx-version-min=13.5",
                "-arch",
                "arm64",
                "-include",
                str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(path) for path in sources)
            command.append(str(fixture_source))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])

            build = subprocess.run(
                command,
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
            self.assertEqual(
                run.returncode,
                0,
                f"status-button window event matrix failed with exit {run.returncode}\n"
                f"{run.stdout}{run.stderr}",
            )
            self.assertIn("STATUS_ITEM_WINDOW_EVENT_MATRIX=PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
