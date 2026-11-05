//
//  FlycutClipping.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

#import <Foundation/Foundation.h>

@interface FlycutClipping : NSObject {
    NSString * clipContents;
    NSString * clipType;
    int clipDisplayLength;
    NSString * clipDisplayString;
    BOOL clipHasName;
    NSString * appLocalizedName;
    NSString * appBundleURL;
    NSInteger clipTimestamp;
    NSString * imageHash;
    NSSize imageSize;
}

-(id) initWithContents:(NSString *)contents withType:(NSString *)type withDisplayLength:(int)displayLength withAppLocalizedName:(NSString *)localizedName withAppBundleURL:(NSString *)bundleURL withTimestamp:(NSInteger)timestamp;
-(id) initWithImageHash:(NSString *)hash withImageSize:(NSSize)size withImageType:(NSString *)imageType withDisplayLength:(int)displayLength withAppLocalizedName:(NSString *)localizedName withAppBundleURL:(NSString *)bundleURL withTimestamp:(NSInteger)timestamp;
/* -(id) initWithCoder:(NSCoder *)coder;
-(void) decodeWithCoder:(NSCoder *)coder; */
-(NSString *) description;

// set values
-(void) setContents:(NSString *)newContents setDisplayLength:(int)newDisplayLength;
-(void) setContents:(NSString *)newContents;
-(void) setType:(NSString *)newType;
-(void) setDisplayLength:(int)newDisplayLength;
-(void) setHasName:(BOOL)newHasName;

// Retrieve values
-(FlycutClipping *) clipping;
-(NSString *) contents;
-(int) displayLength;
-(NSString *) displayString;
-(NSString *) type;
-(NSString *) appLocalizedName;
-(NSString *) appBundleURL;
-(NSInteger) timestamp;
-(BOOL) hasName;
-(BOOL) isImageClipping;
-(NSString *) imageHash;
-(NSSize) imageSize;
-(void) setImageHash:(NSString *)hash;
-(void) setImageSize:(NSSize)size;

// Additional functions
-(void) resetDisplayString;

@end
