//
//  FlycutListPanel.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

#import "FlycutListPanel.h"
#import "FlycutImageStore.h"

// Menu metrics (measured with NSMenu on macOS 27, see the design evidence): 13 pt menu
// font, 24 pt rows, 11 pt separators, 5 pt padding at top and bottom. The width is
// today's status menu width, which its search field set.
static const CGFloat kListWidth = 384;
static const CGFloat kListPadding = 5;
static const CGFloat kListSearchHeight = 34;
static const CGFloat kListSearchFieldHeight = 22;
static const CGFloat kListSeparatorInset = 10;
static const CGFloat kListRowHeight = 24;
static const CGFloat kListSeparatorHeight = 11;
static const CGFloat kListCornerRadius = 10;
static const CGFloat kListHighlightInset = 5;
static const CGFloat kListHighlightRadius = 5;
// Columns of a native menu at this width (macOS 27, AppKit's own menu item views measured
// offscreen: a checkmark's image at 12-25 pt, the title's text field from 28 pt, key
// equivalents ending at 371 pt, the highlight 5 pt inside both edges).
static const CGFloat kListTitleX = 30;          // text column of the rows and the commands
static const CGFloat kListIconColumn = 20;      // width of the star's and the trash's hit areas
// The star sits in the menu's state column, where a checkmark's image would be (12-25 pt).
// Its ink sits about 0.3 pt left of the image's centre, so the hit area (9-29) is centred
// on 19 and the ink (13-24.5 pt) on the column's centre, 18.5.
static const CGFloat kListStarX = 9;
// The search field is as wide as the highlight, so its magnifier sits in the same column,
// centred like the stars (ink 12.5-25 pt).
static const CGFloat kListSearchX = kListHighlightInset;
// The trash's hit area ends this far from the row's right edge; its glyph ends where the
// menu's key equivalents end (371 of 384 pt). The row follows the clip view, so with
// classic scroll bars the trash stays clear of the scroll bar.
static const CGFloat kListTrashRightInset = 9;
static const CGFloat kListRightInset = 12;      // the commands' shortcuts end here
static const CGFloat kListLabelInset = 2;       // NSTextField draws its text this far inside
static const CGFloat kListGapBelowMenuBar = 4;
static const CGFloat kListScreenMargin = 8;
// How far apart a press on the status item and a close may be and still be one press: on
// macOS 27 the menu bar (MenuBarAgent) hands the press to Flycut about 50 ms after the
// list closed (system log of build 9's sight test: closed, navigate action 50 ms later,
// open again 62 ms after the close; that the list's global monitor closed it at the press
// is inferred). Real presses that are not the same are further apart.
static const NSTimeInterval kListSamePressInterval = 0.5;

static NSString *const FlycutListAddToFavorites = @"Add to Favorites";
static NSString *const FlycutListRemoveFromFavorites = @"Remove from Favorites";
static NSString *const FlycutListDelete = @"Delete";
static NSString *const FlycutListMoveUp = @"Move Up";
static NSString *const FlycutListMoveDown = @"Move Down";
// A row dragged inside the list carries this type besides its content; the table takes
// drops of it only (a pasteboard type of its own, as in Apple's sample "Supporting Table
// View Drag and Drop Through File Promises").
static NSString *const FlycutListRowDragType = @"com.generalarcade.flycut.list-row";

// What VoiceOver reads for a favorite's row: its text and that it is a favorite.
static NSString *FlycutListFavoriteLabel(NSString *title)
{
	return [NSString stringWithFormat:@"%@, Favorite", title ?: @""];
}

// An image row's text starts with the picture emoji and one space, then the size text. The
// emoji is no part of the clipping: neither the search nor the drag's file name sees it. It
// is plain text in the row's font, so it looks exactly like the same emoji at the start of a
// copied text clipping: Apple Color Emoji at the font's size by fallback, on the same
// baseline (a sight test found an emoji sized to the capital letters much smaller than the
// copied one). Its ink reaches 0.25 pt below the text line, still inside the row.
static NSString *const FlycutListImageEmoji = @"\U0001F5BC\uFE0F";

static NSString *FlycutListImageRowText(NSString *title)
{
	return [NSString stringWithFormat:@"%@ %@", FlycutListImageEmoji, title ?: @""];
}

// What VoiceOver reads for an image row: "[Image 1280x720]" as "Image 1280 by 720". It never
// reads the emoji, which it would announce as "framed picture" in front of the size.
static NSString *FlycutListSpokenImageTitle(NSString *title)
{
	NSString *spoken = title ?: @"";
	if ( [spoken hasPrefix:@"["] && [spoken hasSuffix:@"]"] && [spoken length] >= 2 )
		spoken = [spoken substringWithRange:NSMakeRange(1, [spoken length] - 2)];
	return [spoken stringByReplacingOccurrencesOfString:@"([0-9]+)x([0-9]+)" withString:@"$1 by $2"
												options:NSRegularExpressionSearch range:NSMakeRange(0, [spoken length])];
}

static NSImage *FlycutListSymbol(NSString *name, CGFloat pointSize, NSString *description)
{
	NSImage *image = [NSImage imageWithSystemSymbolName:name accessibilityDescription:description];
	NSImageSymbolConfiguration *configuration =
		[NSImageSymbolConfiguration configurationWithPointSize:pointSize weight:NSFontWeightRegular scale:NSImageSymbolScaleSmall];
	return [image imageWithSymbolConfiguration:configuration];
}

static BOOL FlycutListIncreasedContrast(NSView *view)
{
	NSAppearanceName match = [[view effectiveAppearance] bestMatchFromAppearancesWithNames:@[
		NSAppearanceNameAqua, NSAppearanceNameDarkAqua,
		NSAppearanceNameAccessibilityHighContrastAqua, NSAppearanceNameAccessibilityHighContrastDarkAqua]];
	return [match isEqualToString:NSAppearanceNameAccessibilityHighContrastAqua] ||
		[match isEqualToString:NSAppearanceNameAccessibilityHighContrastDarkAqua];
}

@class FlycutListCommandRow;

@interface FlycutListController ()
- (BOOL)handleKeyEquivalent:(NSEvent *)event;
- (void)handleCancel;
- (void)hoverRow:(NSInteger)row;
- (void)hoverCommandRow:(FlycutListCommandRow *)row;
- (void)unhoverCommandRow:(FlycutListCommandRow *)row;
- (void)chooseRow:(NSInteger)row;
- (void)chooseCommand:(NSMenuItem *)item;
- (void)toggleFavoriteAtRow:(NSInteger)row;
- (void)deleteRow:(NSInteger)row;
- (BOOL)isEntryRow:(NSInteger)row;
@end

#pragma mark - Window

@implementation FlycutListPanel

// A borderless panel cannot become key unless it says so; it must, for typing.
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)canBecomeMainWindow { return NO; }

// Flycut has no Edit menu while it is inactive, so the list handles its own Command keys.
- (BOOL)performKeyEquivalent:(NSEvent *)event
{
	id controller = [self delegate];
	if ( [controller isKindOfClass:[FlycutListController class]] && [controller handleKeyEquivalent:event] )
		return YES;
	return [super performKeyEquivalent:event];
}

- (void)cancelOperation:(id)sender
{
	id controller = [self delegate];
	if ( [controller isKindOfClass:[FlycutListController class]] )
		[controller handleCancel];
}

@end

// The menu material with rounded corners; with Reduce Transparency the system draws it
// opaque on its own.
@interface FlycutListBackgroundView : NSVisualEffectView
@end

@implementation FlycutListBackgroundView
- (BOOL)isFlipped { return YES; }
@end

// The menu's hairline edge; stronger with Increase Contrast.
@interface FlycutListBorderView : NSView
@end

@implementation FlycutListBorderView
- (BOOL)isFlipped { return YES; }
- (NSView *)hitTest:(NSPoint)point { return nil; }
- (void)drawRect:(NSRect)dirtyRect
{
	BOOL strong = FlycutListIncreasedContrast(self);
	[(strong ? [NSColor secondaryLabelColor] : [NSColor separatorColor]) set];
	NSBezierPath *edge = [NSBezierPath bezierPathWithRoundedRect:NSInsetRect([self bounds], 0.5, 0.5)
														xRadius:kListCornerRadius - 0.5 yRadius:kListCornerRadius - 0.5];
	[edge setLineWidth:strong ? 1.0 : 0.5];
	[edge stroke];
}
@end

// A thin line between parts of the list, like a menu separator.
@interface FlycutListSeparatorView : NSView
@end

@implementation FlycutListSeparatorView
- (BOOL)isFlipped { return YES; }
- (void)drawRect:(NSRect)dirtyRect
{
	NSRect bounds = [self bounds];
	[[NSColor separatorColor] set];
	NSRectFillUsingOperation(NSMakeRect(kListSeparatorInset, floor(NSMidY(bounds)), NSWidth(bounds) - 2 * kListSeparatorInset, 1),
							 NSCompositingOperationSourceOver);
}
@end

static void FlycutListDrawHighlight(NSRect rect)
{
	[[NSColor controlAccentColor] set];
	[[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(rect, kListHighlightInset, 0)
									 xRadius:kListHighlightRadius yRadius:kListHighlightRadius] fill];
}

#pragma mark - Rows

@interface FlycutListRowView : NSTableRowView {
	BOOL listHighlighted;
}
@property (nonatomic, assign) BOOL listHighlighted;
@end

