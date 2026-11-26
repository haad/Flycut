// Native fixture for MenuListModelTests.py: the data behind the menu-bar list.
//
// Compiles the real FlycutClipping, FlycutStore, FlycutOperator and FlycutClipList
// method bodies into this translation unit. Only OS boundaries are replaced:
// NSUserDefaults (an in-memory dictionary, never a real defaults domain),
// FlycutImageStore (records deletions in memory; no file is touched) and the
// file-writing autosave export (recorded instead of written). No pasteboard, app,
// window or input API is used. All clipping texts are dummy data.

#import <Cocoa/Cocoa.h>
#import <objc/message.h>
#include <stdio.h>
#include <string.h>

@interface FCFakeDefaults : NSObject {
    NSMutableDictionary *values;
}
+ (FCFakeDefaults *)standardUserDefaults;
- (void)registerDefaults:(NSDictionary *)registration;
- (id)objectForKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
- (NSDictionary *)dictionaryForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSURL *)URLForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (NSArray *)allKeys;
- (BOOL)synchronize;
@end

@implementation FCFakeDefaults
+ (FCFakeDefaults *)standardUserDefaults {
    static FCFakeDefaults *shared = nil;
    if (shared == nil) {
        shared = [[FCFakeDefaults alloc] init];
        shared->values = [[NSMutableDictionary alloc] init];
    }
    return shared;
}
- (void)registerDefaults:(NSDictionary *)registration {
    for (id key in registration)
        if ([values objectForKey:key] == nil)
            [values setObject:[registration objectForKey:key] forKey:key];
}
- (id)objectForKey:(NSString *)key { return [values objectForKey:key]; }
- (id)valueForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSString *)stringForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [[values objectForKey:key] integerValue]; }
- (BOOL)boolForKey:(NSString *)key { return [[values objectForKey:key] boolValue]; }
- (NSURL *)URLForKey:(NSString *)key { return nil; }
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) [values setObject:value forKey:key]; else [values removeObjectForKey:key];
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (NSArray *)allKeys { return [values allKeys]; }
- (BOOL)synchronize { return YES; }
@end

static NSArray *FCFakeSearchPath(NSSearchPathDirectory directory, NSSearchPathDomainMask mask, BOOL expand) {
    return @[NSTemporaryDirectory()];
}

#define NSUserDefaults FCFakeDefaults
#define NSSearchPathForDirectoriesInDomains FCFakeSearchPath
#define DLog(...) do {} while (0)

#include "FlycutEngine/FlycutClipping.m"
#include "FlycutEngine/FlycutStore.m"
#include "FlycutOperator.m"
#include "FlycutClipList.m"

static NSMutableArray *gDeletedImages;   // hashes passed to -deleteImageForHash:
static NSMutableArray *gExports;         // "favorites:<text>" / "history:<text>"

@implementation FlycutImageStore
+ (FlycutImageStore *)sharedStore {
    static FlycutImageStore *shared = nil;
    if (shared == nil) shared = [FlycutImageStore alloc];   // never -init: no directory
    return shared;
}
+ (NSString *)fileExtensionForType:(NSString *)uti { return @"png"; }
- (void)deleteImageForHash:(NSString *)hash { [gDeletedImages addObject:hash]; }
- (void)persistMemoryOnlyImageForHash:(NSString *)hash {}
- (NSData *)imageDataForHash:(NSString *)hash { return [NSData data]; }
- (BOOL)hasImageForHash:(NSString *)hash { return YES; }
@end

@interface FCListOperator : FlycutOperator {
@public
    int actions;
}
- (FlycutStore *)history;
- (FlycutStore *)favorites;
@end

@implementation FCListOperator
- (FlycutStore *)history { return stashedStore ? stashedStore : clippingStore; }
- (FlycutStore *)favorites { return favoritesStore; }
- (void)actionAfterListModification { actions++; [super actionAfterListModification]; }
- (bool)saveFromStore:(FlycutStore *)store atIndex:(int)index withPrefix:(NSString *)prefix {
    [gExports addObject:[NSString stringWithFormat:@"%@:%@", store == favoritesStore ? @"favorites" : @"history",
                         [[store clippingAtPosition:index] contents]]];
    return YES;
}
@end

static FlycutClipping *Clip(NSString *text, NSInteger timestamp) {
    return [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString withDisplayLength:40
                                withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:timestamp] autorelease];
}

static FlycutClipping *ImageClip(NSString *hash, NSInteger timestamp) {
    return [[[FlycutClipping alloc] initWithImageHash:hash withImageSize:NSMakeSize(10, 10) withImageType:NSPasteboardTypePNG
                                    withDisplayLength:40 withAppLocalizedName:@"Preview" withAppBundleURL:nil
                                        withTimestamp:timestamp] autorelease];
}

// Fills a store so that it lists the clippings in the given order (newest first).
static void Fill(FlycutStore *store, NSArray *clippings) {
    for (FlycutClipping *c in [clippings reverseObjectEnumerator])
        [store addClipping:c];
}

