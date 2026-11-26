//
//  FlycutOperator.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// FlycutOperator owns and interacts with the FlycutStores, providing
// manipulation of the stores.

#ifndef FlycutOperator_h
#define FlycutOperator_h

#import "FlycutStore.h"

// The two lists the menu-bar list shows. They are addressed explicitly, never through
// the bezel's current store, which the bezel's favorites toggle swaps.
typedef NS_ENUM(NSInteger, FlycutList) {
	FlycutListHistory = 0,
	FlycutListFavorites = 1,
};

@protocol FlycutOperatorDelegate <NSObject>
@optional
- (NSString*)alertWithMessageText:(NSString*)message informationText:(NSString*)information buttonsTexts:(NSArray*)buttons;
@end

@interface FlycutOperator : NSObject <FlycutStoreDeleteDelegate> {
    int							stackPosition;
    int							favoritesStackPosition;
    int							stashedStackPosition;

    FlycutStore				*clippingStore;
    FlycutStore				*favoritesStore;
    FlycutStore				*stashedStore;

	SEL saveSelector;
	NSObject* saveTarget;
	int displayNum;
	int displayLength;

    BOOL disableStore;
	BOOL inhibitAutosaveClippings;
	// The latest copies from the clipboard in the history, with their generations
	// (-addClipping:...fromClipboardGeneration:).
	NSMutableArray *recentClipboardRows;

	//Preferences
	BOOL issuedRememberResizeWarning;
}

// Basic functionality
-(int)indexOfClipping:(NSString*)contents ofType:(NSString*)type fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL;
-(bool)addClipping:(NSString*)contents ofType:(NSString*)type fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL target:(id)selectorTarget clippingAddedSelector:(SEL)clippingAddedSelectorclippingAddedSelector;
-(bool)addImageClipping:(NSData *)imageData fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL imageType:(NSString *)imageType target:(id)selectorTarget clippingAddedSelector:(SEL)clippingAddedSelector;
// A copy from the clipboard, with the clipboard generation it was copied in. It goes in below
// every history row of a copy of a newer generation, never above (a copy whose row went in
// after newer copies: a catch-up read that took longer than opening the bezel, the list or the
// search window waited for it, and whose commit came after them), and not at all when one of
// those newer rows holds the same text or image, or, with "Remove duplicates", a row above its
// place does. Otherwise as the variants without a generation.
-(bool)addClipping:(NSString*)contents ofType:(NSString*)type withRichData:(NSDictionary *)richData fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL target:(id)selectorTarget clippingAddedSelector:(SEL)clippingAddedSelector fromClipboardGeneration:(NSInteger)generation;
-(bool)addImageClipping:(NSData *)imageData fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL imageType:(NSString *)imageType target:(id)selectorTarget clippingAddedSelector:(SEL)clippingAddedSelector fromClipboardGeneration:(NSInteger)generation;
-(FlycutClipping *)clippingAtIndex:(int)index;
-(BOOL)shouldSkip:(NSString *)contents ofType:(NSString *)type fromAvailableTypes:(NSArray<NSString *> *)availableTypes;
// Sharing with another account of this Mac: NO for a clipping that must not
// leave this account. Applies -shouldSkip:'s password filters as if all were
// turned on (the factory lengths included) and refuses every type of
// +neverSharedTypes and a copy without a type list, whatever the local settings.
-(BOOL)mayShareClipping:(NSString *)contents ofType:(NSString *)type fromAvailableTypes:(NSArray<NSString *> *)availableTypes;
// Pasteboard types that never leave this account: the factory password and
// concealed type lists plus the other markers listed on nspasteboard.org.
+(NSArray<NSString *> *)neverSharedTypes;
-(bool)addClipping:(NSString*)contents ofType:(NSString*)type withRichData:(NSDictionary *)richData fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL target:(id)selectorTarget clippingAddedSelector:(SEL)clippingAddedSelector;
-(int)stackPosition;
-(NSString*)getPasteFromStackPosition;
-(NSString*)getPasteFromIndex:(int) position;
-(NSDictionary*)getRichDataFromStackPosition;
-(NSDictionary*)getRichDataFromIndex:(int) position;
-(bool) saveFromStack;
-(bool)clearItemAtStackPosition;
-(void)clearList;
-(void)mergeList;

