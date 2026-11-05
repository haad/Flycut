//
//  FlycutImageStore.m
//  Flycut
//
//  File-based image storage for clipboard image clippings.
//

#import "FlycutImageStore.h"

static FlycutImageStore *sharedInstance = nil;

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
    return [data writeToFile:filePath atomically:YES];
}

-(NSData *)imageDataForHash:(NSString *)hash
{
    NSString *filePath = [self resolvedPathForHash:hash];
    if (!filePath)
        return nil;

    return [NSData dataWithContentsOfFile:filePath];
}

-(NSString *)imageFilePathForHash:(NSString *)hash
{
    return [self resolvedPathForHash:hash];
}

-(void)deleteImageForHash:(NSString *)hash
{
    NSString *filePath = [self resolvedPathForHash:hash];
    if (filePath)
        [[NSFileManager defaultManager] removeItemAtPath:filePath error:nil];
}

-(BOOL)hasImageForHash:(NSString *)hash
{
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
    return hashes;
}

-(void)dealloc
{
    [imagesDirectoryPath release];
    [super dealloc];
}

@end
