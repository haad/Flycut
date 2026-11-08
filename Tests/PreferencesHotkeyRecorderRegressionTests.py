#!/usr/bin/env python3
"""Native regression tests for the hotkey recorders in Flycut's Preferences window.

The fixture loads the production MainMenu NIB, runs the production
AppController panel builders, UKPrefsPanel and ShortcutRecorder code, and
drives them with synthesized events. Tests/Fixtures/FixtureIsolation.h keeps
user defaults in process memory; SGHotKeyCenter is replaced by a counter so
no global hotkey is registered; the window is never ordered on screen.
"""

from __future__ import annotations

import os
import pathlib
import plistlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"


def method_body(source: str, signature: str) -> str:
    """The text of one method, from its implementation signature to the matching brace."""
    start = source.index(signature + "\n{")
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1

FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "UKPrefsPanel.h"
#import "SRRecorderCell.h"
#import "SGHotKeyCenter.h"
#import "SGHotKey.h"
#import "SGKeyCombo.h"
#import "FlycutOperator.h"

@interface AppController (RecorderTesting)
- (void)buildAppearancesPreferencePanel;
- (void)buildMainHotkeyRestoreDefaultButton;
- (void)buildGeneralRestoreDefaultButtons;
- (void)loadHotkeyRecorderCombos;
- (void)updateRestoreDefaultButtons;
- (void)storeSaveLocation:(NSURL *)url forButton:(NSButton *)button;
@end

static NSUInteger bezelActions;
static IMP originalSetBezelAlpha, originalSetBezelWidth, originalSetBezelHeight;
static void CountBezelAlpha(id self, SEL cmd, id sender) { bezelActions++; ((void (*)(id, SEL, id))originalSetBezelAlpha)(self, cmd, sender); }
static void CountBezelWidth(id self, SEL cmd, id sender) { bezelActions++; ((void (*)(id, SEL, id))originalSetBezelWidth)(self, cmd, sender); }
static void CountBezelHeight(id self, SEL cmd, id sender) { bezelActions++; ((void (*)(id, SEL, id))originalSetBezelHeight)(self, cmd, sender); }

static void Noop(id self, SEL cmd) { (void)self; (void)cmd; }
static void NoopArg(id self, SEL cmd, id arg) { (void)self; (void)cmd; (void)arg; }
static NSUInteger hotKeyRegistrations;
static NSInteger lastRegisteredKeyCode = -2;
static BOOL FakeRegister(id self, SEL cmd, SGHotKey *hotKey)
{
    (void)self; (void)cmd;
    hotKeyRegistrations++;
    lastRegisteredKeyCode = [[hotKey keyCombo] keyCode];
    return YES;
}

// FCMemoryDefaults keeps the registered values in memory; production code
// reads them back as the registration domain, like from NSUserDefaults.
static NSDictionary *MemoryRegistrationDomain(id self, SEL cmd, NSString *name)
{
    (void)cmd;
    if (![name isEqualToString:NSRegistrationDomain]) return @{};
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    return [[(NSDictionary *)object_getIvar(self, ivar) copy] autorelease];
}

static NSUInteger menuUpdates;
static void CountMenuUpdate(id self, SEL cmd) { (void)self; (void)cmd; menuUpdates++; }
static id AbortSharedStore(id self, SEL cmd) { (void)self; (void)cmd; fprintf(stderr, "image store reached\n"); abort(); }

static NSWindow *window;
static UKPrefsPanel *prefs;
static AppController *controller;
static SRRecorderControl *searchRecorder;
static NSInteger generalPane, hotkeysPane, appearancePane;

static BOOL Recording(SRRecorderControl *recorder)
{
    return [[[recorder cell] valueForKey:@"isRecording"] boolValue];
}

static void ChangePane(NSInteger index)
{
    NSButton *sender = [[[NSButton alloc] init] autorelease];
    [sender setTag:index];
    [prefs changePanes:sender];
}

// A click in the field: SRRecorderCell's tracking loop handles the mouse-up.
static void Click(SRRecorderControl *recorder, CGFloat x)
{
    NSPoint point = [recorder convertPoint:NSMakePoint(x, NSMidY([recorder bounds])) toView:nil];
    NSEvent *up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:point modifierFlags:0 timestamp:0
                                 windowNumber:[window windowNumber] context:nil eventNumber:0 clickCount:1 pressure:0];
    [[recorder cell] trackMouse:up inRect:[recorder bounds] ofView:recorder untilMouseUp:YES];
}

static SRRecorderControl *mainRecorder;

static NSView *Find(NSView *root, BOOL (^match)(NSView *))
{
    if (match(root)) return root;
    for (NSView *child in [root subviews]) {
        NSView *found = Find(child, match);
        if (found) return found;
    }
    return nil;
}

static NSButton *RestoreButton(NSString *identifier)
{
    BOOL (^match)(NSView *) = ^BOOL(NSView *view) { return [[view identifier] isEqualToString:identifier]; };
    NSView *found = Find([controller valueForKey:@"appearancePanel"], match);
    if (found == nil) found = Find([mainRecorder superview], match);
    return [found isKindOfClass:[NSButton class]] ? (NSButton *)found : nil;
}

static NSSlider *SliderNextTo(NSButton *button)
{
    for (NSView *view in [[button superview] subviews])
        if ([view isKindOfClass:[NSSlider class]]) return (NSSlider *)view;
    return nil;
}

static BOOL ComboIs(SRRecorderControl *recorder, NSInteger code, NSUInteger flags)
{
    return [recorder keyCombo].code == code && [recorder keyCombo].flags == flags;
}

static const NSUInteger HotkeyModifiers = NSEventModifierFlagCommand | NSEventModifierFlagOption |
                                          NSEventModifierFlagControl | NSEventModifierFlagShift;

// The one factory-defaults table: what -init and -[FlycutOperator init] registered.
static NSDictionary *Registered(void)
{
    return [[NSUserDefaults standardUserDefaults] volatileDomainForName:NSRegistrationDomain];
}

static BOOL ComboIsRegistered(SRRecorderControl *recorder, NSString *key)
{
    NSDictionary *value = [Registered() objectForKey:key];
    if (value == nil) return [recorder keyCombo].code == -1;
    return [recorder keyCombo].code == [[value objectForKey:@"keyCode"] integerValue] &&
           ([recorder keyCombo].flags & HotkeyModifiers) == ([[value objectForKey:@"modifierFlags"] unsignedIntegerValue] & HotkeyModifiers);
}

static NSView *GeneralPane(void)
{
    return [[controller valueForKey:@"savingSectionLabel"] superview];
}

static NSButton *AnyRestoreButton(NSString *identifier)
{
    NSButton *button = RestoreButton(identifier);
    if (button == nil) {
        NSView *found = Find(GeneralPane(), ^BOOL(NSView *view) { return [[view identifier] isEqualToString:identifier]; });
        if ([found isKindOfClass:[NSButton class]]) button = (NSButton *)found;
    }
    return button;
}

// The NIB control bound to values.<key>.
static NSControl *BoundControl(NSString *key, Class kind)
{
    NSString *keyPath = [@"values." stringByAppendingString:key];
    return (NSControl *)Find(GeneralPane(), ^BOOL(NSView *view) {
        return [view isKindOfClass:kind] &&
               [[[view infoForBinding:NSValueBinding] objectForKey:NSObservedKeyPathKey] isEqualToString:keyPath];
    });
}

// What the user domain holds for a key (nil: the registered value applies).
static id Stored(NSString *key)
{
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "storedValues");
    return [(NSDictionary *)object_getIvar([NSUserDefaults standardUserDefaults], ivar) objectForKey:key];
}

static NSDictionary *GeneralLabels(void)
{
    return @{
        @"rememberNum": @"Restore default number of clippings to remember",
        @"displayNum": @"Restore default number of clippings in the menu",
        @"favoritesRememberNum": @"Restore default number of favorites to remember",
        @"skipPboardTypesList": @"Restore default pasteboard types",
        @"skipPasswordLengthsList": @"Restore default password lengths",
    };
}

