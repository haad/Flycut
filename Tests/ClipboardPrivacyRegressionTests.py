#!/usr/bin/env python3
"""Native regression tests for clipboard privacy handling.

The fixture compiles the real FlycutClipping/FlycutStore/FlycutOperator
method bodies and replaces only OS boundaries (NSUserDefaults, the on-disk
image store, file autosave). It never touches a pasteboard, launches the
app, posts input or reads real user data.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
FIXTURE = ROOT / "Tests/Fixtures/ClipboardPrivacy.m"


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


class ClipboardPrivacyRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-privacy-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS", cls.temporary.name))
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.binary = cls.artifacts / "ClipboardPrivacy"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"),
                   str(FIXTURE), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr}")

    def run_case(self, case: str) -> None:
        run = subprocess.run([str(self.binary), case], cwd=ROOT, text=True,
                             capture_output=True, timeout=30)
        output = run.stdout + run.stderr
        (self.artifacts / f"{case}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)

    def test_concealed_types_are_skipped_independently_of_password_heuristics(self) -> None:
        self.run_case("concealed")

    def test_evaluating_a_clipping_does_not_modify_or_save_the_store(self) -> None:
        self.run_case("no-reveal-no-save")

    def test_reveal_pasteboard_types_on_main_thread_is_immediate(self) -> None:
        self.run_case("reveal-main")

    def test_reveal_pasteboard_types_from_capture_worker_commits_on_main_queue(self) -> None:
        self.run_case("reveal-worker")

    def test_debug_menu_log_omits_clipping_previews(self) -> None:
        method = method_body(APP_CONTROLLER.read_text(), "- (void)updateMenuContaining:")
        log_calls = re.findall(r"\b(?:DLog|NSLog)\s*\((.*?)\);", method, re.S)
        self.assertTrue(log_calls, "expected the menu rebuild to keep its count log")
        for call in log_calls:
            self.assertNotIn("returnedDisplayStrings", call)
            self.assertNotIn("clipStrings", call)

    def test_fixture_uses_no_real_defaults_or_application_support(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        (self.artifacts / "undefined-symbols.log").write_text(symbols)
        for name in ("_OBJC_CLASS_$_NSUserDefaults", "_NSSearchPathForDirectoriesInDomains",
                     "_OBJC_CLASS_$_NSPasteboard", "_CGEventPost"):
            self.assertNotIn(name + "\n", symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
