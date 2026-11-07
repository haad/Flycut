#!/usr/bin/env python3
"""Native regression tests for configurable menu-bar icon colors.

Every fixture imports Tests/Fixtures/FixtureIsolation.h: defaults live in process
memory (nothing is written to the user's Preferences folder) and the status
button is hosted off screen, so no item appears in the menu bar.
"""

from __future__ import annotations

import pathlib
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
ICON_SOURCE = ROOT / "FlycutMenuIcon.m"
MAIN_MENU_XIB = ROOT / "English.lproj" / "MainMenu.xib"

FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <math.h>
#import "FixtureIsolation.h"
#import "FlycutMenuIcon.h"

static BOOL ColorsEqual(NSColor *left, NSColor *right)
{
    NSColor *leftRGB = [left colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    NSColor *rightRGB = [right colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    if (leftRGB == nil || rightRGB == nil)
        return NO;

    CGFloat lr, lg, lb, la, rr, rg, rb, ra;
    [leftRGB getRed:&lr green:&lg blue:&lb alpha:&la];
    [rightRGB getRed:&rr green:&rg blue:&rb alpha:&ra];
    if (!isfinite(lr) || !isfinite(lg) || !isfinite(lb) || !isfinite(la) ||
        !isfinite(rr) || !isfinite(rg) || !isfinite(rb) || !isfinite(ra))
        return NO;
    return fabs(lr - rr) < 0.0001 && fabs(lg - rg) < 0.0001 &&
           fabs(lb - rb) < 0.0001 && fabs(la - ra) < 0.0001;
}

int main(void)
{
    @autoreleasepool {
        // A fresh in-memory store is passed to the production API.
        NSUserDefaults *defaults = [[[FCMemoryDefaults alloc] init] autorelease];
        [FlycutMenuIcon registerColorDefaults:defaults];

        if ([defaults boolForKey:FlycutMenuIconCustomColorsEnabledKey]) {
            fprintf(stderr, "custom icon colors must default to disabled\n");
            return 11;
        }
        if ([FlycutMenuIcon tintColorForPaused:NO userDefaults:defaults] != nil ||
            [FlycutMenuIcon tintColorForPaused:YES userDefaults:defaults] != nil) {
            fprintf(stderr, "automatic mode must return no custom tint\n");
            return 12;
        }
        NSColor *defaultActive = [FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults];
        NSColor *defaultPaused = [FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults];
        if (defaultActive == nil || defaultPaused == nil) {
            fprintf(stderr, "color wells need configured defaults even in automatic mode\n");
            return 16;
        }

        [defaults setBool:YES forKey:FlycutMenuIconCustomColorsEnabledKey];
        [defaults setObject:@[@0.2, [NSNumber numberWithDouble:NAN], @0.4]
                        forKey:FlycutMenuIconActiveColorComponentsKey];
        [defaults setObject:@[@0.2, [NSNumber numberWithDouble:INFINITY], @0.4]
                        forKey:FlycutMenuIconPausedColorComponentsKey];
        if (!ColorsEqual([FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults], defaultActive) ||
            !ColorsEqual([FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults], defaultPaused)) {
            fprintf(stderr, "non-finite defaults must fall back to safe state colors\n");
            return 18;
        }
        [defaults setObject:@[@"not-a-number", @"0.5", @"0.5"]
                        forKey:FlycutMenuIconActiveColorComponentsKey];
        if (!ColorsEqual([FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults], defaultActive)) {
            fprintf(stderr, "nonnumeric defaults must fall back to the safe active color\n");
            return 19;
        }
        [defaults setObject:@[@1.01, @0.5, @0.5]
                        forKey:FlycutMenuIconActiveColorComponentsKey];
        [defaults setObject:@[@0.5, @-0.01, @0.5]
                        forKey:FlycutMenuIconPausedColorComponentsKey];
        if (!ColorsEqual([FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults], defaultActive) ||
            !ColorsEqual([FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults], defaultPaused)) {
            fprintf(stderr, "out-of-range defaults must fall back to safe state colors\n");
            return 20;
        }
        [defaults removeObjectForKey:FlycutMenuIconActiveColorComponentsKey];
        [defaults removeObjectForKey:FlycutMenuIconPausedColorComponentsKey];

        NSColor *activeInput = [NSColor colorWithSRGBRed:0.12 green:0.34 blue:0.56 alpha:0.30];
        NSColor *pausedInput = [NSColor colorWithSRGBRed:0.82 green:0.27 blue:0.09 alpha:0.40];
        [FlycutMenuIcon setTintColor:activeInput forPaused:NO userDefaults:defaults];
        [FlycutMenuIcon setTintColor:pausedInput forPaused:YES userDefaults:defaults];

        NSColor *active = [FlycutMenuIcon tintColorForPaused:NO userDefaults:defaults];
        NSColor *paused = [FlycutMenuIcon tintColorForPaused:YES userDefaults:defaults];
        NSColor *expectedActive = [NSColor colorWithSRGBRed:0.12 green:0.34 blue:0.56 alpha:1.0];
        NSColor *expectedPaused = [NSColor colorWithSRGBRed:0.82 green:0.27 blue:0.09 alpha:1.0];
        if (!ColorsEqual(active, expectedActive) || !ColorsEqual(paused, expectedPaused)) {
            fprintf(stderr, "active and paused colors were not stored independently and opaquely\n");
            return 13;
        }

        [FlycutMenuIcon setTintColor:activeInput forPaused:YES userDefaults:defaults];
        paused = [FlycutMenuIcon tintColorForPaused:YES userDefaults:defaults];
        if (!ColorsEqual(active, paused)) {
            fprintf(stderr, "users must be able to choose identical state colors\n");
            return 14;
        }

        [defaults setBool:NO forKey:FlycutMenuIconCustomColorsEnabledKey];
        if ([FlycutMenuIcon tintColorForPaused:NO userDefaults:defaults] != nil ||
            [FlycutMenuIcon tintColorForPaused:YES userDefaults:defaults] != nil) {
            fprintf(stderr, "disabling custom colors must restore automatic tinting\n");
            return 15;
        }
        if (!ColorsEqual([FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults], active) ||
            !ColorsEqual([FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults], paused)) {
            fprintf(stderr, "automatic mode must not discard configured state colors\n");
            return 17;
        }
    }
    return 0;
}
'''

CONTROLLER_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <math.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutMenuIcon.h"

@interface AppController (MenuIconColorTesting)
- (void)buildAppearancesPreferencePanel;
- (void)updateMenuBarIcon;
- (IBAction)toggleMenuIconCustomColors:(id)sender;
- (IBAction)setActiveMenuIconColor:(id)sender;
- (IBAction)setPausedMenuIconColor:(id)sender;
@end

@interface FCColorStateOperator : NSObject {
    BOOL _paused;
}
@property(nonatomic, assign) BOOL paused;
@end

@implementation FCColorStateOperator
@synthesize paused = _paused;
- (BOOL)storeDisabled { return self.paused; }
@end

static NSView *FindView(NSView *root, NSString *identifier)
{
    if ([[root identifier] isEqualToString:identifier])
        return root;
    for (NSView *child in [root subviews]) {
        NSView *match = FindView(child, identifier);
        if (match != nil)
            return match;
    }
    return nil;
}

static BOOL ColorsEqual(NSColor *left, NSColor *right)
{
    if (left == nil || right == nil)
        return left == right;
    NSColor *leftRGB = [left colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    NSColor *rightRGB = [right colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    CGFloat lr, lg, lb, la, rr, rg, rb, ra;
    [leftRGB getRed:&lr green:&lg blue:&lb alpha:&la];
    [rightRGB getRed:&rr green:&rg blue:&rb alpha:&ra];
    if (!isfinite(lr) || !isfinite(lg) || !isfinite(lb) || !isfinite(la) ||
        !isfinite(rr) || !isfinite(rg) || !isfinite(rb) || !isfinite(ra))
        return NO;
    return fabs(lr - rr) < 0.0001 && fabs(lg - rg) < 0.0001 &&
           fabs(lb - rb) < 0.0001 && fabs(la - ra) < 0.0001;
}

// The colour a text colour shows on screen, in both Light and Dark Mode.
static BOOL ResolvedColorsEqual(NSColor *left, NSColor *right)
{
    __block BOOL equal = YES;
    for (NSString *name in @[NSAppearanceNameAqua, NSAppearanceNameDarkAqua]) {
        [[NSAppearance appearanceNamed:name] performAsCurrentDrawingAppearance:^{
            if (!ColorsEqual(left, right))
                equal = NO;
        }];
    }
    return equal;
}

static NSTextField *FindLabel(NSView *root, NSString *text)
{
    if ([root isKindOfClass:[NSTextField class]] && [[(NSTextField *)root stringValue] isEqualToString:text])
        return (NSTextField *)root;
    for (NSView *child in [root subviews]) {
        NSTextField *match = FindLabel(child, text);
        if (match != nil)
            return match;
    }
    return nil;
}

// Where a label's text starts and ends, in the coordinates of another view.
static NSRect TextRectInView(NSTextField *label, NSView *view)
{
    return [label convertRect:[[label cell] titleRectForBounds:[label bounds]] toView:view];
}

static BOOL FontsEqual(NSFont *left, NSFont *right)
{
    return [[left fontName] isEqualToString:[right fontName]] && fabs([left pointSize] - [right pointSize]) < 0.01;
}

static NSInteger RenderedPixelsNearColor(NSView *view, NSColor *expected)
{
    NSColor *expectedRGB = [expected colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    if (expectedRGB == nil)
        return 0;
    CGFloat er, eg, eb, ea;
    [expectedRGB getRed:&er green:&eg blue:&eb alpha:&ea];

    [view setNeedsDisplay:YES];
    [view displayIfNeeded];
    NSBitmapImageRep *bitmap = [view bitmapImageRepForCachingDisplayInRect:[view bounds]];
    [view cacheDisplayInRect:[view bounds] toBitmapImageRep:bitmap];
    NSInteger matching = 0;
    for (NSInteger y = 0; y < [bitmap pixelsHigh]; y++) {
        for (NSInteger x = 0; x < [bitmap pixelsWide]; x++) {
            NSColor *pixel = [[bitmap colorAtX:x y:y] colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
            if (pixel == nil || [pixel alphaComponent] < 0.15)
                continue;
            if (fabs([pixel redComponent] - er) < 0.20 &&
                fabs([pixel greenComponent] - eg) < 0.20 &&
                fabs([pixel blueComponent] - eb) < 0.20)
                matching++;
        }
    }
    return matching;
}

int main(void)
{
    @autoreleasepool {
        [NSApplication sharedApplication];
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        if (![defaults isMemberOfClass:[FCMemoryDefaults class]]) {
            fprintf(stderr, "production defaults are not the in-memory fixture defaults\n");
            return 20;
        }

        AppController *controller = [[AppController alloc] init];
        NSBox *panel = [[[NSBox alloc] initWithFrame:NSMakeRect(0, 0, __APPEARANCE_PANEL_WIDTH__, 350)] autorelease];
        [controller setValue:panel forKey:@"appearancePanel"];
        CGFloat originalHeight = [panel frame].size.height;
        [controller buildAppearancesPreferencePanel];

        NSButton *checkbox = (NSButton *)FindView(panel, @"menuIconCustomColorsCheckbox");
        NSColorWell *activeWell = (NSColorWell *)FindView(panel, @"menuIconActiveColorWell");
        NSColorWell *pausedWell = (NSColorWell *)FindView(panel, @"menuIconPausedColorWell");
        NSImageView *activePreview = (NSImageView *)FindView(panel, @"menuIconActivePreview");
        NSImageView *pausedPreview = (NSImageView *)FindView(panel, @"menuIconPausedPreview");
        if (checkbox == nil || activeWell == nil || pausedWell == nil ||
            activePreview == nil || pausedPreview == nil) {
            fprintf(stderr, "appearance panel is missing native state-color controls or previews\n");
            return 21;
        }
        if ([panel frame].size.height <= originalHeight ||
            !NSContainsRect([panel bounds], [[checkbox superview] frame])) {
            fprintf(stderr, "state-color row is clipped by the appearance panel\n");
            return 22;
        }
        NSView *colorRow = [checkbox superview];
        for (NSView *child in [colorRow subviews]) {
            if (!NSContainsRect([colorRow bounds], [child frame])) {
                fprintf(stderr, "state-color control is outside the production-width row: %s row=%s child=%s\n",
                        [[[child identifier] description] UTF8String],
                        [NSStringFromRect([colorRow bounds]) UTF8String],
                        [NSStringFromRect([child frame]) UTF8String]);
                return 29;
            }
        }
        // The row reads as one line of the page: wells no taller than a small
        // control next to a regular checkbox, state labels in the checkbox font,
        // and each label centred on the well and preview it names.
        CGFloat lineHeight = [checkbox fittingSize].height;
        for (NSColorWell *well in @[activeWell, pausedWell]) {
            if (NSHeight([well frame]) > lineHeight * 1.25 + 0.01) {
                fprintf(stderr, "color well is too tall for the row: %s line=%.1f\n",
                        [NSStringFromRect([well frame]) UTF8String], lineHeight);
                return 30;
            }
        }
        NSDictionary *stateViews = @{@"Active": @[activeWell, activePreview], @"Paused": @[pausedWell, pausedPreview]};
        for (NSString *title in stateViews) {
            NSTextField *label = nil;
            for (NSView *child in [colorRow subviews])
                if ([child isKindOfClass:[NSTextField class]] && [[(NSTextField *)child stringValue] isEqualToString:title])
                    label = (NSTextField *)child;
            if (label == nil) {
                fprintf(stderr, "state label %s is missing\n", [title UTF8String]);
                return 31;
            }
            if (fabs([[label font] pointSize] - [[checkbox font] pointSize]) > 0.01) {
                fprintf(stderr, "state label %s uses %.1f pt, the checkbox %.1f pt\n", [title UTF8String],
                        [[label font] pointSize], [[checkbox font] pointSize]);
                return 32;
            }
            NSRect labelFrame = [label convertRect:[label bounds] toView:colorRow];
            for (NSView *named in stateViews[title]) {
                NSRect namedFrame = [named convertRect:[named bounds] toView:colorRow];
                if (fabs(NSMidY(labelFrame) - NSMidY(namedFrame)) > 1.0) {
                    fprintf(stderr, "state label %s is not centred on %s: label=%s view=%s\n", [title UTF8String],
                            [[named identifier] UTF8String], [NSStringFromRect(labelFrame) UTF8String],
                            [NSStringFromRect(namedFrame) UTF8String]);
                    return 33;
                }
            }
        }
        // "Active" and "Paused" read like the checkbox title: its font and the
        // colour of its title, both taken from the live checkbox.
        NSColor *checkboxTitleColor = [[checkbox attributedTitle] attribute:NSForegroundColorAttributeName atIndex:0 effectiveRange:NULL];
        if (checkboxTitleColor == nil) {
            fprintf(stderr, "the checkbox title has no text colour to compare with\n");
            return 34;
        }
        for (NSString *title in stateViews) {
            NSTextField *label = FindLabel(colorRow, title);
            if (!FontsEqual([label font], [checkbox font]) || !ResolvedColorsEqual([label textColor], checkboxTitleColor)) {
                fprintf(stderr, "state label %s: font %s %.1f colour %s; checkbox font %s %.1f colour %s\n", [title UTF8String],
                        [[[label font] fontName] UTF8String], [[label font] pointSize], [[[label textColor] description] UTF8String],
                        [[[checkbox font] fontName] UTF8String], [[checkbox font] pointSize], [[checkboxTitleColor description] UTF8String]);
                return 35;
            }
        }
        // The hint under the line reads like the other row labels of the pane
        // ("Bezel width", "Search clipboard hotkey:"): same left edge, font and
        // text colour, compared with those live labels. It sits below the line.
        NSTextField *hint = FindLabel(colorRow, @"Off uses the automatic macOS color.");
        if (hint == nil) {
            fprintf(stderr, "the automatic-colour hint is missing\n");
            return 36;
        }
        for (NSString *title in @[@"Bezel width", @"Search clipboard hotkey:"]) {
            NSTextField *reference = FindLabel(panel, title);
            if (reference == nil || reference == hint) {
                fprintf(stderr, "row label %s is missing\n", [title UTF8String]);
                return 37;
            }
            NSRect hintText = TextRectInView(hint, panel), referenceText = TextRectInView(reference, panel);
            if (fabs(NSMinX(hintText) - NSMinX(referenceText)) > 0.5) {
                fprintf(stderr, "hint text starts at x=%.1f, row label %s at x=%.1f\n", NSMinX(hintText),
                        [title UTF8String], NSMinX(referenceText));
                return 38;
            }
            if (!FontsEqual([hint font], [reference font]) || !ResolvedColorsEqual([hint textColor], [reference textColor])) {
                fprintf(stderr, "hint font %s %.1f colour %s; row label %s font %s %.1f colour %s\n",
                        [[[hint font] fontName] UTF8String], [[hint font] pointSize], [[[hint textColor] description] UTF8String],
                        [title UTF8String], [[[reference font] fontName] UTF8String], [[reference font] pointSize],
                        [[[reference textColor] description] UTF8String]);
                return 39;
            }
        }
        if (NSMaxY([hint frame]) > NSMinY([checkbox frame]) + 0.5 || [hint isEditable] || [hint isBordered]) {
            fprintf(stderr, "the hint is not a plain label below the checkbox line: hint=%s checkbox=%s\n",
                    [NSStringFromRect([hint frame]) UTF8String], [NSStringFromRect([checkbox frame]) UTF8String]);
            return 40;
        }
        NSSize hintFitting = [[hint cell] cellSizeForBounds:NSMakeRect(0, 0, CGFLOAT_MAX, CGFLOAT_MAX)];
        if (NSWidth([hint frame]) + 0.5 < hintFitting.width || NSHeight([hint frame]) + 0.5 < hintFitting.height) {
            fprintf(stderr, "the hint is clipped: frame=%s needs %s\n", [NSStringFromRect([hint frame]) UTF8String],
                    [NSStringFromSize(hintFitting) UTF8String]);
            return 41;
        }
        // One inset on both sides of the row: the paused preview ends as far
        // from the row's right edge as the hint starts from its left edge.
        NSView *rowContent = [hint superview];
        NSRect pausedInRow = [pausedPreview convertRect:[pausedPreview bounds] toView:rowContent];
        if (fabs(NSWidth([rowContent bounds]) - NSMaxX(pausedInRow) - NSMinX([hint frame])) > 0.5) {
            fprintf(stderr, "the colour row ends %.1f from the right edge, the hint starts at %.1f\n",
                    NSWidth([rowContent bounds]) - NSMaxX(pausedInRow), NSMinX([hint frame]));
            return 42;
        }
        if ([checkbox state] != NSControlStateValueOff || [activeWell isEnabled] || [pausedWell isEnabled]) {
            fprintf(stderr, "custom controls must start in automatic mode\n");
            return 23;
        }

        [checkbox setState:NSControlStateValueOn];
        [controller toggleMenuIconCustomColors:checkbox];
        if (![defaults boolForKey:FlycutMenuIconCustomColorsEnabledKey] ||
            ![activeWell isEnabled] || ![pausedWell isEnabled]) {
            fprintf(stderr, "enabling custom colors did not enable both color wells\n");
            return 24;
        }

        NSColor *activeColor = [NSColor colorWithSRGBRed:0.15 green:0.45 blue:0.75 alpha:0.25];
        NSColor *pausedColor = [NSColor colorWithSRGBRed:0.85 green:0.25 blue:0.15 alpha:0.50];
        [activeWell setColor:activeColor];
        [controller setActiveMenuIconColor:activeWell];
        [pausedWell setColor:pausedColor];
        [controller setPausedMenuIconColor:pausedWell];

        NSColor *storedActive = [FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults];
        NSColor *storedPaused = [FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults];
        if (!ColorsEqual(storedActive, [activeWell color]) ||
            !ColorsEqual(storedPaused, [pausedWell color])) {
            fprintf(stderr, "color-well actions did not persist opaque independent colors\n");
            return 25;
        }

        FCOffscreenStatusItem *statusItem = [[[FCOffscreenStatusItem alloc] initWithLength:28.0] autorelease];
        FCColorStateOperator *state = [[[FCColorStateOperator alloc] init] autorelease];
        [controller setValue:statusItem forKey:@"statusItem"];
        [controller setValue:state forKey:@"flycutOperator"];

        state.paused = NO;
        [controller updateMenuBarIcon];
        if (RenderedPixelsNearColor([statusItem button], storedActive) < 3) {
            fprintf(stderr, "active status item did not render the active custom tint\n");
            return 26;
        }
        state.paused = YES;
        [controller updateMenuBarIcon];
        if (RenderedPixelsNearColor([statusItem button], storedPaused) < 3) {
            fprintf(stderr, "paused status item did not render the paused custom tint\n");
            return 27;
        }

        [checkbox setState:NSControlStateValueOff];
        [controller toggleMenuIconCustomColors:checkbox];
        if ([[statusItem button] contentTintColor] != nil ||
            ![[[statusItem button] image] isTemplate] ||
            [activeWell isEnabled] || [pausedWell isEnabled]) {
            fprintf(stderr, "automatic mode did not clear tint and disable both wells\n");
            return 28;
        }

        [controller setValue:nil forKey:@"statusItem"];
        [controller setValue:nil forKey:@"flycutOperator"];
        [controller release];
    }
    return 0;
}
'''

LAYOUT_FIXTURE = r'''
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "UKPrefsPanel.h"
#import "SRRecorderCell.h"

@interface AppController (LayoutProbe)
- (void)buildGeneralPermissionsPreferenceRow;
- (void)buildAppearancesPreferencePanel;
@end
static void Noop(id self, SEL cmd) {}
static id SafeInit(id self, SEL cmd) {
    return ((id (*)(id, SEL))class_getMethodImplementation([NSResponder class], @selector(init)))(self, cmd);
}
static void NoBinding(id self, SEL cmd, id binding, id object, id path, id options) {}
static NSUInteger permissionChecks;
static void Check(id self, SEL cmd, id sender) { permissionChecks++; }

static NSButton *FindButton(NSView *root) {
    if ([root isKindOfClass:[NSButton class]] &&
        [[(NSButton *)root title] isEqualToString:@"Check Accessibility Permissions"])
        return (NSButton *)root;
    for (NSView *child in root.subviews) {
        NSButton *result = FindButton(child);
        if (result) return result;
    }
    return nil;
}
static int VerifyRow(NSView *content, NSBox *box, NSArray *originals, NSArray *frames,
                     AppController *controller) {
    NSButton *button = FindButton(content);
    if (!button) { fprintf(stderr,"General permission button missing\n"); return 43; }
    if (button.target != controller || button.action != @selector(recheckAccessibility:)) return 44;
    NSView *row = button.superview;
    if (!NSContainsRect(content.bounds, row.frame) || !NSContainsRect(box.bounds, content.frame)) return 45;
    for (NSUInteger i=0; i<originals.count; i++) {
        NSView *view = originals[i];
        if (!NSEqualRects(view.frame, [frames[i] rectValue])) {
            fprintf(stderr,"Original General control moved: %s\n", [NSStringFromRect(view.frame) UTF8String]); return 46;
        }
        if (NSIntersectsRect(row.frame, view.frame)) {
            fprintf(stderr,"General row overlaps %s at %s\n", class_getName(view.class), [NSStringFromRect(view.frame) UTF8String]); return 47;
        }
    }
    for (NSView *child in row.subviews) {
        if (!NSContainsRect(row.bounds, child.frame)) {
            fprintf(stderr,"Added General control clipped: %s frame=%s row=%s\n",
                    class_getName(child.class), [NSStringFromRect(child.frame) UTF8String],
                    [NSStringFromRect(row.bounds) UTF8String]); return 52;
        }
    }
    return 0;
}
int main(int argc, const char **argv) {
 @autoreleasepool {
    if (argc < 2) return 2;
    if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
    // Isolate state/lifecycle only (defaults are in memory via FixtureIsolation.h);
    // the NIB hierarchy, constraints, box margins, production panel builders and
    // UKPrefsPanel resizing all run unchanged.
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(init)), (IMP)SafeInit);
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(awakeFromNib)), (IMP)Noop);
    method_setImplementation(class_getInstanceMethod([AppController class], @selector(recheckAccessibility:)), (IMP)Check);
    IMP prefsAwake = method_setImplementation(class_getInstanceMethod([UKPrefsPanel class], @selector(awakeFromNib)), (IMP)Noop);
    method_setImplementation(class_getInstanceMethod([SRRecorderCell class], NSSelectorFromString(@"_loadKeyCombo")), (IMP)Noop);
    method_setImplementation(class_getInstanceMethod([NSObject class], @selector(bind:toObject:withKeyPath:options:)), (IMP)NoBinding);
    [NSApplication sharedApplication];
    NSNib *nib = [[NSNib alloc] initWithNibNamed:@"MainMenu" bundle:[NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]]];
    NSArray *objects = nil;
    if (![nib instantiateWithOwner:NSApp topLevelObjects:&objects]) return 10;
    [NSApp setDelegate:nil];
    AppController *controller = nil; UKPrefsPanel *prefs = nil;
    for (id obj in objects) {
        if ([obj isKindOfClass:[AppController class]]) controller=obj;
        if ([obj isKindOfClass:[UKPrefsPanel class]]) prefs=obj;
    }
    if (!controller || !prefs) return 11;
    NSView *content = [[controller valueForKey:@"savingSectionLabel"] superview];
    NSBox *box = (NSBox *)content.superview;
    NSWindow *window = [controller valueForKey:@"prefsPanel"];
    [window setDelegate:nil];
    NSTabView *tabs = prefs.tabView;
    NSBox *appearance = [controller valueForKey:@"appearancePanel"];
    [window.contentView layoutSubtreeIfNeeded];
    NSArray *originals = [[content.subviews copy] autorelease];
    NSMutableArray *frames = [NSMutableArray array];
    NSUInteger constrained=0;
    for (NSView *view in originals) { [frames addObject:[NSValue valueWithRect:view.frame]]; if (!view.translatesAutoresizingMaskIntoConstraints) constrained++; }
    if (!originals.count || constrained != originals.count || content.constraints.count == 0) return 12;
    fprintf(stderr,"Loaded production NIB: controls=%lu constraints=%lu margins=%s content=%s\n",
            (unsigned long)originals.count, (unsigned long)content.constraints.count,
            [NSStringFromSize(box.contentViewMargins) UTF8String], [NSStringFromRect(content.bounds) UTF8String]);
    if (![controller respondsToSelector:@selector(buildGeneralPermissionsPreferenceRow)]) return 43;
    [controller buildGeneralPermissionsPreferenceRow];
    [controller buildAppearancesPreferencePanel];
    if (FindButton(appearance)) return 41;
    [window.contentView layoutSubtreeIfNeeded];
    int result = VerifyRow(content,box,originals,frames,controller);
    if (result) return result;
    NSButton *button=FindButton(content);
    NSUInteger count=content.subviews.count;
    [controller buildGeneralPermissionsPreferenceRow];
    if (content.subviews.count!=count || FindButton(content)!=button) return 48;
    if (permissionChecks) return 49;
    [button performClick:nil];
    if (permissionChecks!=1) return 50;
    ((void (*)(id, SEL))prefsAwake)(prefs,@selector(awakeFromNib));
    NSInteger generalIndex=[tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"];
    NSInteger appearanceIndex=[tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.appearance.tiff"];
    if (generalIndex==NSNotFound || appearanceIndex==NSNotFound) return 51;
    NSButton *sender=[[[NSButton alloc] init] autorelease];
    NSUInteger transitions=0;
    for (NSString *look in @[NSAppearanceNameAqua,NSAppearanceNameDarkAqua]) {
        window.appearance=[NSAppearance appearanceNamed:look];
        for (NSInteger i=0; i<tabs.numberOfTabViewItems; i++) {
            sender.tag=i; [prefs changePanes:sender];
            [window.contentView layoutSubtreeIfNeeded];
            if (i==appearanceIndex) {
                for (NSView *appearanceRow in appearance.contentView.subviews)
                    if (!NSContainsRect(appearance.contentView.bounds, appearanceRow.frame)) return 54;
            }
            sender.tag=generalIndex; [prefs changePanes:sender];
            transitions++;
            [window.contentView layoutSubtreeIfNeeded];
            result=VerifyRow(content,box,originals,frames,controller);
            if (result) return result;
        }
    }
    if (argc > 2) {
        window.appearance=[NSAppearance appearanceNamed:NSAppearanceNameAqua];
        for (NSNumber *index in @[@(generalIndex),@(appearanceIndex)]) {
            sender.tag=index.integerValue; [prefs changePanes:sender];
            [window.contentView layoutSubtreeIfNeeded];
            NSView *view=window.contentView;
            NSBitmapImageRep *image=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
            [view cacheDisplayInRect:view.bounds toBitmapImageRep:image];
            NSString *name=index.integerValue==generalIndex ? @"general.png" : @"appearance.png";
            NSString *path=[[NSString stringWithUTF8String:argv[2]] stringByAppendingPathComponent:name];
            if (![[image representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES]) return 53;
        }
    }
    fprintf(stderr,"Native NIB layout/action/%lu tab-return checks PASS\n", (unsigned long)transitions);
    return 0;
 }
}

'''


class MenuBarIconColorRegressionTests(unittest.TestCase):
    def test_state_colors_are_local_independent_and_optional(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flycut-menu-icon-colors-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            fixture = temp / "MenuBarIconColorFixture.m"
            binary = temp / "MenuBarIconColorFixture"
            fixture.write_text(FIXTURE)

            build = subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "clang",
                    "-fno-objc-arc",
                    "-fblocks",
                    "-fmodules",
                    "-mmacosx-version-min=13.5",
                    "-arch",
                    "arm64",
                    "-I",
                    str(ROOT),
                    "-I",
                    str(FIXTURES),
                    str(fixture),
                    str(ICON_SOURCE),
                    "-framework",
                    "AppKit",
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            run = subprocess.run(
                [str(binary)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_permission_check_is_only_in_general_without_clipping_or_automatic_checks(self) -> None:
        # An explicitly supplied candidate must prove XIB-to-NIB provenance.
        # Otherwise use only this checkout's tracked compiled resource, not an
        # unrelated installed app or a developer-specific absolute path.
        configured_bundle = os.environ.get("FLYCUT_TEST_RESOURCE_BUNDLE")
        resource_bundle = pathlib.Path(configured_bundle) if configured_bundle else None
        if resource_bundle is not None:
            stamp_path = resource_bundle / "Contents/Resources/build-stamp.json"
            self.assertTrue(stamp_path.is_file(), "Resource bundle needs a verified build stamp")
            compiled = json.loads(stamp_path.read_text())["resources"]["compiled_main_menu"]
            self.assertEqual(hashlib.sha256(MAIN_MENU_XIB.read_bytes()).hexdigest(), compiled["source_sha256"])
            for entry in compiled["files"]:
                self.assertEqual(hashlib.sha256((resource_bundle / "Contents/Resources" / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])

        sources = [
            ROOT / path
            for path in subprocess.check_output(
                ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True
            ).splitlines()
            if path != "main.m"
            and not path.startswith("FlycutHelper/")
            and not path.startswith("Tests/")
        ]
        if ICON_SOURCE not in sources:
            sources.append(ICON_SOURCE)
        include_dirs = sorted({ROOT, FIXTURES, *(path.parent for path in sources)})

        with tempfile.TemporaryDirectory(prefix="flycut-appearance-layout-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            if resource_bundle is None:
                import shutil
                import plistlib
                resource_bundle = temp / "TestResources.bundle"
                resources = resource_bundle / "Contents/Resources"
                resources.mkdir(parents=True)
                source_nib = ROOT / "English.lproj/MainMenu.nib"
                self.assertTrue(source_nib.is_dir(), "Checkout lacks the compiled production NIB")
                shutil.copytree(source_nib, resources / "MainMenu.nib")
                for source_file in source_nib.iterdir():
                    if source_file.is_file():
                        self.assertEqual(source_file.read_bytes(), (resources / "MainMenu.nib" / source_file.name).read_bytes())
                (resource_bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": "org.flycut.tests.layout-resources",
                    "CFBundleName": "Flycut Test Resources",
                    "CFBundlePackageType": "BNDL",
                }))
            fixture = temp / "AppearanceLayoutFixture.m"
            binary = temp / "AppearanceLayoutFixture"
            fixture.write_text(LAYOUT_FIXTURE)

            command = [
                "/usr/bin/xcrun",
                "clang",
                "-fno-objc-arc",
                "-fobjc-weak",
                "-fblocks",
                "-fmodules",
                "-DFLYCUT_MAC=1",
                "-mmacosx-version-min=13.5",
                "-arch",
                "arm64",
                "-include",
                str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(source) for source in sources)
            command.append(str(fixture))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])

            build = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            run = subprocess.run(
                [str(binary), str(resource_bundle), *([os.environ["FLYCUT_TEST_LAYOUT_EVIDENCE_DIR"]] if "FLYCUT_TEST_LAYOUT_EVIDENCE_DIR" in os.environ else [])],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_native_controls_drive_status_button_tints(self) -> None:
        if MAIN_MENU_XIB.exists():
            appearance_box = ET.parse(MAIN_MENU_XIB).find(".//box[@identifier='testbox']/rect[@key='frame']")
            self.assertIsNotNone(appearance_box, "production XIB is missing the Appearance panel frame")
            appearance_panel_width = float(appearance_box.attrib["width"])
        else:
            import plistlib
            import re
            objects = plistlib.loads((ROOT / "English.lproj/MainMenu.nib/keyedobjects.nib").read_bytes())["$objects"]
            def resolve(value):
                return objects[value.data] if isinstance(value, plistlib.UID) else value
            outlets = [obj for obj in objects if isinstance(obj, dict)
                       and resolve(obj.get("NSLabel")) == "appearancePanel"]
            self.assertEqual(len(outlets), 1)
            frame = resolve(resolve(outlets[0]["NSDestination"])["NSFrame"])
            coordinates = re.findall(r"-?\d+(?:\.\d+)?", frame)
            self.assertEqual(len(coordinates), 4)
            appearance_panel_width = float(coordinates[2])

        sources = [
            ROOT / path
            for path in subprocess.check_output(
                ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True
            ).splitlines()
            if path != "main.m"
            and not path.startswith("FlycutHelper/")
            and not path.startswith("Tests/")
        ]
        if ICON_SOURCE not in sources:
            sources.append(ICON_SOURCE)
        include_dirs = sorted({ROOT, FIXTURES, *(path.parent for path in sources)})

        with tempfile.TemporaryDirectory(prefix="flycut-menu-icon-color-ui-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            fixture = temp / "MenuBarIconColorUIFixture.m"
            binary = temp / "MenuBarIconColorUIFixture"
            fixture.write_text(
                CONTROLLER_FIXTURE.replace(
                    "__APPEARANCE_PANEL_WIDTH__", format(appearance_panel_width, ".17g")
                )
            )

            command = [
                "/usr/bin/xcrun",
                "clang",
                "-fno-objc-arc",
                "-fobjc-weak",
                "-fblocks",
                "-fmodules",
                "-DFLYCUT_MAC=1",
                "-mmacosx-version-min=13.5",
                "-arch",
                "arm64",
                "-include",
                str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(source) for source in sources)
            command.append(str(fixture))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])

            build = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            run = subprocess.run(
                [str(binary)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


    def test_appearance_rows_share_one_inset_constant(self) -> None:
        source = (ROOT / "AppController.m").read_text()
        self.assertEqual(source.count("static const CGFloat FlycutAppearanceRowInset = "), 1)
        start = source.index("-(NSBox *)preferencePanelMenuIconColorRowWithFrameMaxY:(int)frameMaxY\n{")
        body = source[start:source.index("\n}\n", start)]
        # Left edge (hint, checkbox) and right edge (paused preview) both come from the shared inset.
        self.assertIn("rowLabelX = FlycutAppearanceRowInset;", body)
        self.assertIn("contentWidth - FlycutAppearanceRowInset - previewSide", body)


if __name__ == "__main__":
    unittest.main()
