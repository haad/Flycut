#!/usr/bin/env python3
""""Diagnostics: save data type, not content": one row per copy with all of its data types.

The row lists every type of the copy, the markers that the Password types list and the
concealed option match (org.nspasteboard.ConcealedType, com.agilebits.onepassword) among them,
also for a copy the filters would skip and for one that holds no text or image. It never holds
the copied content. The cases run the real -pollPB: of Tests/Fixtures/RichTextFormatting.m
(real FlycutClipping/FlycutStore/FlycutOperator on an in-memory clipboard and defaults).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

import RichTextFormattingRegressionTests as base

ROOT = base.ROOT
CASES = r"""
static NSArray *HistoryTexts(FCOperator *op) {
    NSMutableArray *texts = [NSMutableArray array];
    for (int i = 0; i < [op jcListCount]; i++) [texts addObject:[op getClipFromCount:i] ?: @"(nil)"];
    return texts;
}

static BOOL RowIs(NSString *row, NSArray *types) {
    return [[NSSet setWithArray:[row componentsSeparatedByString:@", "]] isEqualToSet:[NSSet setWithArray:types]]
        && [[row componentsSeparatedByString:@", "] count] == [types count];
}

static FCAppHarness *DiagnosticsHarness(FCOperator *op) {
    FCAppHarness *app = FreshHarness(op);
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"revealPasteboardTypes"];
    return app;
}

// A password manager's copy: text plus the markers the filters match; the concealed filter is on.
static void RunDiagnosticsPasswordManager(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-secret", @"com.agilebits.onepassword": [NSData data],
                                        @"org.nspasteboard.ConcealedType": [NSData data]}];
    [app pollPB:nil];
    NSArray *texts = HistoryTexts(op);
    Check([texts count] == 1, "one row for the copy");
    Check(RowIs([texts firstObject], @[NSPasteboardTypeString, @"com.agilebits.onepassword", @"org.nspasteboard.ConcealedType"]),
          "the row lists every type of the copy, the markers among them");
    Check(![[texts componentsJoinedByString:@"|"] containsString:@"example-secret"], "never the content");
}

static void RunDiagnosticsRowPerCopy(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-1"}];
    [app pollPB:nil];
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-2", @"org.nspasteboard.TransientType": [NSData data]}];
    [app pollPB:nil];
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-3", NSPasteboardTypeRTF: Bytes(@"{\\rtf1 x}")}];
    [app pollPB:nil];
    NSArray *texts = HistoryTexts(op);
    Check([texts count] == 3, "three copies of different kinds give three rows");
    Check([texts count] == 3 && RowIs(texts[0], @[NSPasteboardTypeString, NSPasteboardTypeRTF]) &&
          RowIs(texts[1], @[NSPasteboardTypeString, @"org.nspasteboard.TransientType"]) && RowIs(texts[2], @[NSPasteboardTypeString]),
          "each row lists its own copy's types, newest first");
    Check(![[texts componentsJoinedByString:@"|"] containsString:@"example-"], "never the content");
}

// A copy with neither text nor an image: a type declared without data, as a password manager
// leaves the clipboard when it clears it.
static void RunDiagnosticsWithoutTextOrImage(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [app->jcPasteboard copyGeneration:@{@"org.nspasteboard.ConcealedType": [NSData data]}];
    [app pollPB:nil];
    NSArray *texts = HistoryTexts(op);
    Check([texts count] == 1 && RowIs([texts firstObject], @[@"org.nspasteboard.ConcealedType"]),
          "a copy without text or image gets its row too");
}

static void RunDiagnosticsImageWithCaptureOff(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [[FCFakeDefaults standardUserDefaults] setObject:@NO forKey:@"captureImages"];
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeTIFF: Bytes(@"not really a tiff")}];
    [app pollPB:nil];
    NSArray *texts = HistoryTexts(op);
    Check([texts count] == 1 && RowIs([texts firstObject], @[NSPasteboardTypeTIFF]),
          "an image copy gets its row with image capture off too");
}

static void RunDiagnosticsOwnWrite(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [app addClipToPasteboard:@"example-own" withRichData:nil];
    [app pollPB:nil];
    Check([op jcListCount] == 0, "Flycut's own write gives no row");
}

