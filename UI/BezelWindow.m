//
//  BezelWindow.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

#import "BezelWindow.h"
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>

static const float lineHeight = 16;

@implementation BezelWindow

- (id)initWithContentRect:(NSRect)contentRect
				styleMask:(NSUInteger)aStyle
  				backing:(NSBackingStoreType)bufferingType
					defer:(BOOL)flag
			   showSource:(BOOL)showSource {

	self = [super initWithContentRect:contentRect
							styleMask:NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskBorderless
							backing:NSBackingStoreBuffered
							defer:NO];
	if ( self )
	{
		//set this window to be on top of all other windows
		[self setLevel:NSScreenSaverWindowLevel];

		[self setOpaque:NO];
		[self setAlphaValue:1.0];
		[self setOpaque:NO];
		[self setMovableByWindowBackground:NO];
        [self setColor:NO];

        // Modern translucent appearance with proper vibrancy
        if (@available(macOS 10.14, *)) {
            self.titlebarAppearsTransparent = YES;
            // Support both light and dark mode dynamically
            self.appearance = [NSAppearance appearanceNamed:NSAppearanceNameVibrantDark];
        }

        // Modern shadow with blur radius for depth
        NSShadow *shadow = [[NSShadow alloc] init];
        shadow.shadowBlurRadius = 24.0;
        shadow.shadowOffset = NSMakeSize(0, -8);
        shadow.shadowColor = [[NSColor blackColor] colorWithAlphaComponent:0.3];
        [self setHasShadow:YES];

		[self setBackgroundColor:[self backgroundColor]];
        showSourceField = showSource;

        if (showSourceField)
        {
            sourceIcon = [[NSImageView alloc] initWithFrame: [self iconFrame]];
            [[self contentView] addSubview:sourceIcon];
            [sourceIcon setEditable:NO];

            sourceFieldBackground = [[RoundRecTextField alloc] initWithFrame:[self sourceFrame]];
            [[self contentView] addSubview:sourceFieldBackground];
            [sourceFieldBackground.textField setEditable:NO];

            // Use system label color for proper dark mode support
            if (@available(macOS 10.14, *)) {
                [sourceFieldBackground.textField setTextColor:[NSColor labelColor]];
            } else {
                [sourceFieldBackground.textField setTextColor:[NSColor whiteColor]];
            }

            // Modern liquid glass effect for source background
            if (@available(macOS 10.14, *)) {
                NSVisualEffectView *sourceEffectView = [[NSVisualEffectView alloc] initWithFrame:sourceFieldBackground.bounds];
                sourceEffectView.material = NSVisualEffectMaterialHUDWindow;
                sourceEffectView.blendingMode = NSVisualEffectBlendingModeBehindWindow;
                sourceEffectView.state = NSVisualEffectStateActive;
                sourceEffectView.wantsLayer = YES;
                sourceEffectView.layer.cornerRadius = 10.0;
                // Use continuous corner curve for smoother, more modern appearance
                if (@available(macOS 10.15, *)) {
                    sourceEffectView.layer.cornerCurve = @"continuous";
                }
                sourceEffectView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
                [sourceFieldBackground addSubview:sourceEffectView positioned:NSWindowBelow relativeTo:nil];
            } else {
                // Fallback for older macOS versions
                [sourceFieldBackground.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.12, 0.12, 0.12, 0.8)];
            }
            [sourceFieldBackground.textField setBordered:NO];

            sourceFieldApp = [[RoundRecTextField alloc] initWithFrame:[self sourceFrameLeft]];
            [[self contentView] addSubview:sourceFieldApp];
            [sourceFieldApp.textField setEditable:NO];

            // Use secondary label color for hierarchy
            if (@available(macOS 10.14, *)) {
                [sourceFieldApp.textField setTextColor:[NSColor secondaryLabelColor]];
            } else {
                [sourceFieldApp.textField setTextColor:[NSColor whiteColor]];
            }
            [sourceFieldApp.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.1, 0.1, 0.1, 0.0)];
            [sourceFieldApp.textField setBordered:NO];
            [sourceFieldApp.textField setAlignment:NSTextAlignmentLeft];

            NSMutableParagraphStyle *textParagraph = [[NSMutableParagraphStyle alloc] init];
            [textParagraph setLineSpacing:100.0];

            NSDictionary *attrDic = [NSDictionary dictionaryWithObjectsAndKeys:textParagraph, NSParagraphStyleAttributeName, nil];
            NSAttributedString *attrString = [[NSAttributedString alloc] initWithString:@"" attributes:attrDic];
            [sourceFieldApp.textField setAllowsEditingTextAttributes:YES];
            [sourceFieldApp.textField setAttributedStringValue:attrString];

            NSFont *font = [sourceFieldApp.textField font];
            NSFont *newFont = [NSFont fontWithName:[font fontName] size:font.pointSize*3/2];
            [sourceFieldApp.textField setFont:newFont];

            sourceFieldDate = [[RoundRecTextField alloc] initWithFrame:[self sourceFrameRight]];
            [[self contentView] addSubview:sourceFieldDate];
            [sourceFieldDate.textField setEditable:NO];

            // Use tertiary label color for less prominent text
            if (@available(macOS 10.14, *)) {
                [sourceFieldDate.textField setTextColor:[NSColor tertiaryLabelColor]];
            } else {
                [sourceFieldDate.textField setTextColor:[NSColor whiteColor]];
            }
            [sourceFieldDate.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.1, 0.1, 0.1, 0.0)];
            [sourceFieldDate.textField setBordered:NO];
            [sourceFieldDate.textField setAlignment:NSTextAlignmentRight];
            font = [sourceFieldDate.textField font];
            newFont = [NSFont fontWithName:[font fontName] size:font.pointSize*5/4];
            [sourceFieldDate.textField setFont:newFont];
        }

		NSRect textFrame = [self textFrame];
		textField = [[RoundRecTextField alloc] initWithFrame:textFrame];
		[[self contentView] addSubview:textField];
		[textField.textField setEditable:NO];
		//[[textField cell] setScrollable:YES];
		//[[textField cell] setWraps:NO];

		// Use system label color for proper dark mode support
		if (@available(macOS 10.14, *)) {
			[textField.textField setTextColor:[NSColor labelColor]];
		} else {
			[textField.textField setTextColor:[NSColor whiteColor]];
		}

		// Modern liquid glass effect for main text field
		if (@available(macOS 10.14, *)) {
			// Use HUD material for that frosted glass translucent effect
			NSVisualEffectView *textEffectView = [[NSVisualEffectView alloc] initWithFrame:textField.bounds];
			textEffectView.material = NSVisualEffectMaterialHUDWindow;
			textEffectView.blendingMode = NSVisualEffectBlendingModeBehindWindow;
			textEffectView.state = NSVisualEffectStateActive;
			textEffectView.wantsLayer = YES;
			textEffectView.layer.cornerRadius = 14.0;
			// Use continuous corner curve for that smooth, modern iOS/macOS look
			if (@available(macOS 10.15, *)) {
				textEffectView.layer.cornerCurve = @"continuous";
			}
			textEffectView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
			[textField addSubview:textEffectView positioned:NSWindowBelow relativeTo:nil];
		} else {
			// Fallback for older macOS versions
			[textField.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.12, 0.12, 0.12, 0.8)];
		}
		[textField.textField setBordered:NO];
		[textField.textField setAlignment:NSTextAlignmentLeft];

		NSRect charFrame = [self charFrame];
		charField = [[RoundRecTextField alloc] initWithFrame:charFrame];
		[[self contentView] addSubview:charField];
		[charField.textField setEditable:NO];

		// Use secondary label color for status text
		if (@available(macOS 10.14, *)) {
			[charField.textField setTextColor:[NSColor secondaryLabelColor]];
		} else {
			[charField.textField setTextColor:[NSColor whiteColor]];
		}
		[charField.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.12, 0.12, 0.12, 0.8)];
		[charField.textField setBordered:NO];
		[charField.textField setAlignment:NSTextAlignmentCenter];
        [charField.textField setStringValue:@"Empty"];
		// Use Auto Layout for dynamic width.
		charField.translatesAutoresizingMaskIntoConstraints = NO;
		[NSLayoutConstraint activateConstraints:@[
			[charField.bottomAnchor constraintEqualToAnchor:self.contentView.bottomAnchor constant:-charFrame.origin.y],
			[charField.centerXAnchor constraintEqualToAnchor:self.contentView.centerXAnchor],
			[charField.heightAnchor constraintEqualToConstant:charFrame.size.height],
		]];

		[self setInitialFirstResponder:textField];         
		return self;
	}
	return nil;
}


