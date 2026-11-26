#ifndef FlycutMenuShortcuts_h
#define FlycutMenuShortcuts_h

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>

// "Paste as plain text" gives way to an app whose own menus use its keys: Apple's "Paste and
// Match Style" on Option-Shift-Command-V in TextEdit, Mail, Notes and Safari, or the Finder's
// "Paste Exactly". While such an app is in front, Flycut releases the hotkey, so the app's
// command runs. Flycut finds out by reading the menu bar of the app in front through the
// Accessibility API: the key-equivalent attributes only, never a title or any other text
// (menus name windows, documents and accounts). Nothing of it is stored but the key
// equivalents, in memory.
//
// A menu item's key equivalent, as read: @[character, virtual key, AX modifiers], each NSNull
// when the item has none. AX gives the character in upper case and the modifiers apart:
// Command is implied unless kAXMenuItemModifierNoCommand is set.

// What the scan asks each element for, in one request: its children and its key equivalent.
// With the menu bar (asked of the application element) these are the only attributes read.
static inline NSArray *FlycutMenuScanAttributes(void)
{
	return @[(NSString *)kAXChildrenAttribute, (NSString *)kAXMenuItemCmdCharAttribute,
	         (NSString *)kAXMenuItemCmdVirtualKeyAttribute, (NSString *)kAXMenuItemCmdModifiersAttribute];
}

static inline NSUInteger FlycutCocoaFlagsForAXMenuModifiers(NSInteger axModifiers)
{
	NSUInteger flags = (axModifiers & kAXMenuItemModifierNoCommand) ? 0 : NSEventModifierFlagCommand;
	if (axModifiers & kAXMenuItemModifierShift)
		flags |= NSEventModifierFlagShift;
	if (axModifiers & kAXMenuItemModifierOption)
		flags |= NSEventModifierFlagOption;
	if (axModifiers & kAXMenuItemModifierControl)
		flags |= NSEventModifierFlagControl;
	return flags;
}

// Whether a menu item's key equivalent is the hotkey: exactly its four modifiers, and its key.
// Menus name the key by the character it types (keyCharacter: what the hotkey's key types
// with Command, FlycutMenuCharacterForKeyCode; case does not matter, Shift is in the
// modifiers), or by the virtual key code for keys without a character.
static inline BOOL FlycutMenuShortcutIsHotkey(NSArray *shortcut, NSInteger keyCode, NSString *keyCharacter, NSUInteger flags)
{
	if (keyCode < 0 || ![shortcut isKindOfClass:[NSArray class]] || [shortcut count] != 3)
		return NO;
	const NSUInteger mask = NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl |
	                        NSEventModifierFlagShift;
	id character = shortcut[0], virtualKey = shortcut[1], modifiers = shortcut[2];
	NSInteger axModifiers = [modifiers isKindOfClass:[NSNumber class]] ? [modifiers integerValue] : 0;
	if (FlycutCocoaFlagsForAXMenuModifiers(axModifiers) != (flags & mask))
		return NO;
	if ([character isKindOfClass:[NSString class]] && [character length] > 0 && [keyCharacter length] > 0 &&
	    [character caseInsensitiveCompare:keyCharacter] == NSOrderedSame)
		return YES;
	return [virtualKey isKindOfClass:[NSNumber class]] && [virtualKey integerValue] == keyCode;
}

static inline BOOL FlycutMenuShortcutsContainHotkey(NSArray *shortcuts, NSInteger keyCode, NSString *keyCharacter, NSUInteger flags)
{
	for (NSArray *shortcut in shortcuts)
		if (FlycutMenuShortcutIsHotkey(shortcut, keyCode, keyCharacter, flags))
			return YES;
	return NO;
}

// The decision. Flycut gives way only on evidence: the app's menus were read (shortcuts is
// nil otherwise) and one of their key equivalents is the hotkey. Menus that could not be read,
// or a read cut short before such an item, keep Flycut's hotkey; so does Flycut itself in front.
static inline BOOL FlycutPlainPasteYieldsToApp(BOOL appIsFlycut, NSArray *shortcuts, NSInteger keyCode, NSString *keyCharacter,
                                               NSUInteger flags)
{
	return !appIsFlycut && shortcuts != nil && FlycutMenuShortcutsContainHotkey(shortcuts, keyCode, keyCharacter, flags);
}