static FCListOperator *FreshOperator(void) {
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    for (NSString *key in [defaults allKeys]) [defaults setObject:nil forKey:key];
    [defaults setObject:@0 forKey:@"savePreference"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@NO forKey:@"removeDuplicates"];
    [gDeletedImages removeAllObjects];
    [gExports removeAllObjects];
    FCListOperator *op = [[FCListOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:NULL forTarget:nil];
    return [op autorelease];
}

static NSString *Contents(FlycutStore *store) {
    NSMutableArray *parts = [NSMutableArray array];
    for (int i = 0; i < [store jcListCount]; i++) {
        FlycutClipping *c = [store clippingAtPosition:i];
        [parts addObject:[c isImageClipping] ? [c imageHash] : [c contents]];
    }
    return [parts componentsJoinedByString:@","];
}

// One part per row: the clipping's text, "*" in front for a favorite. A row without a
// clipping (a header or divider) would show as "(no clipping)".
static NSString *RowsText(FlycutClipList *list) {
    NSMutableArray *parts = [NSMutableArray array];
    for (FlycutClipListRow *row in [list rows]) {
        FlycutClipping *clipping = [row clipping];
        NSString *text = clipping == nil ? @"(no clipping)" : [clipping isImageClipping] ? [clipping displayString] : [clipping contents];
        [parts addObject:[row list] == FlycutListFavorites ? [@"*" stringByAppendingString:text] : text];
    }
    return [parts componentsJoinedByString:@"|"];
}

static int failures;
static void Check(BOOL condition, NSString *message, NSString *detail) {
    if (condition) { printf("PASS: %s\n", [message UTF8String]); return; }
    failures++;
    fprintf(stderr, "FAIL: %s%s%s\n", [message UTF8String], detail ? " -- " : "", detail ? [detail UTF8String] : "");
}
#define CHECK_EQ(actual, expected, message) do { NSString *a_ = (actual), *e_ = (expected); \
    Check([a_ isEqualToString:e_], message, [NSString stringWithFormat:@"got '%@', expected '%@'", a_, e_]); } while (0)

static BOOL SameObjects(NSArray *a, NSArray *b) {
    if ([a count] != [b count]) return NO;
    for (NSUInteger i = 0; i < [a count]; i++) if ([a objectAtIndex:i] != [b objectAtIndex:i]) return NO;
    return YES;
}

static FlycutClipList *ListFor(FlycutOperator *op) {
    FlycutClipList *list = [[[FlycutClipList alloc] initWithOperator:op] autorelease];
    [list beginSession];
    [list reload];
    return list;
}

#pragma mark - cases

static void RowsOrder(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0), Clip(@"h3", 0)]);
    FlycutClipList *list = ListFor(op);
    CHECK_EQ(RowsText(list), @"*F1|*F2|h1|h2|h3", @"favorites on top, then the whole history: one list, no headers, no divider");
    [op switchToFavoritesStore];   // the bezel's favorites toggle swaps the current store
    [list reload];
    CHECK_EQ(RowsText(list), @"*F1|*F2|h1|h2|h3", @"the list ignores which store the bezel shows");
    [op restoreStashedStore];
    FlycutClipping *h2 = [[op history] clippingAtPosition:1];
    Check([list rowIndexOfClipping:h2] == 3, @"row index follows the clipping object", nil);
    Check([list listOfClipping:h2] == FlycutListHistory, @"a history clipping is in the history list", nil);
    Check([list listOfClipping:[[op favorites] clippingAtPosition:0]] == FlycutListFavorites, @"a favorite is in the favorites list", nil);
    [list endSession];
}

static void RowsEmptyLists(void) {
    FCListOperator *op = FreshOperator();
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    FlycutClipList *list = ListFor(op);
    CHECK_EQ(RowsText(list), @"h1|h2", @"no favorites: the history alone");
    FCListOperator *op2 = FreshOperator();
    Fill([op2 favorites], @[Clip(@"F1", 0)]);
    FlycutClipList *list2 = ListFor(op2);
    CHECK_EQ(RowsText(list2), @"*F1", @"no history: the favorites alone");
    FlycutClipList *list3 = ListFor(FreshOperator());
    CHECK_EQ(RowsText(list3), @"", @"both lists empty: no rows");
    [list endSession]; [list2 endSession]; [list3 endSession];
}

static void Search(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"beta fav", 0), Clip(@"gamma", 0)]);
    Fill([op history], @[Clip(@"alpha", 0), Clip(@"Beta hist", 0), ImageClip(@"abc", 0), Clip(@"delta", 0)]);
    FlycutClipList *list = ListFor(op);
    [list setSearchString:@"beta"];
    [list reload];
    CHECK_EQ(RowsText(list), @"*beta fav|Beta hist", @"search filters both lists, favorite matches on top, case-insensitive");
    [list setSearchString:@"preview"];
    [list reload];
    CHECK_EQ(RowsText(list), @"[Image 10x10]", @"an image matches by its source app, as in today's search");
    [list setSearchString:@"ta"];
    [list reload];
    CHECK_EQ(RowsText(list), @"*beta fav|Beta hist|delta", @"matches keep their list order");
    [list setSearchString:@"zzz"];
    [list reload];
    CHECK_EQ(RowsText(list), @"", @"no match: no rows");
    [list setSearchString:@""];
    [list reload];
    CHECK_EQ(RowsText(list), @"*beta fav|*gamma|alpha|Beta hist|[Image 10x10]|delta", @"empty search shows everything");
    [list endSession];
}

static void StarToTop(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenClippings"];
    Fill([op favorites], @[Clip(@"F1", 0)]);
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0), Clip(@"h3", 0)]);
    FlycutClipList *list = ListFor(op);
    FlycutClipping *h2 = [[op history] clippingAtPosition:1];
    Check([list toggleFavoriteOfClipping:h2], @"star on a history row succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"h2,F1", @"starred clipping is on top of the favorites");
    CHECK_EQ(Contents([op history]), @"h1,h3", @"and no longer in the history");
    Check([[op favorites] clippingAtPosition:0] == h2, @"the same clipping object moved", nil);
    Check([gExports count] == 0, @"moving to the favorites exports nothing", [gExports description]);
    CHECK_EQ(RowsText(list), @"*h2|*F1|h1|h3", @"rows are rebuilt after the change");
    [list endSession];
}

