#!/usr/bin/env python3
"""Remember, Display in menu and Favorites take a typed number in Preferences > General.

Until now the three numbers next to the steppers were display-only labels: a value could
only be reached by clicking the stepper, one step per click. Now each number is a field to
type into, made like Flycut's search fields (a rounded text field with a search field's
capsule, height and font; no search semantics), and the steppers are gone
(no other field in the app has them): not in the pane, not in the Tab order, no longer bound;
their action and tooltip are the field's. Click a field, type up to three digits, and the
value is stored when editing ends (Return, Tab, focus leaving, a pane change or closing the
window), never per keystroke - typing 100 must not pass through 1 and 10, which would ask to
resize the history and drop clippings. Non-digits and a fourth digit are refused while
typing, with the system beep (nothing else shows the refusal); a typed number outside the
limits silently becomes the nearest allowed one, which the field shows: Remember and
Favorites 10-999, "Display in menu" 5 up to the current "Remember". Escape and an empty field
bring back the stored value; leaving a field without typing never changes it. The value takes
the steppers' path (the Resize Stack warning and its Cancel, "Display in menu" following a
smaller "Remember"); the Restore Default arrow follows each field where the stepper was, the
next label follows the arrow with the gap it had after the stepper, the pane keeps its width,
and the VoiceOver names and the Tab order keep working.

The fixture loads the production NIB (master's compiled MainMenu.nib for trees that carry
only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py), sends the builders that
-awakeFromNib sends and types through the field editor as the keyboard does. A real
FlycutOperator holds the clippings; its Resize Stack question is answered by a stand-in
for -alertWithMessageText:... that records it. The production code's NSBeep() is counted:
this binary is built with -DNSBeep=FCFixtureBeep. The memory defaults report changes to the
defaults controller as NSUserDefaults does, and nothing is ordered on screen. What the NIB
has before the builders run (the steppers, their tooltips and actions, the gap after each
stepper, the tab view's width) is recorded first, so the cases compare against the NIB.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

FIXTURE = r'''
@interface AppController (NumberEntryTesting)
- (void)updateRestoreDefaultButtons;
- (IBAction)restoreDefault:(id)sender;
@end

static int beeps;
void FCFixtureBeep(void) { beeps++; }

static NSMutableArray *alerts;
static NSString *alertChoice = @"Resize";
static NSString *RecordAlert(id self, SEL cmd, NSString *message, NSString *information, NSArray *buttons)
{
    (void)self; (void)cmd; (void)information; (void)buttons;
    [alerts addObject:message];
    return alertChoice;
}

// FCMemoryDefaults keeps no registration domain of its own; this reads back what was
// registered, as NSUserDefaults does (the Restore Default arrows compare against it).
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

// The real NSUserDefaults reports every change made in the process to key-value observers
// (and posts NSUserDefaultsDidChangeNotification), and the defaults controller the NIB binds to
// refreshes the bound field and stepper at once, also a field still being edited after Return:
// a value the code stores directly (Cancel in Resize Stack) shows up in the field
// (appkit-probes/defaultsrefresh.m in the evidence, real NSUserDefaults kept in memory).
// FCMemoryDefaults reports nothing, so these wrappers do.
static IMP memorySet, memoryRemove;
static void ReportingSet(id self, SEL cmd, id value, NSString *key)
{
    if (key) [self willChangeValueForKey:key];
    ((void (*)(id, SEL, id, NSString *))memorySet)(self, cmd, value, key);
    if (key) [self didChangeValueForKey:key];
    [[NSNotificationCenter defaultCenter] postNotificationName:NSUserDefaultsDidChangeNotification object:self];
}
static void ReportingRemove(id self, SEL cmd, NSString *key)
{
    if (key) [self willChangeValueForKey:key];
    ((void (*)(id, SEL, NSString *))memoryRemove)(self, cmd, key);
    if (key) [self didChangeValueForKey:key];
    [[NSNotificationCenter defaultCenter] postNotificationName:NSUserDefaultsDidChangeNotification object:self];
}

static NSArray *Keys(void) { return @[@"rememberNum", @"displayNum", @"favoritesRememberNum"]; }
static NSDictionary *Labels(void)
{
    return @{@"rememberNum": @"Remember", @"displayNum": @"Display in menu", @"favoritesRememberNum": @"Favorites"};
}

static NSView *General(void) { return PaneView(generalPane); }

static NSView *FindView(NSView *root, BOOL (^match)(NSView *))
{
    if (match(root)) return root;
    for (NSView *child in [root subviews]) {
        NSView *found = FindView(child, match);
        if (found) return found;
    }
    return nil;
}

static NSControl *Bound(NSString *key, Class kind)
{
    NSString *keyPath = [@"values." stringByAppendingString:key];
    return (NSControl *)FindView(General(), ^BOOL(NSView *view) {
        return [view isKindOfClass:kind] && [BoundKeyPath(view) isEqualToString:keyPath];
    });
}
static NSTextField *Field(NSString *key) { return (NSTextField *)Bound(key, [NSTextField class]); }

// The NIB before the builders run: each number's stepper (kept alive here), its tooltip and
// action, the view the NIB holds at the stepper's right edge and that gap, the tab view's width.
static NSMutableDictionary *nibSteppers, *nibTooltips, *nibActions, *nibNext, *nibGaps;
static CGFloat nibTabsWidth;
static void RecordNib(void)
{
    nibSteppers = [[NSMutableDictionary alloc] init];
    nibTooltips = [[NSMutableDictionary alloc] init];
    nibActions = [[NSMutableDictionary alloc] init];
    nibNext = [[NSMutableDictionary alloc] init];
    nibGaps = [[NSMutableDictionary alloc] init];
    nibTabsWidth = NSWidth([[prefs tabView] frame]);
    NSView *pane = [[controller valueForKey:@"savingSectionLabel"] superview];
    for (NSString *key in Keys()) {
        NSString *keyPath = [@"values." stringByAppendingString:key];
        NSStepper *stepper = (NSStepper *)FindView(pane, ^BOOL(NSView *view) {
            return [view isKindOfClass:[NSStepper class]] && [BoundKeyPath(view) isEqualToString:keyPath];
        });
        if (stepper == nil) continue;
        nibSteppers[key] = stepper;
        if ([stepper toolTip]) nibTooltips[key] = [stepper toolTip];
        if ([stepper action]) nibActions[key] = NSStringFromSelector([stepper action]);
        for (NSLayoutConstraint *c in [[stepper superview] constraints])
            if ([c secondItem] == stepper && [c secondAttribute] == NSLayoutAttributeTrailing &&
                [c firstAttribute] == NSLayoutAttributeLeading && [c relation] == NSLayoutRelationEqual) {
                nibNext[key] = [c firstItem];
                nibGaps[key] = @([c constant]);
            }
    }
}

// A search field as Flycut makes them: a plain NSSearchField with AppKit's defaults (only the
// frame differs between them; AppKit draws the bezel at its own height).
static NSSearchField *SearchField(void)
{
    return [[[NSSearchField alloc] initWithFrame:NSMakeRect(10, 11, 364, 22)] autorelease];
}

static NSButton *Arrow(NSString *key)
{
    NSString *identifier = [@"restoreDefault" stringByAppendingString:[[[key substringToIndex:1] uppercaseString] stringByAppendingString:[key substringFromIndex:1]]];
    return (NSButton *)FindView(General(), ^BOOL(NSView *view) { return [[view identifier] isEqualToString:identifier]; });
}
static NSRect Align(NSView *view) { return [view alignmentRectForFrame:[view frame]]; }

// The text label left of the field on its line ("Remember", ...).
static NSTextField *LabelOf(NSView *field)
{
    NSTextField *best = nil;
    for (NSView *other in [[field superview] subviews]) {
        if (![other isKindOfClass:[NSTextField class]] || [(NSTextField *)other isEditable] || BoundKeyPath(other) != nil) continue;
        NSRect o = [other frame], f = [field frame];
        if (MIN(NSMaxY(o), NSMaxY(f)) - MAX(NSMinY(o), NSMinY(f)) <= 2.0 || NSMaxX(o) > NSMinX(f) + 4.0) continue;
        if (best == nil || NSMaxX(o) > NSMaxX([best frame])) best = (NSTextField *)other;
    }
    return best;
}

// What the user domain holds (nil: the registered value applies).
static id Stored(NSString *key)
{
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    NSDictionary *stored = object_getIvar([NSUserDefaults standardUserDefaults], ivar);
    return [stored objectForKey:key];
}
static NSInteger Value(NSString *key) { return [[NSUserDefaults standardUserDefaults] integerForKey:key]; }

// Through the defaults controller the NIB binds to, as a stepper click stores it.
static void SetUserValue(NSString *key, id value)
{
    NSDictionary *binding = [Field(key) infoForBinding:NSValueBinding];
    [[binding objectForKey:NSObservedObjectKey] setValue:value forKeyPath:[binding objectForKey:NSObservedKeyPathKey]];
}

static FlycutOperator *op;

// A real operator with that many clippings; forgotten clippings are not saved to files.
static void StartOperator(int remember, int clippings)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setBool:NO forKey:@"saveForgottenClippings"];
    [defaults setBool:NO forKey:@"saveForgottenFavorites"];
    SetUserValue(@"rememberNum", @(remember));
    op = [[FlycutOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:NULL forTarget:nil];
    for (int i = 0; i < clippings; i++)
        [op addClipping:[NSString stringWithFormat:@"clipping %d", i] ofType:NSPasteboardTypeString fromApp:@"Fixture"
             withAppBundleURL:@"" target:nil clippingAddedSelector:NULL];
    [op setDelegate:(id)controller];
    [controller setValue:op forKey:@"flycutOperator"];
    [op willShowPreferences];
}

static NSTextView *Begin(NSTextField *field)
{
    if (![window makeFirstResponder:field]) return nil;
    NSTextView *editor = (NSTextView *)[field currentEditor];
    [editor selectAll:nil];
    return editor;
}

// One keystroke per character, as the keyboard types them.
static void TypeKeys(NSTextView *editor, NSString *text)
{
    for (NSUInteger i = 0; i < [text length]; i++)
        [editor insertText:[text substringWithRange:NSMakeRange(i, 1)] replacementRange:[editor selectedRange]];
}

static NSString *Editing(NSTextField *field) { return [(NSTextView *)[field currentEditor] string]; }

// Ends the editing the way the user does.
static void End(NSTextField *field, NSString *how)
{
    NSTextView *editor = (NSTextView *)[field currentEditor];
    if ([how isEqualToString:@"return"]) [editor doCommandBySelector:@selector(insertNewline:)];
    else if ([how isEqualToString:@"tab"]) [editor doCommandBySelector:@selector(insertTab:)];
    else if ([how isEqualToString:@"focus"]) [window makeFirstResponder:nil];
    else if ([how isEqualToString:@"close"]) [window close];
    else if ([how isEqualToString:@"pane"]) ChangePane(appearancePane);
}

static NSDictionary *details;  // what a failing case measured, sent along with the failure

static int Fail(int code, NSString *what)
{
    Emit(@{@"failed": what, @"code": @(code), @"beeps": @(beeps), @"alerts": alerts ?: @[], @"details": details ?: @{}});
    fprintf(stderr, "FAIL: %s\n", [what UTF8String]);
    return code;
}

// The three numbers are editable fields.
static int Editable(void)
{
    for (NSString *key in Keys()) {
        NSTextField *field = Field(key);
        if (field == nil) return Fail(20, [key stringByAppendingString:@": no field"]);
        if (![field isEditable] || ![field isSelectable]) return Fail(21, [key stringByAppendingString:@": the number is not editable"]);
        if (![field acceptsFirstResponder] || Begin(field) == nil) return Fail(22, [key stringByAppendingString:@": a click does not start editing"]);
        [window makeFirstResponder:nil];
    }
    Emit(@{@"mode": @"editable"});
    return 0;
}

// Each field is made like Flycut's search fields: a rounded text field (not a search
// field: no magnifier, no search semantics) with the capsule a search field draws on
// macOS 26 and later, its font, control size, background and height. The digits stand in
// the middle: the capsule's round ends leave no room for a caret next to them.
static int Look(void)
{
    NSSearchField *search = SearchField();
    NSMutableDictionary *report = [NSMutableDictionary dictionary];
    for (NSString *key in Keys()) {
        NSTextField *field = Field(key);
        NSMutableDictionary *row = [NSMutableDictionary dictionaryWithDictionary:@{
            @"class": NSStringFromClass([field class]), @"bezeled": @([field isBezeled]), @"bordered": @([field isBordered]),
            @"bezelStyle": @([field bezelStyle]), @"searchBezelStyle": @([search bezelStyle]),
            @"font": [NSString stringWithFormat:@"%@ %g", [[field font] fontName], [[field font] pointSize]],
            @"searchFont": [NSString stringWithFormat:@"%@ %g", [[search font] fontName], [[search font] pointSize]],
            @"drawsBackground": @([field drawsBackground]), @"searchDrawsBackground": @([search drawsBackground]),
            @"height": @(NSHeight([field frame])), @"searchHeight": @([search intrinsicContentSize].height),
            @"alignment": @([field alignment])}];
        if (@available(macOS 26.0, *)) row[@"borderShape"] = @([field borderShape]);
        report[key] = row;
        details = report;
        if (field == nil || [field isKindOfClass:[NSSearchField class]]) return Fail(170, [key stringByAppendingString:@": not a plain text field"]);
        if (![field isBezeled] || [field isBordered] || [field bezelStyle] != NSTextFieldRoundedBezel || [field bezelStyle] != [search bezelStyle])
            return Fail(171, [key stringByAppendingString:@": not the search field's rounded bezel"]);
        if (@available(macOS 26.0, *)) {
            if ([field borderShape] != NSControlBorderShapeCapsule) return Fail(172, [key stringByAppendingString:@": not the search field's capsule"]);
        }
        if (![[[field font] fontName] isEqualToString:[[search font] fontName]] || [[field font] pointSize] != [[search font] pointSize] ||
            [field controlSize] != [search controlSize])
            return Fail(173, [key stringByAppendingString:@": not the search field's font or size"]);
        if ([field drawsBackground] != [search drawsBackground]) return Fail(174, [key stringByAppendingString:@": draws a background the search field does not"]);
        if (fabs(NSHeight([field frame]) - [search intrinsicContentSize].height) > 0.5)
            return Fail(175, [key stringByAppendingString:@": not as tall as the search field draws"]);
        if ([field alignment] != NSTextAlignmentCenter) return Fail(176, [key stringByAppendingString:@": the digits are not centred"]);
    }
    Emit(@{@"mode": @"look", @"report": report});
    return 0;
}

// The steppers are gone: out of the pane and the window (so out of the Tab order), no
// longer bound to the setting; no stepper is left in the window at all. Their action is
// the field's, so a typed value goes the way a click went.
static int NoSteppers(void)
{
    if ([nibSteppers count] != [Keys() count]) return Fail(180, @"the NIB has no stepper for every number");
    for (NSString *key in Keys()) {
        NSStepper *stepper = nibSteppers[key];
        if ([stepper superview] != nil || [stepper window] != nil)
            return Fail(181, [key stringByAppendingString:@": its stepper is still in the pane"]);
        for (NSString *binding in @[NSValueBinding, NSMaxValueBinding, NSMinValueBinding])
            if ([stepper infoForBinding:binding] != nil)
                return Fail(182, [NSString stringWithFormat:@"%@: the removed stepper is still bound (%@)", key, binding]);
        NSTextField *field = Field(key);
        if ([field target] != controller || ![NSStringFromSelector([field action]) isEqualToString:nibActions[key]])
            return Fail(183, [NSString stringWithFormat:@"%@: the field sends %@ to %@, the stepper sent %@", key,
                             NSStringFromSelector([field action]), [field target], nibActions[key]]);
    }
    NSView *left = FindView([[window contentView] superview], ^BOOL(NSView *view) { return [view isKindOfClass:[NSStepper class]]; });
    if (left != nil) return Fail(184, [NSString stringWithFormat:@"a stepper is left in the window: %@", left]);
    Emit(@{@"mode": @"no-steppers"});
    return 0;
}

// What a stepper's tooltip said is now the field's.
static int Tooltips(void)
{
    for (NSString *key in Keys()) {
        NSString *tip = nibTooltips[key];
        if ([tip length] == 0) return Fail(190, [key stringByAppendingString:@": the NIB's stepper has no tooltip"]);
        if (![[Field(key) toolTip] isEqualToString:tip])
            return Fail(191, [NSString stringWithFormat:@"%@: the field's tooltip is %@, the stepper's was %@", key, [Field(key) toolTip], tip]);
    }
    Emit(@{@"mode": @"tooltips", @"tooltips": nibTooltips});
    return 0;
}

// Three digits fit, the three fields are as wide, and the row is a clean line: label,
// field, then the field's Restore Default arrow (where the stepper's arrow was), then the next
// label with the gap the NIB had after the stepper. The labels keep their width, the digits
// sit on the labels' baseline, the arrows are centred on their fields, and the pane keeps
// the NIB's width (the panes grew for field and stepper before).
static int Layout(void)
{
    [[window contentView] layoutSubtreeIfNeeded];
    NSMutableDictionary *report = [NSMutableDictionary dictionary];
    CGFloat width = -1;
    NSView *pane = General();
    for (NSString *key in Keys()) {
        NSTextField *field = Field(key);
        NSTextField *label = LabelOf(field);
        NSButton *arrow = Arrow(key);
        NSView *next = nibNext[key];
        CGFloat need = 0;
        for (NSString *digits in @[@"000", @"111", @"222", @"333", @"444", @"555", @"666", @"777", @"888", @"999"]) {
            NSTextFieldCell *cell = [[[field cell] copy] autorelease];
            [cell setFormatter:nil];
            [cell setStringValue:digits];
            need = MAX(need, [cell cellSize].width);
        }
        NSRect f = Align(field), a = Align(arrow);
        report[key] = @{@"field": NSStringFromRect([field frame]), @"label": NSStringFromRect([label frame]),
                        @"arrow": NSStringFromRect([arrow frame]), @"next": next ? NSStringFromRect([next frame]) : @"-",
                        @"nibGap": nibGaps[key] ?: @"-", @"needs": @(need), @"labelIntrinsic": @([label intrinsicContentSize].width),
                        @"tabs": NSStringFromRect([[prefs tabView] frame]), @"nibTabsWidth": @(nibTabsWidth)};
        details = report;
        if (label == nil || arrow == nil) return Fail(30, [key stringByAppendingString:@": no label or no arrow"]);
        if (NSWidth([field frame]) + 0.5 < need) return Fail(31, [key stringByAppendingString:@": three digits do not fit"]);
        if (width >= 0 && fabs(NSWidth([field frame]) - width) > 0.5) return Fail(33, @"the three fields differ in width");
        width = NSWidth([field frame]);
        // Squeezed labels give way first: "Favorites" wrapped onto a second line.
        CGFloat oneLine = [[label cell] cellSizeForBounds:NSMakeRect(0, 0, 10000, 10000)].height;
        CGFloat atWidth = [[label cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([label frame]), 10000)].height;
        if (NSWidth([label frame]) + 0.5 < [label intrinsicContentSize].width || atWidth > oneLine + 0.5)
            return Fail(34, [key stringByAppendingString:@": its label is squeezed or wraps"]);
        // The digits on the label's baseline; the arrow centred on the field.
        CGFloat fieldBaseline = NSMaxY([field frame]) - [field firstBaselineOffsetFromTop];
        CGFloat labelBaseline = NSMaxY([label frame]) - [label firstBaselineOffsetFromTop];
        if (fabs(fieldBaseline - labelBaseline) > 0.5 || fabs(NSMidY(a) - NSMidY(f)) > 0.5)
            return Fail(38, [NSString stringWithFormat:@"%@: baseline %g vs label %g, arrow centre %g vs field %g", key, fieldBaseline,
                             labelBaseline, NSMidY(a), NSMidY(f)]);
        // label - field - arrow - next label, with no hole where the stepper was.
        if (NSMinX([field frame]) < NSMaxX([label frame]) || fabs(NSMinX(a) - NSMaxX(f) - 4.0) > 0.5)
            return Fail(35, [NSString stringWithFormat:@"%@: field %@ after label %@, arrow %@", key, NSStringFromRect(f),
                             NSStringFromRect([label frame]), NSStringFromRect(a)]);
        if (next != nil && (nibGaps[key] == nil || fabs(NSMinX(Align(next)) - NSMaxX(a) - [nibGaps[key] doubleValue]) > 0.5))
            return Fail(39, [NSString stringWithFormat:@"%@: the next label starts at %g, the arrow ends at %g, the NIB's gap was %@", key,
                             NSMinX(Align(next)), NSMaxX(a), nibGaps[key]]);
        for (NSView *view in @[field, label, arrow])
            if (!NSContainsRect([pane bounds], [view frame])) return Fail(36, [key stringByAppendingString:@": the row leaves the pane"]);
    }
    if (fabs(NSWidth([[prefs tabView] frame]) - nibTabsWidth) > 0.5)
        return Fail(37, [NSString stringWithFormat:@"the panes are %g wide, the NIB's %g", NSWidth([[prefs tabView] frame]), nibTabsWidth]);
    Emit(@{@"mode": @"layout", @"report": report});
    return 0;
}

// Letters, signs and a fourth digit are refused while typing, with a beep.
static int Digits(void)
{
    SetUserValue(@"rememberNum", @40);
    NSTextField *field = Field(@"rememberNum");
    NSTextView *editor = Begin(field);
    if (editor == nil) return Fail(40, @"no editor");
    for (NSString *text in @[@"a", @"-", @" ", @"1.5"]) {
        [editor selectAll:nil];
        [editor insertText:text replacementRange:[editor selectedRange]];
        if (![[editor string] isEqualToString:@"40"]) return Fail(41, [NSString stringWithFormat:@"'%@' reached the field: %@", text, [editor string]]);
    }
    if (beeps != 4) return Fail(42, [NSString stringWithFormat:@"%d beeps for four refused entries", beeps]);
    [editor selectAll:nil];
    TypeKeys(editor, @"1234");
    if (![[editor string] isEqualToString:@"123"]) return Fail(43, [@"four digits: " stringByAppendingString:[editor string]]);
    if (beeps != 5) return Fail(44, @"no beep for the fourth digit");
    [window makeFirstResponder:nil];
    Emit(@{@"mode": @"digits", @"beeps": @(beeps)});
    return 0;
}

// Typing 1, 0, 0 stores nothing and drops no clipping until the editing ends.
static int CommitAtEnd(NSString *how)
{
    StartOperator(40, 40);
    NSTextField *field = Field(@"rememberNum");
    NSTextView *editor = Begin(field);
    if (editor == nil) return Fail(50, @"no editor");
    NSArray *keys = @[@"1", @"0", @"0"];
    for (NSString *key in keys) {
        TypeKeys(editor, key);
        if (Value(@"rememberNum") != 40 || [op rememberNum] != 40 || [op jcListCount] != 40 || [alerts count])
            return Fail(51, [NSString stringWithFormat:@"after typing %@: stored %ld, store limit %d, %d clippings, %lu alerts",
                             [editor string], (long)Value(@"rememberNum"), [op rememberNum], [op jcListCount],
                             (unsigned long)[alerts count]]);
    }
    End(field, how);
    if (Value(@"rememberNum") != 100 || [op rememberNum] != 100 || [op jcListCount] != 40)
        return Fail(52, [NSString stringWithFormat:@"%@ stored %ld, store limit %d, %d clippings", how, (long)Value(@"rememberNum"),
                         [op rememberNum], [op jcListCount]]);
    if ([alerts count] || beeps) return Fail(53, @"an alert or a beep for an allowed value");
    if (![[field stringValue] isEqualToString:@"100"]) return Fail(54, @"the field does not show 100");
    Emit(@{@"mode": [@"commit-" stringByAppendingString:how]});
    return 0;
}

// Lowering Remember by typing asks once, when the editing ends; Cancel keeps limit and clippings.
static int ResizeWarning(void)
{
    StartOperator(40, 40);
    NSTextField *field = Field(@"rememberNum");
    alertChoice = @"Cancel";
    TypeKeys(Begin(field), @"20");
    End(field, @"return");
    if ([alerts count] != 1 || ![[alerts firstObject] isEqualToString:@"Resize Stack"])
        return Fail(60, [NSString stringWithFormat:@"alerts %@", alerts]);
    if (Value(@"rememberNum") != 40 || [op rememberNum] != 40 || [op jcListCount] != 40 || ![[field stringValue] isEqualToString:@"40"])
        return Fail(61, [NSString stringWithFormat:@"Cancel: stored %ld, store %d, %d clippings, field %@", (long)Value(@"rememberNum"),
                         [op rememberNum], [op jcListCount], [field stringValue]]);
    alertChoice = @"Resize";
    SetUserValue(@"displayNum", @30);
    TypeKeys(Begin(field), @"20");
    End(field, @"focus");
    if ([alerts count] != 2 || Value(@"rememberNum") != 20 || [op rememberNum] != 20 || [op jcListCount] != 20)
        return Fail(62, [NSString stringWithFormat:@"Resize: %lu alerts, stored %ld, store %d, %d clippings", (unsigned long)[alerts count],
                         (long)Value(@"rememberNum"), [op rememberNum], [op jcListCount]]);
    if (Value(@"displayNum") != 20) return Fail(63, [NSString stringWithFormat:@"Display in menu stayed %ld above Remember 20", (long)Value(@"displayNum")]);
    Emit(@{@"mode": @"resize-warning", @"alerts": alerts});
    return 0;
}

// A number outside the limits silently becomes the nearest allowed one; the field shows it.
static int Clamp(void)
{
    StartOperator(999, 0);
    SetUserValue(@"displayNum", @10);
    SetUserValue(@"favoritesRememberNum", @40);
    NSArray *cases = @[
        @[@"rememberNum", @"5", @10], @[@"rememberNum", @"0", @10], @[@"rememberNum", @"007", @10],
        @[@"rememberNum", @"9", @10], @[@"rememberNum", @"999", @999], @[@"rememberNum", @"10", @10], @[@"rememberNum", @"999", @999],
        @[@"favoritesRememberNum", @"3", @10], @[@"favoritesRememberNum", @"0", @10], @[@"favoritesRememberNum", @"999", @999],
        @[@"favoritesRememberNum", @"10", @10], @[@"favoritesRememberNum", @"40", @40],
        @[@"displayNum", @"4", @5], @[@"displayNum", @"0", @5], @[@"displayNum", @"500", @500],
        @[@"displayNum", @"5", @5], @[@"displayNum", @"999", @999],
    ];
    NSMutableArray *results = [NSMutableArray array];
    for (NSArray *c in cases) {
        NSString *key = c[0];
        NSTextField *field = Field(key);
        int before = beeps;
        TypeKeys(Begin(field), c[1]);
        End(field, @"return");
        NSInteger want = [c[2] integerValue];
        [results addObject:[NSString stringWithFormat:@"%@ %@ -> %@ (%d beeps)", key, c[1], [field stringValue], beeps - before]];
        if (Value(key) != want || ![[field stringValue] isEqualToString:[NSString stringWithFormat:@"%ld", (long)want]])
            return Fail(70, [NSString stringWithFormat:@"%@ typed %@: stored %ld, field %@, want %ld", key, c[1],
                             (long)Value(key), [field stringValue], (long)want]);
        if (beeps != before) return Fail(71, [NSString stringWithFormat:@"%@ typed %@: %d beeps, the corrected number shows", key, c[1], beeps - before]);
    }
    Emit(@{@"mode": @"clamp", @"cases": results});
    return 0;
}

// "Display in menu" goes up to the current "Remember", also right after typing Remember,
// silently; a smaller Remember lowers it, a larger one raises only the limit.
static int ClampDisplay(void)
{
    StartOperator(999, 0);
    SetUserValue(@"displayNum", @500);
    NSTextField *remember = Field(@"rememberNum"), *display = Field(@"displayNum");
    TypeKeys(Begin(remember), @"40");
    End(remember, @"tab");
    if (Value(@"rememberNum") != 40 || Value(@"displayNum") != 40)
        return Fail(80, [NSString stringWithFormat:@"Remember 40 left Display in menu at %ld", (long)Value(@"displayNum")]);
    TypeKeys(Begin(display), @"100");
    End(display, @"return");
    if (Value(@"displayNum") != 40 || ![[display stringValue] isEqualToString:@"40"] || beeps)
        return Fail(82, [NSString stringWithFormat:@"Display 100 under Remember 40: stored %ld, field %@, %d beeps",
                         (long)Value(@"displayNum"), [display stringValue], beeps]);
    TypeKeys(Begin(display), @"39");
    End(display, @"return");
    if (Value(@"displayNum") != 39 || beeps) return Fail(83, @"Display 39 under Remember 40 was changed");
    TypeKeys(Begin(remember), @"60");
    End(remember, @"tab");
    if (Value(@"rememberNum") != 60 || Value(@"displayNum") != 39) return Fail(84, @"a larger Remember changed Display in menu");
    TypeKeys(Begin(display), @"70");
    End(display, @"return");
    if (Value(@"displayNum") != 60 || ![[display stringValue] isEqualToString:@"60"] || beeps)
        return Fail(85, [NSString stringWithFormat:@"Display 70 under Remember 60: stored %ld, field %@, %d beeps",
                         (long)Value(@"displayNum"), [display stringValue], beeps]);
    TypeKeys(Begin(display), @"55");
    End(display, @"return");
    if (Value(@"displayNum") != 55 || beeps) return Fail(86, @"Display 55 under Remember 60 was changed");
    Emit(@{@"mode": @"clamp-display"});
    return 0;
}

// Escape brings back the stored value and stores nothing.
static int Escape(void)
{
    StartOperator(77, 60);
    NSTextField *field = Field(@"rememberNum");
    NSTextView *editor = Begin(field);
    if (editor == nil) return Fail(93, @"no editor");
    TypeKeys(editor, @"12");
    if (![[editor string] isEqualToString:@"12"]) return Fail(94, [@"typed 12, the field shows " stringByAppendingString:[editor string]]);
    [editor doCommandBySelector:@selector(cancelOperation:)];
    if (![(Editing(field) ?: [field stringValue]) isEqualToString:@"77"])
        return Fail(90, [NSString stringWithFormat:@"after Escape the field shows %@", Editing(field) ?: [field stringValue]]);
    [window makeFirstResponder:nil];
    if (Value(@"rememberNum") != 77 || [op rememberNum] != 77 || [op jcListCount] != 60 || [alerts count] || beeps)
        return Fail(91, [NSString stringWithFormat:@"Escape stored %ld, store %d, %d clippings, %lu alerts, %d beeps", (long)Value(@"rememberNum"),
                         [op rememberNum], [op jcListCount], (unsigned long)[alerts count], beeps]);
    if (![[field stringValue] isEqualToString:@"77"]) return Fail(92, @"the field does not show 77");
    Emit(@{@"mode": @"escape"});
    return 0;
}

// An emptied field keeps the stored value (not the factory one).
static int Empty(void)
{
    StartOperator(77, 0);
    NSTextField *field = Field(@"rememberNum");
    NSTextView *editor = Begin(field);
    if (editor == nil) return Fail(103, @"no editor");
    [editor deleteBackward:nil];
    if ([[editor string] length]) return Fail(100, @"the field could not be emptied");
    [window makeFirstResponder:nil];
    if (![[Stored(@"rememberNum") description] isEqualToString:@"77"] || [op rememberNum] != 77 || ![[field stringValue] isEqualToString:@"77"])
        return Fail(101, [NSString stringWithFormat:@"empty: stored %@, store %d, field %@", Stored(@"rememberNum"), [op rememberNum], [field stringValue]]);
    if (beeps || [alerts count]) return Fail(102, @"a beep or an alert for an empty field");
    Emit(@{@"mode": @"empty"});
    return 0;
}

// Leaving a field without typing (or after Escape) keeps what is stored, even outside the
// limits (a value stored by hand): no clamping, no Resize Stack question.
static int Untouched(void)
{
    StartOperator(40, 0);
    SetUserValue(@"rememberNum", @1500);
    [op setRememberNum:1500 forPrimaryStore:YES];
    NSTextField *field = Field(@"rememberNum");
    for (NSString *how in @[@"tab", @"return", @"focus"]) {
        if (Begin(field) == nil) return Fail(160, @"no editor");
        End(field, how);
        [window makeFirstResponder:nil];
        if (Value(@"rememberNum") != 1500 || [op rememberNum] != 1500 || beeps || [alerts count])
            return Fail(161, [NSString stringWithFormat:@"%@ without typing: stored %ld, store %d, %d beeps, %lu alerts", how,
                             (long)Value(@"rememberNum"), [op rememberNum], beeps, (unsigned long)[alerts count]]);
    }
    // Typing and then Escape counts as no typing: the field shows the stored value again.
    NSTextView *editor = Begin(field);
    TypeKeys(editor, @"25");
    [editor doCommandBySelector:@selector(cancelOperation:)];
    End(field, @"tab");
    [window makeFirstResponder:nil];
    if (Value(@"rememberNum") != 1500 || [op rememberNum] != 1500 || beeps || [alerts count])
        return Fail(162, [NSString stringWithFormat:@"typing, Escape, Tab: stored %ld, store %d, %d beeps, %lu alerts",
                         (long)Value(@"rememberNum"), [op rememberNum], beeps, (unsigned long)[alerts count]]);
    Emit(@{@"mode": @"untouched"});
    return 0;
}

// After typing a custom value the arrow appears and brings back the factory value.
static int Restore(void)
{
    StartOperator(40, 0);
    [controller updateRestoreDefaultButtons];
    NSTextField *field = Field(@"rememberNum");
    TypeKeys(Begin(field), @"100");
    End(field, @"return");
    [window makeFirstResponder:nil];
    [controller updateRestoreDefaultButtons];
    NSButton *arrow = (NSButton *)FindView(General(), ^BOOL(NSView *view) { return [[view identifier] isEqualToString:@"restoreDefaultRememberNum"]; });
    if (arrow == nil || [arrow isHidden]) return Fail(120, @"no arrow after typing 100");
    [arrow performClick:nil];
    NSInteger registered = [[[[NSUserDefaults standardUserDefaults] volatileDomainForName:NSRegistrationDomain] objectForKey:@"rememberNum"] integerValue];
    if (Stored(@"rememberNum") != nil || [field integerValue] != registered || ![arrow isHidden])
        return Fail(121, [NSString stringWithFormat:@"after the arrow: stored %@, field %@", Stored(@"rememberNum"), [field stringValue]]);
    Emit(@{@"mode": @"restore"});
    return 0;
}

// VoiceOver names each field after its label and reads the number.
static int Names(void)
{
    for (NSString *key in Keys()) {
        NSTextField *field = Field(key);
        NSString *label = Labels()[key];
        if (![[field accessibilityLabel] isEqualToString:label] || ![[[field cell] accessibilityLabel] isEqualToString:label])
            return Fail(130, [NSString stringWithFormat:@"%@: named %@ / %@", key, [field accessibilityLabel], [[field cell] accessibilityLabel]]);
        if (![[[field accessibilityValue] description] isEqualToString:[field stringValue]])
            return Fail(131, [NSString stringWithFormat:@"%@: value %@", key, [field accessibilityValue]]);
    }
    Emit(@{@"mode": @"names"});
    return 0;
}

// Tab reaches the three fields in reading order.
static int KeyLoop(void)
{
    ChangePane(appearancePane);
    ChangePane(generalPane);
    NSMutableArray *stops = [NSMutableArray array];
    NSView *v = [[prefs tabView] nextKeyView];
    for (int i = 0; v != nil && v != [prefs tabView] && i < 500; i++, v = [v nextKeyView])
        if ([v window] == window && ![v isHiddenOrHasHiddenAncestor] && [v acceptsFirstResponder] && ![stops containsObject:v]) [stops addObject:v];
    for (NSView *stop in stops)
        if ([stop isKindOfClass:[NSStepper class]]) return Fail(142, @"a stepper is in the Tab order");
    NSUInteger last = 0;
    NSMutableArray *found = [NSMutableArray array];
    for (NSString *key in Keys()) {
        NSUInteger at = [stops indexOfObjectIdenticalTo:Field(key)];
        [found addObject:at == NSNotFound ? @"-" : @(at)];
        if (at == NSNotFound) return Fail(140, [key stringByAppendingString:@" is not in the Tab order"]);
        if (at < last) return Fail(141, @"the fields are not in reading order");
        last = at;
    }
    Emit(@{@"mode": @"key-loop", @"positions": found, @"stops": @([stops count])});
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        alerts = [[NSMutableArray alloc] init];
        if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 6;
        memorySet = method_setImplementation(class_getInstanceMethod([FCMemoryDefaults class], @selector(setObject:forKey:)), (IMP)ReportingSet);
        memoryRemove = method_setImplementation(class_getInstanceMethod([FCMemoryDefaults class], @selector(removeObjectForKey:)), (IMP)ReportingRemove);
        BeforeBuilders = RecordNib;
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(alertWithMessageText:informationText:buttonsTexts:)),
                                 (IMP)RecordAlert);
        // The width -showPreferencePanel: gives the window before it shows.
        NSRect frame = [window frame];
        if (NSWidth(frame) < 700) { frame.size.width = 720; [window setFrame:frame display:NO animate:NO]; }
        ChangePane(generalPane);
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        if ([mode isEqualToString:@"editable"]) return Editable();
        if ([mode isEqualToString:@"look"]) return Look();
        if ([mode isEqualToString:@"no-steppers"]) return NoSteppers();
        if ([mode isEqualToString:@"tooltips"]) return Tooltips();
        if ([mode isEqualToString:@"layout"]) return Layout();
        if ([mode isEqualToString:@"digits"]) return Digits();
        if ([mode hasPrefix:@"commit-"]) return CommitAtEnd([mode substringFromIndex:7]);
        if ([mode isEqualToString:@"resize-warning"]) return ResizeWarning();
        if ([mode isEqualToString:@"clamp"]) return Clamp();
        if ([mode isEqualToString:@"clamp-display"]) return ClampDisplay();
        if ([mode isEqualToString:@"escape"]) return Escape();
        if ([mode isEqualToString:@"empty"]) return Empty();
        if ([mode isEqualToString:@"restore"]) return Restore();
        if ([mode isEqualToString:@"untouched"]) return Untouched();
        if ([mode isEqualToString:@"names"]) return Names();
        if ([mode isEqualToString:@"key-loop"]) return KeyLoop();
        return 4;
    }
}
'''


class PreferencesNumberEntryRegressionTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "NumberEntry"
    EXTRA_CFLAGS = ("-DNSBeep=FCFixtureBeep",)

    def check(self, mode: str, what: str) -> None:
        self.run_mode(mode, what)

    def test_the_three_numbers_are_editable_number_fields(self) -> None:
        self.check("editable", "Remember, Display in menu or Favorites cannot be typed into")

    def test_the_fields_look_like_the_search_fields(self) -> None:
        self.check("look", "a number field is not made like Flycut's search fields")

    def test_the_steppers_are_gone(self) -> None:
        self.check("no-steppers", "a stepper is still shown, bound or in the window, or the field lost its action")

    def test_the_fields_keep_the_steppers_tooltips(self) -> None:
        self.check("tooltips", "a stepper's tooltip did not move to its field")

    def test_the_row_is_label_field_arrow_without_a_gap(self) -> None:
        self.check("layout", "the number fields do not fit three digits, or the row has a gap, moves or grows the pane")

    def test_only_up_to_three_digits_can_be_typed(self) -> None:
        self.check("digits", "a letter, sign or fourth digit reached a number field, or no beep")

    def test_return_stores_the_typed_value_only_at_the_end(self) -> None:
        self.check("commit-return", "typing stored a value before Return")

    def test_tab_stores_the_typed_value_only_at_the_end(self) -> None:
        self.check("commit-tab", "typing stored a value before Tab")

    def test_focus_loss_stores_the_typed_value_only_at_the_end(self) -> None:
        self.check("commit-focus", "typing stored a value before the field lost focus")

    def test_a_pane_change_stores_the_typed_value(self) -> None:
        self.check("commit-pane", "a pane change did not store the typed value")

    def test_closing_the_window_stores_the_typed_value(self) -> None:
        self.check("commit-close", "closing the Preferences window lost the typed value")

    def test_lowering_remember_by_typing_asks_once_and_cancel_keeps_it(self) -> None:
        self.check("resize-warning", "a typed lower Remember skipped or repeated the Resize Stack warning")

    def test_values_outside_the_limits_silently_become_the_nearest_allowed_one(self) -> None:
        self.check("clamp", "an out-of-range number was stored, or a corrected number beeped")

    def test_display_in_menu_goes_up_to_the_current_remember(self) -> None:
        self.check("clamp-display", "Display in menu went above Remember, or a correction beeped")

    def test_escape_restores_the_stored_value(self) -> None:
        self.check("escape", "Escape did not bring back the stored value")

    def test_an_emptied_field_keeps_the_stored_value(self) -> None:
        self.check("empty", "an empty field changed the stored value")

    def test_leaving_a_field_without_typing_keeps_the_stored_value(self) -> None:
        self.check("untouched", "leaving a field without typing changed or clamped the stored value")

    def test_restore_default_arrow_after_typing(self) -> None:
        self.check("restore", "the Restore Default arrow does not follow a typed value")

    def test_voiceover_names_the_fields_after_their_labels(self) -> None:
        self.check("names", "a number field has no VoiceOver name or value")

    def test_tab_reaches_the_fields_in_reading_order(self) -> None:
        self.check("key-loop", "Tab does not reach the number fields in reading order, or stops at a stepper")


if __name__ == "__main__":
    unittest.main()
