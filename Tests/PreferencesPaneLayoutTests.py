#!/usr/bin/env python3
"""Every Preferences pane follows one set of layout rules, General's.

General (MainMenu.xib) has the rules; Appearance and Hotkeys did not follow them: Appearance put
its sliders at x 109 and its hotkey recorder at x 200 whatever its labels said, inset its rows by
8 pt and spaced them 9 to 20 pt apart; Hotkeys had one recorder 150 pt wide at the NIB's place,
its arrow right behind it and the help text beside it, 178 pt of the window empty at the right.
On General itself the Save pop-up hung 8 pt after its short label while the number fields below
it started further right, and the data types field started before the lengths field under it.

The rules, checked in every pane by alignment rects (an arrow by its frame) in the pane's own
view, after the real -showPreferencePanel: (width fit, toolbar style):
- a 16 pt margin on both sides: labels and checkboxes start at x 16, the Restore Default arrows
  end 16 pt before the window's right edge, the Acknowledgements text spans the margins;
- in a group of labelled rows the controls start on one column, 8 pt after the group's widest
  label: Appearance's three sliders and its hotkey recorder; the Hotkeys recorders; on General
  the Save pop-up with the number fields, the two password list fields;
- what can take any width (sliders, recorders) ends 4 pt before its arrow; the labels at a
  slider's ends stand 2 pt under it, at its two ends;
- labels and arrows are centred on their controls;
- vertically: 16 pt from the pane's top to its first row and between sections (Appearance's
  sliders and hotkey, its checkboxes), 6 pt between rows (the colour options and their hint
  under the colour checkbox, the Hotkeys help text under the recorders), 16 pt below the last.

Every label that names the control after it ends with a colon ("Bezel width:", "Main Hotkey:"),
as "Save forgotten items to:" did; the control's VoiceOver name (its label, else its title, else
the label it is linked to) has none, so VoiceOver does not read a colon with the name. Not labels
in front of a control: checkbox titles, section headings, the words at a slider's ends, hints.

The fixture loads master's compiled MainMenu.nib (FLYCUT_TEST_RESOURCE_BUNDLE), so General's
check runs on master's constraints, which hold the two controls the same way as MainMenu.xib,
once with the NIB's titles and once with the XIB's (checkboxes, and the labels in front of
General's bound controls, as a build from MainMenu.xib titles them). MainMenu.xib's own labels
are checked in the file itself.
The drawn result is for the sight test.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import ROOT, PreferencesNibCase  # noqa: E402

# The password checkboxes in front of the list fields, titled as in MainMenu.xib (master's
# compiled NIB has longer titles, which put the column further right).
XIB_CHECKBOXES = ("values.skipPboardTypes", "values.skipPasswordLengths")
GENERAL_TAB, HOTKEYS_TAB = "net.sf.jumpcut.preferences.general.tiff", "net.sf.jumpcut.preferences.hotkey.tiff"


def xib_checkbox_titles() -> tuple[str, ...]:
    pairs = []
    for button in ET.parse(ROOT / "English.lproj" / "MainMenu.xib").getroot().iter("button"):
        cell, binding = button.find("buttonCell"), button.find("connections/binding[@name='value']")
        if cell is not None and binding is not None and binding.get("keyPath") in XIB_CHECKBOXES:
            pairs.append(f"{binding.get('keyPath')}={cell.get('title')}")
    return tuple(pairs) + tuple(f"label:{key}={title}" for key, title in xib_bound_control_labels())


def _xib_title(view: ET.Element) -> str | None:
    cell = view.find("textFieldCell")
    if cell is None:
        return None
    if cell.get("title") is not None:
        return cell.get("title")
    node = cell.find("string[@key='title']")
    return node.text if node is not None else None


def _xib_is_label(view: ET.Element) -> bool:
    cell = view.find("textFieldCell")
    return (view.tag == "textField" and cell is not None and cell.get("editable") != "YES"
            and view.find("connections/binding[@name='value']") is None)


def _xib_frame(view: ET.Element) -> tuple[float, float, float, float] | None:
    rect = view.find("rect[@key='frame']")
    return None if rect is None else tuple(float(rect.get(k)) for k in ("x", "y", "width", "height"))


def xib_labels_in_front_of_controls(tab: str) -> list[tuple[str, ET.Element]]:
    """(title, control) for every label of a tab in MainMenu.xib whose nearest sibling to its right,
    on the label's middle line, is a control (not another label)."""
    item = next(e for e in ET.parse(ROOT / "English.lproj" / "MainMenu.xib").getroot().iter("tabViewItem")
                if e.get("identifier") == tab)
    found = []
    for subviews in item.iter("subviews"):
        views = [v for v in subviews if _xib_frame(v) is not None]
        for label in views:
            if not _xib_is_label(label):
                continue
            lx, ly, lw, lh = _xib_frame(label)
            mid, right = ly + lh / 2, None
            for other in views:
                ox, oy, ow, oh = _xib_frame(other)
                if other is label or ox < lx + lw - 0.5 or not oy <= mid <= oy + oh:
                    continue
                if right is None or ox < _xib_frame(right)[0]:
                    right = other
            if right is not None and not _xib_is_label(right):
                found.append((_xib_title(label) or "", right))
    return found


