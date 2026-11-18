#!/usr/bin/env python3
"""Native tests for the cross-account sharing engine (FlycutAccountShare).

The fixture compiles the real engine and the real FlycutOperator filter and
drives two simulated accounts (UID 7001 and 7002, no real account) plus a
foreign one (4242) inside an injected scratch root. The kernel's file owner is
simulated per inode; every filesystem mutation of the engine is traced, and one
that would leave the injected root is refused (EPERM). Nothing is created under
/Users/Shared or in a real defaults domain; no pasteboard, app, network or real
account is used.

Set FLYCUT_SHARE_TEST_ROOT to choose the scratch base (default: the temp dir). The
cases pass whatever ACL the folders above it hand down: the replica of
/Users/Shared gets its exact ACL.
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
FIXTURE = ROOT / "Tests/Fixtures/AccountShare.m"
ENGINE = ROOT / "FlycutEngine/FlycutAccountShare.m"
REAL_HOME = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
SHARED = pathlib.Path("/Users/Shared")
CLANG = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
         "-mmacosx-version-min=13.5", "-arch", "arm64", "-Wall"]
MODES = ["round-trip", "acl-exact", "temp-then-exclusive-rename", "preplanted-refused", "temp-planted",
         "rebuild-wrong-inbox", "sender-refuses-untrusted-inbox", "foreign-owner", "special-files",
         "unknown-sender-folder", "never-share-filters", "flood", "malformed", "size-limit", "wipe",
         "replica-under-inheriting-root", "root-cannot-be-moved",
         "grows-after-check", "folder-moved-after-open", "replaced-before-delete", "moved-before-deny",
         "deny-only-for-everyone"]
# Filesystem-mutating libc calls; the engine may only use the ones the fixture traces.
MUTATORS = {"_open", "_openat", "_mkdir", "_mkdirat", "_rename", "_renameat", "_renameatx_np",
            "_renamex_np", "_unlink", "_unlinkat", "_rmdir", "_link", "_linkat", "_symlink",
            "_symlinkat", "_mkfifo", "_mkfifoat", "_mknod", "_mknodat", "_chmod", "_fchmod",
            "_fchmodat", "_lchmod", "_chown", "_fchown", "_lchown", "_fchownat", "_acl_set_file",
            "_acl_set_fd", "_acl_set_fd_np", "_acl_set_link_np", "_truncate", "_ftruncate", "_write",
            "_pwrite", "_writev", "_pwritev", "_utimes", "_futimes", "_lutimes", "_futimens",
            "_utimensat", "_setattrlist", "_fsetattrlist", "_setattrlistat", "_fopen", "_creat",
            "_copyfile", "_fcopyfile", "_clonefile", "_clonefileat", "_fclonefileat",
            "_exchangedata", "_setxattr", "_fsetxattr", "_removexattr", "_fremovexattr", "_open_dprotected_np",
            "_openat_dprotected_np", "_openat_authenticated_np", "_mkstemp", "_mkdtemp", "_mkstemps"}
TRACED = {"_openat", "_mkdirat", "_renameatx_np", "_renameat", "_unlinkat", "_fchmod",
          "_acl_set_fd_np", "_write", "_futimens"}


def remove_tree(path: pathlib.Path) -> None:
    """Inbox roots carry an "everyone deny delete" entry: strip ACLs, then remove."""
    subprocess.run(["/bin/chmod", "-R", "-N", str(path)], capture_output=True)
    shutil.rmtree(path, True)


def snapshot_names(path: pathlib.Path) -> tuple:
    """Names (never printed) plus the directory's own timestamps."""
    st = os.lstat(path)
    names = sorted(os.listdir(path))
    digest = hashlib.sha256("\0".join(names).encode()).hexdigest()
    return st.st_mtime_ns, st.st_ctime_ns, len(names), digest


class AccountShareEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.environ.get("FLYCUT_SHARE_TEST_ROOT") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="flycut-share-", dir=base)).resolve()
        cls.addClassCleanup(remove_tree, cls.scratch)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.scratch / "artifacts").resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.binary = cls.artifacts / "AccountShare"
        command = CLANG[:-1] + ["-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"), str(FIXTURE),
                           "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr[-4000:]}")
        cls.case_number = 0

    def run_case(self, mode: str) -> str:
        type(self).case_number += 1
        case_root = self.scratch / f"case-{self.case_number:02d}-{mode}"
        case_root.mkdir()
        # Beside the case root, writable for everyone like /Users/Shared: the trace
        # must keep the engine out of it.
        outside = pathlib.Path(f"{case_root}-outside")
        outside.mkdir()
        outside.chmod(0o1777)
        run = subprocess.run([str(self.binary), mode, str(case_root)], cwd=ROOT, text=True,
                             capture_output=True, timeout=60)
        output = run.stdout + run.stderr
        (self.artifacts / f"{mode}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)
        trace = re.search(r"^TRACE mutations=(\d+) violations=(\d+)$", output, re.M)
        if trace is None:
            self.fail(output)
        self.assertGreater(int(trace.group(1)), 0, "the trace saw no engine mutation at all")
        self.assertEqual(int(trace.group(2)), 0, output)
        self.assertEqual(os.listdir(outside), [], "something was created outside the injected root")
        return output

    # Normal flow
    def test_round_trip_between_two_simulated_accounts(self) -> None:
        self.run_case("round-trip")

    # Recipient-side creation and verification
    def test_inbox_is_created_with_exact_acl_mode_and_owner(self) -> None:
        self.run_case("acl-exact")

    def test_inbox_is_created_under_a_temporary_name_then_renamed_exclusively(self) -> None:
        self.run_case("temp-then-exclusive-rename")

    def test_preplanted_or_raced_inbox_name_is_refused(self) -> None:
        self.run_case("preplanted-refused")

    def test_an_entry_planted_in_the_temporary_inbox_is_not_published(self) -> None:
        self.run_case("temp-planted")

    def test_wrong_inbox_is_refused_by_pickup_and_rebuilt_by_prepare(self) -> None:
        self.run_case("rebuild-wrong-inbox")

    def test_wipe_removes_only_the_recipients_own_inbox(self) -> None:
        self.run_case("wipe")

    def test_replica_parent_is_exact_below_an_inheriting_folder(self) -> None:
        # The project tree hands an inheritable staff ACE down; a test root there
        # must not change what the cases see.
        self.run_case("replica-under-inheriting-root")

    # Sender side
    def test_sender_refuses_missing_or_untrusted_inbox(self) -> None:
        self.run_case("sender-refuses-untrusted-inbox")

    def test_concealed_and_password_clippings_are_never_written(self) -> None:
        self.run_case("never-share-filters")

    def test_size_limit_on_send(self) -> None:
        self.run_case("size-limit")

    def test_flood_limit_on_both_sides(self) -> None:
        self.run_case("flood")

    # Pickup
    def test_foreign_owner_is_rejected_unread(self) -> None:
        self.run_case("foreign-owner")

    def test_symlink_hardlink_fifo_directory_and_oversize_are_rejected(self) -> None:
        self.run_case("special-files")

    def test_unknown_sender_folder_is_ignored(self) -> None:
        self.run_case("unknown-sender-folder")

    def test_malformed_payloads_are_deleted(self) -> None:
        self.run_case("malformed")

    def test_nobody_can_rename_or_delete_the_inbox_root(self) -> None:
        self.run_case("root-cannot-be-moved")

    def test_an_inbox_moved_away_before_its_deny_entry_is_refused(self) -> None:
        self.run_case("moved-before-deny")

    def test_only_a_deny_entry_for_everyone_counts(self) -> None:
        self.run_case("deny-only-for-everyone")

    # Defence in depth
    def test_a_file_that_grows_after_the_size_check_is_not_taken_in(self) -> None:
        self.run_case("grows-after-check")

    def test_sender_refuses_its_folder_moved_out_of_the_inbox_after_open(self) -> None:
        self.run_case("folder-moved-after-open")

    def test_pickup_deletes_only_the_file_it_checked(self) -> None:
        self.run_case("replaced-before-delete")

    # Containment
    def test_trace_refuses_writes_outside_the_injected_root(self) -> None:
        output = self.run_case("trace-refuses-outside")
        refused = re.search(r"^REFUSED violations=(\d+)$", output, re.M)
        self.assertIsNotNone(refused, output)
        self.assertGreater(int(refused.group(1)), 0, output)

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
        # Another account's own Flycut may keep its inbox there: real data of that account,
        # read no further than its owner and never touched. None may belong to this account
        # (the snapshot above already fails on any entry that came or went during the run).
        mine = [n for n in os.listdir(SHARED)
                if n.startswith(".flycut-share-") and os.lstat(os.path.join(SHARED, n)).st_uid == os.getuid()]
        self.assertFalse(mine)

    def test_engine_links_no_pasteboard_defaults_network_or_path_api(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True).split()
        (self.artifacts / "undefined-symbols.log").write_text("\n".join(symbols) + "\n")
        for name in ("_OBJC_CLASS_$_NSUserDefaults", "_OBJC_CLASS_$_NSPasteboard",
                     "_NSSearchPathForDirectoriesInDomains", "_socket", "_connect", "_CGEventPost"):
            self.assertNotIn(name, symbols)
        obj = self.artifacts / "FlycutAccountShare.o"
        build = subprocess.run(CLANG + ["-I", str(ROOT / "FlycutEngine"), "-c", str(ENGINE), "-o", str(obj)],
                               cwd=ROOT, text=True, capture_output=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertNotIn("warning:", build.stderr)
        engine = set(subprocess.check_output(["/usr/bin/nm", "-u", str(obj)], text=True).split())
        (self.artifacts / "engine-undefined-symbols.log").write_text("\n".join(sorted(engine)) + "\n")
        for name in ("_OBJC_CLASS_$_NSUserDefaults", "_OBJC_CLASS_$_NSPasteboard", "_OBJC_CLASS_$_NSFileManager",
                     "_OBJC_CLASS_$_NSWorkspace", "_NSHomeDirectory", "_NSSearchPathForDirectoriesInDomains",
                     "_socket", "_connect", "_getpwuid", "_getpwnam"):
            self.assertNotIn(name, engine)
        untraced = sorted((engine & MUTATORS) - TRACED)
        self.assertEqual(untraced, [], "engine uses a filesystem mutator the fixture does not trace")
        source = ENGINE.read_text()
        for token in (r"\bwriteToFile\b", r"\bwriteToURL\b", r"\bdataWithContentsOf", r"\bNSFileManager\b",
                      r'@"/Users/Shared"', r"\bNSHomeDirectory\b"):
            self.assertIsNone(re.search(token, source), token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
