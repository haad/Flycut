#!/usr/bin/env python3
"""Every interactive Preferences and search control has an accessible name.

VoiceOver announces a control by its accessibility label, title or title element; the
tooltip (AXHelp) is only read later as a hint, and a placeholder is not a name. Master's
NIB gives the General pane's steppers, Save popup and list fields none, and the
code-built sliders, search window field and table, and the status menu's search field
have none either.

The fixture loads the production NIB (master's compiled MainMenu.nib for trees that carry
only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py), sends the builders that
-awakeFromNib sends, and reads the in-process NSAccessibility values of every visible
interactive control (the view, or the cell of a cell-based control, which is what
VoiceOver reads; new and legacy attribute API). A name must be the
label shown next to the control (the nearest static text or checkbox to its left on the
same line, the search window's title, the table's column header, the menu item's
title). The search window is built without a NIB.
The two password list fields are the exception: the checkbox in front of each is a
sub-option of "Don't save passwords" in MainMenu.xib ("by data type:", "by length &
complexity:"), which does not say what the field holds, so the fields have fixed names,
also when the checkboxes carry the xib's titles.
Nothing is ordered on screen; this is not a live VoiceOver run.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import ROOT, PreferencesNibCase  # noqa: E402

XIB = ROOT / "English.lproj" / "MainMenu.xib"
# The password checkboxes: the group and the two in front of the list fields.
XIB_CHECKBOXES = ("values.skipPasswordFields", "values.skipPboardTypes", "values.skipPasswordLengths")


def xib_checkbox_titles() -> tuple[str, ...]:
    """"keyPath=title" of those checkboxes as MainMenu.xib titles them."""
    pairs = []
    for button in ET.parse(XIB).getroot().iter("button"):
        cell, binding = button.find("buttonCell"), button.find("connections/binding[@name='value']")
        if cell is not None and binding is not None and binding.get("keyPath") in XIB_CHECKBOXES:
            pairs.append(f"{binding.get('keyPath')}={cell.get('title')}")
    return tuple(pairs)

FIXTURE = r'''
@interface AppController (AccessibleNamesTesting)
- (void)buildSearchWindow;
@end

static NSString *Str(id value) { return [value isKindOfClass:[NSString class]] ? value : nil; }
static id Legacy(id element, NSString *attribute)
{
    id value = nil;
    @try { value = [element accessibilityAttributeValue:attribute]; } @catch (id ignored) { value = nil; }
    return value;
}
static NSString *TextOf(id element)
{
    if (element == nil) return nil;
    if ([element isKindOfClass:[NSButton class]]) return [(NSButton *)element title];
    if ([element respondsToSelector:@selector(stringValue)]) return [element stringValue];
    return Str([element accessibilityValue]);
}
static NSString *Trim(NSString *text)
{
    return [text stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@": .\u2026\n\t"]];
}

// Every source VoiceOver can use as the control's name, from the view and its cell.
static NSDictionary *NameSources(NSView *view)
{
    NSMutableDictionary *sources = [NSMutableDictionary dictionary];
    id cell = [view respondsToSelector:@selector(cell)] ? [(NSControl *)view cell] : nil;
    NSArray *elements = cell ? @[view, cell] : @[view];
    NSArray *names = cell ? @[@"view", @"cell"] : @[@"view"];
    for (NSUInteger i = 0; i < [elements count]; i++) {
        id e = elements[i]; NSString *n = names[i];
        if ([Str([e accessibilityLabel]) length]) sources[[n stringByAppendingString:@".label"]] = [e accessibilityLabel];
        if ([Str([e accessibilityTitle]) length]) sources[[n stringByAppendingString:@".title"]] = [e accessibilityTitle];
        NSString *t = TextOf([e accessibilityTitleUIElement]);
        if ([t length]) sources[[n stringByAppendingString:@".titleUIElement"]] = t;
        if ([Str(Legacy(e, NSAccessibilityDescriptionAttribute)) length]) sources[[n stringByAppendingString:@".AXDescription"]] = Legacy(e, NSAccessibilityDescriptionAttribute);
        if ([Str(Legacy(e, NSAccessibilityTitleAttribute)) length]) sources[[n stringByAppendingString:@".AXTitle"]] = Legacy(e, NSAccessibilityTitleAttribute);
        NSString *lt = TextOf(Legacy(e, NSAccessibilityTitleUIElementAttribute));
        if ([lt length]) sources[[n stringByAppendingString:@".AXTitleUIElement"]] = lt;
    }
    return sources;
}

// The element VoiceOver reads: the view, or for a cell-based control that is not an
// accessibility element itself (stepper, pop-up button, slider) its cell.
static id AXElement(NSView *view)
{
    if ([view isAccessibilityElement]) return view;
    id cell = [view respondsToSelector:@selector(cell)] ? [(NSControl *)view cell] : nil;
    if (cell != nil && [cell isAccessibilityElement]) return cell;
    return view;
}

static NSString *NameOf(NSView *view)
{
    NSDictionary *sources = NameSources(view);
    NSString *prefix = AXElement(view) == view ? @"view" : @"cell";
    for (NSString *kind in @[@".label", @".title", @".titleUIElement", @".AXDescription", @".AXTitle", @".AXTitleUIElement"])
        if (sources[[prefix stringByAppendingString:kind]]) return sources[[prefix stringByAppendingString:kind]];
    return nil;
}

static BOOL IsStaticText(NSView *view)
{
    return [view isKindOfClass:[NSTextField class]] && ![(NSTextField *)view isEditable];
}

static BOOL Interactive(NSView *view)
{
    if ([view isKindOfClass:[NSTextField class]] && ![view isKindOfClass:[NSSearchField class]])
        return [(NSTextField *)view isEditable];             // static labels are not controls
    for (NSString *name in @[@"NSStepper", @"NSSlider", @"NSPopUpButton", @"NSSearchField", @"NSTableView",
                             @"NSButton", @"NSColorWell", @"SRRecorderControl", @"NSSegmentedControl"])
        if ([view isKindOfClass:NSClassFromString(name)]) return YES;
    return NO;
}

// Controls that get their name from a label next to them, not from their own title.
static BOOL LabelledByNeighbour(NSView *view)
{
    return [view isKindOfClass:[NSStepper class]] || [view isKindOfClass:[NSSlider class]] ||
           [view isKindOfClass:[NSPopUpButton class]] ||
           ([view isKindOfClass:[NSTextField class]] && ![view isKindOfClass:[NSSearchField class]]);
}

// The label a sighted user reads for the control: the nearest static text (not a bound
// value field) or checkbox to its left on the same line.
static NSString *VisibleLabel(NSView *view)
{
    NSRect frame = [view frame];
    NSView *best = nil;
    for (NSView *other in [[view superview] subviews]) {
        if (other == view || [other isHidden]) continue;
        BOOL label = IsStaticText(other) && BoundKeyPath(other) == nil;
        BOOL checkbox = [other isKindOfClass:[NSButton class]] && BoundKeyPath(other) != nil && [[(NSButton *)other title] length];
        if (!label && !checkbox) continue;
        NSRect o = [other frame];
        CGFloat overlap = MIN(NSMaxY(o), NSMaxY(frame)) - MAX(NSMinY(o), NSMinY(frame));
        if (overlap <= 2.0 || NSMaxX(o) > NSMinX(frame) + 4.0) continue;
        if (best == nil || NSMaxX(o) > NSMaxX([best frame])) best = other;
    }
    if (best == nil) return nil;
    return Trim(IsStaticText(best) ? [(NSTextField *)best stringValue] : [(NSButton *)best title]);
}

static BOOL HiddenBelow(NSView *view, NSView *root)
{
    for (NSView *v = view; v != nil && v != root; v = [v superview]) if ([v isHidden]) return YES;
    return NO;
}

static void Collect(NSView *view, NSView *root, NSMutableArray *out)
{
    if (Interactive(view) && !HiddenBelow(view, root)) [out addObject:view];
    if ([view isKindOfClass:NSClassFromString(@"SRRecorderControl")] || [view isKindOfClass:[NSTableView class]]) return;
    for (NSView *child in [view subviews]) Collect(child, root, out);
}

static NSView *FindBound(NSView *root, NSString *keyPath, BOOL (^match)(NSView *))
{
    if ([BoundKeyPath(root) isEqualToString:keyPath] && match(root)) return root;
    for (NSView *child in [root subviews]) {
        NSView *found = FindBound(child, keyPath, match);
        if (found) return found;
    }
    return nil;
}

// The two password list fields' names, whatever the checkbox in front of them says.
static NSDictionary *FixedNames(void)
{
    return @{@"values.skipPboardTypesList": @"Password data types",
             @"values.skipPasswordLengthsList": @"Password lengths"};
}

// Checkbox titles (binding key path -> title) from MainMenu.xib, set before the builders
// run, as a NIB compiled from the xib would have them.
static NSDictionary *xibTitles;
static NSUInteger xibTitlesSet;
static void SetXibTitles(void)
{
    for (NSView *view in [[[controller valueForKey:@"savingSectionLabel"] superview] subviews]) {
        NSString *title = xibTitles[BoundKeyPath(view) ?: @""];
        if (title == nil || ![view isKindOfClass:[NSButton class]]) continue;
        [(NSButton *)view setTitle:title];
        xibTitlesSet++;
    }
}

// expected: control -> the name it must have (search window, menu); nil = its visible label.
static int Check(NSString *mode, NSView *root, NSMapTable *expected)
{
    NSMutableArray *views = [NSMutableArray array];
    Collect(root, root, views);
    NSMutableArray *controls = [NSMutableArray array], *unnamed = [NSMutableArray array];
    NSMutableArray *mislabelled = [NSMutableArray array], *unreadValues = [NSMutableArray array];
    for (NSView *view in views) {
        NSString *name = NameOf(view);
        NSString *bound = BoundKeyPath(view);
        id element = AXElement(view);
        NSMutableDictionary *row = [NSMutableDictionary dictionaryWithDictionary:@{
            @"class": NSStringFromClass([view class]), @"binding": bound ?: @"", @"name": name ?: @"",
            @"element": element == view ? @"view" : @"cell",
            @"nameSources": NameSources(view), @"help": Str([element accessibilityHelp]) ?: @""}];
        id value = [element accessibilityValue];
        if ([value isKindOfClass:[NSString class]] || [value isKindOfClass:[NSNumber class]]) row[@"value"] = value;
        NSString *want = [expected objectForKey:view];
        if (want == nil && LabelledByNeighbour(view)) want = VisibleLabel(view) ?: @"<no visible label>";
        if (want) row[@"expected"] = want;
        [controls addObject:row];
        if ([name length] == 0) [unnamed addObject:row];
        else if (want && ![name isEqualToString:want]) [mislabelled addObject:row];
        if ([view isKindOfClass:[NSStepper class]] && bound) {
            // A stepper left in a pane: its value is the number shown in the field beside it
            // (the General pane's steppers are taken out when its number fields are built).
            NSTextField *field = (NSTextField *)FindBound(root, bound, ^BOOL(NSView *v) {
                return [v isKindOfClass:[NSTextField class]] && ![v isKindOfClass:[NSSearchField class]];
            });
            row[@"shownNumber"] = field ? [field stringValue] : @"<no field>";
            if (field == nil || ![value isKindOfClass:[NSNumber class]] || [value integerValue] != [field integerValue])
                [unreadValues addObject:row];
        }
    }
    Emit(@{@"mode": mode, @"controls": controls, @"unnamed": unnamed, @"mislabelled": mislabelled, @"unreadValues": unreadValues,
           @"summary": [NSString stringWithFormat:@"%lu interactive, %lu without a name, %lu not named after their label, %lu steppers without the shown number",
                        (unsigned long)[controls count], (unsigned long)[unnamed count], (unsigned long)[mislabelled count],
                        (unsigned long)[unreadValues count]]});
    if ([controls count] == 0) return 31;
    if ([unnamed count]) return 30;
    if ([mislabelled count]) return 32;
    if ([unreadValues count]) return 33;
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 4) return 2;
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        NSMapTable *expected = [NSMapTable strongToStrongObjectsMapTable];
        if ([mode isEqualToString:@"search-window"]) {
            // Built in code; no NIB needed.
            if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
            InstallBoundaries();
            controller = [[AppController alloc] init];
            [controller buildSearchWindow];
            NSWindow *search = [controller valueForKey:@"searchWindow"];
            NSTableView *table = [controller valueForKey:@"searchWindowTableView"];
            [expected setObject:[search title] forKey:[controller valueForKey:@"searchWindowSearchField"]];
            [expected setObject:[[[table tableColumns] firstObject] title] forKey:table];
            return Check(mode, [search contentView], expected);
        }
        BOOL xib = [mode isEqualToString:@"general-xib-titles"];
        if (xib) {
            NSMutableDictionary *titles = [NSMutableDictionary dictionary];
            for (int i = 4; i < argc; i++) {
                NSString *pair = [NSString stringWithUTF8String:argv[i]];
                NSRange equals = [pair rangeOfString:@"="];
                if (equals.location == NSNotFound) return 5;
                titles[[pair substringToIndex:equals.location]] = [pair substringFromIndex:NSMaxRange(equals)];
            }
            if ([titles count] == 0) return 5;
            xibTitles = [titles retain];
            BeforeBuilders = SetXibTitles;
        }
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        if (xib && xibTitlesSet != [xibTitles count]) return 13;     // a checkbox of the xib is not in the NIB
        if ([mode isEqualToString:@"general"] || xib) {
            ChangePane(generalPane);
            NSView *pane = PaneView(generalPane);
            for (NSString *keyPath in FixedNames()) {
                NSView *field = FindBound(pane, keyPath, ^BOOL(NSView *v) {
                    return [v isKindOfClass:[NSTextField class]] && [(NSTextField *)v isEditable];
                });
                if (field == nil) return 14;
                [expected setObject:FixedNames()[keyPath] forKey:field];
            }
            return Check(mode, pane, expected);
        }
        if ([mode isEqualToString:@"appearance"]) { ChangePane(appearancePane); return Check(mode, PaneView(appearancePane), expected); }
        if ([mode isEqualToString:@"hotkeys"]) {
            ChangePane(hotkeysPane);
            return Check(mode, [[controller valueForKey:@"mainRecorder"] superview], expected);
        }
        if ([mode isEqualToString:@"status-menu-search"]) {
            NSSearchField *box = [controller valueForKey:@"searchBox"];
            NSMenuItem *item = nil;
            for (NSMenuItem *candidate in [[controller valueForKey:@"jcMenu"] itemArray])
                if ([candidate view] != nil && (box == [candidate view] || [box isDescendantOf:[candidate view]])) item = candidate;
            if (box == nil || item == nil) return 40;
            [expected setObject:Trim([item title]) forKey:box];
            return Check(mode, [item view], expected);
        }
        return 4;
    }
}
'''


class PreferencesAccessibleNamesRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "AccessibleNames"
    NO_NIB_MODES = ("search-window",)

    def check(self, mode: str, what: str, extra: tuple[str, ...] = ()) -> None:
        self.run_mode(mode, f"{what}: a control has no accessible name, a name other than its visible label, "
                            "or a stepper's value is not the number shown", extra)

    def test_general_pane_controls_are_named_after_their_labels(self) -> None:
        self.check("general", "General pane")

    def test_password_list_fields_keep_their_names_with_the_xib_titles(self) -> None:
        # MainMenu.xib titles the checkboxes in front of the two fields "by data type:" and
        # "by length & complexity:"; a NIB compiled from it must not turn the fields' names
        # into those fragments.
        titles = xib_checkbox_titles()
        self.assertEqual(len(titles), len(XIB_CHECKBOXES), titles)
        self.check("general-xib-titles", "General pane with the xib's checkbox titles", titles)

    def test_appearance_pane_controls_are_named_after_their_labels(self) -> None:
        self.check("appearance", "Appearance pane")

    def test_hotkeys_pane_controls_have_names(self) -> None:
        self.check("hotkeys", "Hotkeys pane")

    def test_search_window_controls_have_names(self) -> None:
        self.check("search-window", "search window")

    def test_status_menu_search_field_has_a_name(self) -> None:
        self.check("status-menu-search", "status menu search field")


if __name__ == "__main__":
    unittest.main()
