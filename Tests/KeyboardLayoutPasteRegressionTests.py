#!/usr/bin/env python3
"""Native regression tests; never select a layout, post input, or touch TCC.

The fixture compiles the exact fakeKey/fakeCommandV method text, replacing
only OS boundaries with test doubles. UCKeyTranslate uses installed layout
data for the four layout cases. No AppController initialization/app launch.
"""
from __future__ import annotations

import os
import hashlib
import json
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
                return source[start:index + 1]
    raise AssertionError(f"Unclosed method: {signature}")


class KeyboardLayoutPasteRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-paste-key-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS", cls.temporary.name))
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        source = APP_CONTROLLER.read_text()
        methods = "\n".join(method_body(source, signature) for signature in
                            ("-(void)fakeKey:", "-(void)fakeCommandV"))
        (cls.artifacts / "PasteMethods.inc").write_text(methods + "\n")
        inputs = [APP_CONTROLLER, pathlib.Path(__file__), ROOT / "Tests/Fixtures/KeyboardLayoutPaste.m"]
        if (ROOT / "FlycutPasteKey.h").exists():
            inputs.append(ROOT / "FlycutPasteKey.h")
        (cls.artifacts / "source-hashes.json").write_text(json.dumps({
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs}, indent=2) + "\n")
        cls.binary = cls.artifacts / "KeyboardLayoutPaste"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fblocks", "-fmodules",
                   "-Wall", "-Wextra", "-Wno-unused-function", "-Werror",
                   "-I", str(ROOT), "-I", str(cls.artifacts),
                   str(ROOT / "Tests/Fixtures/KeyboardLayoutPaste.m"),
                   "-framework", "Cocoa", "-framework", "Carbon", "-o", str(cls.binary)]
        (cls.artifacts / "build-command.txt").write_text(repr(command) + "\n")
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
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

    def test_command_modified_installed_layouts(self) -> None:
        self.run_case("layouts")

    def test_nil_key_never_creates_or_posts_events(self) -> None:
        self.run_case("nil")

    def test_missing_unicode_data_uses_guarded_ascii_fallback(self) -> None:
        self.run_case("fallback")

    def test_command_translation_errors_and_noncharacters_fail_closed(self) -> None:
        self.run_case("translation")

    def test_truncated_layout_data_never_reaches_translator(self) -> None:
        self.run_case("truncated")

    def test_partial_event_allocation_posts_nothing_and_releases_objects(self) -> None:
        self.run_case("allocation")

    def test_unresolved_fallback_never_posts_events(self) -> None:
        self.run_case("fallback-errors")

    def test_fixture_does_not_link_real_input_or_permission_functions(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        (self.artifacts / "undefined-symbols.log").write_text(symbols)
        for name in ("CGEventSourceCreate", "CGEventCreateKeyboardEvent", "CGEventPost",
                     "CGEventSetFlags", "AXIsProcessTrustedWithOptions", "TISSelectInputSource",
                     "TISCopyCurrentKeyboardLayoutInputSource", "TISCopyCurrentASCIICapableKeyboardLayoutInputSource"):
            self.assertNotIn("_" + name + "\n", symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
