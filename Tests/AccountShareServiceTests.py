#!/usr/bin/env python3
"""Native tests for FlycutAccountShareService, which runs the account-share
engine for the app: inbox for every other account, folder watch, safety pickup,
session handling (clippings that arrive while the session is not on the console
go to the pasteboard when it comes back), sending and turning off.

The fixture runs two simulated accounts (UID 7001 and 7002, no real account)
plus one that never turns sharing on (7003) as two services with their own
queues in one process, inside an injected scratch root; the file owner is
simulated per inode and every engine mutation must stay inside that root (the
trace refuses anything else, see the containment case).
Nothing is created under /Users/Shared or in a real defaults domain; no
pasteboard, app, network or real account is used.

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
FIXTURE = ROOT / "Tests/Fixtures/AccountShareService.m"
SERVICE = ROOT / "FlycutEngine/FlycutAccountShareService.m"
REAL_HOME = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
SHARED = pathlib.Path("/Users/Shared")
CLANG = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
         "-mmacosx-version-min=13.5", "-arch", "arm64", "-Wall"]
MODES = ["start", "folder-watch", "safety-timer", "away-then-active", "launch-pickup",
         "sender-conditions", "wipe", "off-wipe-retried", "leftover-wipe",
         "account-rule", "launch-age", "pause-pickup", "withdraw-on-off"]


def remove_tree(path: pathlib.Path) -> None:
    """Inbox roots carry an "everyone deny delete" entry: strip ACLs, then remove."""
    subprocess.run(["/bin/chmod", "-R", "-N", str(path)], capture_output=True)
    shutil.rmtree(path, True)


def snapshot_names(path: pathlib.Path) -> tuple:
    """Names (never printed) plus the directory's own timestamps."""
    st = os.lstat(path)
    names = sorted(os.listdir(path))
    return st.st_mtime_ns, st.st_ctime_ns, len(names), hashlib.sha256("\0".join(names).encode()).hexdigest()


class AccountShareServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.environ.get("FLYCUT_SHARE_TEST_ROOT") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="flycut-share-service-", dir=base)).resolve()
        cls.addClassCleanup(remove_tree, cls.scratch)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.scratch / "artifacts").resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.binary = cls.artifacts / "AccountShareService"
        command = CLANG[:-1] + ["-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"), "-I", str(ROOT / "Tests/Fixtures"),
                               str(FIXTURE), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr[-4000:]}")
        cls.case_number = 0

    def run_case(self, mode: str, violations: bool = False) -> str:
        type(self).case_number += 1
        case_root = self.scratch / f"case-{self.case_number:02d}-{mode}"
        case_root.mkdir()
        outside = pathlib.Path(f"{case_root}-outside")
        outside.mkdir()
        outside.chmod(0o1777)
        run = subprocess.run([str(self.binary), mode, str(case_root)], cwd=ROOT, text=True,
                             capture_output=True, timeout=120)
        output = run.stdout + run.stderr
        (self.artifacts / f"{mode}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)
        trace = re.search(r"^TRACE mutations=(\d+) violations=(\d+)$", output, re.M)
        self.assertIsNotNone(trace, output)
        if violations:
            self.assertGreater(int(trace.group(2)), 0, output)
        else:
            self.assertEqual(int(trace.group(2)), 0, output)
        self.assertEqual(os.listdir(outside), [], "something was created outside the injected root")
        return output

    def test_start_prepares_an_inbox_for_every_other_account(self) -> None:
        self.run_case("start")

    def test_a_copy_arrives_through_the_folder_watch(self) -> None:
        self.run_case("folder-watch")

    def test_safety_timer_and_explicit_pickup(self) -> None:
        self.run_case("safety-timer")

    def test_newest_copy_received_while_away_goes_to_the_pasteboard_on_return(self) -> None:
        self.run_case("away-then-active")

    def test_launch_takes_in_what_waited(self) -> None:
        self.run_case("launch-pickup")

    def test_nothing_is_sent_when_stopped_off_console_or_refused(self) -> None:
        self.run_case("sender-conditions")

    def test_turning_off_wipes_the_inbox(self) -> None:
        self.run_case("wipe")

    def test_a_failed_delete_when_turning_off_is_tried_again(self) -> None:
        self.run_case("off-wipe-retried")

    def test_an_inbox_left_over_is_deleted_while_sharing_is_off(self) -> None:
        self.run_case("leftover-wipe")

    def test_login_account_rule(self) -> None:
        self.run_case("account-rule")

    def test_at_launch_only_a_copy_younger_than_ten_minutes_goes_to_the_pasteboard(self) -> None:
        self.run_case("launch-age")

    def test_paused_pickup_leaves_copies_waiting(self) -> None:
        self.run_case("pause-pickup")

    def test_turning_off_withdraws_this_accounts_waiting_copies(self) -> None:
        self.run_case("withdraw-on-off")

    def test_trace_refuses_writes_outside_the_injected_root(self) -> None:
        self.run_case("containment", violations=True)

    def test_no_writes_outside_the_injected_root(self) -> None:
        prefs = REAL_HOME / "Library/Preferences"
        before_prefs = set(os.listdir(prefs))
        before_shared = snapshot_names(SHARED)
        for mode in MODES:
            self.run_case(mode)
        after_shared = snapshot_names(SHARED)
        added = len(set(os.listdir(prefs)) - before_prefs)
        removed = len(before_prefs - set(os.listdir(prefs)))
        print(f"preferences names: +{added} -{removed}; /Users/Shared unchanged: {before_shared == after_shared}")
        self.assertEqual((added, removed), (0, 0))
        self.assertEqual(before_shared, after_shared)
        # Another account's own Flycut may keep its inbox there; none may belong to this one.
        mine = [n for n in os.listdir(SHARED) if n.startswith(".flycut-share-") and os.lstat(SHARED / n).st_uid == os.getuid()]
        self.assertFalse(mine)

    def test_service_links_no_pasteboard_defaults_workspace_or_network(self) -> None:
        obj = self.artifacts / "FlycutAccountShareService.o"
        build = subprocess.run(CLANG + ["-I", str(ROOT / "FlycutEngine"), "-c", str(SERVICE), "-o", str(obj)],
                               cwd=ROOT, text=True, capture_output=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertNotIn("warning:", build.stderr)
        symbols = set(subprocess.check_output(["/usr/bin/nm", "-u", str(obj)], text=True).split())
        (self.artifacts / "service-undefined-symbols.log").write_text("\n".join(sorted(symbols)) + "\n")
        for name in ("_OBJC_CLASS_$_NSUserDefaults", "_OBJC_CLASS_$_NSPasteboard", "_OBJC_CLASS_$_NSWorkspace",
                     "_OBJC_CLASS_$_NSFileManager", "_socket", "_connect", "_unlink", "_unlinkat", "_rename",
                     "_renameat", "_mkdir", "_mkdirat", "_rmdir", "_write", "_chmod", "_fchmod"):
            self.assertNotIn(name, symbols)


if __name__ == "__main__":
    unittest.main()
