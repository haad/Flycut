// Image clipping backing-store regressions.
//
// The production engine sources (FlycutClipping, FlycutStore, FlycutImageStore,
// FlycutOperator) are compiled unchanged into this file, together with image
// paste methods extracted verbatim from AppController.m. Only OS boundaries are
// test doubles: user defaults live in memory (persisted only to a file inside the
// fixture root), the Application Support / Desktop / temporary directories point
// into the fixture root, and the pasteboard is an in-memory object. A guard
// aborts the process if any guarded file operation leaves the fixture root.
#import <Cocoa/Cocoa.h>
#import <ImageIO/ImageIO.h>
#import <objc/runtime.h>
#import <stdio.h>
#import <string.h>
#import <unistd.h>
#import "FlycutClipping.h"
#import "FlycutStore.h"
#import "FlycutImageStore.h"
#import "FlycutOperator.h"
#import "AppController.h"

static NSString *fixtureRoot;
static int failures;
#define CHECK(condition, message) do { if (!(condition)) { \
    fprintf(stderr, "FAIL: %s (%s:%d)\n", message, __FILE__, __LINE__); failures++; } } while (0)

// ---------------------------------------------------------------------------
// Containment guard: every file path the code under test touches must be inside
// the fixture root. A violation exits immediately with status 90.
// ---------------------------------------------------------------------------
static BOOL PathIsInsideRoot(NSString *path) {
    if (![path isKindOfClass:[NSString class]] || ![path isAbsolutePath]) return NO;
    NSString *standard = [path stringByStandardizingPath];
    return [standard isEqualToString:fixtureRoot] ||
           [standard hasPrefix:[fixtureRoot stringByAppendingString:@"/"]];
}
static void GuardPath(NSString *path, const char *operation) {
    if (PathIsInsideRoot(path)) return;
    fprintf(stderr, "CONTAINMENT: %s outside fixture root: %s\n", operation,
            [path isKindOfClass:[NSString class]] ? [path UTF8String] : "(not a path)");
    fflush(stderr);
    _exit(90);
}
static IMP realCreateDirectory, realRemoveItem, realContents, realFileExists;
static IMP realDataWrite, realDataWriteOptions, realDataRead, realStringWrite;
static BOOL GuardedCreateDirectory(id self, SEL cmd, NSString *path, BOOL intermediate, NSDictionary *attributes, NSError **error) {
    GuardPath(path, "createDirectory");
    return ((BOOL (*)(id, SEL, NSString *, BOOL, NSDictionary *, NSError **))realCreateDirectory)(self, cmd, path, intermediate, attributes, error);
}
static BOOL GuardedRemoveItem(id self, SEL cmd, NSString *path, NSError **error) {
    GuardPath(path, "removeItem");
    return ((BOOL (*)(id, SEL, NSString *, NSError **))realRemoveItem)(self, cmd, path, error);
}
static NSArray *GuardedContents(id self, SEL cmd, NSString *path, NSError **error) {
    GuardPath(path, "contentsOfDirectory");
    return ((NSArray *(*)(id, SEL, NSString *, NSError **))realContents)(self, cmd, path, error);
}
static BOOL GuardedFileExists(id self, SEL cmd, NSString *path) {
    GuardPath(path, "fileExists");
    return ((BOOL (*)(id, SEL, NSString *))realFileExists)(self, cmd, path);
}
static BOOL GuardedDataWrite(id self, SEL cmd, NSString *path, BOOL atomically) {
    GuardPath(path, "NSData write");
    return ((BOOL (*)(id, SEL, NSString *, BOOL))realDataWrite)(self, cmd, path, atomically);
}
static BOOL GuardedDataWriteOptions(id self, SEL cmd, NSString *path, NSDataWritingOptions options, NSError **error) {
    GuardPath(path, "NSData write");
    return ((BOOL (*)(id, SEL, NSString *, NSDataWritingOptions, NSError **))realDataWriteOptions)(self, cmd, path, options, error);
}
static id GuardedDataRead(id self, SEL cmd, NSString *path) {
    GuardPath(path, "NSData read");
    return ((id (*)(id, SEL, NSString *))realDataRead)(self, cmd, path);
}
static BOOL GuardedStringWrite(id self, SEL cmd, NSString *path, BOOL atomically, NSStringEncoding encoding, NSError **error) {
    GuardPath(path, "NSString write");
    return ((BOOL (*)(id, SEL, NSString *, BOOL, NSStringEncoding, NSError **))realStringWrite)(self, cmd, path, atomically, encoding, error);
}
static IMP Swap(Class cls, SEL selector, IMP replacement, BOOL classMethod) {
    Method method = classMethod ? class_getClassMethod(cls, selector) : class_getInstanceMethod(cls, selector);
    if (!method) { fprintf(stderr, "CONTAINMENT: cannot guard %s\n", sel_getName(selector)); _exit(91); }
    return method_setImplementation(method, replacement);
}
static void InstallContainmentGuards(void) {
    Class fm = [NSFileManager class];
    realCreateDirectory = Swap(fm, @selector(createDirectoryAtPath:withIntermediateDirectories:attributes:error:), (IMP)GuardedCreateDirectory, NO);
    realRemoveItem = Swap(fm, @selector(removeItemAtPath:error:), (IMP)GuardedRemoveItem, NO);
    realContents = Swap(fm, @selector(contentsOfDirectoryAtPath:error:), (IMP)GuardedContents, NO);
    realFileExists = Swap(fm, @selector(fileExistsAtPath:), (IMP)GuardedFileExists, NO);
    realDataWrite = Swap([NSData class], @selector(writeToFile:atomically:), (IMP)GuardedDataWrite, NO);
    realDataWriteOptions = Swap([NSData class], @selector(writeToFile:options:error:), (IMP)GuardedDataWriteOptions, NO);
    realDataRead = Swap([NSData class], @selector(dataWithContentsOfFile:), (IMP)GuardedDataRead, YES);
    realStringWrite = Swap([NSString class], @selector(writeToFile:atomically:encoding:error:), (IMP)GuardedStringWrite, NO);
}

// ---------------------------------------------------------------------------
// OS boundary doubles.
// ---------------------------------------------------------------------------
static NSString *RootPath(NSString *relative) {
    return [fixtureRoot stringByAppendingPathComponent:relative];
}

// In-memory user defaults. synchronize persists plist-compatible values to a file
// inside the fixture root, which lets a second fixture process model a relaunch.
@interface FixtureDefaults : NSObject {
    NSMutableDictionary *values;
    NSMutableDictionary *registered;
}
+ (FixtureDefaults *)standardUserDefaults;
- (void)registerDefaults:(NSDictionary *)dictionary;
- (id)objectForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (void)setInteger:(NSInteger)value forKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (void)setBool:(BOOL)value forKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
- (NSDictionary *)dictionaryForKey:(NSString *)key;
- (NSURL *)URLForKey:(NSString *)key;
- (void)setURL:(NSURL *)url forKey:(NSString *)key;
- (BOOL)synchronize;
@end