// What the hotkey's key types with Command held, in the current keyboard layout: the
// character a menu item on that key names. Layouts of other scripts (Russian, Greek, Hebrew)
// and "Dvorak - QWERTY Command" type Latin letters with Command, and AppKit gives a menu's
// Command-V to the key that types v then. nil for no key or no such character.
static inline NSString *FlycutMenuCharacterForKeyCode(NSInteger keyCode)
{
	if (keyCode < 0 || keyCode > UINT16_MAX)
		return nil;
	TISInputSourceRef source = TISCopyCurrentKeyboardLayoutInputSource();
	if (source == NULL)
		return nil;
	NSString *character = nil;
	CFDataRef data = (CFDataRef)TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData);
	if (data != NULL) {
		UInt32 deadKeyState = 0;
		UniChar characters[4];
		UniCharCount length = 0;
		if (UCKeyTranslate((const UCKeyboardLayout *)CFDataGetBytePtr(data), (UInt16)keyCode, kUCKeyActionDisplay,
		                   (cmdKey >> 8) & 0xFF, LMGetKbdType(), kUCKeyTranslateNoDeadKeysMask, &deadKeyState, 4, &length,
		                   characters) == noErr && length > 0)
			character = [NSString stringWithCharacters:characters length:length];
	}
	CFRelease(source);
	return character;
}

// Reads the given attributes of one element: their values in order, NSNull where the element
// has none, nil when the element does not answer.
typedef NSArray *(^FlycutMenuValuesReader)(id element, NSArray *attributes);

// Walks the menu bar of an application element depth first, in menu order (the Edit menu
// comes early), with one request per element, and stops after budget seconds or elementLimit
// elements. Result: "read" (the menu bar was read), "complete", "elements" (menu bar elements
// read), "seconds" and "shortcuts" (every key equivalent found).
static inline NSDictionary *FlycutScanMenuShortcuts(id application, FlycutMenuValuesReader read, NSTimeInterval budget,
                                                    NSUInteger elementLimit)
{
	NSTimeInterval start = [[NSProcessInfo processInfo] systemUptime];
	NSArray *bar = read(application, @[(NSString *)kAXMenuBarAttribute]);
	id menuBar = [bar count] == 1 ? bar[0] : nil;
	if (menuBar == nil || menuBar == [NSNull null])
		return @{@"read": @NO, @"complete": @NO, @"elements": @0, @"shortcuts": @[],
		         @"seconds": @([[NSProcessInfo processInfo] systemUptime] - start)};
	NSArray *attributes = FlycutMenuScanAttributes();
	NSMutableArray *pending = [NSMutableArray arrayWithObject:menuBar];
	NSMutableArray *shortcuts = [NSMutableArray array];
	NSUInteger elements = 0;
	BOOL complete = YES;
	while ([pending count] > 0) {
		if (elements >= elementLimit || [[NSProcessInfo processInfo] systemUptime] - start >= budget) {
			complete = NO;
			break;
		}
		id element = [[[pending lastObject] retain] autorelease];
		[pending removeLastObject];
		elements++;
		NSArray *values = read(element, attributes);
		if ([values count] != [attributes count])
			continue;
		id children = values[0];
		if ([children isKindOfClass:[NSArray class]])
			for (id child in [children reverseObjectEnumerator])
				[pending addObject:child];
		if (values[1] != [NSNull null] || values[2] != [NSNull null])
			[shortcuts addObject:@[values[1], values[2], values[3]]];
	}
	return @{@"read": @YES, @"complete": @(complete), @"elements": @(elements), @"shortcuts": shortcuts,
	         @"seconds": @([[NSProcessInfo processInfo] systemUptime] - start)};
}

// The longest Flycut waits for one answer of the app in front (one element's request).
static const float FlycutMenuScanMessagingTimeout = 0.1f;

// The reader for AXUIElements: one AXUIElementCopyMultipleAttributeValues request per element.
static inline NSArray *FlycutAXReadMenuValues(id element, NSArray *attributes)
{
	AXUIElementRef reference = (AXUIElementRef)element;
	AXUIElementSetMessagingTimeout(reference, FlycutMenuScanMessagingTimeout);
	CFArrayRef values = NULL;
	if (AXUIElementCopyMultipleAttributeValues(reference, (CFArrayRef)attributes, 0, &values) != kAXErrorSuccess || values == NULL)
		return nil;
	NSMutableArray *result = [NSMutableArray arrayWithCapacity:[(NSArray *)values count]];
	for (id value in (NSArray *)values) {
		// A missing attribute comes back as an AXValue wrapping its error.
		BOOL missing = CFGetTypeID((CFTypeRef)value) == AXValueGetTypeID() &&
		               AXValueGetType((AXValueRef)value) == kAXValueTypeAXError;
		[result addObject:missing ? [NSNull null] : value];
	}
	CFRelease(values);
	return result;
}

#endif
