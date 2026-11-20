// Native probe for MenuListPanelTests.py: the real menu-bar list panel, driven by keys.
//
// Compiles the real FlycutClipping, FlycutStore, FlycutOperator, FlycutClipList and
// FlycutListPanel sources. The panel is laid out but never ordered on screen; key events
// are NSEvent objects handed to it the way -[NSApplication sendEvent:] routes them to a
// key window (Command combinations to -performKeyEquivalent: first). Nothing is posted
// to the system. FixtureIsolation.h keeps defaults in memory; the image store records
// deletions in memory; activation and window ordering are counted, never performed.
// Prints one JSON object (the step log) on stdout; exit status = number of failures.

#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import "FixtureIsolation.h"

#define DLog(...) do {} while (0)
// VoiceOver announcements the panel requests are recorded here, never posted.
static NSMutableArray *gAnnouncements;
static void FCRecordAccessibilityPost(id element, NSAccessibilityNotificationName name, NSDictionary *info) {
    if ([name isEqualToString:NSAccessibilityAnnouncementRequestedNotification])
        [gAnnouncements addObject:[info objectForKey:NSAccessibilityAnnouncementKey] ?: @""];
}
#define NSAccessibilityPostNotificationWithUserInfo FCRecordAccessibilityPost
#include "FlycutEngine/FlycutClipping.m"
#include "FlycutEngine/FlycutStore.m"
#include "FlycutOperator.m"
#include "FlycutClipList.m"
#include "UI/FlycutListPanel.m"
#undef NSAccessibilityPostNotificationWithUserInfo

static NSMutableArray *gDeletedImages;
@implementation FlycutImageStore
+ (FlycutImageStore *)sharedStore {
    static FlycutImageStore *shared = nil;
    if (shared == nil) shared = [FlycutImageStore alloc];   // never -init: no directory
    return shared;
}
+ (NSString *)fileExtensionForType:(NSString *)uti { return @"png"; }
- (void)deleteImageForHash:(NSString *)hash { [gDeletedImages addObject:hash]; }
- (void)persistMemoryOnlyImageForHash:(NSString *)hash {}
// Dummy bytes per image, so a drag's data can be compared with what the store holds.
- (NSData *)imageDataForHash:(NSString *)hash { return [[@"image bytes of " stringByAppendingString:hash] dataUsingEncoding:NSUTF8StringEncoding]; }
- (BOOL)hasImageForHash:(NSString *)hash { return YES; }
@end

@interface FCProbeOperator : FlycutOperator
- (FlycutStore *)history;
- (FlycutStore *)favorites;
@end
@implementation FCProbeOperator
- (FlycutStore *)history { return clippingStore; }
- (FlycutStore *)favorites { return favoritesStore; }
- (bool)saveFromStore:(FlycutStore *)store atIndex:(int)index withPrefix:(NSString *)prefix {
    fprintf(stderr, "FAIL: probe reached the autosave export\n");
    abort();
}
@end

@interface FCProbeDelegate : NSObject <FlycutListControllerDelegate> {
@public
    int opened, closed;
    FlycutClipping *chosen;
    NSInteger chosenList;
    NSMenuItem *command;
    NSMenuItem *retitleOnOpen;   // as -menuWillOpen: updates the Pause item when the list opens
    NSString *titleOnOpen;
}
@end
@implementation FCProbeDelegate
- (NSString *)listController:(FlycutListController *)c titleForClipping:(FlycutClipping *)clipping { return [clipping displayString]; }
- (void)listController:(FlycutListController *)c didChooseClipping:(FlycutClipping *)clipping inList:(FlycutList)list {
    if ([c isOpen]) { fprintf(stderr, "FAIL: clipping chosen while the list is still open\n"); exit(90); }
    [chosen release]; chosen = [clipping retain]; chosenList = list;
}
- (void)listController:(FlycutListController *)c didChooseCommand:(NSMenuItem *)item {
    if ([c isOpen]) { fprintf(stderr, "FAIL: command chosen while the list is still open\n"); exit(91); }
    [command release]; command = [item retain];
}
- (void)listControllerDidOpen:(FlycutListController *)c {
    opened++;
    if (retitleOnOpen != nil) [retitleOnOpen setTitle:titleOnOpen];
}
- (void)listControllerDidClose:(FlycutListController *)c { closed++; }
- (void)noop:(id)sender {}
@end

static int gActivations, gOrderFront;
static void CountActivation(id self, SEL _cmd, ...) { gActivations++; }
static BOOL CountActivationBOOL(id self, SEL _cmd, ...) { gActivations++; return NO; }
static void CountOrderFront(id self, SEL _cmd, ...) { gOrderFront++; }
// NSWorkspace's notifications come from a private center (the probe posts there), so an
// application becoming active elsewhere in the session cannot close the list under the probe.
static NSNotificationCenter *gWorkspaceCenter;
static id PrivateWorkspaceCenter(id self, SEL _cmd) { return gWorkspaceCenter; }
static void Swizzle(Class cls, const char *name, IMP imp) {
    Method m = class_getInstanceMethod(cls, sel_registerName(name));
    if (m) method_setImplementation(m, imp);
}

// Each drag event the tracking loop reads gets a spy object that counts how many of
// those events are still alive (retained by an autorelease pool or anyone else).
static IMP gNextEvent;
static BOOL gSpyEvents;
static int gSpiesAlive, gSpiesMaxAlive, gSpiesMade;
@interface FCEventSpy : NSObject
@end
@implementation FCEventSpy
- (void)dealloc { gSpiesAlive--; [super dealloc]; }
@end
static char kEventSpyKey;
static NSEvent *SpyNextEvent(id self, SEL _cmd, NSEventMask mask, NSDate *until, NSRunLoopMode mode, BOOL dequeue) {
    if (gSpyEvents && gSpiesAlive > gSpiesMaxAlive) gSpiesMaxAlive = gSpiesAlive;
    NSEvent *event = ((NSEvent *(*)(id, SEL, NSEventMask, NSDate *, NSRunLoopMode, BOOL))gNextEvent)(self, _cmd, mask, until, mode, dequeue);
    if (gSpyEvents && event != nil && [event type] == NSEventTypeLeftMouseDragged) {
        FCEventSpy *spy = [[FCEventSpy alloc] init];
        gSpiesAlive++; gSpiesMade++;
        objc_setAssociatedObject(event, &kEventSpyKey, spy, OBJC_ASSOCIATION_RETAIN);
        [spy release];
    }
    return event;
}

// Drag sessions are never started: -[NSView beginDraggingSessionWithItems:event:source:]
// records the request and returns nil. (A session would need the window server's drag
// pasteboard; the test sandbox denies the pasteboard server anyway.)
static int gDragBegins;
static NSArray *gDragItems;
static NSView *gDragView;
static id RecordDragBegin(id self, SEL _cmd, NSArray *items, NSEvent *event, id source) {
    gDragBegins++;
    [gDragItems release];
    gDragItems = [items copy];
    gDragView = self;
    return nil;
}

// What a drag moving over the list hands NSTableView (no session, no pasteboard server):
// the source, the pointer and a pasteboard that offers the list's row type.
@interface FCFakeDragPasteboard : NSObject
@end
@implementation FCFakeDragPasteboard
- (NSArray *)types { return @[@"com.generalarcade.flycut.list-row"]; }
- (NSString *)availableTypeFromArray:(NSArray *)types { return [types containsObject:@"com.generalarcade.flycut.list-row"] ? @"com.generalarcade.flycut.list-row" : nil; }
- (BOOL)canReadItemWithDataConformingToTypes:(NSArray *)types { return [self availableTypeFromArray:types] != nil; }
- (NSArray *)pasteboardItems { return @[]; }
@end
@interface FCFakeDraggingInfo : NSObject <NSDraggingInfo> {
@public
    NSWindow *window;
    NSPoint location;   // window coordinates
    id source;
    FCFakeDragPasteboard *pasteboard;
}
@end
@implementation FCFakeDraggingInfo
@synthesize draggingFormation, animatesToDestination, numberOfValidItemsForDrop;
- (NSWindow *)draggingDestinationWindow { return window; }
- (NSDragOperation)draggingSourceOperationMask { return NSDragOperationMove; }
- (NSPoint)draggingLocation { return location; }
- (NSPoint)draggedImageLocation { return location; }
- (NSImage *)draggedImage { return nil; }
- (NSPasteboard *)draggingPasteboard { return (NSPasteboard *)pasteboard; }
- (id)draggingSource { return source; }
- (NSInteger)draggingSequenceNumber { return 1; }
- (void)slideDraggedImageTo:(NSPoint)screenPoint {}
- (NSArray *)namesOfPromisedFilesDroppedAtDestination:(NSURL *)dropDestination { return nil; }
- (void)enumerateDraggingItemsWithOptions:(NSDraggingItemEnumerationOptions)options forView:(NSView *)view classes:(NSArray *)classes
                            searchOptions:(NSDictionary *)searchOptions usingBlock:(void (^)(NSDraggingItem *, NSInteger, BOOL *))block {}
- (NSSpringLoadingHighlight)springLoadingHighlight { return NSSpringLoadingHighlightNone; }
- (void)resetSpringLoading {}
@end

static NSEvent *Key(NSString *chars, unsigned short code, NSEventModifierFlags flags) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0
                        windowNumber:0 context:nil characters:chars charactersIgnoringModifiers:chars
                           isARepeat:NO keyCode:code];
}
static NSString *Char(unichar c) { return [NSString stringWithCharacters:&c length:1]; }

static int failures;
static NSMutableArray *gSteps;
static NSMutableArray *gChecks;
static void Check(BOOL ok, NSString *what, NSString *detail) {
    [gChecks addObject:@{@"check": what, @"pass": @(ok), @"detail": detail ?: @""}];
    if (!ok) { failures++; fprintf(stderr, "FAIL: %s %s\n", [what UTF8String], [detail ?: @"" UTF8String]); }
}

static FlycutListController *gController;

// On screen the open list's panel is key (-openBelowRect:onScreen: makes it key). Offscreen
// it cannot become key, and NSTableView ignores a press in a window that could become key
// but is not (measured: it only peeks at the press's events). So the open list's panel
// reports itself key, as it is on screen.
static IMP gIsKeyWindow;
static BOOL ProbeIsKeyWindow(id self, SEL _cmd) {
    if (gController != nil && self == (id)[gController panel] && [gController isOpen]) return YES;
    return ((BOOL (*)(id, SEL))gIsKeyWindow)(self, _cmd);
}
static NSString *HighlightedText(void) {
    NSInteger r = [gController highlightedRow];
    NSArray *rows = [[gController clipList] rows];
    if (r < 0 || r >= (NSInteger)[rows count]) return @"(none)";
    FlycutClipping *c = [[rows objectAtIndex:r] clipping];
    return c ? [c displayString] : @"(not an entry)";
}

// What VoiceOver is told for the highlighted row: the row's text; an image row's size text is
// spoken as "Image 1280 by 720" (every image of this fixture is 1280 x 720).
static NSString *AnnouncedText(void) {
    NSString *text = HighlightedText();
    return [text isEqualToString:@"[Image 1280x720]"] ? @"Image 1280 by 720" : text;
}

static void Send(NSString *label, NSEvent *event);

// The highlighted command row (nil when none), asked only if the controller has the API.
static NSMenuItem *HighlightedCommand(void) {
    SEL getter = sel_registerName("highlightedCommand");
    return [gController respondsToSelector:getter] ? [gController performSelector:getter] : nil;
}
static NSString *CommandText(void) {
    NSMenuItem *item = HighlightedCommand();
    return item ? [item title] : @"(none)";
}
static void CollectCommandRows(NSView *view, NSMutableArray *rows) {
    if ([view isKindOfClass:[FlycutListCommandRow class]]) [rows addObject:view];
    for (NSView *sub in [view subviews]) CollectCommandRows(sub, rows);
}
static FlycutListCommandRow *CommandRow(NSString *title) {
    NSMutableArray *rows = [NSMutableArray array];
    CollectCommandRows([[gController panel] contentView], rows);
    for (FlycutListCommandRow *row in rows)
        if ([[(NSMenuItem *)[row valueForKey:@"item"] title] isEqualToString:title]) return row;
    return nil;
}
static BOOL CommandRowHovered(NSString *title) { return [[CommandRow(title) valueForKey:@"hovered"] boolValue]; }
static FlycutListCommandRow *CommandRowForItem(NSMenuItem *item) {
    NSMutableArray *rows = [NSMutableArray array];
    CollectCommandRows([[gController panel] contentView], rows);
    for (FlycutListCommandRow *row in rows)
        if ([row valueForKey:@"item"] == item) return row;
    return nil;
}

static void Send(NSString *label, NSEvent *event) {
    FlycutListPanel *panel = [gController panel];
    BOOL viaEquivalent = NO;
    if ([event modifierFlags] & NSEventModifierFlagCommand) viaEquivalent = [panel performKeyEquivalent:event];
    if (!viaEquivalent) [panel sendEvent:event];
    [gSteps addObject:@{@"key": label, @"via": viaEquivalent ? @"performKeyEquivalent:" : @"sendEvent:",
                        @"search": [[gController searchField] stringValue] ?: @"",
                        @"rows": @([[[gController clipList] rows] count]), @"highlighted_row": @([gController highlightedRow]),
                        @"highlighted": HighlightedText(), @"command": CommandText(), @"open": @([gController isOpen]),
                        @"app_active": @([NSApp isActive]), @"panel_visible": @([panel isVisible])}];
}

static NSString *const kDown = @"Down", *const kUp = @"Up";
static void Down(void) { Send(kDown, Key(Char(NSDownArrowFunctionKey), 125, NSEventModifierFlagFunction | NSEventModifierFlagNumericPad)); }
static void Up(void) { Send(kUp, Key(Char(NSUpArrowFunctionKey), 126, NSEventModifierFlagFunction | NSEventModifierFlagNumericPad)); }
static void CmdDelete(void) { Send(@"Cmd-Delete", Key(Char(NSDeleteCharacter), 51, NSEventModifierFlagCommand)); }
static void CmdForwardDelete(void) { Send(@"Cmd-ForwardDelete", Key(Char(NSDeleteFunctionKey), 117, NSEventModifierFlagCommand | NSEventModifierFlagFunction)); }
static void CmdZ(void) { Send(@"Cmd-Z", Key(@"z", 6, NSEventModifierFlagCommand)); }
static void Esc(void) { Send(@"Esc", Key(@"\x1b", 53, 0)); }
static void Return(void) { Send(@"Return", Key(@"\r", 36, 0)); }
static void Type(NSString *text) {
    for (NSUInteger i = 0; i < [text length]; i++) {
        NSString *c = [text substringWithRange:NSMakeRange(i, 1)];
        Send(c, Key(c, 11, 0));   // keyCode is not used for typing; never 0 (see bezel tests)
    }
}

static FlycutClipping *Clip(NSString *text, NSInteger ts) {
    return [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString withDisplayLength:40
                                withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:ts] autorelease];
}

static NSArray *HistoryTexts(void) {
    return @[@"Einkaufsliste: Milch, Brot, Äpfel, Käse", @"Termin verschoben auf Donnerstag, 14 Uhr",
             @"https://example.test/artikel/42?ref=menue", @"beta zwei", @"[image]", @"Lorem ipsum dolor sit amet",
             @"Rechnung Nr. 2026-0815 (Beispiel)", @"beta vier", @"SELECT name FROM beispiel WHERE id = 7;"];
}