- (void) update  {
    [super update];
    [self setBackgroundColor:[self backgroundColor]];

    Boolean savedShowSourceField = showSourceField;
    if (nil == sourceText || 0 == sourceText.length)
        showSourceField = false;

    // Defer frame updates to avoid layout recursion
    dispatch_async(dispatch_get_main_queue(), ^{
        NSRect textFrame = [self textFrame];
        [textField setFrame:textFrame];
        NSRect charFrame = [self charFrame];
        [charField setFrame:charFrame];
    });
    
    if (showSourceField)
        [sourceFieldBackground.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.12, 0.12, 0.12, 0.8)];
    else if ( nil != sourceFieldApp )
        [sourceFieldBackground.background.layer setBackgroundColor:CGColorCreateGenericRGB(0.12, 0.12, 0.12, 0.0)];
    
    showSourceField = savedShowSourceField;

}

-(NSRect) iconFrame
{
    NSRect frame = [self textFrame];
    frame.origin.y += frame.size.height + 5;
    frame.size.height = 1.8 * lineHeight;
    frame.size.width = frame.size.height;
    return frame;
}

-(NSRect) sourceFrame
{
    NSRect frame = [self textFrame];
    frame.origin.y += frame.size.height + 5;
    frame.size.height = 1.8 * lineHeight;
    frame.origin.x += frame.size.height + 5;
    frame.size.width -= frame.size.height + 5;
    return frame;
}