static NSString *IdentifierForKey(NSString *key)
{
    return [@"restoreDefault" stringByAppendingString:[[[key substringToIndex:1] uppercaseString] stringByAppendingString:[key substringFromIndex:1]]];
}

// As a committed edit or a stepper click: through the controller the NIB binds the field to.
static void SetUserValue(NSString *key, id value)
{
    NSDictionary *binding = [BoundControl(key, [NSTextField class]) infoForBinding:NSValueBinding];
    [[binding objectForKey:NSObservedObjectKey] setValue:value forKeyPath:[binding objectForKey:NSObservedKeyPathKey]];
}

static int CheckButton(NSButton *button, NSString *identifier, NSString *label)
{
    if (button == nil) { fprintf(stderr, "missing %s\n", [identifier UTF8String]); return 50; }
    if (![[button toolTip] isEqualToString:@"Restore Default"]) return 51;
    if (![[button accessibilityLabel] isEqualToString:label]) {
        fprintf(stderr, "%s has accessibility label %s\n", [identifier UTF8String], [[button accessibilityLabel] UTF8String]);
        return 52;
    }
    if ([button isBordered] || [button image] == nil || [button target] != controller || [button action] != @selector(restoreDefault:)) return 53;
    return 0;
}

// Variant A: a Restore Default button is shown only while its value differs
// from the registered default, and puts that value back.
static int RestoreButtons(void)
{
    NSDictionary *labels = @{
        @"restoreDefaultBezelAlpha": @"Restore default bezel transparency",
        @"restoreDefaultBezelWidth": @"Restore default bezel width",
        @"restoreDefaultBezelHeight": @"Restore default bezel height",
        @"restoreDefaultSearchHotkey": @"Restore default search clipboard hotkey",
        @"restoreDefaultMainHotkey": @"Restore default main hotkey",
    };
    [controller loadHotkeyRecorderCombos];
    [controller updateRestoreDefaultButtons];
    for (NSString *identifier in labels) {
        NSButton *button = RestoreButton(identifier);
        int failed = CheckButton(button, identifier, labels[identifier]);
        if (failed) return failed;
        if (![button isHidden]) { fprintf(stderr, "%s is shown at the factory default\n", [identifier UTF8String]); return 54; }
    }

    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [mainRecorder setKeyCombo:SRMakeKeyCombo(9, NSEventModifierFlagCommand | NSEventModifierFlagOption)];
    [searchRecorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)];
    NSDictionary *custom = @{@"restoreDefaultBezelAlpha": @0.6, @"restoreDefaultBezelWidth": @700.0, @"restoreDefaultBezelHeight": @400.0};
    NSDictionary *keys = @{@"restoreDefaultBezelAlpha": @"bezelAlpha", @"restoreDefaultBezelWidth": @"bezelWidth", @"restoreDefaultBezelHeight": @"bezelHeight"};
    for (NSString *identifier in custom) {
        [defaults setObject:custom[identifier] forKey:keys[identifier]];
        [SliderNextTo(RestoreButton(identifier)) setDoubleValue:[custom[identifier] doubleValue]];
    }
    [controller updateRestoreDefaultButtons];
    for (NSString *identifier in labels) {
        NSButton *button = RestoreButton(identifier);
        if ([button isHidden] || ![button isEnabled]) { fprintf(stderr, "%s is not offered for a custom value\n", [identifier UTF8String]); return 55; }
    }

    [RestoreButton(@"restoreDefaultMainHotkey") performClick:nil];
    if (!ComboIsRegistered(mainRecorder, @"ShortcutRecorder mainHotkey")) return 56;
    if ([[[defaults dictionaryForKey:@"ShortcutRecorder mainHotkey"] objectForKey:@"keyCode"] integerValue] !=
        [[[Registered() objectForKey:@"ShortcutRecorder mainHotkey"] objectForKey:@"keyCode"] integerValue]) return 57;
    [RestoreButton(@"restoreDefaultSearchHotkey") performClick:nil];
    if (!ComboIsRegistered(searchRecorder, @"ShortcutRecorder searchHotkey")) return 58;
    for (NSString *identifier in custom) {
        NSButton *button = RestoreButton(identifier);
        NSUInteger before = bezelActions;
        [button performClick:nil];
        double expected = [[Registered() objectForKey:keys[identifier]] doubleValue];
        if (fabs([defaults doubleForKey:keys[identifier]] - expected) > 0.0001) return 60;
        if (fabs([SliderNextTo(button) doubleValue] - expected) > 0.0001) return 61;
        if (bezelActions != before + 1) { fprintf(stderr, "%s did not apply the default to the bezel\n", [identifier UTF8String]); return 62; }
    }
    for (NSString *identifier in labels)
        if (![RestoreButton(identifier) isHidden]) { fprintf(stderr, "%s still shown after restoring\n", [identifier UTF8String]); return 63; }
    return 0;
}

// The buttons read the registration domain when clicked: a different table
// gives a different result, so no second copy of the defaults exists.
static int RegisteredTable(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    NSDictionary *table = @{
        @"ShortcutRecorder mainHotkey": @{@"keyCode": @11, @"modifierFlags": @(NSEventModifierFlagCommand | NSEventModifierFlagControl)},
        @"ShortcutRecorder searchHotkey": @{@"keyCode": @5, @"modifierFlags": @(NSEventModifierFlagControl | NSEventModifierFlagOption)},
        @"bezelWidth": @777.0, @"rememberNum": @55, @"displayNum": @7, @"favoritesRememberNum": @33,
        @"skipPboardTypesList": @"org.example.Secret", @"skipPasswordLengthsList": @"8, 9",
    };
    [defaults registerDefaults:table];
    [mainRecorder setKeyCombo:SRMakeKeyCombo(9, NSEventModifierFlagCommand | NSEventModifierFlagShift)];
    [searchRecorder setKeyCombo:SRMakeKeyCombo(1, NSEventModifierFlagControl | NSEventModifierFlagShift)];
    [defaults setObject:@500.0 forKey:@"bezelWidth"];
    [SliderNextTo(RestoreButton(@"restoreDefaultBezelWidth")) setDoubleValue:500.0];
    for (NSString *key in @[@"rememberNum", @"displayNum", @"favoritesRememberNum"]) SetUserValue(key, @40);
    SetUserValue(@"skipPboardTypesList", @"PasswordPboardType");
    SetUserValue(@"skipPasswordLengthsList", @"12, 20, 32");
    [controller updateRestoreDefaultButtons];
    NSArray *identifiers = @[@"restoreDefaultMainHotkey", @"restoreDefaultSearchHotkey", @"restoreDefaultBezelWidth",
                             IdentifierForKey(@"rememberNum"), IdentifierForKey(@"displayNum"), IdentifierForKey(@"favoritesRememberNum"),
                             IdentifierForKey(@"skipPboardTypesList"), IdentifierForKey(@"skipPasswordLengthsList")];
    for (NSString *identifier in identifiers) {
        NSButton *button = AnyRestoreButton(identifier);
        if (button == nil || [button isHidden]) { fprintf(stderr, "%s not offered against the new table\n", [identifier UTF8String]); return 80; }
        [button performClick:nil];
    }
    if ([mainRecorder keyCombo].code != 11 || ([mainRecorder keyCombo].flags & HotkeyModifiers) != (NSEventModifierFlagCommand | NSEventModifierFlagControl)) return 81;
    if ([searchRecorder keyCombo].code != 5 || ([searchRecorder keyCombo].flags & HotkeyModifiers) != (NSEventModifierFlagControl | NSEventModifierFlagOption)) return 82;
    if (fabs([defaults doubleForKey:@"bezelWidth"] - 777.0) > 0.001) return 83;
    for (NSString *key in @[@"rememberNum", @"displayNum", @"favoritesRememberNum", @"skipPboardTypesList", @"skipPasswordLengthsList"]) {
        if (![[[defaults objectForKey:key] description] isEqualToString:[table[key] description]]) {
            fprintf(stderr, "%s restored to %s, registered %s\n", [key UTF8String], [[[defaults objectForKey:key] description] UTF8String],
                    [[table[key] description] UTF8String]);
            return 84;
        }
    }
    for (NSString *identifier in identifiers)
        if (![AnyRestoreButton(identifier) isHidden]) { fprintf(stderr, "%s still shown\n", [identifier UTF8String]); return 85; }
    return 0;
}

