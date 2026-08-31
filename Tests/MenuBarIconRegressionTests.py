#!/usr/bin/env python3
"""Regression tests for native, resolution-independent menu-bar icons."""

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
    def test_appkit_symbols_exist_as_menu_bar_sized_templates(self) -> None:
        fixture = r'''
#import <AppKit/AppKit.h>

static int Check(NSString *name, NSFontWeight weight) {
    NSImage *base = [NSImage imageWithSystemSymbolName:name
                              accessibilityDescription:name];
    if (base == nil) return 1;
    NSImageSymbolConfiguration *configuration =
        [NSImageSymbolConfiguration configurationWithPointSize:14 weight:weight];
    NSImage *image = [base imageWithSymbolConfiguration:configuration];
    if (image == nil) return 2;
    [image setTemplate:YES];
    if (![image isTemplate]) return 3;
    if ([image size].height > 18.0 || [image size].width > 24.0) return 4;
    return 0;
}

int main(void) {
    @autoreleasepool {
        if (Check(@"scissors", NSFontWeightRegular) != 0) return 10;
        if (Check(@"scissors", NSFontWeightBold) != 0) return 11;
        if (Check(@"pause.circle", NSFontWeightRegular) != 0) return 12;
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
                    "-fobjc-weak",
                    "-fmodules",
                    "-mmacosx-version-min=13.5",
                    "-arch",
                    "arm64",
                    str(source),
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

    def test_image_styles_use_native_scissors_symbols(self) -> None:
        source = APP_CONTROLLER.read_text()
        method = method_body(source, "-(void) switchMenuIconTo:")
        self.assertIn("imageWithSystemSymbolName:symbolName", source)
        self.assertIn('menuBarImageForSymbolName:@"scissors"', method)
        self.assertIn("configurationWithPointSize:14", source)
        self.assertIn("NSFontWeightRegular", method)
        self.assertIn("NSFontWeightBold", method)
        self.assertIn("statusItem.button.image", method)
        self.assertNotIn("imageNamed", method)
        self.assertNotIn("com.generalarcade.flycut", method)

    def test_paused_state_is_native_and_rerendered(self) -> None:
        source = APP_CONTROLLER.read_text()
        header = APP_HEADER.read_text()
        switch_method = method_body(source, "-(void) switchMenuIconTo:")
        toggle_method = method_body(source, "-(bool)toggleMenuIconDisabled")

        self.assertIn('menuBarImageForSymbolName:@"pause.circle"', switch_method)
        self.assertIn("statusItemShowsDisabled", switch_method)
        self.assertIn("statusItemShowsDisabled = !statusItemShowsDisabled", toggle_method)
        self.assertIn("[NSThread isMainThread]", toggle_method)
        self.assertIn("dispatch_sync(dispatch_get_main_queue()", toggle_method)
        self.assertIn("[self switchMenuIconTo:", toggle_method)
        self.assertNotIn("statusItemText", header)
        self.assertNotIn("statusItemImage", header)
        self.assertIn("BOOL statusItemShowsDisabled", header)
        self.assertNotIn("imageNamed", toggle_method)

    def test_preferences_name_the_native_image_styles(self) -> None:
        source = APP_CONTROLLER.read_text()
        self.assertIn('@"System scissors"', source)
        self.assertIn('@"Bold system scissors"', source)


if __name__ == "__main__":
    unittest.main()
