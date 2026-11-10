#!/usr/bin/env python3
"""Regression test for preserving the clipboard during app launch."""

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_CONTROLLER = REPO_ROOT / "AppController.m"


def objective_c_method(source: str, signature: str) -> str:
    """Return one Objective-C method, ending at the next method declaration."""
    start = source.index(signature)
    remainder = source[start + len(signature) :]
    next_method = re.search(r"\n[+-]\s*\([^\n]+\)", remainder)
    end = start + len(signature) + next_method.start() if next_method else len(source)
    return source[start:end]


class ClipboardLaunchRegressionTests(unittest.TestCase):
    def test_launch_does_not_replace_current_clipboard_contents(self) -> None:
        source = APP_CONTROLLER.read_text(encoding="utf-8")
        awake_from_nib = objective_c_method(source, "- (void)awakeFromNib")

        self.assertNotIn(
            "[jcPasteboard declareTypes:",
            awake_from_nib,
            "awakeFromNib must observe the pasteboard without declaring new types; "
            "declareTypes: replaces the user's current clipboard contents",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