static int SearchDefault(void)
{
    if (![controller respondsToSelector:@selector(loadHotkeyRecorderCombos)]) return 5;
    [controller loadHotkeyRecorderCombos];
    if (!ComboIsRegistered(searchRecorder, @"ShortcutRecorder searchHotkey")) return 65;
    if (![RestoreButton(@"restoreDefaultSearchHotkey") isHidden]) return 64;
    return 0;
}

// Without a registered search default (an older build's table) "default"
// means no shortcut: the arrow clears a custom one.
static int NoSearchDefault(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Ivar ivar = class_getInstanceVariable([FCMemoryDefaults class], "registeredValues");
    [(NSMutableDictionary *)object_getIvar(defaults, ivar) removeObjectForKey:@"ShortcutRecorder searchHotkey"];
    [searchRecorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)];
    [controller updateRestoreDefaultButtons];
    NSButton *button = RestoreButton(@"restoreDefaultSearchHotkey");
    if ([button isHidden]) return 86;
    [button performClick:nil];
    if ([searchRecorder keyCombo].code != -1) return 87;
    if (![button isHidden]) return 88;
    return 0;
}

// What a control draws: a checkbox or radio button only as wide as its box
// and title, not its whole (often pane-wide) frame; a borderless image button
// (a Restore Default arrow) only its alignment rect, not the inset frame
// Auto Layout gives it.
static NSRect DrawnRect(NSView *view)
{
    NSRect frame = [view frame];
    if ([view isKindOfClass:[NSButton class]] && ![(NSButton *)view isBordered] && [(NSButton *)view imagePosition] == NSImageOnly)
        return [view alignmentRectForFrame:frame];
    if ([view isKindOfClass:[NSButton class]] && [[(NSButton *)view title] length] > 0)
        frame.size.width = MIN(NSWidth(frame), ceil([view fittingSize].width));
    return frame;
}

static BOOL Overlaps(NSView *view, NSView *pane)
{
    NSRect frame = [view superview] == pane ? DrawnRect(view) : [view convertRect:[view bounds] toView:pane];
    for (NSView *other in [pane subviews]) {
        if (other == view || [other isHidden] || [view isDescendantOf:other]) continue;
        if (NSIntersectsRect(NSInsetRect(frame, 0.5, 0.5), DrawnRect(other))) {
            fprintf(stderr, "%s %s overlaps %s %s\n", [[view identifier] UTF8String], [NSStringFromRect(frame) UTF8String],
                    [NSStringFromClass([other class]) UTF8String], [NSStringFromRect(DrawnRect(other)) UTF8String]);
            return YES;
        }
    }
    return NO;
}

// Every General setting with a meaningful factory value gets an arrow next to
// its own control, inside the pane, centred on the field, overlapping nothing.
static int GeneralButtons(void)
{
    NSView *pane = GeneralPane();
    if (pane == nil) return 90;
    [controller updateRestoreDefaultButtons];
    NSDictionary *labels = GeneralLabels();
    for (NSString *key in labels) {
        NSString *identifier = IdentifierForKey(key);
        NSButton *button = AnyRestoreButton(identifier);
        int failed = CheckButton(button, identifier, labels[key]);
        if (failed) return failed;
        if (![button isHidden]) { fprintf(stderr, "%s is shown at the factory default\n", [identifier UTF8String]); return 91; }
        NSTextField *field = (NSTextField *)BoundControl(key, [NSTextField class]);
        NSStepper *stepper = (NSStepper *)BoundControl(key, [NSStepper class]);
        if (field == nil) { fprintf(stderr, "no field bound to %s\n", [key UTF8String]); return 92; }
        NSView *anchor = stepper ?: field;
        NSRect frame = [button convertRect:[button bounds] toView:pane];
        if (!NSContainsRect([pane bounds], frame) || NSMinX(frame) < NSMaxX([anchor frame]) ||
            NSMinX(frame) > NSMaxX([anchor frame]) + 8 || fabs(NSMidY(frame) - NSMidY([field frame])) > 1.0) {
            fprintf(stderr, "%s at %s, field %s, anchor %s\n", [identifier UTF8String], [NSStringFromRect(frame) UTF8String],
                    [NSStringFromRect([field frame]) UTF8String], [NSStringFromRect([anchor frame]) UTF8String]);
            return 93;
        }
        [button setHidden:NO];
        BOOL overlap = Overlaps(button, pane);
        [button setHidden:YES];
        if (overlap) return 94;
    }
    // The NIB controls that made room still fit and overlap nothing.
    for (NSView *view in [pane subviews]) {
        if ([view isHidden]) continue;
        if (!NSContainsRect([pane bounds], [view frame])) {
            fprintf(stderr, "%s %s leaves the pane\n", [NSStringFromClass([view class]) UTF8String], [NSStringFromRect([view frame]) UTF8String]);
            return 95;
        }
    }
    return 0;
}

static NSText *Edit(NSTextField *field, NSString *text)
{
    if (![window makeFirstResponder:field]) return nil;
    NSTextView *editor = (NSTextView *)[field currentEditor];
    [editor selectAll:nil];
    [editor insertText:text replacementRange:[editor selectedRange]];
    return editor;
}

// The arrow follows the value while it changes: typing, stepping.
static int GeneralLive(void)
{
    NSTextField *lengths = (NSTextField *)BoundControl(@"skipPasswordLengthsList", [NSTextField class]);
    NSButton *lengthsButton = AnyRestoreButton(IdentifierForKey(@"skipPasswordLengthsList"));
    NSString *registered = [Registered() objectForKey:@"skipPasswordLengthsList"];
    if (lengths == nil || lengthsButton == nil || registered == nil) return 100;
    if (Edit(lengths, @"12, 20") == nil) return 101;
    if ([lengthsButton isHidden]) { fprintf(stderr, "typing a custom value does not show the arrow\n"); return 102; }
    Edit(lengths, registered);
    if (![lengthsButton isHidden]) { fprintf(stderr, "typing the default back does not hide the arrow\n"); return 103; }
    Edit(lengths, @"12,20,32");
    if (![lengthsButton isHidden]) { fprintf(stderr, "the same lengths without spaces count as custom\n"); return 104; }
    [window makeFirstResponder:nil];

    NSStepper *stepper = (NSStepper *)BoundControl(@"displayNum", [NSStepper class]);
    NSButton *displayButton = AnyRestoreButton(IdentifierForKey(@"displayNum"));
    NSInteger value = [[Registered() objectForKey:@"displayNum"] integerValue];
    [stepper setIntegerValue:value + 1];
    [stepper sendAction:[stepper action] to:[stepper target]];
    if ([displayButton isHidden]) {
        fprintf(stderr, "stepping does not show the arrow: stepper %ld stored %s\n", (long)[stepper integerValue],
                [[[[NSUserDefaults standardUserDefaults] objectForKey:@"displayNum"] description] UTF8String]);
        return 105;
    }
    [stepper setIntegerValue:value];
    [stepper sendAction:[stepper action] to:[stepper target]];
    if (![displayButton isHidden]) { fprintf(stderr, "stepping back does not hide the arrow\n"); return 106; }
    return 0;
}

@interface FCRememberOperator : NSObject {
@public
    int remember, favoritesRemember, count, warnings;
    BOOL favorites;
    NSString *choice;
    NSMutableArray *calls;
}
@end

@implementation FCRememberOperator
- (int)rememberNum { return favorites ? favoritesRemember : remember; }
- (int)jcListCount { return count; }
- (void)switchToFavoritesStore { favorites = YES; [calls addObject:@"switchToFavoritesStore"]; }
- (void)restoreStashedStore { favorites = NO; [calls addObject:@"restoreStashedStore"]; }
// The contract of -[FlycutOperator setRememberNum:forPrimaryStore:]: shrinking
// below the stored clippings asks first; Cancel writes the old value back.
- (int)setRememberNum:(int)value forPrimaryStore:(BOOL)primary
{
    (void)primary;
    [calls addObject:[NSString stringWithFormat:@"setRememberNum:%d", value]];
    int old = [self rememberNum];
    if (value < count) {
        warnings++;
        if ([choice isEqualToString:@"Cancel"]) {
            [[NSUserDefaults standardUserDefaults] setObject:@(old) forKey:favorites ? @"favoritesRememberNum" : @"rememberNum"];
            return old;
        }
    }
    if (favorites) favoritesRemember = value; else remember = value;
    return value;
}
@end