@implementation FixtureDefaults
+ (FixtureDefaults *)standardUserDefaults {
    static FixtureDefaults *shared = nil;
    if (!shared) shared = [[FixtureDefaults alloc] init];
    return shared;
}
- (id)init {
    self = [super init];
    if (self) {
        registered = [[NSMutableDictionary alloc] init];
        NSDictionary *saved = [NSDictionary dictionaryWithContentsOfFile:RootPath(@"defaults.plist")];
        values = saved ? [saved mutableCopy] : [[NSMutableDictionary alloc] init];
    }
    return self;
}
- (void)registerDefaults:(NSDictionary *)dictionary { [registered addEntriesFromDictionary:dictionary]; }
- (id)objectForKey:(NSString *)key {
    id value = [values objectForKey:key];
    return value ? value : [registered objectForKey:key];
}
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) [values setObject:value forKey:key]; else [values removeObjectForKey:key];
}
- (void)removeObjectForKey:(NSString *)key { [values removeObjectForKey:key]; }
- (id)valueForKey:(NSString *)key { return [self objectForKey:key]; }
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [[self objectForKey:key] integerValue]; }
- (void)setInteger:(NSInteger)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (BOOL)boolForKey:(NSString *)key { return [[self objectForKey:key] boolValue]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (NSString *)stringForKey:(NSString *)key {
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSString class]] ? value : nil;
}
- (NSDictionary *)dictionaryForKey:(NSString *)key {
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSDictionary class]] ? value : nil;
}
- (NSURL *)URLForKey:(NSString *)key {
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSURL class]] ? value : nil;
}
- (void)setURL:(NSURL *)url forKey:(NSString *)key { [self setObject:url forKey:key]; }
- (BOOL)synchronize {
    NSMutableDictionary *plist = [NSMutableDictionary dictionary];
    for (NSString *key in values) {
        id value = [values objectForKey:key];
        if ([NSPropertyListSerialization propertyList:value isValidForFormat:NSPropertyListBinaryFormat_v1_0])
            [plist setObject:value forKey:key];
    }
    return [plist writeToFile:RootPath(@"defaults.plist") atomically:YES];
}
@end

static NSArray *FixtureSearchPath(NSSearchPathDirectory directory, NSSearchPathDomainMask domain, BOOL expandTilde) {
    (void)expandTilde;
    if (domain != NSUserDomainMask) { fprintf(stderr, "CONTAINMENT: unexpected search domain\n"); _exit(92); }
    if (directory == NSApplicationSupportDirectory) return @[RootPath(@"Library/Application Support")];
    if (directory == NSDesktopDirectory) return @[RootPath(@"Desktop")];
    fprintf(stderr, "CONTAINMENT: unexpected search directory %lu\n", (unsigned long)directory);
    _exit(92);
}
static NSString *FixtureTemporaryDirectory(void) {
    return [RootPath(@"tmp") stringByAppendingString:@"/"];
}

// In-memory pasteboard. -fixtureCopyTypes:data: models another application copying.
// replaceOnReadOfType models a copy that lands just before that type is read.
@interface FixturePasteboard : NSObject {
@public
    NSInteger changeCount;
    NSMutableArray *declaredTypes;
    NSMutableDictionary *dataByType;
    NSArray *writtenObjects;
    BOOL failWrites;
    NSString *replaceOnReadOfType;
    NSArray *replacementTypes;
    NSDictionary *replacementData;
}
- (NSInteger)changeCount;
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner;
- (NSInteger)clearContents;
- (BOOL)setData:(NSData *)data forType:(NSString *)type;
- (BOOL)setString:(NSString *)string forType:(NSString *)type;
- (BOOL)writeObjects:(NSArray *)objects;
- (NSArray *)types;
- (NSString *)availableTypeFromArray:(NSArray *)types;
- (NSData *)dataForType:(NSString *)type;
- (NSString *)stringForType:(NSString *)type;
- (void)fixtureCopyTypes:(NSArray *)types data:(NSDictionary *)data;
@end

@implementation FixturePasteboard
- (id)init {
    self = [super init];
    if (self) {
        changeCount = 1;
        declaredTypes = [[NSMutableArray alloc] init];
        dataByType = [[NSMutableDictionary alloc] init];
    }
    return self;
}
- (NSInteger)changeCount { @synchronized (self) { return changeCount; } }
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner {
    (void)owner;
    @synchronized (self) {
        changeCount++;
        [declaredTypes setArray:types];
        [dataByType removeAllObjects];
        [writtenObjects release]; writtenObjects = nil;
        return changeCount;
    }
}
- (NSInteger)clearContents { return [self declareTypes:@[] owner:nil]; }
- (BOOL)setData:(NSData *)data forType:(NSString *)type {
    @synchronized (self) {
        if (failWrites || !data || ![declaredTypes containsObject:type]) return NO;
        [dataByType setObject:data forKey:type];
        return YES;
    }
}
- (BOOL)setString:(NSString *)string forType:(NSString *)type {
    return [self setData:[string dataUsingEncoding:NSUTF8StringEncoding] forType:type];
}
- (BOOL)writeObjects:(NSArray *)objects {
    // As on NSPasteboard, only -clearContents/-declareTypes:owner: change the change count.
    @synchronized (self) {
        if (failWrites) return NO;
        [writtenObjects release];
        writtenObjects = [objects copy];
        [declaredTypes setArray:@[NSPasteboardTypeFileURL]];
        return YES;
    }
}
- (NSArray *)types { @synchronized (self) { return [[declaredTypes copy] autorelease]; } }
- (NSString *)availableTypeFromArray:(NSArray *)types {
    @synchronized (self) {
        for (NSString *type in types)
            if ([declaredTypes containsObject:type]) return type;
        return nil;
    }
}
- (NSData *)dataForType:(NSString *)type {
    @synchronized (self) {
        if (replaceOnReadOfType && [type isEqualToString:replaceOnReadOfType]) {
            [replaceOnReadOfType release]; replaceOnReadOfType = nil;
            [self fixtureCopyTypes:replacementTypes data:replacementData];
        }
        return [[[dataByType objectForKey:type] retain] autorelease];
    }
}
- (NSString *)stringForType:(NSString *)type {
    NSData *data = [self dataForType:type];
    return data ? [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] autorelease] : nil;
}
- (void)fixtureCopyTypes:(NSArray *)types data:(NSDictionary *)data {
    @synchronized (self) {
        changeCount++;
        [declaredTypes setArray:types];
        [dataByType setDictionary:data];
        [writtenObjects release]; writtenObjects = nil;
    }
}
@end

// ---------------------------------------------------------------------------
// Production engine sources, compiled with the doubles above.
// ---------------------------------------------------------------------------
#define NSUserDefaults FixtureDefaults
#define NSSearchPathForDirectoriesInDomains FixtureSearchPath
#define NSTemporaryDirectory FixtureTemporaryDirectory
#include "FlycutEngine/FlycutClipping.m"
#include "FlycutEngine/FlycutStore.m"
#include "FlycutEngine/FlycutImageStore.m"
#include "FlycutOperator.m"

