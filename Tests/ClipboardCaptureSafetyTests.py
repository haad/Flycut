#!/usr/bin/env python3
"""Regression tests for asynchronous clipboard capture safety."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
FLYCUT_OPERATOR = ROOT / "FlycutOperator.m"


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


class ClipboardCaptureSafetyTests(unittest.TestCase):
    def test_generation_policy_rejects_changed_and_blocked_reads(self) -> None:
        fixture = r'''
#include "ClipboardGenerationPolicy.h"

int main(void) {
    if (!FCShouldCommitClipboardRead(11, 11, 10, false)) return 1;
    if (FCShouldCommitClipboardRead(11, 12, 10, false)) return 2;
    if (FCShouldCommitClipboardRead(11, 11, 11, false)) return 3;
    if (FCShouldCommitClipboardRead(11, 12, 12, false)) return 4;
    if (FCShouldCommitClipboardRead(11, 11, 10, true)) return 5;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="flycut-generation-policy-") as directory:
            source = pathlib.Path(directory) / "generation_policy.c"
            binary = pathlib.Path(directory) / "generation_policy"
            source.write_text(fixture)
            build = subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "clang",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT),
                    str(source),
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], cwd=ROOT, timeout=30)
            self.assertEqual(run.returncode, 0)

    def test_poll_binds_content_types_and_commit_to_one_generation(self) -> None:
        source = APP_CONTROLLER.read_text()
        method = method_body(source, "-(void)pollPB:")

        self.assertIn(
            "NSInteger pasteboardGeneration = [jcPasteboard changeCount]", method
        )
        self.assertIn("NSArray *availableTypes = [jcPasteboard types]", method)
        self.assertIn(
            "NSInteger blockedGeneration = [pbBlockCount integerValue]", method
        )
        self.assertIn(
            "NSInteger pasteboardGenerationAfterRead = [jcPasteboard changeCount]",
            method,
        )
        self.assertIn(
            "[flycutOperator shouldSkip:contents ofType:type "
            "fromAvailableTypes:availableTypes]",
            method,
        )
        normalized_method = " ".join(method.split())
        self.assertIn(
            "FCShouldCommitClipboardRead( pasteboardGeneration, "
            "pasteboardGenerationAfterRead, blockedGeneration, "
            "[flycutOperator storeDisabled] )",
            normalized_method,
        )

        background = method.index("dispatch_async(clipboardReadQueue")
        self.assertNotIn("toggleMenuIconDisabled", method)

        background_body = method[background:]
        self.assertNotIn(
            "[jcPasteboard availableTypeFromArray", background_body
        )
        self.assertNotIn("[jcPasteboard types]", background_body)

    def test_dispatch_queue_uses_a_c_string_label(self) -> None:
        source = APP_CONTROLLER.read_text()
        self.assertIn(
            'dispatch_queue_create("com.Flycut.clipboardReadQueue",', source
        )
        self.assertNotIn(
            'dispatch_queue_create(@"com.Flycut.clipboardReadQueue",', source
        )

    def test_diagnostic_mode_skips_payload_and_mutates_store_on_main(self) -> None:
        operator_source = FLYCUT_OPERATOR.read_text()
        operator_method = method_body(operator_source, "-(BOOL)shouldSkip:")
        self.assertNotIn("revealPasteboardTypes", operator_method)
        self.assertNotIn("dispatch_async", operator_method)
        self.assertNotIn("[clippingStore addClipping:type", operator_method)

        controller_source = APP_CONTROLLER.read_text()
        poll_method = method_body(controller_source, "-(void)pollPB:")
        self.assertIn(
            'BOOL revealPasteboardTypes = [[NSUserDefaults standardUserDefaults] '
            'boolForKey:@"revealPasteboardTypes"]',
            poll_method,
        )
        policy = poll_method.index("FCShouldCommitClipboardRead")
        diagnostic = poll_method.index("if (revealPasteboardTypes)", policy)
        payload = poll_method.rindex("[flycutOperator addClipping:contents")
        self.assertLess(policy, diagnostic)
        self.assertLess(diagnostic, payload)
        diagnostic_branch = poll_method[diagnostic:payload]
        self.assertIn("[flycutOperator addClipping:type", diagnostic_branch)
        self.assertIn("return;", diagnostic_branch)


if __name__ == "__main__":
    unittest.main()