@implementation FlycutListRowView
@synthesize listHighlighted;
- (void)setListHighlighted:(BOOL)value
{
	if ( listHighlighted == value )
		return;
	listHighlighted = value;
	[self setNeedsDisplay:YES];
}
- (void)drawBackgroundInRect:(NSRect)dirtyRect
{
	if ( listHighlighted )
		FlycutListDrawHighlight([self bounds]);
}
- (void)drawSelectionInRect:(NSRect)dirtyRect {}
@end

@interface FlycutListEntryView () {
	NSButton *starButton;
	NSButton *trashButton;
	NSTextField *titleField;
	BOOL favorite;
	FlycutListController *controller;   // not retained, owns the table
}
- (void)configureWithTitle:(NSString *)title image:(BOOL)isImage favorite:(BOOL)isFavorite highlighted:(BOOL)highlighted;
- (void)setListHighlighted:(BOOL)highlighted;
@end

@implementation FlycutListEntryView
@synthesize starButton, trashButton, titleField;

- (NSButton *)iconButtonWithFrame:(NSRect)frame action:(SEL)action target:(id)target
{
	NSButton *button = [[[NSButton alloc] initWithFrame:frame] autorelease];
	[button setBordered:NO];
	[button setButtonType:NSButtonTypeMomentaryChange];
	[button setImagePosition:NSImageOnly];
	[button setTitle:@""];
	[button setRefusesFirstResponder:YES];
	[button setTarget:target];
	[button setAction:action];
	return button;
}

- (instancetype)initWithFrame:(NSRect)frame target:(id)target
{
	self = [super initWithFrame:frame];
	if ( self != nil )
	{
		controller = target;
		CGFloat height = NSHeight(frame);
		// The star at the left, in the state column; the trash at the right edge.
		starButton = [[self iconButtonWithFrame:NSMakeRect(kListStarX, 0, kListIconColumn, height)
									 action:@selector(starButtonClicked:) target:target] retain];
		trashButton = [[self iconButtonWithFrame:NSMakeRect(NSWidth(frame) - kListTrashRightInset - kListIconColumn, 0, kListIconColumn, height)
										  action:@selector(trashButtonClicked:) target:target] retain];
		[trashButton setImage:FlycutListSymbol(@"trash", [[NSFont menuFontOfSize:0] pointSize] - 1, FlycutListDelete)];
		[trashButton setAccessibilityLabel:FlycutListDelete];
		[trashButton setToolTip:@"Delete (\u2318\u232B)"];
		titleField = [[NSTextField labelWithString:@""] retain];
		[titleField setFont:[NSFont menuFontOfSize:0]];
		[titleField setLineBreakMode:NSLineBreakByTruncatingTail];
		[[titleField cell] setUsesSingleLineMode:YES];
		// The row follows the table's width: with classic (always visible) scroll bars the
		// clip view is narrower and the trash keeps its distance from the scroll bar.
		[titleField setAutoresizingMask:NSViewWidthSizable];
		[trashButton setAutoresizingMask:NSViewMinXMargin];
		[self setAutoresizingMask:NSViewWidthSizable];
		[self addSubview:starButton];
		[self addSubview:titleField];
		[self addSubview:trashButton];
		[self setTextField:titleField];
	}
	return self;
}

- (void)dealloc
{
	[starButton release];
	[trashButton release];
	[titleField release];
	[super dealloc];
}

- (void)configureWithTitle:(NSString *)title image:(BOOL)isImage favorite:(BOOL)isFavorite highlighted:(BOOL)highlighted
{
	CGFloat height = NSHeight([self bounds]);
	favorite = isFavorite;
	NSString *starLabel = favorite ? FlycutListRemoveFromFavorites : FlycutListAddToFavorites;
	[starButton setImage:FlycutListSymbol(favorite ? @"star.fill" : @"star", [[NSFont menuFontOfSize:0] pointSize], starLabel)];
	[starButton setState:favorite ? NSControlStateValueOn : NSControlStateValueOff];
	[starButton setAccessibilityLabel:starLabel];
	[starButton setToolTip:starLabel];
	// An image row starts with the picture emoji, one space and the size text; VoiceOver
	// hears the size ("Image 1280 by 720"), not the emoji and its name.
	NSString *spoken = isImage ? FlycutListSpokenImageTitle(title) : title;
	[titleField setStringValue:(isImage ? FlycutListImageRowText(title) : title) ?: @""];
	[[titleField cell] setAccessibilityValue:spoken ?: @""];   // the element VoiceOver reads
	CGFloat textX = kListTitleX - kListLabelInset;
	CGFloat textHeight = ceil([titleField fittingSize].height);
	// The title ends before the trash's column also while the trash is hidden, so it does
	// not move or change its truncation when the row is highlighted.
	CGFloat right = NSMinX([trashButton frame]) - 6;
	[titleField setFrame:NSMakeRect(textX, floor((height - textHeight) / 2), right - textX + kListLabelInset, textHeight)];
	// No section headers: VoiceOver hears a favorite's state with its text.
	[self setAccessibilityLabel:favorite ? FlycutListFavoriteLabel(spoken) : spoken];
	[self setListHighlighted:highlighted];
}

- (void)setListHighlighted:(BOOL)highlighted
{
	// One colour for star and trash, as the user chose: tertiaryLabelColor, which the
	// system strengthens with Increase Contrast; white like the text on the highlight.
	NSColor *icons = highlighted ? [NSColor selectedMenuItemTextColor] : [NSColor tertiaryLabelColor];
	NSColor *text = highlighted ? [NSColor selectedMenuItemTextColor] : [NSColor labelColor];
	[starButton setContentTintColor:icons];
	[trashButton setContentTintColor:icons];
	[titleField setTextColor:text];
	// A favorite always shows its filled star at the left, so the favorites on top stand
	// out without a header. The highlighted row shows the trash at the right and, for a
	// history clipping, the star's outline; other rows show no icons.
	[trashButton setHidden:!highlighted];
	[starButton setHidden:!highlighted && !favorite];
	// VoiceOver: the highlighted row is the selected element of the list.
	[self setAccessibilitySelected:highlighted];
}

// VoiceOver's press pastes the row, as a click or Return does.
- (BOOL)accessibilityPerformPress
{
	NSInteger row = [[controller tableView] rowForView:self];
	if ( ![controller isEntryRow:row] )
		return NO;
	[controller chooseRow:row];
	return YES;
}

@end

@interface FlycutListTableView : NSTableView {
	NSTrackingArea *hoverArea;
}
@end

@implementation FlycutListTableView
- (BOOL)acceptsFirstResponder { return NO; }   // typing stays in the search field
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (void)dealloc
{
	[hoverArea release];
	[super dealloc];
}

- (void)updateTrackingAreas
{
	[super updateTrackingAreas];
	if ( hoverArea != nil )
	{
		[self removeTrackingArea:hoverArea];
		[hoverArea release];
	}
	// Active always: Flycut stays inactive while the list is open.
	hoverArea = [[NSTrackingArea alloc] initWithRect:NSZeroRect
											 options:NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited |
													 NSTrackingActiveAlways | NSTrackingInVisibleRect
											   owner:self userInfo:nil];
	[self addTrackingArea:hoverArea];
}
- (NSInteger)rowForEvent:(NSEvent *)event
{
	return [self rowAtPoint:[self convertPoint:[event locationInWindow] fromView:nil]];
}
- (void)mouseMoved:(NSEvent *)event
{
	[(FlycutListController *)[self delegate] hoverRow:[self rowForEvent:event]];
}
- (void)mouseEntered:(NSEvent *)event
{
	[(FlycutListController *)[self delegate] hoverRow:[self rowForEvent:event]];
}
// This is where every press on a row in the list starts (a press on the status item that
// is dragged into the list is followed by -[FlycutListController trackMouseFromEvent:]
// and never drags). NSTableView tracks it: released within AppKit's drag threshold it is
// a click, and the table sends its action, which chooses the row as in a menu; moved
// further, the table drags the row (-tableView:pasteboardWriterForRow:).
- (void)mouseDown:(NSEvent *)event
{
	if ( ![(FlycutListController *)[self delegate] isEntryRow:[self rowForEvent:event]] )
		return;
	[super mouseDown:event];
}
@end

#pragma mark - Dragging rows out

// A text row's drag: the text and the rich text Flycut stored (RTF, HTML), as a paste
// writes them, and the list's row type. No file: the Finder makes a clipping file of
// dropped text itself, and an application that takes files (Mail, Messages) would attach
// a file instead of inserting the text.
static NSPasteboardItem *FlycutListTextDragItem(FlycutClipping *clipping)
{
	NSPasteboardItem *item = [[[NSPasteboardItem alloc] init] autorelease];
	[item setString:[clipping contents] ?: @"" forType:NSPasteboardTypeString];
	NSDictionary *richData = [clipping richData];
	for ( NSString *type in richData )
		[item setData:[richData objectForKey:type] forType:type];
	[item setString:@"" forType:FlycutListRowDragType];
	return item;
}

