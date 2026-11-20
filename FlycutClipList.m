//
//  FlycutClipList.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

#import "FlycutClipList.h"

@implementation FlycutClipListRow
@synthesize list, clipping;

+ (FlycutClipListRow *)rowWithList:(FlycutList)aList clipping:(FlycutClipping *)aClipping
{
	FlycutClipListRow *row = [[[FlycutClipListRow alloc] init] autorelease];
	row->list = aList;
	row->clipping = [aClipping retain];
	return row;
}

- (void)dealloc
{
	[clipping release];
	[super dealloc];
}
@end

// One undoable change: both lists before it, and as it left them. The undo applies only
// while the lists still look exactly as the change left them.
@interface FlycutClipListStep : NSObject {
@public
	NSArray *before;
	NSArray *after;
	FlycutClipping *clipping;
}
@end

@implementation FlycutClipListStep
- (void)dealloc
{
	[before release];
	[after release];
	[clipping release];
	[super dealloc];
}
@end

static BOOL FlycutSameClippingObjects(NSArray *a, NSArray *b)
{
	if ( [a count] != [b count] )
		return NO;
	for ( NSUInteger i = 0 ; i < [a count] ; i++ )
	{
		NSArray *listA = [a objectAtIndex:i], *listB = [b objectAtIndex:i];
		if ( [listA count] != [listB count] )
			return NO;
		for ( NSUInteger j = 0 ; j < [listA count] ; j++ )
			if ( [listA objectAtIndex:j] != [listB objectAtIndex:j] )
				return NO;
	}
	return YES;
}

@implementation FlycutClipList
@synthesize searchString;

- (instancetype)initWithOperator:(FlycutOperator *)op
{
	self = [super init];
	if ( self != nil )
	{
		flycutOperator = [op retain];
		rows = [[NSArray alloc] init];
		undoStack = [[NSMutableArray alloc] init];
	}
	return self;
}

- (void)dealloc
{
	if ( inSession )
		[self endSession];
	[flycutOperator release];
	[searchString release];
	[rows release];
	[undoStack release];
	[super dealloc];
}

- (void)beginSession
{
	[undoStack removeAllObjects];
	[flycutOperator beginDeferringImageDeletion];
	inSession = YES;
}

- (void)endSession
{
	// Undo steps exist only in memory and only while the list is open.
	[undoStack removeAllObjects];
	inSession = NO;
	[flycutOperator endDeferringImageDeletion];
}

// One list, no headers and no divider: the favorites first, then the history. A row
// shows its store by its star (FlycutListEntryView).
- (void)reload
{
	NSMutableArray *newRows = [NSMutableArray array];
	for ( FlycutClipping *clipping in [flycutOperator clippingsInList:FlycutListFavorites matching:searchString] )
		[newRows addObject:[FlycutClipListRow rowWithList:FlycutListFavorites clipping:clipping]];
	for ( FlycutClipping *clipping in [flycutOperator clippingsInList:FlycutListHistory matching:searchString] )
		[newRows addObject:[FlycutClipListRow rowWithList:FlycutListHistory clipping:clipping]];
	[rows release];
	rows = [newRows copy];
}

- (NSArray *)rows
{
	return rows;
}

- (NSInteger)rowIndexOfClipping:(FlycutClipping *)clipping
{
	if ( nil == clipping )
		return -1;
	for ( NSUInteger i = 0 ; i < [rows count] ; i++ )
		if ( [(FlycutClipListRow *)[rows objectAtIndex:i] clipping] == clipping )
			return (NSInteger)i;
	return -1;
}

- (NSInteger)listOfClipping:(FlycutClipping *)clipping
{
	if ( [flycutOperator indexOfClipping:clipping inList:FlycutListFavorites] >= 0 )
		return FlycutListFavorites;
	if ( [flycutOperator indexOfClipping:clipping inList:FlycutListHistory] >= 0 )
		return FlycutListHistory;
	return -1;
}

// Runs one change and records it for undo.
- (BOOL)recordChange:(BOOL (^)(void))change concerning:(FlycutClipping *)clipping
{
	NSArray *before = [flycutOperator listsSnapshot];
	[clipping retain];
	BOOL changed = change();
	if ( changed )
	{
		FlycutClipListStep *step = [[FlycutClipListStep alloc] init];
		step->before = [before retain];
		step->after = [[flycutOperator listsSnapshot] retain];
		step->clipping = [clipping retain];
		[undoStack addObject:step];
		[step release];
		[self reload];
	}
	[clipping release];
	return changed;
}

- (BOOL)toggleFavoriteOfClipping:(FlycutClipping *)clipping
{
	NSInteger list = [self listOfClipping:clipping];
	if ( list < 0 )
		return NO;
	FlycutOperator *op = flycutOperator;
	return [self recordChange:^BOOL{
		return ( list == FlycutListFavorites ) ? [op moveClippingToHistory:clipping] : [op moveClippingToFavorites:clipping];
	} concerning:clipping];
}