// Workspace, network and UI doubles for the extracted AppController methods.
@interface FixtureWorkspace : NSObject
+ (FixtureWorkspace *)sharedWorkspace;
- (NSArray *)runningApplications;
@end
@implementation FixtureWorkspace
+ (FixtureWorkspace *)sharedWorkspace { static FixtureWorkspace *shared; if (!shared) shared = [[self alloc] init]; return shared; }
- (NSArray *)runningApplications { return @[]; }
@end

typedef void (^FixtureCompletion)(NSData *, NSURLResponse *, NSError *);
static FixtureCompletion pendingDownload;   // completion handler of the last requested download
static NSURL *pendingDownloadURL;
static int downloadRequests;
@interface FixtureURLSessionConfiguration : NSObject {
    NSTimeInterval timeoutIntervalForRequest, timeoutIntervalForResource;
}
@property (nonatomic, assign) NSTimeInterval timeoutIntervalForRequest;
@property (nonatomic, assign) NSTimeInterval timeoutIntervalForResource;
+ (FixtureURLSessionConfiguration *)ephemeralSessionConfiguration;
@end
@implementation FixtureURLSessionConfiguration
@synthesize timeoutIntervalForRequest, timeoutIntervalForResource;
+ (FixtureURLSessionConfiguration *)ephemeralSessionConfiguration { return [[[self alloc] init] autorelease]; }
@end
@interface FixtureDataTask : NSObject
- (void)resume;
@end
@implementation FixtureDataTask
- (void)resume { downloadRequests++; }
@end
@interface FixtureURLSession : NSObject
+ (FixtureURLSession *)sessionWithConfiguration:(FixtureURLSessionConfiguration *)configuration;
- (id)dataTaskWithURL:(NSURL *)url completionHandler:(void (^)(NSData *, NSURLResponse *, NSError *))handler;
- (void)finishTasksAndInvalidate;
@end
@implementation FixtureURLSession
+ (FixtureURLSession *)sessionWithConfiguration:(FixtureURLSessionConfiguration *)configuration {
    (void)configuration;
    return [[[self alloc] init] autorelease];
}
- (id)dataTaskWithURL:(NSURL *)url completionHandler:(void (^)(NSData *, NSURLResponse *, NSError *))handler {
    [pendingDownload release]; pendingDownload = [handler copy];
    [pendingDownloadURL release]; pendingDownloadURL = [url retain];
    return [[[FixtureDataTask alloc] init] autorelease];
}
- (void)finishTasksAndInvalidate {}
@end

// Background work of the extracted methods runs on this serial queue, so a case can
// wait for it deterministically before draining the main queue.
static dispatch_queue_t fixtureBackgroundQueue;
static dispatch_queue_t FixtureGlobalQueue(intptr_t identifier, uintptr_t flags) {
    (void)identifier; (void)flags;
    return fixtureBackgroundQueue;
}
static void Settle(void) {
    for (int i = 0; i < 3; i++) {
        dispatch_sync(fixtureBackgroundQueue, ^{});
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.02, false);
    }
}

@interface FixtureControl : NSObject
- (NSString *)stringValue;
- (NSInteger)selectedRow;
@end
@implementation FixtureControl
- (NSString *)stringValue { return @""; }
- (NSInteger)selectedRow { return 0; }
@end
@interface FixtureMenu : NSObject
- (NSInteger)indexOfItem:(id)item;
@end
@implementation FixtureMenu
- (NSInteger)indexOfItem:(id)item { (void)item; return 0; }
@end
@interface FixtureMenuItem : NSObject {
    FixtureMenu *fixtureMenu;
}
- (id)menu;
@end
@implementation FixtureMenuItem
- (id)menu { if (!fixtureMenu) fixtureMenu = [[FixtureMenu alloc] init]; return fixtureMenu; }
@end

// The AppController image paste and capture methods, verbatim, on a harness with
// the same instance variable names. Unrelated UI methods are recorded stubs.
#define NSPasteboard FixtureForbiddenRealPasteboard
#define NSWorkspace FixtureWorkspace
#define NSURLSession FixtureURLSession
#define NSURLSessionConfiguration FixtureURLSessionConfiguration
#define dispatch_get_global_queue FixtureGlobalQueue
@interface ImageHarness : NSObject {
@public
    FixturePasteboard *jcPasteboard;
    NSNumber *pbCount;
    NSNumber *pbBlockCount;
    FlycutOperator *flycutOperator;
    FixtureControl *searchBox;
    FixtureControl *searchWindowSearchField;
    FixtureControl *searchWindowTableView;
    NSArray *searchResults;
    NSMutableArray *scheduled;   // selectors passed to -performSelector:withObject:afterDelay:
    NSMutableArray *calls;       // stubbed UI methods that ran
}
@end
@implementation ImageHarness
#include "AppControllerImageMethods.inc"
- (void)performSelector:(SEL)selector withObject:(id)object afterDelay:(NSTimeInterval)delay {
    (void)object; (void)delay;
    [scheduled addObject:NSStringFromSelector(selector)];
}
- (void)hideApp { [calls addObject:@"hideApp"]; }
- (void)fakeCommandV { [calls addObject:@"fakeCommandV"]; }
- (void)restoreStashedStoreAndUpdate { [calls addObject:@"restoreStashedStoreAndUpdate"]; }
- (void)updateMenu { [calls addObject:@"updateMenu"]; }
- (void)hideSearchWindow { [calls addObject:@"hideSearchWindow"]; }
- (void)toggleMenuIconDisabled { [calls addObject:@"toggleMenuIconDisabled"]; }
@end
#undef NSPasteboard
#undef NSWorkspace
#undef NSURLSession
#undef NSURLSessionConfiguration
#undef dispatch_get_global_queue
#undef NSUserDefaults
#undef NSSearchPathForDirectoriesInDomains
#undef NSTemporaryDirectory

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------
static int clippingAddedCalls;
@interface SaveTarget : NSObject
- (void)savePreferencesOnDict:(NSMutableDictionary *)dictionary;
- (void)clippingAdded;
@end
@implementation SaveTarget
- (void)savePreferencesOnDict:(NSMutableDictionary *)dictionary { (void)dictionary; }
- (void)clippingAdded { clippingAddedCalls++; }
@end
static SaveTarget *saveTarget;

static FixtureDefaults *Defaults(void) { return [FixtureDefaults standardUserDefaults]; }
static NSString *ImagesDirectory(void) { return RootPath(@"Library/Application Support/Flycut/Images"); }

static NSArray *FilesUnder(NSString *directory) {
    NSMutableArray *files = [NSMutableArray array];
    NSDirectoryEnumerator *enumerator = [[NSFileManager defaultManager] enumeratorAtPath:directory];
    for (NSString *relative in enumerator) {
        if ([[[enumerator fileAttributes] fileType] isEqualToString:NSFileTypeRegular])
            [files addObject:relative];
    }
    return files;
}
// Every regular file in the fixture root except the defaults double's own file.
static NSArray *DataFilesUnderRoot(void) {
    NSMutableArray *files = [[FilesUnder(fixtureRoot) mutableCopy] autorelease];
    [files removeObject:@"defaults.plist"];
    return files;
}
static NSString *Describe(NSArray *files) { return [files componentsJoinedByString:@", "]; }