// "Remove duplicates" on: a starred clipping equal to a favorite takes that favorite's
// place instead of the top, as Shift-F does, so the favorites keep their order.
static void StarRemoveDuplicatesTakesEqualPlace(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"X", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"X", 20), Clip(@"h2", 10)]);
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    FlycutClipping *x = [[op history] clippingAtPosition:1];
    Check([list toggleFavoriteOfClipping:x], @"star on a history clipping equal to a favorite succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,X,F2", @"it takes the equal favorite's place; the favorites keep their order");
    Check([[op favorites] clippingAtPosition:1] == x, @"the starred clipping is the one listed", nil);
    CHECK_EQ(Contents([op history]), @"h1,h2", @"and it left the history");
    Check([list rowIndexOfClipping:x] == 1, @"its row can stay highlighted", nil);
    Check([list undo] == x && SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"undo restores both lists", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [list endSession];
}

static void StarFullFavorites(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenFavorites"];
    [[op favorites] setRememberNum:2];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    Check([list toggleFavoriteOfClipping:[[op history] clippingAtPosition:0]], @"star with full favorites succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"h1,F1", @"full favorites drop their oldest entry, as with Shift-F");
    CHECK_EQ([gExports componentsJoinedByString:@","], @"favorites:F2", @"the dropped favorite is exported as today (saveForgottenFavorites)");
    Check([list undo] != nil, @"undo after star", nil);
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"undo restores both lists including the dropped favorite", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [list endSession];
}

static void UnstarTimePosition(void) {
    FCListOperator *op = FreshOperator();
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"h50", 50), Clip(@"h40", 40), Clip(@"h20", 20), Clip(@"h10", 10)]);
    Check([op historyIndexForReturningClipping:x] == 2, @"time position: below every newer history entry",
          [NSString stringWithFormat:@"%d", [op historyIndexForReturningClipping:x]]);
    FlycutClipList *list = ListFor(op);
    Check([list toggleFavoriteOfClipping:x], @"star off succeeds", nil);
    CHECK_EQ(Contents([op history]), @"h50,h40,X,h20,h10", @"the favorite returns to its old time position");
    CHECK_EQ(Contents([op favorites]), @"", @"and leaves the favorites");
    Check([gExports count] == 0, @"star off exports nothing", nil);
    [list endSession];
}

static void UnstarUnsorted(void) {
    FCListOperator *op = FreshOperator();
    FlycutClipping *x = Clip(@"X", 7);
    Fill([op favorites], @[x]);
    // b5 was pasted to the top (pasteMovesToTop), so the history is not in time order.
    Fill([op history], @[Clip(@"b5", 5), Clip(@"a10", 10), Clip(@"c3", 3)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"b5,a10,X,c3", @"unsorted history: below the last entry captured later");
    [list endSession];
}

static void UnstarUnknownTime(void) {
    FCListOperator *op = FreshOperator();
    FlycutClipping *x = Clip(@"X", 0);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"a10", 10), Clip(@"b5", 5)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"X,a10,b5", @"no timestamp: back to the top of the history");
    [list endSession];
}

static void UnstarFullHistoryOldest(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenClippings"];
    [[op history] setRememberNum:3];
    FlycutClipping *x = Clip(@"X", 5);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"a30", 30), Clip(@"b20", 20), Clip(@"c10", 10)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    Check([list toggleFavoriteOfClipping:x], @"star off into a full history succeeds", nil);
    CHECK_EQ(Contents([op history]), @"a30,b20,X", @"full history: the returning entry keeps the last slot, never falls out itself");
    CHECK_EQ([gExports componentsJoinedByString:@","], @"history:c10", @"the history's last entry falls out as with a new copy (saveForgottenClippings)");
    Check([list undo] == x, @"undo returns the unstarred clipping", nil);
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"undo restores the dropped history entry and the favorite", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [list endSession];
}

static void UnstarFullHistoryMiddle(void) {
    FCListOperator *op = FreshOperator();
    [[op history] setRememberNum:3];
    FlycutClipping *x = Clip(@"X", 25);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"a30", 30), Clip(@"b20", 20), Clip(@"c10", 10)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"a30,X,b20", @"full history: time position kept, the oldest entry falls out");
    [list endSession];
}

// "Remove duplicates" on: -[FlycutStore insertClipping:atIndex:] first removes every history
// entry equal to the returning favorite, so the time position must be counted without them.
static void UnstarRemoveDuplicatesEqualAtTimePosition(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"A", 50), Clip(@"X", 30), Clip(@"B", 10)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    Check([list toggleFavoriteOfClipping:x], @"star off with an equal history entry succeeds", nil);
    CHECK_EQ(Contents([op history]), @"A,X,B", @"removeDuplicates: the favorite replaces its equal entry at its time position");
    Check([[op history] clippingAtPosition:1] == x, @"the returning favorite itself is listed, once", nil);
    CHECK_EQ(Contents([op favorites]), @"", @"and leaves the favorites");
    Check([list undo] == x, @"undo returns the unstarred clipping", nil);
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"undo restores the equal history entry and the favorite", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [list endSession];
}

static void UnstarRemoveDuplicatesEqualNewer(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    // The same text was copied again later: its newer entry is above the time position.
    Fill([op history], @[Clip(@"X", 60), Clip(@"A", 50), Clip(@"B", 10)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"A,X,B", @"removeDuplicates: an equal entry above is not counted, X goes below A");
    Check([[op history] clippingAtPosition:1] == x, @"the returning favorite is at its time position", nil);
    [list endSession];
}

static void UnstarRemoveDuplicatesEqualOlder(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"A", 50), Clip(@"B", 10), Clip(@"X", 5)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"A,X,B", @"removeDuplicates: an equal entry below drops out, X keeps its time position");
    [list endSession];
}