static void Open(void) { [gController openOffscreenWithMaximumListHeight:2000]; }

static FlycutListEntryView *EntryView(NSInteger row) {
    id v = [[gController tableView] viewAtColumn:0 row:row makeIfNecessary:YES];
    return [v isKindOfClass:[FlycutListEntryView class]] ? v : nil;
}

static BOOL SameColor(NSColor *a, NSColor *b) { return a == b || [a isEqual:b]; }

// Pixel-level alignment (sight test of the v4 renders): the panel's content drawn
// offscreen at 2x (rows top-down = the content view's flipped points), and the ink of one
// glyph found in a band of it. The background is the colour at bgPoint; a pixel column is
// ink where some pixel of the band deviates from it by at least 30% of the strongest
// deviation in the range, so both antialiased edges count alike. Returns the first ink run
// from the left as {left, right, next run's left} in points, or nil.
static NSBitmapImageRep *DrawPanel(NSView *content) {
    NSRect b = [content bounds];
    NSBitmapImageRep *rep = [[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:(NSInteger)NSWidth(b) * 2
        pixelsHigh:(NSInteger)NSHeight(b) * 2 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO
        colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0] autorelease];
    [rep setSize:b.size];
    [content cacheDisplayInRect:b toBitmapImageRep:rep];
    return rep;
}
static NSArray *FirstInk(NSBitmapImageRep *rep, CGFloat x0pt, CGFloat x1pt, NSRect band, NSPoint bgPoint) {
    NSInteger x0 = (NSInteger)ceil(x0pt * 2), x1 = (NSInteger)floor(x1pt * 2);
    NSInteger y0 = (NSInteger)ceil((NSMinY(band) + 3) * 2), y1 = (NSInteger)floor((NSMaxY(band) - 3) * 2);
    NSUInteger bg[5] = {0};
    [rep getPixel:bg atX:(NSInteger)(bgPoint.x * 2) y:(NSInteger)(bgPoint.y * 2)];
    CGFloat dev[2048] = {0}, peak = 0;
    for (NSInteger x = x0; x < x1 && x - x0 < 2048; x++) {
        for (NSInteger y = y0; y < y1; y++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            for (int c = 0; c < 3; c++) dev[x - x0] = MAX(dev[x - x0], fabs((CGFloat)p[c] - (CGFloat)bg[c]));
        }
        peak = MAX(peak, dev[x - x0]);
    }
    if (peak < 16) return nil;
    NSMutableArray *runs = [NSMutableArray array];
    NSInteger start = -1;
    for (NSInteger x = x0; x <= x1 && [runs count] < 2; x++) {
        BOOL ink = x < x1 && dev[x - x0] >= 0.3 * peak;
        if (ink && start < 0) start = x;
        if (!ink && start >= 0) { [runs addObject:@[@(start / 2.0), @(x / 2.0)]]; start = -1; }
    }
    if ([runs count] == 0) return nil;
    return @[runs[0][0], runs[0][1], [runs count] > 1 ? runs[1][0] : @(NAN)];
}

// Sight tests: the picture emoji instead of the eye, and as large as the same emoji copied as
// text. An image row starts with the picture emoji U+1F5BC U+FE0F, one space,
// then the size text. Measured on the drawn ink like the stars: where its columns and rows lie, and
// whether it has the colours of the emoji (warm pixels of its golden frame: red clearly above
// blue; nothing a template image or the text draws, neither on the menu's grey nor on the
// highlight's blue).
static NSString *const kPictureEmoji = @"\U0001F5BC\uFE0F";
// Rows (points from the top of the band) of the ink in the columns of a run FirstInk found:
// {top, bottom}, same 30% rule, 1 pt inside the band's edges.
static NSArray *InkRowsOfRun(NSBitmapImageRep *rep, NSArray *run, NSRect band, NSPoint bgPoint) {
    NSInteger x0 = (NSInteger)round([run[0] doubleValue] * 2), x1 = (NSInteger)round([run[1] doubleValue] * 2);
    NSInteger y0 = (NSInteger)ceil((NSMinY(band) + 1) * 2), y1 = (NSInteger)floor((NSMaxY(band) - 1) * 2);
    NSUInteger bg[5] = {0};
    [rep getPixel:bg atX:(NSInteger)(bgPoint.x * 2) y:(NSInteger)(bgPoint.y * 2)];
    CGFloat peak = 0;
    for (NSInteger y = y0; y < y1; y++)
        for (NSInteger x = x0; x < x1; x++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            for (int c = 0; c < 3; c++) peak = MAX(peak, fabs((CGFloat)p[c] - (CGFloat)bg[c]));
        }
    if (peak < 16) return nil;
    NSInteger top = -1, bottom = -1;
    for (NSInteger y = y0; y < y1; y++) {
        BOOL ink = NO;
        for (NSInteger x = x0; x < x1 && !ink; x++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            for (int c = 0; c < 3; c++) if (fabs((CGFloat)p[c] - (CGFloat)bg[c]) >= 0.3 * peak) ink = YES;
        }
        if (ink) { if (top < 0) top = y; bottom = y; }
    }
    return top < 0 ? nil : @[@(top / 2.0), @((bottom + 1) / 2.0)];
}
// Pixels in the columns [x0pt, x1pt) of a band that are clearly warm (red >= blue + 40).
static NSUInteger WarmPixels(NSBitmapImageRep *rep, CGFloat x0pt, CGFloat x1pt, NSRect band) {
    NSUInteger warm = 0;
    for (NSInteger y = (NSInteger)ceil(NSMinY(band) * 2); y < (NSInteger)floor(NSMaxY(band) * 2); y++)
        for (NSInteger x = (NSInteger)floor(x0pt * 2); x < (NSInteger)ceil(x1pt * 2); x++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            if ((long)p[0] - (long)p[2] >= 40) warm++;
        }
    return warm;
}
// Near-white pixels (the highlighted row's text colour) in the columns of a band.
static NSUInteger WhitePixels(NSBitmapImageRep *rep, CGFloat x0pt, CGFloat x1pt, NSRect band) {
    NSUInteger white = 0;
    for (NSInteger y = (NSInteger)ceil(NSMinY(band) * 2); y < (NSInteger)floor(NSMaxY(band) * 2); y++)
        for (NSInteger x = (NSInteger)floor(x0pt * 2); x < (NSInteger)ceil(x1pt * 2); x++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            if (p[0] >= 235 && p[1] >= 235 && p[2] >= 235) white++;
        }
    return white;
}
// Leftmost and rightmost ink column (points) in [x0pt, x1pt) of a band, same 30% rule.
static NSArray *InkSpan(NSBitmapImageRep *rep, CGFloat x0pt, CGFloat x1pt, NSRect band, NSPoint bgPoint) {
    NSInteger x0 = (NSInteger)ceil(x0pt * 2), x1 = (NSInteger)floor(x1pt * 2);
    NSInteger y0 = (NSInteger)ceil((NSMinY(band) + 3) * 2), y1 = (NSInteger)floor((NSMaxY(band) - 3) * 2);
    NSUInteger bg[5] = {0};
    [rep getPixel:bg atX:(NSInteger)(bgPoint.x * 2) y:(NSInteger)(bgPoint.y * 2)];
    CGFloat peak = 0;
    NSMutableArray *dev = [NSMutableArray array];
    for (NSInteger x = x0; x < x1; x++) {
        CGFloat d = 0;
        for (NSInteger y = y0; y < y1; y++) {
            NSUInteger p[5] = {0};
            [rep getPixel:p atX:x y:y];
            for (int c = 0; c < 3; c++) d = MAX(d, fabs((CGFloat)p[c] - (CGFloat)bg[c]));
        }
        [dev addObject:@(d)];
        peak = MAX(peak, d);
    }
    if (peak < 16) return nil;
    NSInteger first = -1, last = -1;
    for (NSInteger i = 0; i < (NSInteger)[dev count]; i++)
        if ([dev[i] doubleValue] >= 0.3 * peak) { if (first < 0) first = i; last = i; }
    return @[@((x0 + first) / 2.0), @((x0 + last + 1) / 2.0)];
}
// Row views of the list drawn alone on white, one 24 pt row under the other (top-down, 2x),
// the reference for the title font's capital letters and baseline in the same row code.
@interface FCWhiteView : NSView
@end
@implementation FCWhiteView
- (BOOL)isFlipped { return YES; }
- (void)drawRect:(NSRect)dirty { [[NSColor whiteColor] set]; NSRectFill(dirty); }
@end
static NSBitmapImageRep *DrawRowsAlone(NSArray *rowViews) {
    FCWhiteView *sheet = [[[FCWhiteView alloc] initWithFrame:NSMakeRect(0, 0, 384, 24 * [rowViews count])] autorelease];
    for (NSUInteger i = 0; i < [rowViews count]; i++) {
        NSView *v = rowViews[i];
        [v setFrame:NSMakeRect(0, 24 * i, 384, 24)];
        [sheet addSubview:v];
    }
    [sheet layoutSubtreeIfNeeded];
    return DrawPanel(sheet);
}
static BOOL HasImageView(NSView *view) {
    if ([view isKindOfClass:[NSImageView class]]) return YES;
    for (NSView *sub in [view subviews]) if (HasImageView(sub)) return YES;
    return NO;
}
// The runs CoreText lays out for a text field's string as the field holds it: per run the
// font (PostScript name, which tells a fallback font from a named one), its size, any
// baseline offset and the string range. A glyph the font lacks gets the font's own fallback,
// as when the field draws it.
static NSArray *TextRuns(NSTextField *field) {
    NSMutableArray *runs = [NSMutableArray array];
    NSAttributedString *text = [field attributedStringValue];
    if ([text length] == 0) return runs;
    CTLineRef line = CTLineCreateWithAttributedString((CFAttributedStringRef)text);
    for (id object in (NSArray *)CTLineGetGlyphRuns(line)) {
        CTRunRef run = (CTRunRef)object;
        NSDictionary *attributes = (NSDictionary *)CTRunGetAttributes(run);
        CTFontRef font = (CTFontRef)attributes[(id)kCTFontAttributeName];
        CFRange range = CTRunGetStringRange(run);
        NSString *name = font ? [(NSString *)CTFontCopyPostScriptName(font) autorelease] : @"";
        [runs addObject:@{@"font": name, @"size": @(font ? CTFontGetSize(font) : 0),
                          @"baselineOffset": @([attributes[NSBaselineOffsetAttributeName] doubleValue]),
                          @"location": @(range.location), @"length": @(range.length)}];
    }
    CFRelease(line);
    return runs;
}
// The ink of a row drawn alone (DrawRowsAlone, row i): the first glyph from the text column
// on (columns and rows, points from the row's top) and, for the text after it, its columns
// and rows. nil members when there is no ink.
static NSDictionary *RowInk(NSBitmapImageRep *rep, NSUInteger i, CGFloat fieldRight) {
    NSRect row = NSMakeRect(0, 24 * i, 384, 24);
    NSPoint bg = NSMakePoint(6.5, NSMidY(row));
    NSArray *first = FirstInk(rep, 27, 80, row, bg);
    NSArray *firstRows = first ? InkRowsOfRun(rep, first, row, bg) : nil;
    NSArray *rest = first ? InkSpan(rep, [first[1] doubleValue] + 0.5, fieldRight, row, bg) : nil;
    NSArray *restRows = rest ? InkRowsOfRun(rep, rest, row, bg) : nil;
    NSUInteger warm = first ? WarmPixels(rep, [first[0] doubleValue], [first[1] doubleValue], row) : 0;
    NSMutableDictionary *ink = [NSMutableDictionary dictionary];
    if (first) ink[@"first"] = @[first[0], first[1]];
    if (firstRows) ink[@"firstRows"] = @[@([firstRows[0] doubleValue] - NSMinY(row)), @([firstRows[1] doubleValue] - NSMinY(row))];
    if (rest) ink[@"rest"] = rest;
    if (restRows) ink[@"restRows"] = @[@([restRows[0] doubleValue] - NSMinY(row)), @([restRows[1] doubleValue] - NSMinY(row))];
    ink[@"warm"] = @(warm);
    return ink;
}
static BOOL Near(id a, id b, CGFloat tolerance) {
    if (![a isKindOfClass:[NSArray class]] || ![b isKindOfClass:[NSArray class]] || [a count] != [b count]) return NO;
    for (NSUInteger i = 0; i < [a count]; i++)
        if (!(fabs([a[i] doubleValue] - [b[i] doubleValue]) <= tolerance)) return NO;
    return YES;
}