static NSData *PNGData(unsigned char red, unsigned char green, unsigned char blue) {
    NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:2 pixelsHigh:2
        bitsPerSample:8 samplesPerPixel:3 hasAlpha:NO isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace
        bytesPerRow:0 bitsPerPixel:0];
    unsigned char *pixels = [rep bitmapData];
    for (NSInteger i = 0; i < [rep bytesPerRow] * 2; i += 3) {
        pixels[i] = red; pixels[i + 1] = green; pixels[i + 2] = blue;
    }
    NSData *png = [rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    [rep release];
    return png;
}
static NSData *AnimatedGIFData(void) {
    NSMutableData *gif = [NSMutableData data];
    CGImageDestinationRef destination = CGImageDestinationCreateWithData((CFMutableDataRef)gif, CFSTR("com.compuserve.gif"), 2, NULL);
    for (int frame = 0; frame < 2; frame++) {
        NSBitmapImageRep *rep = [NSBitmapImageRep imageRepWithData:PNGData(frame ? 255 : 0, 0, frame ? 0 : 255)];
        CGImageDestinationAddImage(destination, [rep CGImage], NULL);
    }
    BOOL ok = CGImageDestinationFinalize(destination);
    CFRelease(destination);
    return ok ? gif : nil;
}

static FlycutOperator *NewOperator(void) {
    FlycutOperator *op = [[FlycutOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:saveTarget];
    return [op autorelease];
}
static BOOL AddImage(FlycutOperator *op, NSData *data, NSString *type) {
    return [op addImageClipping:data fromApp:@"Fixture" withAppBundleURL:nil imageType:type
                         target:saveTarget clippingAddedSelector:@selector(clippingAdded)];
}
static NSString *HashOf(NSData *data) { return [[FlycutImageStore sharedStore] hashForData:data]; }

static ImageHarness *NewHarness(FlycutOperator *op) {
    ImageHarness *harness = [[[ImageHarness alloc] init] autorelease];
    harness->jcPasteboard = [[FixturePasteboard alloc] init];
    harness->pbCount = [@0 retain];
    harness->pbBlockCount = [@0 retain];
    harness->flycutOperator = [op retain];
    harness->searchBox = [[FixtureControl alloc] init];
    harness->searchWindowSearchField = [[FixtureControl alloc] init];
    harness->searchWindowTableView = [[FixtureControl alloc] init];
    harness->scheduled = [[NSMutableArray alloc] init];
    harness->calls = [[NSMutableArray alloc] init];
    return harness;
}
static NSString *PastedFilePath(ImageHarness *harness) {
    NSArray *objects = harness->jcPasteboard->writtenObjects;
    if ([objects count] != 1 || ![[objects firstObject] isKindOfClass:[NSURL class]]) return nil;
    return [[objects firstObject] path];
}

// ---------------------------------------------------------------------------
// Cases.
// ---------------------------------------------------------------------------

// Save: Never must keep captured image bytes off the disk.
static void CaseNeverCaptureIsMemoryOnly(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(10, 20, 30);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image clipping is captured with Save: Never");
    CHECK([op jcListCount] == 1, "captured image is listed");
    NSString *hash = [[op clippingAtStackPosition] imageHash];
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:hash] isEqualToData:png], "captured bytes stay readable for display and paste");
    NSArray *files = DataFilesUnderRoot();
    if ([files count]) fprintf(stderr, "files written with Save: Never: %s\n", [Describe(files) UTF8String]);
    CHECK([files count] == 0, "Save: Never wrote image contents to disk");
}

// Terminating with Save: Never leaves no image file behind, including images that
// were stored while saving was still enabled and temporary copies made for a paste.
static void CaseNeverTerminateLeavesNoImageFiles(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    CHECK(AddImage(op, PNGData(200, 0, 0), NSPasteboardTypePNG), "image stored while saving is enabled");
    CHECK([FilesUnder(ImagesDirectory()) count] == 1, "saving enabled stores the image file");

    [Defaults() setInteger:0 forKey:@"savePreference"];
    CHECK(AddImage(op, PNGData(0, 200, 0), NSPasteboardTypePNG), "image captured after switching to Save: Never");
    NSData *gif = AnimatedGIFData();
    CHECK(gif != nil, "fixture GIF encodes");
    CHECK(AddImage(op, gif, @"com.compuserve.gif"), "GIF captured with Save: Never");
    ImageHarness *harness = NewHarness(op);
    [harness addImageClipToPasteboard:[op clippingAtStackPosition]];
    CHECK(PastedFilePath(harness) != nil, "GIF is offered as a file reference");

    [op applicationWillTerminate];
    CHECK([[Defaults() dictionaryForKey:@"store"] count] == 0, "Save: Never clears the saved store on exit");
    NSArray *files = DataFilesUnderRoot();
    if ([files count]) fprintf(stderr, "files left after terminate: %s\n", [Describe(files) UTF8String]);
    CHECK([files count] == 0, "terminate with Save: Never left image files on disk");
}

// A GIF paste needs a file. With Save: Never that file is a temporary copy outside
// the persistent store, removed again when the clipping is deleted.
static void CaseNeverGIFPasteUsesTemporaryCopy(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *gif = AnimatedGIFData();
    CHECK(AddImage(op, gif, @"com.compuserve.gif"), "GIF captured with Save: Never");
    ImageHarness *harness = NewHarness(op);
    [harness addImageClipToPasteboard:[op clippingAtStackPosition]];
    NSString *path = PastedFilePath(harness);
    CHECK(path != nil, "GIF is offered as a file reference");
    CHECK([path hasPrefix:[RootPath(@"tmp") stringByAppendingString:@"/"]], "GIF file reference is a temporary copy");
    CHECK(![path hasPrefix:ImagesDirectory()], "GIF file reference must not be the persistent image store");
    CHECK([[NSData dataWithContentsOfFile:path] isEqualToData:gif], "temporary copy holds the GIF bytes");

    CHECK([op clearItemAtStackPosition], "clipping deleted");
    NSArray *files = DataFilesUnderRoot();
    if ([files count]) fprintf(stderr, "files left after delete: %s\n", [Describe(files) UTF8String]);
    CHECK([files count] == 0, "deleting the clipping removes its temporary copy");
}

// Clear All with Save: Never forgets the bytes and leaves nothing on disk.
static void CaseNeverClearAllForgetsImages(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *first = PNGData(1, 2, 3), *second = PNGData(4, 5, 6);
    CHECK(AddImage(op, first, NSPasteboardTypePNG) && AddImage(op, second, NSPasteboardTypePNG), "images captured");
    CHECK([DataFilesUnderRoot() count] == 0, "Save: Never wrote image contents to disk");
    [op clearList];
    CHECK([op jcListCount] == 0, "list cleared");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(first)] &&
          ![[FlycutImageStore sharedStore] hasImageForHash:HashOf(second)], "Clear All forgets the image bytes");
    CHECK([DataFilesUnderRoot() count] == 0, "Clear All leaves no image files");
}