static void UnstarRemoveDuplicatesFullHistory(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenClippings"];
    [[op history] setRememberNum:3];
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"A", 50), Clip(@"X", 40), Clip(@"B", 10)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"A,X,B", @"removeDuplicates, full history: the equal entry makes room, nothing falls out");
    Check([gExports count] == 0, @"no history entry was pushed out and exported", [gExports description]);
    [list endSession];
}

static void UnstarKeepsDuplicatesWhenOff(void) {
    FCListOperator *op = FreshOperator();   // removeDuplicates NO
    FlycutClipping *x = Clip(@"X", 30);
    Fill([op favorites], @[x]);
    Fill([op history], @[Clip(@"A", 50), Clip(@"X", 30), Clip(@"B", 10)]);
    FlycutClipList *list = ListFor(op);
    [list toggleFavoriteOfClipping:x];
    CHECK_EQ(Contents([op history]), @"A,X,X,B", @"without removeDuplicates both equal entries stay, as with a new copy");
    Check([[op history] clippingAtPosition:2] == x, @"the returning favorite goes below the entry of the same time", nil);
    [list endSession];
}

static void DeleteNotExported(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenClippings"];
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenFavorites"];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    FlycutClipList *list = ListFor(op);
    Check([list deleteClipping:[[op history] clippingAtPosition:1]], @"trash on a history row succeeds", nil);
    Check([list deleteClipping:[[op favorites] clippingAtPosition:0]], @"trash on a favorite succeeds", nil);
    CHECK_EQ(Contents([op history]), @"h1", @"deleted from the history only");
    CHECK_EQ(Contents([op favorites]), @"F2", @"deleted from the favorites only");
    Check([gExports count] == 0, @"an explicit delete is never exported", [gExports description]);
    Check(![list deleteClipping:Clip(@"h1", 0)], @"an equal-looking but different clipping is not deleted", nil);
    CHECK_EQ(Contents([op history]), @"h1", @"history unchanged after the refused delete");
    [list endSession];
}

static void UndoMultiStep(void) {
    FCListOperator *op = FreshOperator();
    FlycutClipping *f1 = Clip(@"F1", 25);
    Fill([op favorites], @[f1]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"h2", 20), Clip(@"h3", 10)]);
    NSArray *initial = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    FlycutClipping *h1 = [[op history] clippingAtPosition:0];
    FlycutClipping *h3 = [[op history] clippingAtPosition:2];
    [list deleteClipping:h1];
    [list toggleFavoriteOfClipping:h3];
    [list toggleFavoriteOfClipping:f1];
    CHECK_EQ(Contents([op favorites]), @"h3", @"after delete, star, star off: favorites");
    CHECK_EQ(Contents([op history]), @"F1,h2", @"after delete, star, star off: history");
    Check([list canUndo], @"three steps can be undone", nil);
    Check([list undo] == f1, @"first undo reverts the star off", nil);
    CHECK_EQ(Contents([op favorites]), @"h3,F1", @"favorites after first undo");
    Check([list undo] == h3, @"second undo reverts the star", nil);
    Check([list undo] == h1, @"third undo reverts the delete", nil);
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [initial objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [initial objectAtIndex:1]),
          @"three undos restore the exact original objects and order", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    Check(![list canUndo] && [list undo] == nil, @"nothing left to undo", nil);
    [list endSession];
}

static void UndoRefusedAfterExternalChange(void) {
    FCListOperator *op = FreshOperator();
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    FlycutClipList *list = ListFor(op);
    [list deleteClipping:[[op history] clippingAtPosition:0]];
    // A capture that was already being read when the list opened lands now.
    [op addClipping:@"arrived" ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil target:nil clippingAddedSelector:NULL];
    Check([list undo] == nil, @"undo is refused once the stores changed otherwise", nil);
    CHECK_EQ(Contents([op history]), @"arrived,h2", @"the newer clipping is never removed by an undo");
    Check(![list canUndo], @"the undo steps are dropped", nil);
    [list endSession];
}

static void ImageDeletionDeferred(void) {
    FCListOperator *op = FreshOperator();
    Fill([op history], @[ImageClip(@"aaa", 0), Clip(@"h1", 0)]);
    FlycutClipList *list = ListFor(op);
    FlycutClipping *image = [[op history] clippingAtPosition:0];
    [list deleteClipping:image];
    Check([gDeletedImages count] == 0, @"image file is kept while the list is open", [gDeletedImages description]);
    Check([list undo] == image, @"undo brings the image row back", nil);
    [list deleteClipping:image];
    [list endSession];
    CHECK_EQ([gDeletedImages componentsJoinedByString:@","], @"aaa", @"closing the list deletes the image of the deleted row once");

    FCListOperator *op2 = FreshOperator();
    Fill([op2 history], @[ImageClip(@"bbb", 0)]);
    FlycutClipList *list2 = ListFor(op2);
    [list2 deleteClipping:[[op2 history] clippingAtPosition:0]];
    [list2 undo];
    [list2 endSession];
    Check([gDeletedImages count] == 0, @"an image restored by undo is not deleted on close", [gDeletedImages description]);

    FCListOperator *op3 = FreshOperator();
    Fill([op3 favorites], @[ImageClip(@"ccc", 0)]);
    Fill([op3 history], @[ImageClip(@"ccc", 0)]);
    FlycutClipList *list3 = ListFor(op3);
    [list3 deleteClipping:[[op3 history] clippingAtPosition:0]];
    [list3 endSession];
    Check([gDeletedImages count] == 0, @"an image still listed in the other list is not deleted", [gDeletedImages description]);

    FCListOperator *op4 = FreshOperator();
    [[op4 history] setRememberNum:2];
    FlycutClipping *x = Clip(@"X", 50);
    Fill([op4 favorites], @[x]);
    Fill([op4 history], @[Clip(@"h1", 60), ImageClip(@"ddd", 40)]);
    FlycutClipList *list4 = ListFor(op4);
    [list4 toggleFavoriteOfClipping:x];
    Check([gDeletedImages count] == 0, @"an image pushed out of a full history is kept while open", [gDeletedImages description]);
    [list4 undo];
    [list4 endSession];
    Check([gDeletedImages count] == 0, @"and stays after undo and close", [gDeletedImages description]);

    FCListOperator *op5 = FreshOperator();
    Fill([op5 history], @[ImageClip(@"eee", 0)]);
    [op5 deleteClipping:[[op5 history] clippingAtPosition:0] fromList:FlycutListHistory];
    CHECK_EQ([gDeletedImages componentsJoinedByString:@","], @"eee", @"outside the list the image is deleted at once, as today");
}