// "Flycut Image 2026-11-11 at 12.00.47.png", like a screenshot, from the capture time.
static NSString *FlycutListImageFileName(FlycutClipping *clipping, NSString *type)
{
	NSString *name = @"Flycut Image";
	if ( [clipping timestamp] > 0 )
	{
		NSDateFormatter *format = [[[NSDateFormatter alloc] init] autorelease];
		[format setLocale:[NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"]];
		[format setDateFormat:@"yyyy-MM-dd 'at' HH.mm.ss"];
		NSDate *captured = [NSDate dateWithTimeIntervalSince1970:(NSTimeInterval)[clipping timestamp]];
		name = [NSString stringWithFormat:@"%@ %@", name, [format stringFromDate:captured]];
	}
	return [name stringByAppendingPathExtension:[FlycutImageStore fileExtensionForType:type]];
}

// An image row's drag: a file promise, so the Finder gets a file of the stored image
// (PNG, TIFF, GIF or JPEG, byte for byte), plus the image data for applications that take
// images, and the list's row type. The promise is written when the drop happens, on a
// queue of its own (Apple: "Supporting Drag and Drop Through File Promises"); the provider
// keeps its own copy of the bytes, so a deleted row or a closed list cannot take them away.
@interface FlycutListImageDragItem : NSFilePromiseProvider <NSFilePromiseProviderDelegate> {
	NSData *imageData;
	NSString *fileName;
}
- (instancetype)initWithImageData:(NSData *)data type:(NSString *)type fileName:(NSString *)name;
@end

@implementation FlycutListImageDragItem

+ (NSOperationQueue *)writeQueue
{
	static NSOperationQueue *queue = nil;
	static dispatch_once_t once;
	dispatch_once(&once, ^{
		queue = [[NSOperationQueue alloc] init];
		[queue setMaxConcurrentOperationCount:1];
		[queue setName:@"Flycut list drag files"];
	});
	return queue;
}

- (instancetype)initWithImageData:(NSData *)data type:(NSString *)type fileName:(NSString *)name
{
	self = [super init];
	if ( self != nil )
	{
		imageData = [data copy];
		fileName = [name copy];
		[self setFileType:type];
		[self setDelegate:self];
	}
	return self;
}

- (void)dealloc
{
	[imageData release];
	[fileName release];
	[super dealloc];
}

- (NSArray *)writableTypesForPasteboard:(NSPasteboard *)pasteboard
{
	NSMutableArray *types = [[[super writableTypesForPasteboard:pasteboard] mutableCopy] autorelease];
	[types addObject:[self fileType]];
	[types addObject:FlycutListRowDragType];
	return types;
}

- (NSPasteboardWritingOptions)writingOptionsForType:(NSPasteboardType)type pasteboard:(NSPasteboard *)pasteboard
{
	if ( [type isEqualToString:[self fileType]] || [type isEqualToString:FlycutListRowDragType] )
		return 0;
	return [super writingOptionsForType:type pasteboard:pasteboard];
}

- (id)pasteboardPropertyListForType:(NSPasteboardType)type
{
	if ( [type isEqualToString:[self fileType]] )
		return imageData;
	if ( [type isEqualToString:FlycutListRowDragType] )
		return @"";
	return [super pasteboardPropertyListForType:type];
}

- (NSString *)filePromiseProvider:(NSFilePromiseProvider *)provider fileNameForType:(NSString *)type
{
	return fileName;
}

- (void)filePromiseProvider:(NSFilePromiseProvider *)provider writePromiseToURL:(NSURL *)url completionHandler:(void (^)(NSError *))completionHandler
{
	NSError *error = nil;
	if ( ![imageData writeToURL:url options:NSDataWritingAtomic error:&error] && error == nil )
		error = [NSError errorWithDomain:NSCocoaErrorDomain code:NSFileWriteUnknownError userInfo:nil];
	completionHandler(error);
}

- (NSOperationQueue *)operationQueueForFilePromiseProvider:(NSFilePromiseProvider *)provider
{
	return [FlycutListImageDragItem writeQueue];
}

@end

#pragma mark - Commands

@interface FlycutListCommandRow : NSView {
	NSMenuItem *item;
	NSTextField *titleField;
	NSTextField *shortcutField;
	NSTrackingArea *hoverArea;
	BOOL hovered;
	FlycutListController *controller;   // not retained, owns this view
}
- (instancetype)initWithFrame:(NSRect)frame item:(NSMenuItem *)anItem controller:(FlycutListController *)aController;
- (NSMenuItem *)item;
- (BOOL)isHovered;
- (void)setHovered:(BOOL)value;
- (void)refreshFromItem;
@end

static NSString *FlycutListShortcutString(NSMenuItem *item)
{
	NSString *key = [item keyEquivalent];
	if ( [key length] == 0 )
		return @"";
	NSEventModifierFlags mask = [item keyEquivalentModifierMask];
	NSMutableString *text = [NSMutableString string];
	if ( mask & NSEventModifierFlagControl ) [text appendString:@"\u2303"];
	if ( mask & NSEventModifierFlagOption ) [text appendString:@"\u2325"];
	if ( mask & NSEventModifierFlagShift ) [text appendString:@"\u21E7"];
	if ( mask & NSEventModifierFlagCommand ) [text appendString:@"\u2318"];
	[text appendString:[key uppercaseString]];
	return text;
}

@implementation FlycutListCommandRow
- (BOOL)isFlipped { return YES; }
- (instancetype)initWithFrame:(NSRect)frame item:(NSMenuItem *)anItem controller:(FlycutListController *)aController
{
	self = [super initWithFrame:frame];
	if ( self != nil )
	{
		item = [anItem retain];
		controller = aController;
		NSFont *font = [NSFont menuFontOfSize:0];
		titleField = [[NSTextField labelWithString:@""] retain];
		[titleField setFont:font];
		shortcutField = [[NSTextField labelWithString:@""] retain];
		[shortcutField setFont:font];
		[shortcutField setAlignment:NSTextAlignmentRight];
		[self addSubview:titleField];
		[self addSubview:shortcutField];
		[self setAccessibilityElement:YES];
		[self setAccessibilityRole:NSAccessibilityMenuItemRole];
		[self refreshFromItem];
	}
	return self;
}
// Title, shortcut and state come from the menu item, also when the item changes while
// the list is open (the Pause item is retitled by Option-click on the status item).
- (void)refreshFromItem
{
	NSRect frame = [self bounds];
	[titleField setStringValue:[item title] ?: @""];
	[shortcutField setStringValue:FlycutListShortcutString(item)];
	CGFloat textHeight = ceil([titleField fittingSize].height);
	CGFloat y = floor((NSHeight(frame) - textHeight) / 2);
	CGFloat shortcutWidth = ceil([shortcutField fittingSize].width);
	[titleField setFrame:NSMakeRect(kListTitleX - kListLabelInset, y, NSWidth(frame) - kListTitleX - shortcutWidth - kListRightInset - 8, textHeight)];
	[shortcutField setFrame:NSMakeRect(NSWidth(frame) - kListRightInset - shortcutWidth + kListLabelInset, y, shortcutWidth, textHeight)];
	[self setAccessibilityLabel:[item title]];
	[self setAccessibilityEnabled:[item isEnabled]];
	[self updateColors];
}
- (void)dealloc
{
	[item release];
	[titleField release];
	[shortcutField release];
	[hoverArea release];
	[super dealloc];
}
- (NSMenuItem *)item { return item; }
- (BOOL)isHovered { return hovered; }
- (void)updateColors
{
	BOOL enabled = [item isEnabled];
	[titleField setTextColor:!enabled ? [NSColor tertiaryLabelColor] : hovered ? [NSColor selectedMenuItemTextColor] : [NSColor labelColor]];
	[shortcutField setTextColor:hovered && enabled ? [NSColor selectedMenuItemTextColor] : [NSColor secondaryLabelColor]];
}
// The one highlight of the list, by mouse or keyboard (the controller keeps it unique).
- (void)setHovered:(BOOL)value
{
	value = value && [item isEnabled];
	if ( hovered == value )
		return;
	hovered = value;
	[self setAccessibilitySelected:hovered];
	[self updateColors];
	[self setNeedsDisplay:YES];
}
- (void)updateTrackingAreas
{
	[super updateTrackingAreas];
	if ( hoverArea != nil )
	{
		[self removeTrackingArea:hoverArea];
		[hoverArea release];
	}
	hoverArea = [[NSTrackingArea alloc] initWithRect:NSZeroRect
											 options:NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
											   owner:self userInfo:nil];
	[self addTrackingArea:hoverArea];
}
- (void)mouseEntered:(NSEvent *)event { [controller hoverCommandRow:self]; }
- (void)mouseExited:(NSEvent *)event { [controller unhoverCommandRow:self]; }
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (void)mouseDown:(NSEvent *)event {}
- (void)mouseUp:(NSEvent *)event
{
	if ( NSPointInRect([self convertPoint:[event locationInWindow] fromView:nil], [self bounds]) )
		[controller chooseCommand:item];
}
- (void)drawRect:(NSRect)dirtyRect
{
	if ( hovered )
		FlycutListDrawHighlight([self bounds]);
}
- (BOOL)accessibilityPerformPress
{
	[controller chooseCommand:item];
	return YES;
}
@end

#pragma mark - Controller

@implementation FlycutListController {
	FlycutOperator *flycutOperator;
	id<FlycutListControllerDelegate> delegate;   // not retained
	FlycutClipList *clipList;
	FlycutListPanel *panel;
	FlycutListBackgroundView *background;
	FlycutListBorderView *border;
	NSSearchField *searchField;
	FlycutListSeparatorView *searchSeparator;
	NSScrollView *scrollView;
	FlycutListTableView *tableView;
	NSView *commandsView;
	NSMutableArray *commandRows;   // FlycutListCommandRow, top to bottom
	NSTextField *emptyLabel;
	NSInteger highlightedRow;
	NSInteger highlightedCommand;   // index into commandRows, -1 for none
	BOOL open;
	BOOL offscreen;
	NSTimeInterval closedAt;     // seconds since startup, -1 before the first close
	BOOL closeAnswered;          // no press on the status item may take the last close as its own
	id globalMouseMonitor;
	CGFloat listHeightMaximum;   // room below the status item, for this opening
	CGFloat openedListHeight;    // the list's height without a search ("Display in menu" rows)
	FlycutClipping *draggedClipping;   // the row being dragged, while the drag lasts
	BOOL droppedInList;          // the current drag was dropped on the list itself
}
@synthesize visibleRows, commandItems;

- (instancetype)initWithOperator:(FlycutOperator *)op delegate:(id<FlycutListControllerDelegate>)aDelegate
{
	self = [super init];
	if ( self != nil )
	{
		flycutOperator = [op retain];
		delegate = aDelegate;
		clipList = [[FlycutClipList alloc] initWithOperator:op];
		commandRows = [[NSMutableArray alloc] init];
		highlightedRow = -1;
		highlightedCommand = -1;
		visibleRows = 20;
		closedAt = -1;
	}
	return self;
}

- (void)dealloc
{
	// The owner is going away: close without calling back into it.
	delegate = nil;
	[self close];
	[panel setDelegate:nil];
	[tableView setDelegate:nil];
	[tableView setDataSource:nil];
	[searchField setDelegate:nil];
	[panel release];
	[background release];
	[border release];
	[searchField release];
	[searchSeparator release];
	[scrollView release];
	[tableView release];
	[commandsView release];
	[commandRows release];
	[emptyLabel release];
	[clipList release];
	[flycutOperator release];
	[commandItems release];
	[draggedClipping release];
	[super dealloc];
}

- (FlycutListPanel *)panel { return panel; }
- (FlycutClipList *)clipList { return clipList; }
- (NSSearchField *)searchField { return searchField; }
- (NSTableView *)tableView { return tableView; }
- (BOOL)isOpen { return open; }
- (BOOL)closeForStatusItemPressAt:(NSTimeInterval)pressTime
{
	if ( open )
	{
		[self close];
		return YES;
	}
	if ( closeAnswered || closedAt < 0 || fabs(pressTime - closedAt) >= kListSamePressInterval )
		return NO;
	// The press closed the list itself before it got here: it is the second click.
	closeAnswered = YES;
	return YES;
}
- (NSInteger)highlightedRow { return highlightedRow; }
- (NSMenuItem *)highlightedCommand
{
	if ( highlightedCommand < 0 || highlightedCommand >= (NSInteger)[commandRows count] )
		return nil;
	return [(FlycutListCommandRow *)[commandRows objectAtIndex:highlightedCommand] item];
}

- (void)buildIfNeeded
{
	if ( panel != nil )
		return;
	panel = [[FlycutListPanel alloc] initWithContentRect:NSMakeRect(0, 0, kListWidth, 200)
											   styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
												 backing:NSBackingStoreBuffered
												   defer:NO];
	[panel setReleasedWhenClosed:NO];
	[panel setHidesOnDeactivate:NO];
	[panel setBecomesKeyOnlyIfNeeded:NO];
	[panel setFloatingPanel:YES];
	[panel setLevel:NSPopUpMenuWindowLevel];
	[panel setCollectionBehavior:NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary |
								 NSWindowCollectionBehaviorTransient | NSWindowCollectionBehaviorIgnoresCycle];
	[panel setOpaque:NO];
	[panel setBackgroundColor:[NSColor clearColor]];
	[panel setHasShadow:YES];
	[panel setAnimationBehavior:NSWindowAnimationBehaviorNone];
	[panel setAccessibilityLabel:@"Flycut"];
	[panel setDelegate:self];

	background = [[FlycutListBackgroundView alloc] initWithFrame:NSMakeRect(0, 0, kListWidth, 200)];
	[background setMaterial:NSVisualEffectMaterialMenu];
	[background setBlendingMode:NSVisualEffectBlendingModeBehindWindow];
	[background setState:NSVisualEffectStateActive];
	[background setWantsLayer:YES];
	[[background layer] setCornerRadius:kListCornerRadius];
	[[background layer] setMasksToBounds:YES];
	[panel setContentView:background];

	searchField = [[NSSearchField alloc] initWithFrame:NSMakeRect(kListSearchX, kListPadding + floor((kListSearchHeight - kListSearchFieldHeight) / 2),
																  kListWidth - 2 * kListSearchX, kListSearchFieldHeight)];
	[searchField setPlaceholderString:@"Search"];
	// VoiceOver reads a placeholder only while the field is empty; the field needs a name.
	// Its cell is the element VoiceOver gets.
	[[searchField cell] setAccessibilityLabel:@"Search clippings"];
	[searchField setDelegate:self];
	[searchField setSendsSearchStringImmediately:YES];
	[[searchField cell] setScrollable:YES];
	[background addSubview:searchField];

	searchSeparator = [[FlycutListSeparatorView alloc] initWithFrame:NSMakeRect(0, kListPadding + kListSearchHeight, kListWidth, kListSeparatorHeight)];
	[background addSubview:searchSeparator];

	scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(0, kListPadding + kListSearchHeight + kListSeparatorHeight, kListWidth, kListRowHeight)];
	[scrollView setDrawsBackground:NO];
	[scrollView setBorderType:NSNoBorder];
	[scrollView setHasVerticalScroller:YES];
	[scrollView setHasHorizontalScroller:NO];
	[scrollView setAutohidesScrollers:YES];
	[scrollView setAutomaticallyAdjustsContentInsets:NO];
	[scrollView setContentInsets:NSEdgeInsetsZero];

	tableView = [[FlycutListTableView alloc] initWithFrame:NSMakeRect(0, 0, kListWidth, kListRowHeight)];
	NSTableColumn *column = [[[NSTableColumn alloc] initWithIdentifier:@"clipping"] autorelease];
	[column setWidth:kListWidth];
	[column setResizingMask:NSTableColumnAutoresizingMask];
	[tableView addTableColumn:column];
	[tableView setHeaderView:nil];
	[tableView setStyle:NSTableViewStylePlain];
	[tableView setIntercellSpacing:NSMakeSize(0, 0)];
	[tableView setBackgroundColor:[NSColor clearColor]];
	[tableView setSelectionHighlightStyle:NSTableViewSelectionHighlightStyleNone];
	[tableView setColumnAutoresizingStyle:NSTableViewLastColumnOnlyAutoresizingStyle];
	[tableView setFocusRingType:NSFocusRingTypeNone];
	[tableView setAllowsEmptySelection:YES];
	[tableView setAutoresizingMask:NSViewWidthSizable];
	[tableView setAccessibilityLabel:@"Clippings"];
	[tableView setDataSource:self];
	[tableView setDelegate:self];
	// A click on a row chooses it (the table's action); a press moved past AppKit's drag
	// threshold drags the row instead. Other applications and the Finder may only copy it
	// (NSTableView defaults to no operation outside the application); inside the list it
	// moves, and only rows of this list are taken, by their own type. The rows make room
	// where a drop would go (NSTableView.h, gap style: AppKit hides the dragged row
	// meanwhile), so the list shows the order a drop gives.
	[tableView setTarget:self];
	[tableView setAction:@selector(tableViewClicked:)];
	[tableView setDraggingSourceOperationMask:NSDragOperationCopy forLocal:NO];
	[tableView setDraggingSourceOperationMask:NSDragOperationMove forLocal:YES];
	[tableView registerForDraggedTypes:@[FlycutListRowDragType]];
	[tableView setDraggingDestinationFeedbackStyle:NSTableViewDraggingDestinationFeedbackStyleGap];
	[scrollView setDocumentView:tableView];
	[background addSubview:scrollView];

	emptyLabel = [[NSTextField labelWithString:@""] retain];
	[emptyLabel setFont:[NSFont menuFontOfSize:0]];
	[emptyLabel setTextColor:[NSColor secondaryLabelColor]];
	[emptyLabel setHidden:YES];
	[background addSubview:emptyLabel];

	commandsView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kListWidth, kListRowHeight)];
	[background addSubview:commandsView];

	border = [[FlycutListBorderView alloc] initWithFrame:[background bounds]];
	[border setAutoresizingMask:NSViewWidthSizable | NSViewHeightSizable];
	[background addSubview:border];
}

