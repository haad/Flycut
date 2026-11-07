// Native fixture for RichTextFormattingRegressionTests.py.
//
// Compiles the real FlycutClipping, FlycutStore and FlycutOperator method
// bodies plus the exact AppController pollPB:, addClipToPasteboard:withRichData:
// and setPBBlockCount: method text (extracted by the runner). Only OS
// boundaries are replaced: NSPasteboard (an in-memory generation model),
// NSWorkspace, NSUserDefaults (an in-memory dictionary), libdispatch (runs
// blocks inline and records the target queue), the on-disk image store and
// the file-writing autosave path. Nothing touches the real clipboard,
// defaults, Application Support, other apps or input.

#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static void Check(BOOL condition, const char *message) {
    if (condition) {
        printf("PASS: %s\n", message);
    } else {
        fprintf(stderr, "FAIL: %s\n", message);
        failures++;
    }
}

#pragma mark - NSUserDefaults double

@interface FCFakeDefaults : NSObject {
    NSMutableDictionary *values;
}
+ (FCFakeDefaults *)standardUserDefaults;
- (void)reset;
- (void)registerDefaults:(NSDictionary *)registration;
- (id)objectForKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
- (NSDictionary *)dictionaryForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSURL *)URLForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
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
- (void)reset { [values removeAllObjects]; }
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
- (BOOL)synchronize { return YES; }
@end

#pragma mark - NSPasteboard double

// Each generation maps pasteboard types to NSString or NSData values. A read
// trigger models another app replacing the clipboard while Flycut reads it.
@interface FCFakePasteboard : NSObject {
@public
    NSInteger generation;
    NSMutableDictionary *current;
    NSDictionary *replacement;
    NSString *replaceBeforeDataReadOfType;
    NSMutableArray *declaredTypes;
}
- (NSInteger)changeCount;
- (NSArray *)types;
- (NSString *)availableTypeFromArray:(NSArray *)types;
- (NSString *)stringForType:(NSString *)type;
- (NSData *)dataForType:(NSString *)type;
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner;
- (BOOL)setString:(NSString *)string forType:(NSString *)type;
- (BOOL)setData:(NSData *)data forType:(NSString *)type;
- (void)copyGeneration:(NSDictionary *)contents;
@end

@implementation FCFakePasteboard
- (id)init {
    if ((self = [super init])) {
        current = [[NSMutableDictionary alloc] init];
        declaredTypes = [[NSMutableArray alloc] init];
    }
    return self;
}
- (void)copyGeneration:(NSDictionary *)contents {
    generation++;
    [current setDictionary:contents];
}
- (NSInteger)changeCount { return generation; }
- (NSArray *)types { return [current allKeys]; }
- (NSString *)availableTypeFromArray:(NSArray *)types {
    for (NSString *type in types)
        if ([current objectForKey:type] != nil)
            return type;
    return nil;
}
- (NSString *)stringForType:(NSString *)type {
    id value = [current objectForKey:type];
    if ([value isKindOfClass:[NSData class]])
        return [[[NSString alloc] initWithData:value encoding:NSUTF8StringEncoding] autorelease];
    return value;
}
- (NSData *)dataForType:(NSString *)type {
    if (replacement != nil && [type isEqualToString:replaceBeforeDataReadOfType]) {
        [self copyGeneration:replacement];
        [replacement release];
        replacement = nil;
    }
    id value = [current objectForKey:type];
    if ([value isKindOfClass:[NSString class]])
        return [value dataUsingEncoding:NSUTF8StringEncoding];
    return value;
}
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner {
    generation++;
    [current removeAllObjects];
    [declaredTypes setArray:types];
    return generation;
}
- (BOOL)setString:(NSString *)string forType:(NSString *)type {
    [current setObject:string forKey:type];
    return YES;
}
- (BOOL)setData:(NSData *)data forType:(NSString *)type {
    [current setObject:data forKey:type];
    return YES;
}
@end

#pragma mark - NSWorkspace and libdispatch doubles