static void SessionDropsUndo(void) {
    FCListOperator *op = FreshOperator();
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    FlycutClipList *list = ListFor(op);
    [list deleteClipping:[[op history] clippingAtPosition:0]];
    [list endSession];
    [list beginSession];
    Check(![list canUndo] && [list undo] == nil, @"closing the list drops its undo steps", nil);
    [list endSession];
}

static void SaveAfterChange(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@2 forKey:@"savePreference"];
    Fill([op history], @[Clip(@"h1", 0), Clip(@"h2", 0)]);
    FlycutClipList *list = ListFor(op);
    int before = op->actions;
    [list deleteClipping:[[op history] clippingAtPosition:0]];
    Check(op->actions > before, @"a delete runs the save-after-change path", nil);
    NSDictionary *saved = [[FCFakeDefaults standardUserDefaults] dictionaryForKey:@"store"];
    Check([[saved objectForKey:@"jcList"] count] == 1, @"savePreference 2 saves the change at once", [saved description]);
    int afterDelete = op->actions;
    [list undo];
    Check(op->actions > afterDelete, @"an undo saves again", nil);
    saved = [[FCFakeDefaults standardUserDefaults] dictionaryForKey:@"store"];
    Check([[saved objectForKey:@"jcList"] count] == 2, @"the saved history has the restored clipping", nil);
    NSSet *allowed = [NSSet setWithArray:@[@"version", @"rememberNum", @"favoritesRememberNum", @"jcList", @"favoritesList"]];
    Check([[NSSet setWithArray:[saved allKeys]] isSubsetOfSet:allowed], @"no undo data is written with the store", [[saved allKeys] description]);
    for (NSString *key in [[FCFakeDefaults standardUserDefaults] allKeys])
        Check([key rangeOfString:@"undo" options:NSCaseInsensitiveSearch].location == NSNotFound, @"no undo key in the defaults", key);
    [list endSession];
}

#pragma mark - drag and drop inside the list

// The list's drop API, reached by selector: without it a case fails on a check (and the
// fixture still compiles), it does not crash.
static BOOL HasDropAPI(FlycutClipList *list) {
    BOOL has = [list respondsToSelector:sel_registerName("favoriteRowCount")] &&
               [list respondsToSelector:sel_registerName("canDropClipping:aboveRow:")] &&
               [list respondsToSelector:sel_registerName("dropClipping:aboveRow:")];
    Check(has, @"FlycutClipList offers -favoriteRowCount, -canDropClipping:aboveRow: and -dropClipping:aboveRow:", nil);
    return has;
}
static NSInteger FavoriteRows(FlycutClipList *list) {
    SEL s = sel_registerName("favoriteRowCount");
    return [list respondsToSelector:s] ? ((NSInteger (*)(id, SEL))objc_msgSend)(list, s) : -1;
}
static BOOL CanDrop(FlycutClipList *list, FlycutClipping *clipping, NSInteger row) {
    SEL s = sel_registerName("canDropClipping:aboveRow:");
    return [list respondsToSelector:s] && ((BOOL (*)(id, SEL, id, NSInteger))objc_msgSend)(list, s, clipping, row);
}
static BOOL Drop(FlycutClipList *list, FlycutClipping *clipping, NSInteger row) {
    SEL s = sel_registerName("dropClipping:aboveRow:");
    return [list respondsToSelector:s] && ((BOOL (*)(id, SEL, id, NSInteger))objc_msgSend)(list, s, clipping, row);
}
static NSString *Number(NSInteger n) { return [NSString stringWithFormat:@"%ld", (long)n]; }