// Quitting with Save: Never removes only the store's own content-addressed files
// (64 lowercase hex digits). Anything else in the image folder is left alone.
static void CaseNeverTerminateKeepsOtherFiles(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(40, 50, 60);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image stored while saving is enabled");
    NSString *hashFile = [HashOf(png) stringByAppendingPathExtension:@"png"];
    // Same length as a hash but not hex, and one digit short (the volume may be case-insensitive,
    // so an upper-case variant would be the stored file itself).
    NSArray *others = @[@"notes.txt", @"cafe.png",
                        [[@"g" stringByAppendingString:[HashOf(png) substringFromIndex:1]] stringByAppendingPathExtension:@"png"],
                        [[HashOf(png) substringFromIndex:1] stringByAppendingPathExtension:@"png"]];
    for (NSString *name in others)
        CHECK([[NSData dataWithBytes:"x" length:1] writeToFile:[ImagesDirectory() stringByAppendingPathComponent:name] atomically:NO], "other file written");

    [Defaults() setInteger:0 forKey:@"savePreference"];
    [op applicationWillTerminate];
    NSArray *left = FilesUnder(ImagesDirectory());
    CHECK(![left containsObject:hashFile], "the stored image file is removed on exit");
    for (NSString *name in others)
        CHECK([left containsObject:name], "a file that is not a stored image is kept on exit");
    if ([left count] != [others count]) fprintf(stderr, "image folder after terminate: %s\n", [Describe(left) UTF8String]);
    CHECK([left count] == [others count], "only the stored image file is removed");
}

// With "save on every change" (savePreference 2), the next list change writes the
// images that were kept in memory while history was not saved.
static void CaseNeverThenSavingOnChangePersists(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(70, 80, 90);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image captured with Save: Never");
    CHECK([FilesUnder(ImagesDirectory()) count] == 0, "Save: Never wrote image contents to disk");
    [Defaults() setInteger:2 forKey:@"savePreference"];
    CHECK([op addClipping:@"text" ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil
                   target:saveTarget clippingAddedSelector:@selector(clippingAdded)], "text clipping added");
    NSArray *stored = FilesUnder(ImagesDirectory());
    CHECK([stored isEqualToArray:@[[HashOf(png) stringByAppendingPathExtension:@"png"]]], "the next list change writes the memory-only image");
    CHECK([[[Defaults() dictionaryForKey:@"store"] objectForKey:@"jcList"] count] == 2, "the list change saved the history");
}

// Behaviour with saving enabled is unchanged: files in the persistent store, kept on
// exit, and GIFs pasted as a reference to that file.
static void CaseSavingEnabledKeepsPersistentFiles(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(7, 8, 9);
    NSData *gif = AnimatedGIFData();
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "PNG captured");
    CHECK(AddImage(op, gif, @"com.compuserve.gif"), "GIF captured");
    NSString *pngFile = [HashOf(png) stringByAppendingPathExtension:@"png"];
    NSString *gifFile = [HashOf(gif) stringByAppendingPathExtension:@"gif"];
    NSArray *stored = FilesUnder(ImagesDirectory());
    CHECK([stored containsObject:pngFile] && [stored containsObject:gifFile] && [stored count] == 2, "images stored in the persistent store");

    ImageHarness *harness = NewHarness(op);
    [harness addImageClipToPasteboard:[op clippingAtStackPosition]];
    CHECK([PastedFilePath(harness) isEqualToString:[ImagesDirectory() stringByAppendingPathComponent:gifFile]], "GIF pasted as the persistent file");

    [op applicationWillTerminate];
    NSArray *saved = [[Defaults() dictionaryForKey:@"store"] objectForKey:@"jcList"];
    CHECK([saved count] == 2, "store saved on exit");
    stored = FilesUnder(ImagesDirectory());
    CHECK([stored containsObject:pngFile] && [stored containsObject:gifFile], "saving enabled keeps image files on exit");
    CHECK([DataFilesUnderRoot() count] == 2, "no extra files besides the stored images");
}

// Images captured under Save: Never are written when the user enables saving before
// exit, so the saved history can restore them after a relaunch (two processes).
static void CaseNeverThenSavingPersistsOnExit(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(90, 91, 92);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image captured with Save: Never");
    [Defaults() setInteger:1 forKey:@"savePreference"];
    [op applicationWillTerminate];
    NSArray *stored = FilesUnder(ImagesDirectory());
    CHECK([stored isEqualToArray:@[[HashOf(png) stringByAppendingPathExtension:@"png"]]], "enabling saving writes the image on exit");
    CHECK([DataFilesUnderRoot() count] == 1, "only the stored image remains");
    [png writeToFile:RootPath(@"expected.png") atomically:YES];
}
static void CaseNeverThenSavingRestoresAfterRelaunch(void) {
    NSData *png = [NSData dataWithContentsOfFile:RootPath(@"expected.png")];
    CHECK(png != nil, "first phase recorded the image");
    CHECK([Defaults() integerForKey:@"savePreference"] == 1, "saving preference survived the relaunch");
    FlycutOperator *op = NewOperator();
    CHECK([op jcListCount] == 1, "saved image clipping restored after relaunch");
    FlycutClipping *clipping = [op clippingAtStackPosition];
    CHECK([clipping isImageClipping], "restored clipping is an image");
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:[clipping imageHash]] isEqualToData:png], "restored image bytes match");
}

// Temporary copies left by a process that no longer exists are removed at launch,
// before any image is copied: -awakeFromNib starts the operator and then creates
// the image store (checked in the source by the Python test). A copy owned by a
// live process is kept.
static void CaseStaleTemporaryCopiesRemovedAtStart(void) {
    NSFileManager *fm = [NSFileManager defaultManager];
    NSString *stale = RootPath(@"tmp/Flycut-Images-99999999");
    NSString *live = RootPath([NSString stringWithFormat:@"tmp/Flycut-Images-%d", getpid()]);
    for (NSString *directory in @[stale, live]) {
        CHECK([fm createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil], "fixture directory created");
        CHECK([[NSData dataWithBytes:"GIF89a" length:6] writeToFile:[directory stringByAppendingPathComponent:@"x.gif"] atomically:NO], "fixture copy written");
    }
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    [FlycutImageStore sharedStore]; // the launch step of -awakeFromNib
    CHECK(![fm fileExistsAtPath:stale], "temporary copies of an exited process are removed at launch, before any image is copied");
    CHECK([fm fileExistsAtPath:[live stringByAppendingPathComponent:@"x.gif"]], "temporary copies of a live process are kept at launch");
    CHECK(AddImage(op, PNGData(3, 3, 3), NSPasteboardTypePNG), "image captured");
    CHECK([fm fileExistsAtPath:[live stringByAppendingPathComponent:@"x.gif"]], "temporary copies of a live process are kept");
}

static BOOL AddText(FlycutOperator *op, NSString *text) {
    return [op addClipping:text ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil
                    target:saveTarget clippingAddedSelector:@selector(clippingAdded)];
}

