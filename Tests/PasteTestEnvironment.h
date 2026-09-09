#pragma once
// Native fixtures never use real application preferences or activate a UI.
#import <Cocoa/Cocoa.h>
@interface FCPasteTestDefaults : NSObject
+ (id)standardUserDefaults;
- (void)registerDefaults:(NSDictionary *)defaults;
- (id)objectForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (void)setBool:(BOOL)value forKey:(NSString *)key;
@end
#define NSUserDefaults FCPasteTestDefaults
#undef NSApp
#define NSApp ((NSApplication *)nil)
