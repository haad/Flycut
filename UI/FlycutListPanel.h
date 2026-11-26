//
//  FlycutListPanel.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// The list the menu-bar item opens: a search field, one scrolling list with the favorites
// on top and then the whole history, and the menu's commands below. It looks like a menu
// but is a non-activating panel: views inside an NSMenu get no keyboard events, and
// Flycut must not become active, or pasting would no longer go to the application the
// user works in. The bezel (BezelWindow) uses the same kind of window.

#import <Cocoa/Cocoa.h>
#import "FlycutClipList.h"

@class FlycutListController;

@protocol FlycutListControllerDelegate <NSObject>
// Title of a clipping row (the app applies its menu title rules).
- (NSString *)listController:(FlycutListController *)controller titleForClipping:(FlycutClipping *)clipping;
// The user chose a clipping. The list is closed already.
- (void)listController:(FlycutListController *)controller didChooseClipping:(FlycutClipping *)clipping inList:(FlycutList)list;
// The user chose one of the command rows. The list is closed already.
- (void)listController:(FlycutListController *)controller didChooseCommand:(NSMenuItem *)item;
- (void)listControllerDidOpen:(FlycutListController *)controller;
- (void)listControllerDidClose:(FlycutListController *)controller;
@optional
// The status item's frame in screen coordinates, up to the top edge of its screen. A press
// there is the status item's own (the second click), which the list's global mouse-down
// monitor leaves to the status item.
- (NSRect)statusItemFrameForListController:(FlycutListController *)controller;
@end

@interface FlycutListPanel : NSPanel
@end

// One clipping row: at the left the star (in a native menu's state column), the optional
// image icon and the title, at the right edge the trash. A favorite always shows its
// filled star; the highlighted row also shows the trash and, for a history clipping, the
// star's outline.
@interface FlycutListEntryView : NSTableCellView
@property (nonatomic, readonly) NSButton *starButton;
@property (nonatomic, readonly) NSButton *trashButton;
@property (nonatomic, readonly) NSTextField *titleField;
@end

@interface FlycutListController : NSObject <NSTableViewDataSource, NSTableViewDelegate, NSSearchFieldDelegate, NSWindowDelegate>

- (instancetype)initWithOperator:(FlycutOperator *)op delegate:(id<FlycutListControllerDelegate>)delegate;

// List height in rows ("Display in menu").
@property (nonatomic, assign) NSInteger visibleRows;
// The commands shown below the list (NSMenuItems, separators allowed).
@property (nonatomic, copy) NSArray *commandItems;

- (BOOL)isOpen;
// A press on the status item, stamped pressTime (seconds since startup, as -[NSEvent
// timestamp]; now for a press without an event). Returns YES if the press closes the
// list: it is open (closed now), or it closed within a moment of the press for a reason
// the press may have caused itself (key focus lost, another application active, a press
// the global monitor saw in the menu bar) and no other press answered that close. The
// caller opens the list on NO. Each close answers one press at most.
- (BOOL)closeForStatusItemPressAt:(NSTimeInterval)pressTime;
// Shows the list below anchorRect (screen coordinates of the status item) without
// activating Flycut, and makes it key so typing goes to its search field.
- (void)openBelowRect:(NSRect)anchorRect onScreen:(NSScreen *)screen;
// The same list, laid out but never ordered on screen (tests and offscreen renders).
- (void)openOffscreenWithMaximumListHeight:(CGFloat)maximumListHeight;
// Called with the status item's mouse-down right after the list opened for it: follows the
// pressed button like a menu, so a press, drag and release on a row chooses that row. A
// release elsewhere (a plain click) leaves the list open. Returns when the button is up.
- (void)trackMouseFromEvent:(NSEvent *)mouseDown;
// The geometry of -openBelowRect:onScreen:, in screen coordinates. The panel's top edge
// is 4 pt below the status item and never above the visible frame (menu bar, notch); the
// list gets the room down to 8 pt above the visible frame's bottom (Dock) minus the search
// field and commands (chrome); the panel starts at the status item's left edge and keeps
// 8 pt from both sides of the visible frame.
+ (CGFloat)panelTopBelowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible;
+ (CGFloat)maximumListHeightBelowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible chromeHeight:(CGFloat)chrome;
+ (NSPoint)panelOriginForSize:(NSSize)size belowRect:(NSRect)anchorRect visibleFrame:(NSRect)visible;
- (void)close;
// The stores changed while the list is open, not through the list (a capture that was in
// flight when it opened): rebuild the rows, keeping the highlighted entry (the same
// clipping) and the scroll position. Does nothing while the list is closed.
- (void)storesDidChange;

- (FlycutListPanel *)panel;
- (FlycutClipList *)clipList;
- (NSSearchField *)searchField;
- (NSTableView *)tableView;
// Row index into -[FlycutClipList rows], -1 for none.
- (NSInteger)highlightedRow;
- (void)setHighlightedRow:(NSInteger)row;
// The command row the arrows or the pointer highlight (nil for none); Return runs it.
// At most one row of the whole list, entry or command, is highlighted.
- (NSMenuItem *)highlightedCommand;

@end
