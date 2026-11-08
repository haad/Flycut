#!/usr/bin/env python3
"""Regression coverage for grapheme-safe clipping display strings."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class GraphemeDisplayRegressionTests(unittest.TestCase):
    def test_display_length_never_splits_a_composed_character(self) -> None:
        clang = subprocess.run(
            ["/usr/bin/xcrun", "--find", "clang"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(clang)
        sdk_path = subprocess.run(
            ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(sdk_path)

        fixture = r'''
#import <Foundation/Foundation.h>
#import "FlycutClipping.h"

static void AssertDisplay(const char *caseName, NSString *input, int length, NSString *expected) {
    FlycutClipping *clipping = [[FlycutClipping alloc]
        initWithContents:input
                 withType:@"public.utf8-plain-text"
        withDisplayLength:length
     withAppLocalizedName:@"Regression Fixture"
         withAppBundleURL:nil
            withTimestamp:0];
    NSString *actual = [clipping displayString];
    if (![actual isEqualToString:expected]) {
        fprintf(stderr, "FAIL:%s\n", caseName);
        exit(1);
    }
    [clipping release];
}

int main(void) {
    @autoreleasepool {
        AssertDisplay("ascii", @"ABCDE", 3, @"ABC…");
        AssertDisplay("single-emoji", @"😀", 1, @"😀");
        AssertDisplay("emoji", @"😀X", 1, @"😀…");
        AssertDisplay("combining-mark", @"e\u0301X", 1, @"e\u0301…");
        AssertDisplay("zwj", @"👩‍💻X", 1, @"👩‍💻…");
        AssertDisplay("flag", @"🇩🇪X", 1, @"🇩🇪…");
    }
    return 0;
}
'''

        temp_root = pathlib.Path(tempfile.mkdtemp(prefix="flycut-grapheme-test-"))
        try:
            source = temp_root / "GraphemeFixture.m"
            binary = temp_root / "GraphemeFixture"
            source.write_text(textwrap.dedent(fixture), encoding="utf-8")
            compile_result = subprocess.run(
                [
                    clang,
                    "-isysroot",
                    sdk_path,
                    "-fno-objc-arc",
                    "-fobjc-weak",
                    "-fblocks",
                    "-fmodules",
                    "-mmacosx-version-min=13.5",
                    "-arch",
                    "arm64",
                    str(source),
                    str(ROOT / "FlycutEngine" / "FlycutClipping.m"),
                    "-I",
                    str(ROOT / "FlycutEngine"),
                    "-framework",
                    "Foundation",
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            run_result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run_result.returncode, 0, run_result.stderr)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
