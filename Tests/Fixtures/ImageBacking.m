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
@interface FixturePasteboard : NSObject {
@public
    NSInteger changeCount;
    NSMutableArray *declaredTypes;
    NSMutableDictionary *dataByType;
    NSArray *writtenObjects;
    BOOL failWrites;
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
    @synchronized (self) { return [[[dataByType objectForKey:type] retain] autorelease]; }
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

// The AppController image paste methods, verbatim, on a harness with the same
// instance variable names. Unrelated UI methods are recorded stubs.
#define NSPasteboard FixtureForbiddenRealPasteboard
@interface ImageHarness : NSObject {
@public
    FixturePasteboard *jcPasteboard;
    NSNumber *pbCount;
    NSNumber *pbBlockCount;
    FlycutOperator *flycutOperator;
    NSMutableArray *scheduled;
}
@end
@implementation ImageHarness
#include "AppControllerImageMethods.inc"
- (void)performSelector:(SEL)selector withObject:(id)object afterDelay:(NSTimeInterval)delay {
    (void)object; (void)delay;
    [scheduled addObject:NSStringFromSelector(selector)];
}
@end
#undef NSPasteboard
#undef NSUserDefaults
#undef NSSearchPathForDirectoriesInDomains
#undef NSTemporaryDirectory

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------
@interface SaveTarget : NSObject
- (void)savePreferencesOnDict:(NSMutableDictionary *)dictionary;
- (void)clippingAdded;
@end
@implementation SaveTarget
- (void)savePreferencesOnDict:(NSMutableDictionary *)dictionary { (void)dictionary; }
- (void)clippingAdded {}
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
    harness->scheduled = [[NSMutableArray alloc] init];
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
