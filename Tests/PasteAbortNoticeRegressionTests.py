#!/usr/bin/env python3
"""A paste the user chose that ends without Command-V says so: one log line, never the content,
and the alert sound (not for a paste that a newer selection replaced; a plain copy
that cannot be written is logged without it).

The test drives the real AppController paste transaction on the in-memory clipboard of
ClipboardOwnershipRegressionTests (its fixture counts NSBeep on stderr instead of playing it) and
counts what a user or a log reader notices when a chosen clipping is NOT pasted: log lines beyond
the routine ones, and beeps. Every such end gives exactly one line and one beep. What each case
does with the clipboard is ClipboardOwnershipRegressionTests' business and stays as it was.
"""
import re
import unittest

from PasteNativeTestSupport import build_fixture, run_fixture
from ClipboardOwnershipRegressionTests import FIXTURE as BASE

HIDE = 'FCNOTICE-HIDEAPP'
BEEP = 'FCTEST-BEEP'
ROUTINE = (
    HIDE,
    BEEP,
    'pasteFromStack called',
    'Content found; adding it to the pasteboard and preparing to paste',
    'metaKeysReleased called - isBezelPinned: NO',
)
# The fixed, content-free lines a dropped paste may log (whole lines; a clipping's text never).
FIXED = {
    'Paste cancelled because the clipboard no longer holds the chosen clipping',
    'Paste cancelled because focus left the original transaction before activation',
    'Could not reactivate the application selected for paste',
    'Paste could not be posted; the selection stays on the clipboard',
    'Paste cancelled because the original target did not become frontmost',
    'Paste cancelled because the clipboard changed while it was being saved',
    'Paste cancelled because a newer selection replaced it',
    'Could not write the clipboard',
    'Paste cancelled because the clipboard could not be written',
}


def patched(source):
    def once(old, new):
        assert source.count(old) == 1, (source.count(old), old)
        return source.replace(old, new)
    source = once('board.writeFails=[mode isEqual:@"write-failed"];',
                  'board.writeFails=[mode hasSuffix:@"write-failed"];')
    source = once('board.changesDuringSnapshot=[mode isEqual:@"snapshot-changed"];',
                  'board.changesDuringSnapshot=[mode hasSuffix:@"snapshot-changed"];')
    source = once('if ([mode isEqual:@"unsaved-list"]) {',
                  'if ([mode isEqual:@"unsaved-list"] || [mode hasPrefix:@"list-"]) {')
    source = once('- (void)hideApp { isBezelDisplayed=NO; }',
                  '- (void)hideApp { isBezelDisplayed=NO; fprintf(stderr, "' + HIDE + '\\n"); }')
    source = once('inList:FlycutListHistory];\n    } else if ([mode hasPrefix:@"copy-only"]) {',
                  'inList:FlycutListHistory];\n'
                  '        if ([mode isEqual:@"list-external"]) {\n'
                  '            [board declareTypes:nil owner:nil]; [board setString:@"external copy" forType:NSPasteboardTypeString];\n'
                  '        }\n'
                  '    } else if ([mode hasPrefix:@"copy-only"]) {')
    source = once('    if ([mode isEqual:@"empty-cancel"]) {\n        if (c.posts || board.value) return 25;',
                  '    if ([mode hasPrefix:@"list-"]) {\n'
                  '        if (c.posts) { fprintf(stderr,"a list abort mode posted a paste\\n"); return 40; }\n'
                  '        if ([mode isEqual:@"list-external"] && ![board.value isEqual:@"external copy"]) return 41;\n'
                  '        if ([mode hasSuffix:@"-failed"] && [board.value isEqual:@"selected"]) return 42;\n'
                  '        printf("PASS clipboard ownership %s\\n",argv[1]); return 0;\n'
                  '    } else if ([mode isEqual:@"empty-cancel"]) {\n        if (c.posts || board.value) return 25;')
    # A plain copy (a list row with "Menu selection pastes" off) whose write fails, and a paste
    # that a newer selection replaces while the clipboard is being saved.
    source = once('@interface MemoryBoard : NSObject\n',
                  'static id FCNoticeController;   // the controller a board callback opens a new selection on\n'
                  '@interface MemoryBoard : NSObject\n')
    source = once('@property BOOL changesDuringSnapshot;\n',
                  '@property BOOL changesDuringSnapshot;\n@property BOOL supersedesDuringSnapshot;\n')
    source = once('- (NSArray *)pasteboardItems {\n',
                  '- (NSArray *)pasteboardItems {\n'
                  '    if (self.supersedesDuringSnapshot) { self.supersedesDuringSnapshot=NO; [FCNoticeController rememberFrontmostApplicationForPaste]; }\n')
    source = once('[c prepare:board operator:op];\n',
                  '[c prepare:board operator:op];\n'
                  '    FCNoticeController=c; board.supersedesDuringSnapshot=[mode isEqual:@"superseded-while-saved"];\n')
    source = once('    if ([mode isEqual:@"unsaved-list"] || [mode hasPrefix:@"list-"]) {\n',
                  '    if ([mode isEqual:@"copy-write-failed"]) {\n'
                  '        [[NSUserDefaults standardUserDefaults] setBool:NO forKey:@"menuSelectionPastes"];\n'
                  '        [(id<FlycutListControllerDelegate>)c listController:nil didChooseClipping:[op clippingAtStackPosition] inList:FlycutListHistory];\n'
                  '    } else if ([mode isEqual:@"unsaved-list"] || [mode hasPrefix:@"list-"]) {\n')
    source = once('    if ([mode hasPrefix:@"list-"]) {\n        if (c.posts) {',
                  '    if ([mode isEqual:@"copy-write-failed"] || [mode isEqual:@"superseded-while-saved"]) {\n'
                  '        if (c.posts || c.postAttempts) return 44;\n'
                  '        if ([mode isEqual:@"copy-write-failed"] && [board.value isEqual:@"selected"]) return 45;\n'
                  '        printf("PASS clipboard ownership %s\\n",argv[1]); return 0;\n'
                  '    }\n'
                  '    if ([mode hasPrefix:@"list-"]) {\n        if (c.posts) {')
    return source