@interface FCFakeWorkspace : NSObject
+ (FCFakeWorkspace *)sharedWorkspace;
- (NSArray *)runningApplications;
@end
@implementation FCFakeWorkspace
+ (FCFakeWorkspace *)sharedWorkspace { return [[[FCFakeWorkspace alloc] init] autorelease]; }
- (NSArray *)runningApplications { return @[]; }
@end

static int mainQueueBlocks, backgroundQueueBlocks;
static void FCDispatchAsync(dispatch_queue_t queue, dispatch_block_t block) {
    if (queue == dispatch_get_main_queue()) mainQueueBlocks++; else backgroundQueueBlocks++;
    block();
}

// Filesystem root used by the (overridden, never reached) autosave path.
static NSArray *FCFakeSearchPath(NSSearchPathDirectory directory, NSSearchPathDomainMask mask, BOOL expand) {
    return @[NSTemporaryDirectory()];
}

#define NSUserDefaults FCFakeDefaults
#define NSSearchPathForDirectoriesInDomains FCFakeSearchPath
#define DLog(...) do {} while (0)

#include "FlycutEngine/FlycutClipping.m"
#include "FlycutEngine/FlycutStore.m"
#include "FlycutOperator.m"

@implementation FlycutImageStore
+ (FlycutImageStore *)sharedStore {
    fprintf(stderr, "FAIL: fixture reached the on-disk image store\n");
    abort();
}
+ (NSString *)fileExtensionForType:(NSString *)uti { return @"tiff"; }
@end

@interface FCOperator : FlycutOperator
@end
@implementation FCOperator
- (bool)saveFromStore:(FlycutStore *)store atIndex:(int)index withPrefix:(NSString *)prefix {
    fprintf(stderr, "FAIL: fixture reached the file-writing autosave path\n");
    abort();
}
@end

#pragma mark - AppController method harness

#define NSWorkspace FCFakeWorkspace
#define dispatch_async FCDispatchAsync

