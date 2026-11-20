#ifndef FlycutPlainPaste_h
#define FlycutPlainPaste_h

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

// "Paste as plain text": what the current clipboard allows, and when the hotkey is
// registered. Pure functions; AppController does the pasteboard and hotkey work.

typedef NS_ENUM(NSInteger, FlycutPlainPasteKind) {
	// No copied text: an image, files (their names are no copied text), an empty clipboard.
	FlycutPlainPasteNothing = 0,
	// Plain text alone: the app's own paste pastes it without formatting already, so the
	// clipboard is left as it is (a password manager's copy keeps its own clear timer).
	FlycutPlainPasteAsIs,
	// Text with formatting or other data: its plain text takes the clipboard's place for
	// the paste.
	FlycutPlainPasteReplace,
};

// NSPasteboard.org markers: the item is on the pasteboard only for a moment, and the
// content is private. Other clipboard tools skip both.
static NSString *const FlycutTransientPasteboardType = @"org.nspasteboard.TransientType";
static NSString *const FlycutConcealedPasteboardType = @"org.nspasteboard.ConcealedType";

static inline BOOL FlycutPasteboardTypeIsPlainText(NSString *type)
{
	return [@[NSPasteboardTypeString, @"public.plain-text", @"public.utf16-plain-text", @"public.utf16-external-plain-text",
	          @"com.apple.traditional-mac-plain-text", @"NSStringPboardType"] containsObject:type];
}

// Types that carry no content of their own: the NSPasteboard.org markers and the password
// managers' markers Flycut's filter knows.
static inline BOOL FlycutPasteboardTypeIsMarker(NSString *type)
{
	return [type hasPrefix:@"org.nspasteboard."] || [type isEqualToString:@"PasswordPboardType"] ||
	       [type isEqualToString:@"com.agilebits.onepassword"];
}

// itemTypes: the types of each pasteboard item, in order.
static inline FlycutPlainPasteKind FlycutPlainPasteKindForItems(NSArray *itemTypes)
{
	BOOL text = NO;
	for (NSArray *types in itemTypes) {
		if ([types containsObject:NSPasteboardTypeFileURL])
			return FlycutPlainPasteNothing;
		if ([types containsObject:NSPasteboardTypeString])
			text = YES;
	}
	if (!text)
		return FlycutPlainPasteNothing;
	if ([itemTypes count] == 1) {
		for (NSString *type in [itemTypes firstObject])
			if (!FlycutPasteboardTypeIsPlainText(type) && !FlycutPasteboardTypeIsMarker(type))
				return FlycutPlainPasteReplace;
		return FlycutPlainPasteAsIs;
	}
	return FlycutPlainPasteReplace;
}

// Two hotkeys collide when they use the same key with the same four modifiers; an empty
// hotkey (key code -1) uses nothing.
static inline BOOL FlycutHotkeysCollide(NSInteger code, NSUInteger flags, NSInteger otherCode, NSUInteger otherFlags)
{
	const NSUInteger modifiers = NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl |
	                             NSEventModifierFlagShift;
	return code >= 0 && code == otherCode && (flags & modifiers) == (otherFlags & modifiers);
}

// Whether the plain-text hotkey is registered: it has a combination that neither the
// bezel's nor the search window's hotkey uses (if one does, that one wins).
static inline BOOL FlycutPlainPasteHotkeyIsWanted(NSInteger code, NSUInteger flags, NSInteger mainCode, NSUInteger mainFlags,
                                                  NSInteger searchCode, NSUInteger searchFlags)
{
	return code >= 0 && !FlycutHotkeysCollide(code, flags, mainCode, mainFlags) &&
	       !FlycutHotkeysCollide(code, flags, searchCode, searchFlags);
}

#endif