static FCRememberOperator *Operator(int remember, int count, NSString *choice)
{
    FCRememberOperator *op = [[[FCRememberOperator alloc] init] autorelease];
    op->remember = remember; op->favoritesRemember = remember; op->count = count; op->choice = choice;
    op->calls = [NSMutableArray array];
    [controller setValue:op forKey:@"flycutOperator"];
    return op;
}

// Every General arrow restores the registered value; the remember limits go
// through the operator's resize path like a stepper change.
static int GeneralRestore(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    FCRememberOperator *op = Operator(80, 60, @"Resize");
    NSDictionary *custom = @{@"rememberNum": @80, @"displayNum": @12, @"favoritesRememberNum": @80,
                             @"skipPboardTypesList": @"PasswordPboardType", @"skipPasswordLengthsList": @"12, 20"};
    for (NSString *key in custom) SetUserValue(key, custom[key]);
    [controller updateRestoreDefaultButtons];
    for (NSString *key in custom) {
        NSButton *button = AnyRestoreButton(IdentifierForKey(key));
        if ([button isHidden] || ![button isEnabled]) { fprintf(stderr, "%s not offered for a custom value\n", [key UTF8String]); return 110; }
        [button performClick:nil];
        id registered = [Registered() objectForKey:key];
        if (![[[defaults objectForKey:key] description] isEqualToString:[registered description]]) {
            fprintf(stderr, "%s restored to %s, registered %s\n", [key UTF8String], [[[defaults objectForKey:key] description] UTF8String],
                    [[registered description] UTF8String]);
            return 111;
        }
        NSTextField *field = (NSTextField *)BoundControl(key, [NSTextField class]);
        if (![[field stringValue] isEqualToString:[registered description]]) {
            fprintf(stderr, "%s field shows %s\n", [key UTF8String], [[field stringValue] UTF8String]);
            return 112;
        }
        if (![button isHidden]) return 113;
    }
    NSString *remember = [NSString stringWithFormat:@"setRememberNum:%ld", (long)[[Registered() objectForKey:@"rememberNum"] integerValue]];
    NSString *favorites = [NSString stringWithFormat:@"setRememberNum:%ld", (long)[[Registered() objectForKey:@"favoritesRememberNum"] integerValue]];
    NSUInteger at = [op->calls indexOfObject:@"switchToFavoritesStore"];
    if (![op->calls containsObject:remember] || at == NSNotFound || at + 2 >= [op->calls count] ||
        ![[op->calls objectAtIndex:at + 1] isEqualToString:favorites] ||
        ![[op->calls objectAtIndex:at + 2] isEqualToString:@"restoreStashedStore"]) {
        fprintf(stderr, "operator calls %s\n", [[op->calls description] UTF8String]);
        return 114;
    }
    if (op->warnings != 2) { fprintf(stderr, "%d resize warnings for two shrinking limits\n", op->warnings); return 115; }
    return 0;
}

// Cancel in the resize warning keeps the limit and the clippings.
static int RememberCancel(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    FCRememberOperator *op = Operator(80, 60, @"Cancel");
    SetUserValue(@"rememberNum", @80);
    [controller updateRestoreDefaultButtons];
    NSButton *button = AnyRestoreButton(IdentifierForKey(@"rememberNum"));
    [button performClick:nil];
    if (op->warnings != 1) return 120;
    if ([defaults integerForKey:@"rememberNum"] != 80 || op->remember != 80) {
        fprintf(stderr, "Cancel left rememberNum %ld, operator %d\n", (long)[defaults integerForKey:@"rememberNum"], op->remember);
        return 121;
    }
    if ([button isHidden]) { fprintf(stderr, "the arrow hid although the custom limit stayed\n"); return 122; }
    return 0;
}

// The Hotkeys pane's help text says what the arrow next to the recorder does,
// and still fits next to it.
static int HelpText(void)
{
    NSView *pane = [mainRecorder superview];
    NSButton *button = RestoreButton(@"restoreDefaultMainHotkey");
    NSTextField *help = nil;
    for (NSView *view in [pane subviews])
        if ([view isKindOfClass:[NSTextField class]] && NSMinX([view frame]) > NSMaxX([mainRecorder frame])) help = (NSTextField *)view;
    if (help == nil || button == nil) return 130;
    NSString *text = [help stringValue];
    if ([text rangeOfString:@"arrow"].location == NSNotFound || [text rangeOfString:@"default"].location == NSNotFound) {
        fprintf(stderr, "help text: %s\n", [text UTF8String]);
        return 131;
    }
    if ([text rangeOfString:@"\"X\""].location == NSNotFound) return 132;
    NSSize needed = [[help cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth([help frame]), CGFLOAT_MAX)];
    if (ceil(needed.height) > NSHeight([help frame]) + 0.5) {
        fprintf(stderr, "help text needs %.1f, has %.1f\n", needed.height, NSHeight([help frame]));
        return 133;
    }
    if (!NSContainsRect([pane bounds], [help frame]) || NSIntersectsRect([help frame], [button frame]) ||
        NSMinX([help frame]) < NSMaxX([button frame]) + 4) {
        fprintf(stderr, "help %s button %s pane %s\n", [NSStringFromRect([help frame]) UTF8String],
                [NSStringFromRect([button frame]) UTF8String], [NSStringFromRect([pane bounds]) UTF8String]);
        return 134;
    }
    return 0;
}

static int NoSnapback(void)
{
    [searchRecorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)];
    Click(searchRecorder, 40);
    if (!Recording(searchRecorder)) return 66;
    // Where the old snapback arrow was: a click there no longer cancels.
    Click(searchRecorder, NSMaxX([searchRecorder bounds]) - 8);
    if (!Recording(searchRecorder)) { fprintf(stderr, "a click on the right end still cancels the recording\n"); return 67; }
    NSEvent *escape = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
                                   windowNumber:[window windowNumber] context:nil characters:@"\x1b"
                    charactersIgnoringModifiers:@"\x1b" isARepeat:NO keyCode:53];
    [searchRecorder keyDown:escape];
    if (Recording(searchRecorder)) { fprintf(stderr, "Escape does not cancel the recording\n"); return 68; }
    if (!ComboIs(searchRecorder, 11, NSEventModifierFlagControl | NSEventModifierFlagCommand)) return 69;
    return 0;
}

static int LabelCentred(void)
{
    NSView *label = Find([controller valueForKey:@"appearancePanel"], ^BOOL(NSView *view) {
        return [view isKindOfClass:[NSTextField class]] && [[(NSTextField *)view stringValue] isEqualToString:@"Search clipboard hotkey:"];
    });
    if (label == nil || [label superview] != [searchRecorder superview]) return 70;
    if (fabs(NSMidY([label frame]) - NSMidY([searchRecorder frame])) > 1.0) {
        fprintf(stderr, "label %s is not centred on the recorder %s\n", [NSStringFromRect([label frame]) UTF8String],
                [NSStringFromRect([searchRecorder frame]) UTF8String]);
        return 71;
    }
    NSButton *reset = RestoreButton(@"restoreDefaultSearchHotkey");
    if (reset == nil || fabs(NSMidY([reset frame]) - NSMidY([searchRecorder frame])) > 1.0 ||
        NSMinX([reset frame]) < NSMaxX([searchRecorder frame]) ||
        !NSContainsRect([[reset superview] bounds], [reset frame])) return 72;
    return 0;
}