@interface FCAppHarness : NSObject {
@public
    FCFakePasteboard *jcPasteboard;
    NSNumber *pbCount;
    NSNumber *pbBlockCount;
    FlycutOperator *flycutOperator;
    int menuUpdates;
}
- (void)pollPB:(NSTimer *)timer;
- (void)addClipToPasteboard:(NSString *)pbFullText withRichData:(NSDictionary *)richData;
- (void)setPBBlockCount:(NSNumber *)newPBBlockCount;
- (bool)toggleMenuIconDisabled;
- (NSURL *)animatedGifURLFromPasteboard;
- (void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL;
- (void)updateMenu;
@end

@implementation FCAppHarness
#include "AppControllerMethods.inc"
- (bool)toggleMenuIconDisabled { Check(NO, "unexpected status item toggle"); return NO; }
- (NSURL *)animatedGifURLFromPasteboard { Check(NO, "unexpected GIF URL lookup"); return nil; }
- (void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL {
    Check(NO, "unexpected network download");
}
- (void)updateMenu { menuUpdates++; }
@end

#undef dispatch_async
#undef NSWorkspace

#pragma mark - Helpers

static NSData *Bytes(NSString *text) { return [text dataUsingEncoding:NSUTF8StringEncoding]; }

static FCOperator *FreshOperator(int savePreference) {
    [[FCFakeDefaults standardUserDefaults] reset];
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    [defaults setObject:@(savePreference) forKey:@"savePreference"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@NO forKey:@"captureImages"];
    FCOperator *op = [[FCOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:NULL forTarget:nil];
    return op;
}

static FCAppHarness *FreshHarness(FCOperator *op) {
    FCAppHarness *app = [[FCAppHarness alloc] init];
    app->jcPasteboard = [[FCFakePasteboard alloc] init];
    app->pbCount = [[NSNumber numberWithInt:0] retain];
    app->pbBlockCount = [[NSNumber numberWithInt:0] retain];
    app->flycutOperator = op;
    mainQueueBlocks = backgroundQueueBlocks = 0;
    return app;
}

static NSDictionary *SavedRichData(FCOperator *op, int index) {
    NSArray *list = [[[FCFakeDefaults standardUserDefaults] dictionaryForKey:@"store"] objectForKey:@"jcList"];
    if (index >= (int)[list count]) return nil;
    return [[list objectAtIndex:index] objectForKey:@"RichData"];
}

#pragma mark - Cases

static void RunCaptureStable(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = FreshHarness(op);
    NSData *rtf = Bytes(@"{\\rtf1 stable}");
    NSData *html = Bytes(@"<b>stable</b>");
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"stable text", NSPasteboardTypeRTF: rtf, NSPasteboardTypeHTML: html}];
    [app pollPB:nil];
    Check([op jcListCount] == 1 && [[op getClipFromCount:0] isEqualToString:@"stable text"],
          "a stable clipboard generation is captured");
    Check([[op getRichDataFromIndex:0] isEqual:(@{NSPasteboardTypeRTF: rtf, NSPasteboardTypeHTML: html})],
          "its RTF and HTML are stored with the text");
    Check(backgroundQueueBlocks == 1 && mainQueueBlocks == 1,
          "the clipboard is read on a background queue and committed on the main queue");
}

static void RunCaptureMixedGeneration(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = FreshHarness(op);
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"visible text", NSPasteboardTypeRTF: Bytes(@"{\\rtf1 visible}")}];
    // Another app replaces the clipboard (with a concealed item) after Flycut
    // read and checked the plain text but before it read the RTF.
    app->jcPasteboard->replacement = [@{NSPasteboardTypeString: @"concealed secret",
                                        NSPasteboardTypeRTF: Bytes(@"{\\rtf1 concealed secret}"),
                                        @"org.nspasteboard.ConcealedType": [NSData data]} retain];
    app->jcPasteboard->replaceBeforeDataReadOfType = NSPasteboardTypeRTF;
    [app pollPB:nil];
    BOOL mixed = NO;
    for (int i = 0; i < [op jcListCount]; i++)
        if ([[[op getRichDataFromIndex:i] objectForKey:NSPasteboardTypeRTF] isEqual:Bytes(@"{\\rtf1 concealed secret}")])
            mixed = YES;
    Check(!mixed, "RTF from a later clipboard generation is never stored with earlier text");
    Check([op jcListCount] == 0, "a snapshot whose generation changed while reading is discarded");
    [app pollPB:nil];
    Check([op jcListCount] == 0, "the replacing concealed generation is skipped on the next poll");
    [app->jcPasteboard copyGeneration:@{NSPasteboardTypeString: @"next text", NSPasteboardTypeRTF: Bytes(@"{\\rtf1 next}")}];
    [app pollPB:nil];
    Check([op jcListCount] == 1 && [[op getClipFromCount:0] isEqualToString:@"next text"]
          && [[op getRichDataFromIndex:0] isEqual:@{NSPasteboardTypeRTF: Bytes(@"{\\rtf1 next}")}],
          "the following stable generation is captured with its own RTF");
}

static void RunSameTextNewFormatting(void) {
    FCOperator *op = FreshOperator(2);
    NSDictionary *bold = @{NSPasteboardTypeRTF: Bytes(@"{\\rtf1 \\b same}")};
    [op addClipping:@"same" ofType:NSPasteboardTypeString withRichData:nil fromApp:@"Fixture" withAppBundleURL:nil target:nil clippingAddedSelector:NULL];
    [op addClipping:@"same" ofType:NSPasteboardTypeString withRichData:bold fromApp:@"Fixture" withAppBundleURL:nil target:nil clippingAddedSelector:NULL];
    Check([op jcListCount] == 1, "copying the same text again does not add a duplicate");
    Check([[op getRichDataFromIndex:0] isEqual:bold], "the newest formatting of the same text is kept");
    Check([SavedRichData(op, 0) isEqual:bold], "the updated formatting is saved");
    [op addClipping:@"same" ofType:NSPasteboardTypeString withRichData:nil fromApp:@"Fixture" withAppBundleURL:nil target:nil clippingAddedSelector:NULL];
    Check([op jcListCount] == 1 && [op getRichDataFromIndex:0] == nil,
          "a later plain copy of the same text clears the stale formatting");
    Check(SavedRichData(op, 0) == nil, "the cleared formatting is saved");
}

