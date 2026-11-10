#!/usr/bin/env python3
"""Native regression tests for preserving text formatting (RTF/HTML).

The fixture compiles the real FlycutClipping/FlycutStore/FlycutOperator
method bodies and the exact AppController pollPB:,
addClipToPasteboard:withRichData: and setPBBlockCount: method text. Only OS
boundaries are replaced (pasteboard, workspace, defaults, libdispatch, the
on-disk image store and file autosave). It never touches the real
clipboard, launches the app, posts input or reads real user data.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
FIXTURE = ROOT / "Tests/Fixtures/RichTextFormatting.m"
METHODS = (
    "-(void)pollPB:(NSTimer *)timer",
    "-(void) setPBBlockCount:(NSNumber *)newPBBlockCount",
    "-(void)addClipToPasteboard:(NSString*)pbFullText withRichData:(NSDictionary *)richData",
)


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
                return source[start:index + 1]
    raise AssertionError(f"Unclosed method: {signature}")


class RichTextFormattingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-rich-text-")
        cls.addClassCleanup(cls.temporary.cleanup)
        # An exported but empty variable must not put the artifacts into the checkout.
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name).resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        source = APP_CONTROLLER.read_text()
        methods = "\n".join(method_body(source, signature) for signature in METHODS)
        (cls.artifacts / "AppControllerMethods.inc").write_text(methods + "\n")
        cls.binary = cls.artifacts / "RichTextFormatting"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"), "-I", str(cls.artifacts),
                   str(FIXTURE), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        (cls.artifacts / "rich-text-build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr}")

    def run_case(self, case: str) -> None:
        run = subprocess.run([str(self.binary), case], cwd=ROOT, text=True,
                             capture_output=True, timeout=30)
        output = run.stdout + run.stderr
        (self.artifacts / f"rich-text-{case}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)

    def test_stable_clipboard_keeps_rtf_and_html_with_text(self) -> None:
        self.run_case("capture-stable")

    def test_clipboard_change_during_capture_discards_mixed_snapshot(self) -> None:
        self.run_case("capture-mixed-generation")

    def test_same_text_with_new_formatting_updates_newest_clipping(self) -> None:
        self.run_case("same-text-new-formatting")

    def test_rich_data_is_limited_to_valid_rtf_and_html(self) -> None:
        self.run_case("restored-rich-data")

    def test_restored_rich_data_never_replaces_pasted_text(self) -> None:
        self.run_case("restored-rich-data-paste")

    def test_fixture_uses_no_real_pasteboard_defaults_or_application_support(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        (self.artifacts / "rich-text-undefined-symbols.log").write_text(symbols)
        for name in ("_OBJC_CLASS_$_NSPasteboard", "_OBJC_CLASS_$_NSWorkspace",
                     "_OBJC_CLASS_$_NSUserDefaults", "_NSSearchPathForDirectoriesInDomains",
                     "_CGEventPost"):
            self.assertNotIn(name + "\n", symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