- (CGFloat)rowHeightAtIndex:(NSInteger)row
{
	return kListRowHeight;
}

// Separator, the command rows (separators included), as in the menu.
- (CGFloat)commandsHeight
{
	CGFloat height = kListSeparatorHeight;
	for ( NSMenuItem *item in commandItems )
		height += [item isSeparatorItem] ? kListSeparatorHeight : kListRowHeight;
	return height;
}

- (void)rebuildCommandsAtY:(CGFloat)top
{
	highlightedCommand = -1;
	[commandRows removeAllObjects];
	for ( NSView *view in [[[commandsView subviews] copy] autorelease] )
		[view removeFromSuperview];
	CGFloat height = [self commandsHeight];
	[commandsView setFrame:NSMakeRect(0, top, kListWidth, height)];
	// commandsView is not flipped: lay out from its top edge down.
	CGFloat y = height;
	FlycutListSeparatorView *line = [[[FlycutListSeparatorView alloc] initWithFrame:NSMakeRect(0, y - kListSeparatorHeight, kListWidth, kListSeparatorHeight)] autorelease];
	[commandsView addSubview:line];
	y -= kListSeparatorHeight;
	for ( NSMenuItem *item in commandItems )
	{
		if ( [item isHidden] )
			continue;
		if ( [item isSeparatorItem] )
		{
			FlycutListSeparatorView *separator = [[[FlycutListSeparatorView alloc] initWithFrame:NSMakeRect(0, y - kListSeparatorHeight, kListWidth, kListSeparatorHeight)] autorelease];
			[commandsView addSubview:separator];
			y -= kListSeparatorHeight;
			continue;
		}
		FlycutListCommandRow *row = [[[FlycutListCommandRow alloc] initWithFrame:NSMakeRect(0, y - kListRowHeight, kListWidth, kListRowHeight)
																			item:item controller:self] autorelease];
		[commandsView addSubview:row];
		[commandRows addObject:row];
		y -= kListRowHeight;
	}
}