def lines(stderr):
    """Log lines beyond the routine ones (NSLog's prefix removed)."""
    found = []
    for line in stderr.splitlines():
        text = re.sub(r'^\d{4}-\d\d-\d\d [\d:.]+ \S+\[\d+:\d+\] ', '', line).strip()
        if text and text not in ROUTINE:
            found.append(text)
    return found


class PasteAbortNoticeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(patched(BASE), 'PasteAbortNoticeFixture')

    def notices(self, mode):
        run = run_fixture(self.binary, mode)
        # The fixture's own verdict first: nothing was posted, the clipboard is as before.
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        found = lines(run.stderr)
        beeps = run.stderr.count(BEEP)
        hides = run.stderr.count(HIDE)
        print(f'{mode}: lines={found} beeps={beeps} hides={hides}')
        for text in found:
            self.assertIn(text, FIXED, f'{mode}: not one of the fixed, content-free lines')
        return found, beeps, hides

    def says_so_once(self, mode):
        found, beeps, _ = self.notices(mode)
        self.assertEqual(len(found), 1, f'{mode}: want exactly one log line, got {found}')
        self.assertEqual(beeps, 1, f'{mode}: want exactly one beep, got {beeps}')

    # Bezel: the target lost focus, could not be activated, or refused the posted key.
    def test_focus_loss_logs_and_beeps(self):
        self.says_so_once('focus-left')

    def test_refused_post_logs_and_beeps(self):
        self.says_so_once('post-rejected')

    def test_refused_activation_logs_and_beeps(self):
        self.says_so_once('activation-refused')

    # Bezel: another process writes the clipboard between Flycut's write and Command-V.
    def test_bezel_paste_dropped_for_a_foreign_clipboard_write_logs_and_beeps(self):
        self.says_so_once('external')

    def test_bezel_paste_dropped_for_a_foreign_write_after_activation_logs_and_beeps(self):
        self.says_so_once('external-after-activation')

    def test_bezel_paste_dropped_for_a_failed_clipboard_write_logs_and_beeps(self):
        self.says_so_once('write-failed')

    def test_bezel_paste_dropped_for_a_clipboard_changing_while_saved_logs_and_beeps(self):
        self.says_so_once('snapshot-changed')

    # Menu-bar list row with "Menu selection pastes" on.
    def test_list_paste_dropped_for_a_foreign_clipboard_write_logs_and_beeps(self):
        self.says_so_once('list-external')

    def test_list_paste_dropped_for_a_failed_clipboard_write_logs_and_beeps(self):
        self.says_so_once('list-write-failed')

    def test_list_paste_dropped_for_a_clipboard_changing_while_saved_logs_and_beeps(self):
        self.says_so_once('list-snapshot-changed')

    # No paste, so no alert sound: a plain copy whose write fails, and a paste that a newer
    # selection replaced while the clipboard was being saved (the newer one pastes).
    def test_a_plain_copy_that_cannot_be_written_is_logged_without_a_beep(self):
        found, beeps, _ = self.notices('copy-write-failed')
        self.assertEqual((found, beeps), (['Could not write the clipboard'], 0))

    def test_a_paste_replaced_by_a_newer_selection_while_saving_does_not_beep(self):
        found, beeps, _ = self.notices('superseded-while-saved')
        self.assertEqual((found, beeps), (['Paste cancelled because a newer selection replaced it'], 0))

    # A delivered paste stays quiet.
    def test_a_delivered_paste_neither_logs_nor_beeps(self):
        found, beeps, _ = self.notices('payload')
        self.assertEqual((found, beeps), ([], 0))


if __name__ == '__main__':
    unittest.main()