- (BOOL)deleteClipping:(FlycutClipping *)clipping
{
	NSInteger list = [self listOfClipping:clipping];
	if ( list < 0 )
		return NO;
	FlycutOperator *op = flycutOperator;
	return [self recordChange:^BOOL{
		return [op deleteClipping:clipping fromList:(FlycutList)list];
	} concerning:clipping];
}

- (NSInteger)favoriteRowCount
{
	NSInteger count = 0;
	for ( FlycutClipListRow *row in rows )
	{
		if ( [row list] != FlycutListFavorites )
			break;
		count++;
	}
	return count;
}

- (BOOL)canDropClipping:(FlycutClipping *)clipping aboveRow:(NSInteger)row
{
	return [self rowIndexOfClipping:clipping] >= 0 && [self listOfClipping:clipping] >= 0 &&
		row >= 0 && row <= [self favoriteRowCount];
}

// All favorites (also those a search hides) from the drop position on: the dropped clipping
// goes directly above the first of them that is still a favorite after the change. So an
// equal favorite that "Remove duplicates" drops, or the last one that full favorites drop,
// does not shift the place the user chose.
- (NSArray *)favoritesFromDropRow:(NSInteger)row
{
	NSArray *favorites = [flycutOperator clippingsInList:FlycutListFavorites matching:nil];
	NSInteger shown = [self favoriteRowCount];
	NSUInteger start = 0;
	if ( row < shown )
		start = [favorites indexOfObjectIdenticalTo:[(FlycutClipListRow *)[rows objectAtIndex:row] clipping]];
	else if ( shown > 0 )
	{
		start = [favorites indexOfObjectIdenticalTo:[(FlycutClipListRow *)[rows objectAtIndex:shown - 1] clipping]];
		if ( start != NSNotFound )
			start++;
	}
	if ( start == NSNotFound || start > [favorites count] )
		start = [favorites count];
	return [favorites subarrayWithRange:NSMakeRange(start, [favorites count] - start)];
}

- (BOOL)dropClipping:(FlycutClipping *)clipping aboveRow:(NSInteger)row
{
	if ( ![self canDropClipping:clipping aboveRow:row] )
		return NO;
	NSArray *below = [self favoritesFromDropRow:row];
	NSInteger list = [self listOfClipping:clipping];
	FlycutOperator *op = flycutOperator;
	return [self recordChange:^BOOL{
		// A history clipping first becomes a favorite exactly as with the star.
		if ( list == FlycutListHistory && ![op moveClippingToFavorites:clipping] )
			return NO;
		NSMutableArray *others = [[[op clippingsInList:FlycutListFavorites matching:nil] mutableCopy] autorelease];
		[others removeObjectIdenticalTo:clipping];
		NSUInteger index = [others count];
		for ( FlycutClipping *favorite in below )
		{
			NSUInteger at = [others indexOfObjectIdenticalTo:favorite];
			if ( at != NSNotFound )
			{
				index = at;
				break;
			}
		}
		BOOL moved = [op moveFavorite:clipping toIndex:(int)index];
		return moved || list == FlycutListHistory;
	} concerning:clipping];
}

- (BOOL)canUndo
{
	return [undoStack count] > 0;
}

- (FlycutClipping *)undo
{
	FlycutClipListStep *step = [[[undoStack lastObject] retain] autorelease];
	if ( nil == step )
		return nil;
	if ( !FlycutSameClippingObjects([flycutOperator listsSnapshot], step->after) )
	{
		// Something else changed the lists since (a capture that was already being read
		// when the list opened). Restoring the old state would remove that clipping.
		[undoStack removeAllObjects];
		[self reload];
		return nil;
	}
	[undoStack removeLastObject];
	[flycutOperator restoreListsSnapshot:step->before];
	[self reload];
	return [[step->clipping retain] autorelease];
}

+ (CGFloat)listHeightForRowHeights:(NSArray *)rowHeights
						 rowHeight:(CGFloat)rowHeight
					   visibleRows:(NSInteger)visibleRows
						   maximum:(CGFloat)maximum
{
	CGFloat content = 0;
	for ( NSNumber *height in rowHeights )
		content += [height doubleValue];
	CGFloat target = MAX((CGFloat)1, (CGFloat)visibleRows) * rowHeight;
	if ( maximum > 0 && target > maximum )
		target = maximum;
	if ( content <= target )
		return content;
	CGFloat y = 0;
	for ( NSNumber *number in rowHeights )
	{
		CGFloat height = [number doubleValue];
		if ( y + height >= target )
			return y + floor(height / 2);
		y += height;
	}
	return content;
}

@end
