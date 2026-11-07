#!/usr/bin/env python3
"""Regression tests for Escape handling in the clipping bezel."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Unclosed method: {signature}")


class BezelEscapeRegressionTests(unittest.TestCase):
    def test_appkit_can_deliver_escape_keycode_without_characters(self) -> None:
        harness = r'''
#import <AppKit/AppKit.h>

int main(void) {
    @autoreleasepool {
        NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown
                                         location:NSZeroPoint
                                    modifierFlags:0
                                        timestamp:0
                                     windowNumber:0
                                          context:nil
                                       characters:@""
                      charactersIgnoringModifiers:@""
                                         isARepeat:NO
                                           keyCode:53];
        if ([event keyCode] != 53) return 1;
        if ([[event charactersIgnoringModifiers] length] != 0) return 2;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "escape_event.m"
            binary = pathlib.Path(directory) / "escape_event"
            source.write_text(harness)
            subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "clang",
                    "-fobjc-arc",
                    "-framework",
                    "AppKit",
                    str(source),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run([str(binary)], check=True)

    def test_production_handles_escape_keycode_before_reading_characters(self) -> None:
        source = APP_CONTROLLER.read_text()
        method = method_body(source, "- (void)processBezelKeyDown:")

        keycode_check = "[theEvent keyCode] == 53"
        character_read = "characterAtIndex:0"
        self.assertIn(keycode_check, method)
        self.assertIn(character_read, method)
        self.assertLess(method.index(keycode_check), method.index(character_read))

    def test_production_guards_empty_character_events(self) -> None:
        source = APP_CONTROLLER.read_text()
        method = method_body(source, "- (void)processBezelKeyDown:")

        empty_guard = "[characters length] == 0"
        character_read = "characterAtIndex:0"
        self.assertIn(empty_guard, method)
        self.assertIn(character_read, method)
        self.assertLess(method.index(empty_guard), method.index(character_read))

    def test_escape_cancels_pending_paste_and_restores_store(self) -> None:
        fixture = r'''
#import <Cocoa/Cocoa.h>
#import <string.h>
#import "AppController.h"

@interface AppController (BezelCancelTesting)
- (void)metaKeysReleased;
- (void)processBezelKeyDown:(NSEvent *)event;
@end

@interface FCBezelCancelController : AppController {
    int _pasteCount;
    int _restoreCount;
    int _hideCount;
}
@property(nonatomic, assign) int pasteCount;
@property(nonatomic, assign) int restoreCount;
@property(nonatomic, assign) int hideCount;
- (void)configureDisplayed:(BOOL)displayed pinned:(BOOL)pinned;
@end

@implementation FCBezelCancelController
@synthesize pasteCount = _pasteCount;
@synthesize restoreCount = _restoreCount;
@synthesize hideCount = _hideCount;

- (void)configureDisplayed:(BOOL)displayed pinned:(BOOL)pinned {
    isBezelDisplayed = displayed;
    isBezelPinned = pinned;
}

- (void)pasteFromStack {
    self.pasteCount += 1;
}

- (void)restoreStashedStoreAndUpdate {
    self.restoreCount += 1;
}

- (void)hideApp {
    self.hideCount += 1;
    isBezelDisplayed = NO;
    isBezelPinned = NO;
}
@end

static NSEvent *EscapeEvent(unsigned short keyCode, NSString *characters) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown
                            location:NSZeroPoint
                       modifierFlags:0
                           timestamp:0
                        windowNumber:0
                             context:nil
                          characters:characters
         charactersIgnoringModifiers:characters
                            isARepeat:NO
                              keyCode:keyCode];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        FCBezelCancelController *controller = [[FCBezelCancelController alloc] init];

        if (strcmp(argv[1], "meta") == 0) {
            [controller configureDisplayed:YES pinned:NO];
            [controller metaKeysReleased];
            if (controller.pasteCount != 1) return 21;

            [controller configureDisplayed:YES pinned:YES];
            [controller metaKeysReleased];
            if (controller.pasteCount != 1) return 22;

            [controller configureDisplayed:NO pinned:NO];
            [controller metaKeysReleased];
            if (controller.pasteCount != 1) return 23;
            return 0;
        }

        if (strcmp(argv[1], "escape") == 0) {
            [controller configureDisplayed:YES pinned:NO];
            [controller processBezelKeyDown:EscapeEvent(53, @"")];
            if (controller.restoreCount != 1 || controller.hideCount != 1 ||
                controller.pasteCount != 0) return 31;

            [controller configureDisplayed:YES pinned:NO];
            [controller processBezelKeyDown:EscapeEvent(1, @"\033")];
            if (controller.restoreCount != 2 || controller.hideCount != 2 ||
                controller.pasteCount != 0) return 32;
            return 0;
        }
    }
    return 3;
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
        sources = [ROOT / path for path in relative_sources]
        include_dirs = sorted({ROOT, *(path.parent for path in sources)})

        with tempfile.TemporaryDirectory(prefix="flycut-bezel-cancel-") as directory:
            source = pathlib.Path(directory) / "BezelCancelFixture.m"
            binary = pathlib.Path(directory) / "BezelCancelFixture"
            source.write_text(fixture)
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
            self.assertEqual(build.returncode, 0, build.stderr)

            expected = {
                "meta": "hidden bezel triggered a modifier-release paste",
                "escape": "Escape did not restore the store and cancel the paste",
            }
            for mode, message in expected.items():
                with self.subTest(mode=mode):
                    run = subprocess.run(
                        [str(binary), mode],
                        cwd=ROOT,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                    )
                    self.assertEqual(run.returncode, 0, f"{message}; exit={run.returncode}")


class BezelPendingPasteRegressionTests(unittest.TestCase):
    """Real pasteFromStack/processBezelKeyDown run-loop lifecycle.

    The fixture links every production source and replaces only OS
    boundaries (event posting, permission check, keyboard layout, NSApp,
    pasteboard, preferences storage). It never posts input or touches TCC, and
    it aborts if a case reaches the real image store or general pasteboard.
    """

    FIXTURE = ROOT / "Tests/Fixtures/BezelPendingPaste.m"

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-bezel-pending-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name).resolve() / "BezelPendingPaste"
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        sources = [
            ROOT / path
            for path in subprocess.check_output(
                ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True
            ).splitlines()
            if path != "main.m"
            and not path.startswith("FlycutHelper/")
            and not path.startswith("Tests/")
        ]
        cls.binary = cls.artifacts / "BezelPendingPaste"
        command = [
            "/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
            "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
            "-include", str(ROOT / "Flycut_Prefix.pch"),
        ]
        for include_dir in sorted({ROOT, *(path.parent for path in sources)}):
            command.extend(["-I", str(include_dir)])
        command.extend(str(path) for path in sources)
        command.append(str(cls.FIXTURE))
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command.extend(["-framework", framework])
        command.extend(["-o", str(cls.binary)])
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture build failed ({build.returncode}):\n{build.stderr}")

    def run_case(self, case: str) -> None:
        run = subprocess.run([str(self.binary), case], cwd=ROOT, text=True,
                             capture_output=True, timeout=60)
        output = run.stdout + run.stderr
        (self.artifacts / f"{case}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)

    def test_fixture_does_not_link_real_input_or_permission_functions(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        (self.artifacts / "undefined-symbols.log").write_text(symbols)
        for name in ("CGEventPost", "AXIsProcessTrustedWithOptions",
                     "TISCopyCurrentKeyboardLayoutInputSource"):
            self.assertNotIn("_" + name + "\n", symbols)

    def test_selection_without_escape_pastes_exactly_once(self) -> None:
        self.run_case("selection")

    def test_escape_after_selection_cancels_scheduled_paste_and_hide(self) -> None:
        self.run_case("escape-after-selection")

    def test_escape_restores_clipping_store_from_favorites(self) -> None:
        self.run_case("favorites")


if __name__ == "__main__":
    unittest.main()
