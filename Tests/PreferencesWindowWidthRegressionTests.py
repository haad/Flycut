#!/usr/bin/env python3
"""The Preferences window is as wide as what its panes show, in the Preference toolbar style.

-[AppController showPreferencePanel:] used to widen the 507 pt window to 720 pt, whatever the
panes held. The Preference style puts the title on top and the four items centred below it, so
the toolbar needs far less than the panes. The window was then fitted to the panes' FRAMES: the
Hotkeys hint label's frame (16..502 in the NIB) set 518 pt, while its text ends near 450, and the
tab view kept the NIB's 507 pt, so every pane had an empty strip at the right.

Now the window is as wide as the widest FIXED content of all panes plus that pane's left inset:
a label by its own text, a checkbox by its box and title, other controls by their alignment
rects, every Restore Default arrow by its frame (shown or not). Controls that can take any width
follow the window instead of setting it: a wrapping label (the Hotkeys hint), sliders, the
Acknowledgements text, separators, and on Appearance the arrow column with what hangs on it (the
sliders' right ends, the search recorder, the right-aligned "Darker"/"Bigger" labels). They end
at the window's width less the pane's left inset. The tab view takes the window's width, so
every pane spans it, and no control reaches past the window. The window keeps its centre, and
each pane still fits under the taller toolbar. The toolbar holds the four panes and no space;
they are evenly spaced and centred (their item views' frames, measured offscreen).

The fixture loads the production NIB (master's compiled MainMenu.nib for trees that carry
only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py), sends the builders that
-awakeFromNib sends, attaches the toolbar as -[UKPrefsPanel awakeFromNib] does and calls the
real -showPreferencePanel:. The window is never ordered in; the toolbar is laid out offscreen,
and -[NSToolbar visibleItems] says which items are on the bar and which are in the overflow
(measured on this macOS: monotone in the width). The case measures the toolbar's need itself,
one point at a time. Run with the NIB's checkbox titles (master's compiled NIB has the long
ones) and with those of MainMenu.xib. The drawn toolbar is not reproduced pixel for pixel; the
sight test looks at it.
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

static BOOL gVisible = NO;
static int gShows = 0;
static NSInteger gStyleAtShow = -1;
static void FakeActivate(id self, SEL cmd, BOOL flag) { (void)self; (void)cmd; (void)flag; }
static id FakeAcknowledgements(id self, SEL cmd, id path, NSStringEncoding enc, NSError **error)
{
    (void)self; (void)cmd; (void)path; (void)enc; if (error) *error = nil;
    return @"Acknowledgements (fixture)";
}
static BOOL FakeIsVisible(NSWindow *self, SEL cmd) { (void)cmd; return self == window ? gVisible : NO; }
static void FakeMakeKeyAndOrderFront(NSWindow *self, SEL cmd, id sender)
{
    (void)cmd; (void)sender;
    if (self != window) return;
    gShows++;
    gStyleAtShow = [self toolbarStyle];
    gVisible = YES;
}
static void FakeClose(NSWindow *self, SEL cmd)
{
    (void)cmd;
    [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowWillCloseNotification object:self];
    gVisible = NO;
}

// ---- A pane's content: every visible control, and every Restore Default arrow, at leaf level.
static BOOL IsAppearance(NSView *pane)
{
    NSView *panel = [controller valueForKey:@"appearancePanel"];
    return panel != nil && [panel isDescendantOf:pane];
}

// A label whose text runs over more than one line at its width (the Hotkeys hint).
static BOOL Wraps(NSView *view)
{
    return [view isKindOfClass:[NSTextField class]] && ![(NSTextField *)view isEditable] && [[(NSTextField *)view cell] wraps]
        && [[(NSTextField *)view attributedStringValue] size].width > NSWidth([view frame]);
}

// Controls that take the width the window gives them.
static BOOL Elastic(NSView *view, BOOL appearance)
{
    if ([view isKindOfClass:[NSSlider class]] || [view isKindOfClass:[NSScrollView class]] || [view isKindOfClass:[NSBox class]] || Wraps(view))
        return YES;
    if (!appearance) return NO;
    if ([[view identifier] hasPrefix:@"restoreDefault"] || [view isKindOfClass:NSClassFromString(@"SRRecorderControl")]) return YES;
    return [view isKindOfClass:[NSTextField class]] && [(NSTextField *)view alignment] == NSTextAlignmentRight;
}

// Where a fixed control's content ends, in its superview's coordinates.
static double ContentMaxX(NSView *view)
{
    NSRect frame = [view frame];
    if ([[view identifier] hasPrefix:@"restoreDefault"]) return NSMaxX(frame);
    if ([view isKindOfClass:[NSTextField class]] && ![(NSTextField *)view isEditable] && ![(NSTextField *)view isBezeled]) {
        NSRect edges = [view alignmentRectForFrame:frame];
        double text = ceil([[(NSTextField *)view attributedStringValue] size].width);
        NSTextAlignment alignment = [(NSTextField *)view alignment];
        if (alignment == NSTextAlignmentRight) return NSMaxX(edges);
        if (alignment == NSTextAlignmentCenter) return MIN(NSMaxX(edges), NSMidX(edges) + text / 2.0);
        return MIN(NSMaxX(edges), NSMinX(edges) + text);
    }
    if ([view isKindOfClass:[NSButton class]] && ![view isKindOfClass:[NSPopUpButton class]] && [[(NSButton *)view title] length] > 0)
        frame.size.width = MIN(NSWidth(frame), [view fittingSize].width);
    return NSMaxX([view alignmentRectForFrame:frame]);
}

static void LeavesIn(NSView *view, NSView *pane, BOOL appearance, NSMutableArray *out)
{
    for (NSView *sub in [view subviews]) {
        BOOL restore = [sub isKindOfClass:[NSButton class]] && [[sub identifier] hasPrefix:@"restoreDefault"];
        if ([sub isHidden] && !restore) continue;
        BOOL box = [sub isKindOfClass:[NSBox class]];
        BOOL container = box ? [(NSBox *)sub boxType] != NSBoxSeparator
                             : ([sub isMemberOfClass:[NSView class]] && [[sub subviews] count] > 0);
        if (container) {
            LeavesIn(box ? [(NSBox *)sub contentView] : sub, pane, appearance, out);
        } else {
            NSView *parent = [sub superview];
            NSRect r = [pane convertRect:[sub frame] fromView:parent];
            NSRect edges = [pane convertRect:[sub alignmentRectForFrame:[sub frame]] fromView:parent];
            BOOL elastic = Elastic(sub, appearance);
            NSRect content = [sub frame];
            content.size.width = elastic ? 0 : ContentMaxX(sub) - NSMinX(content);
            double contentMaxX = NSMaxX([pane convertRect:content fromView:parent]);
            [out addObject:@{@"view": sub, @"minX": @(NSMinX(r)), @"maxX": @(NSMaxX(r)), @"alignMinX": @(NSMinX(edges)),
                             @"alignMaxX": @(NSMaxX(edges)), @"elastic": @(elastic), @"contentMaxX": @(contentMaxX)}];
        }
    }
}

static void Leaves(NSView *view, NSView *pane, NSMutableArray *out) { LeavesIn(view, pane, IsAppearance(pane), out); }

// The pane's fixed content's right edge plus its left inset, in points. 0 for a pane without
// fixed content (Acknowledgements: only its text, which follows the window).
static double PaneNeed(NSView *pane, double *minOut, double *maxOut)
{
    NSMutableArray *leaves = [NSMutableArray array];
    [pane layoutSubtreeIfNeeded];
    Leaves(pane, pane, leaves);
    double minX = 1e9, maxX = 0;
    for (NSDictionary *leaf in leaves) {
        minX = MIN(minX, [leaf[@"alignMinX"] doubleValue]);
        if (![leaf[@"elastic"] boolValue]) maxX = MAX(maxX, [leaf[@"contentMaxX"] doubleValue]);
    }
    if (minOut) *minOut = [leaves count] ? minX : 0;
    if (maxOut) *maxOut = maxX;
    return maxX > 0 ? ceil(maxX + minX) : 0;
}

static double ContentNeed(NSMutableArray *per)
{
    NSTabView *tabs = [prefs tabView];
    double need = 0;
    for (NSInteger i = 0; i < [tabs numberOfTabViewItems]; i++) {
        double lo = 0, hi = 0;
        double n = PaneNeed([[tabs tabViewItemAtIndex:i] view], &lo, &hi);
        [per addObject:@{@"pane": [[tabs tabViewItemAtIndex:i] label], @"leftInset": @(lo), @"rightEdge": @(hi), @"need": @(n)}];
        need = MAX(need, n);
    }
    return need;
}

// The shown pane's lowest and highest control against the window's content view, which is
// all the window shows below its toolbar.
static NSDictionary *Vertical(NSInteger index)
{
    NSView *content = [window contentView];
    [content layoutSubtreeIfNeeded];
    NSView *pane = [[[prefs tabView] tabViewItemAtIndex:index] view];
    NSMutableArray *leaves = [NSMutableArray array];
    Leaves(pane, pane, leaves);
    double lowest = 1e9, highest = -1e9;
    for (NSDictionary *leaf in leaves) {
        NSView *view = leaf[@"view"];
        NSRect r = [content convertRect:[view bounds] fromView:view];
        lowest = MIN(lowest, NSMinY(r));
        highest = MAX(highest, NSMaxY(r));
    }
    return @{@"pane": [[[prefs tabView] tabViewItemAtIndex:index] label], @"controls": @([leaves count]),
             @"lowest": @(lowest), @"highest": @(highest), @"contentHeight": @(NSHeight([content bounds])),
             @"frameHeight": @(NSHeight([window frame]))};
}

// ---- The toolbar: are all its items on the bar at the window's current width?
static BOOL ToolbarShowsAllItems(void)
{
    [[window contentView] layoutSubtreeIfNeeded];
    [[[window contentView] superview] layoutSubtreeIfNeeded];
    NSToolbar *toolbar = [window toolbar];
    NSArray *visible = [[toolbar visibleItems] valueForKey:@"itemIdentifier"];
    NSUInteger counted = 0;
    for (NSToolbarItem *item in [toolbar items]) {
        if ([[item label] length] == 0) continue;           // a space
        counted++;
        if (![visible containsObject:[item itemIdentifier]]) return NO;
    }
    return counted > 0;
}

static void SetContentWidth(double width)
{
    NSRect frame = [window frame];
    NSRect content = [window contentRectForFrameRect:frame];
    content.size.width = width;
    NSRect target = [window frameRectForContentRect:content];
    target.origin = frame.origin;
    [window setFrame:target display:NO animate:NO];
}

// The frames (window coordinates) of the toolbar's items as the bar lays them out offscreen:
// each item's viewer, the view that holds its icon and label. AppKit has no public API for
// it; -[NSToolbarItem _itemViewer] (private, used here only) answers on this macOS. nil when
// it does not, so the case fails instead of measuring nothing.
static NSArray *ToolbarItemFrames(void)
{
    [[window contentView] layoutSubtreeIfNeeded];
    [[[window contentView] superview] layoutSubtreeIfNeeded];
    SEL viewerSelector = NSSelectorFromString(@"_itemViewer");
    NSMutableArray *frames = [NSMutableArray array];
    for (NSToolbarItem *item in [[window toolbar] items]) {
        if (![item respondsToSelector:viewerSelector]) return nil;
        NSView *viewer = ((id (*)(id, SEL))objc_msgSend)(item, viewerSelector);
        if (![viewer isKindOfClass:[NSView class]] || [viewer window] != window) return nil;
        NSRect r = [viewer convertRect:[viewer bounds] toView:nil];
        [frames addObject:@{@"item": [item itemIdentifier], @"label": [item label] ?: @"", @"minX": @(NSMinX(r)), @"maxX": @(NSMaxX(r))}];
    }
    return frames;
}

// The least content width, one point at a time, at which the toolbar shows all of its items.
static double ToolbarNeed(void)
{
    NSRect saved = [window frame];
    double need = -1;
    for (double w = 200; w <= 1400; w += 1) {
        SetContentWidth(w);
        if (ToolbarShowsAllItems()) { need = w; break; }
    }
    [window setFrame:saved display:NO animate:NO];
    return need;
}

static NSMutableDictionary *report;
static int Fail(int code, NSString *what) { report[@"failure"] = what; Emit(report); return code; }

int main(int argc, const char **argv)
{
    @autoreleasepool {
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        BOOL xib = [mode hasSuffix:@"-xib"];
        if (xib) {
            mode = [mode substringToIndex:[mode length] - 4];
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
        if (xib && xibTitlesSet != [xibTitles count]) return 13;
        report = [NSMutableDictionary dictionaryWithObject:[NSString stringWithUTF8String:argv[2]] forKey:@"mode"];

        method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(activateIgnoringOtherApps:)), (IMP)FakeActivate);
        method_setImplementation(class_getClassMethod([NSString class], @selector(stringWithContentsOfFile:encoding:error:)), (IMP)FakeAcknowledgements);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(makeKeyAndOrderFront:)), (IMP)FakeMakeKeyAndOrderFront);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isVisible)), (IMP)FakeIsVisible);
        method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(close)), (IMP)FakeClose);
        ChangePane(generalPane);     // stands in for the -resizeToFit: of -[UKPrefsPanel awakeFromNib]

        BOOL arrowOut = [mode isEqualToString:@"arrow-reaches-out"];
        if (arrowOut) {
            // A Restore Default arrow, hidden while its value is the default, past everything else.
            NSButton *arrow = nil;
            for (NSInteger i = 0; i < [[prefs tabView] numberOfTabViewItems] && arrow == nil; i++) {
                NSMutableArray *leaves = [NSMutableArray array];
                Leaves([[[prefs tabView] tabViewItemAtIndex:i] view], [[[prefs tabView] tabViewItemAtIndex:i] view], leaves);
                for (NSDictionary *leaf in leaves)
                    if ([[leaf[@"view"] identifier] isEqualToString:@"restoreDefaultMainHotkey"]) arrow = leaf[@"view"];
            }
            if (arrow == nil || ![arrow isHidden]) return Fail(21, @"the main hotkey's Restore Default arrow is not there or not hidden");
            [arrow setFrameOrigin:NSMakePoint(560, NSMinY([arrow frame]))];
        }

        double nibWidth = NSWidth([[prefs tabView] frame]);
        NSMutableArray *panes = [NSMutableArray array];
        double contentNeed = ContentNeed(panes);
        // A centred label whose text ends where General's fixed content ends (a column header at
        // the arrow column): its frame reaches 2 pt further, as a label keeps 2 pt free on each side.
        NSTextField *insetLabel = nil;
        NSRect insetFrame = NSZeroRect;
        if ([mode isEqualToString:@"inset-label"]) {
            NSView *general = [[[prefs tabView] tabViewItemAtIndex:generalPane] view];
            double edge = -1;
            for (NSDictionary *pane in panes)
                if ([pane[@"pane"] isEqualToString:[[[prefs tabView] tabViewItemAtIndex:generalPane] label]])
                    edge = [pane[@"rightEdge"] doubleValue];
            if (edge < 0) return Fail(22, @"no right edge for General");
            insetLabel = [NSTextField labelWithString:@"Receive"];
            [insetLabel setAlignment:NSTextAlignmentCenter];
            [insetLabel setFrame:[insetLabel frameForAlignmentRect:NSMakeRect(edge - 60, 8, 60, 16)]];
            [insetLabel setAutoresizingMask:NSViewMaxXMargin | NSViewMaxYMargin];
            [general addSubview:insetLabel];
            insetFrame = [insetLabel frame];
            report[@"insetLabelBefore"] = NSStringFromRect(insetFrame);
            report[@"generalRightEdge"] = @(edge);
        }
        double toolbarNeed = ToolbarNeed();
        double expected = contentNeed;     // the NIB's width is no floor
        NSRect before = [window frame];
        report[@"nibWidth"] = @(nibWidth);
        report[@"contentNeed"] = @(contentNeed);
        report[@"panes"] = panes;
        report[@"toolbarNeed"] = @(toolbarNeed);
        report[@"expectedWidth"] = @(expected);
        report[@"frameBefore"] = NSStringFromRect(before);
        if (toolbarNeed < 0) return Fail(20, @"the toolbar never shows all its items offscreen");

        [controller showPreferencePanel:nil];
        NSRect after = [window frame];
        report[@"frameAfter"] = NSStringFromRect(after);
        double width = [window contentRectForFrameRect:after].size.width;
        report[@"widthAfter"] = @(width);
        report[@"toolbarStyleAtShow"] = @(gStyleAtShow);

        if ([mode isEqualToString:@"preference-style"]) {
            if (gShows != 1 || gStyleAtShow != NSWindowToolbarStylePreference)
                return Fail(36, [NSString stringWithFormat:@"the window shows (%d times) with toolbar style %ld, not Preference (%ld): "
                                 "the title and the items share one row that needs %.0f pt", gShows, (long)gStyleAtShow,
                                 (long)NSWindowToolbarStylePreference, toolbarNeed]);
        } else if ([mode isEqualToString:@"fits-every-pane"]) {
            for (NSDictionary *pane in panes)
                if ([pane[@"need"] doubleValue] > width + 0.01)
                    return Fail(30, [NSString stringWithFormat:@"%@ needs %.1f pt, the window is %.1f", pane[@"pane"], [pane[@"need"] doubleValue], width]);
        } else if ([mode isEqualToString:@"fits-vertically"]) {
            // The pane shown when the window opens, then every pane as the toolbar selects it.
            NSMutableArray *vertical = [NSMutableArray arrayWithObject:Vertical(generalPane)];
            for (NSInteger i = 0; i < [[prefs tabView] numberOfTabViewItems]; i++) { ChangePane(i); [vertical addObject:Vertical(i)]; }
            report[@"vertical"] = vertical;
            for (NSDictionary *v in vertical)
                if ([v[@"controls"] integerValue] == 0 || [v[@"lowest"] doubleValue] < -0.01
                    || [v[@"highest"] doubleValue] > [v[@"contentHeight"] doubleValue] + 0.01)
                    return Fail(37, [NSString stringWithFormat:@"%@ is cut off under the toolbar: its controls span %.1f..%.1f pt, the window shows 0..%.1f",
                                     v[@"pane"], [v[@"lowest"] doubleValue], [v[@"highest"] doubleValue], [v[@"contentHeight"] doubleValue]]);
        } else if ([mode isEqualToString:@"toolbar-shows-all"]) {
            if (!ToolbarShowsAllItems())
                return Fail(31, [NSString stringWithFormat:@"the toolbar needs %.0f pt to show all four items, the window is %.1f: the last item is in the overflow", toolbarNeed, width]);
        } else if ([mode isEqualToString:@"no-wider-than-needed"] || arrowOut) {
            if (width > expected + 0.5)
                return Fail(32, [NSString stringWithFormat:@"the window is %.1f pt wide, the panes need %.1f (the NIB is %.0f, the toolbar %.0f): %.1f pt too wide",
                                 width, contentNeed, nibWidth, toolbarNeed, width - expected]);
            if (width < expected - 0.5)
                return Fail(35, [NSString stringWithFormat:@"the window is %.1f pt wide, narrower than the %.1f it needs", width, expected]);
        } else if ([mode isEqualToString:@"no-empty-strip"]) {
            NSDictionary *widest = nil;
            for (NSDictionary *pane in panes)
                if (widest == nil || [pane[@"need"] doubleValue] > [widest[@"need"] doubleValue]) widest = pane;
            double strip = width - [widest[@"rightEdge"] doubleValue];
            report[@"stripRightOfWidestPane"] = @(strip);
            if (strip > [widest[@"leftInset"] doubleValue] + 0.5)
                return Fail(38, [NSString stringWithFormat:@"%@, the widest pane, ends %.1f pt short of the window's right edge, %.1f pt more than its left inset (%.1f): an empty strip",
                                 widest[@"pane"], strip, strip - [widest[@"leftInset"] doubleValue], [widest[@"leftInset"] doubleValue]]);
        } else if ([mode isEqualToString:@"centred"]) {
            if (fabs(NSMidX(after) - NSMidX(before)) > 0.5 || fabs(NSMinY(after) - NSMinY(before)) > 0.5 || fabs(NSHeight(after) - NSHeight(before)) > 0.5)
                return Fail(33, [NSString stringWithFormat:@"the window moved: %@ -> %@", NSStringFromRect(before), NSStringFromRect(after)]);
        } else if ([mode isEqualToString:@"reopened"]) {
            [window close];
            [controller showPreferencePanel:nil];
            NSRect second = [window frame];
            [controller showPreferencePanel:nil];      // chosen again while open
            NSRect third = [window frame];
            report[@"frameSecond"] = NSStringFromRect(second);
            report[@"frameThird"] = NSStringFromRect(third);
            if (!NSEqualRects(after, second) || !NSEqualRects(after, third))
                return Fail(34, [NSString stringWithFormat:@"opening again moves or resizes the window: %@, %@, %@", NSStringFromRect(after), NSStringFromRect(second), NSStringFromRect(third)]);
        } else if ([mode isEqualToString:@"toolbar-no-spaces"]) {
            // The toolbar holds the four panes in the tab view's order and nothing else: no
            // flexible or fixed space (in the centred Preference style a space before
            // Acknowledgements only widens its gap). Every item stays on the allow-list of the
            // toolbar's customization.
            NSToolbar *toolbar = [window toolbar];
            NSArray *items = [[toolbar items] valueForKey:@"itemIdentifier"];
            NSMutableArray *tabs = [NSMutableArray array];
            for (NSTabViewItem *tab in [[prefs tabView] tabViewItems]) [tabs addObject:[tab identifier]];
            NSArray *defaults = [[toolbar delegate] toolbarDefaultItemIdentifiers:toolbar];
            NSArray *allowed = [[toolbar delegate] toolbarAllowedItemIdentifiers:toolbar];
            report[@"toolbarItems"] = items;
            report[@"toolbarDefaults"] = defaults;
            report[@"toolbarAllowed"] = allowed;
            if ([items containsObject:NSToolbarFlexibleSpaceItemIdentifier] || [items containsObject:NSToolbarSpaceItemIdentifier])
                return Fail(39, [NSString stringWithFormat:@"the toolbar holds a space: %@", [items componentsJoinedByString:@", "]]);
            if ([tabs count] != 4 || ![items isEqualToArray:tabs] || ![defaults isEqualToArray:tabs])
                return Fail(40, [NSString stringWithFormat:@"the toolbar holds %@ (defaults %@), not the four panes in order: %@",
                                 [items componentsJoinedByString:@", "], [defaults componentsJoinedByString:@", "], [tabs componentsJoinedByString:@", "]]);
            for (NSString *item in items)
                if (![allowed containsObject:item])
                    return Fail(41, [NSString stringWithFormat:@"%@ is on the toolbar but not on its allow-list %@", item, allowed]);
        } else if ([mode isEqualToString:@"toolbar-evenly-spaced"]) {
            // The window as shown, in the Preference style: the four items all on the bar, the
            // gaps between their frames equal (within 1 pt), the row centred in the window, and
            // the window as wide as before.
            NSArray *frames = ToolbarItemFrames();
            if (frames == nil) return Fail(42, @"the toolbar's item views cannot be found offscreen (-[NSToolbarItem _itemViewer])");
            report[@"toolbarFrames"] = frames;
            NSArray *visible = [[[window toolbar] visibleItems] valueForKey:@"itemIdentifier"];
            NSMutableArray *labelled = [NSMutableArray array];
            for (NSDictionary *frame in frames)
                if ([frame[@"label"] length] > 0) [labelled addObject:frame];
            if ([labelled count] != 4) return Fail(43, [NSString stringWithFormat:@"%lu labelled toolbar items, not 4", (unsigned long)[labelled count]]);
            for (NSDictionary *frame in labelled)
                if (![visible containsObject:frame[@"item"]])
                    return Fail(44, [NSString stringWithFormat:@"%@ is not on the bar (overflow) at %.1f pt", frame[@"label"], width]);
            NSMutableArray *gaps = [NSMutableArray array];
            double least = 1e9, most = -1e9;
            for (NSUInteger i = 1; i < [labelled count]; i++) {
                double gap = [labelled[i][@"minX"] doubleValue] - [labelled[i - 1][@"maxX"] doubleValue];
                [gaps addObject:@(gap)];
                least = MIN(least, gap);
                most = MAX(most, gap);
            }
            double left = [labelled[0][@"minX"] doubleValue], right = NSWidth([window frame]) - [[labelled lastObject][@"maxX"] doubleValue];
            report[@"toolbarGaps"] = gaps;
            report[@"toolbarMargins"] = @[@(left), @(right)];
            if (most - least > 1.0)
                return Fail(45, [NSString stringWithFormat:@"the gaps between General, Hotkeys, Appearance and Acknowledgements are %@ pt: not evenly spaced",
                                 [gaps componentsJoinedByString:@" / "]]);
            if (fabs(left - right) > 1.0)
                return Fail(46, [NSString stringWithFormat:@"the items are not centred: %.1f pt left, %.1f pt right", left, right]);
            if (fabs(width - expected) > 0.5)
                return Fail(47, [NSString stringWithFormat:@"the window is %.1f pt wide, not the %.1f the panes need", width, expected]);
        } else if ([mode isEqualToString:@"tab-view-follows"]) {
            // The tab view, and with it every pane, spans the window.
            NSMutableArray *widths = [NSMutableArray arrayWithObject:@(NSWidth([[prefs tabView] frame]))];
            for (NSInteger i = 0; i < [[prefs tabView] numberOfTabViewItems]; i++) {
                ChangePane(i);
                [widths addObject:@(NSWidth([[[[prefs tabView] tabViewItemAtIndex:i] view] frame]))];
            }
            report[@"tabWidths"] = widths;
            for (NSNumber *w in widths)
                if (fabs([w doubleValue] - width) > 0.5)
                    return Fail(48, [NSString stringWithFormat:@"the tab view or a pane is %@ pt wide, the window %.1f: %@", w, width,
                                     [widths componentsJoinedByString:@" / "]]);
        } else if ([mode isEqualToString:@"nothing-past-the-window"]) {
            // No control's frame (arrows hidden or not) reaches past the window's content.
            for (NSInteger i = 0; i < [[prefs tabView] numberOfTabViewItems]; i++) {
                ChangePane(i);
                NSView *pane = [[[prefs tabView] tabViewItemAtIndex:i] view];
                NSMutableArray *leaves = [NSMutableArray array];
                Leaves(pane, pane, leaves);
                for (NSDictionary *leaf in leaves) {
                    NSView *view = leaf[@"view"];
                    NSRect r = [[window contentView] convertRect:[view bounds] fromView:view];
                    if (NSMaxX(r) > width + 0.5 || NSMinX(r) < -0.5)
                        return Fail(49, [NSString stringWithFormat:@"%@: %@ %@ spans %.1f..%.1f, the window 0..%.1f", [[[prefs tabView] tabViewItemAtIndex:i] label],
                                         NSStringFromClass([view class]), [view identifier] ?: @"", NSMinX(r), NSMaxX(r), width]);
                }
            }
        } else if ([mode isEqualToString:@"elastic-follows"]) {
            // What takes any width ends at the window's width less the pane's left inset: the
            // Hotkeys hint (and its text still fits), the Acknowledgements text, Appearance's
            // arrow column; on Appearance a row's slider or recorder ends one gap before its
            // arrow and the right-aligned label under a slider ends where its slider ends, less 4.
            NSMutableArray *seen = [NSMutableArray array];
            for (NSInteger i = 0; i < [[prefs tabView] numberOfTabViewItems]; i++) {
                ChangePane(i);
                NSView *pane = [[[prefs tabView] tabViewItemAtIndex:i] view];
                NSString *name = [[[prefs tabView] tabViewItemAtIndex:i] label];
                BOOL appearance = IsAppearance(pane);
                double inset = 0;
                PaneNeed(pane, &inset, NULL);
                double target = width - inset;
                NSMutableArray *leaves = [NSMutableArray array];
                Leaves(pane, pane, leaves);
                for (NSDictionary *leaf in leaves) {
                    NSView *view = leaf[@"view"];
                    if (![leaf[@"elastic"] boolValue] || [view isKindOfClass:[NSBox class]]) continue;
                    [seen addObject:[NSString stringWithFormat:@"%@:%@", name, NSStringFromClass([view class])]];
                    BOOL arrow = [[view identifier] hasPrefix:@"restoreDefault"];
                    if (!appearance || arrow) {
                        double end = arrow ? [leaf[@"maxX"] doubleValue] : [leaf[@"alignMaxX"] doubleValue];
                        if (fabs(end - target) > 0.5)
                            return Fail(50, [NSString stringWithFormat:@"%@: %@ %@ ends at %.1f, not at the window less the inset (%.1f - %.1f = %.1f)",
                                             name, NSStringFromClass([view class]), [view identifier] ?: @"", end, width, inset, target]);
                    }
                    if (Wraps(view) || ([view isKindOfClass:[NSTextField class]] && [[(NSTextField *)view cell] wraps] && !appearance)) {
                        double needs = ceil([[(NSTextField *)view cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([view frame]), CGFLOAT_MAX)].height);
                        if (needs > NSHeight([view frame]) + 0.5)
                            return Fail(51, [NSString stringWithFormat:@"%@: the wrapping label needs %.1f pt, it has %.1f", name, needs, NSHeight([view frame])]);
                    }
                    if (appearance && !arrow) {
                        NSButton *rowArrow = nil;
                        NSSlider *rowSlider = nil;
                        for (NSView *sibling in [[view superview] subviews]) {
                            if ([[sibling identifier] hasPrefix:@"restoreDefault"]) rowArrow = (NSButton *)sibling;
                            if ([sibling isKindOfClass:[NSSlider class]]) rowSlider = (NSSlider *)sibling;
                        }
                        if ([view isKindOfClass:[NSTextField class]]) {
                            // a right-aligned min/max label: its slider is in the row above
                            NSView *row = [[view superview] superview];
                            if (rowSlider == nil && [row isKindOfClass:[NSBox class]])
                                for (NSView *sibling in [[(NSBox *)row contentView] subviews])
                                    if ([sibling isKindOfClass:[NSSlider class]]) rowSlider = (NSSlider *)sibling;
                            if (rowSlider == nil || fabs(NSMaxX([view frame]) - (NSMaxX([rowSlider frame]) - 4)) > 0.5)
                                return Fail(52, [NSString stringWithFormat:@"%@: the right-aligned label %@ ends at %.1f, its slider at %.1f", name,
                                                 [(NSTextField *)view stringValue], NSMaxX([view frame]), rowSlider ? NSMaxX([rowSlider frame]) : -1]);
                        } else if (rowArrow == nil || fabs(NSMaxX([view frame]) - (NSMinX([rowArrow frame]) - 4)) > 0.5) {
                            return Fail(53, [NSString stringWithFormat:@"%@: %@ ends at %.1f, its row's arrow starts at %.1f", name,
                                             NSStringFromClass([view class]), NSMaxX([view frame]), rowArrow ? NSMinX([rowArrow frame]) : -1]);
                        }
                    }
                }
            }
            report[@"elastic"] = seen;
            if ([seen count] < 8)
                return Fail(54, [NSString stringWithFormat:@"only %lu controls that follow the window were found: %@", (unsigned long)[seen count], seen]);
        } else if ([mode isEqualToString:@"inset-label"]) {
            // Its text fits: only the 2 pt it keeps free reach past the content's edge, so
            // nothing of it is cut off.
            report[@"insetLabelAfter"] = NSStringFromRect([insetLabel frame]);
            if (!NSEqualRects([insetLabel frame], insetFrame))
                return Fail(39, [NSString stringWithFormat:@"a label whose text ends at the arrows' edge was cut: %@ -> %@ "
                                 "(its text ended at %.1f)", NSStringFromRect(insetFrame), NSStringFromRect([insetLabel frame]),
                                 NSMaxX([insetLabel alignmentRectForFrame:insetFrame])]);
        } else if ([mode isEqualToString:@"report"]) {
            // numbers only
        } else {
            return 4;
        }
        Emit(report);
        return 0;
    }
}
'''


class PreferencesWindowWidthRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "WindowWidth"

    def check(self, mode: str, what: str, xib: bool = False) -> None:
        extra: tuple[str, ...] = ()
        if xib:
            titles = xib_checkbox_titles()
            self.assertEqual(len(titles), len(XIB_CHECKBOXES), titles)
            mode, extra = mode + "-xib", titles
        self.run_mode(mode, what, extra)

    def test_toolbar_has_the_preference_style_when_shown(self) -> None:
        self.check("preference-style", "the window shows with a toolbar style other than Preference")

    def test_window_is_no_wider_than_the_panes_need(self) -> None:
        self.check("no-wider-than-needed", "the window is wider than the panes need")

    def test_window_is_no_wider_than_needed_with_the_xib_titles(self) -> None:
        self.check("no-wider-than-needed", "the window is wider than the panes need (xib titles)", xib=True)

    def test_no_empty_strip_right_of_the_widest_pane(self) -> None:
        self.check("no-empty-strip", "an empty strip stays right of the widest pane")

    def test_every_pane_fits_the_window(self) -> None:
        self.check("fits-every-pane", "a pane's content, with its margin, does not fit the window")

    def test_every_pane_fits_the_window_with_the_xib_titles(self) -> None:
        self.check("fits-every-pane", "a pane's content, with its margin, does not fit the window (xib titles)", xib=True)

    def test_every_pane_fits_under_the_taller_toolbar(self) -> None:
        self.check("fits-vertically", "a pane's controls are cut off at the top or the bottom")

    def test_toolbar_shows_all_four_items(self) -> None:
        self.check("toolbar-shows-all", "the toolbar moves an item into its overflow")

    def test_toolbar_shows_all_four_items_with_the_xib_titles(self) -> None:
        self.check("toolbar-shows-all", "the toolbar moves an item into its overflow (xib titles)", xib=True)

    def test_a_restore_arrow_reaching_out_widens_the_window(self) -> None:
        self.check("arrow-reaches-out", "a Restore Default arrow, hidden or shown, is cut off or the window is wider than it needs")

    def test_tab_view_and_every_pane_span_the_window(self) -> None:
        self.check("tab-view-follows", "the tab view or a pane is not as wide as the window")

    def test_no_control_reaches_past_the_window(self) -> None:
        self.check("nothing-past-the-window", "a control's frame reaches past the window's content")

    def test_no_control_reaches_past_the_window_with_the_xib_titles(self) -> None:
        self.check("nothing-past-the-window", "a control's frame reaches past the window's content (xib titles)", xib=True)

    def test_controls_that_take_any_width_follow_the_window(self) -> None:
        self.check("elastic-follows", "a wrapping label, a slider, the arrow column or the Acknowledgements text does not end "
                   "at the window's width less the pane's inset")

    def test_a_label_reaching_out_only_by_its_inset_keeps_its_frame(self) -> None:
        self.check("inset-label", "a label whose text ends at the right edge is shortened by the 2 pt its frame keeps free")

    def test_window_stays_centred_where_it_was(self) -> None:
        self.check("centred", "the window's centre, bottom edge or height changed")

    def test_opening_again_leaves_the_window_as_it_was(self) -> None:
        self.check("reopened", "opening Preferences again moves or resizes the window")

    # A sight test: Acknowledgements must not sit further away than the other items. The
    # flexible space in front of it pushed it to the right edge in the old one-row toolbar; in
    # the centred Preference style it only made its gap 10 pt instead of 1.
    def test_toolbar_holds_the_four_panes_and_no_space(self) -> None:
        self.check("toolbar-no-spaces", "the toolbar holds a space or items other than the four panes")

    def test_toolbar_items_are_evenly_spaced_and_centred(self) -> None:
        self.check("toolbar-evenly-spaced", "the toolbar's four items are not all shown, evenly spaced and centred")


if __name__ == "__main__":
    unittest.main()