// PR3-1: while Favorites is shown, deleting a favorite must not release image bytes
// that the (stashed) main history still references.
static void FavoriteDeleteKeepsMainHistoryImage(NSInteger savePreference) {
    [Defaults() setInteger:savePreference forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(40, 50, 60);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image captured");
    CHECK([op saveFromStackToFavorites], "image moved to Favorites");
    CHECK(AddText(op, @"text"), "text captured");
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "same image copied again into the main history");
    [op toggleToFromFavoritesStore];
    CHECK([op favoritesStoreIsSelected], "Favorites shown");
    CHECK([[[op clippingAtStackPosition] imageHash] isEqualToString:HashOf(png)], "selected favorite is the image");
    CHECK([op clearItemAtStackPosition], "favorite deleted");
    [op toggleToFromFavoritesStore];
    CHECK(![op favoritesStoreIsSelected] && [op jcListCount] == 2, "main history shown again");
    FlycutClipping *mainClipping = [op clippingAtStackPosition];
    CHECK([mainClipping isImageClipping], "main history still lists the image");
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:[mainClipping imageHash]] isEqualToData:png],
          "deleting the favorite released the bytes of the main history image");
}
static void CaseFavoriteDeleteKeepsMainImageSaved(void) { FavoriteDeleteKeepsMainHistoryImage(1); }
static void CaseFavoriteDeleteKeepsMainImageNever(void) { FavoriteDeleteKeepsMainHistoryImage(0); }

// PR3-6: Clear All must release an image that is listed more than once.
static void ClearAllReleasesDuplicates(NSInteger savePreference) {
    [Defaults() setInteger:savePreference forKey:@"savePreference"];
    [Defaults() setBool:NO forKey:@"removeDuplicates"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(70, 80, 90);
    CHECK(AddImage(op, png, NSPasteboardTypePNG) && AddText(op, @"between") && AddImage(op, png, NSPasteboardTypePNG),
          "duplicate image clippings captured");
    CHECK([op jcListCount] == 3, "both duplicates listed");
    [op clearList];
    CHECK([op jcListCount] == 0, "list cleared");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(png)], "Clear All kept the bytes of a duplicated image");
    NSArray *files = DataFilesUnderRoot();
    if ([files count]) fprintf(stderr, "files left after Clear All: %s\n", [Describe(files) UTF8String]);
    CHECK([files count] == 0, "Clear All left image files on disk");
}
static void CaseClearAllDuplicatesSaved(void) { ClearAllReleasesDuplicates(1); }
static void CaseClearAllDuplicatesNever(void) { ClearAllReleasesDuplicates(0); }

// PR3-2: an image evicted from a full history is exported by "save forgotten
// clippings" before its bytes are released.
static void EvictedImageIsAutosaved(NSInteger savePreference) {
    [Defaults() setInteger:savePreference forKey:@"savePreference"];
    [Defaults() setInteger:1 forKey:@"rememberNum"];
    [Defaults() setBool:YES forKey:@"saveForgottenClippings"];
    [Defaults() setURL:[NSURL fileURLWithPath:RootPath(@"Autosave")] forKey:@"autoSaveToLocation"];
    FlycutOperator *op = NewOperator();
    NSData *evicted = PNGData(11, 12, 13), *kept = PNGData(14, 15, 16);
    CHECK(AddImage(op, evicted, NSPasteboardTypePNG) && AddImage(op, kept, NSPasteboardTypePNG), "two images captured");
    CHECK([op jcListCount] == 1, "history remembers one clipping");
    NSArray *exports = FilesUnder(RootPath(@"Autosave"));
    fprintf(stderr, "forgotten-clipping exports: [%s]\n", [Describe(exports) UTF8String]);
    CHECK([exports count] == 1, "evicted image was not exported");
    NSString *export = [RootPath(@"Autosave") stringByAppendingPathComponent:[exports firstObject] ?: @"missing"];
    CHECK([[export pathExtension] isEqualToString:@"png"], "export keeps the image file type");
    CHECK([[NSData dataWithContentsOfFile:export] isEqualToData:evicted], "export holds the evicted image bytes");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(evicted)], "evicted image bytes released after the export");
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:HashOf(kept)] isEqualToData:kept], "remembered image kept");
}
static void CaseEvictedImageAutosavedSaved(void) { EvictedImageIsAutosaved(1); }
static void CaseEvictedImageAutosavedNever(void) { EvictedImageIsAutosaved(0); }

// PR3-2: saving a clipping to a file reports a failed write, so "save and delete"
// does not delete a clipping that was not saved.
static void CaseSaveReportsWriteFailure(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    NSFileManager *fm = [NSFileManager defaultManager];
    // A regular file where the save directory should be makes every write fail
    // (ENOTDIR), independent of permissions and inherited ACLs.
    NSString *notADirectory = RootPath(@"NotADirectory"), *writable = RootPath(@"Writable");
    CHECK([[NSData dataWithBytes:"x" length:1] writeToFile:notADirectory atomically:NO] &&
          [fm createDirectoryAtPath:writable withIntermediateDirectories:YES attributes:nil error:nil], "fixture paths");
    [Defaults() setURL:[NSURL fileURLWithPath:notADirectory] forKey:@"saveToLocation"];
    FlycutOperator *op = NewOperator();
    CHECK(AddText(op, @"text to save"), "text captured");
    CHECK(![op saveFromStack], "a failed text export was reported as saved");
    CHECK(AddImage(op, PNGData(17, 18, 19), NSPasteboardTypePNG), "image captured");
    CHECK(![op saveFromStack], "a failed image export was reported as saved");

    [Defaults() setURL:[NSURL fileURLWithPath:writable] forKey:@"saveToLocation"];
    CHECK([op saveFromStack], "image export to a writable directory succeeds");
    CHECK([FilesUnder(writable) count] == 1, "image exported once");
}

// PR3-5: an image whose bytes could not be stored is not reported as a clipping.
static void CaseFailedImageWriteIsNotCaptured(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    // A regular file where the image directory should be makes every image write fail.
    NSString *flycutDirectory = [ImagesDirectory() stringByDeletingLastPathComponent];
    CHECK([[NSFileManager defaultManager] createDirectoryAtPath:flycutDirectory withIntermediateDirectories:YES attributes:nil error:nil] &&
          [[NSData dataWithBytes:"x" length:1] writeToFile:ImagesDirectory() atomically:NO], "fixture paths");
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(21, 22, 23);
    clippingAddedCalls = 0;
    CHECK(!AddImage(op, png, NSPasteboardTypePNG), "an image that could not be stored was reported as captured");
    CHECK([op jcListCount] == 0, "an image that could not be stored was listed");
    CHECK(clippingAddedCalls == 0, "an image that could not be stored triggered a menu update");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(png)], "no bytes for the rejected image");
}

// PR3-5: bytes that do not decode as an image are not captured.
static void UndecodableBytesAreNotCaptured(NSInteger savePreference) {
    [Defaults() setInteger:savePreference forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    NSData *junk = [@"these bytes are not an image" dataUsingEncoding:NSUTF8StringEncoding];
    clippingAddedCalls = 0;
    CHECK(!AddImage(op, junk, NSPasteboardTypePNG), "undecodable bytes were reported as an image clipping");
    CHECK([op jcListCount] == 0 && clippingAddedCalls == 0, "undecodable bytes were listed as an image");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(junk)], "undecodable bytes were stored");
    CHECK([DataFilesUnderRoot() count] == 0, "undecodable bytes were written to disk");
}
static void CaseUndecodableBytesNotCapturedSaved(void) { UndecodableBytesAreNotCaptured(1); }
static void CaseUndecodableBytesNotCapturedNever(void) { UndecodableBytesAreNotCaptured(0); }

