//
//  FlycutImageStore.m
//  Flycut
//
//  Storage for clipboard image clippings: files in Application Support, or,
//  while history is not saved (Save: Never), memory only.
//

#import "FlycutImageStore.h"
#import <errno.h>
#import <signal.h>
#import <unistd.h>

static FlycutImageStore *sharedInstance = nil;
static NSString *const ephemeralDirectoryPrefix = @"Flycut-Images-";

@implementation FlycutImageStore

+(FlycutImageStore *)sharedStore
{
    if (nil == sharedInstance) {
        sharedInstance = [[FlycutImageStore alloc] init];
    }
    return sharedInstance;
}

+(NSString *)fileExtensionForType:(NSString *)uti
{
    if ([uti isEqualToString:@"com.compuserve.gif"])
        return @"gif";
    if ([uti isEqualToString:@"public.png"])
        return @"png";
    if ([uti isEqualToString:@"public.jpeg"])
        return @"jpg";
    return @"tiff";
}

-(id)init
{
    self = [super init];
    if (self) {
        NSArray *paths = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES);
        NSString *appSupportDir = [paths firstObject];
        imagesDirectoryPath = [[appSupportDir stringByAppendingPathComponent:@"Flycut/Images"] retain];
        memoryImages = [[NSMutableDictionary alloc] init];
        memoryImageExtensions = [[NSMutableDictionary alloc] init];
        ephemeralDirectoryPath = [[NSTemporaryDirectory() stringByAppendingPathComponent:
                                   [NSString stringWithFormat:@"%@%d", ephemeralDirectoryPrefix, getpid()]] retain];
        [self removeStaleEphemeralDirectories];

        NSFileManager *fm = [NSFileManager defaultManager];
        if (![fm fileExistsAtPath:imagesDirectoryPath]) {
            [fm createDirectoryAtPath:imagesDirectoryPath
          withIntermediateDirectories:YES
                           attributes:nil
                                error:nil];
        }
    }
    return self;
}

// Temporary copies belong to the Flycut process named in their directory. Remove
// the ones a process left behind when it ended without cleaning up (e.g. a crash).
-(void)removeStaleEphemeralDirectories
{
    NSFileManager *fm = [NSFileManager defaultManager];
    NSString *parent = [ephemeralDirectoryPath stringByDeletingLastPathComponent];
    for (NSString *name in [fm contentsOfDirectoryAtPath:parent error:nil]) {
        if (![name hasPrefix:ephemeralDirectoryPrefix])
            continue;
        NSString *pidString = [name substringFromIndex:[ephemeralDirectoryPrefix length]];
        int pid = [pidString intValue];
        if (pid <= 0 || pid == getpid() || ![[NSString stringWithFormat:@"%d", pid] isEqualToString:pidString])
            continue;
        // Signal 0 only checks whether the process exists; nothing is sent.
        if (kill(pid, 0) == 0 || errno != ESRCH)
            continue;
        [fm removeItemAtPath:[parent stringByAppendingPathComponent:name] error:nil];
    }
}