-(NSRect) sourceFrameLeft
{
    NSRect frame = [self sourceFrame];
    frame.size.width = frame.size.width * 1 / 3 - 5;
    return frame;
}

-(NSRect) sourceFrameRight
{
    NSRect frame = [self sourceFrame];
    frame.size.height -= 0.3 * lineHeight;
    frame.origin.x += frame.size.width * 1 / 3 + 10;
    frame.size.width = frame.size.width * 2 / 3 - 10;
    return frame;
}

-(NSRect) textFrame
{
    int adjustHeight = 0;
    if (showSourceField) adjustHeight = 1.8 * lineHeight;
    return NSMakeRect(12, 36, self.frame.size.width - 24, self.frame.size.height - 50 - adjustHeight);
}

-(NSRect) charFrame
{
    return NSMakeRect(([self frame].size.width - (3 * lineHeight)) / 2, 7, 8 * lineHeight, 1.2 * lineHeight);
}

-(NSColor*) backgroundColor
{
    // Larger corner radius for modern appearance (like Spotlight or Control Center)
    return [self sizedBezelBackgroundWithRadius:28.0 withAlpha:[[NSUserDefaults standardUserDefaults] floatForKey:@"bezelAlpha"]];
}

- (void) setAlpha:(float)newValue
{
	[self setBackgroundColor:[self backgroundColor]];
	[[self contentView] setNeedsDisplay:YES];
}

- (NSString *)title
{
	return title;
}

- (void)setTitle:(NSString *)newTitle
{
	[newTitle retain];
	[title release];
	title = newTitle;
}

- (NSString *)text
{
	return bezelText;
}

- (void)setCharString:(NSString *)newChar
{
	[newChar retain];
	[charString release];
	charString = newChar;
	[charField.textField setStringValue:charString];
}

- (void)setText:(NSString *)newText
{
    // The Bezel gets slow when newText is huge.  Probably the retain.
    // Since we can't see that much of it anyway, trim to 2000 characters.
    if ([newText length] > 2000)
        newText = [newText substringToIndex:2000];
	[newText retain];
	[bezelText release];
	bezelText = newText;
	[textField.textField setStringValue:bezelText];
}

- (void)setSourceIcon:(NSImage *)newSourceIcon
{
	if (!showSourceField)
		return;
	[newSourceIcon retain];
	[sourceIconImage release];
	sourceIconImage = newSourceIcon;
	[sourceIcon setImage:sourceIconImage];
}