// Mean brightness of the field's middle, away from its border and text.
static double FieldBrightness(SRRecorderControl *recorder, CGFloat x)
{
    [recorder setNeedsDisplay:YES];
    NSBitmapImageRep *rep = [recorder bitmapImageRepForCachingDisplayInRect:[recorder bounds]];
    [recorder cacheDisplayInRect:[recorder bounds] toBitmapImageRep:rep];
    CGFloat scale = [rep pixelsWide] / NSWidth([recorder bounds]);
    double sum = 0; int count = 0;
    for (NSInteger dy = -2; dy <= 2; dy++) {
        NSColor *c = [[rep colorAtX:(NSInteger)(x * scale) y:[rep pixelsHigh] / 2 + dy] colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
        sum += 0.2126 * [c redComponent] + 0.7152 * [c greenComponent] + 0.0722 * [c blueComponent];
        count++;
    }
    return sum / count;
}

// In Dark Mode the field follows the system colors like a text field.
static int DarkField(void)
{
    [window setAppearance:[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua]];
    [searchRecorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)];
    double idle = FieldBrightness(searchRecorder, 24);
    if (idle > 0.5) { fprintf(stderr, "idle field is light in Dark Mode: %.2f\n", idle); return 73; }
    [window setAppearance:[NSAppearance appearanceNamed:NSAppearanceNameAqua]];
    double light = FieldBrightness(searchRecorder, 24);
    if (light < 0.9) { fprintf(stderr, "idle field is not light in Light Mode: %.2f\n", light); return 74; }
    return 0;
}

static int PaneSwitch(void)
{
    Click(searchRecorder, 40);
    if (!Recording(searchRecorder) || [window firstResponder] != searchRecorder) {
        fprintf(stderr, "precondition: a click did not start recording\n");
        return 40;
    }
    ChangePane(hotkeysPane);
    ChangePane(appearancePane);
    if (Recording(searchRecorder)) {
        fprintf(stderr, "the recorder is still recording after the pane switch\n");
        return 41;
    }
    if ([window firstResponder] == searchRecorder) {
        fprintf(stderr, "the pane switch gave keyboard focus back to the recorder, unseen\n");
        return 42;
    }
    return 0;
}

static int FocusRing(void)
{
    if (![window makeFirstResponder:searchRecorder]) return 43;
    if (!NSEqualRects([searchRecorder focusRingMaskBounds], [searchRecorder bounds])) {
        fprintf(stderr, "a focused recorder has no focus ring outline: mask=%s bounds=%s\n",
                [NSStringFromRect([searchRecorder focusRingMaskBounds]) UTF8String],
                [NSStringFromRect([searchRecorder bounds]) UTF8String]);
        return 44;
    }
    NSEvent *space = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
                                  windowNumber:[window windowNumber] context:nil characters:@" "
                   charactersIgnoringModifiers:@" " isARepeat:NO keyCode:49];
    [searchRecorder keyDown:space];
    if (!Recording(searchRecorder)) return 45;
    if (!NSIsEmptyRect([searchRecorder focusRingMaskBounds])) {
        fprintf(stderr, "the recording look and a focus ring are drawn together\n");
        return 46;
    }
    return 0;
}

// A pane switch first ends editing. A field that refuses (its value does not
// validate) keeps the window on its pane and the toolbar on that pane's item;
// nothing is ended half-way. Once it lets go, the switch happens.
@interface FCRefusingFieldDelegate : NSObject <NSTextFieldDelegate> {
@public
    BOOL refuse;
}
@end
@implementation FCRefusingFieldDelegate
- (BOOL)control:(NSControl *)control textShouldEndEditing:(NSText *)fieldEditor { (void)control; (void)fieldEditor; return !refuse; }
@end

static int PaneSwitchRefused(void)
{
    NSTabView *tabs = [prefs tabView];
    NSView *content = [[controller valueForKey:@"appearancePanel"] contentView];
    NSTextField *field = [[[NSTextField alloc] initWithFrame:NSMakeRect(8, 8, 120, 22)] autorelease];
    FCRefusingFieldDelegate *delegate = [[[FCRefusingFieldDelegate alloc] init] autorelease];
    delegate->refuse = YES;
    [field setDelegate:delegate];
    [content addSubview:field];
    if (![window makeFirstResponder:field]) return 170;
    [(NSTextView *)[field currentEditor] insertText:@"not valid" replacementRange:NSMakeRange(0, 0)];
    ChangePane(hotkeysPane);
    if ([tabs indexOfTabViewItem:[tabs selectedTabViewItem]] != appearancePane) {
        fprintf(stderr, "the pane changed although the field refused to end editing\\n");
        return 171;
    }
    NSToolbar *toolbar = [window toolbar];
    if (toolbar != nil && ![[toolbar selectedItemIdentifier] isEqual:[[tabs tabViewItemAtIndex:appearancePane] identifier]]) {
        fprintf(stderr, "the toolbar shows %s\\n", [[[toolbar selectedItemIdentifier] description] UTF8String]);
        return 172;
    }
    if ([field currentEditor] == nil) return 173;
    delegate->refuse = NO;
    ChangePane(hotkeysPane);
    if ([tabs indexOfTabViewItem:[tabs selectedTabViewItem]] != hotkeysPane || [field currentEditor] != nil) return 174;
    [field setDelegate:nil];
    return 0;
}

// Every arrow is one gap right of its control, and the arrows of a pane line
// up: on Appearance one column for sliders and the search hotkey, ending at
// the rows' inset (where the menu bar colour row ends, too); on General the
// arrows that end a line share one column, and so do the two folder arrows.
static const CGFloat ArrowGap = 4.0;

static NSRect FrameIn(NSView *view, NSView *reference)
{
    return [view convertRect:[view bounds] toView:reference];
}

static BOOL Same(CGFloat a, CGFloat b) { return fabs(a - b) <= 0.5; }

