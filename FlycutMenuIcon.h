//
//  FlycutMenuIcon.h
//  Flycut
//
//  Resolution-independent menu-bar artwork for clipboard tracking.
//

#import <AppKit/AppKit.h>

FOUNDATION_EXPORT NSString * const FlycutMenuIconCustomColorsEnabledKey;
FOUNDATION_EXPORT NSString * const FlycutMenuIconActiveColorComponentsKey;
FOUNDATION_EXPORT NSString * const FlycutMenuIconPausedColorComponentsKey;

@interface FlycutMenuIcon : NSObject

// Returns an 18-point monochrome template image. Active shows writing lines;
// paused keeps the same clipping-stack outline, removes those lines, and adds
// a diagonal strike.
+(NSImage *)imageForPaused:(BOOL)paused;

// Custom colors are painted directly because NSStatusBarButton can ignore
// contentTintColor even though the property retains the requested value.
+(NSImage *)imageForPaused:(BOOL)paused tintColor:(NSColor *)tintColor;

// Custom colors are local preferences. A nil tint means AppKit should use its
// automatic appearance-aware template rendering.
+(void)registerColorDefaults:(NSUserDefaults *)defaults;
+(NSColor *)configuredColorForPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults;
+(NSColor *)tintColorForPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults;
+(void)setTintColor:(NSColor *)color forPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults;

@end