// Stack position manipulation functionality
-(bool)setStackPositionToOneMoreRecent;
-(bool)setStackPositionToOneLessRecent;
-(bool)setStackPositionToFirstItem;
-(bool)setStackPositionToLastItem;
-(bool)setStackPositionToTenMoreRecent;
-(bool)setStackPositionToTenLessRecent;
-(bool)setStackPositionTo:(int) newStackPosition;
-(void)adjustStackPositionIfOutOfBounds;
-(bool)stackPositionIsInBounds;

// Stack related
-(BOOL) isValidClippingNumber:(NSNumber *)number;
-(NSString *) clippingStringWithCount:(int)count;

// Read-only access to a stored clipping, for callers that need to hold on to a
// specific clipping across store changes.  Returns nil for an out-of-range position.
-(FlycutClipping *) clippingAtPosition:(int)position;

// Save and load
-(void) saveEngine;
-(bool) loadEngineFromPList;

// Preference related
-(void) willShowPreferences;
-(int) setRememberNum:(int)newRemember forPrimaryStore:(BOOL) isPrimaryStore;

// Initialization / cleanup related
-(void)applicationWillTerminate;;
-(void)awakeFromNibDisplaying:(int) displayNum withDisplayLength:(int) displayLength withSaveSelector:(SEL) selector forTarget:(NSObject*) target;
// Once per install, at launch before any copy is filtered: where master
// kept concealed copies, skipConcealedTypes becomes NO (see the .m).
+(void)carryOverConcealedTypesSetting;

// Favorites Store related
-(bool)favoritesStoreIsSelected;
-(void)switchToFavoritesStore;
-(bool)restoreStashedStore;
-(void)toggleToFromFavoritesStore;
-(bool)saveFromStackToFavorites;

// Clippings Store related
-(int)jcListCount;
-(int)rememberNum;
-(FlycutClipping*)clippingAtStackPosition;
-(NSArray *) previousDisplayStrings:(int)howMany containing:(NSString*)search;
-(NSArray *) previousIndexes:(int)howMany containing:(NSString*)search; // This method is in newest-first order.
-(void)setDisableStoreTo:(bool) value;
-(bool)storeDisabled;
-(void)setClippingsStoreDelegate:(id<FlycutStoreDelegate>) delegate;
-(void)setFavoritesStoreDelegate:(id<FlycutStoreDelegate>) delegate;

// Menu-bar list: both stores, addressed explicitly (see FlycutList).
// The clippings of a list, newest first; with a search string only those that match
// (same matching as the search box). A snapshot, not a live view.
-(NSArray *)clippingsInList:(FlycutList)list matching:(NSString *)search;
// Position of exactly this clipping object in the list, or -1.
-(int)indexOfClipping:(FlycutClipping *)clipping inList:(FlycutList)list;
// Removes the clipping from the list on the user's request; it is never exported.
-(bool)deleteClipping:(FlycutClipping *)clipping fromList:(FlycutList)list;
// History -> top of the favorites, like the bezel's Shift-F (with "Remove duplicates" a
// clipping equal to a favorite takes that favorite's place instead).
-(bool)moveClippingToFavorites:(FlycutClipping *)clipping;
// Favorites -> back into the history at its time position.
-(bool)moveClippingToHistory:(FlycutClipping *)clipping;
// A favorite moves to index, counted in the favorites without it (dragged in the list).
// Nothing is added, dropped or exported. NO when it is not a favorite or already there.
-(bool)moveFavorite:(FlycutClipping *)clipping toIndex:(int)index;
// Where -moveClippingToHistory: puts the clipping (see there).
-(int)historyIndexForReturningClipping:(FlycutClipping *)clipping;
// Undo support: the clipping objects of both lists, and putting such a state back.
-(NSArray *)listsSnapshot;
-(void)restoreListsSnapshot:(NSArray *)snapshot;
// While deferring, image files of removed clippings are kept; ending deletes those that
// no list references any more.
-(void)beginDeferringImageDeletion;
-(void)endDeferringImageDeletion;

/** optional delegate (not retained) */
@property (nonatomic, nullable, assign) id<FlycutOperatorDelegate> delegate;

@end

#endif /* FlycutOperator_h */