static int ArrowColumns(void)
{
    NSBox *panel = [controller valueForKey:@"appearancePanel"];
    NSView *content = [panel contentView];
    NSButton *search = RestoreButton(@"restoreDefaultSearchHotkey");
    NSArray *ids = @[@"restoreDefaultBezelAlpha", @"restoreDefaultBezelWidth", @"restoreDefaultBezelHeight", @"restoreDefaultSearchHotkey"];
    NSRect first = FrameIn(RestoreButton(ids[0]), content);
    for (NSString *identifier in ids) {
        NSButton *button = RestoreButton(identifier);
        if (button == nil) return 140;
        NSRect frame = FrameIn(button, content);
        NSView *control = button == search ? (NSView *)searchRecorder : (NSView *)SliderNextTo(button);
        NSRect controlFrame = FrameIn(control, content);
        if (!Same(NSMinX(frame), NSMinX(first)) || !Same(NSMaxX(frame), NSMaxX(first))) {
            fprintf(stderr, "Appearance: %s at %s, %s at %s\\n", [identifier UTF8String], [NSStringFromRect(frame) UTF8String],
                    [ids[0] UTF8String], [NSStringFromRect(first) UTF8String]);
            return 141;
        }
        if (!Same(NSMinX(frame) - NSMaxX(controlFrame), ArrowGap)) {
            fprintf(stderr, "Appearance: %s %s is not %.0f pt right of its control %s\\n", [identifier UTF8String],
                    [NSStringFromRect(frame) UTF8String], ArrowGap, [NSStringFromRect(controlFrame) UTF8String]);
            return 142;
        }
    }
    // The column ends as far from the row's right edge as the row labels start from its left edge.
    NSView *label = Find(panel, ^BOOL(NSView *view) {
        return [view isKindOfClass:[NSTextField class]] && [[(NSTextField *)view stringValue] isEqualToString:@"Bezel width"];
    });
    NSButton *width = RestoreButton(@"restoreDefaultBezelWidth");
    if (label == nil || [label superview] != [width superview]) return 143;
    if (!Same(NSWidth([[label superview] bounds]) - NSMaxX([width frame]), NSMinX([label frame]))) {
        fprintf(stderr, "Appearance: the arrow column ends at %.1f of %.1f, the labels start at %.1f\\n", NSMaxX([width frame]),
                NSWidth([[label superview] bounds]), NSMinX([label frame]));
        return 144;
    }
    // With the menu bar colour row (#20), that row ends at the column's right edge.
    NSView *paused = Find(panel, ^BOOL(NSView *view) { return [[view identifier] isEqualToString:@"menuIconPausedPreview"]; });
    if (paused != nil && !Same(NSMaxX(FrameIn(paused, content)), NSMaxX(first))) {
        fprintf(stderr, "Appearance: the colour row ends at %.1f, the arrow column at %.1f\\n", NSMaxX(FrameIn(paused, content)), NSMaxX(first));
        return 145;
    }

    // Hotkeys: the same gap.
    NSButton *main = RestoreButton(@"restoreDefaultMainHotkey");
    if (main == nil || !Same(NSMinX([main frame]) - NSMaxX([mainRecorder frame]), ArrowGap)) return 146;

    // General.
    NSView *pane = GeneralPane();
    NSDictionary *anchors = @{
        @"rememberNum": BoundControl(@"rememberNum", [NSStepper class]),
        @"displayNum": BoundControl(@"displayNum", [NSStepper class]),
        @"favoritesRememberNum": BoundControl(@"favoritesRememberNum", [NSStepper class]),
        @"skipPboardTypesList": BoundControl(@"skipPboardTypesList", [NSTextField class]),
        @"skipPasswordLengthsList": BoundControl(@"skipPasswordLengthsList", [NSTextField class]),
        @"saveToLocation": [controller valueForKey:@"saveToLocationButton"],
        @"autoSaveToLocation": [controller valueForKey:@"autoSaveToLocationButton"],
    };
    for (NSString *key in anchors) {
        NSButton *button = AnyRestoreButton(IdentifierForKey(key));
        if (button == nil) { fprintf(stderr, "General: no arrow for %s\\n", [key UTF8String]); return 147; }
        // Auto Layout places alignment rects; frames may differ by a fraction of a point.
        NSRect frame = FrameIn(button, pane), anchor = FrameIn(anchors[key], pane);
        if (fabs(NSMinX(frame) - NSMaxX(anchor) - ArrowGap) > 1.0 || fabs(NSMidY(frame) - NSMidY(anchor)) > 1.0) {
            fprintf(stderr, "General: %s arrow %s, its control %s\\n", [key UTF8String], [NSStringFromRect(frame) UTF8String],
                    [NSStringFromRect(anchor) UTF8String]);
            return 148;
        }
    }
    NSArray *lineEnds = @[@"favoritesRememberNum", @"skipPboardTypesList", @"skipPasswordLengthsList"];
    CGFloat column = NSMinX(FrameIn(AnyRestoreButton(IdentifierForKey(lineEnds[0])), pane));
    for (NSString *key in lineEnds) {
        CGFloat x = NSMinX(FrameIn(AnyRestoreButton(IdentifierForKey(key)), pane));
        if (!Same(x, column)) {
            fprintf(stderr, "General: the %s arrow starts at %.1f, the %s arrow at %.1f\\n", [key UTF8String], x,
                    [lineEnds[0] UTF8String], column);
            return 149;
        }
    }
    CGFloat folders = NSMinX(FrameIn(AnyRestoreButton(IdentifierForKey(@"saveToLocation")), pane));
    if (!Same(NSMinX(FrameIn(AnyRestoreButton(IdentifierForKey(@"autoSaveToLocation")), pane)), folders)) {
        fprintf(stderr, "General: the two folder arrows are not in one column\\n");
        return 150;
    }
    return 0;
}

// Both hotkey fields say what they are and how to use them.
static int RecorderAccessibility(void)
{
    NSDictionary *labels = @{@"Search clipboard hotkey": searchRecorder, @"Main hotkey": mainRecorder};
    for (NSString *label in labels) {
        SRRecorderControl *recorder = labels[label];
        if (![[recorder accessibilityLabel] isEqualToString:label]) {
            fprintf(stderr, "recorder label %s, expected %s\\n", [[recorder accessibilityLabel] UTF8String], [label UTF8String]);
            return 180;
        }
        if ([[recorder accessibilityHelp] length] == 0) { fprintf(stderr, "%s has no accessibility help\\n", [label UTF8String]); return 181; }
        if (![recorder isAccessibilityElement]) { fprintf(stderr, "%s is no accessibility element\\n", [label UTF8String]); return 182; }
    }
    return 0;
}

// The arrow follows a recording at once: it appears when a shortcut is
// recorded, stays when the X clears it (no shortcut is not the default) and
// goes when the arrow restores the default.
static int LiveArrow(void)
{
    [controller loadHotkeyRecorderCombos];
    [controller updateRestoreDefaultButtons];
    NSButton *arrow = RestoreButton(@"restoreDefaultSearchHotkey");
    if (arrow == nil || ![arrow isHidden]) return 160;
    Click(searchRecorder, 40);
    if (!Recording(searchRecorder)) return 161;
    NSEventModifierFlags flags = NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand;
    NSEvent *combo = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0
                                  windowNumber:[window windowNumber] context:nil characters:@"g"
                   charactersIgnoringModifiers:@"g" isARepeat:NO keyCode:5];
    [searchRecorder performKeyEquivalent:combo];
    if (Recording(searchRecorder) || [searchRecorder keyCombo].code != 5) return 162;
    if ([arrow isHidden]) { fprintf(stderr, "recording a shortcut does not show the arrow\\n"); return 163; }
    // The X badge: SRRecorderCell clears through -setKeyCombo: with the empty combination.
    NSRect badge = ((NSRect (*)(id, SEL, NSRect))objc_msgSend)([searchRecorder cell], NSSelectorFromString(@"_removeButtonRectForFrame:"), [searchRecorder bounds]);
    if (NSWidth(badge) > 0)
        Click(searchRecorder, NSMidX(badge));
    else
        [searchRecorder setKeyCombo:SRMakeKeyCombo(ShortcutRecorderEmptyCode, ShortcutRecorderEmptyFlags)];
    if ([searchRecorder keyCombo].code != ShortcutRecorderEmptyCode) return 164;
    BOOL registered = [Registered() objectForKey:@"ShortcutRecorder searchHotkey"] != nil;
    if (registered && [arrow isHidden]) { fprintf(stderr, "clearing the shortcut hides the arrow\\n"); return 165; }
    [arrow performClick:nil];
    if (![arrow isHidden] || !ComboIsRegistered(searchRecorder, @"ShortcutRecorder searchHotkey")) return 166;
    return 0;
}

// Restoring drops the stored value, so the registered default applies again
// (sliders, hotkeys, General fields); hotkeys are registered again at once.
static int RestoreRemoves(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    NSDictionary *sliders = @{@"restoreDefaultBezelAlpha": @"bezelAlpha", @"restoreDefaultBezelWidth": @"bezelWidth", @"restoreDefaultBezelHeight": @"bezelHeight"};
    for (NSString *identifier in sliders) {
        NSString *key = sliders[identifier];
        NSSlider *slider = SliderNextTo(RestoreButton(identifier));
        [slider setDoubleValue:([slider minValue] + [slider maxValue]) / 2];
        [slider sendAction:[slider action] to:[slider target]];
        if (Stored(key) == nil) return 190;  // precondition: the slider stored a custom value
        [RestoreButton(identifier) performClick:nil];
        if (Stored(key) != nil) { fprintf(stderr, "%s still stored after restoring: %s\\n", [key UTF8String], [[Stored(key) description] UTF8String]); return 191; }
    }

    NSDictionary *hotkeys = @{@"restoreDefaultMainHotkey": @"ShortcutRecorder mainHotkey", @"restoreDefaultSearchHotkey": @"ShortcutRecorder searchHotkey"};
    for (NSString *identifier in hotkeys) {
        NSString *key = hotkeys[identifier];
        SRRecorderControl *recorder = [identifier isEqualToString:@"restoreDefaultMainHotkey"] ? mainRecorder : searchRecorder;
        [recorder setKeyCombo:SRMakeKeyCombo(11, NSEventModifierFlagControl | NSEventModifierFlagCommand)];
        if (Stored(key) == nil) return 192;
        NSUInteger before = hotKeyRegistrations;
        [RestoreButton(identifier) performClick:nil];
        if (Stored(key) != nil) { fprintf(stderr, "%s still stored after restoring: %s\\n", [key UTF8String], [[Stored(key) description] UTF8String]); return 193; }
        NSInteger code = [[[Registered() objectForKey:key] objectForKey:@"keyCode"] integerValue];
        if (hotKeyRegistrations == before || lastRegisteredKeyCode != code) {
            fprintf(stderr, "%s not registered again: %lu registrations, last key code %ld\\n", [key UTF8String],
                    (unsigned long)(hotKeyRegistrations - before), (long)lastRegisteredKeyCode);
            return 194;
        }
    }
    // Loading the fields at launch does not store the registered shortcuts either.
    [controller loadHotkeyRecorderCombos];
    if (Stored(@"ShortcutRecorder mainHotkey") != nil || Stored(@"ShortcutRecorder searchHotkey") != nil) return 195;

    Operator(80, 0, @"Resize");
    NSDictionary *custom = @{@"rememberNum": @80, @"displayNum": @12, @"favoritesRememberNum": @80,
                             @"skipPboardTypesList": @"PasswordPboardType", @"skipPasswordLengthsList": @"12, 20"};
    for (NSString *key in custom) {
        SetUserValue(key, custom[key]);
        if (Stored(key) == nil) return 196;
        [controller updateRestoreDefaultButtons];
        [AnyRestoreButton(IdentifierForKey(key)) performClick:nil];
        if (Stored(key) != nil) { fprintf(stderr, "%s still stored after restoring\\n", [key UTF8String]); return 197; }
    }
    (void)defaults;
    return 0;
}