def xib_bound_control_labels() -> list[tuple[str, str]]:
    """(key path, title) of General's labels in front of a bound control, as MainMenu.xib has them."""
    pairs = []
    for title, control in xib_labels_in_front_of_controls(GENERAL_TAB):
        for name in ("value", "selectedIndex"):
            binding = control.find(f"connections/binding[@name='{name}']")
            if binding is not None:
                pairs.append((binding.get("keyPath"), title))
    return pairs

FIXTURE = r'''
static BOOL gVisible = NO;
static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; }
static id FakeAcknowledgements(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc; if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? gVisible : NO; }
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender) { (void)cmd; (void)sender; if (self == window) gVisible = YES; }
static void FakeClose(NSWindow *self, SEL cmd)
{
    (void)cmd;
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowWillCloseNotification object:self];
    gVisible = NO;
}

static NSMutableDictionary *report;
static NSDictionary *xibTitles;
static NSTextField *LabelInFront(NSView *control, NSArray *views, NSView *root);
static void SetXibTitles(void)
{
    NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
    for (NSView *view in [pane subviews]) {
        NSString *title = xibTitles[BoundKeyPath(view) ?: @""];
        if (title != nil && [view isKindOfClass:[NSButton class]]) [(NSButton *)view setTitle:title];
        NSString *labelTitle = xibTitles[[@"label:" stringByAppendingString:BoundKeyPath(view) ?: @""]];
        if (labelTitle != nil) [LabelInFront(view, [pane subviews], pane) setStringValue:labelTitle];
    }
}
static int Fail(int code, NSString *what)
{
    report[@"failure"] = what;
    fprintf(stderr, "%s\n", [what UTF8String]);
    Emit(report);
    return code;
}

static NSView *Root(NSInteger index) { return [[[prefs tabView] tabViewItemAtIndex:index] view]; }
static BOOL IsArrow(NSView *v) { return [v isKindOfClass:[NSButton class]] && [[v identifier] hasPrefix:@"restoreDefault"]; }
// Alignment rect (an arrow: its frame) in root's coordinates.
static NSRect R(NSView *v, NSView *root)
{
    return [root convertRect:IsArrow(v) ? [v frame] : [v alignmentRectForFrame:[v frame]] fromView:[v superview]];
}
static void All(NSView *v, NSMutableArray *out) { for (NSView *s in [v subviews]) { [out addObject:s]; All(s, out); } }
static NSArray *Views(NSView *root) { NSMutableArray *a = [NSMutableArray array]; All(root, a); return a; }
static NSTextField *Label(NSArray *views, NSString *text)
{
    for (NSView *v in views)
        if ([v isKindOfClass:[NSTextField class]] && ![(NSTextField *)v isEditable] &&
            [[[(NSTextField *)v stringValue] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] isEqualToString:text])
            return (NSTextField *)v;
    return nil;
}
static NSView *WithId(NSArray *views, NSString *ident) { for (NSView *v in views) if ([[v identifier] isEqualToString:ident]) return v; return nil; }
static NSButton *Checkbox(NSArray *views, NSString *title)
{
    for (NSView *v in views) if ([v isKindOfClass:[NSButton class]] && [[(NSButton *)v title] isEqualToString:title]) return (NSButton *)v;
    return nil;
}
static double TextWidth(NSTextField *label) { return ceil([[label attributedStringValue] size].width); }
static BOOL Near(double a, double b) { return fabs(a - b) <= 0.5; }
static NSString *Num(double v) { return [NSString stringWithFormat:@"%.1f", v]; }

// A label: a plain text field (not editable, no bezel) that shows.
static BOOL IsLabelView(NSView *v)
{
    return [v isKindOfClass:[NSTextField class]] && ![(NSTextField *)v isEditable] && ![(NSTextField *)v isBezeled] && ![v isHiddenOrHasHiddenAncestor];
}
// The nearest text label on a control's left, on the control's line.
static NSTextField *LabelInFront(NSView *control, NSArray *views, NSView *root)
{
    NSRect c = R(control, root);
    NSTextField *best = nil;
    for (NSView *v in views) {
        if (v == control || !IsLabelView(v)) continue;
        NSRect r = R(v, root);
        if (NSMaxX(r) > NSMinX(c) + 0.5 || NSMaxY(r) <= NSMinY(c) || NSMinY(r) >= NSMaxY(c)) continue;
        if (best == nil || NSMaxX(r) > NSMaxX(R(best, root))) best = (NSTextField *)v;
    }
    return best;
}
// What a label can name: a control that shows (not an arrow, not a label), outside any other control.
static BOOL IsNamedControl(NSView *v)
{
    if ([v isHiddenOrHasHiddenAncestor] || IsArrow(v) || IsLabelView(v)) return NO;
    for (NSView *up = [v superview]; up != nil; up = [up superview])
        if ([up isKindOfClass:[NSControl class]] || [up isKindOfClass:NSClassFromString(@"SRRecorderControl")]) return NO;
    return [v isKindOfClass:[NSControl class]] || [v isKindOfClass:NSClassFromString(@"SRRecorderControl")];
}
// The nearest view on a label's right whose line takes in the label's middle: a control, a label or nothing.
static NSView *RightOf(NSTextField *label, NSArray *views, NSView *root)
{
    NSRect l = R(label, root);
    NSView *best = nil;
    for (NSView *v in views) {
        if (v == label || !(IsLabelView(v) || IsNamedControl(v))) continue;
        NSRect r = R(v, root);
        if (NSMinX(r) < NSMaxX(l) - 0.5 || NSMidY(l) < NSMinY(r) || NSMidY(l) > NSMaxY(r)) continue;
        if (best == nil || NSMinX(r) < NSMinX(R(best, root))) best = v;
    }
    return best;
}
// What VoiceOver says for a control's name: the element it reads (the view, else its cell), its
// label (AXDescription), else its title (AXTitle), else the text of the label linked as its title.
static NSString *SpokenName(NSView *control)
{
    id element = control, cell = [control respondsToSelector:@selector(cell)] ? [(NSControl *)control cell] : nil;
    if (![control isAccessibilityElement] && [cell isAccessibilityElement]) element = cell;
    NSString *name = [element accessibilityLabel];
    if ([name length] == 0) name = [element accessibilityTitle];
    if ([name length] == 0) name = [[element accessibilityTitleUIElement] accessibilityValue];
    return name ?: @"";
}
// A label in front of a control ends with one colon, right after its last word, and VoiceOver
// reads it as that text; the control's spoken name has no colon at all.
static int CheckNamingLabel(NSTextField *label, NSView *control, NSMutableArray *seen)
{
    NSString *text = [label stringValue], *name = SpokenName(control);
    [seen addObject:[NSString stringWithFormat:@"%@ -> %@ \"%@\"", text, [control className], name]];
    BOOL one = [text hasSuffix:@":"] && ![text hasSuffix:@"::"] && ![text hasSuffix:@" :"] &&
               [text rangeOfCharacterFromSet:[NSCharacterSet newlineCharacterSet]].location == NSNotFound;
    if (!one) return Fail(100, [NSString stringWithFormat:@"label \"%@\" in front of a %@ does not end with one colon", text, [control className]]);
    id element = NSAccessibilityUnignoredDescendant(label);
    if (![[element accessibilityRole] isEqualToString:NSAccessibilityStaticTextRole] || ![[element accessibilityValue] isEqual:text])
        return Fail(101, [NSString stringWithFormat:@"\"%@\" is not static text for VoiceOver (%@ %@)", text, [element accessibilityRole], [element accessibilityValue]]);
    if ([name length] == 0 || [name rangeOfString:@":"].location != NSNotFound)
        return Fail(102, [NSString stringWithFormat:@"the %@ after \"%@\" is spoken as \"%@\"", [control className], text, name]);
    return 0;
}
// Every Restore Default arrow of a pane, shown or not, is spoken without a colon.
static int CheckArrowNames(NSArray *views)
{
    int arrows = 0;
    for (NSView *v in views) {
        if (!IsArrow(v)) continue;
        arrows++;
        NSString *name = [v accessibilityLabel];
        if ([name length] == 0 || [name rangeOfString:@":"].location != NSNotFound)
            return Fail(103, [NSString stringWithFormat:@"Restore Default arrow %@ is spoken as \"%@\"", [v identifier], name]);
    }
    return arrows > 0 ? 0 : Fail(104, @"no Restore Default arrow found");
}

static void Show(void)
{
    method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
    method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeAcknowledgements);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(close)), (IMP)FakeClose);
    ChangePane(generalPane);     // stands in for the -resizeToFit: of -[UKPrefsPanel awakeFromNib]
    [controller showPreferencePanel:nil];
    [[window contentView] layoutSubtreeIfNeeded];
}

// One labelled row: label at the margin, control on the column, ending 4 pt before its arrow,
// the arrow at the right margin, label and arrow centred on the control.
static int CheckRow(NSTextField *label, NSView *control, NSView *arrow, double column, double W, NSView *root, NSString *name)
{
    NSRect l = R(label, root), c = R(control, root), a = R(arrow, root);
    report[name] = @{@"label": NSStringFromRect(l), @"control": NSStringFromRect(c), @"arrow": NSStringFromRect(a)};
    if (!Near(NSMinX(l), 16)) return Fail(40, [NSString stringWithFormat:@"%@: label starts at x %@, not at the 16 pt margin", name, Num(NSMinX(l))]);
    if (!Near(NSMinX(c), column)) return Fail(41, [NSString stringWithFormat:@"%@: control starts at x %@, the group's column is %@", name, Num(NSMinX(c)), Num(column)]);
    if (!Near(NSMaxX(a), W - 16)) return Fail(42, [NSString stringWithFormat:@"%@: arrow ends at x %@, the right margin at %@", name, Num(NSMaxX(a)), Num(W - 16)]);
    if (!Near(NSMaxX(c), NSMinX(a) - 4)) return Fail(43, [NSString stringWithFormat:@"%@: control ends at x %@, its arrow starts at %@", name, Num(NSMaxX(c)), Num(NSMinX(a))]);
    if (!Near(NSMidY(l), NSMidY(c)) || !Near(NSMidY(a), NSMidY(c)))
        return Fail(44, [NSString stringWithFormat:@"%@: label centre %@, arrow centre %@, control centre %@", name, Num(NSMidY(l)), Num(NSMidY(a)), Num(NSMidY(c))]);
    return 0;
}

// The visible gap between two views, the first one above the second.
static int CheckGap(NSView *above, NSView *below, double wanted, NSView *root, NSString *name)
{
    double gap = NSMinY(R(above, root)) - NSMaxY(R(below, root));
    report[[@"gap " stringByAppendingString:name]] = @(gap);
    if (!Near(gap, wanted)) return Fail(50, [NSString stringWithFormat:@"gap %@ is %@ pt, wanted %@", name, Num(gap), Num(wanted)]);
    return 0;
}

static int CheckTopAndBottom(NSView *box, NSView *first, NSView *last, NSView *root, NSString *pane)
{
    NSRect b = [root convertRect:[box bounds] fromView:box];
    double top = NSMaxY(b) - NSMaxY(R(first, root)), bottom = NSMinY(R(last, root)) - NSMinY(b);
    report[[pane stringByAppendingString:@" top"]] = @(top);
    report[[pane stringByAppendingString:@" bottom"]] = @(bottom);
    if (!Near(top, 16) || !Near(bottom, 16))
        return Fail(51, [NSString stringWithFormat:@"%@: %@ pt above the first row, %@ pt below the last; wanted 16 and 16", pane, Num(top), Num(bottom)]);
    return 0;
}

static int Appearance(void)
{
    ChangePane(appearancePane);
    NSView *root = Root(appearancePane);
    NSArray *views = Views(root);
    double W = NSWidth([[window contentView] bounds]);
    report[@"width"] = @(W);
    NSArray *titles = @[@"Bezel transparency:", @"Bezel width:", @"Bezel height:", @"Search clipboard hotkey:"];
    NSArray *arrows = @[@"restoreDefaultBezelAlpha", @"restoreDefaultBezelWidth", @"restoreDefaultBezelHeight", @"restoreDefaultSearchHotkey"];
    NSMutableArray *labels = [NSMutableArray array], *controls = [NSMutableArray array];
    double widest = 0;
    for (NSString *title in titles) {
        NSTextField *label = Label(views, title);
        if (label == nil) return Fail(30, [@"missing label " stringByAppendingString:title]);
        [labels addObject:label];
        widest = MAX(widest, TextWidth(label));
    }
    NSMutableArray *sliders = [NSMutableArray array];
    NSView *recorder = nil;
    for (NSView *v in views) {
        if ([v isKindOfClass:[NSSlider class]]) [sliders addObject:v];
        if ([v isKindOfClass:NSClassFromString(@"SRRecorderControl")]) recorder = v;
    }
    [sliders sortUsingComparator:^NSComparisonResult(NSView *a, NSView *b) { return NSMidY(R(a, root)) > NSMidY(R(b, root)) ? NSOrderedAscending : NSOrderedDescending; }];
    if ([sliders count] != 3 || recorder == nil) return Fail(31, @"three sliders and a recorder expected");
    [controls addObjectsFromArray:sliders];
    [controls addObject:recorder];
    double column = 16 + widest + 8;
    report[@"column"] = @(column);
    for (NSUInteger i = 0; i < 4; i++) {
        NSView *arrow = WithId(views, arrows[i]);
        if (arrow == nil) return Fail(32, [@"missing arrow " stringByAppendingString:arrows[i]]);
        int failed = CheckRow(labels[i], controls[i], arrow, column, W, root, titles[i]);
        if (failed) return failed;
    }
    // The labels at a slider's ends: 2 pt under it, at its two ends.
    NSMutableArray *endRows = [NSMutableArray array];
    for (NSView *slider in sliders) {
        NSRect s = R(slider, root);
        NSTextField *minLabel = nil, *maxLabel = nil;
        for (NSView *v in views) {
            if (![v isKindOfClass:[NSTextField class]] || [labels containsObject:v]) continue;
            NSRect r = R(v, root);
            if (NSMaxY(r) > NSMinY(s) + 0.5 || NSMaxY(r) < NSMinY(s) - 10) continue;
            if ([(NSTextField *)v alignment] == NSTextAlignmentLeft) minLabel = (NSTextField *)v;
            if ([(NSTextField *)v alignment] == NSTextAlignmentRight) maxLabel = (NSTextField *)v;
        }
        if (minLabel == nil || maxLabel == nil) return Fail(33, [NSString stringWithFormat:@"the labels at the ends of the slider at %@ are not under it", NSStringFromRect(s)]);
        NSRect mn = R(minLabel, root), mx = R(maxLabel, root);
        if (!Near(NSMinX(mn), NSMinX(s)) || !Near(NSMaxX(mx), NSMaxX(s)) || !Near(NSMinY(s) - NSMaxY(mn), 2) || !Near(NSMinY(s) - NSMaxY(mx), 2))
            return Fail(34, [NSString stringWithFormat:@"slider %@: end labels %@ and %@ not at its ends 2 pt under it", NSStringFromRect(s), NSStringFromRect(mn), NSStringFromRect(mx)]);
        [endRows addObject:minLabel];
    }
    NSArray *boxes = @[@"Show clipping source app and time", @"Capture images from clipboard", @"Download animated GIFs from web", @"Use custom menu bar icon colors"];
    NSMutableArray *checkboxes = [NSMutableArray array];
    for (NSString *title in boxes) {
        NSButton *b = Checkbox(views, title);
        if (b == nil) return Fail(35, [@"missing checkbox " stringByAppendingString:title]);
        if (!Near(NSMinX(R(b, root)), 16)) return Fail(36, [NSString stringWithFormat:@"checkbox %@ starts at x %@", title, Num(NSMinX(R(b, root)))]);
        [checkboxes addObject:b];
    }
    NSView *well = WithId(views, @"menuIconActiveColorWell");
    NSTextField *hint = Label(views, @"Off uses the automatic macOS color.");
    if (well == nil || hint == nil) return Fail(37, @"colour options or hint missing");
    int failed = 0;
    if ((failed = CheckGap(sliders[0], endRows[0], 2, root, @"slider 1 to its end labels"))) return failed;
    if ((failed = CheckGap(endRows[0], sliders[1], 6, root, @"end labels 1 to slider 2"))) return failed;
    if ((failed = CheckGap(endRows[1], sliders[2], 6, root, @"end labels 2 to slider 3"))) return failed;
    if ((failed = CheckGap(endRows[2], recorder, 6, root, @"end labels 3 to the recorder"))) return failed;
    if ((failed = CheckGap(recorder, checkboxes[0], 16, root, @"recorder to the first checkbox"))) return failed;
    for (NSUInteger i = 0; i + 1 < [checkboxes count]; i++)
        if ((failed = CheckGap(checkboxes[i], checkboxes[i + 1], 6, root, [NSString stringWithFormat:@"checkbox %lu to %lu", (unsigned long)i + 1, (unsigned long)i + 2]))) return failed;
    if ((failed = CheckGap(checkboxes[3], well, 6, root, @"colour checkbox to its options"))) return failed;
    if ((failed = CheckGap(well, hint, 6, root, @"colour options to the hint"))) return failed;
    return CheckTopAndBottom([controller valueForKey:@"appearancePanel"], sliders[0], hint, root, @"appearance");
}

static int Hotkeys(void)
{
    ChangePane(hotkeysPane);
    NSView *root = Root(hotkeysPane);
    NSArray *views = Views(root);
    double W = NSWidth([[window contentView] bounds]);
    report[@"width"] = @(W);
    NSView *recorder = [controller valueForKey:@"mainRecorder"];
    NSTextField *label = Label(views, @"Main Hotkey:");
    NSView *arrow = WithId(views, @"restoreDefaultMainHotkey");
    NSTextField *help = nil;
    for (NSView *v in views) if ([v isKindOfClass:[NSTextField class]] && [[(NSTextField *)v stringValue] hasPrefix:@"To change"]) help = (NSTextField *)v;
    if (label == nil || arrow == nil || help == nil) return Fail(60, @"Hotkeys label, arrow or help missing");
    if ([[label stringValue] rangeOfCharacterFromSet:[NSCharacterSet newlineCharacterSet]].location != NSNotFound)
        return Fail(61, @"the Main Hotkey label still ends with a line break");
    double column = 16;
    for (NSView *v in views)
        if ([v isKindOfClass:[NSTextField class]] && ![(NSTextField *)v isEditable] && v != help)
            column = MAX(column, 16 + TextWidth((NSTextField *)v) + 8);
    int failed = CheckRow(label, recorder, arrow, column, W, root, @"Main Hotkey:");
    if (failed) return failed;
    NSRect h = R(help, root);
    report[@"help"] = NSStringFromRect(h);
    if (!Near(NSMinX(h), column) || NSMaxX(h) > W - 16 + 0.5)
        return Fail(62, [NSString stringWithFormat:@"help %@ does not start at the column %@ and end by the margin %@", NSStringFromRect(h), Num(column), Num(W - 16)]);
    NSSize needed = [[help cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([help frame]), CGFLOAT_MAX)];
    if (ceil(needed.height) > NSHeight([help frame]) + 0.5) return Fail(63, [NSString stringWithFormat:@"help needs %@ pt, has %@", Num(needed.height), Num(NSHeight([help frame]))]);
    NSView *lowest = recorder;
    for (NSView *v in views) if ([v isKindOfClass:NSClassFromString(@"SRRecorderControl")] && NSMinY(R(v, root)) < NSMinY(R(lowest, root))) lowest = v;
    if ((failed = CheckGap(lowest, help, 6, root, @"last recorder to the help text"))) return failed;
    NSBox *box = (NSBox *)[[recorder superview] superview];
    if ((failed = CheckTopAndBottom(box, recorder, help, root, @"hotkeys"))) return failed;
    double content = NSHeight([[window contentView] frame]);
    report[@"window content height"] = @(content);
    if (!Near(content, NSHeight([box frame]))) return Fail(64, [NSString stringWithFormat:@"window content %@ pt, Hotkeys box %@", Num(content), Num(NSHeight([box frame]))]);
    return 0;
}

static int Acknowledgements(void)
{
    NSTabView *tabs = [prefs tabView];
    NSInteger index = [tabs indexOfTabViewItemWithIdentifier:@"com.generalarcade.flycut.32.png"];
    if (index == NSNotFound) return Fail(70, @"no Acknowledgements pane");
    ChangePane(index);
    NSView *root = Root(index);
    double W = NSWidth([[window contentView] bounds]);
    NSScrollView *scroll = nil;
    for (NSView *v in Views(root)) if ([v isKindOfClass:[NSScrollView class]]) scroll = (NSScrollView *)v;
    NSRect r = R(scroll, root);
    report[@"acknowledgements"] = NSStringFromRect(r);
    if (scroll == nil || !Near(NSMinX(r), 16) || !Near(NSMaxX(r), W - 16))
        return Fail(71, [NSString stringWithFormat:@"Acknowledgements text at %@, margins wanted at 16 and %@", NSStringFromRect(r), Num(W - 16)]);
    return 0;
}

static NSView *Bound(NSArray *views, NSString *key)
{
    NSString *kp = [@"values." stringByAppendingString:key];
    for (NSView *v in views)
        for (NSString *b in @[NSValueBinding, NSSelectedIndexBinding])
            if ([[[v infoForBinding:b] objectForKey:NSObservedKeyPathKey] isEqualToString:kp]) return v;
    return nil;
}

static int General(void)
{
    ChangePane(generalPane);
    NSView *root = Root(generalPane);
    NSArray *views = Views(root);
    NSView *popup = Bound(views, @"savePreference"), *remember = Bound(views, @"rememberNum");
    NSView *types = Bound(views, @"skipPboardTypesList"), *lengths = Bound(views, @"skipPasswordLengthsList");
    if (!popup || !remember || !types || !lengths) return Fail(80, @"General controls missing");
    report[@"popup"] = NSStringFromRect(R(popup, root)); report[@"remember"] = NSStringFromRect(R(remember, root));
    report[@"types"] = NSStringFromRect(R(types, root)); report[@"lengths"] = NSStringFromRect(R(lengths, root));
    // The labels in front of them (the nearest views on their left, on their lines).
    NSView *labels[4] = {nil, nil, nil, nil};
    NSView *controls[4] = {popup, remember, types, lengths};
    for (int i = 0; i < 4; i++) {
        NSRect c = R(controls[i], root);
        for (NSView *v in views) {
            if (v == controls[i] || ![v isKindOfClass:[NSControl class]] || IsArrow(v)) continue;
            NSRect r = R(v, root);
            if (NSMaxX(r) > NSMinX(c) + 0.5 || NSMaxY(r) <= NSMinY(c) || NSMinY(r) >= NSMaxY(c)) continue;
            if (labels[i] == nil || NSMaxX(r) > NSMaxX(R(labels[i], root))) labels[i] = v;
        }
        if (labels[i] == nil) return Fail(83, [NSString stringWithFormat:@"no label in front of %@", NSStringFromRect(c)]);
        // a label shows its whole text: not squeezed by the column
        NSSize natural = [labels[i] fittingSize];
        if (NSWidth([labels[i] frame]) + 0.5 < natural.width)
            return Fail(84, [NSString stringWithFormat:@"label %@ is %@ pt wide, its text needs %@", NSStringFromRect(R(labels[i], root)), Num(NSWidth([labels[i] frame])), Num(natural.width)]);
    }
    for (int g = 0; g < 4; g += 2) {
        double column = MAX(NSMaxX(R(labels[g], root)), NSMaxX(R(labels[g + 1], root))) + 8;
        report[[NSString stringWithFormat:@"column %d", g / 2]] = @(column);
        for (int i = g; i < g + 2; i++)
            if (!Near(NSMinX(R(controls[i], root)), column))
                return Fail(81 + g / 2, [NSString stringWithFormat:@"control %@ does not start on its group's column %@ (8 pt after the widest label)", NSStringFromRect(R(controls[i], root)), Num(column)]);
    }
    // the list fields keep reaching the arrow column (with MainMenu.xib's titles they stay wide)
    if (!Near(NSMaxX(R(types, root)), NSMaxX(R(lengths, root))) || (xibTitles != nil && NSWidth(R(types, root)) < 100))
        return Fail(85, [NSString stringWithFormat:@"list fields %@ and %@ do not both reach the arrow column", NSStringFromRect(R(types, root)), NSStringFromRect(R(lengths, root))]);
    return 0;
}

// One type scale: every label of Appearance and Hotkeys is a label (system
// font, 13 pt, labelColor, like a checkbox title) or explains a control (11 pt,
// secondaryLabelColor): the hints and the words at a slider's ends. All of them
// stay static text for VoiceOver.
static int TypeScale(void)
{
    NSSet *hints = [NSSet setWithArray:@[@"Lighter", @"Darker", @"Smaller", @"Bigger", @"Off uses the automatic macOS color."]];
    NSMutableArray *seen = [NSMutableArray array];
    for (NSNumber *index in @[@(appearancePane), @(hotkeysPane)]) {
        ChangePane([index integerValue]);
        for (NSView *v in Views(Root([index integerValue]))) {
            if (![v isKindOfClass:[NSTextField class]] || [(NSTextField *)v isEditable] || [(NSTextField *)v isBezeled]) continue;
            NSTextField *t = (NSTextField *)v;
            NSString *text = [t stringValue];
            BOOL hint = [hints containsObject:text] || [text hasPrefix:@"To change"];
            CGFloat size = hint ? [NSFont smallSystemFontSize] : [NSFont systemFontSize];
            NSColor *colour = hint ? [NSColor secondaryLabelColor] : [NSColor labelColor];
            NSFont *font = [t font];
            BOOL system = [[font familyName] isEqualToString:[[NSFont systemFontOfSize:size] familyName]] &&
                          !([[font fontDescriptor] symbolicTraits] & NSFontDescriptorTraitBold);
            [seen addObject:[NSString stringWithFormat:@"%@ %.0f %@", text, [font pointSize], [[t textColor] colorNameComponent]]];
            if (!system || fabs([font pointSize] - size) > 0.01 || ![[t textColor] isEqual:colour])
                return Fail(90, [NSString stringWithFormat:@"%@ \"%@\": %@ %.1f pt %@, wanted the system font %.0f pt %@", hint ? @"hint" : @"label", text,
                                 [font fontName], [font pointSize], [t textColor], size, colour]);
            // the field's cell is the element VoiceOver reads (the field itself is ignored)
            id element = NSAccessibilityUnignoredDescendant(t);
            if (![[element accessibilityRole] isEqualToString:NSAccessibilityStaticTextRole] || ![[element accessibilityValue] isEqual:text])
                return Fail(91, [NSString stringWithFormat:@"\"%@\" is not static text for VoiceOver (%@ %@)", text, [element accessibilityRole], [element accessibilityValue]]);
        }
    }
    report[@"labels"] = seen;
    if ([seen count] < 12) return Fail(92, [NSString stringWithFormat:@"only %lu labels found: %@", (unsigned long)[seen count], seen]);
    return 0;
}

// Appearance and Hotkeys (built and laid out in code; the Hotkeys label comes from the NIB): every
// label whose nearest neighbour on its right is a control names it.
static int Colons(void)
{
    NSArray *panes = @[@(appearancePane), @(hotkeysPane)];
    NSArray *wanted = @[@[@"Bezel transparency:", @"Bezel width:", @"Bezel height:", @"Search clipboard hotkey:", @"Active:", @"Paused:"],
                        @[@"Main Hotkey:"]];
    NSMutableArray *seen = [NSMutableArray array];
    for (NSUInteger p = 0; p < [panes count]; p++) {
        NSInteger index = [panes[p] integerValue];
        ChangePane(index);
        NSView *root = Root(index);
        NSArray *views = Views(root);
        NSMutableSet *named = [NSMutableSet set];
        for (NSView *v in views) {
            if (!IsLabelView(v) || [[(NSTextField *)v stringValue] length] == 0) continue;
            NSView *right = RightOf((NSTextField *)v, views, root);
            if (right == nil || !IsNamedControl(right)) continue;
            int failed = CheckNamingLabel((NSTextField *)v, right, seen);
            if (failed) return failed;
            [named addObject:[(NSTextField *)v stringValue]];
        }
        for (NSString *text in wanted[p])
            if (![named containsObject:text]) return Fail(105, [NSString stringWithFormat:@"no label \"%@\" in front of a control (found %@)", text, seen]);
        int failed = CheckArrowNames(views);
        if (failed) return failed;
    }
    report[@"labels"] = seen;
    return 0;
}

// General with MainMenu.xib's titles: the labels in front of its bound controls (titled by the
// XIB in this mode) and in front of the two folder buttons, every arrow, and no label squeezed.
static int GeneralColons(void)
{
    ChangePane(generalPane);
    NSView *root = Root(generalPane);
    NSArray *views = Views(root);
    NSMutableArray *seen = [NSMutableArray array], *controls = [NSMutableArray array];
    for (NSString *key in xibTitles)
        if ([key hasPrefix:@"label:values."]) {
            NSView *control = Bound(views, [key substringFromIndex:[@"label:values." length]]);
            if (control == nil) return Fail(106, [@"no control bound to " stringByAppendingString:key]);
            [controls addObject:control];
        }
    for (NSString *ivar in @[@"saveToLocationButton", @"autoSaveToLocationButton"]) [controls addObject:[controller valueForKey:ivar]];
    if ([controls count] < 6) return Fail(107, [NSString stringWithFormat:@"only %lu labelled controls", (unsigned long)[controls count]]);
    for (NSView *control in controls) {
        NSTextField *label = LabelInFront(control, views, root);
        if (label == nil) return Fail(108, [NSString stringWithFormat:@"no label in front of %@", NSStringFromRect(R(control, root))]);
        int failed = CheckNamingLabel(label, control, seen);
        if (failed) return failed;
        NSSize natural = [label fittingSize];
        CGFloat oneLine = [[label cell] cellSizeForBounds:NSMakeRect(0, 0, CGFLOAT_MAX, CGFLOAT_MAX)].height;
        CGFloat atWidth = [[label cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([label frame]), CGFLOAT_MAX)].height;
        if (NSWidth([label frame]) + 0.5 < natural.width || atWidth > oneLine + 0.5)
            return Fail(109, [NSString stringWithFormat:@"label \"%@\" is %@ pt wide, its text needs %@", [label stringValue], Num(NSWidth([label frame])), Num(natural.width)]);
    }
    report[@"labels"] = seen;
    report[@"width"] = @(NSWidth([[window contentView] bounds]));
    return CheckArrowNames(views);
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        if ([mode isEqualToString:@"general-xib"] || [mode isEqualToString:@"colons-xib"]) {
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
        report = [NSMutableDictionary dictionaryWithObject:mode forKey:@"mode"];
        if ([mode isEqualToString:@"hotkeys-shown"]) {
            // Hotkeys is the pane shown when Preferences opens again.
            Show();
            ChangePane(hotkeysPane);
            [window close];
            [controller showPreferencePanel:nil];
            [[window contentView] layoutSubtreeIfNeeded];
            double content = NSHeight([[window contentView] frame]);
            NSBox *box = (NSBox *)[[[controller valueForKey:@"mainRecorder"] superview] superview];
            report[@"content"] = @(content); report[@"box"] = @(NSHeight([box frame]));
            if (!Near(content, NSHeight([box frame]))) return Fail(65, [NSString stringWithFormat:@"window content %@ pt, Hotkeys box %@", Num(content), Num(NSHeight([box frame]))]);
            Emit(report);
            return 0;
        }
        Show();
        int result = [mode isEqualToString:@"appearance"] ? Appearance() : [mode isEqualToString:@"hotkeys"] ? Hotkeys()
                   : [mode isEqualToString:@"acknowledgements"] ? Acknowledgements() : [mode hasPrefix:@"general"] ? General() : [mode isEqualToString:@"type-scale"] ? TypeScale()
                   : [mode isEqualToString:@"colons"] ? Colons() : [mode isEqualToString:@"colons-xib"] ? GeneralColons() : 2;
        if (result == 0) Emit(report);
        return result;
    }
}
'''


class PreferencesPaneLayoutTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "PreferencesPaneLayoutFixture"

    def test_appearance_follows_the_margins_column_and_grid(self) -> None:
        self.run_mode("appearance", "Appearance does not follow the layout rules")

    def test_hotkeys_recorders_reach_the_arrow_column_with_the_help_below(self) -> None:
        self.run_mode("hotkeys", "Hotkeys does not follow the layout rules")

    def test_hotkeys_window_follows_its_pane_when_it_opens_on_it(self) -> None:
        self.run_mode("hotkeys-shown", "the window does not fit the Hotkeys pane it opens on")

    def test_labels_and_hints_follow_one_type_scale(self) -> None:
        self.run_mode("type-scale", "a label or hint is not in the Preferences' type scale")

    def test_acknowledgements_text_keeps_the_margins(self) -> None:
        self.run_mode("acknowledgements", "the Acknowledgements text is not on the margins")

    def test_general_controls_of_a_group_share_one_column(self) -> None:
        self.run_mode("general", "General's grouped controls do not share a column")

    def test_general_controls_of_a_group_share_one_column_with_the_xib_titles(self) -> None:
        self.run_mode("general-xib", "General's grouped controls do not share a column (XIB titles)", xib_checkbox_titles())

    def test_labels_in_front_of_a_control_end_with_a_colon_and_names_have_none(self) -> None:
        self.run_mode("colons", "a label in front of a control lacks its colon, or VoiceOver reads one in a name")

    def test_general_labels_end_with_a_colon_with_the_xib_titles(self) -> None:
        self.run_mode("colons-xib", "a General label lacks its colon, or VoiceOver reads one in a name (XIB titles)",
                      xib_checkbox_titles())

    def test_xib_labels_in_front_of_a_control_end_with_a_colon(self) -> None:
        for tab, least in ((GENERAL_TAB, 6), (HOTKEYS_TAB, 1)):
            titles = [title.strip() for title, _ in xib_labels_in_front_of_controls(tab)]
            self.assertGreaterEqual(len(titles), least, (tab, titles))
            bad = [t for t in titles if not t.endswith(":") or t.endswith(("::", " :")) or "\n" in t]
            self.assertEqual(bad, [], f"MainMenu.xib labels in front of a control without one colon at the end ({tab})")
        self.assertEqual(len(xib_bound_control_labels()), 4, xib_bound_control_labels())

    def test_help_quotes_the_labels_with_their_colons(self) -> None:
        help_lines = (ROOT / "help.md").read_text(encoding="utf-8").splitlines()
        for line in ('"Display in menu:" in Preferences sets how many rows the list shows before it scrolls: 20 by '
                     'default, at most as many as fit on the screen. The list always holds all your clippings.',):
            self.assertIn(line, help_lines)
        text = "\n".join(help_lines)
        self.assertIn('You can change or clear the shortcut under "Search clipboard hotkey:" in Preferences.', text)
        for old in ('"Display in menu"', '"Search clipboard hotkey"', '"Bezel width"', '"Main Hotkey"', '"Remember"'):
            self.assertNotIn(old, text)


if __name__ == "__main__":
    unittest.main()
