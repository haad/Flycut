#ifndef FlycutHotkeyDefaults_h
#define FlycutHotkeyDefaults_h

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

// The factory hotkeys and the one-time carry-over that keeps earlier users' bezel hotkey.
// Stored like ShortcutRecorder stores them: the key code (9 is the V key) and Cocoa
// modifier flags. ShortcutRecorder's empty value (key code -1, no flags) means "no hotkey".

static NSString *const FlycutMainHotkeyKey = @"ShortcutRecorder mainHotkey";
static NSString *const FlycutPlainPasteHotkeyKey = @"ShortcutRecorder plainPasteHotkey";
// Named like sandboxMigrationCompleted: set by the first launch of this version.
static NSString *const FlycutHotkeyDefaultsCarryOverKey = @"hotkeyDefaultsMigrationCompleted";

static inline NSDictionary *FlycutHotkeyValue(NSInteger keyCode, NSUInteger modifierFlags)
{
	return @{@"keyCode": @(keyCode), @"modifierFlags": @(modifierFlags)};
}

// The bezel: Control-Option-Command-V. Shift-Command-V, the bezel's hotkey up to now, is
// "paste without formatting" in Google Docs, Chrome and Firefox, "Paste Selection" in
// Terminal and "Paste as Quotation" in Mail, and a held hotkey takes it from all of them;
// Control-Option-Command-V is in none of the shortcut lists and app menus checked. Without
// Shift in it, Shift-V still steps back in the open bezel. A new install leaves
// Shift-Command-V to the apps.
static inline NSDictionary *FlycutBezelHotkeyDefault(void)
{
	return FlycutHotkeyValue(9, NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand);
}

// "Paste as plain text": Option-Shift-Command-V, Apple's "Paste and Match Style". The one
// place that names its factory combination.
static inline NSDictionary *FlycutPlainPasteHotkeyDefault(void)
{
	return FlycutHotkeyValue(9, NSEventModifierFlagOption | NSEventModifierFlagShift | NSEventModifierFlagCommand);
}

// The bezel's factory hotkey before this version: Shift-Command-V.
static inline NSDictionary *FlycutPreviousBezelHotkey(void)
{
	return FlycutHotkeyValue(9, NSEventModifierFlagShift | NSEventModifierFlagCommand);
}

// Keys that macOS writes into any app's defaults domain, some before the app's first launch:
// AppKit's ("NSWindow Frame ...", "NSStatusItem ...", App Shortcuts' NSUserKeyEquivalents) and
// System Settings' language for one app (AppleLanguages). No Flycut key starts like these.
static inline BOOL FlycutIsSystemDefaultsKey(NSString *key)
{
	return [key hasPrefix:@"NS"] || [key hasPrefix:@"Apple"];
}

// Whether a stored hotkey uses the plain-text hotkey's factory keys: the same key with the
// same four modifiers.
static inline BOOL FlycutHotkeyValueUsesPlainPasteDefault(id value)
{
	if (![value isKindOfClass:[NSDictionary class]] || [value objectForKey:@"keyCode"] == nil)
		return NO;
	const NSUInteger modifiers = NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl |
	                             NSEventModifierFlagShift;
	NSDictionary *plain = FlycutPlainPasteHotkeyDefault();
	return [[value objectForKey:@"keyCode"] integerValue] == [[plain objectForKey:@"keyCode"] integerValue] &&
	       ([[value objectForKey:@"modifierFlags"] unsignedIntegerValue] & modifiers) ==
	       ([[plain objectForKey:@"modifierFlags"] unsignedIntegerValue] & modifiers);
}

// Runs once, on the first launch of this version, before anything of that launch stores a
// value or loads a recorder. An earlier Flycut ran for this user when the defaults domain
// already holds a key that is not one of macOS's. Every Flycut since the first import stores
// loadOnStartup at each launch (this version too, after this check), a user of the sandboxed
// Flycut gets sandboxMigrationCompleted from the import that runs just before, and a Flycut in
// use stores more (the history, any changed setting), so an earlier user who never changed a
// setting is found as well. An unknown key counts as Flycut's: that error only leaves a new
// user the old bezel hotkey. The earlier user keeps Shift-Command-V for the bezel unless he
// stored a bezel hotkey himself (a cleared one stays cleared), so the key he used before
// keeps doing what it did. The plain-text hotkey is new for everyone and keeps its factory
// value, unless the earlier user's bezel or search hotkey is stored on that combination:
// then that one keeps it, and the plain-text hotkey starts empty, as a cleared one, instead
// of a combination it does not get. A new install gets the factory hotkeys. "Stored" is
// the domain's own content: -objectForKey: also answers from the registration domain and
// launch arguments. The marker records that the check ran, whatever it decided.
static inline void FlycutCarryOverHotkeyDefaults(NSUserDefaults *defaults, NSString *domain)
{
	if ([defaults boolForKey:FlycutHotkeyDefaultsCarryOverKey])
		return;
	NSDictionary *stored = domain != nil ? [defaults persistentDomainForName:domain] : nil;
	BOOL earlierFlycut = NO;
	for (NSString *key in stored)
		if (!FlycutIsSystemDefaultsKey(key))
			earlierFlycut = YES;
	if (earlierFlycut && [stored objectForKey:FlycutMainHotkeyKey] == nil)
		[defaults setObject:FlycutPreviousBezelHotkey() forKey:FlycutMainHotkeyKey];
	if (earlierFlycut && [stored objectForKey:FlycutPlainPasteHotkeyKey] == nil &&
	    (FlycutHotkeyValueUsesPlainPasteDefault([stored objectForKey:FlycutMainHotkeyKey]) ||
	     FlycutHotkeyValueUsesPlainPasteDefault([stored objectForKey:@"ShortcutRecorder searchHotkey"])))
		[defaults setObject:FlycutHotkeyValue(-1, 0) forKey:FlycutPlainPasteHotkeyKey];
	[defaults setBool:YES forKey:FlycutHotkeyDefaultsCarryOverKey];
}

#endif
