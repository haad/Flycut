//
//  FlycutImageStore.h
//  Flycut
//
//  Storage for clipboard image clippings: files in Application Support, or,
//  while history is not saved (Save: Never), memory only.
//

#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>

@interface FlycutImageStore : NSObject {
    NSString *imagesDirectoryPath;
    // Images kept in memory only (Save: Never), keyed by hash.
    NSMutableDictionary *memoryImages;
    NSMutableDictionary *memoryImageExtensions;
    // This process's directory for temporary copies of memory-only images.
    NSString *ephemeralDirectoryPath;
}

+(FlycutImageStore *)sharedStore;

// Maps a pasteboard UTI (e.g. com.compuserve.gif) to the on-disk file extension.
+(NSString *)fileExtensionForType:(NSString *)uti;

-(NSString *)hashForData:(NSData *)data;
-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash;
-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext;
// Keeps the image in memory only; nothing is written to disk.
-(BOOL)saveMemoryOnlyImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext;
// Writes a memory-only image to the image directory. No-op for other images.
-(void)persistMemoryOnlyImageForHash:(NSString *)hash;
-(NSData *)imageDataForHash:(NSString *)hash;
// Absolute path to the stored image file for a hash (whatever extension), or nil.
// For a memory-only image this is a temporary copy, removed together with the
// image and by -removeEphemeralFiles.
-(NSString *)imageFilePathForHash:(NSString *)hash;
-(void)deleteImageForHash:(NSString *)hash;
-(BOOL)hasImageForHash:(NSString *)hash;
-(NSString *)imagesDirectoryPath;
-(NSArray *)allStoredHashes;
// Removes the temporary copies made for memory-only images.
-(void)removeEphemeralFiles;
// Forgets every image: memory-only data, temporary copies and stored files.
-(void)removeAllImages;

@end