// PR3-5: when an image cannot be placed on the clipboard, no Paste keystroke is
// synthesized, because it would paste whatever the clipboard held before.
static void CaseLostImageBytesAreNotPasted(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    [Defaults() setBool:YES forKey:@"menuSelectionPastes"];
    FlycutOperator *op = NewOperator();
    NSData *png = PNGData(24, 25, 26);
    CHECK(AddImage(op, png, NSPasteboardTypePNG), "image captured");
    ImageHarness *harness = NewHarness(op);
    FixtureMenuItem *menuItem = [[[FixtureMenuItem alloc] init] autorelease];
    harness->searchResults = [@[@"[Image]"] retain];

    // Control: with its bytes available the image is placed and pasted on every path.
    [harness pasteFromStack];
    CHECK([harness->scheduled containsObject:@"fakeCommandV"], "control: bezel pastes a stored image");
    CHECK([[harness->jcPasteboard dataForType:NSPasteboardTypePNG] isEqualToData:png], "control: image placed on the clipboard");
    [harness->scheduled removeAllObjects];
    [harness processMenuClippingSelection:menuItem];
    CHECK([harness->scheduled containsObject:@"fakeCommandV"], "control: menu selection pastes a stored image");
    [harness->scheduled removeAllObjects];
    [harness searchWindowItemSelected:nil];
    CHECK([harness->scheduled containsObject:@"fakeCommandV"], "control: search window pastes a stored image");

    // The stored file disappears behind Flycut's back.
    NSString *stored = [ImagesDirectory() stringByAppendingPathComponent:[HashOf(png) stringByAppendingPathExtension:@"png"]];
    CHECK([[NSFileManager defaultManager] removeItemAtPath:stored error:nil], "stored image file removed");
    [harness->jcPasteboard fixtureCopyTypes:@[NSPasteboardTypeString] data:@{NSPasteboardTypeString: [@"previous clipboard" dataUsingEncoding:NSUTF8StringEncoding]}];
    NSInteger generation = [harness->jcPasteboard changeCount];

    [harness->scheduled removeAllObjects];
    [harness pasteFromStack];
    CHECK(![harness->scheduled containsObject:@"fakeCommandV"], "bezel synthesized Paste for an image that could not be placed");
    CHECK([harness->scheduled containsObject:@"hideApp"], "bezel still closes");
    [harness->scheduled removeAllObjects];
    [harness processMenuClippingSelection:menuItem];
    CHECK(![harness->scheduled containsObject:@"fakeCommandV"], "menu synthesized Paste for an image that could not be placed");
    [harness->scheduled removeAllObjects];
    [harness searchWindowItemSelected:nil];
    CHECK(![harness->scheduled containsObject:@"fakeCommandV"], "search window synthesized Paste for an image that could not be placed");
    CHECK([harness->jcPasteboard changeCount] == generation, "the previous clipboard was left untouched");
}

// PR3-5: a pasteboard that refuses the image write does not get a Paste keystroke.
static void CaseRefusedPasteboardWriteIsNotPasted(void) {
    [Defaults() setInteger:1 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    CHECK(AddImage(op, PNGData(27, 28, 29), NSPasteboardTypePNG) && AddImage(op, AnimatedGIFData(), @"com.compuserve.gif"), "images captured");
    ImageHarness *harness = NewHarness(op);
    harness->jcPasteboard->failWrites = YES;
    [harness pasteFromStack];
    CHECK(![harness->scheduled containsObject:@"fakeCommandV"], "GIF file reference was refused but Paste was synthesized");
    CHECK([op setStackPositionTo:1], "PNG selected");
    [harness->scheduled removeAllObjects];
    [harness pasteFromStack];
    CHECK(![harness->scheduled containsObject:@"fakeCommandV"], "image data was refused but Paste was synthesized");
}

// PR3-4: capture reads the clipboard on a background queue. Only bytes of the
// generation whose types passed the privacy check may be committed.
static ImageHarness *PollingHarness(FlycutOperator *op) {
    [Defaults() setBool:YES forKey:@"captureImages"];
    ImageHarness *harness = NewHarness(op);
    [harness->pbCount release];
    harness->pbCount = [@([harness->jcPasteboard changeCount]) retain];
    return harness;
}
static void CaseImageCaptureControl(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    ImageHarness *harness = PollingHarness(op);
    NSData *png = PNGData(31, 32, 33);
    [harness->jcPasteboard fixtureCopyTypes:@[NSPasteboardTypePNG] data:@{NSPasteboardTypePNG: png}];
    [harness pollPB:nil];
    Settle();
    CHECK([op jcListCount] == 1, "control: copied image captured");
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:[[op clippingAtStackPosition] imageHash]] isEqualToData:png], "control: captured bytes");
    [harness->jcPasteboard fixtureCopyTypes:@[NSPasteboardTypePNG, @"org.nspasteboard.ConcealedType"] data:@{NSPasteboardTypePNG: PNGData(34, 35, 36)}];
    [harness pollPB:nil];
    Settle();
    CHECK([op jcListCount] == 1, "control: concealed image skipped");
}
static void CaseImageReplacedBeforeReadIsDropped(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    ImageHarness *harness = PollingHarness(op);
    NSData *visible = PNGData(41, 42, 43), *concealed = PNGData(44, 45, 46);
    FixturePasteboard *pasteboard = harness->jcPasteboard;
    [pasteboard fixtureCopyTypes:@[NSPasteboardTypePNG] data:@{NSPasteboardTypePNG: visible}];
    // A password manager copies a concealed image after the type check, before the read.
    pasteboard->replaceOnReadOfType = [NSPasteboardTypePNG retain];
    pasteboard->replacementTypes = [@[NSPasteboardTypePNG, @"org.nspasteboard.ConcealedType"] retain];
    pasteboard->replacementData = [@{NSPasteboardTypePNG: concealed} retain];
    [harness pollPB:nil];
    Settle();
    CHECK(pasteboard->replaceOnReadOfType == nil, "the image was read after the replacement");
    CHECK(![[FlycutImageStore sharedStore] hasImageForHash:HashOf(concealed)], "bytes of a concealed clipboard generation were captured");
    CHECK([op jcListCount] == 0, "an image read from a later clipboard generation was captured");
}