// Height of the list showing the current rows: all of them up to "Display in menu" rows
// and the room below the status item; an empty list keeps one row for its note.
- (CGFloat)fittingListHeight
{
	NSMutableArray *heights = [NSMutableArray array];
	for ( NSInteger i = 0 ; i < (NSInteger)[[clipList rows] count] ; i++ )
		[heights addObject:@([self rowHeightAtIndex:i])];
	CGFloat listHeight = [FlycutClipList listHeightForRowHeights:heights rowHeight:kListRowHeight
													visibleRows:visibleRows > 0 ? visibleRows : 20
														maximum:listHeightMaximum];
	return MAX(listHeight, kListRowHeight);
}

- (CGFloat)listTop
{
	return kListPadding + kListSearchHeight + kListSeparatorHeight;
}

// Resizes the panel for a list of this height. The top edge stays where it is, under the
// status item, as a menu that grows or shrinks downwards.
- (void)applyListHeight:(CGFloat)listHeight
{
	CGFloat listTop = [self listTop];
	CGFloat height = listTop + listHeight + [self commandsHeight] + kListPadding;
	NSRect frame = [panel frame];
	if ( NSHeight(frame) != height )
	{
		[panel setFrame:NSMakeRect(NSMinX(frame), NSMaxY(frame) - height, kListWidth, height) display:!offscreen];
		if ( !offscreen )
			[panel invalidateShadow];
	}
	[background setFrame:NSMakeRect(0, 0, kListWidth, height)];
	[scrollView setFrame:NSMakeRect(0, listTop, kListWidth, listHeight)];
	[commandsView setFrameOrigin:NSMakePoint(0, listTop + listHeight)];
	[border setFrame:[background bounds]];
}

// At opening, without a search: the list's height for this opening.
- (void)layoutWithMaximumListHeight:(CGFloat)maximum
{
	listHeightMaximum = maximum;
	openedListHeight = [self fittingListHeight];
	CGFloat listTop = [self listTop];
	[self rebuildCommandsAtY:listTop + openedListHeight];
	[self applyListHeight:openedListHeight];
	CGFloat labelHeight = ceil([emptyLabel fittingSize].height);
	[emptyLabel setFrame:NSMakeRect(kListTitleX - kListLabelInset, listTop + floor((kListRowHeight - labelHeight) / 2),
									kListWidth - 2 * kListTitleX, labelHeight)];
}

// While searching, the list fits the matches as a native menu does: at least one row
// (a match or the "No Matches" note), at most the height it opened with. Without a
// search it keeps that height, so rows do not jump under the pointer while deleting.
- (void)fitListToRows
{
	if ( !open )
		return;
	CGFloat listHeight = openedListHeight;
	if ( [[searchField stringValue] length] > 0 )
		listHeight = MIN([self fittingListHeight], openedListHeight);
	[self applyListHeight:listHeight];
}

- (void)updateEmptyLabel
{
	BOOL empty = [[clipList rows] count] == 0;
	[emptyLabel setStringValue:[[searchField stringValue] length] > 0 ? @"No Matches" : @"No Clippings"];
	[emptyLabel setHidden:!empty];
}

