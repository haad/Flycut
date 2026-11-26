#!/usr/bin/env python3
"""Shift-Tab and Tab walk the shown Preferences pane's key-view loop, in both directions.

Full Keyboard Access moves focus along -nextKeyView (Tab) and -previousKeyView
(Shift-Tab). The tab view links the pane it shows into the window's loop when the
pane changes, but its own previous key view kept pointing into the pane that was
shown when the loop was first made (General). After switching to Appearance,
Shift-Tab from the first slider walked back into General's views, which are no
longer in the window, found nothing it could focus and left the focus where it was;
Tab worked.

The fixture loads the production NIB (master's compiled MainMenu.nib for trees that
carry only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py), sends the
builders that -awakeFromNib sends and switches panes with -[UKPrefsPanel
changePanes:], as the toolbar does. The window is never shown, so the loop AppKit
makes when it is first shown is not reproduced; every case changes the pane at least
once more after the first change. For the shown pane it walks the links from the tab
view: every view on the way must be in the window, the walk backward from the pane's
first focus stop must reach its last one (where AppKit wraps to the toolbar), and the
backward stops must be the forward stops reversed (a pane with one stop must lead
back to it). A focus stop is a view in the window, not hidden, that accepts first
responder. AppKit adds the toolbar items to the loop only on screen, so they are not
part of this check.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

FIXTURE = r'''
static NSString *Describe(NSView *v)
{
    if (v == nil) return @"nil";
    NSString *text = @"";
    if ([v isKindOfClass:[NSButton class]]) text = [(NSButton *)v title];
    if ([text length] == 0 && [[v accessibilityLabel] length]) text = [v accessibilityLabel];
    NSString *bound = BoundKeyPath(v);
    return [NSString stringWithFormat:@"%@%@%@%@", NSStringFromClass([v class]),
            [text length] ? [NSString stringWithFormat:@" \"%@\"", text] : @"",
            bound ? [@" " stringByAppendingString:bound] : @"", [v window] == window ? @"" : @" (not in the window)"];
}

static BOOL IsStop(NSView *v)
{
    return [v window] == window && ![v isHiddenOrHasHiddenAncestor] && [v acceptsFirstResponder];
}

// Follows next (or previous) key views from start until it comes back to start, reaches
// nil or has taken 500 steps. Collects the stops and the views that are not in the window.
static NSDictionary *Walk(NSView *start, BOOL forward)
{
    NSMutableArray *stops = [NSMutableArray array], *stopViews = [NSMutableArray array];
    NSMutableArray *outside = [NSMutableArray array];
    NSView *v = forward ? [start nextKeyView] : [start previousKeyView];
    NSUInteger steps = 1;
    while (v != nil && v != start && steps < 500) {
        if ([v window] != window && [outside count] < 5) [outside addObject:Describe(v)];
        if (IsStop(v) && ![stopViews containsObject:v]) { [stopViews addObject:v]; [stops addObject:Describe(v)]; }
        v = forward ? [v nextKeyView] : [v previousKeyView];
        steps++;
    }
    return @{@"stops": stops, @"stopViews": stopViews, @"outside": outside,
             @"end": v == start ? @"back at the start" : (v == nil ? @"nil" : @"500 steps without coming back")};
}

static int CheckPane(NSString *mode)
{
    NSView *tabView = [prefs tabView];
    NSDictionary *forward = Walk(tabView, YES);
    NSArray *stops = forward[@"stopViews"];
    NSMutableDictionary *report = [NSMutableDictionary dictionaryWithDictionary:@{
        @"mode": mode, @"pane": [[[prefs tabView] selectedTabViewItem] label],
        @"forward": forward[@"stops"], @"forwardEnd": forward[@"end"], @"forwardOutside": forward[@"outside"]}];
    int result = 0;
    if ([stops count] == 0) result = 40;
    else if ([forward[@"outside"] count]) result = 41;
    else {
        NSView *first = [stops firstObject], *last = [stops lastObject];
        NSDictionary *backward = Walk(first, NO);
        report[@"backwardFromFirst"] = backward[@"stops"];
        report[@"backwardEnd"] = backward[@"end"];
        report[@"backwardOutside"] = backward[@"outside"];
        NSArray *back = backward[@"stopViews"];
        report[@"shiftTabFromFirstReaches"] = [back count] ? Describe([back firstObject]) : @"no focus stop";
        report[@"expected"] = Describe(last);
        if ([backward[@"outside"] count]) result = 42;          // walks out of the window
        else if ([stops count] == 1) result = [backward[@"end"] isEqualToString:@"back at the start"] ? 0 : 45;
        else if ([back count] == 0 || [back firstObject] != last) result = 43;
        else {
            // Back from the first stop: the last, ..., the second.
            NSMutableArray *reversed = [[[[stops reverseObjectEnumerator] allObjects] mutableCopy] autorelease];
            [reversed removeLastObject];
            if (![back isEqualToArray:reversed]) result = 44;
        }
    }
    Emit(report);
    return result;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        // The first change to General stands in for -[UKPrefsPanel awakeFromNib], which
        // the fixture replaces; the others are the user's clicks in the toolbar.
        NSDictionary *paths = @{@"appearance-after-general": @[@(generalPane), @(appearancePane)],
                                @"hotkeys-after-general": @[@(generalPane), @(hotkeysPane)],
                                @"general-after-appearance": @[@(generalPane), @(appearancePane), @(generalPane)],
                                @"appearance-after-hotkeys": @[@(generalPane), @(hotkeysPane), @(appearancePane)],
                                @"general-again": @[@(generalPane), @(generalPane)]};
        NSArray *path = paths[mode];
        if (path == nil) return 4;
        for (NSNumber *pane in path) ChangePane([pane integerValue]);
        return CheckPane(mode);
    }
}
'''


class PreferencesKeyViewLoopRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "KeyViewLoop"

    def check(self, mode: str) -> None:
        self.run_mode(mode, f"{mode}: Shift-Tab does not walk the shown pane's key-view loop back to its last "
                            "focus stop, or the loop leaves the window")

    def test_shift_tab_from_the_first_appearance_control(self) -> None:
        self.check("appearance-after-general")

    def test_shift_tab_from_the_first_appearance_control_after_hotkeys(self) -> None:
        self.check("appearance-after-hotkeys")

    def test_shift_tab_from_the_first_hotkeys_control(self) -> None:
        self.check("hotkeys-after-general")

    def test_shift_tab_from_the_first_general_control_after_appearance(self) -> None:
        self.check("general-after-appearance")

    def test_shift_tab_from_the_first_general_control_after_clicking_general(self) -> None:
        self.check("general-again")


if __name__ == "__main__":
    unittest.main()
