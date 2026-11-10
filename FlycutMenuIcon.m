//
//  FlycutMenuIcon.m
//  Flycut
//
//  Resolution-independent menu-bar artwork for clipboard tracking.
//

#import "FlycutMenuIcon.h"
#import <math.h>

NSString * const FlycutMenuIconCustomColorsEnabledKey = @"menuIconCustomColorsEnabled";
NSString * const FlycutMenuIconActiveColorComponentsKey = @"menuIconActiveColorComponents";
NSString * const FlycutMenuIconPausedColorComponentsKey = @"menuIconPausedColorComponents";

static NSArray *FlycutColorComponents(NSColor *color)
{
    NSColor *sRGBColor = [color colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    if (sRGBColor == nil)
        return nil;

    CGFloat red = 0.0;
    CGFloat green = 0.0;
    CGFloat blue = 0.0;
    CGFloat alpha = 0.0;
    [sRGBColor getRed:&red green:&green blue:&blue alpha:&alpha];
    if (!isfinite(red) || !isfinite(green) || !isfinite(blue))
        return nil;
    return @[@(red), @(green), @(blue)];
}

static NSColor *FlycutColorFromComponents(NSArray *components)
{
    if ([components count] != 3)
        return nil;

    for (id component in components) {
        if (![component isKindOfClass:[NSNumber class]])
            return nil;
    }

    CGFloat red = [components[0] doubleValue];
    CGFloat green = [components[1] doubleValue];
    CGFloat blue = [components[2] doubleValue];
    if (!isfinite(red) || !isfinite(green) || !isfinite(blue) ||
        red < 0.0 || red > 1.0 ||
        green < 0.0 || green > 1.0 ||
        blue < 0.0 || blue > 1.0)
        return nil;

    return [NSColor colorWithSRGBRed:red
                               green:green
                                blue:blue
                               alpha:1.0];
}

static NSColor *FlycutDefaultColor(BOOL paused)
{
    return paused ? [NSColor colorWithSRGBRed:1.0 green:0.584 blue:0.0 alpha:1.0]
                  : [NSColor colorWithSRGBRed:0.0 green:0.478 blue:1.0 alpha:1.0];
}

static void ConfigureStroke(NSBezierPath *path, CGFloat width)
{
    [path setLineWidth:width];
    [path setLineCapStyle:NSLineCapStyleRound];
    [path setLineJoinStyle:NSLineJoinStyleRound];
}

static void DrawClippingStackPages(NSColor *strokeColor)
{
    [strokeColor setStroke];

    NSBezierPath *backPage = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(6.5, 5.0, 8.0, 10.5)
                                                              xRadius:1.4
                                                              yRadius:1.4];
    ConfigureStroke(backPage, 1.35);
    [backPage stroke];

    NSBezierPath *frontPage = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(3.0, 2.5, 8.5, 11.0)
                                                               xRadius:1.4
                                                               yRadius:1.4];

    // The front page occludes the parts of the rear outline beneath it. Clearing
    // that area in the alpha mask keeps the two sheets readable at 18 points.
    [NSGraphicsContext saveGraphicsState];
    [[NSGraphicsContext currentContext] setCompositingOperation:NSCompositingOperationClear];
    [frontPage fill];
    [NSGraphicsContext restoreGraphicsState];

    ConfigureStroke(frontPage, 1.35);
    [frontPage stroke];
}

static void DrawClippingTextLines(NSColor *strokeColor)
{
    [strokeColor setStroke];

    const CGFloat starts[] = {5.25, 5.25, 5.25};
    const CGFloat ends[] = {9.35, 9.35, 8.25};
    const CGFloat heights[] = {9.65, 7.55, 5.45};
    for (NSUInteger index = 0; index < 3; index++) {
        NSBezierPath *line = [NSBezierPath bezierPath];
        [line moveToPoint:NSMakePoint(starts[index], heights[index])];
        [line lineToPoint:NSMakePoint(ends[index], heights[index])];
        ConfigureStroke(line, 1.05);
        [line stroke];
    }
}

static void DrawPauseSlash(NSColor *strokeColor)
{
    [strokeColor setStroke];

    NSBezierPath *slash = [NSBezierPath bezierPath];
    [slash moveToPoint:NSMakePoint(2.3, 2.3)];
    [slash lineToPoint:NSMakePoint(15.7, 15.7)];
    ConfigureStroke(slash, 1.75);
    [slash stroke];
}

@implementation FlycutMenuIcon

+(void)registerColorDefaults:(NSUserDefaults *)defaults
{
    [defaults registerDefaults:@{
        FlycutMenuIconCustomColorsEnabledKey: @NO,
        FlycutMenuIconActiveColorComponentsKey: @[@0.0, @0.478, @1.0],
        FlycutMenuIconPausedColorComponentsKey: @[@1.0, @0.584, @0.0]
    }];
}

+(NSColor *)tintColorForPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults
{
    if (![defaults boolForKey:FlycutMenuIconCustomColorsEnabledKey])
        return nil;

    return [self configuredColorForPaused:paused userDefaults:defaults];
}

+(NSColor *)configuredColorForPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults
{
    NSString *key = paused ? FlycutMenuIconPausedColorComponentsKey : FlycutMenuIconActiveColorComponentsKey;
    NSColor *configuredColor = FlycutColorFromComponents([defaults arrayForKey:key]);
    return configuredColor ?: FlycutDefaultColor(paused);
}

+(void)setTintColor:(NSColor *)color forPaused:(BOOL)paused userDefaults:(NSUserDefaults *)defaults
{
    NSArray *components = FlycutColorComponents(color);
    if (components == nil)
        return;

    NSString *key = paused ? FlycutMenuIconPausedColorComponentsKey : FlycutMenuIconActiveColorComponentsKey;
    [defaults setObject:components forKey:key];
}

+(NSImage *)imageForPaused:(BOOL)paused
{
    return [self imageForPaused:paused tintColor:nil];
}

+(NSImage *)imageForPaused:(BOOL)paused tintColor:(NSColor *)tintColor
{
    NSColor *drawingColor = tintColor != nil ? tintColor : [NSColor blackColor];
    NSImage *image = [NSImage imageWithSize:NSMakeSize(18.0, 18.0)
                                    flipped:NO
                             drawingHandler:^BOOL(NSRect destinationRect) {
        (void)destinationRect;
        DrawClippingStackPages(drawingColor);
        if (!paused) {
            DrawClippingTextLines(drawingColor);
        }
        if (paused) {
            DrawPauseSlash(drawingColor);
        }
        return YES;
    }];
    [image setTemplate:tintColor == nil];
    return image;
}

@end