// The two "Save ... to:" folder buttons fall back to the Desktop while no
// folder is stored; their arrows show only for another folder and drop it.
static int FolderArrows(void)
{
    NSDictionary *labels = @{@"saveToLocation": @"Restore default folder for clippings saved from the bezel",
                             @"autoSaveToLocation": @"Restore default folder for forgotten clippings"};
    NSDictionary *buttons = @{@"saveToLocation": [controller valueForKey:@"saveToLocationButton"],
                              @"autoSaveToLocation": [controller valueForKey:@"autoSaveToLocationButton"]};
    NSString *desktop = [NSSearchPathForDirectoriesInDomains(NSDesktopDirectory, NSUserDomainMask, YES) firstObject];
    if (![controller respondsToSelector:@selector(storeSaveLocation:forButton:)]) { fprintf(stderr, "no -storeSaveLocation:forButton:\\n"); return 200; }
    [controller updateRestoreDefaultButtons];
    NSView *pane = GeneralPane();
    for (NSString *key in labels) {
        NSString *identifier = IdentifierForKey(key);
        NSButton *arrow = AnyRestoreButton(identifier);
        int failed = CheckButton(arrow, identifier, labels[key]);
        if (failed) return failed;
        if (![arrow isHidden]) return 201;
        NSButton *folder = buttons[key];
        [controller storeSaveLocation:[NSURL fileURLWithPath:@"/private/var/empty/flycut-folder-probe" isDirectory:YES] forButton:folder];
        if (Stored(key) == nil) return 202;
        if (![[folder title] isEqualToString:@"flycut-folder-probe"]) { fprintf(stderr, "folder button shows %s\\n", [[folder title] UTF8String]); return 203; }
        if ([arrow isHidden] || ![arrow isEnabled]) { fprintf(stderr, "%s arrow not offered for another folder\\n", [key UTF8String]); return 204; }
    }
    [[pane window] layoutIfNeeded];
    for (NSString *key in labels) {
        NSButton *arrow = AnyRestoreButton(IdentifierForKey(key));
        if (!NSContainsRect([pane bounds], FrameIn(arrow, pane)) || Overlaps(arrow, pane)) return 205;
        [arrow performClick:nil];
        if (Stored(key) != nil) return 206;
        if (![[buttons[key] title] isEqualToString:[desktop lastPathComponent]]) { fprintf(stderr, "after restoring the button shows %s\\n", [[buttons[key] title] UTF8String]); return 207; }
        if (![arrow isHidden]) return 208;
        // Choosing the Desktop itself is the default: nothing stored, no arrow.
        [controller storeSaveLocation:[NSURL fileURLWithPath:desktop isDirectory:YES] forButton:buttons[key]];
        if (Stored(key) != nil || ![arrow isHidden]) return 209;
    }
    for (NSView *view in [pane subviews])
        if (![view isHidden] && !NSContainsRect([pane bounds], [view frame])) return 210;
    return 0;
}