-(NSString *)hashForData:(NSData *)data
{
    if (!data || [data length] == 0)
        return nil;

    unsigned char hash[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256([data bytes], (CC_LONG)[data length], hash);
    NSMutableString *hashString = [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++)
        [hashString appendFormat:@"%02x", hash[i]];
    return hashString;
}

-(NSString *)filePathForHash:(NSString *)hash extension:(NSString *)ext
{
    if (!ext || [ext length] == 0)
        ext = @"tiff";
    return [imagesDirectoryPath stringByAppendingPathComponent:
            [NSString stringWithFormat:@"%@.%@", hash, ext]];
}

// Resolves a hash to whatever extension it was actually stored under (e.g. .gif,
// .png, or legacy .tiff). Returns nil if no matching file exists.
-(NSString *)resolvedPathForHash:(NSString *)hash
{
    if (!hash)
        return nil;

    NSFileManager *fm = [NSFileManager defaultManager];
    NSString *prefix = [hash stringByAppendingString:@"."];
    for (NSString *file in [fm contentsOfDirectoryAtPath:imagesDirectoryPath error:nil]) {
        if ([file hasPrefix:prefix])
            return [imagesDirectoryPath stringByAppendingPathComponent:file];
    }
    return nil;
}

-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash
{
    return [self saveImageData:data forHash:hash extension:@"tiff"];
}

-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext
{
    if (!data || !hash)
        return NO;

    // Content-addressed: if any representation of this hash is already stored, keep it.
    if ([self resolvedPathForHash:hash])
        return YES;

    NSString *filePath = [self filePathForHash:hash extension:ext];
    if (![data writeToFile:filePath atomically:YES])
        return NO;
    // Now on disk; drop a memory-only copy captured while history was not saved.
    [memoryImages removeObjectForKey:hash];
    [memoryImageExtensions removeObjectForKey:hash];
    return YES;
}

-(BOOL)saveMemoryOnlyImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext
{
    if (!data || !hash)
        return NO;

    if ([memoryImages objectForKey:hash] || [self resolvedPathForHash:hash])
        return YES;

    [memoryImages setObject:[[data copy] autorelease] forKey:hash];
    [memoryImageExtensions setObject:(ext && [ext length] > 0 ? ext : @"tiff") forKey:hash];
    return YES;
}

-(void)persistMemoryOnlyImageForHash:(NSString *)hash
{
    NSData *data = hash ? [[[memoryImages objectForKey:hash] retain] autorelease] : nil;
    if (data)
        [self saveImageData:data forHash:hash extension:[memoryImageExtensions objectForKey:hash]];
}

-(NSData *)imageDataForHash:(NSString *)hash
{
    NSData *memoryData = hash ? [memoryImages objectForKey:hash] : nil;
    if (memoryData)
        return [[memoryData retain] autorelease];

    NSString *filePath = [self resolvedPathForHash:hash];
    if (!filePath)
        return nil;

    return [NSData dataWithContentsOfFile:filePath];
}

-(NSString *)imageFilePathForHash:(NSString *)hash
{
    NSString *filePath = [self resolvedPathForHash:hash];
    if (filePath)
        return filePath;
    return [self ephemeralCopyPathForHash:hash];
}

// File-reference pastes (animated GIFs) need a file. A memory-only image gets a
// temporary copy in this process's own directory instead of the image directory.
-(NSString *)ephemeralCopyPathForHash:(NSString *)hash
{
    NSData *data = hash ? [memoryImages objectForKey:hash] : nil;
    if (!data)
        return nil;

    NSString *path = [ephemeralDirectoryPath stringByAppendingPathComponent:
                      [NSString stringWithFormat:@"%@.%@", hash, [memoryImageExtensions objectForKey:hash]]];
    NSFileManager *fm = [NSFileManager defaultManager];
    if ([fm fileExistsAtPath:path])
        return path;
    if (![fm createDirectoryAtPath:ephemeralDirectoryPath
       withIntermediateDirectories:YES
                        attributes:@{NSFilePosixPermissions: @0700}
                             error:nil])
        return nil;
    return [data writeToFile:path atomically:YES] ? path : nil;
}

-(void)removeEphemeralCopiesForHash:(NSString *)hash
{
    NSFileManager *fm = [NSFileManager defaultManager];
    NSString *prefix = [hash stringByAppendingString:@"."];
    for (NSString *file in [fm contentsOfDirectoryAtPath:ephemeralDirectoryPath error:nil]) {
        if ([file hasPrefix:prefix])
            [fm removeItemAtPath:[ephemeralDirectoryPath stringByAppendingPathComponent:file] error:nil];
    }
}

-(void)deleteImageForHash:(NSString *)hash
{
    if (!hash)
        return;

    [memoryImages removeObjectForKey:hash];
    [memoryImageExtensions removeObjectForKey:hash];
    [self removeEphemeralCopiesForHash:hash];

    NSString *filePath = [self resolvedPathForHash:hash];
    if (filePath)
        [[NSFileManager defaultManager] removeItemAtPath:filePath error:nil];
}

-(BOOL)hasImageForHash:(NSString *)hash
{
    if (hash && [memoryImages objectForKey:hash])
        return YES;
    return [self resolvedPathForHash:hash] != nil;
}

-(NSString *)imagesDirectoryPath
{
    return imagesDirectoryPath;
}

-(NSArray *)allStoredHashes
{
    NSArray *files = [[NSFileManager defaultManager] contentsOfDirectoryAtPath:imagesDirectoryPath error:nil];
    NSMutableArray *hashes = [NSMutableArray arrayWithCapacity:[files count]];
    for (NSString *file in files) {
        // Any stored image representation (.tiff/.gif/.png/.jpg) maps back to its hash.
        if ([[file pathExtension] length] > 0 && ![file hasPrefix:@"."]) {
            [hashes addObject:[file stringByDeletingPathExtension]];
        }
    }
    for (NSString *hash in memoryImages) {
        if (![hashes containsObject:hash])
            [hashes addObject:hash];
    }
    return hashes;
}

-(void)removeEphemeralFiles
{
    NSFileManager *fm = [NSFileManager defaultManager];
    if ([fm fileExistsAtPath:ephemeralDirectoryPath])
        [fm removeItemAtPath:ephemeralDirectoryPath error:nil];
}

-(void)removeAllImages
{
    [memoryImages removeAllObjects];
    [memoryImageExtensions removeAllObjects];
    [self removeEphemeralFiles];

    // Only content-addressed image files (SHA-256 hex name) belong to the store.
    NSCharacterSet *nonHex = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
    NSFileManager *fm = [NSFileManager defaultManager];
    for (NSString *file in [fm contentsOfDirectoryAtPath:imagesDirectoryPath error:nil]) {
        NSString *stem = [file stringByDeletingPathExtension];
        if ([stem length] == CC_SHA256_DIGEST_LENGTH * 2 && [stem rangeOfCharacterFromSet:nonHex].location == NSNotFound)
            [fm removeItemAtPath:[imagesDirectoryPath stringByAppendingPathComponent:file] error:nil];
    }
}

-(void)dealloc
{
    [imagesDirectoryPath release];
    [memoryImages release];
    [memoryImageExtensions release];
    [ephemeralDirectoryPath release];
    [super dealloc];
}

@end