// Rows merge like clippings: the same types as the newest row add none; with "Remove duplicates"
// on, an equal row further down moves to the top.
static void RunDiagnosticsSameTypesMerge(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = DiagnosticsHarness(op);
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-1"}];
    [app pollPB:nil];
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-2"}];
    [app pollPB:nil];
    Check([op jcListCount] == 1, "a copy with the newest row's types adds no row");
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-3", @"org.nspasteboard.TransientType": [NSData data]}];
    [app pollPB:nil];
    Check([op jcListCount] == 2, "other types add a row");
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"example-4"}];
    [app pollPB:nil];
    NSArray *texts = HistoryTexts(op);
    Check([texts count] == 2, "with Remove duplicates on, an equal row is not added again");
    Check(RowIs([texts firstObject], @[NSPasteboardTypeString]), "the equal row moved to the top");
}
"""
MODES = {
    "diagnostics-password-manager": "RunDiagnosticsPasswordManager",
    "diagnostics-row-per-copy": "RunDiagnosticsRowPerCopy",
    "diagnostics-without-text-or-image": "RunDiagnosticsWithoutTextOrImage",
    "diagnostics-image-with-capture-off": "RunDiagnosticsImageWithCaptureOff",
    "diagnostics-own-write": "RunDiagnosticsOwnWrite",
    "diagnostics-same-types-merge": "RunDiagnosticsSameTypesMerge",
}


def patched_fixture() -> str:
    source = base.FIXTURE.read_text()
    marker = "int main(int argc, const char *argv[]) {"
    assert source.count(marker) == 1
    source = source.replace(marker, CASES + "\n" + marker)
    first = 'if (strcmp(argv[1], "capture-stable") == 0) RunCaptureStable();'
    assert source.count(first) == 1
    extra = "".join(f'if (strcmp(argv[1], "{mode}") == 0) {function}();\n        else ' for mode, function in MODES.items())
    return source.replace(first, extra + first)


class DiagnosticsTypesRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-diagnostics-types-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name).resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        source = base.APP_CONTROLLER.read_text()
        methods = "\n".join(base.method_body(source, signature) for signature in base.METHODS)
        (cls.artifacts / "AppControllerMethods.inc").write_text(methods + "\n")
        types = [match.group(0) for pattern in base.TYPES for match in [re.search(pattern, source, re.S)] if match]
        (cls.artifacts / "AppControllerTypes.inc").write_text("\n".join(types) + "\n")
        fixture = cls.artifacts / "DiagnosticsTypes.m"
        fixture.write_text(patched_fixture())
        cls.binary = cls.artifacts / "DiagnosticsTypes"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"), "-I", str(cls.artifacts),
                   str(fixture), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
        (cls.artifacts / "diagnostics-types-build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr[-4000:]}")

    def run_case(self, case: str) -> None:
        run = subprocess.run([str(self.binary), case], cwd=ROOT, text=True, capture_output=True, timeout=30)
        output = run.stdout + run.stderr
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)

    def test_a_password_managers_copy_gives_one_row_with_all_its_types(self) -> None:
        self.run_case("diagnostics-password-manager")

    def test_every_copy_gets_its_own_row(self) -> None:
        self.run_case("diagnostics-row-per-copy")

    def test_a_copy_without_text_or_image_gets_a_row(self) -> None:
        self.run_case("diagnostics-without-text-or-image")

    def test_an_image_copy_gets_a_row_with_image_capture_off(self) -> None:
        self.run_case("diagnostics-image-with-capture-off")

    def test_rows_with_the_same_types_merge_like_clippings(self) -> None:
        self.run_case("diagnostics-same-types-merge")

    def test_the_tooltip_says_one_row_per_copy_and_how_rows_merge(self) -> None:
        import xml.etree.ElementTree as ElementTree
        xib = ElementTree.parse(ROOT / "English.lproj" / "MainMenu.xib")
        tip = next(e.get("toolTip") for e in xib.iter() if e.get("id") == "mka-NZ-Esg")
        self.assertTrue(tip.startswith("For troubleshooting: saves one row per copy with all of its data types "), tip)
        self.assertIn(" skip. A copy with the same data types as the newest row adds none, and with \"Remove duplicates\" "
                      "on, a listed row with the same types moves to the top. Use it ", tip)

    def test_flycuts_own_write_gives_no_row(self) -> None:
        self.run_case("diagnostics-own-write")

    def test_fixture_uses_no_real_pasteboard_defaults_or_application_support(self) -> None:
        symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(self.binary)], text=True)
        for name in ("_OBJC_CLASS_$_NSPasteboard", "_OBJC_CLASS_$_NSWorkspace", "_OBJC_CLASS_$_NSUserDefaults",
                     "_NSSearchPathForDirectoriesInDomains", "_CGEventPost"):
            self.assertNotIn(name + "\n", symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