// The General arrows show the stored values as soon as the pane is built,
// without waiting for the window to become key.
static int GeneralInitial(void)
{
    NSButton *remember = AnyRestoreButton(IdentifierForKey(@"rememberNum"));
    NSButton *lengths = AnyRestoreButton(IdentifierForKey(@"skipPasswordLengthsList"));
    if (remember == nil || lengths == nil) return 220;
    if ([remember isHidden] || [lengths isHidden]) { fprintf(stderr, "custom General values show no arrow after building the pane\\n"); return 221; }
    if (![AnyRestoreButton(IdentifierForKey(@"displayNum")) isHidden]) return 222;
    return 0;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        if (argc < 3) return 2;
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
        method_setImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)), (IMP)Noop);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(registerHotKey:)), (IMP)FakeRegister);
        method_setImplementation(class_getInstanceMethod([SGHotKeyCenter class], @selector(unregisterHotKey:)), (IMP)NoopArg);
        if (!class_addMethod([FCMemoryDefaults class], @selector(volatileDomainForName:), (IMP)MemoryRegistrationDomain, "@@:@")) return 6;
        method_setImplementation(class_getInstanceMethod([AppController class], @selector(updateMenu)), (IMP)CountMenuUpdate);
        Class imageStore = NSClassFromString(@"FlycutImageStore");
        if (imageStore) method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)AbortSharedStore);
        [NSApplication sharedApplication];
        // -[AppController awakeFromNib] creates the operator, which registers its defaults.
        [[[FlycutOperator alloc] init] autorelease];
        NSNib *nib = [[NSNib alloc] initWithNibNamed:@"MainMenu" bundle:[NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]]];
        NSArray *objects = nil;
        if (![nib instantiateWithOwner:NSApp topLevelObjects:&objects]) return 10;
        [NSApp setDelegate:nil];
        for (id obj in objects) {
            if ([obj isKindOfClass:[AppController class]]) controller = obj;
            if ([obj isKindOfClass:[UKPrefsPanel class]]) prefs = obj;
        }
        if (!controller || !prefs) return 11;
        window = [controller valueForKey:@"prefsPanel"];
        [window setDelegate:nil];
        NSString *mode = [NSString stringWithUTF8String:argv[2]];
        if ([mode isEqualToString:@"general-initial"]) {
            // Stored before the pane is built, as at launch.
            [[NSUserDefaults standardUserDefaults] setObject:@80 forKey:@"rememberNum"];
            [[NSUserDefaults standardUserDefaults] setObject:@"12, 20" forKey:@"skipPasswordLengthsList"];
        }
        originalSetBezelAlpha = method_setImplementation(class_getInstanceMethod([AppController class], @selector(setBezelAlpha:)), (IMP)CountBezelAlpha);
        originalSetBezelWidth = method_setImplementation(class_getInstanceMethod([AppController class], @selector(setBezelWidth:)), (IMP)CountBezelWidth);
        originalSetBezelHeight = method_setImplementation(class_getInstanceMethod([AppController class], @selector(setBezelHeight:)), (IMP)CountBezelHeight);
        [controller buildAppearancesPreferencePanel];
        if ([controller respondsToSelector:@selector(buildMainHotkeyRestoreDefaultButton)])
            [controller buildMainHotkeyRestoreDefaultButton];
        if ([controller respondsToSelector:@selector(buildGeneralRestoreDefaultButtons)])
            [controller buildGeneralRestoreDefaultButtons];
        searchRecorder = [controller valueForKey:@"searchRecorder"];
        mainRecorder = [controller valueForKey:@"mainRecorder"];
        [prefs mapTabsToToolbar];
        NSTabView *tabs = [prefs tabView];
        generalPane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"];
        hotkeysPane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.hotkey.tiff"];
        appearancePane = [tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.appearance.tiff"];
        if (searchRecorder == nil || hotkeysPane == NSNotFound || appearancePane == NSNotFound) return 12;
        ChangePane(appearancePane);
        if ([searchRecorder window] != window) return 13;

        if ([mode isEqualToString:@"pane-switch"]) return PaneSwitch();
        if ([mode isEqualToString:@"pane-switch-refused"]) return PaneSwitchRefused();
        if ([mode isEqualToString:@"focus-ring"]) return FocusRing();
        if ([mode isEqualToString:@"no-snapback"]) return NoSnapback();
        if ([mode isEqualToString:@"search-default"]) return SearchDefault();
        if ([mode isEqualToString:@"dark-field"]) return DarkField();
        if (![controller respondsToSelector:@selector(loadHotkeyRecorderCombos)] ||
            ![controller respondsToSelector:@selector(updateRestoreDefaultButtons)]) {
            fprintf(stderr, "AppController has no Restore Default support\n");
            return 5;
        }
        if ([mode isEqualToString:@"restore-buttons"]) return RestoreButtons();
        if ([mode isEqualToString:@"registered-table"]) return RegisteredTable();
        if ([mode isEqualToString:@"no-search-default"]) return NoSearchDefault();
        if ([mode isEqualToString:@"label-centred"]) return LabelCentred();
        if ([mode isEqualToString:@"help-text"]) return HelpText();
        if ([mode isEqualToString:@"recorder-accessibility"]) return RecorderAccessibility();
        if ([mode isEqualToString:@"live-arrow"]) return LiveArrow();
        if (![controller respondsToSelector:@selector(buildGeneralRestoreDefaultButtons)]) {
            fprintf(stderr, "AppController has no Restore Default arrows on the General pane\n");
            return 7;
        }
        if (generalPane == NSNotFound) return 14;
        ChangePane(generalPane);
        [[window contentView] layoutSubtreeIfNeeded];
        if ([GeneralPane() window] != window) return 15;
        if ([mode isEqualToString:@"general-buttons"]) return GeneralButtons();
        if ([mode isEqualToString:@"general-live"]) return GeneralLive();
        if ([mode isEqualToString:@"general-restore"]) return GeneralRestore();
        if ([mode isEqualToString:@"remember-cancel"]) return RememberCancel();
        if ([mode isEqualToString:@"arrow-columns"]) return ArrowColumns();
        if ([mode isEqualToString:@"restore-removes"]) return RestoreRemoves();
        if ([mode isEqualToString:@"folder-arrows"]) return FolderArrows();
        if ([mode isEqualToString:@"general-initial"]) return GeneralInitial();
        return 4;
    }
}
'''


class PreferencesHotkeyRecorderRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="flycut-recorder-")
        temp = pathlib.Path(cls.temp.name)
        cls.bundle = temp / "TestResources.bundle"
        resources = cls.bundle / "Contents" / "Resources"
        resources.mkdir(parents=True)
        # A checkout with only MainMenu.xib (no ibtool here) runs these tests
        # against the compiled NIB of a built bundle instead.
        configured = os.environ.get("FLYCUT_TEST_RESOURCE_BUNDLE")
        nib = (pathlib.Path(configured) / "Contents" / "Resources" / "English.lproj" / "MainMenu.nib"
               if configured else ROOT / "English.lproj" / "MainMenu.nib")
        if not nib.is_dir():
            raise unittest.SkipTest(f"no compiled MainMenu.nib at {nib}; set FLYCUT_TEST_RESOURCE_BUNDLE to a built Flycut.app")
        shutil.copytree(nib, resources / "MainMenu.nib")
        (cls.bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "org.flycut.tests.recorder-resources",
            "CFBundlePackageType": "BNDL",
        }))
        sources = [
            ROOT / path
            for path in subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True).splitlines()
            if path != "main.m" and not path.startswith(("FlycutHelper/", "Tests/"))
        ]
        fixture = temp / "RecorderFixture.m"
        fixture.write_text(FIXTURE)
        cls.binary = temp / "RecorderFixture"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, FIXTURES, *(path.parent for path in sources)}):
            command += ["-I", str(include)]
        command += [str(path) for path in sources] + [str(fixture)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
        if build.returncode != 0:
            cls.temp.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_mode(self, mode: str) -> None:
        run = subprocess.run([str(self.binary), str(self.bundle), mode], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_pane_switch_ends_recording_and_leaves_no_hidden_focus(self) -> None:
        self.run_mode("pane-switch")

    def test_refused_end_of_editing_keeps_the_pane(self) -> None:
        self.run_mode("pane-switch-refused")

    def test_focused_recorder_has_a_focus_ring_except_while_recording(self) -> None:
        self.run_mode("focus-ring")

    def test_restore_default_buttons_appear_for_custom_values_and_restore_them(self) -> None:
        self.run_mode("restore-buttons")

    def test_search_hotkey_shows_the_registered_default(self) -> None:
        self.run_mode("search-default")

    def test_restore_reads_the_registered_defaults_table(self) -> None:
        self.run_mode("registered-table")

    def test_without_a_registered_search_default_the_arrow_clears_the_shortcut(self) -> None:
        self.run_mode("no-search-default")

    def test_general_pane_has_restore_arrows_next_to_its_fields(self) -> None:
        self.run_mode("general-buttons")

    def test_general_arrows_follow_typing_and_stepping(self) -> None:
        self.run_mode("general-live")

    def test_general_arrows_restore_registered_values_through_the_resize_path(self) -> None:
        self.run_mode("general-restore")

    def test_cancel_in_the_resize_warning_keeps_the_remember_limit(self) -> None:
        self.run_mode("remember-cancel")

    def test_hotkeys_help_text_explains_the_arrow(self) -> None:
        self.run_mode("help-text")

    def test_no_second_copy_of_factory_values(self) -> None:
        source = (ROOT / "AppController.m").read_text()
        self.assertNotIn("PLACEHOLDER", source)
        self.assertNotIn("FlycutDefault", source)

    def test_recording_has_no_snapback_and_escape_still_cancels(self) -> None:
        self.run_mode("no-snapback")

    def test_search_hotkey_label_and_restore_button_are_centred_on_the_field(self) -> None:
        self.run_mode("label-centred")

    def test_hotkey_field_follows_dark_mode(self) -> None:
        self.run_mode("dark-field")

    def test_restore_arrows_line_up_in_one_column_per_pane(self) -> None:
        self.run_mode("arrow-columns")

    def test_hotkey_fields_have_accessibility_labels(self) -> None:
        self.run_mode("recorder-accessibility")

    def test_search_arrow_follows_recording_and_clearing_at_once(self) -> None:
        self.run_mode("live-arrow")

    def test_restoring_removes_the_stored_value(self) -> None:
        self.run_mode("restore-removes")

    def test_folder_buttons_have_arrows_back_to_the_desktop(self) -> None:
        self.run_mode("folder-arrows")

    def test_general_arrows_are_right_when_the_pane_is_built(self) -> None:
        self.run_mode("general-initial")

    def test_arrow_state_is_computed_when_preferences_are_shown(self) -> None:
        body = method_body((ROOT / "AppController.m").read_text(), "-(IBAction) showPreferencePanel:(id)sender")
        refresh = body.find("[self updateRestoreDefaultButtons]")
        self.assertNotEqual(refresh, -1, "showPreferencePanel: does not refresh the arrows")
        self.assertLess(refresh, body.find("makeKeyAndOrderFront"), "the arrows are refreshed only after the window is shown")

    def test_no_restore_identifier_without_a_setting(self) -> None:
        source = (ROOT / "AppController.m").read_text()
        self.assertNotIn('@"restoreDefaultHotkey"', source)

    def test_help_explains_the_restore_arrows(self) -> None:
        help_text = (ROOT / "help.md").read_text()
        section = help_text[help_text.index("**Preferences Panel**"):]
        self.assertRegex(section, r"(?s)arrow.*default", "help.md does not explain the Restore Default arrow")


if __name__ == "__main__":
    unittest.main()