// What VoiceOver gets: AppKit serves the accessibility server through
// -_accessibilityValueForAttribute:clientError: (private; used here only, so the probe
// reads exactly what is served: attribute-API elements such as the table's rows and
// protocol elements alike). Without it, the attribute API.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static id AX(id element, NSString *attribute) {
    SEL served = NSSelectorFromString(@"_accessibilityValueForAttribute:clientError:");
    if ([element respondsToSelector:served]) return ((id (*)(id, SEL, id, void *))objc_msgSend)(element, served, attribute, NULL);
    return [element accessibilityAttributeValue:attribute];
}
#pragma clang diagnostic pop
static NSString *AXRoleOf(id element) { return AX(element, NSAccessibilityRoleAttribute); }
// The table's accessibility row for a list row (by AXIndex), or nil.
static id AXRowForListRow(NSArray *axRows, NSInteger row) {
    for (id r in axRows) if ([AX(r, NSAccessibilityIndexAttribute) integerValue] == row) return r;
    return nil;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        Swizzle([NSApplication class], "activateIgnoringOtherApps:", (IMP)CountActivation);
        Swizzle([NSApplication class], "activate", (IMP)CountActivation);
        Swizzle([NSApplication class], "unhide:", (IMP)CountActivation);
        Swizzle([NSRunningApplication class], "activateWithOptions:", (IMP)CountActivationBOOL);
        Swizzle([NSWindow class], "orderFront:", (IMP)CountOrderFront);
        Swizzle([NSWindow class], "makeKeyAndOrderFront:", (IMP)CountOrderFront);
        Swizzle([NSWindow class], "orderFrontRegardless", (IMP)CountOrderFront);
        gWorkspaceCenter = [[NSNotificationCenter alloc] init];
        Swizzle([NSWorkspace class], "notificationCenter", (IMP)PrivateWorkspaceCenter);
        gNextEvent = method_setImplementation(class_getInstanceMethod([NSApplication class],
                                                                      @selector(nextEventMatchingMask:untilDate:inMode:dequeue:)),
                                              (IMP)SpyNextEvent);
        method_setImplementation(class_getInstanceMethod([NSView class], @selector(beginDraggingSessionWithItems:event:source:)),
                                 (IMP)RecordDragBegin);
        gIsKeyWindow = method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(isKeyWindow)), (IMP)ProbeIsKeyWindow);
        gDeletedImages = [NSMutableArray new];
        gAnnouncements = [NSMutableArray new];
        gSteps = [NSMutableArray new];
        gChecks = [NSMutableArray new];

        FCProbeOperator *op = [[FCProbeOperator alloc] init];
        [op awakeFromNibDisplaying:20 withDisplayLength:40 withSaveSelector:NULL forTarget:nil];
        [[op history] setRememberNum:99];
        NSArray *texts = HistoryTexts();
        NSMutableArray *history = [NSMutableArray array];
        for (int i = 0; i < 57; i++) {
            NSString *t = texts[i % [texts count]];
            if ([t isEqualToString:@"[image]"])
                [history addObject:[[[FlycutClipping alloc] initWithImageHash:[NSString stringWithFormat:@"hash%d", i] withImageSize:NSMakeSize(1280, 720)
                    withImageType:NSPasteboardTypePNG withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:1000 - i] autorelease]];
            else
                [history addObject:Clip(i < (int)[texts count] ? t : [NSString stringWithFormat:@"%@ #%d", t, i], 1000 - i)];
        }
        for (FlycutClipping *c in [history reverseObjectEnumerator]) [[op history] addClipping:c];
        for (NSString *t in [@[@"Mit freundlichen Grüßen, Max Mustermann", @"https://example.test/projekt/handbuch",
                               @"Vorlage: Rückruf am Dienstag um 10 Uhr"] reverseObjectEnumerator])
            [[op favorites] addClipping:Clip(t, 500)];

        FCProbeDelegate *delegate = [[FCProbeDelegate alloc] init];
        gController = [[FlycutListController alloc] initWithOperator:op delegate:delegate];
        [gController setVisibleRows:20];
        NSMutableArray *commands = [NSMutableArray array];
        // In an NSMenu, as jcMenu's items are: the list follows the menu's item changes.
        NSMenu *commandMenu = [[NSMenu alloc] initWithTitle:@"Menu"];
        for (NSString *t in @[@"Clear All", @"Merge All", @"Pause Clipboard Tracking", @"Preferences…", @"About Flycut", @"-", @"Quit"]) {
            if ([t isEqualToString:@"-"]) { [commands addObject:[NSMenuItem separatorItem]]; [commandMenu addItem:[commands lastObject]]; continue; }
            NSMenuItem *item = [[[NSMenuItem alloc] initWithTitle:t action:@selector(noop:) keyEquivalent:[t hasPrefix:@"Pref"] ? @"," : @""] autorelease];
            [item setTarget:delegate];
            [commands addObject:item];
            [commandMenu addItem:item];
        }
        [gController setCommandItems:commands];

        // --- open
        Open();
        FlycutListPanel *panel = [gController panel];
        Check([gController isOpen], @"list opens", nil);
        Check(delegate->opened == 1, @"delegate told about opening (capture freeze)", nil);
        Check(panel != nil && ([panel styleMask] & NSWindowStyleMaskNonactivatingPanel) != 0, @"panel is non-activating", nil);
        Check([panel canBecomeKeyWindow] && ![panel canBecomeMainWindow], @"panel can become key, never main", nil);
        Check(![panel hidesOnDeactivate] && ![panel becomesKeyOnlyIfNeeded], @"panel stays while Flycut is inactive; key at once", nil);
        Check([panel level] == NSPopUpMenuWindowLevel, @"panel sits at menu level", nil);
        id fr = [panel firstResponder];
        Check([fr isKindOfClass:[NSTextView class]] && [(NSTextView *)fr delegate] == (id)[gController searchField],
              @"search field has the keyboard focus", NSStringFromClass([fr class]));
        Check([[[gController searchField] placeholderString] isEqualToString:@"Search"], @"search placeholder", nil);
        NSArray *rows = [[gController clipList] rows];
        // One list: the 3 favorites on top, then the 57 history clippings; no headers, no divider.
        Check([rows count] == 3 + 57 && [(FlycutClipListRow *)rows[2] list] == FlycutListFavorites &&
              [(FlycutClipListRow *)rows[3] list] == FlycutListHistory,
              @"all 60 clippings in one list, favorites first, no header or divider rows", [NSString stringWithFormat:@"%lu", (unsigned long)[rows count]]);
        Check([gController highlightedRow] == -1, @"nothing highlighted at first (Return does nothing)", nil);

        // Geometry against the approved mockup (MenuMockupMono.m constants).
        NSRect content = [[panel contentView] frame];
        NSScrollView *scroll = [[gController tableView] enclosingScrollView];
        NSRect searchFrame = [[gController searchField] frame];
        Check(NSWidth(content) == 384, @"panel width 384 pt (today's menu width)", NSStringFromRect(content));
        Check(NSHeight([scroll frame]) == 19 * 24 + 12, @"20 rows: list height 468 pt, the 20th row cut in half", NSStringFromRect([scroll frame]));
        Check(NSMinX(searchFrame) == 5 && NSWidth(searchFrame) == 374 && NSHeight(searchFrame) == 22,
              @"search field 5/374/22 pt, as wide as the highlight", NSStringFromRect(searchFrame));
        Check(NSHeight(content) == 5 + 34 + 11 + 468 + 166 + 5, @"panel height = padding+search+separator+list+commands+padding",
              NSStringFromRect(content));

        // --- arrows
        Down();
        Check([HighlightedText() hasPrefix:@"Mit freundlichen"], @"Down highlights the first favorite", HighlightedText());
        Down(); Down(); Down();
        Check([gController highlightedRow] == 3 && [HighlightedText() hasPrefix:@"Einkaufsliste"],
              @"Down goes from the last favorite straight to the first history row", [NSString stringWithFormat:@"%ld", (long)[gController highlightedRow]]);
        Up();
        Check([gController highlightedRow] == 2, @"Up goes back to the last favorite", [NSString stringWithFormat:@"%ld", (long)[gController highlightedRow]]);
        Down(); Down(); Down(); Down();

        // --- row look: icons only where they belong. Row 6 (history) is highlighted, row 8
        // is a plain history row (row 7 is an image), row 1 a favorite that is not highlighted.
        FlycutListEntryView *hi = EntryView(6), *normal = EntryView(8), *fav = EntryView(1);
        Check(hi != nil && normal != nil && fav != nil, @"rows are entry views", nil);
        Check([[normal starButton] isHidden] && [[normal trashButton] isHidden], @"a plain history row shows no icons", nil);
        Check(![[fav starButton] isHidden] && [[fav trashButton] isHidden] && [[fav starButton] state] == NSControlStateValueOn,
              @"a favorite that is not highlighted shows only its filled star", nil);
        Check(![[hi trashButton] isHidden] && ![[hi starButton] isHidden] && [[hi starButton] state] == NSControlStateValueOff,
              @"the highlighted row shows the trash and the star (outline: not a favorite)", nil);
        Check([[[fav starButton] accessibilityLabel] isEqualToString:@"Remove from Favorites"] &&
              [[[hi starButton] accessibilityLabel] isEqualToString:@"Add to Favorites"] &&
              [[[normal starButton] accessibilityLabel] isEqualToString:@"Add to Favorites"],
              @"star labels for VoiceOver", [[normal starButton] accessibilityLabel]);
        Check([[[hi trashButton] accessibilityLabel] isEqualToString:@"Delete"], @"trash label for VoiceOver", [[hi trashButton] accessibilityLabel]);
        Check([[fav starButton] state] == NSControlStateValueOn && [[normal starButton] state] == NSControlStateValueOff,
              @"filled star for favorites, outline otherwise", nil);
        Check(SameColor([[fav starButton] contentTintColor], [NSColor tertiaryLabelColor]) &&
              SameColor([[normal starButton] contentTintColor], [NSColor tertiaryLabelColor]),
              @"star in tertiaryLabelColor", [[[fav starButton] contentTintColor] description]);
        Check(SameColor([[hi starButton] contentTintColor], [NSColor selectedMenuItemTextColor]) &&
              SameColor([[hi trashButton] contentTintColor], [NSColor selectedMenuItemTextColor]) &&
              SameColor([[hi titleField] textColor], [NSColor selectedMenuItemTextColor]),
              @"highlighted row: star, trash and text in the selected-menu-item colour", nil);
        NSArray *actions = [[hi accessibilityCustomActions] valueForKey:@"name"];
        Check([actions containsObject:@"Add to Favorites"] && [actions containsObject:@"Delete"], @"row custom actions for VoiceOver",
              [actions description]);
        Check([[fav accessibilityLabel] hasSuffix:@", Favorite"] && [[hi accessibilityLabel] isEqualToString:[[hi titleField] stringValue]],
              @"VoiceOver hears which rows are favorites", [NSString stringWithFormat:@"%@ / %@", [fav accessibilityLabel], [hi accessibilityLabel]]);
        // --- image rows (sight test of build 11): the picture emoji at the start of the text,
        // one space, then the size text as before; no Quick Look eye; the text in the text
        // rows' column; VoiceOver reads the size and not the emoji
        {
            NSString *imageText = [kPictureEmoji stringByAppendingString:@" [Image 1280x720]"];
            NSMutableArray *wrong = [NSMutableArray array];
            NSUInteger imageRowCount = 0, textRowCount = 0;
            for (NSInteger r = 0; r < 24; r++) {
                FlycutListEntryView *v = EntryView(r);
                FlycutClipping *clipping = [[[[gController clipList] rows] objectAtIndex:r] clipping];
                NSString *shown = [[v titleField] stringValue];
                if ([clipping isImageClipping]) {
                    imageRowCount++;
                    if (![shown isEqualToString:imageText]) [wrong addObject:[NSString stringWithFormat:@"row %ld: %@", (long)r, shown]];
                } else {
                    textRowCount++;
                    if (![shown isEqualToString:[clipping displayString]] || [shown rangeOfString:@"\U0001F5BC"].location != NSNotFound)
                        [wrong addObject:[NSString stringWithFormat:@"row %ld: %@", (long)r, shown]];
                }
            }
            Check([wrong count] == 0 && imageRowCount >= 2 && textRowCount >= 20,
                  @"image rows start with the picture emoji and one space before the size text; text rows are unchanged",
                  [NSString stringWithFormat:@"%lu image rows, %lu text rows, wrong: %@", (unsigned long)imageRowCount, (unsigned long)textRowCount, wrong]);
            NSUInteger eyes = 0;
            for (NSInteger r = 0; r < 24; r++) if (HasImageView(EntryView(r))) eyes++;
            Check(eyes == 0, @"no row has an image view: the Quick Look eye is gone", [NSString stringWithFormat:@"%lu rows with an image view", (unsigned long)eyes]);
            FlycutListEntryView *imageView = EntryView(7);
            Check(NSMinX([[imageView titleField] frame]) == NSMinX([[normal titleField] frame]) && NSMinX([[imageView titleField] frame]) == 28 &&
                  NSMaxX([[imageView titleField] frame]) == NSMaxX([[normal titleField] frame]) &&
                  NSHeight([[imageView titleField] frame]) == NSHeight([[normal titleField] frame]) &&
                  NSMinY([[imageView titleField] frame]) == NSMinY([[normal titleField] frame]),
                  @"image rows' text starts in the text rows' column: the same text field frame",
                  [NSString stringWithFormat:@"image %@ text %@", NSStringFromRect([[imageView titleField] frame]), NSStringFromRect([[normal titleField] frame])]);
            // VoiceOver: the row's label is "Image 1280 by 720", never the emoji (VoiceOver would
            // read its name, "framed picture", too); the table's tree is checked further down.
            Check([[imageView accessibilityLabel] isEqualToString:@"Image 1280 by 720"] &&
                  [AX(imageView, NSAccessibilityDescriptionAttribute) isEqualToString:@"Image 1280 by 720"],
                  @"VoiceOver reads an image row as \"Image 1280 by 720\"",
                  [NSString stringWithFormat:@"label %@, description %@", [imageView accessibilityLabel], AX(imageView, NSAccessibilityDescriptionAttribute)]);
            Check([[normal accessibilityLabel] isEqualToString:[[normal titleField] stringValue]],
                  @"a text row's label stays its text", [normal accessibilityLabel]);
        }
        // Columns as in a native menu (macOS 27, measured offscreen with AppKit's own menu
        // item views at 384 pt: checkmark image 12-25, title text field from 28, key
        // equivalents end at 371): the star in the state column (hit area 9-29, its glyph
        // centred where the checkmark is), the title where the menu's titles start, the
        // trash at the right edge, its glyph ending where the key equivalents end.
        NSRect hiStar = [[hi starButton] frame], hiTrash = [[hi trashButton] frame];
        CGFloat rowWidth = NSWidth([hi bounds]);
        Check(NSMinX(hiStar) == 9 && NSWidth(hiStar) == 20 && NSMinX([[normal titleField] frame]) == 28 &&
              NSMaxX(hiTrash) == rowWidth - 9 && NSWidth(hiTrash) == 20 && NSMaxX([[hi titleField] frame]) <= NSMinX(hiTrash) &&
              NSEqualRects([[fav starButton] frame], hiStar),
              @"columns: star in the state column at the left, title at 28 like a native menu's, trash at the right edge",
              [NSString stringWithFormat:@"row %g title %@ trash %@ star %@; favorite's star %@", rowWidth, NSStringFromRect([[hi titleField] frame]),
               NSStringFromRect(hiTrash), NSStringFromRect(hiStar), NSStringFromRect([[fav starButton] frame])]);
        NSView *besideStar = [hi hitTest:[[hi superview] convertPoint:NSMakePoint(NSMaxX(hiStar) + 1, NSMidY(hiStar)) fromView:hi]];
        NSView *onTitle = [hi hitTest:[[hi superview] convertPoint:NSMakePoint(NSMidX([[hi titleField] frame]), NSMidY(hiStar)) fromView:hi]];
        Check(besideStar != [hi starButton] && onTitle != [hi starButton] && onTitle != [hi trashButton] &&
              [hi hitTest:[[hi superview] convertPoint:NSMakePoint(NSMidX(hiStar), NSMidY(hiStar)) fromView:hi]] == [hi starButton] &&
              [hi hitTest:[[hi superview] convertPoint:NSMakePoint(NSMidX(hiTrash), NSMidY(hiTrash)) fromView:hi]] == [hi trashButton],
              @"a click right of the star or on the title hits the row, not an icon", [NSString stringWithFormat:@"%@ / %@", [besideStar className], [onTitle className]]);

        // Classic scroll bars (mouse attached, or "Show scroll bars: Always") narrow the
        // clip view; the trash must keep its 9 pt from the scroll bar instead of hiding
        // under it, and the star its column.
        [scroll setScrollerStyle:NSScrollerStyleLegacy];
        [scroll tile];
        [[gController tableView] reloadData];
        FlycutListEntryView *legacy = EntryView(6);
        CGFloat clipWidth = NSWidth([[scroll contentView] bounds]);
        NSRect legacyStar = [[legacy starButton] convertRect:[[legacy starButton] bounds] toView:[gController tableView]];
        NSRect legacyTrash = [[legacy trashButton] convertRect:[[legacy trashButton] bounds] toView:[gController tableView]];
        Check(clipWidth < 384 && NSMaxX(legacyTrash) == clipWidth - 9 && NSMinX(legacyStar) == 9 &&
              ![[legacy trashButton] isHidden] && ![[legacy starButton] isHidden],
              @"classic scroll bars: the trash stays 9 pt inside the narrower list, the star keeps its column",
              [NSString stringWithFormat:@"clip %.1f trash %@ star %@", clipWidth, NSStringFromRect(legacyTrash), NSStringFromRect(legacyStar)]);
        [scroll setScrollerStyle:NSScrollerStyleOverlay];
        [scroll tile];
        [[gController tableView] reloadData];

        // In pixels (sight test of the v4 renders: "Das Auge ist nicht bündig, die Such-Lupe
        // oben nicht in der Spalte und auch die Sterne minimal links"): the drawn ink of the
        // stars (favorites filled, the highlighted row's outline) and of the search field's
        // magnifier is centred between the lines of a native menu's checkmark column (12 and
        // 25 pt, centre 18.5). The image row's emoji is measured below.
        NSMutableArray *titleInk = [NSMutableArray array];
        NSArray *emojiRun = nil;
        NSArray *emojiRows = nil;
        NSUInteger emojiWarm = 0;
        NSRect imageRowRect = NSZeroRect, imageFieldRect = NSZeroRect;
        {
            NSView *content = [panel contentView];
            [content layoutSubtreeIfNeeded];
            NSBitmapImageRep *rep = DrawPanel(content);
            NSMutableArray *starInk = [NSMutableArray array];
            BOOL starsCentred = YES;
            for (NSInteger r = 0; r < 12; r++) {
                FlycutListEntryView *v = EntryView(r);
                NSRect row = [v convertRect:[v bounds] toView:content];
                NSPoint bg = NSMakePoint(6.5, NSMidY(row));
                if (![[v starButton] isHidden]) {
                    NSArray *ink = FirstInk(rep, 6, 27, row, bg);
                    CGFloat centre = ink ? ([ink[0] doubleValue] + [ink[1] doubleValue]) / 2 : NAN;
                    starsCentred &= ink != nil && fabs(centre - 18.5) <= 0.5;
                    [starInk addObject:[NSString stringWithFormat:@"row %ld %@-%@ centre %.2f", (long)r, ink[0], ink[1], centre]];
                }
                if ([[[v titleField] stringValue] hasPrefix:kPictureEmoji]) {
                    emojiRun = FirstInk(rep, 27, 80, row, bg);
                    emojiRows = emojiRun ? InkRowsOfRun(rep, emojiRun, row, bg) : nil;
                    emojiWarm = emojiRun ? WarmPixels(rep, [emojiRun[0] doubleValue], [emojiRun[1] doubleValue], row) : 0;
                    imageRowRect = row;
                    imageFieldRect = [[v titleField] convertRect:[[v titleField] bounds] toView:content];
                } else {
                    NSArray *ink = FirstInk(rep, 27, 90, row, bg);
                    if (ink) [titleInk addObject:ink[0]];
                }
            }
            Check([starInk count] == 4 && starsCentred,
                  @"pixels: the stars' ink is centred between the native checkmark column's lines (18.5 +-0.5 pt)",
                  [starInk componentsJoinedByString:@"; "]);
            NSSearchField *search = [gController searchField];
            NSRect field = [search convertRect:[search bounds] toView:content];
            NSArray *magnifier = FirstInk(rep, NSMinX(field) + 2.5, NSMinX(field) + 60, NSInsetRect(field, 0, 2),
                                          NSMakePoint(NSMaxX(field) - 20, NSMidY(field)));
            CGFloat magnifierCentre = magnifier ? ([magnifier[0] doubleValue] + [magnifier[1] doubleValue]) / 2 : NAN;
            Check(magnifier != nil && fabs(magnifierCentre - 18.5) <= 0.5,
                  @"pixels: the search field's magnifier is centred in the same column (18.5 +-0.5 pt)",
                  [NSString stringWithFormat:@"field %@ magnifier %@-%@ centre %.2f", NSStringFromRect(field), magnifier[0], magnifier[1], magnifierCentre]);
        }
        // The emoji of the image row (row 7) where the text rows' ink starts and in colour.
        {
            CGFloat column = [[titleInk valueForKeyPath:@"@min.self"] doubleValue];
            CGFloat emojiLeft = emojiRun ? [emojiRun[0] doubleValue] : NAN;
            Check(emojiRun != nil && [titleInk count] >= 8 && fabs(emojiLeft - column) <= 0.75 && emojiWarm >= 8,
                  @"pixels: the picture emoji starts where the text rows' ink starts (+-0.75 pt) and is in colour",
                  [NSString stringWithFormat:@"emoji ink %@-%@, text ink from %.2f (%lu rows: %@), %lu warm pixels", emojiRun[0], emojiRun[1], column,
                   (unsigned long)[titleInk count], [titleInk componentsJoinedByString:@" "], (unsigned long)emojiWarm]);
        }
        // A sight test: the picture emoji of an image row was much smaller than the same emoji
        // copied as text. An image row's emoji must look exactly like the emoji at the start of
        // a copied text clipping in a text row: compared with a text row whose clipping is the
        // image row's string, made by the same row code.
        {
            NSString *imageText = [kPictureEmoji stringByAppendingString:@" [Image 1280x720]"];
            FlycutListEntryView *(^makeRow)(NSString *, BOOL, BOOL) = ^(NSString *title, BOOL image, BOOL highlighted) {
                FlycutListEntryView *v = [[[FlycutListEntryView alloc] initWithFrame:NSMakeRect(0, 0, 384, 24) target:gController] autorelease];
                [v configureWithTitle:title image:image favorite:NO highlighted:highlighted];
                return v;
            };
            FlycutListEntryView *copied = makeRow(imageText, NO, NO);
            FlycutListEntryView *image = makeRow(@"[Image 1280x720]", YES, NO);
            FlycutListEntryView *plain = makeRow(@"Rechnung Nr. 2026", NO, NO);
            // The runs CoreText lays out: font, size and baseline of the emoji and of the text.
            NSArray *copiedRuns = TextRuns([copied titleField]), *imageRuns = TextRuns([image titleField]);
            BOOL sameRuns = [copiedRuns count] >= 2 && [copiedRuns isEqualToArray:imageRuns] &&
                [copiedRuns[0][@"location"] integerValue] == 0 && [copiedRuns[0][@"length"] integerValue] == (NSInteger)[kPictureEmoji length] &&
                [copiedRuns[0][@"baselineOffset"] doubleValue] == 0 && [copiedRuns[0][@"size"] doubleValue] == [[NSFont menuFontOfSize:0] pointSize];
            Check(sameRuns && [[[image titleField] stringValue] isEqualToString:[[copied titleField] stringValue]] &&
                  [[[image titleField] font] isEqual:[[copied titleField] font]],
                  @"an image row's emoji is the run of the same emoji at the start of a copied text clipping: same font, size and baseline",
                  [NSString stringWithFormat:@"image row %@ / text row %@", imageRuns, copiedRuns]);
            // The same in pixels, drawn alone: the emoji's ink (columns and rows) within 0.25 pt,
            // and the size text after it on the same baseline (its ink rows) and as far from it.
            CGFloat fieldRight = NSMaxX([[image titleField] frame]);
            NSBitmapImageRep *rep = DrawRowsAlone(@[copied, image]);
            NSDictionary *copiedInk = RowInk(rep, 0, fieldRight), *imageInk = RowInk(rep, 1, fieldRight);
            Check(copiedInk[@"first"] && Near(imageInk[@"first"], copiedInk[@"first"], 0.25) && Near(imageInk[@"firstRows"], copiedInk[@"firstRows"], 0.25) &&
                  Near(imageInk[@"rest"], copiedInk[@"rest"], 0.25) && Near(imageInk[@"restRows"], copiedInk[@"restRows"], 0.25) &&
                  [imageInk[@"warm"] unsignedIntegerValue] >= 8,
                  @"pixels: an image row's emoji has the ink of the same emoji in a text row (+-0.25 pt), the size text after it the same baseline",
                  [NSString stringWithFormat:@"image row %@ / text row %@", imageInk, copiedInk]);
            // Rows with the emoji at the text's size: not cut off (as tall as drawn in a tall
            // field) and inside their 24 pt row, the text field as in a plain text row, and the
            // list's row pitch kept, also for the image row in the open list.
            NSTextField *tall = [NSTextField labelWithString:@""];
            [tall setFont:[[copied titleField] font]];
            [tall setStringValue:imageText];
            [tall setFrame:NSMakeRect(28, 4, 323, 40)];
            FCWhiteView *sheet = [[[FCWhiteView alloc] initWithFrame:NSMakeRect(0, 0, 384, 48)] autorelease];
            [sheet addSubview:tall];
            NSBitmapImageRep *tallRep = DrawPanel(sheet);
            NSRect tallBand = NSMakeRect(0, 0, 384, 48);
            NSArray *tallRun = FirstInk(tallRep, 27, 80, tallBand, NSMakePoint(6.5, 24));
            NSArray *tallRows = tallRun ? InkRowsOfRun(tallRep, tallRun, tallBand, NSMakePoint(6.5, 24)) : nil;
            CGFloat whole = tallRows ? [tallRows[1] doubleValue] - [tallRows[0] doubleValue] : NAN;
            NSMutableArray *heights = [NSMutableArray array];
            BOOL whole2 = YES;
            for (NSDictionary *ink in @[copiedInk, imageInk]) {
                NSArray *rows = ink[@"firstRows"];
                CGFloat h = rows ? [rows[1] doubleValue] - [rows[0] doubleValue] : NAN;
                [heights addObject:@(h)];
                whole2 &= rows != nil && fabs(h - whole) <= 0.25 && [rows[0] doubleValue] >= 0.5 && [rows[1] doubleValue] <= 23.5;
            }
            CGFloat panelHeight = emojiRows ? [emojiRows[1] doubleValue] - [emojiRows[0] doubleValue] : NAN;
            NSTableView *table = [gController tableView];
            NSRect r7 = [table rectOfRow:7], r8 = [table rectOfRow:8], r6 = [table rectOfRow:6];
            BOOL pitch = NSHeight(r7) == 24 && NSMinY(r8) - NSMinY(r7) == 24 && NSMinY(r7) - NSMinY(r6) == 24;
            BOOL fields = NSEqualRects([[image titleField] frame], [[plain titleField] frame]) && NSEqualRects([[copied titleField] frame], [[plain titleField] frame]);
            Check(tallRows != nil && whole2 && fabs(panelHeight - whole) <= 0.25 && pitch && fields,
                  @"pixels: rows with the emoji are not cut off, keep a text row's text field and the list's 24 pt row pitch",
                  [NSString stringWithFormat:@"emoji ink heights text row / image row %@, in the open list %.2f, drawn in a tall field %.2f; rows 6-8 %@ %@ %@; "
                   "fields image %@ text %@ plain %@", heights, panelHeight, whole, NSStringFromRect(r6), NSStringFromRect(r7), NSStringFromRect(r8),
                   NSStringFromRect([[image titleField] frame]), NSStringFromRect([[copied titleField] frame]), NSStringFromRect([[plain titleField] frame])]);
            // Highlighted: both emoji keep their colours and the same ink, both texts take
            // the highlight's text colour.
            FlycutListEntryView *copiedHi = makeRow(imageText, NO, YES), *imageHi = makeRow(@"[Image 1280x720]", YES, YES);
            NSBitmapImageRep *hiRep = DrawRowsAlone(@[copiedHi, imageHi]);
            NSDictionary *copiedHiInk = RowInk(hiRep, 0, fieldRight), *imageHiInk = RowInk(hiRep, 1, fieldRight);
            NSUInteger warmCopied = [copiedHiInk[@"warm"] unsignedIntegerValue], warmImage = [imageHiInk[@"warm"] unsignedIntegerValue];
            Check(copiedHiInk[@"first"] && Near(imageHiInk[@"first"], copiedHiInk[@"first"], 0.25) && Near(imageHiInk[@"firstRows"], copiedHiInk[@"firstRows"], 0.25) &&
                  warmImage >= 8 && warmImage == warmCopied && Near(imageHiInk[@"first"], imageInk[@"first"], 0.25) &&
                  SameColor([[imageHi titleField] textColor], [NSColor selectedMenuItemTextColor]) &&
                  SameColor([[copiedHi titleField] textColor], [NSColor selectedMenuItemTextColor]),
                  @"highlighted: an image row's emoji keeps the ink and colours of the same emoji in a text row, both texts in the selected-menu-item colour",
                  [NSString stringWithFormat:@"image row %@ / text row %@; text colours %@ / %@", imageHiInk, copiedHiInk,
                   [[imageHi titleField] textColor], [[copiedHi titleField] textColor]]);
        }
        // The highlighted image row: the emoji keeps its colours (a colour glyph, never tinted
        // like the template eye was), the size text takes the highlight's text colour.
        {
            [gController setHighlightedRow:7];
            NSView *content = [panel contentView];
            [content layoutSubtreeIfNeeded];
            NSBitmapImageRep *rep = DrawPanel(content);
            FlycutListEntryView *v = EntryView(7);
            NSRect row = [v convertRect:[v bounds] toView:content];
            NSPoint bg = NSMakePoint(6.5, NSMidY(row));
            NSArray *run = FirstInk(rep, 27, 80, row, bg);
            NSUInteger warm = run ? WarmPixels(rep, [run[0] doubleValue], [run[1] doubleValue], row) : 0;
            NSUInteger white = WhitePixels(rep, 46, 140, row);
            NSColor *textColour = [[v titleField] textColor];
            Check(run != nil && warm >= 8 && white >= 20 && SameColor(textColour, [NSColor selectedMenuItemTextColor]),
                  @"highlighted image row: the emoji keeps its colours, the size text is in the selected-menu-item colour",
                  [NSString stringWithFormat:@"emoji ink %@, %lu warm pixels, %lu white pixels right of it, size text colour %@", run, (unsigned long)warm,
                   (unsigned long)white, textColour]);
            [gController setHighlightedRow:6];
        }
        // A long size text is cut at the end, as every title is, and the emoji stays at the start;
        // a row view reused for another kind of row shows that row correctly.
        {
            NSMutableString *longTitle = [NSMutableString stringWithString:@"[Image 1280x720] "];
            for (int i = 0; i < 12; i++) [longTitle appendString:@"0123456789 "];
            FlycutListEntryView *cut = [[[FlycutListEntryView alloc] initWithFrame:NSMakeRect(0, 0, 384, 24) target:gController] autorelease];
            [cut configureWithTitle:longTitle image:YES favorite:NO highlighted:NO];
            NSBitmapImageRep *rep = DrawRowsAlone(@[cut]);
            NSRect row = NSMakeRect(0, 0, 384, 24);
            NSRect field = [[cut titleField] frame];
            NSArray *span = InkSpan(rep, 27, NSMaxX(field) + 20, row, NSMakePoint(6.5, 12));
            NSUInteger warm = WarmPixels(rep, 28, 44, row);
            CGFloat inkRight = span ? [span[1] doubleValue] : NAN;
            Check([[cut titleField] lineBreakMode] == NSLineBreakByTruncatingTail && [[[cut titleField] stringValue] hasPrefix:kPictureEmoji] &&
                  warm >= 8 && inkRight <= NSMaxX(field) + 0.5 && inkRight >= NSMaxX(field) - 16,
                  @"image rows: a long size text is cut at the end inside the text field, the emoji stays at the start",
                  [NSString stringWithFormat:@"field %@, ink %@, %lu warm pixels at the start, line break mode %ld", NSStringFromRect(field), span,
                   (unsigned long)warm, (long)[[cut titleField] lineBreakMode]]);
            FlycutListEntryView *reused = [[[FlycutListEntryView alloc] initWithFrame:NSMakeRect(0, 0, 384, 24) target:gController] autorelease];
            NSFont *menuFont = [NSFont menuFontOfSize:0];
            // The text's font throughout, as in a text row: no font or baseline of the emoji's own.
            BOOL (^uniformText)(NSAttributedString *) = ^BOOL(NSAttributedString *text) {
                __block BOOL uniform = [text length] > 0;
                [text enumerateAttributesInRange:NSMakeRange(0, [text length]) options:0 usingBlock:^(NSDictionary *attributes, NSRange range, BOOL *stop) {
                    if (![attributes[NSFontAttributeName] isEqual:menuFont] || attributes[NSBaselineOffsetAttributeName] != nil) uniform = NO;
                }];
                return uniform;
            };
            [reused configureWithTitle:@"[GIF 640x480]" image:YES favorite:NO highlighted:NO];
            NSAttributedString *asImage = [[[[reused titleField] attributedStringValue] copy] autorelease];
            BOOL imageUniform = uniformText(asImage);
            NSRect imageFrame = [[reused titleField] frame];
            [reused setListHighlighted:YES];
            [reused setListHighlighted:NO];
            NSAttributedString *afterHighlight = [[reused titleField] attributedStringValue];
            BOOL afterUniform = uniformText(afterHighlight) && [afterHighlight isEqualToAttributedString:asImage];
            [reused configureWithTitle:@"Rechnung Nr. 2026" image:NO favorite:NO highlighted:NO];
            NSAttributedString *asText = [[reused titleField] attributedStringValue];
            BOOL uniform = uniformText(asText);
            NSRect textFrame = [[reused titleField] frame];
            [reused configureWithTitle:@"[GIF 640x480]" image:YES favorite:NO highlighted:NO];
            Check(imageUniform && afterUniform && [[[reused titleField] stringValue] isEqualToString:[kPictureEmoji stringByAppendingString:@" [GIF 640x480]"]] &&
                  [[[reused titleField] attributedStringValue] isEqualToAttributedString:asImage] &&
                  NSMinX(imageFrame) == 28 && NSEqualRects(imageFrame, textFrame) &&
                  [asText length] == [@"Rechnung Nr. 2026" length] && uniform && [[asText string] isEqualToString:@"Rechnung Nr. 2026"],
                  @"image rows: the emoji has no font or baseline of its own, also after the highlight; a reused row view shows each kind right",
                  [NSString stringWithFormat:@"image row %@ (uniform %d, after highlight %d), frames %@ / %@, text uniform %d", asImage, imageUniform, afterUniform,
                   NSStringFromRect(imageFrame), NSStringFromRect(textFrame), uniform]);
        }
        // A highlighted favorite shows its filled star and the trash.
        [gController setHighlightedRow:0];
        FlycutListEntryView *hiFav = EntryView(0);
        Check(![[hiFav starButton] isHidden] && ![[hiFav trashButton] isHidden] && [[hiFav starButton] state] == NSControlStateValueOn &&
              SameColor([[hiFav starButton] contentTintColor], [NSColor selectedMenuItemTextColor]),
              @"a highlighted favorite shows the trash and its filled star", nil);
        [gController setHighlightedRow:6];
        Check([[hiFav trashButton] isHidden] && ![[hiFav starButton] isHidden] && [[EntryView(6) starButton] isHidden] == NO,
              @"the highlight moving on hides the favorite's trash, keeps its star", nil);

        // --- delete and undo
        NSString *before = HighlightedText();
        CmdDelete();
        Check(![HighlightedText() isEqualToString:before] && [[[gController clipList] rows] count] == 59, @"Cmd-Delete deletes the highlighted row", HighlightedText());
        Check([gController highlightedRow] == 6, @"the highlight stays on the row that moved up", nil);
        CmdZ();
        Check([HighlightedText() isEqualToString:before] && [[[gController clipList] rows] count] == 60, @"Cmd-Z restores it, highlighted", HighlightedText());
        CmdForwardDelete();
        Check([[[gController clipList] rows] count] == 59, @"Cmd-Forward-Delete deletes too", nil);
        CmdZ();
        Check([HighlightedText() isEqualToString:before], @"and Cmd-Z restores", nil);

        // --- typing filters, favorites first, Cmd-Delete keeps the search text
        Type(@"beta");
        Check([[[gController searchField] stringValue] isEqualToString:@"beta"], @"typing goes to the search field", [[gController searchField] stringValue]);
        NSArray *filtered = [[gController clipList] rows];
        Check([filtered count] == 12 && [(FlycutClipListRow *)filtered[0] list] == FlycutListHistory,
              @"search filters, only the matches are listed", [NSString stringWithFormat:@"%lu", (unsigned long)[filtered count]]);
        Check([HighlightedText() isEqualToString:@"beta zwei"], @"first match highlighted", HighlightedText());
        CmdDelete();
        Check([[[gController searchField] stringValue] isEqualToString:@"beta"] && [[[gController clipList] rows] count] == 11,
              @"Cmd-Delete in the search field deletes the row, not the search text", [[gController searchField] stringValue]);
        CmdZ();
        Check([[[gController clipList] rows] count] == 12 && [HighlightedText() isEqualToString:@"beta zwei"], @"undo while searching", nil);
        Esc();
        Check([gController isOpen] && [[[gController searchField] stringValue] length] == 0 && [[[gController clipList] rows] count] == 60,
              @"Esc clears the search first, the list stays open", nil);

        // --- the search matches the size text of an image row, never its emoji
        Type(@"1280x720");
        NSArray *sizeMatches = [[gController clipList] rows];
        BOOL onlyImages = [sizeMatches count] > 0;
        for (FlycutClipListRow *r in sizeMatches) if (![[r clipping] isImageClipping]) onlyImages = NO;
        Check(onlyImages && [sizeMatches count] == 6, @"searching the size text finds the image rows",
              [NSString stringWithFormat:@"%lu rows", (unsigned long)[sizeMatches count]]);
        Esc();
        Send(@"picture emoji", Key(kPictureEmoji, 11, 0));
        Check([[[gController searchField] stringValue] isEqualToString:kPictureEmoji] && [[[gController clipList] rows] count] == 0,
              @"searching the emoji finds nothing: it is not part of the searchable text",
              [NSString stringWithFormat:@"search %@, %lu rows", [[gController searchField] stringValue], (unsigned long)[[[gController clipList] rows] count]]);
        Esc();
        Check([[[gController searchField] stringValue] length] == 0 && [[[gController clipList] rows] count] == 60, @"Esc clears the emoji search", nil);

        // --- while searching the list fits its matches like a native menu (at least one row,
        // at most the height it opened with); the panel's top edge stays under the status item
        {
            NSRect opened = [panel frame];
            CGFloat normalList = NSHeight([scroll frame]);
            CGFloat chrome = NSHeight(opened) - normalList;
            CGFloat listTop = NSMinY([scroll frame]);
            NSString *(^Geometry)(void) = ^NSString *{
                return [NSString stringWithFormat:@"panel %@ list %@ (opened %@)", NSStringFromRect([panel frame]),
                        NSStringFromRect([scroll frame]), NSStringFromRect(opened)];
            };
            BOOL (^Fits)(CGFloat) = ^BOOL(CGFloat list) {
                return NSHeight([scroll frame]) == list && NSHeight([panel frame]) == chrome + list &&
                       NSHeight([[panel contentView] frame]) == chrome + list && NSMinY([scroll frame]) == listTop;
            };
            Type(@"handbuch");   // one favorite matches
            Check([[[gController clipList] rows] count] == 1 && Fits(24),
                  @"search with one match: list shrinks to that row", Geometry());
            Check(NSMaxY([panel frame]) == NSMaxY(opened) && NSMinX([panel frame]) == NSMinX(opened),
                  @"the shrunken panel keeps its top edge (anchored under the status item)", Geometry());
            Type(@"x");          // "handbuchx": nothing matches
            Check([[[gController clipList] rows] count] == 0 && Fits(24),
                  @"no match: one row is left for the note", Geometry());
            NSTextField *note = nil;
            for (NSView *v in [[panel contentView] subviews])
                if ([v isKindOfClass:[NSTextField class]] && ![v isKindOfClass:[NSSearchField class]] && ![v isHidden]) note = (NSTextField *)v;
            Check([[note stringValue] isEqualToString:@"No Matches"] &&
                  NSMinY([note frame]) >= NSMinY([scroll frame]) && NSMaxY([note frame]) <= NSMaxY([scroll frame]),
                  @"the row says No Matches", [note stringValue]);
            Check(NSMaxY([panel frame]) == NSMaxY(opened), @"top edge still in place", Geometry());
            Esc();
            Check(Fits(normalList) && NSEqualRects([panel frame], opened), @"clearing the search restores the opening height", Geometry());
            Type(@"e");          // matches most clippings
            Check([[[gController clipList] rows] count] > 20 && NSHeight([scroll frame]) <= normalList && NSHeight([scroll frame]) > normalList - 24 &&
                  NSMaxY([panel frame]) == NSMaxY(opened), @"many matches: at most the opening height", Geometry());
            Esc();
            Type(@"beta");       // 12 history matches
            Check(Fits(12 * 24), @"12 matches: 12 rows tall", Geometry());
            CmdDelete();
            Check(Fits(11 * 24) && NSMaxY([panel frame]) == NSMaxY(opened), @"deleting a match shrinks it by its row", Geometry());
            CmdZ();
            Check(Fits(12 * 24), @"undo grows it back", Geometry());
            Esc();
            Check(Fits(normalList) && NSEqualRects([panel frame], opened), @"and Esc restores the opening height", Geometry());
        }

        // --- star by mouse (button action) on the highlighted row (the pointer over a row
        // highlights it), list stays open. Row 4 is the second history clipping.
        [gController hoverRow:4];
        FlycutListEntryView *row4 = EntryView(4);
        FlycutClipping *starred = [[[[[gController clipList] rows] objectAtIndex:4] clipping] retain];
        Check(![[row4 starButton] isHidden], @"the pointer's row shows its star", nil);
        [[row4 starButton] performClick:nil];
        Check([gController isOpen], @"star click keeps the list open", nil);
        Check([[[[gController clipList] rows] objectAtIndex:0] clipping] == starred, @"starred clipping is the top favorite", nil);
        FlycutListEntryView *topFav = EntryView(0);
        Check([[[topFav starButton] accessibilityLabel] isEqualToString:@"Remove from Favorites"] && [[topFav starButton] state] == NSControlStateValueOn &&
              ![[topFav starButton] isHidden], @"its star is filled now", nil);
        [[topFav starButton] performClick:nil];
        Check([[[gController clipList] rows] count] == 60 && [[op favorites] jcListCount] == 3 && [[op history] clippingAtPosition:1] == starred &&
              [[gController clipList] rowIndexOfClipping:starred] == 4,
              @"star off returns it to its time position", nil);
        CmdZ(); CmdZ();
        Check([[op history] clippingAtPosition:1] == starred && [[op favorites] jcListCount] == 3, @"two undos revert star and star off", nil);
        // An image clipping starred: its favorite row has the emoji too and reads the size and
        // "Favorite" (row 7 is the first image row; its history position is 4).
        [gController hoverRow:7];
        FlycutClipping *starredImage = [[[[[gController clipList] rows] objectAtIndex:7] clipping] retain];
        [[EntryView(7) starButton] performClick:nil];
        FlycutListEntryView *imageFavorite = EntryView(0);
        Check([starredImage isImageClipping] && [[[[gController clipList] rows] objectAtIndex:0] clipping] == starredImage &&
              [[[imageFavorite titleField] stringValue] isEqualToString:[kPictureEmoji stringByAppendingString:@" [Image 1280x720]"]] &&
              [[imageFavorite accessibilityLabel] isEqualToString:@"Image 1280 by 720, Favorite"] && ![[imageFavorite starButton] isHidden],
              @"a favorite image row has the emoji and the filled star and reads \"Image 1280 by 720, Favorite\"",
              [NSString stringWithFormat:@"%@ / %@", [[imageFavorite titleField] stringValue], [imageFavorite accessibilityLabel]]);
        CmdZ();
        Check([[op history] clippingAtPosition:4] == starredImage && [[op favorites] jcListCount] == 3, @"undo returns the starred image to the history", nil);
        [starredImage release];

        // --- Return pastes (delegate) and closes
        [gController setHighlightedRow:6];
        FlycutClipping *expected = [[[[gController clipList] rows] objectAtIndex:6] clipping];
        Return();
        Check(![gController isOpen] && delegate->closed == 1, @"Return closes the list", nil);
        Check(delegate->chosen == expected && delegate->chosenList == FlycutListHistory, @"Return chooses the highlighted clipping", nil);
        Check(![[gController clipList] canUndo], @"closing drops the undo steps", nil);

        // --- closing rules
        Open(); Esc();
        Check(![gController isOpen] && delegate->closed == 2, @"Esc with an empty search closes", nil);
        Open();
        [[NSNotificationCenter defaultCenter] postNotificationName:NSWindowDidResignKeyNotification object:panel];
        Check(![gController isOpen], @"losing key status (click outside) closes", nil);
        Open();
        [[[NSWorkspace sharedWorkspace] notificationCenter] postNotificationName:NSWorkspaceDidActivateApplicationNotification object:nil];
        Check(![gController isOpen], @"another app becoming active closes", nil);
        Open();
        [[[NSWorkspace sharedWorkspace] notificationCenter] postNotificationName:NSWorkspaceActiveSpaceDidChangeNotification object:nil];
        Check(![gController isOpen], @"a Space switch closes", nil);
        Open();
        Send(@"Cmd-,", Key(@",", 43, NSEventModifierFlagCommand));
        Check(![gController isOpen] && [[delegate->command title] isEqualToString:@"Preferences…"], @"Cmd-, runs Preferences… and closes", nil);
        Open();
        [gController close];
        Check(![gController isOpen] && delegate->closed == delegate->opened, @"every opening is closed once", nil);

        // --- the keyboard reaches the command rows below the list, as in the status menu:
        // Down past the last entry, disabled rows and separators skipped, Up back into the
        // list, Return runs the highlighted command
        {
            NSMenuItem *merge = commands[1];
            [merge setEnabled:NO];
            Open();
            NSInteger lastRow = (NSInteger)[[[gController clipList] rows] count] - 1;
            [gController setHighlightedRow:lastRow];
            Down();
            Check([CommandText() isEqualToString:@"Clear All"] && [gController highlightedRow] == -1,
                  @"Down from the last entry highlights the first command row", [NSString stringWithFormat:@"%@ row %ld", CommandText(), (long)[gController highlightedRow]]);
            Check(CommandRowHovered(@"Clear All") && !CommandRowHovered(@"Quit"), @"the highlighted command row draws the highlight", nil);
            Check(![[[gController tableView] rowViewAtRow:lastRow makeIfNecessary:NO] listHighlighted],
                  @"the entry row lost its highlight: one highlight at a time", nil);
            Down();
            Check([CommandText() isEqualToString:@"Pause Clipboard Tracking"], @"Down skips the disabled command row", CommandText());
            Down(); Down(); Down();
            Check([CommandText() isEqualToString:@"Quit"], @"Down skips the separator between the commands", CommandText());
            Down();
            Check([CommandText() isEqualToString:@"Quit"], @"Down on the last command stays there", CommandText());
            Up(); Up(); Up(); Up();
            Check([CommandText() isEqualToString:@"Clear All"], @"Up skips the disabled row back to the first command", CommandText());
            Up();
            Check([CommandText() isEqualToString:@"(none)"] && [gController highlightedRow] == lastRow && !CommandRowHovered(@"Clear All"),
                  @"Up from the first command returns to the last entry", [NSString stringWithFormat:@"%@ row %ld", CommandText(), (long)[gController highlightedRow]]);
            Down(); Down();
            Send(@"PageUp", Key(Char(NSPageUpFunctionKey), 116, NSEventModifierFlagFunction));
            Check([CommandText() isEqualToString:@"(none)"] && [gController highlightedRow] >= 0 && [gController highlightedRow] < lastRow,
                  @"Page Up from a command goes back into the list", [NSString stringWithFormat:@"%@ row %ld", CommandText(), (long)[gController highlightedRow]]);
            Type(@"zzzz");
            Down();
            Check([[[gController clipList] rows] count] == 0 && [CommandText() isEqualToString:@"Clear All"],
                  @"no match: Down goes straight to the commands", CommandText());
            Type(@"z");
            Check([CommandText() isEqualToString:@"(none)"], @"typing drops the command highlight", CommandText());
            Up();
            Check([CommandText() isEqualToString:@"Quit"], @"no match: Up goes to the last command", CommandText());
            Esc();
            Check([gController isOpen] && [CommandText() isEqualToString:@"(none)"], @"Esc clears the search and the highlight", CommandText());
            id pauseRow = CommandRow(@"Pause Clipboard Tracking");
            Check([[pauseRow accessibilityLabel] isEqualToString:@"Pause Clipboard Tracking"] &&
                  [[pauseRow accessibilityRole] isEqualToString:NSAccessibilityMenuItemRole],
                  @"command rows keep their VoiceOver label and menu-item role", [pauseRow accessibilityLabel]);
            [gController setHighlightedRow:6];
            [CommandRow(@"Quit") mouseEntered:nil];
            Check([CommandText() isEqualToString:@"Quit"] && [gController highlightedRow] == -1 &&
                  ![[[gController tableView] rowViewAtRow:6 makeIfNecessary:NO] listHighlighted],
                  @"the pointer on a command row takes the highlight from the entry", CommandText());
            [CommandRow(@"Quit") mouseExited:nil];
            Check([CommandText() isEqualToString:@"(none)"] && !CommandRowHovered(@"Quit"), @"leaving the command row drops its highlight", CommandText());
            [CommandRow(@"Quit") mouseEntered:nil];
            [gController hoverRow:6];
            Check([CommandText() isEqualToString:@"(none)"] && !CommandRowHovered(@"Quit") && [gController highlightedRow] == 6,
                  @"the pointer on an entry takes the highlight from the command row", CommandText());
            [CommandRow(@"Merge All") mouseEntered:nil];
            Check([CommandText() isEqualToString:@"(none)"] && [gController highlightedRow] == 6, @"a disabled command row takes no highlight", CommandText());
            [gController setHighlightedRow:lastRow];
            Down(); Down();
            [delegate->command release]; delegate->command = nil;
            Return();
            Check(![gController isOpen] && [[delegate->command title] isEqualToString:@"Pause Clipboard Tracking"],
                  @"Return runs the highlighted command and closes the list", [delegate->command title]);
            [merge setEnabled:YES];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (commands)", nil);

        // --- VoiceOver: rows can be pressed, the highlighted row is the selected element,
        // and arrow-key moves are announced (keyboard focus stays in the search field)
        {
            Open();
            Check([[panel accessibilityLabel] isEqualToString:@"Flycut"], @"the panel has a VoiceOver label", [panel accessibilityLabel]);
            [gAnnouncements removeAllObjects];
            Down();
            NSString *first = HighlightedText();
            Check([[gAnnouncements lastObject] isEqualToString:[first stringByAppendingString:@", Favorite"]],
                  @"an arrow-key move announces the highlighted row (a favorite says so)",
                  [NSString stringWithFormat:@"%@ / %@", [gAnnouncements lastObject], first]);
            Check([EntryView(0) isAccessibilitySelected] && ![EntryView(1) isAccessibilitySelected], @"the highlighted row is the selected element", nil);
            Down();
            Check(![EntryView(0) isAccessibilitySelected] && [EntryView(1) isAccessibilitySelected] &&
                  [[gAnnouncements lastObject] hasPrefix:HighlightedText()], @"the next move moves the selection and is announced", [gAnnouncements lastObject]);
            Down(); Down();
            Check([[gAnnouncements lastObject] isEqualToString:HighlightedText()], @"a history row is announced by its text alone", [gAnnouncements lastObject]);
            [gController setHighlightedRow:6];
            Down();   // the image row 7
            Check([gController highlightedRow] == 7 && [HighlightedText() isEqualToString:@"[Image 1280x720]"] &&
                  [[gAnnouncements lastObject] isEqualToString:@"Image 1280 by 720"],
                  @"an arrow-key move onto an image row announces \"Image 1280 by 720\", without the emoji", [gAnnouncements lastObject]);
            NSUInteger announced = [gAnnouncements count];
            [gController hoverRow:3];
            Check([gAnnouncements count] == announced, @"pointer moves are not announced", nil);
            NSInteger lastRow = (NSInteger)[[[gController clipList] rows] count] - 1;
            [gController setHighlightedRow:lastRow];
            Down();
            Check([[gAnnouncements lastObject] isEqualToString:@"Clear All"] && [CommandRow(@"Clear All") isAccessibilitySelected],
                  @"moving onto a command row announces and selects it", [gAnnouncements lastObject]);
            Down();
            Check(![CommandRow(@"Clear All") isAccessibilitySelected], @"the command row is deselected when the highlight leaves", nil);
            Send(@"PageUp", Key(Char(NSPageUpFunctionKey), 116, NSEventModifierFlagFunction));
            Check([[gAnnouncements lastObject] isEqualToString:AnnouncedText()], @"a Page Up move is announced", [gAnnouncements lastObject]);
            FlycutListEntryView *pressRow = EntryView(6);
            FlycutClipping *pressed = [[[[gController clipList] rows] objectAtIndex:6] clipping];
            BOOL pressable = [pressRow respondsToSelector:@selector(accessibilityPerformPress)];
            BOOL handled = pressable && [pressRow accessibilityPerformPress];
            Check(handled && ![gController isOpen] && delegate->chosen == pressed && delegate->chosenList == FlycutListHistory,
                  @"VoiceOver's press on an entry row pastes that clipping and closes the list", nil);
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (VoiceOver)", nil);

        // --- VoiceOver: the search field has a name; the table holds one row per clipping,
        // no heading or divider rows. (AppKit wraps every cell of a view-based table in an
        // element that reports itself focused.)
        {
            Open();
            NSTableView *table = [gController tableView];
            id field = [panel accessibilityFocusedUIElement];
            Check([AX(field, NSAccessibilityDescriptionAttribute) isEqualToString:@"Search clippings"] &&
                  [AX(field, NSAccessibilityPlaceholderValueAttribute) isEqualToString:@"Search"],
                  @"the search field has an accessible name besides its placeholder",
                  [NSString stringWithFormat:@"%@ / %@ (%@)", AX(field, NSAccessibilityDescriptionAttribute),
                   AX(field, NSAccessibilityPlaceholderValueAttribute), [field className]]);
            NSArray *axRows = AX(table, NSAccessibilityRowsAttribute);
            NSArray *rows = [[gController clipList] rows];
            NSUInteger headings = 0;
            for (id r in axRows)
                for (id child in AX(r, NSAccessibilityChildrenAttribute) ?: @[])
                    if ([AXRoleOf(child) isEqualToString:@"AXHeading"]) headings++;
            Check([axRows count] == [rows count] && headings == 0, @"one table row per clipping, no headings",
                  [NSString stringWithFormat:@"%lu rows for %lu clippings, %lu headings", (unsigned long)[axRows count], (unsigned long)[rows count], (unsigned long)headings]);
            id entry = AXRowForListRow(axRows, 3);
            id cell = [AX(entry, NSAccessibilityChildrenAttribute) firstObject];
            id favoriteCell = [AX(AXRowForListRow(axRows, 0), NSAccessibilityChildrenAttribute) firstObject];
            Check([AXRoleOf(entry) isEqualToString:NSAccessibilityRowRole] && [AXRoleOf(cell) isEqualToString:NSAccessibilityCellRole] &&
                  [AX(cell, NSAccessibilityDescriptionAttribute) isEqualToString:[EntryView(3) accessibilityLabel]] &&
                  [AX(favoriteCell, NSAccessibilityDescriptionAttribute) hasSuffix:@", Favorite"],
                  @"entry rows stay AppKit's table rows with their text; a favorite's says Favorite",
                  [NSString stringWithFormat:@"%@ / %@", AX(cell, NSAccessibilityDescriptionAttribute), AX(favoriteCell, NSAccessibilityDescriptionAttribute)]);
            // An image row's cell and its text element read "Image 1280 by 720": the text
            // element's value is what VoiceOver reads when it goes into the cell, and it must
            // not carry the emoji either. A text row's text element keeps its text.
            // (AppKit's cell elements are mock objects: read a row's before asking for another's.)
            id textRowValue = AX([AX(cell, NSAccessibilityChildrenAttribute) firstObject], NSAccessibilityValueAttribute);   // row 3's cell, above
            id imageCell = [AX(AXRowForListRow(axRows, 7), NSAccessibilityChildrenAttribute) firstObject];
            NSMutableArray *imageServed = [NSMutableArray array];
            NSMutableArray *imageTexts = [NSMutableArray array];
            for (id element in [@[imageCell] arrayByAddingObjectsFromArray:AX(imageCell, NSAccessibilityChildrenAttribute) ?: @[]])
                for (NSString *attribute in @[NSAccessibilityDescriptionAttribute, NSAccessibilityTitleAttribute, NSAccessibilityValueAttribute, NSAccessibilityHelpAttribute]) {
                    id value = AX(element, attribute);
                    if ([value isKindOfClass:[NSString class]]) [imageServed addObject:value];
                    if ([AXRoleOf(element) isEqualToString:NSAccessibilityStaticTextRole] && [attribute isEqualToString:NSAccessibilityValueAttribute] && [value isKindOfClass:[NSString class]])
                        [imageTexts addObject:value];
                }
            BOOL imageEmojiHeard = NO;
            for (NSString *text in imageServed) if ([text rangeOfString:@"\U0001F5BC"].location != NSNotFound) imageEmojiHeard = YES;
            Check([AX(imageCell, NSAccessibilityDescriptionAttribute) isEqualToString:@"Image 1280 by 720"] && [imageTexts isEqualToArray:@[@"Image 1280 by 720"]] &&
                  !imageEmojiHeard && [textRowValue isEqualToString:[EntryView(3) accessibilityLabel]],
                  @"VoiceOver's tree: an image row's cell and its text read \"Image 1280 by 720\", the emoji in no label or value",
                  [NSString stringWithFormat:@"served %@, text values %@, a text row's text %@", imageServed, imageTexts, textRowValue]);
            [gController close];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (rows)", nil);

        // --- the command rows follow their menu items while the list is open: pausing by
        // Option-click on the status item (or any other path) retitles the Pause item, and
        // -menuWillOpen: retitles it while the list opens
        {
            NSMenuItem *merge = commands[1], *pause = commands[2];
            Open();
            FlycutListCommandRow *pauseRow = CommandRow(@"Pause Clipboard Tracking"), *mergeRow = CommandRow(@"Merge All");
            [pause setTitle:@"Resume Clipboard Tracking"];
            Check([[[pauseRow valueForKey:@"titleField"] stringValue] isEqualToString:@"Resume Clipboard Tracking"] &&
                  [[pauseRow accessibilityLabel] isEqualToString:@"Resume Clipboard Tracking"],
                  @"a command retitled while the list is open shows the new title (text and VoiceOver)",
                  [[pauseRow valueForKey:@"titleField"] stringValue]);
            [merge setEnabled:NO];
            Check(SameColor([[mergeRow valueForKey:@"titleField"] textColor], [NSColor tertiaryLabelColor]) && ![mergeRow isAccessibilityEnabled],
                  @"a command disabled while the list is open is shown disabled", nil);
            [gController setHighlightedRow:(NSInteger)[[[gController clipList] rows] count] - 1];
            Down(); Down();
            Check([CommandText() isEqualToString:@"Resume Clipboard Tracking"], @"and the keyboard skips it", CommandText());
            [pause setEnabled:NO];
            Check([CommandText() isEqualToString:@"(none)"] && !CommandRowHovered(@"Resume Clipboard Tracking"),
                  @"a highlighted command that gets disabled loses the highlight", CommandText());
            [pause setEnabled:YES];
            [merge setEnabled:YES];
            Check(SameColor([[mergeRow valueForKey:@"titleField"] textColor], [NSColor labelColor]) && [mergeRow isAccessibilityEnabled],
                  @"enabled again, the row is shown enabled", nil);
            [pause setTitle:@"Pause Clipboard Tracking"];
            [gController close];
            delegate->retitleOnOpen = pause;
            delegate->titleOnOpen = @"Resume Clipboard Tracking";
            Open();
            FlycutListCommandRow *openedRow = CommandRowForItem(pause);
            Check([[[openedRow valueForKey:@"titleField"] stringValue] isEqualToString:@"Resume Clipboard Tracking"] &&
                  [[openedRow accessibilityLabel] isEqualToString:@"Resume Clipboard Tracking"],
                  @"a title the delegate sets while the list opens is shown", [[openedRow valueForKey:@"titleField"] stringValue]);
            delegate->retitleOnOpen = nil;
            [gController close];
            [pause setTitle:@"Pause Clipboard Tracking"];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (live commands)", nil);

        // --- a clipping that lands while the list is open (a capture already in flight when
        // it opened) is listed at once; the highlight stays on its clipping, the list keeps its
        // scroll position, and a search keeps filtering
        {
            Open();
            SEL refresh = sel_registerName("storesDidChange");
            NSClipView *clip = [scroll contentView];
            [clip scrollToPoint:NSMakePoint(0, 240)];
            [scroll reflectScrolledClipView:clip];
            [gController setHighlightedRow:20];
            FlycutClipping *kept = [[[[gController clipList] rows] objectAtIndex:20] clipping];
            CGFloat offset = NSMinY([clip bounds]);
            NSUInteger count = [[[gController clipList] rows] count];
            [[op history] addClipping:Clip(@"angekommen, während die Liste offen ist", 2000)];
            if ([gController respondsToSelector:refresh]) [gController performSelector:refresh];
            Check([[[gController clipList] rows] count] == count + 1 && [[gController tableView] numberOfRows] == (NSInteger)count + 1 &&
                  [[[[[gController clipList] rows] objectAtIndex:3] clipping] isEqual:[[op history] clippingAtPosition:0]],
                  @"a clipping that lands while the list is open is listed at once", nil);
            Check([[[[gController clipList] rows] objectAtIndex:[gController highlightedRow] >= 0 ? [gController highlightedRow] : 0] clipping] == kept &&
                  [gController highlightedRow] == 21, @"the highlight stays on the same clipping",
                  [NSString stringWithFormat:@"%ld", (long)[gController highlightedRow]]);
            Check(NSMinY([clip bounds]) == offset, @"the list keeps its scroll position", [NSString stringWithFormat:@"%g / %g", NSMinY([clip bounds]), offset]);
            Down();
            Check([gController highlightedRow] == 22, @"arrows go on from the kept highlight", nil);
            Type(@"beta");
            NSUInteger matches = [[[gController clipList] rows] count];
            [[op history] addClipping:Clip(@"noch eine Zeile ohne Treffer", 2001)];
            [[op history] addClipping:Clip(@"beta neu", 2002)];
            if ([gController respondsToSelector:refresh]) [gController performSelector:refresh];
            Check([[[gController clipList] rows] count] == matches + 1 && [[[gController searchField] stringValue] isEqualToString:@"beta"] &&
                  [[[[[gController clipList] rows] objectAtIndex:0] clipping] isEqual:[[op history] clippingAtPosition:0]],
                  @"while searching, only a matching new clipping is added", [NSString stringWithFormat:@"%lu -> %lu", (unsigned long)matches, (unsigned long)[[[gController clipList] rows] count]]);
            [gController close];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (refresh)", nil);

        // --- press on the status item, drag into the list, release on a row: chosen as in a
        // native menu. The drag events belong to the status item's window; here they are
        // NSEvents in this process's own queue (postEvent:), nothing goes to the system.
        {
            SEL track = sel_registerName("trackMouseFromEvent:");
            BOOL tracks = [gController respondsToSelector:track];
            NSTableView *table = [gController tableView];
            NSPoint (^RowPoint)(NSInteger) = ^NSPoint(NSInteger row) {
                NSRect rect = [table rectOfRow:row];
                return [panel convertPointToScreen:[table convertPoint:NSMakePoint(NSMidX(rect), NSMidY(rect)) toView:nil]];
            };
            NSEvent *(^Mouse)(NSEventType, NSPoint) = ^NSEvent *(NSEventType type, NSPoint point) {
                return [NSEvent mouseEventWithType:type location:point modifierFlags:0 timestamp:0 windowNumber:0 context:nil
                                       eventNumber:0 clickCount:1 pressure:1];
            };
            void (^Track)(NSEventType) = ^(NSEventType down) {
                if (tracks) [gController performSelector:track withObject:Mouse(down, NSMakePoint(-20000, -20000))];
                while ([NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES] != nil) {}
            };
            Open();
            gDragBegins = 0;
            [delegate->chosen release]; delegate->chosen = nil;
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseDragged, RowPoint(7)) atStart:NO];
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000)) atStart:NO];
            Track(NSEventTypeLeftMouseDown);
            Check(tracks && [gController isOpen] && [gController highlightedRow] == 7 && delegate->chosen == nil,
                  @"dragging over a row highlights it; releasing outside the list leaves it open", [NSString stringWithFormat:@"%ld", (long)[gController highlightedRow]]);
            FlycutClipping *nine = [[[[gController clipList] rows] objectAtIndex:9] clipping];
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseDragged, RowPoint(8)) atStart:NO];
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, RowPoint(9)) atStart:NO];
            Track(NSEventTypeLeftMouseDown);
            Check(![gController isOpen] && delegate->chosen == nine && delegate->chosenList == FlycutListHistory,
                  @"releasing on a row chooses that row and closes the list", nil);
            Open();
            FlycutClipping *favorite = [[[[gController clipList] rows] objectAtIndex:2] clipping];
            [NSApp postEvent:Mouse(NSEventTypeRightMouseDragged, RowPoint(2)) atStart:NO];
            [NSApp postEvent:Mouse(NSEventTypeRightMouseUp, RowPoint(2)) atStart:NO];
            Track(NSEventTypeRightMouseDown);
            Check(![gController isOpen] && delegate->chosen == favorite && delegate->chosenList == FlycutListFavorites,
                  @"the same with the right button", nil);
            Open();
            NSMenuItem *merge = commands[1];
            [merge setEnabled:NO];
            FlycutListCommandRow *mergeRow = CommandRow(@"Merge All");
            NSPoint mergePoint = [panel convertPointToScreen:[mergeRow convertPoint:NSMakePoint(50, 12) toView:nil]];
            [delegate->command release]; delegate->command = nil;
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, mergePoint) atStart:NO];
            Track(NSEventTypeLeftMouseDown);
            Check(tracks && [gController isOpen] && delegate->command == nil, @"releasing on a disabled command row does nothing", nil);
            [merge setEnabled:YES];
            [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, mergePoint) atStart:NO];
            Track(NSEventTypeLeftMouseDown);
            Check(![gController isOpen] && [[delegate->command title] isEqualToString:@"Merge All"], @"releasing on a command row runs it", nil);
            // A long drag: the press handler (a local event monitor) returns only when the
            // button is up, so the loop must let go of each event before it reads the next.
            Open();
            @autoreleasepool {
                for (int i = 0; i < 40; i++)
                    [NSApp postEvent:Mouse(NSEventTypeLeftMouseDragged, RowPoint(5 + i % 4)) atStart:NO];
                [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, NSMakePoint(-20000, -20000)) atStart:NO];
            }
            gSpyEvents = YES;
            @autoreleasepool {
                if (tracks) [gController performSelector:track withObject:Mouse(NSEventTypeLeftMouseDown, NSMakePoint(-20000, -20000))];
                gSpyEvents = NO;
                Check(tracks && gSpiesMade == 40 && gSpiesMaxAlive <= 1 && [gController isOpen],
                      @"a long drag: each event is released before the next one is read",
                      [NSString stringWithFormat:@"%d drag events read, at most %d alive at a time", gSpiesMade, gSpiesMaxAlive]);
            }
            while ([NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES] != nil) {}
            // Every press above went down on the status item and moved far across rows of
            // the list: it is followed like a menu and never becomes a drag of a row.
            Check(tracks && gDragBegins == 0 && [[[gController tableView] hiddenRowIndexes] count] == 0,
                  @"press, drag and release from the status item never starts a drag session",
                  [NSString stringWithFormat:@"%d drag sessions", gDragBegins]);
            [gController close];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (press-drag-release)", nil);

        // --- dragging a row. A press on a row that moves past AppKit's drag threshold starts
        // a drag session of that row from the table (recorded here, never started); a press
        // released within the threshold is a click and pastes. The drag carries the
        // clipping's content; inside the list the favorites block takes drops, the history
        // block does not. The table's own NSDraggingSource and NSDraggingDestination methods
        // are driven with a fake NSDraggingInfo; nothing reaches a pasteboard.
        {
            NSTableView *table = [gController tableView];
            NSInteger windowNumber = [panel windowNumber];
            NSPoint (^Centre)(NSInteger) = ^NSPoint(NSInteger row) {
                NSRect rect = [table rectOfRow:row];
                return [table convertPoint:NSMakePoint(NSMinX(rect) + 120, NSMidY(rect)) toView:nil];
            };
            NSEvent *(^Mouse)(NSEventType, NSPoint) = ^NSEvent *(NSEventType type, NSPoint point) {
                return [NSEvent mouseEventWithType:type location:point modifierFlags:0 timestamp:0 windowNumber:windowNumber context:nil
                                       eventNumber:0 clickCount:1 pressure:type == NSEventTypeLeftMouseUp ? 0 : 1];
            };
            void (^Drain)(void) = ^{
                while ([NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES] != nil) {}
            };
            // A press on a row, moved by (dx, dy) window points and released there.
            void (^Press)(NSInteger, CGFloat, CGFloat) = ^(NSInteger row, CGFloat dx, CGFloat dy) {
                NSPoint start = Centre(row), end = NSMakePoint(start.x + dx, start.y + dy);
                if (dx != 0 || dy != 0)
                    [NSApp postEvent:Mouse(NSEventTypeLeftMouseDragged, end) atStart:NO];
                [NSApp postEvent:Mouse(NSEventTypeLeftMouseUp, end) atStart:NO];
                [table mouseDown:Mouse(NSEventTypeLeftMouseDown, start)];
                Drain();
            };
            // The session ends (AppKit tells the table, the table its data source).
            void (^EndDrag)(NSPoint, NSDragOperation) = ^(NSPoint screenPoint, NSDragOperation operation) {
                [table draggingSession:nil endedAtPoint:screenPoint operation:operation];
            };
            NSPoint far = NSMakePoint(5000, 5000);   // another application or the Finder
            NSPoint insidePanel = NSMakePoint(NSMidX([panel frame]), NSMidY([panel frame]));
            BOOL (^SameLists)(NSArray *) = ^BOOL(NSArray *snapshot) {
                NSArray *now = [op listsSnapshot];
                for (NSUInteger i = 0; i < 2; i++) {
                    NSArray *a = now[i], *b = snapshot[i];
                    if ([a count] != [b count]) return NO;
                    for (NSUInteger j = 0; j < [a count]; j++) if (a[j] != b[j]) return NO;
                }
                return YES;
            };
            NSInteger (^FavoriteCount)(void) = ^NSInteger {
                NSInteger n = 0;
                for (FlycutClipListRow *r in [[gController clipList] rows]) if ([r list] == FlycutListFavorites) n++;
                return n;
            };

            NSUInteger deletedImages = [gDeletedImages count];

            // Click versus drag
            Open();
            [delegate->chosen release]; delegate->chosen = nil;
            gDragBegins = 0;
            FlycutClipping *clicked = [[[[gController clipList] rows] objectAtIndex:6] clipping];
            Press(6, 1, -2);
            Check(gDragBegins == 0 && ![gController isOpen] && delegate->chosen == clicked,
                  @"a press released within the drag threshold pastes the row, as a click",
                  [NSString stringWithFormat:@"%d drags, open %d", gDragBegins, [gController isOpen]]);
            Open();
            [delegate->chosen release]; delegate->chosen = nil;
            NSArray *before = [[op listsSnapshot] retain];
            FlycutClipping *dragged = [[[[gController clipList] rows] objectAtIndex:6] clipping];
            Press(6, 0, -10);
            Check(gDragBegins == 1 && gDragView == table && [gDragItems count] == 1 && delegate->chosen == nil && [gController isOpen],
                  @"moving past the drag threshold drags the row from the list instead of pasting it",
                  [NSString stringWithFormat:@"%d drags from %@, %lu items, chosen %@, open %d", gDragBegins, [gDragView className],
                   (unsigned long)[gDragItems count], [delegate->chosen displayString], [gController isOpen]]);
            Check(SameLists(before) && [[[gController clipList] rows] objectAtIndex:6] != nil &&
                  [[[[gController clipList] rows] objectAtIndex:6] clipping] == dragged,
                  @"starting a drag changes no list", nil);
            EndDrag(far, NSDragOperationNone);
            [gController setHighlightedRow:6];
            Press(6, 8, 0);
            Check(gDragBegins == 2 && delegate->chosen == nil, @"sideways too", [NSString stringWithFormat:@"%d drags", gDragBegins]);
            // The drag image is a picture of the row's view, without the highlight drawn
            // behind it by the row: a highlighted row's white title would vanish on a
            // light window under the pointer.
            NSArray *components = [gDragItems count] == 1 ? [(NSDraggingItem *)gDragItems[0] imageComponents] : nil;
            NSRect imageFrame = [components count] == 1 ? [(NSDraggingImageComponent *)components[0] frame] : NSZeroRect;
            Check([gController highlightedRow] == -1 && NSWidth(imageFrame) >= NSMaxX([[EntryView(6) titleField] frame]) &&
                  [[[EntryView(6) titleField] textColor] isEqual:[NSColor labelColor]],
                  @"the dragged row is not highlighted; its drag image shows its title in the normal colour",
                  [NSString stringWithFormat:@"highlight %ld, components %@ %@, colour %@", (long)[gController highlightedRow],
                   [components valueForKey:@"key"], NSStringFromRect(imageFrame), [[EntryView(6) titleField] textColor]]);
            EndDrag(far, NSDragOperationNone);
            Check([table draggingSession:nil sourceOperationMaskForDraggingContext:NSDraggingContextOutsideApplication] == NSDragOperationCopy &&
                  ([table draggingSession:nil sourceOperationMaskForDraggingContext:NSDraggingContextWithinApplication] & NSDragOperationMove) != 0,
                  @"other applications and the Finder may only copy a dragged row; inside the list it moves",
                  [NSString stringWithFormat:@"outside %lu, inside %lu",
                   (unsigned long)[table draggingSession:nil sourceOperationMaskForDraggingContext:NSDraggingContextOutsideApplication],
                   (unsigned long)[table draggingSession:nil sourceOperationMaskForDraggingContext:NSDraggingContextWithinApplication]]);

            // What the drag carries
            NSArray *rows = [[gController clipList] rows];
            NSInteger textRow = -1, imageRow = -1;
            for (NSInteger i = 0; i < (NSInteger)[rows count]; i++) {
                FlycutClipListRow *r = rows[i];
                if ([r list] != FlycutListHistory) continue;
                if (textRow < 0 && ![[r clipping] isImageClipping]) textRow = i;
                if (imageRow < 0 && [[r clipping] isImageClipping]) imageRow = i;
            }
            FlycutClipping *text = [rows[textRow] clipping], *image = [rows[imageRow] clipping];
            NSData *rtf = [@"{\\rtf1\\ansi Rechnung}" dataUsingEncoding:NSUTF8StringEncoding];
            NSData *html = [@"<b>Rechnung</b>" dataUsingEncoding:NSUTF8StringEncoding];
            [text setRichData:@{NSPasteboardTypeRTF: rtf, NSPasteboardTypeHTML: html}];
            Press(textRow, 0, -10);
            id writer = [gDragItems count] == 1 ? [(NSDraggingItem *)gDragItems[0] item] : nil;
            NSArray *types = [writer isKindOfClass:[NSPasteboardItem class]] ? [(NSPasteboardItem *)writer types] : nil;
            Check([[(NSPasteboardItem *)writer stringForType:NSPasteboardTypeString] isEqualToString:[text contents]] &&
                  [[(NSPasteboardItem *)writer dataForType:NSPasteboardTypeRTF] isEqual:rtf] &&
                  [[(NSPasteboardItem *)writer dataForType:NSPasteboardTypeHTML] isEqual:html],
                  @"a text row's drag carries its text, RTF and HTML", [types description]);
            Check(types != nil && ![writer isKindOfClass:[NSFilePromiseProvider class]] && ![types containsObject:NSPasteboardTypeFileURL],
                  @"text is dragged as text, no file (the Finder makes its own clipping file of it)", [types description]);
            EndDrag(far, NSDragOperationNone);
            Press(imageRow, 0, -10);
            id promise = [gDragItems count] == 1 ? [(NSDraggingItem *)gDragItems[0] item] : nil;
            BOOL promises = [promise isKindOfClass:[NSFilePromiseProvider class]];
            NSData *bytes = [[FlycutImageStore sharedStore] imageDataForHash:[image imageHash]];
            NSArray *promiseTypes = promises ? [promise writableTypesForPasteboard:(NSPasteboard *)nil] : nil;
            Check(promises && [[promise fileType] isEqualToString:NSPasteboardTypePNG] && [promiseTypes containsObject:NSPasteboardTypePNG] &&
                  [[promise pasteboardPropertyListForType:NSPasteboardTypePNG] isEqual:bytes],
                  @"an image row's drag promises a PNG file and carries the stored PNG data", [promiseTypes description]);
            id<NSFilePromiseProviderDelegate> promiser = promises ? [(NSFilePromiseProvider *)promise delegate] : nil;
            NSString *fileName = [promiser filePromiseProvider:promise fileNameForType:NSPasteboardTypePNG];
            Check([fileName hasPrefix:@"Flycut Image "] && [fileName hasSuffix:@".png"],
                  @"the promised file is named \"Flycut Image <date> at <time>.png\"", fileName);
            Check([fileName isEqualToString:FlycutListImageFileName(image, NSPasteboardTypePNG)] && [fileName rangeOfString:@"\U0001F5BC"].location == NSNotFound &&
                  [fileName rangeOfString:@"Image 1280"].location == NSNotFound,
                  @"the promised file name has no emoji and no size text, as before", fileName);
            NSURL *target = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:@"flycut-probe-drop.png"]];
            [[NSFileManager defaultManager] removeItemAtURL:target error:NULL];
            __block BOOL written = NO;
            __block NSError *writeError = nil;
            [promiser filePromiseProvider:promise writePromiseToURL:target completionHandler:^(NSError *error) {
                written = YES;
                writeError = [error retain];
            }];
            Check(written && writeError == nil && [[NSData dataWithContentsOfURL:target] isEqual:bytes],
                  @"the Finder's file gets exactly the stored image bytes", [writeError description]);
            [[NSFileManager defaultManager] removeItemAtURL:target error:NULL];
            NSOperationQueue *queue = [promiser respondsToSelector:@selector(operationQueueForFilePromiseProvider:)] ?
                [promiser operationQueueForFilePromiseProvider:promise] : nil;
            Check(queue != nil && queue != [NSOperationQueue mainQueue], @"the file is written off the main queue", nil);
            EndDrag(far, NSDragOperationNone);
            Check(SameLists(before) && [gDeletedImages count] == deletedImages && [gController isOpen],
                  @"dragging rows out changes no list and deletes no image", nil);
            [before release];

            // Drops inside the list: a favorite
            NSInteger favorites = FavoriteCount();
            rows = [[gController clipList] rows];
            FlycutClipping *second = [rows[1] clipping];
            Press(1, 0, -10);
            FCFakeDraggingInfo *info = [[[FCFakeDraggingInfo alloc] init] autorelease];
            info->window = panel;
            info->source = table;
            info->pasteboard = [[[FCFakeDragPasteboard alloc] init] autorelease];
            SEL validateSelector = @selector(tableView:validateDrop:proposedRow:proposedDropOperation:);
            BOOL validates = [gController respondsToSelector:validateSelector];
            NSDragOperation (^Validate)(NSInteger, NSTableViewDropOperation) = ^NSDragOperation(NSInteger row, NSTableViewDropOperation operation) {
                return validates ? [gController tableView:table validateDrop:info proposedRow:row proposedDropOperation:operation] : NSDragOperationNone;
            };
            BOOL favoritesBlock = YES, historyBlock = YES;
            for (NSInteger r = 0; r <= favorites; r++) favoritesBlock = favoritesBlock && Validate(r, NSTableViewDropAbove) == NSDragOperationMove;
            for (NSInteger r = favorites + 1; r <= favorites + 6; r++)
                historyBlock = historyBlock && Validate(r, NSTableViewDropAbove) == NSDragOperationNone && Validate(r, NSTableViewDropOn) == NSDragOperationNone;
            Check(favorites == 3 && favoritesBlock, @"a dragged favorite can be dropped anywhere in the favorites block", nil);
            Check(historyBlock, @"but not in the history block: the table shows no drop indicator there", nil);
            info->source = nil;
            Check(Validate(0, NSTableViewDropAbove) == NSDragOperationNone, @"a drag from another application is not taken", nil);
            info->source = table;
            Check([table draggingDestinationFeedbackStyle] == NSTableViewDraggingDestinationFeedbackStyleGap,
                  @"the rows make room for a drop (gap feedback)", nil);
            info->location = Centre(favorites + 4);
            [table draggingEntered:info];
            NSDragOperation overHistory = [table draggingUpdated:info];
            info->location = Centre(0);
            NSDragOperation overFirst = [table draggingUpdated:info];
            BOOL dropped = [table prepareForDragOperation:info] && [table performDragOperation:info];
            [table concludeDragOperation:info];
            // The list's own drop keeps it open, not where AppKit reports the end: a list
            // that got shorter by the drop (Remove duplicates) may no longer be under it.
            EndDrag(far, NSDragOperationMove);
            Check(overHistory == NSDragOperationNone && overFirst == NSDragOperationMove && dropped &&
                  [[op favorites] clippingAtPosition:0] == second && FavoriteCount() == favorites && [gController isOpen],
                  @"dropping the second favorite on the first row's place makes it the first favorite; the list stays open",
                  [NSString stringWithFormat:@"over history %lu, over first %lu, dropped %d", (unsigned long)overHistory, (unsigned long)overFirst, dropped]);
            Check([[table hiddenRowIndexes] count] == 0 && [[[[gController clipList] rows] objectAtIndex:0] clipping] == second,
                  @"after the drop every row is shown, in the new order", [[table hiddenRowIndexes] description]);
            id typing = [panel firstResponder];
            Check([typing isKindOfClass:[NSTextView class]] && [(NSTextView *)typing delegate] == (id)[gController searchField],
                  @"after pressing and dragging rows typing still goes to the search field", NSStringFromClass([typing class]));
            CmdZ();
            Check([[op favorites] clippingAtPosition:1] == second, @"Cmd-Z undoes the move", nil);

            // A history clipping dropped into the favorites becomes a favorite there
            rows = [[gController clipList] rows];
            NSInteger historyRow = favorites + 2;
            FlycutClipping *starred = [rows[historyRow] clipping];
            NSUInteger historyCount = (NSUInteger)[[op history] jcListCount];
            Press(historyRow, 0, -10);
            favoritesBlock = YES; historyBlock = YES;
            for (NSInteger r = 0; r <= favorites; r++) favoritesBlock = favoritesBlock && Validate(r, NSTableViewDropAbove) == NSDragOperationMove;
            for (NSInteger r = favorites + 1; r <= favorites + 6; r++)
                historyBlock = historyBlock && Validate(r, NSTableViewDropAbove) == NSDragOperationNone && Validate(r, NSTableViewDropOn) == NSDragOperationNone;
            Check(favoritesBlock && historyBlock, @"a dragged history row can be dropped into the favorites block only", nil);
            info->location = Centre(1);
            [table draggingEntered:info];
            NSDragOperation overFavorite = [table draggingUpdated:info];
            dropped = [table prepareForDragOperation:info] && [table performDragOperation:info];
            [table concludeDragOperation:info];
            EndDrag(insidePanel, NSDragOperationMove);
            NSInteger newRow = [[gController clipList] rowIndexOfClipping:starred];
            Check(overFavorite == NSDragOperationMove && dropped && [[op favorites] clippingAtPosition:1] == starred &&
                  (NSUInteger)[[op history] jcListCount] == historyCount - 1 && newRow == 1 &&
                  [[EntryView(newRow) starButton] state] == NSControlStateValueOn && [gController isOpen],
                  @"a history row dropped between two favorites becomes a favorite there, with its filled star",
                  [NSString stringWithFormat:@"row %ld", (long)newRow]);
            CmdZ();
            Check([[gController clipList] rowIndexOfClipping:starred] == historyRow && FavoriteCount() == favorites,
                  @"Cmd-Z returns it to its place in the history", nil);

            // A favorite dropped on the history is not unstarred
            rows = [[gController clipList] rows];
            FlycutClipping *first = [rows[0] clipping];
            Press(0, 0, -10);
            info->location = Centre(favorites + 3);
            [table draggingEntered:info];
            overHistory = [table draggingUpdated:info];
            [table prepareForDragOperation:info];
            [table performDragOperation:info];
            [table concludeDragOperation:info];
            EndDrag(insidePanel, NSDragOperationNone);
            Check(overHistory == NSDragOperationNone && [[op favorites] clippingAtPosition:0] == first && FavoriteCount() == favorites,
                  @"a favorite dropped on the history stays a favorite (only the star unstars)", nil);

            // How a drag ends
            before = [[op listsSnapshot] retain];
            [delegate->chosen release]; delegate->chosen = nil;
            Press(textRow, 0, -10);
            EndDrag(far, NSDragOperationNone);
            Check([gController isOpen] && [[table hiddenRowIndexes] count] == 0 && delegate->chosen == nil,
                  @"a cancelled drag leaves the list open with every row shown", nil);
            Press(textRow, 0, -10);
            EndDrag(insidePanel, NSDragOperationCopy);
            Check([gController isOpen], @"a drop inside the list's own panel (its search field) keeps the list open", nil);
            NSUInteger closed = delegate->closed;
            Press(textRow, 0, -10);
            EndDrag(far, NSDragOperationCopy);
            Check(![gController isOpen] && delegate->closed == closed + 1 && delegate->chosen == nil && SameLists(before) &&
                  [gDeletedImages count] == deletedImages,
                  @"a drop in another application or the Finder closes the list; nothing is pasted, moved or deleted",
                  [NSString stringWithFormat:@"open %d", [gController isOpen]]);
            [before release];

            // VoiceOver and keyboard users move favorites with custom actions
            Open();
            NSArray *(^ActionNames)(NSInteger) = ^NSArray *(NSInteger row) {
                return [[EntryView(row) accessibilityCustomActions] valueForKey:@"name"];
            };
            Check(![ActionNames(0) containsObject:@"Move Up"] && [ActionNames(0) containsObject:@"Move Down"] &&
                  [ActionNames(1) containsObject:@"Move Up"] && [ActionNames(1) containsObject:@"Move Down"] &&
                  [ActionNames(favorites - 1) containsObject:@"Move Up"] && ![ActionNames(favorites - 1) containsObject:@"Move Down"] &&
                  ![ActionNames(favorites) containsObject:@"Move Up"] && ![ActionNames(favorites) containsObject:@"Move Down"],
                  @"favorites have Move Up and Move Down actions where they can move; history rows have none",
                  [NSString stringWithFormat:@"%@ / %@ / %@", ActionNames(0), ActionNames(favorites - 1), ActionNames(favorites)]);
            first = [[[[gController clipList] rows] objectAtIndex:0] clipping];
            NSAccessibilityCustomAction *moveDown = nil;
            for (NSAccessibilityCustomAction *action in [EntryView(0) accessibilityCustomActions])
                if ([[action name] isEqualToString:@"Move Down"]) moveDown = action;
            BOOL moved = moveDown != nil && [moveDown handler] != nil && [moveDown handler]();
            Check(moved && [[op favorites] clippingAtPosition:1] == first && [gController isOpen] &&
                  [gController highlightedRow] == 1, @"Move Down moves the favorite one place down and keeps it highlighted", nil);
            CmdZ();
            Check([[op favorites] clippingAtPosition:0] == first, @"Cmd-Z undoes it", nil);
            [gController close];
        }

        Check(delegate->closed == delegate->opened, @"every opening is closed once (drag)", nil);

        // --- where the list opens: the geometry of -openBelowRect:onScreen: (screen points)
        {
            Open();
            [gController setHighlightedRow:6];
            FlycutClipping *trashed = [[[[gController clipList] rows] objectAtIndex:6] clipping];
            NSUInteger before = [[[gController clipList] rows] count];
            [[EntryView(6) trashButton] performClick:nil];
            Check([gController isOpen] && [[gController clipList] rowIndexOfClipping:trashed] < 0 &&
                  [[[gController clipList] rows] count] == before - 1, @"the trash button deletes its row and keeps the list open", nil);
            CmdZ();
            Check([[gController clipList] rowIndexOfClipping:trashed] == 6, @"and Cmd-Z brings the row back", nil);
            [gController close];
        }
        {
            NSSize size = NSMakeSize(384, 700);
            NSRect visible = NSMakeRect(0, 0, 1440, 875);       // 900 pt display, 25 pt menu bar
            NSPoint o = [FlycutListController panelOriginForSize:size belowRect:NSMakeRect(1000, 875, 28, 25) visibleFrame:visible];
            Check(o.x == 1000 && o.y == 875 - 4 - 700, @"the panel starts at the status item's left edge, 4 pt below the menu bar",
                  NSStringFromPoint(o));
            o = [FlycutListController panelOriginForSize:size belowRect:NSMakeRect(1300, 875, 28, 25) visibleFrame:visible];
            Check(o.x == 1440 - 384 - 8, @"near the right edge the panel keeps 8 pt from it", NSStringFromPoint(o));
            o = [FlycutListController panelOriginForSize:size belowRect:NSMakeRect(-50, 875, 28, 25) visibleFrame:visible];
            Check(o.x == 8, @"left of the visible frame it keeps 8 pt from the left edge", NSStringFromPoint(o));
            NSRect left = NSMakeRect(-1920, -200, 1920, 1055);  // a second display left of the main one
            o = [FlycutListController panelOriginForSize:size belowRect:NSMakeRect(-100, 855, 28, 25) visibleFrame:left];
            Check(o.x == -392 && o.y == 855 - 4 - 700, @"on a display left of the main one the same rules apply in its coordinates",
                  NSStringFromPoint(o));
            Check([FlycutListController panelTopBelowRect:NSMakeRect(700, 982, 28, 32) visibleFrame:NSMakeRect(0, 0, 1512, 950)] == 946,
                  @"the top edge never goes above the visible frame (a taller menu bar, the notch)", nil);
            Check([FlycutListController panelTopBelowRect:NSMakeRect(700, 930, 28, 20) visibleFrame:NSMakeRect(0, 0, 1512, 950)] == 926,
                  @"a status item lower than the visible top: 4 pt below the item", nil);
            CGFloat chrome = 5 + 34 + 11 + 166 + 5;
            CGFloat room = [FlycutListController maximumListHeightBelowRect:NSMakeRect(1000, 875, 28, 25)
                                                               visibleFrame:NSMakeRect(0, 70, 1440, 805) chromeHeight:chrome];
            Check(room == 871 - 70 - 8 - chrome, @"the list gets the room down to 8 pt above the Dock, without search field and commands",
                  [NSString stringWithFormat:@"%g", room]);
        }

        Check(![NSApp isActive], @"Flycut never became active", nil);
        Check(gActivations == 0, @"no activation call", [NSString stringWithFormat:@"%d", gActivations]);
        Check(gOrderFront == 0 && ![panel isVisible], @"the panel was never ordered on screen", [NSString stringWithFormat:@"%d", gOrderFront]);
        for (NSDictionary *step in gSteps)
            if ([step[@"app_active"] boolValue]) { Check(NO, @"app inactive in every step", step[@"key"]); break; }

        NSDictionary *out = @{@"steps": gSteps, @"checks": gChecks, @"failures": @(failures), @"activations": @(gActivations),
                              @"order_front_calls": @(gOrderFront), @"macos": [[NSProcessInfo processInfo] operatingSystemVersionString]};
        NSData *json = [NSJSONSerialization dataWithJSONObject:out options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:NULL];
        fwrite([json bytes], 1, [json length], stdout);
        fputc('\n', stdout);
    }
    return failures > 100 ? 100 : failures;
}