static void DropFavoriteReorder(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0), Clip(@"F3", 0), Clip(@"F4", 0)]);
    Fill([op history], @[Clip(@"h1", 20), Clip(@"h2", 10)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *f1 = [[op favorites] clippingAtPosition:0], *f3 = [[op favorites] clippingAtPosition:2];
    FlycutClipping *f4 = [[op favorites] clippingAtPosition:3];
    Check(FavoriteRows(list) == 4, @"the favorites are the first 4 rows", Number(FavoriteRows(list)));
    BOOL inside = YES;
    for (NSInteger row = 0; row <= 4; row++) inside = inside && CanDrop(list, f1, row);
    Check(inside, @"a favorite can be dropped above every favorite and below the last one", nil);
    Check(!CanDrop(list, f1, 5) && !CanDrop(list, f1, 6) && !CanDrop(list, f1, -1) && !CanDrop(list, f1, 7),
          @"but not inside the history block or outside the list", nil);
    Check(Drop(list, f3, 1), @"dropping F3 above the second row moves it", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,F3,F2,F4", @"F3 is the second favorite now");
    Check([[op favorites] clippingAtPosition:1] == f3, @"the same clipping object moved", nil);
    CHECK_EQ(RowsText(list), @"*F1|*F3|*F2|*F4|h1|h2", @"the rows follow the new order");
    CHECK_EQ(Contents([op history]), @"h1,h2", @"the history is untouched");
    Check(Drop(list, f1, 4), @"dropping F1 below the last favorite moves it there", nil);
    CHECK_EQ(Contents([op favorites]), @"F3,F2,F4,F1", @"F1 is the last favorite now");
    Check(Drop(list, f4, 0), @"dropping F4 above the first row moves it to the top", nil);
    CHECK_EQ(Contents([op favorites]), @"F4,F3,F2,F1", @"F4 is the first favorite now");
    Check(CanDrop(list, f3, 1) && CanDrop(list, f3, 2) && !Drop(list, f3, 1) && !Drop(list, f3, 2),
          @"a favorite dropped on its own place is accepted but changes nothing", nil);
    CHECK_EQ(Contents([op favorites]), @"F4,F3,F2,F1", @"order unchanged after dropping in place");
    Check([gExports count] == 0, @"reordering exports nothing", [gExports description]);
    Check([list undo] == f4 && [list undo] == f1 && [list undo] == f3, @"each move is one undo step, in reverse order", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,F2,F3,F4", @"three undos restore the original order");
    Check(![list canUndo], @"a drop in place left no undo step", nil);
    [list endSession];
}

static void DropFavoriteRefusedInHistory(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"h2", 20), Clip(@"h3", 10)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *f2 = [[op favorites] clippingAtPosition:1];
    Check(!CanDrop(list, f2, 3) && !CanDrop(list, f2, 4) && !CanDrop(list, f2, 5),
          @"a favorite cannot be dropped into the history block", nil);
    Check(!Drop(list, f2, 4), @"dropping it there does nothing", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,F2", @"it stays a favorite (only the star unstars)");
    CHECK_EQ(Contents([op history]), @"h1,h2,h3", @"the history is unchanged");
    Check(![list canUndo], @"no undo step for a refused drop", nil);
    [list endSession];
}

static void DropHistoryIntoFavorites(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenClippings"];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"h2", 20), Clip(@"h3", 10)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *h2 = [[op history] clippingAtPosition:1];
    Check(FavoriteRows(list) == 2 && CanDrop(list, h2, 0) && CanDrop(list, h2, 1) && CanDrop(list, h2, 2),
          @"a history clipping can be dropped into the favorites block and below its last favorite", nil);
    Check(!CanDrop(list, h2, 3) && !CanDrop(list, h2, 4) && !CanDrop(list, h2, 5),
          @"but not inside the history block (the history cannot be reordered)", nil);
    Check(Drop(list, h2, 1), @"dropping h2 between F1 and F2 succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,h2,F2", @"h2 is a favorite at the drop position");
    CHECK_EQ(Contents([op history]), @"h1,h3", @"and no longer in the history");
    Check([[op favorites] clippingAtPosition:1] == h2, @"the same clipping object moved", nil);
    CHECK_EQ(RowsText(list), @"*F1|*h2|*F2|h1|h3", @"the rows show it as a favorite");
    Check([gExports count] == 0, @"moving it to the favorites exports nothing", [gExports description]);
    Check([list undo] == h2, @"undo returns the dropped clipping", nil);
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"one undo restores both lists", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [list endSession];
}

static void DropHistoryAtEndOfFavorites(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"h2", 20)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    Check(Drop(list, [[op history] clippingAtPosition:0], 2), @"dropping h1 below the last favorite succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,F2,h1", @"h1 is the last favorite");
    CHECK_EQ(Contents([op history]), @"h2", @"and left the history");
    [list endSession];

    FCListOperator *op2 = FreshOperator();
    Fill([op2 history], @[Clip(@"h1", 30), Clip(@"h2", 20)]);
    FlycutClipList *list2 = ListFor(op2);
    FlycutClipping *h2 = [[op2 history] clippingAtPosition:1];
    Check(FavoriteRows(list2) == 0 && CanDrop(list2, h2, 0) && !CanDrop(list2, h2, 1),
          @"without favorites only the top of the list takes a drop", nil);
    Check(Drop(list2, h2, 0), @"dropping there makes the first favorite", nil);
    CHECK_EQ(Contents([op2 favorites]), @"h2", @"h2 is the only favorite");
    CHECK_EQ(Contents([op2 history]), @"h1", @"and left the history");
    [list2 endSession];
}

static void DropHistoryRefusedInHistory(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0)]);
    Fill([op history], @[Clip(@"h1", 40), Clip(@"h2", 30), Clip(@"h3", 20), Clip(@"h4", 10)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *h1 = [[op history] clippingAtPosition:0], *h3 = [[op history] clippingAtPosition:2];
    BOOL refused = YES;
    for (NSInteger row = 2; row <= 5; row++) refused = refused && !CanDrop(list, h3, row) && !CanDrop(list, h1, row);
    Check(refused, @"no position inside the history block takes a history clipping", nil);
    Check(!Drop(list, h3, 2) && !Drop(list, h1, 5), @"dropping there does nothing", nil);
    CHECK_EQ(Contents([op history]), @"h1,h2,h3,h4", @"the history stays in time order");
    CHECK_EQ(Contents([op favorites]), @"F1", @"the favorites are unchanged");
    Check(![list canUndo], @"no undo step", nil);
    [list endSession];
}

static void DropHistoryFullFavorites(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"saveForgottenFavorites"];
    [[op favorites] setRememberNum:3];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0), Clip(@"F3", 0)]);
    Fill([op history], @[Clip(@"h1", 20), Clip(@"h2", 10)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *h1 = [[op history] clippingAtPosition:0];
    Check(Drop(list, h1, 1), @"dropping into full favorites succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,h1,F2", @"as with the star the last favorite falls out; h1 sits where it was dropped");
    CHECK_EQ([gExports componentsJoinedByString:@","], @"favorites:F3", @"the dropped favorite is exported as with the star");
    Check([list undo] == h1 && SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]),
          @"undo restores both lists including the fallen-out favorite", [NSString stringWithFormat:@"%@ / %@", Contents([op history]), Contents([op favorites])]);
    [gExports removeAllObjects];
    Check(Drop(list, h1, 3), @"dropping below the last of full favorites succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,F2,h1", @"the last favorite falls out, h1 takes the end");
    [list endSession];
}