static NSData *GIFDownloadPage(void) {
    return [@"<html><img src=\"https://example.test/animated.gif\"></html>" dataUsingEncoding:NSUTF8StringEncoding];
}
static ImageHarness *StartGIFDownload(FlycutOperator *op) {
    [Defaults() setBool:YES forKey:@"downloadAnimatedGIFs"];
    ImageHarness *harness = PollingHarness(op);
    [harness->jcPasteboard fixtureCopyTypes:@[NSPasteboardTypeTIFF, @"public.html"]
                                       data:@{NSPasteboardTypeTIFF: PNGData(1, 1, 1), @"public.html": GIFDownloadPage()}];
    [harness pollPB:nil];
    Settle();
    CHECK(downloadRequests == 1 && pendingDownload != nil, "animated GIF download requested (no network: session double)");
    CHECK([[pendingDownloadURL absoluteString] isEqualToString:@"https://example.test/animated.gif"], "download URL from the copied HTML");
    CHECK([op jcListCount] == 0, "the still image is not captured while the GIF downloads");
    return harness;
}
static void FinishGIFDownload(NSData *gif) {
    NSHTTPURLResponse *response = [[[NSHTTPURLResponse alloc] initWithURL:pendingDownloadURL statusCode:200
                                                              HTTPVersion:@"HTTP/1.1" headerFields:@{}] autorelease];
    FixtureCompletion handler = pendingDownload;
    dispatch_async(fixtureBackgroundQueue, ^{ handler(gif, response, nil); });
    Settle();
}
static void CaseGIFDownloadControl(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    StartGIFDownload(op);
    NSData *gif = AnimatedGIFData();
    FinishGIFDownload(gif);
    CHECK([op jcListCount] == 1 && [[[op clippingAtStackPosition] type] isEqualToString:@"com.compuserve.gif"], "control: downloaded GIF captured");
    CHECK([[[FlycutImageStore sharedStore] imageDataForHash:[[op clippingAtStackPosition] imageHash]] isEqualToData:gif], "control: GIF bytes");
}
static void CaseGIFDownloadAfterClipboardChangeIsDropped(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    ImageHarness *harness = StartGIFDownload(op);
    [harness->jcPasteboard fixtureCopyTypes:@[NSPasteboardTypeString] data:@{NSPasteboardTypeString: [@"newer copy" dataUsingEncoding:NSUTF8StringEncoding]}];
    FinishGIFDownload(AnimatedGIFData());
    CHECK([op jcListCount] == 0, "a GIF download finishing after the clipboard changed was captured");
}
static void CaseGIFDownloadAfterCapturePausedIsDropped(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    StartGIFDownload(op);
    [op setDisableStoreTo:YES];
    FinishGIFDownload(AnimatedGIFData());
    CHECK([op jcListCount] == 0, "a GIF download finishing after capture was paused was captured");
}
static void CaseGIFDownloadAfterImageCaptureOffIsDropped(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    StartGIFDownload(op);
    [Defaults() setBool:NO forKey:@"captureImages"];
    FinishGIFDownload(AnimatedGIFData());
    CHECK([op jcListCount] == 0, "a GIF download finishing after image capture was turned off was captured");
}
static void CaseGIFDownloadAfterDownloadsOffIsDropped(void) {
    [Defaults() setInteger:0 forKey:@"savePreference"];
    FlycutOperator *op = NewOperator();
    StartGIFDownload(op);
    [Defaults() setBool:NO forKey:@"downloadAnimatedGIFs"];
    FinishGIFDownload(AnimatedGIFData());
    CHECK([op jcListCount] == 0, "a GIF download finishing after GIF downloads were turned off was captured");
}

// Guard self-tests: the containment guard must stop writes and deletes outside the
// fixture root. The probe targets are harmless even if the guard failed.
static void CaseGuardStopsOutsideWrite(void) {
    [[NSData dataWithBytes:"x" length:1] writeToFile:@"/dev/null" atomically:NO];
    fprintf(stderr, "guard did not stop an outside write\n");
    failures++;
}
static void CaseGuardStopsOutsideDelete(void) {
    [[NSFileManager defaultManager] removeItemAtPath:@"/nonexistent-flycut-containment-probe" error:nil];
    fprintf(stderr, "guard did not stop an outside delete\n");
    failures++;
}

typedef struct { const char *name; void (*run)(void); } Case;
static const Case cases[] = {
    {"never-capture-memory-only", CaseNeverCaptureIsMemoryOnly},
    {"never-terminate-no-files", CaseNeverTerminateLeavesNoImageFiles},
    {"never-gif-temporary-copy", CaseNeverGIFPasteUsesTemporaryCopy},
    {"never-clear-all", CaseNeverClearAllForgetsImages},
    {"never-terminate-keeps-other-files", CaseNeverTerminateKeepsOtherFiles},
    {"never-then-saving-on-change", CaseNeverThenSavingOnChangePersists},
    {"saving-enabled-unchanged", CaseSavingEnabledKeepsPersistentFiles},
    {"never-then-saving-exit", CaseNeverThenSavingPersistsOnExit},
    {"never-then-saving-relaunch", CaseNeverThenSavingRestoresAfterRelaunch},
    {"stale-temporary-copies", CaseStaleTemporaryCopiesRemovedAtStart},
    {"favorite-delete-main-image-saved", CaseFavoriteDeleteKeepsMainImageSaved},
    {"favorite-delete-main-image-never", CaseFavoriteDeleteKeepsMainImageNever},
    {"clear-all-duplicates-saved", CaseClearAllDuplicatesSaved},
    {"clear-all-duplicates-never", CaseClearAllDuplicatesNever},
    {"evicted-image-autosaved-saved", CaseEvictedImageAutosavedSaved},
    {"evicted-image-autosaved-never", CaseEvictedImageAutosavedNever},
    {"save-reports-write-failure", CaseSaveReportsWriteFailure},
    {"failed-image-write-not-captured", CaseFailedImageWriteIsNotCaptured},
    {"undecodable-bytes-not-captured-saved", CaseUndecodableBytesNotCapturedSaved},
    {"undecodable-bytes-not-captured-never", CaseUndecodableBytesNotCapturedNever},
    {"lost-image-not-pasted", CaseLostImageBytesAreNotPasted},
    {"refused-pasteboard-write-not-pasted", CaseRefusedPasteboardWriteIsNotPasted},
    {"image-capture-control", CaseImageCaptureControl},
    {"image-replaced-before-read", CaseImageReplacedBeforeReadIsDropped},
    {"gif-download-control", CaseGIFDownloadControl},
    {"gif-download-after-clipboard-change", CaseGIFDownloadAfterClipboardChangeIsDropped},
    {"gif-download-after-capture-paused", CaseGIFDownloadAfterCapturePausedIsDropped},
    {"gif-download-after-image-capture-off", CaseGIFDownloadAfterImageCaptureOffIsDropped},
    {"gif-download-after-downloads-off", CaseGIFDownloadAfterDownloadsOffIsDropped},
    {"guard-outside-write", CaseGuardStopsOutsideWrite},
    {"guard-outside-delete", CaseGuardStopsOutsideDelete},
};

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) { fprintf(stderr, "usage: %s <case> <fixture-root>\n", argv[0]); return 2; }
        fixtureRoot = [[[NSString stringWithUTF8String:argv[2]] stringByStandardizingPath] retain];
        if (![fixtureRoot isAbsolutePath] || [fixtureRoot length] < 8) return 2;
        InstallContainmentGuards();
        saveTarget = [[SaveTarget alloc] init];
        fixtureBackgroundQueue = dispatch_queue_create("fixture.background", DISPATCH_QUEUE_SERIAL);
        for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
            if (strcmp(argv[1], cases[i].name) == 0) {
                cases[i].run();
                if (failures) fprintf(stderr, "%d check(s) failed\n", failures);
                return failures ? 1 : 0;
            }
        }
        fprintf(stderr, "unknown case %s\n", argv[1]);
        return 2;
    }
}
