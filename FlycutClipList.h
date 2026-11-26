//
//  FlycutClipList.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// The data behind the menu-bar list: one list with the favorites on top, then the
// history, filtered by the search text, plus the list's own changes (star, delete) and
// their undo. Undo lives in memory only and only while the list is open (one session).

#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import "FlycutOperator.h"

// One row: a clipping and the store that holds it.
@interface FlycutClipListRow : NSObject {
	FlycutList list;
	FlycutClipping *clipping;
}
@property (nonatomic, readonly) FlycutList list;
@property (nonatomic, readonly) FlycutClipping *clipping;
@end

@interface FlycutClipList : NSObject {
	FlycutOperator *flycutOperator;
	NSString *searchString;
	NSArray *rows;
	NSMutableArray *undoStack;
	BOOL inSession;
}

- (instancetype)initWithOperator:(FlycutOperator *)op;

// A session is one opening of the list. Ending it drops the undo steps and lets the
// operator delete image files that no list references any more.
- (void)beginSession;
- (void)endSession;

@property (nonatomic, copy) NSString *searchString;

// Rebuilds -rows from the stores.
- (void)reload;
- (NSArray *)rows;
// Row of exactly this clipping object in -rows, or -1.
- (NSInteger)rowIndexOfClipping:(FlycutClipping *)clipping;
// Which list holds this clipping object right now (-1 when neither).
- (NSInteger)listOfClipping:(FlycutClipping *)clipping;

// Star: a history clipping moves to the top of the favorites (with "Remove duplicates" to
// the place of an equal favorite), a favorite returns to the history (see
// -[FlycutOperator moveClippingToHistory:]). Undoable.
- (BOOL)toggleFavoriteOfClipping:(FlycutClipping *)clipping;
// Trash: removes the clipping from its own list. Undoable.
- (BOOL)deleteClipping:(FlycutClipping *)clipping;

// Dragging rows inside the list. The favorites block is the favorite rows at the top of
// -rows; a drop goes above a row of it or below its last row (row 0 up to
// -favoriteRowCount). There a favorite moves, and a history clipping becomes a favorite
// (as with the star, then moved). The history keeps its time order: it takes no drop, and
// a favorite dropped on it stays a favorite (only the star unstars).
- (NSInteger)favoriteRowCount;
- (BOOL)canDropClipping:(FlycutClipping *)clipping aboveRow:(NSInteger)row;
// Undoable. NO when refused or when nothing changes (a favorite dropped on its own place).
- (BOOL)dropClipping:(FlycutClipping *)clipping aboveRow:(NSInteger)row;

- (BOOL)canUndo;
// Reverts the latest change and returns the clipping it concerned (to highlight it), or
// nil when there is nothing to undo or the stores changed otherwise in the meantime.
- (FlycutClipping *)undo;

// Height of a list showing rows of the given heights: all of them if they fit into
// visibleRows rows of rowHeight (and maximum); otherwise the list ends in the middle of
// the row that crosses that height, so a half row shows there is more.
+ (CGFloat)listHeightForRowHeights:(NSArray *)rowHeights
						 rowHeight:(CGFloat)rowHeight
					   visibleRows:(NSInteger)visibleRows
						   maximum:(CGFloat)maximum;

@end