// "Remove duplicates" on: adding the clipping to the favorites first removes an equal
// favorite, so the drop position must not be counted with it.
static void DropHistoryRemoveDuplicates(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@YES forKey:@"removeDuplicates"];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"X", 0), Clip(@"F2", 0)]);
    Fill([op history], @[Clip(@"h1", 30), Clip(@"X", 20), Clip(@"h2", 10)]);
    NSArray *before = [op listsSnapshot];
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *x = [[op history] clippingAtPosition:1];
    Check(Drop(list, x, 2), @"dropping X above F2 succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,X,F2", @"the equal favorite made room; X sits above F2");
    Check([[op favorites] clippingAtPosition:1] == x, @"the dropped clipping is the one listed", nil);
    CHECK_EQ(Contents([op history]), @"h1,h2", @"X left the history");
    [list undo];
    Check(SameObjects([[op listsSnapshot] objectAtIndex:0], [before objectAtIndex:0]) &&
          SameObjects([[op listsSnapshot] objectAtIndex:1], [before objectAtIndex:1]), @"undo restores both lists", nil);
    Check(Drop(list, x, 1), @"dropping X above its equal favorite succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"F1,X,F2", @"X takes the place of its equal favorite");
    Check([[op favorites] clippingAtPosition:1] == x, @"and is the dropped clipping", nil);
    [list endSession];
}