static NSDictionary *UntrustedStore(void) {
    NSMutableData *oversized = [NSMutableData dataWithLength:1048577];
    return @{@"jcList": @[@{@"Contents": @"visible",
                            @"Type": NSPasteboardTypeString,
                            @"RichData": @{NSPasteboardTypeString: Bytes(@"hidden replacement"),
                                           @"com.example.custom": Bytes(@"custom"),
                                           NSPasteboardTypeHTML: oversized,
                                           NSPasteboardTypeRTF: Bytes(@"{\\rtf1 visible}")}}]};
}

static void RunRestoredRichDataNormalised(void) {
    FCOperator *op = FreshOperator(0);
    FlycutStore *restored = [[FlycutStore alloc] initRemembering:40 displaying:10 withDisplayLength:40];
    [op loadEngineFrom:UntrustedStore() key:@"jcList" into:restored];
    NSDictionary *richData = [[restored clippingAtPosition:0] richData];
    Check([[restored clippingContentsAtPosition:0] isEqualToString:@"visible"], "the plain text is restored");
    Check([richData objectForKey:NSPasteboardTypeString] == nil, "restored rich data never carries the plain-text type");
    Check([richData objectForKey:@"com.example.custom"] == nil, "restored rich data drops types other than RTF and HTML");
    Check([richData objectForKey:NSPasteboardTypeHTML] == nil, "restored rich data drops representations over 1 MiB");
    Check([richData isEqual:@{NSPasteboardTypeRTF: Bytes(@"{\\rtf1 visible}")}], "valid restored RTF is kept");
    [restored release];

    NSDictionary *supplied = @{NSPasteboardTypeString: Bytes(@"hidden"), NSPasteboardTypeRTF: [NSData data]};
    [op addClipping:@"plain" ofType:NSPasteboardTypeString withRichData:supplied fromApp:@"Fixture" withAppBundleURL:nil target:nil clippingAddedSelector:NULL];
    Check([op getRichDataFromIndex:0] == nil, "supplied rich data without a valid RTF/HTML entry is dropped");
}

static void RunRestoredRichDataPaste(void) {
    FCOperator *op = FreshOperator(0);
    FCAppHarness *app = FreshHarness(op);
    FlycutStore *restored = [[FlycutStore alloc] initRemembering:40 displaying:10 withDisplayLength:40];
    [op loadEngineFrom:UntrustedStore() key:@"jcList" into:restored];
    [app addClipToPasteboard:[restored clippingContentsAtPosition:0] withRichData:[[restored clippingAtPosition:0] richData]];
    Check([[app->jcPasteboard stringForType:NSPasteboardTypeString] isEqualToString:@"visible"],
          "pasting a restored clipping puts its visible text on the pasteboard");
    NSSet *declared = [NSSet setWithArray:app->jcPasteboard->declaredTypes];
    Check([declared isEqual:[NSSet setWithObjects:NSPasteboardTypeString, NSPasteboardTypeRTF, nil]],
          "only the plain string and valid RTF/HTML types are declared");
    Check([app->pbBlockCount integerValue] == [app->jcPasteboard changeCount],
          "Flycut's own paste generation is blocked from capture");
    [restored release];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        if (strcmp(argv[1], "capture-stable") == 0) RunCaptureStable();
        else if (strcmp(argv[1], "capture-mixed-generation") == 0) RunCaptureMixedGeneration();
        else if (strcmp(argv[1], "same-text-new-formatting") == 0) RunSameTextNewFormatting();
        else if (strcmp(argv[1], "restored-rich-data") == 0) RunRestoredRichDataNormalised();
        else if (strcmp(argv[1], "restored-rich-data-paste") == 0) RunRestoredRichDataPaste();
        else return 3;
    }
    return failures == 0 ? 0 : 1;
}
