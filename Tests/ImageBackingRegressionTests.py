#!/usr/bin/env python3
"""Native regression tests for image clipping backing storage.

The fixture (Tests/Fixtures/ImageBacking.m) compiles the production engine
sources unchanged, plus the image paste methods extracted verbatim from
AppController.m. Only OS boundaries are doubles: in-memory user defaults, the
Application Support / Desktop / temporary directories redirected into a fresh
per-case root, and an in-memory pasteboard. A guard inside the fixture aborts if
a file operation leaves that root. Nothing is launched and no real pasteboard,
preference domain or Application Support data is read or written.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
FIXTURE = ROOT / "Tests/Fixtures/ImageBacking.m"
ENGINE_SOURCES = ("FlycutEngine/FlycutClipping.m", "FlycutEngine/FlycutStore.m",
                  "FlycutEngine/FlycutImageStore.m", "FlycutOperator.m")
# AppController methods compiled into the fixture harness, by selector.
APP_METHODS = ("setPBBlockCount:", "addClipToPasteboard:", "addImageClipToPasteboard:", "pasteFromStack",
               "pasteIndexAndUpdate:", "processMenuClippingSelection:", "searchWindowItemSelected:",
               "pollPB:", "animatedGifURLFromPasteboard", "downloadAndCaptureGIFFromURL:")
# Helpers that only exist once the image capture fix is applied; optional so the
# regression also compiles against the pre-fix source.
OPTIONAL_APP_METHODS = ("isImageCaptureCurrentForGeneration:",)
# Symbols the fixture binary must never reference: real defaults, pasteboard,
# workspace, network, and the real directory lookups.
FORBIDDEN_SYMBOLS = ("_OBJC_CLASS_$_NSUserDefaults", "_OBJC_CLASS_$_NSPasteboard",
                     "_OBJC_CLASS_$_NSWorkspace", "_OBJC_CLASS_$_NSURLSession",
                     "_NSSearchPathForDirectoriesInDomains", "_NSTemporaryDirectory",
                     "_NSHomeDirectory")


def method_body(source: str, selector: str) -> str | None:
    """Return the implementation of selector; declarations (ending in ';') are skipped."""
    for match in re.finditer(r"(?m)^-\s*\([^)]*\)\s*" + re.escape(selector), source):
        start = match.start()
        opening = source.index("{", start)
        if source.find(";", start, opening) != -1:
            continue
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[start:index + 1]
        raise AssertionError(f"Unclosed method: {selector}")
    return None


class ImageBackingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-image-backing-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name).resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        source = APP_CONTROLLER.read_text()
        methods = []
        for selector in APP_METHODS + OPTIONAL_APP_METHODS:
            body = method_body(source, selector)
            if body is None and selector not in OPTIONAL_APP_METHODS:
                raise AssertionError(f"Method not found: {selector}")
            if body is not None:
                methods.append(body)
        (cls.artifacts / "AppControllerImageMethods.inc").write_text("\n\n".join(methods) + "\n")
        inputs = [APP_CONTROLLER, FIXTURE, pathlib.Path(__file__)] + [ROOT / path for path in ENGINE_SOURCES]
        (cls.artifacts / "source-hashes.json").write_text(json.dumps({
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs}, indent=2) + "\n")
        # Tracked headers in a git checkout; a directory walk in an export without git metadata.
        listing = subprocess.run(["/usr/bin/git", "ls-files", "*.h"], cwd=ROOT, text=True, capture_output=True)
        headers = listing.stdout.splitlines() if listing.returncode == 0 else []
        if not headers:
            headers = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.h")]
        include_dirs = sorted({ROOT} | {(ROOT / header).parent for header in headers
                                        if not header.startswith(("Tests/", "FlycutHelper/"))})
        cls.binary = cls.artifacts / "ImageBacking"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch"), "-I", str(cls.artifacts)]
        for directory in include_dirs:
            command += ["-I", str(directory)]
        command += [str(FIXTURE), "-framework", "Cocoa", "-framework", "ImageIO", "-o", str(cls.binary)]
        (cls.artifacts / "build-command.txt").write_text(repr(command) + "\n")
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr}")

    def new_root(self) -> pathlib.Path:
        return pathlib.Path(tempfile.mkdtemp(prefix="root-", dir=self.temporary.name))

    def run_case(self, case: str, root: pathlib.Path | None = None, expected_exit: int = 0) -> str:
        root = root or self.new_root()
        run = subprocess.run([str(self.binary), case, str(root)], cwd=root, text=True,
                             capture_output=True, timeout=60)
        output = run.stdout + run.stderr
        files = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        (self.artifacts / f"{case}.log").write_text(output + "\nfiles: " + json.dumps(files) + "\n")
        print(output, end="")
        self.assertEqual(run.returncode, expected_exit, output)
        return output

    # PR3-3: Save: Never must not persist image contents beyond the process.
    def test_save_never_captures_images_in_memory_only(self) -> None:
        self.run_case("never-capture-memory-only")

    def test_save_never_terminate_leaves_no_image_files(self) -> None:
        self.run_case("never-terminate-no-files")

    def test_save_never_gif_paste_uses_removed_temporary_copy(self) -> None:
        self.run_case("never-gif-temporary-copy")

    def test_save_never_clear_all_forgets_images(self) -> None:
        self.run_case("never-clear-all")

    def test_save_never_terminate_keeps_files_that_are_not_stored_images(self) -> None:
        self.run_case("never-terminate-keeps-other-files")

    def test_enabling_save_on_every_change_persists_images_at_next_change(self) -> None:
        self.run_case("never-then-saving-on-change")

    def test_stale_temporary_copies_are_removed_at_start(self) -> None:
        self.run_case("stale-temporary-copies")

    def test_launch_creates_image_store_so_stale_copies_are_removed(self) -> None:
        # The fixture case above models the launch as "operator start, then image
        # store". -awakeFromNib cannot be compiled into the fixture (window, status
        # item and permission setup), so its call is checked in the source.
        awake = method_body(APP_CONTROLLER.read_text(), "awakeFromNib\n")
        self.assertIsNotNone(awake, "-awakeFromNib not found in AppController.m")
        operator_start = awake.find("awakeFromNibDisplaying:")
        self.assertNotEqual(operator_start, -1, "-awakeFromNib no longer starts the FlycutOperator")
        self.assertTrue("[FlycutImageStore sharedStore];" in awake[operator_start:],
                        "-awakeFromNib must create the image store at launch, so temporary image copies "
                        "left by an earlier process are removed before any image is copied")

    # Behaviour with saving enabled must stay as it was.
    def test_saving_enabled_keeps_persistent_image_files(self) -> None:
        self.run_case("saving-enabled-unchanged")

    def test_enabling_saving_before_exit_persists_and_restores_images(self) -> None:
        root = self.new_root()
        self.run_case("never-then-saving-exit", root)
        self.run_case("never-then-saving-relaunch", root)

    # PR3-1: the reference scan must include the stashed main history.
    def test_deleting_favorite_keeps_image_of_main_history(self) -> None:
        for case in ("favorite-delete-main-image-saved", "favorite-delete-main-image-never"):
            with self.subTest(case=case):
                self.run_case(case)

    # PR3-6: Clear All must release images that are listed more than once.
    def test_clear_all_releases_duplicated_images(self) -> None:
        for case in ("clear-all-duplicates-saved", "clear-all-duplicates-never"):
            with self.subTest(case=case):
                self.run_case(case)

    # PR3-2: forgotten-clipping export runs before the bytes are released, and
    # saving reports the real write result.
    def test_evicted_image_is_exported_before_its_bytes_are_released(self) -> None:
        for case in ("evicted-image-autosaved-saved", "evicted-image-autosaved-never"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_save_to_file_reports_write_failure(self) -> None:
        self.run_case("save-reports-write-failure")

    # PR3-5: failed backing writes/reads must not produce a clipping or a paste.
    def test_failed_image_write_is_not_captured(self) -> None:
        self.run_case("failed-image-write-not-captured")

    def test_undecodable_image_bytes_are_not_captured(self) -> None:
        for case in ("undecodable-bytes-not-captured-saved", "undecodable-bytes-not-captured-never"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_lost_image_bytes_are_not_pasted(self) -> None:
        self.run_case("lost-image-not-pasted")

    def test_refused_pasteboard_write_is_not_pasted(self) -> None:
        self.run_case("refused-pasteboard-write-not-pasted")

    # PR3-4: image and GIF capture are bound to the checked clipboard generation.
    def test_image_capture_control(self) -> None:
        self.run_case("image-capture-control")

    def test_image_from_replaced_clipboard_generation_is_dropped(self) -> None:
        self.run_case("image-replaced-before-read")

    def test_gif_download_control(self) -> None:
        self.run_case("gif-download-control")

    def test_gif_download_after_clipboard_change_or_pause_is_dropped(self) -> None:
        for case in ("gif-download-after-clipboard-change", "gif-download-after-capture-paused",
                     "gif-download-after-image-capture-off", "gif-download-after-downloads-off"):
            with self.subTest(case=case):
                self.run_case(case)

    # The fixture's own containment must hold.
    def test_containment_guard_stops_writes_outside_fixture_root(self) -> None:
        output = self.run_case("guard-outside-write", expected_exit=90)
        self.assertIn("CONTAINMENT: NSData write outside fixture root: /dev/null", output)

    def test_containment_guard_stops_deletes_outside_fixture_root(self) -> None:
        output = self.run_case("guard-outside-delete", expected_exit=90)
        self.assertIn("CONTAINMENT: removeItem outside fixture root", output)

    def test_fixture_does_not_link_real_defaults_pasteboard_or_directories(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        (self.artifacts / "undefined-symbols.log").write_text(symbols)
        for name in FORBIDDEN_SYMBOLS:
            self.assertNotIn(name + "\n", symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
