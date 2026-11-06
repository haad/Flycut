#!/usr/bin/env python3
"""Source integration regressions for Flycut's Accessibility UI flow."""

from pathlib import Path
import re
import unittest

# Run compiled production-method regressions through the existing test entry point.
from AccessibilityPromptRegressionTests import AccessibilityPromptRegressionTests


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_CONTROLLER_M = REPO_ROOT / "AppController.m"


def objective_c_method(source: str, signature: str) -> str:
    """Return one Objective-C method, ending at the next method declaration."""
    start = source.index(signature)
    remainder = source[start + len(signature) :]
    next_method = re.search(r"\n[+-]\s*\([^\n]+\)", remainder)
    end = start + len(signature) + next_method.start() if next_method else len(source)
    return source[start:end]


class AccessibilityPromptSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.implementation = APP_CONTROLLER_M.read_text(encoding="utf-8")

    def test_launch_does_not_show_accessibility_explanation(self) -> None:
        awake_from_nib = objective_c_method(self.implementation, "- (void)awakeFromNib")
        self.assertNotIn("[self showAccessibilityAlert]", awake_from_nib)

    def test_launch_does_not_activate_flycut(self) -> None:
        awake_from_nib = objective_c_method(self.implementation, "- (void)awakeFromNib")
        self.assertNotIn("activateIgnoringOtherApps", awake_from_nib)

    def test_system_prompt_request_does_not_force_open_settings(self) -> None:
        request_prompt = objective_c_method(
            self.implementation, "- (void)requestAccessibilityWithPrompt"
        )
        self.assertNotIn("[self openAccessibilitySettings]", request_prompt)

    def test_failed_paste_routes_through_session_policy(self) -> None:
        fake_command_v = objective_c_method(self.implementation, "-(void)fakeCommandV")
        policy_call = "FlycutShouldShowAccessibilityExplanation("
        mark_statement = "hasShownAccessibilityExplanationThisSession = YES;"
        show_statement = "[self showAccessibilityAlert];"
        for statement in (policy_call, mark_statement, show_statement):
            self.assertIn(statement, fake_command_v)
        policy = fake_command_v.index(policy_call)
        mark_shown = fake_command_v.index(mark_statement)
        show = fake_command_v.index(show_statement)
        self.assertLess(policy, mark_shown)
        self.assertLess(mark_shown, show)
        self.assertNotIn("dispatch_async", fake_command_v)

    def test_denied_paste_requests_native_consent_without_prerequisite_ui(self) -> None:
        show_alert = objective_c_method(
            self.implementation, "- (void)showAccessibilityAlert"
        )
        self.assertIn("[self requestAccessibilityWithPrompt]", show_alert)
        self.assertNotIn("NSAlert", show_alert)
        self.assertNotIn("[self openAccessibilitySettings]", show_alert)
        self.assertNotIn("[NSApp activateIgnoringOtherApps:", show_alert)
        self.assertNotIn("[self hideApp]", show_alert)

    def test_manual_recheck_has_no_untrusted_dialog_or_settings_navigation(self) -> None:
        recheck = objective_c_method(self.implementation, "-(IBAction)recheckAccessibility:")
        self.assertIn("[self requestAccessibilityWithPrompt]", recheck)
        self.assertNotIn("Accessibility Access Required", recheck)
        self.assertNotIn("[self openAccessibilitySettings]", recheck)
        self.assertEqual(recheck.count("[alert runModal]"), 1)  # Trusted information only.

    def test_launch_checks_trust_without_requesting_native_consent(self) -> None:
        awake_from_nib = objective_c_method(self.implementation, "- (void)awakeFromNib")
        self.assertIn("kAXTrustedCheckOptionPrompt): @NO", awake_from_nib)
        self.assertIn("AXIsProcessTrustedWithOptions", awake_from_nib)
        self.assertNotIn("kAXTrustedCheckOptionPrompt): @YES", awake_from_nib)
        self.assertNotIn("requestAccessibilityWithPrompt", awake_from_nib)
        self.assertNotIn("recheckAccessibility:", awake_from_nib)
        self.assertNotIn("openAccessibilitySettings", awake_from_nib)


if __name__ == "__main__":
    unittest.main(verbosity=2)