- (void)prepareWithMaximumListHeight:(CGFloat)maximumListHeight
{
	[self buildIfNeeded];
	open = YES;
	[clipList beginSession];
	[clipList setSearchString:nil];
	[searchField setStringValue:@""];
	[clipList reload];
	highlightedRow = -1;
	[self layoutWithMaximumListHeight:maximumListHeight];
	[tableView reloadData];
	[tableView scrollRowToVisible:0];
	[self updateEmptyLabel];
	[panel makeFirstResponder:searchField];
	NSNotificationCenter *workspace = [[NSWorkspace sharedWorkspace] notificationCenter];
	[workspace addObserver:self selector:@selector(closeForNotification:) name:NSWorkspaceDidActivateApplicationNotification object:nil];
	[workspace addObserver:self selector:@selector(closeForNotification:) name:NSWorkspaceActiveSpaceDidChangeNotification object:nil];
	// The command rows follow their menu items while the list is open, from here on: the
	// delegate's -listControllerDidOpen: may retitle the Pause item already.
	NSMutableSet *menus = [NSMutableSet set];
	for ( NSMenuItem *item in commandItems )
		if ( [item menu] != nil )
			[menus addObject:[item menu]];
	for ( NSMenu *menu in menus )
		[[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(commandItemDidChange:)
													 name:NSMenuDidChangeItemNotification object:menu];
	[delegate listControllerDidOpen:self];
}

- (void)commandItemDidChange:(NSNotification *)notification
{
	for ( FlycutListCommandRow *row in commandRows )
		[row refreshFromItem];
	if ( highlightedCommand >= 0 && ![[self highlightedCommand] isEnabled] )
		[self highlightCommandAtIndex:-1];
}

- (void)openOffscreenWithMaximumListHeight:(CGFloat)maximumListHeight
{
	if ( open )
		return;
	offscreen = YES;
	[self prepareWithMaximumListHeight:maximumListHeight];
	[panel setFrameOrigin:NSMakePoint(-30000, -30000)];
}

// Where the list goes on screen (pure geometry, see the header).
+ (CGFloat)panelTopBelowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible
{
	return MIN(NSMinY(anchorRect), NSMaxY(visible)) - kListGapBelowMenuBar;
}

+ (CGFloat)maximumListHeightBelowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible chromeHeight:(CGFloat)chrome
{
	return [self panelTopBelowRect:anchorRect visibleFrame:visible] - NSMinY(visible) - kListScreenMargin - chrome;
}

+ (NSPoint)panelOriginForSize:(NSSize)size belowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible
{
	CGFloat x = NSMinX(anchorRect);
	x = MIN(x, NSMaxX(visible) - size.width - kListScreenMargin);
	x = MAX(x, NSMinX(visible) + kListScreenMargin);
	return NSMakePoint(x, [self panelTopBelowRect:anchorRect visibleFrame:visible] - size.height);
}

- (void)openBelowRect:(NSRect)anchorRect onScreen:(NSScreen *)screen
{
	if ( open )
		return;
	offscreen = NO;
	[self buildIfNeeded];
	NSRect visible = [(screen ?: [NSScreen mainScreen]) visibleFrame];
	CGFloat chrome = kListPadding + kListSearchHeight + kListSeparatorHeight + [self commandsHeight] + kListPadding;
	[self prepareWithMaximumListHeight:[FlycutListController maximumListHeightBelowRect:anchorRect visibleFrame:visible chromeHeight:chrome]];
	[panel setFrameOrigin:[FlycutListController panelOriginForSize:[panel frame].size belowRect:anchorRect visibleFrame:visible]];
	[panel invalidateShadow];
	// A non-activating panel becomes key without making Flycut the active application,
	// so the user's application stays frontmost and receives the paste (as the bezel).
	[panel makeKeyAndOrderFront:nil];
	[panel makeFirstResponder:searchField];
	[scrollView flashScrollers];
	__block FlycutListController *controller = self;   // not retained (MRC); removed on close
	globalMouseMonitor = [[NSEvent addGlobalMonitorForEventsMatchingMask:NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown | NSEventMaskOtherMouseDown
																handler:^(NSEvent *event) { [controller mouseDownElsewhere:event]; }] retain];
}

// The global monitor: a press that went to another application. On macOS 27 a press on
// the status item is one of them: the menu bar (MenuBarAgent) takes it and hands it to
// Flycut a moment later. That press is the second click and closes the list when it
// arrives, so the monitor leaves it alone. Any other press closes the list; one elsewhere
// in the menu bar may still be handed to the status item, so it may answer this close.
- (void)mouseDownElsewhere:(NSEvent *)event
{
	NSPoint point = [event window] != nil ? [[event window] convertPointToScreen:[event locationInWindow]] : [event locationInWindow];
	NSRect item = NSZeroRect;
	if ( [delegate respondsToSelector:@selector(statusItemFrameForListController:)] )
		item = [delegate statusItemFrameForListController:self];
	if ( !NSIsEmptyRect(item) && NSPointInRect(point, item) )
		return;
	if ( !open )
		return;
	[self close];
	if ( !NSIsEmptyRect(item) && point.y >= NSMinY(item) )
		closeAnswered = NO;
}

- (void)close
{
	if ( !open )
		return;
	open = NO;
	// The same clock as event time stamps (-closeForStatusItemPressAt:). A close by the
	// list itself or by its owner answers no press on the status item.
	closedAt = [[NSProcessInfo processInfo] systemUptime];
	closeAnswered = YES;
	[[[NSWorkspace sharedWorkspace] notificationCenter] removeObserver:self];
	[[NSNotificationCenter defaultCenter] removeObserver:self name:NSMenuDidChangeItemNotification object:nil];
	if ( globalMouseMonitor != nil )
	{
		[NSEvent removeMonitor:globalMouseMonitor];
		[globalMouseMonitor release];
		globalMouseMonitor = nil;
	}
	[panel orderOut:nil];
	[clipList endSession];
	[clipList setSearchString:nil];
	highlightedRow = -1;
	[self highlightCommandAtIndex:-1];
	[delegate listControllerDidClose:self];
}

// Another application became active or the Space changed, or the panel lost key focus:
// the cause may be the press on the status item that is still on its way to Flycut, so
// that press may answer this close (-closeForStatusItemPressAt:).
- (void)closeLeavingItToAPress
{
	if ( !open )
		return;
	[self close];
	closeAnswered = NO;
}

- (void)closeForNotification:(NSNotification *)notification
{
	[self closeLeavingItToAPress];
}

- (void)windowDidResignKey:(NSNotification *)notification
{
	if ( [notification object] == panel )
		[self closeLeavingItToAPress];
}

#pragma mark Rows and highlight

- (FlycutClipListRow *)rowAtIndex:(NSInteger)row
{
	NSArray *rows = [clipList rows];
	if ( row < 0 || row >= (NSInteger)[rows count] )
		return nil;
	return [rows objectAtIndex:row];
}

- (BOOL)isEntryRow:(NSInteger)row
{
	return [self rowAtIndex:row] != nil;
}

- (NSInteger)entryRowFrom:(NSInteger)row step:(NSInteger)step
{
	NSInteger count = (NSInteger)[[clipList rows] count];
	for ( NSInteger r = row ; r >= 0 && r < count ; r += step )
		if ( [self isEntryRow:r] )
			return r;
	return -1;
}

- (void)applyHighlight:(BOOL)highlighted toRow:(NSInteger)row
{
	if ( row < 0 || row >= [tableView numberOfRows] )
		return;
	FlycutListRowView *rowView = [tableView rowViewAtRow:row makeIfNecessary:NO];
	[rowView setListHighlighted:highlighted];
	id view = [tableView viewAtColumn:0 row:row makeIfNecessary:NO];
	if ( [view isKindOfClass:[FlycutListEntryView class]] )
		[(FlycutListEntryView *)view setListHighlighted:highlighted];
}

- (void)setHighlightedRow:(NSInteger)row
{
	if ( ![self isEntryRow:row] )
		row = -1;
	if ( row >= 0 )
		[self highlightCommandAtIndex:-1];   // one highlight in the whole list, as in a menu
	if ( row == highlightedRow )
		return;
	[self applyHighlight:NO toRow:highlightedRow];
	highlightedRow = row;
	[self applyHighlight:YES toRow:highlightedRow];
}

// The command rows below the list take part in the highlight like the rows of a menu.
- (void)highlightCommandAtIndex:(NSInteger)index
{
	if ( index >= (NSInteger)[commandRows count] ||
		 ( index >= 0 && ![[(FlycutListCommandRow *)[commandRows objectAtIndex:index] item] isEnabled] ) )
		index = -1;
	if ( index >= 0 && highlightedRow >= 0 )
	{
		[self applyHighlight:NO toRow:highlightedRow];
		highlightedRow = -1;
	}
	if ( index == highlightedCommand )
		return;
	if ( highlightedCommand >= 0 && highlightedCommand < (NSInteger)[commandRows count] )
		[(FlycutListCommandRow *)[commandRows objectAtIndex:highlightedCommand] setHovered:NO];
	highlightedCommand = index;
	if ( index >= 0 )
		[(FlycutListCommandRow *)[commandRows objectAtIndex:index] setHovered:YES];
}

// The next enabled command row from index on in the direction of step, or -1.
- (NSInteger)enabledCommandFrom:(NSInteger)index step:(NSInteger)step
{
	for ( NSInteger i = index ; i >= 0 && i < (NSInteger)[commandRows count] ; i += step )
		if ( [[(FlycutListCommandRow *)[commandRows objectAtIndex:i] item] isEnabled] )
			return i;
	return -1;
}

- (void)hoverCommandRow:(FlycutListCommandRow *)row
{
	NSUInteger index = [commandRows indexOfObjectIdenticalTo:row];
	if ( index != NSNotFound )
		[self highlightCommandAtIndex:(NSInteger)index];
}

- (void)unhoverCommandRow:(FlycutListCommandRow *)row
{
	if ( highlightedCommand >= 0 && [commandRows indexOfObjectIdenticalTo:row] == (NSUInteger)highlightedCommand )
		[self highlightCommandAtIndex:-1];
}

- (void)showHighlightedRow
{
	if ( highlightedRow >= 0 )
		[tableView scrollRowToVisible:highlightedRow];
}

- (void)reloadRows
{
	highlightedRow = -1;
	[tableView reloadData];
	[self updateEmptyLabel];
	[self fitListToRows];
}

// The stores changed while the list is open, not through the list: a capture that was
// already being read when it opened landed. The rows are rebuilt (a search keeps
// filtering); the highlighted entry stays highlighted, wherever its clipping moved, and
// the list keeps its scroll position.
- (void)storesDidChange
{
	if ( !open )
		return;
	FlycutClipping *highlighted = [[[[self rowAtIndex:highlightedRow] clipping] retain] autorelease];
	NSClipView *clip = [scrollView contentView];
	NSPoint scroll = [clip bounds].origin;
	[clipList reload];
	[self reloadRows];
	CGFloat bottom = MAX((CGFloat)0, NSHeight([tableView frame]) - NSHeight([clip bounds]));
	[clip scrollToPoint:NSMakePoint(scroll.x, MIN(scroll.y, bottom))];
	[scrollView reflectScrolledClipView:clip];
	if ( highlighted != nil )
		[self setHighlightedRow:[clipList rowIndexOfClipping:highlighted]];
}

- (NSInteger)rowUnderMouse
{
	if ( offscreen || panel == nil )
		return -1;
	NSPoint point = [tableView convertPoint:[panel mouseLocationOutsideOfEventStream] fromView:nil];
	if ( !NSPointInRect(point, [tableView visibleRect]) )
		return -1;
	return [tableView rowAtPoint:point];
}

- (void)hoverRow:(NSInteger)row
{
	if ( [self isEntryRow:row] )
		[self setHighlightedRow:row];
}

#pragma mark Press, drag and release from the status item

static NSPoint FlycutListScreenLocation(NSEvent *event)
{
	NSWindow *window = [event window];
	return window != nil ? [window convertPointToScreen:[event locationInWindow]] : [event locationInWindow];
}

- (NSInteger)entryRowAtScreenPoint:(NSPoint)point
{
	NSPoint inTable = [tableView convertPoint:[panel convertPointFromScreen:point] fromView:nil];
	if ( !NSPointInRect(inTable, [tableView visibleRect]) )
		return -1;
	NSInteger row = [tableView rowAtPoint:inTable];
	return [self isEntryRow:row] ? row : -1;
}

- (NSInteger)commandIndexAtScreenPoint:(NSPoint)point
{
	NSPoint inWindow = [panel convertPointFromScreen:point];
	for ( NSUInteger i = 0 ; i < [commandRows count] ; i++ )
	{
		FlycutListCommandRow *row = [commandRows objectAtIndex:i];
		if ( NSPointInRect([row convertPoint:inWindow fromView:nil], [row bounds]) )
			return (NSInteger)i;
	}
	return -1;
}

// A press on the status item opens the list; like a native menu, the list then follows the
// pressed button. While the button is held, the pointer's events still go to the status
// item's window, not to the list (so its hover tracking does not fire); a release on a row
// or an enabled command chooses it. A release anywhere else (on the status item: a plain
// click) leaves the list open. Nothing here activates Flycut.
- (void)trackMouseFromEvent:(NSEvent *)mouseDown
{
	NSEventType type = [mouseDown type];
	if ( !open || ( type != NSEventTypeLeftMouseDown && type != NSEventTypeRightMouseDown ) )
		return;
	BOOL right = ( type == NSEventTypeRightMouseDown );
	NSEventMask mask = right ? ( NSEventMaskRightMouseDragged | NSEventMaskRightMouseUp ) : ( NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp );
	NSEventType upType = right ? NSEventTypeRightMouseUp : NSEventTypeLeftMouseUp;
	NSUInteger button = right ? ( 1 << 1 ) : ( 1 << 0 );
	while ( open )
	{
		// The caller is a local event monitor, whose autorelease pool drains only when the
		// button is up: each turn's event goes with the turn, however long the drag.
		@autoreleasepool
		{
			NSEvent *event = [NSApp nextEventMatchingMask:mask untilDate:[NSDate dateWithTimeIntervalSinceNow:0.25]
												   inMode:NSEventTrackingRunLoopMode dequeue:YES];
			if ( event == nil )
			{
				// The button went up without its event reaching Flycut: stop following it.
				if ( ( [NSEvent pressedMouseButtons] & button ) == 0 )
					return;
				continue;
			}
			NSPoint point = FlycutListScreenLocation(event);
			NSInteger row = [self entryRowAtScreenPoint:point];
			NSInteger command = row < 0 ? [self commandIndexAtScreenPoint:point] : -1;
			if ( [event type] == upType )
			{
				if ( row >= 0 )
					[self chooseRow:row];
				else if ( command >= 0 )
					[self chooseCommand:[(FlycutListCommandRow *)[commandRows objectAtIndex:command] item]];
				return;
			}
			if ( row >= 0 )
				[self setHighlightedRow:row];
			else if ( command >= 0 )
				[self highlightCommandAtIndex:command];
		}
	}
}

#pragma mark Actions

- (void)chooseRow:(NSInteger)row
{
	FlycutClipListRow *entry = [self rowAtIndex:row];
	if ( entry == nil )
		return;
	FlycutClipping *clipping = [[[entry clipping] retain] autorelease];
	FlycutList list = [entry list];
	// Close first: key focus must be back with the user's application before the paste.
	[self close];
	[delegate listController:self didChooseClipping:clipping inList:list];
}

- (void)chooseCommand:(NSMenuItem *)item
{
	if ( ![item isEnabled] || [item isSeparatorItem] )
		return;
	[[item retain] autorelease];
	[self close];
	[delegate listController:self didChooseCommand:item];
}

- (void)toggleFavoriteAtRow:(NSInteger)row
{
	FlycutClipping *clipping = [[[[self rowAtIndex:row] clipping] retain] autorelease];
	if ( clipping == nil || ![clipList toggleFavoriteOfClipping:clipping] )
		return;
	[self reloadRows];
	// The list stays where it is; the highlight follows the pointer if it is over a row.
	NSInteger under = [self rowUnderMouse];
	[self setHighlightedRow:[self isEntryRow:under] ? under : [clipList rowIndexOfClipping:clipping]];
}

- (void)deleteRow:(NSInteger)row
{
	FlycutClipping *clipping = [[self rowAtIndex:row] clipping];
	if ( clipping == nil || ![clipList deleteClipping:clipping] )
		return;
	[self reloadRows];
	// The highlight stays on the row that moves up into the place, as in a menu.
	NSInteger next = [self entryRowFrom:row step:1];
	if ( next < 0 )
		next = [self entryRowFrom:row - 1 step:-1];
	[self setHighlightedRow:next];
	[self showHighlightedRow];
}

- (void)undo
{
	FlycutClipping *clipping = [clipList undo];
	[self reloadRows];
	if ( clipping != nil )
	{
		[self setHighlightedRow:[clipList rowIndexOfClipping:clipping]];
		[self showHighlightedRow];
	}
}

- (void)starButtonClicked:(id)sender
{
	[self toggleFavoriteAtRow:[tableView rowForView:sender]];
}

- (void)trashButtonClicked:(id)sender
{
	[self deleteRow:[tableView rowForView:sender]];
}

// VoiceOver's Move Up and Move Down on a favorite: one place, as a drag would move it.
- (BOOL)moveFavorite:(FlycutClipping *)clipping by:(NSInteger)step
{
	NSInteger row = [clipList rowIndexOfClipping:clipping];
	if ( row < 0 || ![clipList dropClipping:clipping aboveRow:step < 0 ? row - 1 : row + 2] )
		return NO;
	[self reloadRows];
	[self setHighlightedRow:[clipList rowIndexOfClipping:clipping]];
	[self showHighlightedRow];
	return YES;
}

- (void)searchTextChanged
{
	NSString *text = [searchField stringValue];
	[clipList setSearchString:text];
	[clipList reload];
	[self reloadRows];
	[tableView scrollRowToVisible:0];
	// Typing highlights the first match, so Return pastes it.
	[self highlightCommandAtIndex:-1];
	if ( [text length] > 0 )
		[self setHighlightedRow:[self entryRowFrom:0 step:1]];
}

// Arrows move over the entries and on into the enabled command rows below them, as in a
// menu; they stop at either end.
- (void)stepHighlightBy:(NSInteger)step
{
	NSInteger count = (NSInteger)[[clipList rows] count];
	if ( highlightedCommand >= 0 )
	{
		NSInteger command = [self enabledCommandFrom:highlightedCommand + step step:step > 0 ? 1 : -1];
		NSInteger row = ( command < 0 && step < 0 ) ? [self entryRowFrom:count - 1 step:-1] : -1;
		if ( command >= 0 )
			[self highlightCommandAtIndex:command];
		else if ( row >= 0 )
		{
			[self setHighlightedRow:row];
			[self showHighlightedRow];
		}
		return;
	}
	NSInteger row;
	if ( highlightedRow < 0 )
		row = step > 0 ? [self entryRowFrom:0 step:1] : [self entryRowFrom:count - 1 step:-1];
	else
		row = [self entryRowFrom:highlightedRow + step step:step > 0 ? 1 : -1];
	if ( row >= 0 )
	{
		[self setHighlightedRow:row];
		[self showHighlightedRow];
		return;
	}
	// Past the last entry, or no entries at all: the commands.
	if ( step > 0 )
		[self highlightCommandAtIndex:[self enabledCommandFrom:0 step:1]];
	else if ( highlightedRow < 0 )
		[self highlightCommandAtIndex:[self enabledCommandFrom:(NSInteger)[commandRows count] - 1 step:-1]];
}

- (void)stepHighlightByPage:(NSInteger)direction
{
	NSInteger count = (NSInteger)[[clipList rows] count];
	// From a command row only Page Up leads anywhere: back into the list.
	if ( highlightedCommand >= 0 && ( direction > 0 || count == 0 ) )
		return;
	NSInteger rowsPerPage = MAX((NSInteger)1, (NSInteger)floor(NSHeight([scrollView frame]) / kListRowHeight) - 1);
	NSInteger start = highlightedCommand >= 0 ? count : highlightedRow < 0 ? 0 : highlightedRow;
	NSInteger target = MIN(MAX(start + direction * rowsPerPage, (NSInteger)0), count - 1);
	NSInteger row = [self entryRowFrom:target step:direction > 0 ? 1 : -1];
	if ( row < 0 )
		row = [self entryRowFrom:target step:direction > 0 ? -1 : 1];
	[self setHighlightedRow:row];
	[self showHighlightedRow];
}

// VoiceOver stays on the search field, where the keys go, so a highlight moved by key is
// announced. Pointer moves are not: VoiceOver reads what is under its own cursor.
- (void)announceHighlight
{
	NSMenuItem *command = [self highlightedCommand];
	FlycutClipListRow *row = [self rowAtIndex:highlightedRow];
	FlycutClipping *clipping = [row clipping];
	NSString *text = command != nil ? [command title] :
		clipping != nil ? ( [delegate listController:self titleForClipping:clipping] ?: [clipping displayString] ) : nil;
	if ( command == nil && [clipping isImageClipping] )
		text = FlycutListSpokenImageTitle(text);
	if ( command == nil && [row list] == FlycutListFavorites && [text length] > 0 )
		text = FlycutListFavoriteLabel(text);
	if ( [text length] == 0 )
		return;
	NSAccessibilityPostNotificationWithUserInfo(panel, NSAccessibilityAnnouncementRequestedNotification,
		@{NSAccessibilityAnnouncementKey: text, NSAccessibilityPriorityKey: @(NSAccessibilityPriorityHigh)});
}

- (void)moveHighlightBy:(NSInteger)step
{
	NSInteger row = highlightedRow, command = highlightedCommand;
	[self stepHighlightBy:step];
	if ( row != highlightedRow || command != highlightedCommand )
		[self announceHighlight];
}

- (void)moveHighlightByPage:(NSInteger)direction
{
	NSInteger row = highlightedRow, command = highlightedCommand;
	[self stepHighlightByPage:direction];
	if ( row != highlightedRow || command != highlightedCommand )
		[self announceHighlight];
}

- (void)handleCancel
{
	if ( [[searchField stringValue] length] > 0 )
	{
		[searchField setStringValue:@""];
		[self searchTextChanged];
	}
	else
		[self close];
}

- (BOOL)handleKeyEquivalent:(NSEvent *)event
{
	if ( !open || [event type] != NSEventTypeKeyDown )
		return NO;
	// Forward Delete and the arrows carry the Function flag; compare only real modifiers.
	NSEventModifierFlags flags = [event modifierFlags] & (NSEventModifierFlagCommand | NSEventModifierFlagShift |
														 NSEventModifierFlagOption | NSEventModifierFlagControl);
	NSString *characters = [event charactersIgnoringModifiers];
	unichar key = [characters length] > 0 ? [characters characterAtIndex:0] : 0;
	if ( flags == NSEventModifierFlagCommand )
	{
		if ( key == 'z' )
		{
			[self undo];
			return YES;
		}
		// Cmd-Delete (as "Move to Trash" in the Finder) and Cmd-Forward-Delete delete the
		// highlighted row; the search text is left alone.
		if ( key == NSDeleteCharacter || key == NSBackspaceCharacter || key == NSDeleteFunctionKey )
		{
			[self deleteRow:highlightedRow];
			return YES;
		}
		SEL edit = key == 'a' ? @selector(selectAll:) : key == 'c' ? @selector(copy:) :
				   key == 'v' ? @selector(paste:) : key == 'x' ? @selector(cut:) : NULL;
		if ( edit != NULL )
			return [[panel firstResponder] tryToPerform:edit with:self];
	}
	for ( NSMenuItem *item in commandItems )
	{
		NSString *equivalent = [item keyEquivalent];
		NSEventModifierFlags mask = [item keyEquivalentModifierMask] & (NSEventModifierFlagCommand | NSEventModifierFlagShift |
																		NSEventModifierFlagOption | NSEventModifierFlagControl);
		if ( [equivalent length] > 0 && mask == flags && [equivalent caseInsensitiveCompare:characters] == NSOrderedSame )
		{
			[self chooseCommand:item];
			return YES;
		}
	}
	return NO;
}

// Keys typed into the search field arrive here as key-binding commands.
- (BOOL)control:(NSControl *)control textView:(NSTextView *)textView doCommandBySelector:(SEL)command
{
	if ( command == @selector(moveDown:) ) { [self moveHighlightBy:1]; return YES; }
	if ( command == @selector(moveUp:) ) { [self moveHighlightBy:-1]; return YES; }
	if ( command == @selector(scrollPageDown:) || command == @selector(pageDown:) ) { [self moveHighlightByPage:1]; return YES; }
	if ( command == @selector(scrollPageUp:) || command == @selector(pageUp:) ) { [self moveHighlightByPage:-1]; return YES; }
	if ( command == @selector(insertNewline:) )
	{
		NSMenuItem *item = [self highlightedCommand];
		if ( item != nil )
			[self chooseCommand:item];
		else
			[self chooseRow:highlightedRow];
		return YES;
	}
	if ( command == @selector(cancelOperation:) ) { [self handleCancel]; return YES; }
	if ( command == @selector(deleteToBeginningOfLine:) ) { [self deleteRow:highlightedRow]; return YES; }
	return NO;
}

- (void)controlTextDidChange:(NSNotification *)notification
{
	[self searchTextChanged];
}

#pragma mark Table

- (NSInteger)numberOfRowsInTableView:(NSTableView *)aTableView
{
	return (NSInteger)[[clipList rows] count];
}

- (CGFloat)tableView:(NSTableView *)aTableView heightOfRow:(NSInteger)row
{
	return [self rowHeightAtIndex:row];
}

- (BOOL)tableView:(NSTableView *)aTableView shouldSelectRow:(NSInteger)row
{
	return NO;
}

- (BOOL)tableView:(NSTableView *)aTableView isGroupRow:(NSInteger)row
{
	return NO;
}

- (NSTableRowView *)tableView:(NSTableView *)aTableView rowViewForRow:(NSInteger)row
{
	FlycutListRowView *rowView = [[[FlycutListRowView alloc] initWithFrame:NSMakeRect(0, 0, kListWidth, [self rowHeightAtIndex:row])] autorelease];
	[rowView setListHighlighted:row == highlightedRow];
	return rowView;
}

- (NSArray *)customActionsForRow:(FlycutClipListRow *)row atIndex:(NSInteger)index
{
	__block FlycutListController *controller = self;   // not retained (MRC)
	FlycutClipping *clipping = [row clipping];
	NSString *starName = [row list] == FlycutListFavorites ? FlycutListRemoveFromFavorites : FlycutListAddToFavorites;
	NSAccessibilityCustomAction *star = [[[NSAccessibilityCustomAction alloc] initWithName:starName handler:^BOOL{
		NSInteger index = [[controller clipList] rowIndexOfClipping:clipping];
		[controller toggleFavoriteAtRow:index];
		return index >= 0;
	}] autorelease];
	NSAccessibilityCustomAction *delete = [[[NSAccessibilityCustomAction alloc] initWithName:FlycutListDelete handler:^BOOL{
		NSInteger index = [[controller clipList] rowIndexOfClipping:clipping];
		[controller deleteRow:index];
		return index >= 0;
	}] autorelease];
	NSMutableArray *actions = [NSMutableArray arrayWithObjects:star, delete, nil];
	// Reordering the favorites without a drag: VoiceOver and keyboard users.
	if ( [row list] == FlycutListFavorites && index > 0 )
		[actions addObject:[[[NSAccessibilityCustomAction alloc] initWithName:FlycutListMoveUp handler:^BOOL{
			return [controller moveFavorite:clipping by:-1];
		}] autorelease]];
	if ( [row list] == FlycutListFavorites && index < [clipList favoriteRowCount] - 1 )
		[actions addObject:[[[NSAccessibilityCustomAction alloc] initWithName:FlycutListMoveDown handler:^BOOL{
			return [controller moveFavorite:clipping by:1];
		}] autorelease]];
	return actions;
}

- (NSView *)tableView:(NSTableView *)aTableView viewForTableColumn:(NSTableColumn *)column row:(NSInteger)row
{
	FlycutClipListRow *entry = [self rowAtIndex:row];
	NSRect frame = NSMakeRect(0, 0, column != nil ? [column width] : kListWidth, [self rowHeightAtIndex:row]);
	FlycutListEntryView *view = [aTableView makeViewWithIdentifier:@"FlycutListEntry" owner:self];
	if ( view == nil )
	{
		view = [[[FlycutListEntryView alloc] initWithFrame:frame target:self] autorelease];
		[view setIdentifier:@"FlycutListEntry"];
	}
	FlycutClipping *clipping = [entry clipping];
	NSString *title = [delegate listController:self titleForClipping:clipping] ?: [clipping displayString];
	[view configureWithTitle:title image:[clipping isImageClipping] favorite:[entry list] == FlycutListFavorites
				 highlighted:row == highlightedRow];
	[view setAccessibilityCustomActions:[self customActionsForRow:entry atIndex:row]];
	return view;
}

#pragma mark Dragging rows

// A click on a row (released within the drag threshold) chooses it, as in a menu. A press
// that became a drag does not: the drag session takes the release.
- (void)tableViewClicked:(id)sender
{
	NSInteger row = [tableView clickedRow];
	if ( [self isEntryRow:row] )
		[self chooseRow:row];
}

// The press moved past the drag threshold: the row's content goes on the drag. Dragging
// never pastes, deletes or moves a clipping by itself; only a drop on the list does.
- (id<NSPasteboardWriting>)tableView:(NSTableView *)aTableView pasteboardWriterForRow:(NSInteger)row
{
	FlycutClipping *clipping = [[self rowAtIndex:row] clipping];
	if ( clipping == nil )
		return nil;
	id<NSPasteboardWriting> writer = nil;
	if ( [clipping isImageClipping] )
	{
		NSString *type = [[clipping type] length] > 0 ? [clipping type] : NSPasteboardTypeTIFF;
		NSData *data = [[FlycutImageStore sharedStore] imageDataForHash:[clipping imageHash]];
		if ( data == nil )
			return nil;
		writer = [[[FlycutListImageDragItem alloc] initWithImageData:data type:type
															fileName:FlycutListImageFileName(clipping, type)] autorelease];
	}
	else
		writer = FlycutListTextDragItem(clipping);
	[draggedClipping release];
	draggedClipping = [clipping retain];
	droppedInList = NO;
	// The drag image is a picture of the row's view, without the highlight the row draws
	// behind it: a highlighted row's white title would vanish on a light window.
	if ( row == highlightedRow )
		[self setHighlightedRow:-1];
	return writer;
}

- (void)tableView:(NSTableView *)aTableView draggingSession:(NSDraggingSession *)session endedAtPoint:(NSPoint)screenPoint operation:(NSDragOperation)operation
{
	BOOL droppedHere = droppedInList;
	[draggedClipping release];
	draggedClipping = nil;
	droppedInList = NO;
	// Dropped in another application or the Finder: as after choosing a row, the list
	// closes, and typing goes to the user's application again. A cancelled drag, or one
	// dropped on the list or its search field, leaves it open.
	if ( open && !droppedHere && operation != NSDragOperationNone && !NSPointInRect(screenPoint, [panel frame]) )
		[self close];
}

// Only rows dragged from this list, and only between rows of the favorites block. With the
// gap style AppKit proposes a drop above a row first, and on a row only when that was
// refused, so a refused position shows no indicator at all.
- (NSDragOperation)tableView:(NSTableView *)aTableView validateDrop:(id<NSDraggingInfo>)info proposedRow:(NSInteger)row proposedDropOperation:(NSTableViewDropOperation)operation
{
	if ( [info draggingSource] != tableView || draggedClipping == nil || operation != NSTableViewDropAbove ||
		 ![clipList canDropClipping:draggedClipping aboveRow:row] )
		return NSDragOperationNone;
	return NSDragOperationMove;
}

- (BOOL)tableView:(NSTableView *)aTableView acceptDrop:(id<NSDraggingInfo>)info row:(NSInteger)row dropOperation:(NSTableViewDropOperation)operation
{
	if ( [self tableView:aTableView validateDrop:info proposedRow:row proposedDropOperation:operation] == NSDragOperationNone )
		return NO;
	FlycutClipping *clipping = [[draggedClipping retain] autorelease];
	droppedInList = YES;
	if ( [clipList dropClipping:clipping aboveRow:row] )
	{
		[self reloadRows];
		[self setHighlightedRow:[clipList rowIndexOfClipping:clipping]];
	}
	return YES;
}

@end