static void DropWhileSearching(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"alpha one", 0), Clip(@"beta two", 0), Clip(@"alpha three", 0), Clip(@"beta four", 0)]);
    Fill([op history], @[Clip(@"alpha h", 20), Clip(@"beta h", 10)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    [list setSearchString:@"alpha"];
    [list reload];
    CHECK_EQ(RowsText(list), @"*alpha one|*alpha three|alpha h", @"search: two favorites and one history clipping match");
    FlycutClipping *alphaH = [[op history] clippingAtPosition:0], *alphaOne = [[op favorites] clippingAtPosition:0];
    Check(FavoriteRows(list) == 2 && CanDrop(list, alphaH, 2) && !CanDrop(list, alphaH, 3),
          @"while searching, the shown favorites are the favorites block", nil);
    Check(Drop(list, alphaH, 1), @"dropping above the second shown favorite succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"alpha one,beta two,alpha h,alpha three,beta four", @"it goes directly above that favorite");
    [list undo];
    Check(Drop(list, alphaH, 2), @"dropping below the last shown favorite succeeds", nil);
    CHECK_EQ(Contents([op favorites]), @"alpha one,beta two,alpha three,alpha h,beta four", @"it goes directly below that favorite");
    [list undo];
    Check(Drop(list, alphaOne, 2), @"a shown favorite moves below the last shown one", nil);
    CHECK_EQ(Contents([op favorites]), @"beta two,alpha three,alpha one,beta four", @"directly below it, hidden favorites keep their places");
    CHECK_EQ(RowsText(list), @"*alpha three|*alpha one|alpha h", @"the search keeps filtering");
    [list endSession];
}

static void DropPersists(void) {
    FCListOperator *op = FreshOperator();
    [[FCFakeDefaults standardUserDefaults] setObject:@2 forKey:@"savePreference"];
    Fill([op favorites], @[Clip(@"F1", 0), Clip(@"F2", 0), Clip(@"F3", 0)]);
    Fill([op history], @[Clip(@"h1", 20), Clip(@"h2", 10)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    int actions = op->actions;
    Check(Drop(list, [[op favorites] clippingAtPosition:2], 0), @"F3 dropped at the top", nil);
    Check(op->actions > actions, @"a reorder runs the save-after-change path", nil);
    NSDictionary *saved = [[FCFakeDefaults standardUserDefaults] dictionaryForKey:@"store"];
    CHECK_EQ([[[saved objectForKey:@"favoritesList"] valueForKey:@"Contents"] componentsJoinedByString:@","], @"F3,F1,F2",
             @"the saved favorites store has the new order");
    Check(Drop(list, [[op history] clippingAtPosition:0], 1), @"h1 dropped between F3 and F1", nil);
    saved = [[FCFakeDefaults standardUserDefaults] dictionaryForKey:@"store"];
    CHECK_EQ([[[saved objectForKey:@"favoritesList"] valueForKey:@"Contents"] componentsJoinedByString:@","], @"F3,h1,F1,F2",
             @"the saved favorites have the new favorite at its place");
    CHECK_EQ([[[saved objectForKey:@"jcList"] valueForKey:@"Contents"] componentsJoinedByString:@","], @"h2",
             @"the saved history no longer has it");
    [list endSession];
}

static void DropRefusesUnlisted(void) {
    FCListOperator *op = FreshOperator();
    Fill([op favorites], @[Clip(@"F1", 0)]);
    Fill([op history], @[Clip(@"h1", 0)]);
    FlycutClipList *list = ListFor(op);
    if (!HasDropAPI(list)) { [list endSession]; return; }
    FlycutClipping *stranger = Clip(@"h1", 0);   // equal text, but not a listed object
    Check(!CanDrop(list, stranger, 0) && !Drop(list, stranger, 0) && !CanDrop(list, nil, 0),
          @"a clipping that is not listed cannot be dropped", nil);
    CHECK_EQ(Contents([op favorites]), @"F1", @"favorites unchanged");
    CHECK_EQ(Contents([op history]), @"h1", @"history unchanged");
    [list endSession];
}

static void ListHeight(void) {
    NSMutableArray *mock = [NSMutableArray arrayWithObjects:@24, @24, @24, @24, @11, @24, nil];
    for (int i = 0; i < 57; i++) [mock addObject:@24];
    CGFloat h = [FlycutClipList listHeightForRowHeights:mock rowHeight:24 visibleRows:20 maximum:10000];
    Check(h == 479, @"20 rows: the list ends in the middle of the row crossing 20 rows (approved mockup: 479 pt)",
          [NSString stringWithFormat:@"%g", h]);
    CGFloat few = [FlycutClipList listHeightForRowHeights:@[@24, @24, @24] rowHeight:24 visibleRows:20 maximum:10000];
    Check(few == 72, @"fewer rows than displayNum: the list follows its content", [NSString stringWithFormat:@"%g", few]);
    CGFloat capped = [FlycutClipList listHeightForRowHeights:mock rowHeight:24 visibleRows:20 maximum:200];
    Check(capped == 191, @"capped to the screen: ends in the middle of the row crossing the cap", [NSString stringWithFormat:@"%g", capped]);
    CGFloat ten = [FlycutClipList listHeightForRowHeights:mock rowHeight:24 visibleRows:10 maximum:10000];
    Check(ten == 239, @"displayNum 10 gives ten rows minus a half", [NSString stringWithFormat:@"%g", ten]);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        gDeletedImages = [[NSMutableArray alloc] init];
        gExports = [[NSMutableArray alloc] init];
        NSDictionary *cases = @{
            @"rows-order": [NSValue valueWithPointer:RowsOrder],
            @"rows-empty-lists": [NSValue valueWithPointer:RowsEmptyLists],
            @"search": [NSValue valueWithPointer:Search],
            @"star-to-top": [NSValue valueWithPointer:StarToTop],
            @"star-full-favorites": [NSValue valueWithPointer:StarFullFavorites],
            @"star-remove-duplicates-equal": [NSValue valueWithPointer:StarRemoveDuplicatesTakesEqualPlace],
            @"unstar-time-position": [NSValue valueWithPointer:UnstarTimePosition],
            @"unstar-unsorted": [NSValue valueWithPointer:UnstarUnsorted],
            @"unstar-unknown-time": [NSValue valueWithPointer:UnstarUnknownTime],
            @"unstar-full-history-oldest": [NSValue valueWithPointer:UnstarFullHistoryOldest],
            @"unstar-full-history-middle": [NSValue valueWithPointer:UnstarFullHistoryMiddle],
            @"unstar-remove-duplicates-equal": [NSValue valueWithPointer:UnstarRemoveDuplicatesEqualAtTimePosition],
            @"unstar-remove-duplicates-newer": [NSValue valueWithPointer:UnstarRemoveDuplicatesEqualNewer],
            @"unstar-remove-duplicates-older": [NSValue valueWithPointer:UnstarRemoveDuplicatesEqualOlder],
            @"unstar-remove-duplicates-full": [NSValue valueWithPointer:UnstarRemoveDuplicatesFullHistory],
            @"unstar-duplicates-kept-when-off": [NSValue valueWithPointer:UnstarKeepsDuplicatesWhenOff],
            @"delete-not-exported": [NSValue valueWithPointer:DeleteNotExported],
            @"undo-multi-step": [NSValue valueWithPointer:UndoMultiStep],
            @"undo-refused-after-external-change": [NSValue valueWithPointer:UndoRefusedAfterExternalChange],
            @"image-deletion-deferred": [NSValue valueWithPointer:ImageDeletionDeferred],
            @"session-drops-undo": [NSValue valueWithPointer:SessionDropsUndo],
            @"save-after-change": [NSValue valueWithPointer:SaveAfterChange],
            @"list-height": [NSValue valueWithPointer:ListHeight],
            @"drop-favorite-reorder": [NSValue valueWithPointer:DropFavoriteReorder],
            @"drop-favorite-refused-in-history": [NSValue valueWithPointer:DropFavoriteRefusedInHistory],
            @"drop-history-into-favorites": [NSValue valueWithPointer:DropHistoryIntoFavorites],
            @"drop-history-at-end-of-favorites": [NSValue valueWithPointer:DropHistoryAtEndOfFavorites],
            @"drop-history-refused-in-history": [NSValue valueWithPointer:DropHistoryRefusedInHistory],
            @"drop-history-full-favorites": [NSValue valueWithPointer:DropHistoryFullFavorites],
            @"drop-history-remove-duplicates": [NSValue valueWithPointer:DropHistoryRemoveDuplicates],
            @"drop-while-searching": [NSValue valueWithPointer:DropWhileSearching],
            @"drop-persists": [NSValue valueWithPointer:DropPersists],
            @"drop-refuses-unlisted": [NSValue valueWithPointer:DropRefusesUnlisted],
        };
        NSValue *found = [cases objectForKey:[NSString stringWithUTF8String:argv[1]]];
        if (found == nil) return 3;
        ((void (*)(void))[found pointerValue])();
    }
    return failures == 0 ? 0 : 1;
}