- (void)setSource:(NSString *)newSource
{
	if (!showSourceField)
		return;

	// Ensure that the source will fit in the screen space available, and truncate nicely if need be.
	NSDictionary *attributes = @{NSFontAttributeName: sourceFieldApp.textField.font};
	CGSize size = [newSource sizeWithAttributes:attributes]; // How big is this string when drawn in this font?
	if (size.width >= sourceFieldApp.frame.size.width - 5)
	{
		newSource = [NSString stringWithFormat:@"%@...", newSource];
		do
		{
			newSource = [NSString stringWithFormat:@"%@...", [newSource substringToIndex:[newSource length] - 4]];
			size = [newSource sizeWithAttributes:attributes];
		} while (size.width >= sourceFieldApp.frame.size.width - 5);
	}

	[newSource retain];
	[sourceText release];
	sourceText = newSource;
	[sourceFieldApp.textField setStringValue:sourceText];
}

- (void)setDate:(NSString *)newDate
{
	if (!showSourceField)
		return;
	[newDate retain];
	[dateText release];
	dateText = newDate;
	[sourceFieldDate.textField setStringValue:dateText];
}

- (void)setColor:(BOOL)value
{
    color=value;
}


- (NSColor *)roundedBackgroundWithRect:(NSRect)bgRect withRadius:(float)radius withAlpha:(float)alpha
{
	NSImage *bg = [[NSImage alloc] initWithSize:bgRect.size];
	[bg lockFocus];
	NSRect dummyRect = NSMakeRect(0, 0, [bg size].width, [bg size].height);
	NSBezierPath *roundedRec = [NSBezierPath bezierPathWithRoundRectInRect:dummyRect radius:radius];

    // Modern translucent colors that adapt to the system appearance
    if (color) {
        // Favorites mode - subtle warm accent with liquid glass effect
        [[NSColor colorWithCalibratedRed:0.18 green:0.16 blue:0.14 alpha:alpha * 0.85] set];
    } else {
        // Normal mode - cool dark translucent for that liquid glass look
        [[NSColor colorWithCalibratedRed:0.10 green:0.10 blue:0.12 alpha:alpha * 0.85] set];
    }
    [roundedRec fill];
	[bg unlockFocus];
	return [NSColor colorWithPatternImage:[bg autorelease]];
}

- (NSColor *)sizedBezelBackgroundWithRadius:(float)radius withAlpha:(float)alpha
{
	return [self roundedBackgroundWithRect:[self frame] withRadius:radius withAlpha:alpha];
}

-(BOOL)canBecomeKeyWindow
{
	return YES;
}

- (void)dealloc
{
	[textField release];
	[charField release];
	[iconView release];
	[super dealloc];
}

- (BOOL)performKeyEquivalent:(NSEvent*) theEvent
{
	if ( [self delegate] )
	{
		[delegate performSelector:@selector(processBezelKeyDown:) withObject:theEvent];
		return YES;
	}
	return NO;
}

- (void)scrollWheel:(NSEvent *)theEvent
{
    if ( [self delegate] )
    {
        [delegate performSelector:@selector(processBezelMouseEvents:) withObject:theEvent];
    }
}

 - (void)mouseUp:(NSEvent *)theEvent
{
    if ( [self delegate] )
    {
       [delegate performSelector:@selector(processBezelMouseEvents:) withObject:theEvent];
    }
}



- (void)keyDown:(NSEvent *)theEvent {
	if ( [self delegate] )
	{
		[delegate performSelector:@selector(processBezelKeyDown:) withObject:theEvent];
	}
}

- (void)flagsChanged:(NSEvent *)theEvent {
	if ( !    ( [theEvent modifierFlags] & NSEventModifierFlagCommand )
		 && ! ( [theEvent modifierFlags] & NSEventModifierFlagOption )
		 && ! ( [theEvent modifierFlags] & NSEventModifierFlagControl )
		 && ! ( [theEvent modifierFlags] & NSEventModifierFlagShift )
		 && [ self delegate ]
		 )
	{
		[delegate performSelector:@selector(metaKeysReleased)];
	}
}
		
- (id<BezelWindowDelegate>)delegate {
    return delegate;
}

- (void)setDelegate:(id<BezelWindowDelegate>)newDelegate {
    delegate = newDelegate;
	super.delegate = newDelegate;
}

@end
