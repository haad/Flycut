#!/usr/bin/env python3
"""Native tests for wiring the account-share service into AppController.

The fixture compiles every app source and runs two AppControllers as two
simulated accounts (UID 7001 and 7002, no real account), each with its own
FlycutOperator, an in-memory pasteboard and an account-share service on an
injected scratch root (simulated file owners, traced engine mutations). A copy
goes through the production -pollPB:, the other account adds it through the
production delegate method, and coming to the console puts it on that account's
pasteboard through -addClipToPasteboard:withRichData:, which -pollPB: then
neither captures nor sends back. Defaults stay in memory; NSWorkspace is a
stand-in; nothing is created under /Users/Shared.

Set FLYCUT_SHARE_TEST_ROOT to choose the scratch base (default: the temp dir).
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import pwd
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
FIXTURE = FIXTURES / "AccountShareAppController.m"
APP_CONTROLLER = ROOT / "AppController.m"
REAL_HOME = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
SHARED = pathlib.Path("/Users/Shared")
ENGINE = "FlycutEngine/FlycutAccountShare.m"   # compiled into the fixture with trace wrappers


def method_body(source: str, signature: str) -> str:
    found = [m.start() for m in re.finditer(re.escape(signature) + r"\s*\{", source)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} definitions of {signature}")
    start = found[0]
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Unclosed method: {signature}")


def remove_tree(path: pathlib.Path) -> None:
    """Inbox roots carry an "everyone deny delete" entry: strip ACLs, then remove."""
    subprocess.run(["/bin/chmod", "-R", "-N", str(path)], capture_output=True)
    shutil.rmtree(path, True)


def snapshot_names(path: pathlib.Path) -> tuple:
    st = os.lstat(path)
    names = sorted(os.listdir(path))
    return st.st_mtime_ns, st.st_ctime_ns, len(names), hashlib.sha256("\0".join(names).encode()).hexdigest()


class AccountShareAppControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.environ.get("FLYCUT_SHARE_TEST_ROOT") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="flycut-share-app-", dir=base)).resolve()
        cls.addClassCleanup(remove_tree, cls.scratch)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.scratch / "artifacts").resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
        sources = [ROOT / p for p in sorted(listed)
                   if p != "main.m" and p != ENGINE and not p.startswith(("FlycutHelper/", "Tests/"))]
        cls.binary = cls.artifacts / "AccountShareAppController"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, ROOT / "UI", ROOT / "FlycutEngine", *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(FIXTURE)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit", "CoreText"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr[-4000:]}")
        cls.case_number = 0

    def run_case(self, mode: str) -> str:
        type(self).case_number += 1
        case_root = self.scratch / f"case-{self.case_number:02d}-{mode}"
        case_root.mkdir()
        run = subprocess.run([str(self.binary), mode, str(case_root)], cwd=ROOT, text=True,
                             capture_output=True, timeout=120)
        output = run.stdout + run.stderr
        (self.artifacts / f"{mode}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)
        trace = re.search(r"^TRACE mutations=(\d+) violations=(\d+)$", output, re.M)
        self.assertIsNotNone(trace, output)
        self.assertEqual(int(trace.group(2)), 0, output)
        return output

    def test_sharing_is_off_by_default(self) -> None:
        self.run_case("defaults")

    def test_launch_setup_with_sharing_off_starts_nothing(self) -> None:
        before = snapshot_names(SHARED)
        self.run_case("setup-off")
        self.assertEqual(before, snapshot_names(SHARED))

    def test_launch_with_sharing_off_deletes_an_inbox_left_over(self) -> None:
        before = snapshot_names(SHARED)
        self.run_case("setup-off-leftover")
        self.assertEqual(before, snapshot_names(SHARED))

    def test_launch_with_sharing_on_takes_in_a_copy_that_waited(self) -> None:
        before = snapshot_names(SHARED)
        self.run_case("setup-on-waiting")
        self.assertEqual(before, snapshot_names(SHARED))

    def test_help_says_what_other_accounts_see_and_that_a_failed_delete_is_retried(self) -> None:
        help_text = (ROOT / "help.md").read_text()
        self.assertIn("Any other account on this Mac can see that the folder exists and which accounts may add "
                      "copies to it, but not the copies; an account that sends to you can also tell how many "
                      "copies from the others wait there and when they came or were taken in.", help_text)
        self.assertIn("Turning the option off deletes your folder with everything in it (if it cannot be deleted "
                      "at once, Flycut tries again every minute, also after it restarts)", help_text)

    def test_a_copy_reaches_the_other_accounts_history(self) -> None:
        self.run_case("capture")

    def test_switching_in_puts_the_copy_on_the_pasteboard_without_echo(self) -> None:
        self.run_case("away-no-echo")

    def test_diagnostics_pause_background_and_passwords_send_nothing(self) -> None:
        self.run_case("nothing-sent")

    def test_a_copy_of_the_newest_clipping_is_shared_too(self) -> None:
        self.run_case("recopy")

    def test_a_formatted_copy_from_the_poll_is_shared_with_its_formatting(self) -> None:
        self.run_case("rich-poll")

    def test_a_formatted_copy_caught_up_by_a_selection_is_shared_with_its_formatting(self) -> None:
        self.run_case("rich-catch-up")

    def test_a_formatted_copy_whose_row_goes_in_after_a_newer_copy_is_not_shared_above_it(self) -> None:
        self.run_case("late-rich-below-newer")

    def test_a_formatted_copy_whose_read_spans_a_choice_is_neither_kept_nor_shared(self) -> None:
        self.run_case("late-rich-choice")

    def test_a_copy_another_account_shares_stays_above_a_copy_whose_read_was_running(self) -> None:
        self.run_case("received-above-late")

    def test_checkbox_action_starts_and_wipes(self) -> None:
        self.run_case("toggle")

    def test_launch_quit_and_capture_hooks(self) -> None:
        source = APP_CONTROLLER.read_text()
        awake = method_body(source, "- (void)awakeFromNib")
        self.assertIn("[self setUpAccountSharing];", awake)
        self.assertLess(awake.index("pbBlockCount = [[NSNumber numberWithInt:0] retain];"),
                        awake.index("[self setUpAccountSharing];"),
                        "sharing starts only after the pasteboard state exists")
        self.assertLess(awake.index("[self buildGeneralPermissionsPreferenceRow];"),
                        awake.index("[self buildGeneralAccountSharingSection];"))
        setup = method_body(source, "-(void)setUpAccountSharing")
        self.assertIn("NSWorkspaceSessionDidBecomeActiveNotification", setup)
        self.assertIn('boolForKey:@"shareClippingsAcrossAccounts"', setup)
        terminate = method_body(source, "- (void)applicationWillTerminate:(NSNotification *)notification")
        self.assertIn("[accountShareService stop];", terminate)
        poll = method_body(source, "-(void)pollPB:(NSTimer *)timer")
        offer = "[accountShareService offerText:contents"
        self.assertEqual(poll.count("accountShareService"), 1)
        text_branch = poll[poll.index("if ( type != nil ) {"):poll.index("if ( imageType != nil ) {")]
        self.assertIn(offer, text_branch, "only text copies are shared")
        self.assertLess(text_branch.index("[flycutOperator addClipping:contents"), text_branch.index(offer),
                        "offered only once it is in the history")
        self.assertLess(text_branch.index("if (revealPasteboardTypes) {"), text_branch.index(offer))
        registered = method_body(source, "- (id)init")
        self.assertRegex(registered, r"numberWithBool:NO\],\s*@\"shareClippingsAcrossAccounts\"")

    def test_nothing_reaches_the_real_shared_folder(self) -> None:
        prefs = REAL_HOME / "Library/Preferences"
        before_prefs = set(os.listdir(prefs))
        before = snapshot_names(SHARED)
        for mode in ("capture", "recopy", "away-no-echo", "toggle"):
            self.run_case(mode)
        self.assertEqual(before, snapshot_names(SHARED))
        self.assertEqual(set(os.listdir(prefs)), before_prefs)
        # Another account's own Flycut may keep its inbox there; none may belong to this one.
        mine = [n for n in os.listdir(SHARED) if n.startswith(".flycut-share-") and os.lstat(SHARED / n).st_uid == os.getuid()]
        self.assertFalse(mine)


if __name__ == "__main__":
    unittest.main()
