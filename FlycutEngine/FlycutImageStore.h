//
//  FlycutImageStore.h
//  Flycut
//
//  File-based image storage for clipboard image clippings.
//

#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>

@interface FlycutImageStore : NSObject {
    NSString *imagesDirectoryPath;
}

+(FlycutImageStore *)sharedStore;

// Maps a pasteboard UTI (e.g. com.compuserve.gif) to the on-disk file extension.
+(NSString *)fileExtensionForType:(NSString *)uti;

-(NSString *)hashForData:(NSData *)data;
-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash;
-(BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext;
-(NSData *)imageDataForHash:(NSString *)hash;
// Absolute path to the stored image file for a hash (whatever extension), or nil.
-(NSString *)imageFilePathForHash:(NSString *)hash;
-(void)deleteImageForHash:(NSString *)hash;
-(BOOL)hasImageForHash:(NSString *)hash;
-(NSString *)imagesDirectoryPath;
-(NSArray *)allStoredHashes;

@end
