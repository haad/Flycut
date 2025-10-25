//
//  AppController.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// AppController owns and interacts with the FlycutOperator, providing a user
// interface and platform-specific mechanisms.

#import "AppController.h"
#import "SGHotKey.h"
#import "SGHotKeyCenter.h"
#import "SRRecorderCell.h"
#import "UKLoginItemRegistry.h"
#import "NSWindow+TrueCenter.h"
#import "NSWindow+ULIZoomEffect.h"
//#import "MJCloudKitUserDefaultsSync/MJCloudKitUserDefaultsSync.h"
#import <ApplicationServices/ApplicationServices.h>
#import <CoreFoundation/CoreFoundation.h>
#import <ServiceManagement/ServiceManagement.h>

@implementation AppController

/// Determines, through a hack of sorts, if the app is running sandboxed. The SANDBOXING define has no direct connection to being sandboxed, but this method identifies the state by looking for a directory which will have at least eight path components if sandboxed and is quite unlikely to have that many if not sandboxed. Of course, if this doesn't work for your unique case, just do a custom build with this method returning NO.
+ (BOOL)isAppSandboxed {
	// Get the Desktop directory:
	NSArray *paths = NSSearchPathForDirectoriesInDomains
	(NSDesktopDirectory, NSUserDomainMask, YES);
	NSString *desktopDirectory = [paths objectAtIndex:0];
	return ((NSArray*)[desktopDirectory componentsSeparatedByString:@"/"]).count >= 8;
}

- (id)init
{
	[[NSUserDefaults standardUserDefaults] registerDefaults:[NSDictionary dictionaryWithObjectsAndKeys:
		[NSDictionary dictionaryWithObjects:[NSArray arrayWithObjects:[NSNumber numberWithInt:9],[NSNumber numberWithLong:1179648],nil] forKeys:[NSArray arrayWithObjects:@"keyCode",@"modifierFlags",nil]],
		@"ShortcutRecorder mainHotkey",
		[NSDictionary dictionaryWithObjects:[NSArray arrayWithObjects:[NSNumber numberWithInt:1],[NSNumber numberWithLong:1179648|NSEventModifierFlagShift],nil] forKeys:[NSArray arrayWithObjects:@"keyCode",@"modifierFlags",nil]],
		@"ShortcutRecorder searchHotkey",
		[NSNumber numberWithInt:10],
		@"displayNum",
		[NSNumber numberWithInt:40],
		@"displayLen",
		[NSNumber numberWithInt:0],
		@"menuIcon",
		[NSNumber numberWithFloat:.25],
		@"bezelAlpha",
		[NSNumber numberWithBool:NO],
		@"stickyBezel",
		[NSNumber numberWithBool:NO],
		@"wraparoundBezel",
		[NSNumber numberWithBool:NO],// No by default
		@"loadOnStartup",
		[NSNumber numberWithBool:YES], 
		@"menuSelectionPastes",
        // Flycut new options
        [NSNumber numberWithFloat:500.0],
        @"bezelWidth",
        [NSNumber numberWithFloat:320.0],
        @"bezelHeight",
        [NSNumber numberWithBool:NO],
        @"popUpAnimation",
        [NSNumber numberWithBool:YES],
        @"displayClippingSource",
        [NSNumber numberWithBool:NO],
        @"saveForgottenClippings",
#ifdef SANDBOXING
        [NSNumber numberWithBool:NO],
#else
        [NSNumber numberWithBool:YES],
#endif
        @"saveForgottenFavorites",
        [NSNumber numberWithBool:NO],
        @"suppressAccessibilityAlert",
        nil]];

	/* For testing, the ability to force initial values of the sync settings:
	[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
											 forKey:@"syncSettingsViaICloud"];
	[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
											 forKey:@"syncClippingsViaICloud"];*/

	settingsSyncList = @[@"displayNum",
						 @"displayLen",
						 @"menuIcon",
						 @"bezelAlpha",
						 @"stickyBezel",
						 @"wraparoundBezel",
						 @"loadOnStartup",
						 @"menuSelectionPastes",
						 @"bezelWidth",
						 @"bezelHeight",
						 @"popUpAnimation",
						 @"displayClippingSource",
						 @"saveForgottenClippings",
						 @"saveForgottenFavorites",
                         @"suppressAccessibilityAlert",
                        ];
	[settingsSyncList retain];

	menuQueue = dispatch_queue_create(@"com.Flycut.menuUpdateQueue", DISPATCH_QUEUE_SERIAL);

	return [super init];
}

//- (void)registerOrDeregisterICloudSync
//{
//	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"syncSettingsViaICloud"] ) {
//		[[MJCloudKitUserDefaultsSync sharedSync] removeNotificationsFor:MJSyncNotificationChanges forTarget:self];
//		[[MJCloudKitUserDefaultsSync sharedSync] addNotificationFor:MJSyncNotificationChanges withSelector:@selector(checkPreferencesChanges:) withTarget: self];
//		// Not registering for conflict notifications, since we just sync settings, and if the settings are conflictingly adjusted simultaneously on two systems there is nothing to say which setting is better.
//
//		[[MJCloudKitUserDefaultsSync sharedSync] startWithKeyMatchList:settingsSyncList
//					withContainerIdentifier:kiCloudId];
//	}
//	else {
//		[[MJCloudKitUserDefaultsSync sharedSync] stopForKeyMatchList:settingsSyncList];
//
//		[[MJCloudKitUserDefaultsSync sharedSync] removeNotificationsFor:MJSyncNotificationChanges forTarget:self];
//	}
//
//	[flycutOperator registerOrDeregisterICloudSync];
//}

- (void)showAccessibilityAlert {
    BOOL suppressAlert = [[NSUserDefaults standardUserDefaults] boolForKey:@"suppressAccessibilityAlert"];
    NSDictionary* options = @{(id) (kAXTrustedCheckOptionPrompt): @NO};
    if (!suppressAlert && &AXIsProcessTrustedWithOptions != NULL && !AXIsProcessTrustedWithOptions((CFDictionaryRef) (options))) {
        NSAlert *alert = [NSAlert alertWithMessageText:@"Flycut" defaultButton:@"OK" alternateButton:nil otherButton:nil informativeTextWithFormat:@"For correct functioning of the app please tick Flycut in Accessibility apps list"];
        alert.showsSuppressionButton = YES;
        [alert runModal];
        if (alert.suppressionButton.state == NSControlStateValueOn) {
            [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:YES]
                                                     forKey:@"suppressAccessibilityAlert"];
        }
        NSString *urlString = @"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility";
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:urlString]];
    }
}


- (void)showOldOSXAlert {
    // FIXME: Should ask Gennadii if the "#ifdef SANDBOXING" should be removed and replaced with "if (![AppController isAppSandboxed]) { return; }"
#ifdef SANDBOXING
    NSOperatingSystemVersion ver = [[NSProcessInfo processInfo] operatingSystemVersion];
    if (ver.majorVersion == 10 && ver.minorVersion <= 13) {
        BOOL suppressAlert = [[NSUserDefaults standardUserDefaults] boolForKey:@"suppressOldOSXAlert"];
        if (!suppressAlert) {
            NSAlert *alert = [NSAlert alertWithMessageText:@"Flycut" defaultButton:@"OK" alternateButton:nil otherButton:nil informativeTextWithFormat:@"Unfortunatly due to some app sandbox security restrictions from Apple Flycut may not correctly function on MacOSX 10.13 or lower. You can download non sandboxed version here: https://github.com/TermiT/Flycut/releases"];
            alert.showsSuppressionButton = YES;
            [alert runModal];
            if (alert.suppressionButton.state == NSOnState) {
                [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:YES]
                                                         forKey:@"suppressOldOSXAlert"];
            }
        }
    }
#endif
}



- (void)awakeFromNib
{
	[self buildAppearancesPreferencePanel];

	// We no longer get autosave from ShortcutRecorder, so let's set the recorder by hand
	if ( [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder mainHotkey"] ) {
		[mainRecorder setKeyCombo:SRMakeKeyCombo([[[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder mainHotkey"] objectForKey:@"keyCode"] intValue],
												 [[[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder mainHotkey"] objectForKey:@"modifierFlags"] intValue] )
		];
	};

	// Set up search hotkey recorder
	if ( [[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder searchHotkey"] && searchRecorder ) {
		[searchRecorder setKeyCombo:SRMakeKeyCombo([[[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder searchHotkey"] objectForKey:@"keyCode"] intValue],
												   [[[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"ShortcutRecorder searchHotkey"] objectForKey:@"modifierFlags"] intValue] )
		];
	};

	// Initialize the FlycutOperator
	flycutOperator = [[FlycutOperator alloc] init];
	flycutOperator.delegate = self;
	[flycutOperator setClippingsStoreDelegate:self];
	[flycutOperator setFavoritesStoreDelegate:self];
	[flycutOperator awakeFromNibDisplaying:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"]
						 withDisplayLength:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayLen"]
						  withSaveSelector:@selector(savePreferencesOnDict:)
								 forTarget:self];

    [bezel setColor:NO];
    
	// Set up the bezel window
	[self setupBezel:nil];

	// Set up the bezel date formatter
	dateFormat = [[NSDateFormatter alloc] init];
	[dateFormat setDateFormat:@"EEEE, MMMM dd 'at' h:mm a"];

	// Create our pasteboard interface
    jcPasteboard = [NSPasteboard generalPasteboard];
    [jcPasteboard declareTypes:[NSArray arrayWithObject:NSPasteboardTypeString] owner:nil];
    pbCount = [[NSNumber numberWithInt:[jcPasteboard changeCount]] retain];

	// Build the statusbar menu
    statusItem = [[[NSStatusBar systemStatusBar]
            statusItemWithLength:NSVariableStatusItemLength] retain];
    [statusItem setHighlightMode:YES];
    [self switchMenuIconTo: [[NSUserDefaults standardUserDefaults] integerForKey:@"menuIcon"]];
	[statusItem setMenu:jcMenu];
    [jcMenu setDelegate:self];
    jcMenuBaseItemsCount = [[[[jcMenu itemArray] reverseObjectEnumerator] allObjects] count];
    [statusItem setEnabled:YES];

    // If our preferences indicate that we are saving, we may have loaded the dictionary from the
    // saved plist and should update the menu.
	if ( [[NSUserDefaults standardUserDefaults] integerForKey:@"savePreference"] >= 1 ) {
        [self updateMenu];
	}

	// Build our listener timer
	NSDate *oneSecondFromNow = [NSDate dateWithTimeIntervalSinceNow:1.0];
	pollPBTimer = [[NSTimer alloc] initWithFireDate:oneSecondFromNow
										   interval:(1.0)
											 target:self
										   selector:@selector(pollPB:)
										   userInfo:nil
											repeats:YES];
	// Assign it to NSRunLoopCommonModes so that it will still poll while the menu is open.  Using a simple NSTimer scheduledTimerWithTimeInterval: would result in polling that stops while the menu is active.  In the past this was okay but with Universal Clipboard a new clipping an arrive while the user has the menu open.
	[[NSRunLoop currentRunLoop] addTimer:pollPBTimer forMode:NSRunLoopCommonModes];

    // Finish up
	srTransformer = [[[SRKeyCodeTransformer alloc] init] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
    [pollPBTimer fire];
    
    
    // The load-on-startup check can be really slow, so this will be dispatched out so our thread isn't blocked.
    dispatch_queue_t queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0);
    dispatch_async(queue, ^{
        // FIXME: Should ask Gennadii if the "#ifdef SANDBOXING" should be removed and replaced with "if ([AppController isAppSandboxed])"
#ifdef SANDBOXING
        NSPredicate *predicate = [NSPredicate predicateWithFormat:@"bundleIdentifier == %@", kFlycutHelperId];
        NSArray *helperApp = [[[NSWorkspace sharedWorkspace] runningApplications] filteredArrayUsingPredicate:predicate];
        BOOL helperLaunched = ([helperApp count] != 0);
        [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:helperLaunched]
                                                            forKey:@"loadOnStartup"];
#else

        // This can take five seconds, perhaps more, so do it in the background instead of holding up opening of the preference panel.
        int checkLoginRegistry = [UKLoginItemRegistry indexForLoginItemWithPath:[[NSBundle mainBundle] bundlePath]];
        if ( checkLoginRegistry >= 1 ) {
            [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:YES]
                                                     forKey:@"loadOnStartup"];
        } else {
            [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
                                                     forKey:@"loadOnStartup"];
        }
#endif
    });
//    [self registerOrDeregisterICloudSync];

    [NSApp activateIgnoringOtherApps: YES];
    
    // Check if the app has Accessibility permission
    [self showAccessibilityAlert];
    [self showOldOSXAlert];
}

-(void)savePreferencesOnDict:(NSMutableDictionary *)saveDict
{
	[saveDict setObject:[NSNumber numberWithInt:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayLen"]]
				 forKey:@"displayLen"];
	[saveDict setObject:[NSNumber numberWithInt:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"]]
				 forKey:@"displayNum"];
}

-(void)menuWillOpen:(NSMenu *)menu
{
    NSEvent *event = [NSApp currentEvent];
    if([event modifierFlags] & NSEventModifierFlagOption) {
        [menu cancelTracking];
        bool disableStore = [self toggleMenuIconDisabled];
        if (!disableStore)
        {
            // Update the pbCount so we don't enable and have it immediately copy the thing the user was trying to avoid.
            // Code copied from pollPB, which is disabled at this point, so the "should be okay" should still be okay.
            
            // Reload pbCount with the current changeCount
            // Probably poor coding technique, but pollPB should be the only thing messing with pbCount, so it should be okay
            [pbCount release];
            pbCount = [[NSNumber numberWithInt:[jcPasteboard changeCount]] retain];
        }
        [flycutOperator setDisableStoreTo:disableStore];
    }
    else
    {
        // We need to do a little trick to get the search box functional.  Figure out what is currently active.
        NSString *currRunningApp = @"";
        NSRunningApplication *currApp = nil;
        for (currApp in [[NSWorkspace sharedWorkspace] runningApplications])
            if ([currApp isActive])
            {
                currRunningApp = [currApp localizedName];
                break;
            }

        if ( [currRunningApp rangeOfString:@"Flycut"].location == NSNotFound )
        {
            // We haven't activated Flycut yet.
            currentRunningApplication = [currApp retain]; // Remember what app we came from.
            menuOpenEvent = [event retain]; // So we can send it again to open the menu.
            [menu cancelTracking]; // Prevent the menu from displaying, since activateIgnoringOtherApps would close it anyway.
            [NSApp activateIgnoringOtherApps: YES]; // Required to make the search field firstResponder any good.
            [self performSelector:@selector(reopenMenu) withObject:nil afterDelay:0.2 inModes:[NSArray arrayWithObject:NSRunLoopCommonModes]]; // Because we really do want the menu open.
        }
        else
        {
            // Flycut is now active, so set the first responder once the menu opens.
            [self performSelector:@selector(activateSearchBox) withObject:nil afterDelay:0.2 inModes:[NSArray arrayWithObject:NSRunLoopCommonModes]];
        }
    }
}

-(void)menuDidClose:(NSMenu *)menu
{
    // The method the menu triggers may clear currentRunningApplication, but that method won't be called until after the menu has closed.  Queue a call to the reactivate method that will come up after the method resulting from the menu.
    [self performSelector:@selector(reactivateCurrentRunningApplication) withObject:nil afterDelay:0.0 inModes:[NSArray arrayWithObject:NSRunLoopCommonModes]];
}

-(void)reactivateCurrentRunningApplication
{
    // Return focus to application that the menu search box stole from.
    if ( nil != currentRunningApplication )
    {
        // But only if the bezel hasn't opened since the menu closed.  This happens if the bezel hotkey is pressed while the menu is open.  The bezel won't display until the menu closes, but will then display.
        if (!isBezelDisplayed)
            [currentRunningApplication activateWithOptions: NSApplicationActivateIgnoringOtherApps];
        // Paste from the bezel in this scenario works fine, so release and forget this resource in both cases.
        [currentRunningApplication release];
        currentRunningApplication = nil;
    }
}

-(bool)toggleMenuIconDisabled
{
    // Toggles the "disabled" look of the menu icon.  Returns if the icon looks disabled or not, allowing the caller to decide if anything is actually being disabled or if they just wanted the icon to be a status display.
    if (nil == statusItemText)
    {
        statusItemText = statusItem.button.title;
        statusItemImage = statusItem.button.image;
        statusItem.button.title = @"";
        statusItem.button.image = [NSImage imageNamed:@"com.generalarcade.flycut.xout.16.png"];
        return true;
    }
    else
    {
        statusItem.button.title = statusItemText;
        statusItem.button.image = statusItemImage;
        statusItemText = nil;
        statusItemImage = nil;
    }
    return false;
}

- (void)reopenMenu
{
    [NSApp sendEvent:menuOpenEvent];
    [menuOpenEvent release];
    menuOpenEvent = nil;
}

- (void)activateSearchBox
{
    menuFirstResponder = [[searchBox window] firstResponder]; // So we can return control to normal menu function if the user presses an arrow key.
    [[searchBox window] makeFirstResponder:searchBox]; // So the search box works.
}

-(IBAction) activateAndOrderFrontStandardAboutPanel:(id)sender
{
    [currentRunningApplication release];
    currentRunningApplication = nil; // So it doesn't get pulled foreground atop the about panel.
    [[NSApplication sharedApplication] activateIgnoringOtherApps:YES];
    [[NSApplication sharedApplication] orderFrontStandardAboutPanel:sender];
}

-(IBAction) setBezelAlpha:(id)sender
{
	// In a masterpiece of poorly-considered design--because I want to eventually 
	// allow users to select from a variety of bezels--I've decided to create the
	// bezel programatically, meaning that I have to go through AppController as
	// a cutout to allow the user interface to interact w/the bezel.
	[bezel setAlpha:[sender floatValue]];
}

-(IBAction) setBezelWidth:(id)sender
{
    NSSize bezelSize = NSMakeSize([sender floatValue], bezel.frame.size.height);
	NSRect windowFrame = NSMakeRect( 0, 0, bezelSize.width, bezelSize.height);
	
	// Defer frame update to avoid layout recursion during preference changes
	dispatch_async(dispatch_get_main_queue(), ^{
		[bezel setFrame:windowFrame display:NO];
		[bezel trueCenter];
	});
}

-(IBAction) setBezelHeight:(id)sender
{
    NSSize bezelSize = NSMakeSize(bezel.frame.size.width, [sender floatValue]);
	NSRect windowFrame = NSMakeRect( 0, 0, bezelSize.width, bezelSize.height);
	
	// Defer frame update to avoid layout recursion during preference changes
	dispatch_async(dispatch_get_main_queue(), ^{
		[bezel setFrame:windowFrame display:NO];
		[bezel trueCenter];
	});
}

-(IBAction) setupBezel:(id)sender
{
    NSRect windowFrame = NSMakeRect(0, 0,
                                    [[NSUserDefaults standardUserDefaults] floatForKey:@"bezelWidth"],
                                    [[NSUserDefaults standardUserDefaults] floatForKey:@"bezelHeight"]);
    bezel = [[BezelWindow alloc] initWithContentRect:windowFrame
                                           styleMask:NSWindowStyleMaskBorderless
                                             backing:NSBackingStoreBuffered
                                               defer:NO
                                          showSource:[[NSUserDefaults standardUserDefaults] boolForKey:@"displayClippingSource"]];

    [bezel trueCenter];
    [bezel setDelegate:self];
}

-(IBAction) switchMenuIcon:(id)sender
{
    [self switchMenuIconTo: [sender indexOfSelectedItem]];
}

-(void) switchMenuIconTo:(int)number
{
    if (number == 1 ) {
        statusItem.button.title = @"";
        statusItem.button.image = [NSImage imageNamed:@"com.generalarcade.flycut.black.16.png"];
    } else if (number == 2 ) {
        statusItem.button.image = nil;
        statusItem.button.title = [NSString stringWithFormat:@"%C",0x2704];
    } else if ( number == 3 ) {
        statusItem.button.image = nil;
        statusItem.button.title = [NSString stringWithFormat:@"%C",0x2702];
    } else {
        statusItem.button.title = @"";
        statusItem.button.image = [NSImage imageNamed:@"com.generalarcade.flycut.16.png"];
    }
}

-(NSDictionary*) checkPreferencesChanges:(NSDictionary*)changes
{
	if ( [changes valueForKey:@"rememberNum"] )
		[self checkRememberNumPref:[[NSUserDefaults standardUserDefaults] integerForKey:@"rememberNum"]
				   forPrimaryStore:YES];
	if ( [changes valueForKey:@"favoritesRememberNum"] )
		[self checkFavoritesRememberNumPref:[[NSUserDefaults standardUserDefaults] integerForKey:@"favoritesRememberNum"]];
	return nil;
}

-(IBAction) setRememberNumPref:(id)sender
{
	[self checkRememberNumPref:[sender intValue] forPrimaryStore:YES];
}

-(int) checkRememberNumPref:(int)newRemember forPrimaryStore:(BOOL) isPrimaryStore
{
	int oldRemember = [flycutOperator rememberNum];
	int setRemember = [flycutOperator setRememberNum:newRemember forPrimaryStore:YES];

	if ( isPrimaryStore )
	{
		if ( setRemember == oldRemember )
		{
			[self updateMenu];
		}
		else if ( setRemember < oldRemember )
		{
			// Trim down the number displayed in the menu if it is greater than the new
			// number to remember.
			if ( isPrimaryStore ) {
				if ( setRemember < [[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] ) {
					[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithInt:setRemember]
															 forKey:@"displayNum"];
					[self updateMenu];
				}
			}
		}
	}
}

-(IBAction) setFavoritesRememberNumPref:(id)sender
{
	[self checkFavoritesRememberNumPref:[sender intValue]];
}

-(void) checkFavoritesRememberNumPref:(int)newRemember
{
	[flycutOperator switchToFavoritesStore];
	[self checkRememberNumPref:newRemember forPrimaryStore:NO];
	[flycutOperator restoreStashedStore];
}

-(IBAction) setDisplayNumPref:(id)sender
{
	[self updateMenu];
}

-(NSTextField*) preferencePanelSliderLabelForText:(NSString*)text aligned:(NSTextAlignment)alignment andFrame:(NSRect)frame
{
	NSTextField *newLabel = [[NSTextField alloc] initWithFrame:frame];
	newLabel.editable = NO;
	[newLabel setAlignment:alignment];
	[newLabel setBordered:NO];
	[newLabel setDrawsBackground:NO];
	[newLabel setFont:[NSFont labelFontOfSize:10]];
	[newLabel setStringValue:text];
	return newLabel;
}

-(NSBox*) preferencePanelSliderRowForText:(NSString*)title withTicks:(int)ticks minText:(NSString*)minText maxText:(NSString*)maxText minValue:(double)min maxValue:(double)max frameMaxY:(int)frameMaxY binding:(NSString*)keyPath action:(SEL)action
{
	NSRect panelFrame = [appearancePanel frame];

	if ( frameMaxY < 0 )
		frameMaxY = panelFrame.size.height-8;

	int height = 63;

	NSBox *newRow = [[NSBox alloc] initWithFrame:NSMakeRect(0, frameMaxY-height, panelFrame.size.width-10, height)];
	[newRow setTitlePosition:NSNoTitle];
	[newRow setTransparent:YES];

    [newRow addSubview:[self preferencePanelSliderLabelForText:title aligned:NSTextAlignmentNatural andFrame:NSMakeRect(8, 25, 100, 25)]];

    [newRow addSubview:[self preferencePanelSliderLabelForText:minText aligned:NSTextAlignmentLeft andFrame:NSMakeRect(113, 0, 151, 25)]];
    [newRow addSubview:[self preferencePanelSliderLabelForText:maxText aligned:NSTextAlignmentRight andFrame:NSMakeRect(109+310-151-4, 0, 151, 25)]];

	NSSlider *newControl = [[NSSlider alloc] initWithFrame:NSMakeRect(109, 29, 310, 25)];

	newControl.numberOfTickMarks=ticks;
	[newControl setMinValue:min];
	[newControl setMaxValue:max];

	[self setBinding:@"value" forKey:keyPath andOrAction:action on:newControl];

	[newRow addSubview:newControl];

	return newRow;
}

-(NSBox*) preferencePanelPopUpRowForText:(NSString*)title items:(NSArray*)items frameMaxY:(int)frameMaxY binding:(NSString*)keyPath action:(SEL)action
{
	NSRect panelFrame = [appearancePanel frame];

	if ( frameMaxY < 0 )
		frameMaxY = panelFrame.size.height-8;

	int height = 40;

	NSBox *newRow = [[NSBox alloc] initWithFrame:NSMakeRect(0, frameMaxY-height+5, panelFrame.size.width-10, height)];
	[newRow setTitlePosition:NSNoTitle];
	[newRow setTransparent:YES];

    [newRow addSubview:[self preferencePanelSliderLabelForText:title aligned:NSTextAlignmentNatural andFrame:NSMakeRect(8, -2, 100, 25)]];

	NSPopUpButton *newControl = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(109, 4, 150, 25) pullsDown:NO];

	[newControl addItemsWithTitles:items];

	[self setBinding:@"selectedIndex" forKey:keyPath andOrAction:action on:newControl];

	[newRow addSubview:newControl];

	return newRow;
}

-(NSBox*) preferencePanelCheckboxRowForText:(NSString*)title frameMaxY:(int)frameMaxY binding:(NSString*)keyPath action:(SEL)action
{
	NSRect panelFrame = [appearancePanel frame];

	if ( frameMaxY < 0 )
		frameMaxY = panelFrame.size.height-8;

	int height = 40;

	NSBox *newRow = [[NSBox alloc] initWithFrame:NSMakeRect(0, frameMaxY-height+5, panelFrame.size.width-10, height)];
	[newRow setTitlePosition:NSNoTitle];
	[newRow setTransparent:YES];

	NSButton *newControl = [[NSButton alloc] initWithFrame:NSMakeRect(8, 4, panelFrame.size.width-20, 25)];

    [newControl setButtonType:NSButtonTypeSwitch];
	[newControl setTitle:title];

	[self setBinding:@"value" forKey:keyPath andOrAction:action on:newControl];

	[newRow addSubview:newControl];

	return newRow;
}

-(NSBox*) preferencePanelHotkeyRowForText:(NSString*)title recorder:(SRRecorderControl**)recorder frameMaxY:(int)frameMaxY
{
	NSRect panelFrame = [appearancePanel frame];

	if ( frameMaxY < 0 )
		frameMaxY = panelFrame.size.height-8;

	int height = 50; // Increased height for better hotkey recorder visibility

	NSBox *newRow = [[NSBox alloc] initWithFrame:NSMakeRect(0, frameMaxY-height+5, panelFrame.size.width-10, height)];
	[newRow setTitlePosition:NSNoTitle];
	[newRow setTransparent:YES];

    [newRow addSubview:[self preferencePanelSliderLabelForText:title aligned:NSTextAlignmentNatural andFrame:NSMakeRect(8, 15, 180, 25)]];

	*recorder = [[SRRecorderControl alloc] initWithFrame:NSMakeRect(200, 12, 280, 25)]; // Wider recorder control
	[*recorder setDelegate:self];
	[newRow addSubview:*recorder];

	return newRow;
}

-(void)setBinding:(NSString*)binding forKey:(NSString*)keyPath andOrAction:(SEL)action on:(NSControl*)newControl
{
	[newControl bind:binding
			toObject:[NSUserDefaults standardUserDefaults]
		 withKeyPath:keyPath
			 options:[NSDictionary dictionaryWithObject:[NSNumber numberWithBool:YES]
												 forKey:@"NSContinuouslyUpdatesValue"]];
	if ( nil != action )
	{
		[newControl setTarget:self];
		[newControl setAction:action];
	}
}

-(void) buildAppearancesPreferencePanel
{
	NSRect screenFrame = [[NSScreen mainScreen] frame];

	int nextYMax = -1;
	NSView *row = [self preferencePanelSliderRowForText:@"Bezel transparency"
											 withTicks:16
											   minText:@"Lighter"
											   maxText:@"Darker"
											  minValue:0.1
											  maxValue:0.9
											 frameMaxY:nextYMax
											   binding:@"bezelAlpha"
												action:@selector(setBezelAlpha:)];
	[appearancePanel addSubview:row];
	nextYMax = row.frame.origin.y;

	row = [self preferencePanelSliderRowForText:@"Bezel width"
									  withTicks:50
										minText:@"Smaller"
										maxText:@"Bigger"
									   minValue:200
									   maxValue:screenFrame.size.width
									  frameMaxY:nextYMax
										binding:@"bezelWidth"
										 action:@selector(setBezelWidth:)];
	[appearancePanel addSubview:row];
	nextYMax = row.frame.origin.y;

	row = [self preferencePanelSliderRowForText:@"Bezel height"
									  withTicks:50
										minText:@"Smaller"
										maxText:@"Bigger"
									   minValue:200
									   maxValue:screenFrame.size.height
									  frameMaxY:nextYMax
										binding:@"bezelHeight"
										 action:@selector(setBezelHeight:)];
	[appearancePanel addSubview:row];
	nextYMax = row.frame.origin.y;

	row = [self preferencePanelPopUpRowForText:@"Menu item icon"
										 items:[NSArray arrayWithObjects:
												@"Flycut icon",
												@"Black Flycut icon",
												@"White scissors",
												@"Black scissors",nil]
									 frameMaxY:nextYMax
									   binding:@"menuIcon"
										action:@selector(switchMenuIcon:)];
	[appearancePanel addSubview:row];
	nextYMax = row.frame.origin.y;

	// Add search hotkey recorder - moved up for better visibility
	row = [self preferencePanelHotkeyRowForText:@"Search clipboard hotkey:" recorder:&searchRecorder frameMaxY:nextYMax];
	[appearancePanel addSubview:row];
	nextYMax = row.frame.origin.y;

//	row = [self preferencePanelCheckboxRowForText:@"Animate bezel appearance"
//										frameMaxY:nextYMax
//										  binding:@"popUpAnimation"
//										   action:nil];
//	[appearancePanel addSubview:row];
//	nextYMax = row.frame.origin.y;

    row = [self preferencePanelCheckboxRowForText:@"Show clipping source app and time"
                                        frameMaxY:nextYMax
                                          binding:@"displayClippingSource"
                                           action:@selector(setupBezel:)];
    [appearancePanel addSubview:row];
    nextYMax = row.frame.origin.y;
#ifdef SANDBOXING
    // Hide the Save Clippings preferences. These work fine when sandboxed. They just save to somwehere under ~/Library/Containers. If SANDBOXING isn't set, automatic saving of forgotten clippings will go somewhere under ~/Library/Containers while manual saving (s or S in the bezel) will open an NSSavePanel to prompt the user to pick.
    forgottenItemLabel.hidden = YES;
    forgottenClippingsCheckbox.hidden = YES;
    forgottenFavoritesCheckbox.hidden = YES;
    savingSectionLabel.hidden = YES;
    saveToLocationButton.hidden = YES;
    autoSaveToLocationButton.hidden = YES;
    saveFromBezelToLabel.hidden = YES;
#endif
    if ([AppController isAppSandboxed]) {
        // Saving to a prior-selected location while sandboxed would be unpleasant, so these really should be disabled always when sandboxed but can still show where the saves happen so the user knows what to expect.
        saveToLocationButton.enabled = NO;
        [saveToLocationButton setTitle:@"Ask User"];
        autoSaveToLocationButton.enabled = NO;
        [autoSaveToLocationButton setTitle:@"App Sandbox"];
    }
}

-(IBAction) showPreferencePanel:(id)sender
{
    [currentRunningApplication release];
    currentRunningApplication = nil; // So it doesn't get pulled foreground atop the preference panel.
	if ([prefsPanel respondsToSelector:@selector(setCollectionBehavior:)])
		[prefsPanel setCollectionBehavior:NSWindowCollectionBehaviorCanJoinAllSpaces];
	[NSApp activateIgnoringOtherApps: YES];
    
    // Make preferences window larger and more modern-looking
    NSRect currentFrame = [prefsPanel frame];
    NSSize newSize = NSMakeSize(720, 700); // Increased width and height for hotkey recorder visibility
    NSRect newFrame = NSMakeRect(currentFrame.origin.x, currentFrame.origin.y, newSize.width, newSize.height);
    
    // Adjust position to keep window centered
    newFrame.origin.x = currentFrame.origin.x - (newSize.width - currentFrame.size.width) / 2;
    newFrame.origin.y = currentFrame.origin.y - (newSize.height - currentFrame.size.height) / 2;
    
    [prefsPanel setFrame:newFrame display:YES animate:YES];
	[prefsPanel makeKeyAndOrderFront:self];
	NSString *fileRoot = [[NSBundle mainBundle] pathForResource:@"acknowledgements" ofType:@"txt"];
	NSString *contents = [NSString stringWithContentsOfFile:fileRoot
												   encoding:NSUTF8StringEncoding
													  error:NULL];
	[acknowledgementsView setString:contents];
	if (![AppController isAppSandboxed]) {
		NSURL* saveToLocation = [[NSUserDefaults standardUserDefaults] URLForKey:@"saveToLocation"];
		if (saveToLocation) {
			[saveToLocationButton setTitle:[saveToLocation lastPathComponent]];
		}
		NSURL* autoSaveToLocation = [[NSUserDefaults standardUserDefaults] URLForKey:@"autoSaveToLocation"];
		if (autoSaveToLocation) {
			[autoSaveToLocationButton setTitle:[autoSaveToLocation lastPathComponent]];
		}
	}
	[flycutOperator willShowPreferences];
}

-(IBAction)toggleLoadOnStartup:(id)sender {
	// Since the control in Interface Builder is bound to User Defaults and sends this action, this method is called after User Defaults already reflects the newly-selected state and merely conveys that value to the relevant mechanisms rather than acting to negate the User Defaults state.
	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"loadOnStartup"] ) {
        // FIXME: Should ask Gennadii if the "#ifdef SANDBOXING" should be removed and replaced with "if ([AppController isAppSandboxed])"
#ifdef SANDBOXING
        SMLoginItemSetEnabled((__bridge CFStringRef)kFlycutHelperId, YES);
#else
    [UKLoginItemRegistry addLoginItemWithPath:[[NSBundle mainBundle] bundlePath] hideIt:NO];
#endif
	} else {
        // FIXME: Should ask Gennadii if the "#ifdef SANDBOXING" should be removed and replaced with "if ([AppController isAppSandboxed])"
#ifdef SANDBOXING
        SMLoginItemSetEnabled((__bridge CFStringRef)kFlycutHelperId, NO);
#else
		[UKLoginItemRegistry removeLoginItemWithPath:[[NSBundle mainBundle] bundlePath]];
#endif
	}
}

- (void)restoreStashedStoreAndUpdate
{
    if ([flycutOperator restoreStashedStore])
    {
        [bezel setColor:NO];
        [self updateBezel];
    }
}

- (void)pasteFromStack
{
	NSLog(@"pasteFromStack called");
	NSString *content = [flycutOperator getPasteFromStackPosition];
	if ( nil != content ) {
		NSLog(@"Content found, adding to pasteboard and preparing to paste: %@", [content substringToIndex:MIN(content.length, 50)]);
		[self addClipToPasteboard:content];
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
		[self performSelector:@selector(fakeCommandV) withObject:nil afterDelay:0.2];
	} else {
		NSLog(@"No content found in stack position");
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
	}
    [self restoreStashedStoreAndUpdate];
}

- (void)moveItemAtStackPositionToTopOfStack
{
	if ( [flycutOperator stackPositionIsInBounds] ) {
		[self pasteIndexAndUpdate: [flycutOperator stackPosition]];
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
	} else {
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
	}
}

- (void)pasteIndexAndUpdate:(int) position {
    // If there is an active search, we need to map the menu index to the stack position.
    NSString* search = [searchBox stringValue];
    if ( nil != search && 0 != search.length )
    {
        NSArray *mapping = [flycutOperator previousIndexes:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:search];
        position = [mapping[position] intValue];
    }

    NSString *content = [flycutOperator getPasteFromIndex: position];
    if ( nil != content )
    {
        [self addClipToPasteboard:content];
        [self updateMenu];
	}
}

- (void)metaKeysReleased
{
	NSLog(@"metaKeysReleased called - isBezelPinned: %@", isBezelPinned ? @"YES" : @"NO");
	if ( ! isBezelPinned ) {
		[self pasteFromStack];
	}
}

- (void)windowDidResignKey:(NSNotification *)notification {
	if ( isBezelPinned ) {
		[self hideApp];
	}
}

-(void)fakeKey:(NSNumber*) keyCode withCommandFlag:(BOOL) setFlag
	/*" +fakeKey synthesizes keyboard events. "*/
{     
    CGEventSourceRef sourceRef = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState);
    if (!sourceRef)
    {
        DLog(@"No event source");
        return;
    }
    CGKeyCode veeCode = (CGKeyCode)[keyCode intValue];
    CGEventRef eventDown = CGEventCreateKeyboardEvent(sourceRef, veeCode, true);
    if ( setFlag )
        CGEventSetFlags(eventDown, kCGEventFlagMaskCommand|0x000008); // some apps want bit set for one of the command keys
    CGEventRef eventUp = CGEventCreateKeyboardEvent(sourceRef, veeCode, false);
    CGEventPost(kCGHIDEventTap, eventDown);
    CGEventPost(kCGHIDEventTap, eventUp);
    CFRelease(eventDown);
    CFRelease(eventUp);
    CFRelease(sourceRef);
}

/*" +fakeCommandV synthesizes keyboard events for Cmd-v Paste shortcut. "*/
-(void)fakeCommandV { 
    NSLog(@"fakeCommandV called - attempting to paste");
    
    // Check if we have accessibility permissions
    BOOL accessibilityEnabled = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)@{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES});
    
    if (!accessibilityEnabled) {
        NSLog(@"Accessibility permissions not granted - cannot simulate keystrokes");
        // Show alert to user
        dispatch_async(dispatch_get_main_queue(), ^{
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"Accessibility Access Required";
            alert.informativeText = @"Flycut needs accessibility access to automatically paste. Please grant access in System Preferences > Security & Privacy > Privacy > Accessibility.";
            [alert addButtonWithTitle:@"OK"];
            [alert runModal];
        });
        return;
    }
    
    [self fakeKey:[srTransformer reverseTransformedValue:@"V"] withCommandFlag:TRUE]; 
}

/*" +fakeDownArrow synthesizes keyboard events for the down-arrow key. "*/
-(void)fakeDownArrow { [self fakeKey:@125 withCommandFlag:FALSE]; }

/*" +fakeUpArrow synthesizes keyboard events for the up-arrow key. "*/
-(void)fakeUpArrow { [self fakeKey:@126 withCommandFlag:FALSE]; }

// Perform the search and display updated results when the user types.
-(void)controlTextDidChange:(NSNotification *)aNotification
{
    NSString* search = [searchBox stringValue];
    [self updateMenuContaining:search];
}

// Perform the search and display updated results when the search field performs its action.
-(IBAction)searchItems:(id)sender
{
    NSString* search = [searchBox stringValue];
    [self updateMenuContaining:search];
}

// Catch keystrokes in the search field and look for arrows.
-(BOOL)control:(NSControl *)control textView:(NSTextView *)fieldEditor doCommandBySelector:(SEL)commandSelector
{
    // Handle menu search box navigation
    if (control == searchBox) {
        if( commandSelector == @selector(moveUp:) )
        {
            [[searchBox window] makeFirstResponder:menuFirstResponder];
            [self fakeUpArrow];
            return YES;    // We handled this command; don't pass it on
        }
        if( commandSelector == @selector(moveDown:) )
        {
            [[searchBox window] makeFirstResponder:menuFirstResponder];
            [self fakeDownArrow];
            return YES;    // We handled this command; don't pass it on
        }
    }
    // Handle search window navigation
    else if (control == searchWindowSearchField) {
        if( commandSelector == @selector(moveUp:) )
        {
            NSInteger currentRow = [searchWindowTableView selectedRow];
            NSInteger newRow = currentRow <= 0 ? [searchWindowTableView numberOfRows] - 1 : currentRow - 1;
            [searchWindowTableView selectRowIndexes:[NSIndexSet indexSetWithIndex:newRow] byExtendingSelection:NO];
            [searchWindowTableView scrollRowToVisible:newRow];
            return YES;
        }
        if( commandSelector == @selector(moveDown:) )
        {
            NSInteger currentRow = [searchWindowTableView selectedRow];
            NSInteger newRow = currentRow >= [searchWindowTableView numberOfRows] - 1 ? 0 : currentRow + 1;
            [searchWindowTableView selectRowIndexes:[NSIndexSet indexSetWithIndex:newRow] byExtendingSelection:NO];
            [searchWindowTableView scrollRowToVisible:newRow];
            return YES;
        }
        if( commandSelector == @selector(insertNewline:) ) // Enter key
        {
            [self searchWindowItemSelected:nil];
            return YES;
        }
        if( commandSelector == @selector(cancelOperation:) ) // Escape key
        {
            [self hideSearchWindow];
            return YES;
        }
    }

    return NO;    // Default handling of the command
}

-(void)pollPB:(NSTimer *)timer
{
    NSString *type = [jcPasteboard availableTypeFromArray:[NSArray arrayWithObject:NSPasteboardTypeString]];
    if ( [pbCount intValue] != [jcPasteboard changeCount] && ![flycutOperator storeDisabled] ) {
        // Reload pbCount with the current changeCount
        // Probably poor coding technique, but pollPB should be the only thing messing with pbCount, so it should be okay
        [pbCount release];
        pbCount = [[NSNumber numberWithInt:[jcPasteboard changeCount]] retain];
        if ( type != nil ) {
			NSRunningApplication *currRunningApp = nil;
			for (NSRunningApplication *currApp in [[NSWorkspace sharedWorkspace] runningApplications])
				if ([currApp isActive])
					currRunningApp = currApp;
			bool largeCopyRisk = nil != currRunningApp && [[currRunningApp localizedName] rangeOfString:@"Remote Desktop Connection"].location != NSNotFound;

			// Microsoft's Remote Desktop Connection has an issue with large copy actions, which appears to be in the time it takes to transer them over the network.  The copy starts being registered with OS X prior to completion of the transfer, and if the active application changes during the transfer the copy will be lost.  Indicate this time period by toggling the menu icon at the beginning of all RDC trasfers and back at the end.  Apple's Screen Sharing does not demonstrate this problem.
			if (largeCopyRisk)
				[self toggleMenuIconDisabled];

			// In case we need to do a status visual, this will be dispatched out so our thread isn't blocked.
			dispatch_queue_t queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0);
			dispatch_async(queue, ^{

				// This operation blocks until the transfer is complete, though it was was here before the RDC issue was discovered.  Convenient.
                NSString *contents = [jcPasteboard stringForType:type];

				// Toggle back if dealing with the RDC issue.
				if (largeCopyRisk)
					[self toggleMenuIconDisabled];

                if ( contents == nil || [flycutOperator shouldSkip:contents ofType:[jcPasteboard availableTypeFromArray:[NSArray arrayWithObject:NSPasteboardTypeString]] fromAvailableTypes:[jcPasteboard types]] ) {
                   DLog(@"Contents: Empty or skipped");
               } else if ( ! [pbCount isEqualTo:pbBlockCount] ) {
                   [flycutOperator addClipping:contents ofType:type fromApp:[currRunningApp localizedName] withAppBundleURL:currRunningApp.bundleURL.path target:self clippingAddedSelector:@selector(updateMenu)];
               }
            });
        } 
    }
}

- (void)processBezelKeyDown:(NSEvent *)theEvent {
	int newStackPosition;
	// AppControl should only be getting these directly from bezel via delegation
    if ([theEvent type] == NSEventTypeKeyDown) {
		if ([theEvent keyCode] == [mainRecorder keyCombo].code ) {
            if ([theEvent modifierFlags] & NSEventModifierFlagShift) [self stackUp];
			 else [self stackDown];
			return;
		}
		unichar pressed = [[theEvent charactersIgnoringModifiers] characterAtIndex:0];
        NSUInteger modifiers = [theEvent modifierFlags];
		switch (pressed) {
			case 0x1B:
				[self hideApp];
				break;
            case 0xD: // Enter or Return
				[self pasteFromStack];
				break;
			case 0x3:
                [self moveItemAtStackPositionToTopOfStack];
                break;
            case 0x2C: // Comma
                if ( modifiers & NSEventModifierFlagCommand ) {
                    [self showPreferencePanel:nil];
                }
                break;
			case NSUpArrowFunctionKey: 
			case NSLeftArrowFunctionKey: 
            case 0x6B: // k
				[self stackUp];
				break;
			case NSDownArrowFunctionKey: 
			case NSRightArrowFunctionKey:
            case 0x6A: // j
				[self stackDown];
				break;
            case NSHomeFunctionKey:
				if ( [flycutOperator setStackPositionToFirstItem] ) {
					[self updateBezel];
				}
				break;
            case NSEndFunctionKey:
				if ( [flycutOperator setStackPositionToLastItem] ) {
					[self updateBezel];
				}
				break;
            case NSPageUpFunctionKey:
				if ( [flycutOperator setStackPositionToTenMoreRecent] ) {
					[self updateBezel];
				}
				break;
			case NSPageDownFunctionKey:
				if ( [flycutOperator setStackPositionToTenLessRecent] ) {
                    [self updateBezel];
                }
				break;
			case NSBackspaceCharacter:
            case NSDeleteCharacter:
                if ( [flycutOperator clearItemAtStackPosition] ) {
                    [self updateBezel];
                    [self updateMenu];
                }
                break;
            case NSDeleteFunctionKey: break;
			case 0x30: case 0x31: case 0x32: case 0x33: case 0x34: 				// Numeral 
			case 0x35: case 0x36: case 0x37: case 0x38: case 0x39:
				// We'll currently ignore the possibility that the user wants to do something with shift.
				// First, let's set the new stack count to "10" if the user pressed "0"
				newStackPosition = pressed == 0x30 ? 9 : [[NSString stringWithCharacters:&pressed length:1] intValue] - 1;
				if ( [flycutOperator setStackPositionTo: newStackPosition] ) {
					[self fillBezel];
				}
				break;
            case 's': case 'S': // Save / Save-and-delete
                {
                    bool success = [flycutOperator saveFromStack];
                    [self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
                    [self restoreStashedStoreAndUpdate];

                    if ( success ) {
                        if ( modifiers & NSEventModifierFlagShift ) {
                            [flycutOperator clearItemAtStackPosition];
                            [self updateBezel];
                            [self updateMenu];
                        }
                    }
                }
                break;
            case 'f':
                [flycutOperator toggleToFromFavoritesStore];
                [bezel setColor:[flycutOperator favoritesStoreIsSelected]];
                [self updateBezel];
                [self hideBezel];
                [self showBezel];
                break;
            case 'F':
                if ( [flycutOperator saveFromStackToFavorites] )
                {
                    [self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
                    [self restoreStashedStoreAndUpdate];
                    [self updateBezel];
                    [self updateMenu];
                }

                [self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
                break;
            default: // It's not a navigation/application-defined thing, so let's figure out what to do with it.
				DLog(@"PRESSED %d", pressed);
				DLog(@"CODE %ld", (long)[mainRecorder keyCombo].code);
				break;
		}		
    }
}

-(void) processBezelMouseEvents:(NSEvent *)theEvent {
    if (theEvent.type == NSEventTypeScrollWheel) {
        if (theEvent.deltaY > 0.0f) {
            [self stackUp];
        } else if (theEvent.deltaY < 0.0f) {
            [self stackDown];
        }
    } else if (theEvent.type == NSEventTypeLeftMouseUp && theEvent.clickCount == 2) {
        [self pasteFromStack];
    }
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification
{
	// CloudKit notifications disabled - uncomment if you need CloudKit sync
	// [NSApp registerForRemoteNotificationTypes:NSRemoteNotificationTypeNone];// silent push notification!

	//Create our hot keys
	[self toggleMainHotKey:[NSNull null]];
	[self toggleSearchHotKey:[NSNull null]];
}

// Remote Notifications (APN, aka Push Notifications) are only available on apps distributed via the App Store.
// To support building for both distribution channels, include the following two methods to detect if Remote Notifications are available and inform MJCloudKitUserDefaultsSync.
- (void)application:(NSApplication *)application
didRegisterForRemoteNotificationsWithDeviceToken:(NSData *)deviceToken {
	// Forward the token to your provider, using a custom method.
	NSLog(@"Registered for remote notifications.");
//	[[MJCloudKitUserDefaultsSync sharedSync] setRemoteNotificationsEnabled:YES];
}

- (void)application:(NSApplication *)application
didFailToRegisterForRemoteNotificationsWithError:(NSError *)error {
	NSLog(@"Remote notification support is unavailable due to error: %@", error);
//	[[MJCloudKitUserDefaultsSync sharedSync] setRemoteNotificationsEnabled:NO];
}

- (void)application:(NSApplication *)application didReceiveRemoteNotification:(NSDictionary *)userInfo
{
	//[flycutOperator checkCloudKitUpdates];
}

- (void) updateBezel
{
	[flycutOperator adjustStackPositionIfOutOfBounds];
	if ([flycutOperator jcListCount] == 0) { // empty
		[bezel setText:@""];
		[bezel setCharString:@"Empty"];
        [bezel setSource:@""];
        [bezel setDate:@""];
        [bezel setSourceIcon:nil];
	}
	else { // normal
		[self fillBezel];
	}
}

- (void) showBezel
{
	if ( [flycutOperator stackPositionIsInBounds] ) {
		[self fillBezel];
	}
	NSRect mainScreenRect = [NSScreen mainScreen].visibleFrame;
	[bezel setFrame:NSMakeRect(mainScreenRect.origin.x + mainScreenRect.size.width/2 - bezel.frame.size.width/2,
							   mainScreenRect.origin.y + mainScreenRect.size.height/2 - bezel.frame.size.height/2,
							   bezel.frame.size.width,
							   bezel.frame.size.height) display:YES];
	if ([bezel respondsToSelector:@selector(setCollectionBehavior:)])
		[bezel setCollectionBehavior:NSWindowCollectionBehaviorCanJoinAllSpaces];
//	if ([[NSUserDefaults standardUserDefaults] boolForKey:@"popUpAnimation"])
//		[bezel makeKeyAndOrderFrontWithPopEffect];
//	else
    [bezel makeKeyAndOrderFront:self];
	isBezelDisplayed = YES;
}

- (void) hideBezel
{
	[bezel orderOut:nil];
	[bezel setCharString:@"Empty"];
	isBezelDisplayed = NO;
}

-(void)hideApp
{
	isBezelPinned = NO;
	[self hideBezel];
	[NSApp hide:self];
}

- (void) applicationWillResignActive:(NSApplication *)app; {
	// This should be hidden anyway, but just in case it's not.
	[self hideBezel];
}


- (void)hitMainHotKey:(SGHotKey *)hotKey
{
	if ( ! isBezelDisplayed ) {
		//Do NOT activate the app so focus stays on app the user is interacting with
		//https://github.com/TermiT/Flycut/issues/45
		//[NSApp activateIgnoringOtherApps:YES];
		if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"stickyBezel"] ) {
			isBezelPinned = YES;
		}
		[self showBezel];
	} else {
		[self stackDown];
	}
}

- (IBAction)toggleMainHotKey:(id)sender
{
	if (mainHotKey != nil)
	{
		[[SGHotKeyCenter sharedCenter] unregisterHotKey:mainHotKey];
		[mainHotKey release];
		mainHotKey = nil;
	}
	mainHotKey = [[SGHotKey alloc] initWithIdentifier:@"mainHotKey"
											   keyCombo:[SGKeyCombo keyComboWithKeyCode:[mainRecorder keyCombo].code
																			  modifiers:[mainRecorder cocoaToCarbonFlags: [mainRecorder keyCombo].flags]]];
	[mainHotKey setName: @"Activate Flycut HotKey"]; //This is typically used by PTKeyComboPanel
	[mainHotKey setTarget: self];
	[mainHotKey setAction: @selector(hitMainHotKey:)];
	[[SGHotKeyCenter sharedCenter] registerHotKey:mainHotKey];
}

- (IBAction)toggleICloudSyncSettings:(id)sender
{
	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"syncSettingsViaICloud"] ) {
		NSAlert *alert = [[NSAlert alloc] init];
		[alert setMessageText:@"Warning"];
		[alert addButtonWithTitle:@"Ok"];
		[alert addButtonWithTitle:@"Cancel"];
		[alert setInformativeText:@"Enabling iCloud Settings Sync will overwrite local settings if your iCloud account already has Flycut settings.  If you have never enabled this in Flycut on any computer, your current settings will be retained and loaded into iCloud."];
		if ( [alert runModal] != NSAlertFirstButtonReturn )
		{
			[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
													 forKey:@"syncSettingsViaICloud"];
		}
		[alert release];
		// Add option to overwrite iCloud.
	}
}

- (IBAction)toggleICloudSyncClippings:(id)sender
{
	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"syncClippingsViaICloud"] ) {
		if ( [[NSUserDefaults standardUserDefaults] integerForKey:@"savePreference"] < 2 ) {
			// Must set syncClippingsViaICloud = 2
			NSAlert *alert = [[NSAlert alloc] init];
			[alert setMessageText:@"Settings Change"];
			[alert addButtonWithTitle:@"Ok"];
			[alert addButtonWithTitle:@"Cancel"];
			[alert setInformativeText:@"iCloud Clippings Sync will set 'Save: After each clip'."];
			if ( [alert runModal] == NSAlertFirstButtonReturn )
			{
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithInt:2]
														 forKey:@"savePreference"];
			} else {
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
														 forKey:@"syncClippingsViaICloud"];
			}
			[alert release];
		}
	}

	//[self registerOrDeregisterICloudSync];
}

- (IBAction)setSavePreference:(id)sender
{
	if ( [[NSUserDefaults standardUserDefaults] integerForKey:@"savePreference"] < 2 ) {
		if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"syncClippingsViaICloud"] ) {
			// Must disable syncClippingsViaICloud
			NSAlert *alert = [[NSAlert alloc] init];
			[alert setMessageText:@"Settings Change"];
			[alert addButtonWithTitle:@"Ok"];
			[alert addButtonWithTitle:@"Cancel"];
			[alert setInformativeText:@"Disabling 'Save: After each clip' will disable iCloud Clippings Sync."];

			if ( [alert runModal] == NSAlertFirstButtonReturn )
			{
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]];
			}
			else
			{
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithInt:2]];
			}
			[alert release];
		}
	}
}

- (IBAction)selectSaveLocation:(id)sender {
	// Create and configure the panel.
	NSOpenPanel* panel = [NSOpenPanel openPanel];
	[panel retain];
	[panel setCanChooseFiles:NO];
	[panel setCanChooseDirectories:YES];
	[panel setCanCreateDirectories:YES];
	[panel setAllowsMultipleSelection:NO];
	[panel setMessage:@"Select a directory."];

	// Display the panel attached to the document's window.
	[panel beginSheetModalForWindow:prefsPanel completionHandler:^(NSInteger result){
        if (result == NSModalResponseOK) {
			NSURL* url = [[panel URLs] firstObject];

			[panel release];

			if (!url) { return; }

			if (sender == saveToLocationButton) {
				[[NSUserDefaults standardUserDefaults] setURL:url forKey:@"saveToLocation"];
			}
			else if (sender == autoSaveToLocationButton) {
				[[NSUserDefaults standardUserDefaults] setURL:url forKey:@"autoSaveToLocation"];
			}
			[sender setTitle:[url lastPathComponent]];
		}

	}];
}

-(IBAction)clearClippingList:(id)sender {
    NSInteger choice;
	
	[NSApp activateIgnoringOtherApps:YES];
    
    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:@"Clear Clipping List"];
    [alert setInformativeText:@"Do you want to clear all recent clippings?"];
    [alert addButtonWithTitle:@"Clear"];
    [alert addButtonWithTitle:@"Cancel"];
    choice = [alert runModal];
    [alert release];
	
    // on clear, zap the list and redraw the menu
    if ( choice == NSAlertFirstButtonReturn ) {
        [self restoreStashedStoreAndUpdate]; // Only clear the clipping store.  Never the favorites.
        [flycutOperator clearList];
        [self updateMenu];
		if ( [[NSUserDefaults standardUserDefaults] integerForKey:@"savePreference"] >= 1 ) {
			[flycutOperator saveEngine];
		}
		[bezel setText:@""];
    }
}

-(IBAction)mergeClippingList:(id)sender {
    [flycutOperator mergeList];
    [self updateMenu];
}

- (void)updateMenu {
    dispatch_async(dispatch_get_main_queue(), ^{
    if ( !statusItem || !statusItem.isEnabled )
        return;

        [self updateMenuContaining:nil];
        // Clear the search box whenever the is reason for updateMenu to be called, since the nil call will produce non-searched results.
        [searchBox setStringValue:@""];
        [[[searchBox cell] cancelButtonCell] performClick:self];
    });
}

- (void)updateMenuContaining:(NSString*)search {
	// Use GDC to prevent concurrent modification of the menu, since that would be messy.
	dispatch_async(dispatch_get_main_queue(), ^{
		[jcMenu setMenuChangedMessagesEnabled:NO];

		NSArray *returnedDisplayStrings = [flycutOperator previousDisplayStrings:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:search];

		NSArray *menuItems = [[[jcMenu itemArray] reverseObjectEnumerator] allObjects];

		NSArray *clipStrings = [[returnedDisplayStrings reverseObjectEnumerator] allObjects];

		// Figure out if the number of menu items is changing and add or remove entries as necessary.
		// If we remove all of them and add all new ones, the menu won't redraw if the count is unchanged, so just reuse them by changing their title.
		int oldItems = [menuItems count]-jcMenuBaseItemsCount;
		int newItems = [clipStrings count];
        DLog(@"list=%@, oldItems=%d, newItems=%d", returnedDisplayStrings, oldItems, newItems);
        
        for ( int i = 0; i < oldItems; i++ )
            [jcMenu removeItemAtIndex:0];
        
        for ( int i = 0; i < newItems; i++ )
        {
            NSMenuItem *item;
            item = [[NSMenuItem alloc] initWithTitle:[clipStrings objectAtIndex:i]
                                              action:@selector(processMenuClippingSelection:)
                                       keyEquivalent:@""];
            [item setTarget:self];
            [item setEnabled:YES];
            [jcMenu insertItem:item atIndex:0];
            // Way back in 0.2, failure to release the new item here was causing a quite atrocious memory leak.
            [item release];
        }
    });
}

-(IBAction)processMenuClippingSelection:(id)sender
{
	int index=[[sender menu] indexOfItem:sender];
	[self pasteIndexAndUpdate:index];

	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"menuSelectionPastes"] ) {
		[self performSelector:@selector(hideApp) withObject:nil];
		[self performSelector:@selector(fakeCommandV) withObject:nil afterDelay:0.2];
	}
}

-(void) setPBBlockCount:(NSNumber *)newPBBlockCount
{
    [newPBBlockCount retain];
    [pbBlockCount release];
    pbBlockCount = newPBBlockCount;
}

-(void)addClipToPasteboard:(NSString*)pbFullText
{
    NSArray *pbTypes;
    pbTypes = [NSArray arrayWithObjects:@"NSStringPboardType",NULL];
    
    [jcPasteboard declareTypes:pbTypes owner:NULL];
	
    [jcPasteboard setString:pbFullText forType:@"NSStringPboardType"];
    [self setPBBlockCount:[NSNumber numberWithInt:[jcPasteboard changeCount]]];
}

-(void) stackDown
{
	NSLog(@"stackDown: current position=%d, total count=%d", [flycutOperator stackPosition], [flycutOperator jcListCount]);
	if ( [flycutOperator setStackPositionToOneLessRecent] ) {
		NSLog(@"stackDown: moved to position=%d", [flycutOperator stackPosition]);
		[self fillBezel];
	} else {
		NSLog(@"stackDown: could not move, at limit");
	}
}

-(void) fillBezel
{
    FlycutClipping* clipping = [flycutOperator clippingAtStackPosition];
    [bezel setText:[NSString stringWithFormat:@"%@", [clipping contents]]];
    
    int currentPos = [flycutOperator stackPosition] + 1;
    int totalCount = [flycutOperator jcListCount];
    int displayNum = [[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"];
    
    NSLog(@"fillBezel: showing %d of %d (displayNum pref=%d)", currentPos, totalCount, displayNum);
    [bezel setCharString:[NSString stringWithFormat:@"%d of %d", currentPos, totalCount]];
    
    NSString *localizedName = [clipping appLocalizedName];
    if ( nil == localizedName )
        localizedName = @"";
    NSString* dateString = @"";
    if ( [clipping timestamp] > 0)
        dateString = [dateFormat stringFromDate:[NSDate dateWithTimeIntervalSince1970: [clipping timestamp]]];
    NSImage* icon = nil;
    if (nil != [clipping appBundleURL])
        icon = [[NSWorkspace sharedWorkspace] iconForFile:[clipping appBundleURL]];
    [bezel setSource:localizedName];
    [bezel setDate:dateString];
    [bezel setSourceIcon:icon];
}

-(void) stackUp
{
	NSLog(@"stackUp: current position=%d, total count=%d", [flycutOperator stackPosition], [flycutOperator jcListCount]);
	if ( [flycutOperator setStackPositionToOneMoreRecent] ) {
		NSLog(@"stackUp: moved to position=%d", [flycutOperator stackPosition]);
		[self fillBezel];
	} else {
		NSLog(@"stackUp: could not move, at limit");
	}
}

- (void)setHotKeyPreferenceForRecorder:(SRRecorderControl *)aRecorder {
    if (aRecorder == mainRecorder) {
        NSDictionary *hotKeyDict = @{
            @"keyCode": @([mainRecorder keyCombo].code),
            @"modifierFlags": @([mainRecorder keyCombo].flags)
        };
        [[NSUserDefaults standardUserDefaults] setObject:hotKeyDict
                                                   forKey:@"ShortcutRecorder mainHotkey"];
    } else if (aRecorder == searchRecorder) {
        NSDictionary *hotKeyDict = @{
            @"keyCode": @([searchRecorder keyCombo].code),
            @"modifierFlags": @([searchRecorder keyCombo].flags)
        };
        [[NSUserDefaults standardUserDefaults] setObject:hotKeyDict
                                                   forKey:@"ShortcutRecorder searchHotkey"];
    }
}

- (BOOL)shortcutRecorder:(SRRecorderControl *)aRecorder isKeyCode:(NSInteger)keyCode andFlagsTaken:(NSUInteger)flags reason:(NSString **)aReason {
	return NO;
}

- (void)shortcutRecorder:(SRRecorderControl *)aRecorder keyComboDidChange:(KeyCombo)newKeyCombo {
	NSLog(@"keyComboDidChange called for recorder: %p, code: %ld, flags: %lu", aRecorder, (long)newKeyCombo.code, (unsigned long)newKeyCombo.flags);
	
	if (aRecorder == mainRecorder) {
		[self toggleMainHotKey: aRecorder];
		[self setHotKeyPreferenceForRecorder: aRecorder];
	} else if (aRecorder == searchRecorder) {
		NSLog(@"Search recorder keyCombo changed");
		[self toggleSearchHotKey: aRecorder];
		[self setHotKeyPreferenceForRecorder: aRecorder];
	}
}

- (NSString*)alertWithMessageText:(NSString*)message informationText:(NSString*)information buttonsTexts:(NSArray*)buttons {
	NSAlert *alert = [[NSAlert alloc] init];
	[alert setMessageText:message];
	[buttons enumerateObjectsUsingBlock:^(id  _Nonnull obj, NSUInteger idx, BOOL * _Nonnull stop) {
		[alert addButtonWithTitle:obj];
	}];
	[alert setInformativeText:information];
	NSInteger result = [alert runModal];
	[alert release];
	if ( result < NSAlertFirstButtonReturn || result >= NSAlertFirstButtonReturn + [buttons count] )
		return nil;
	return buttons[result - NSAlertFirstButtonReturn];
}

- (void)beginUpdates {
	needBezelUpdate = NO;
	needMenuUpdate = NO;
}

- (void)endUpdates {
	DLog(@"ending updates");
	if ( needBezelUpdate && isBezelDisplayed )
		[self updateBezel];
	if ( needMenuUpdate )
	{
		DLog(@"launching updateMenu");
		// Timers attach to the run loop of the process, which isn't present on all processes, so we must dispatch to the main queue to ensure we have a run loop for the timer.
		dispatch_async(dispatch_get_main_queue(), ^{
			// Menu updates need to be in NSRunLoopCommonModes to reliably happen.
			[[NSRunLoop currentRunLoop] performSelector:@selector(updateMenu) target:self argument:nil order:0 modes:[NSArray arrayWithObject:NSRunLoopCommonModes]];
		});
	}
	needBezelUpdate = needMenuUpdate = NO;
}

- (void)insertClippingAtIndex:(int)index {
	[self noteChangeAtIndex:index];
}

- (void)deleteClippingAtIndex:(int)index {
	[self noteChangeAtIndex:index];
}

- (void)reloadClippingAtIndex:(int)index {
	[self noteChangeAtIndex:index];
}

- (void)moveClippingAtIndex:(int)index toIndex:(int)newIndex {
	[self noteChangeAtIndex:index];
	[self noteChangeAtIndex:newIndex];
}

- (void)noteChangeAtIndex:(int)index {
	// Always give bezel update, since the count may need updating and the possibility of concurrent user bezel navigation and store changes make need detection risky.
	needBezelUpdate = YES;
	if ( index < [[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] )
		needMenuUpdate = YES;
}

- (void)applicationWillTerminate:(NSNotification *)notification {
	[flycutOperator applicationWillTerminate];
	//Unregister our hot keys (not required)
	[[SGHotKeyCenter sharedCenter] unregisterHotKey: mainHotKey];
	[mainHotKey release];
	mainHotKey = nil;
	[[SGHotKeyCenter sharedCenter] unregisterHotKey: searchHotKey];
	[searchHotKey release];
	searchHotKey = nil;
	[self hideBezel];
	[self hideSearchWindow];
	[[NSDistributedNotificationCenter defaultCenter]
		removeObserver:self
        		  name:@"AppleKeyboardPreferencesChangedNotification"
				object:nil];
	[[NSDistributedNotificationCenter defaultCenter]
		removeObserver:self
				  name:@"AppleSelectedInputSourcesChangedNotification"
				object:nil];
}

#pragma mark - Search Hotkey Methods

- (IBAction)toggleSearchHotKey:(id)sender
{
	if (searchHotKey != nil)
	{
		[[SGHotKeyCenter sharedCenter] unregisterHotKey:searchHotKey];
		[searchHotKey release];
		searchHotKey = nil;
	}
	
	// Only create hotkey if searchRecorder exists and has a valid combo
	if (searchRecorder && [searchRecorder keyCombo].code != -1) {
		searchHotKey = [[SGHotKey alloc] initWithIdentifier:@"searchHotKey"
												   keyCombo:[SGKeyCombo keyComboWithKeyCode:[searchRecorder keyCombo].code
																				  modifiers:[searchRecorder cocoaToCarbonFlags: [searchRecorder keyCombo].flags]]];
		[searchHotKey setName: @"Search Clipboard HotKey"];
		[searchHotKey setTarget: self];
		[searchHotKey setAction: @selector(hitSearchHotKey:)];
		[[SGHotKeyCenter sharedCenter] registerHotKey:searchHotKey];
	}
}

- (void)hitSearchHotKey:(SGHotKey *)hotKey
{
	NSLog(@"hitSearchHotKey called! isSearchWindowDisplayed: %d", isSearchWindowDisplayed);
	if ( ! isSearchWindowDisplayed ) {
		[self showSearchWindow];
	} else {
		[self hideSearchWindow];
	}
}

#pragma mark - Search Window Methods

- (void)buildSearchWindow
{
	NSLog(@"buildSearchWindow called");
	if (searchWindow) {
		NSLog(@"Search window already exists, returning");
		return; // Already built
	}
	
	// Get appearance settings from user defaults
	CGFloat bezelAlpha = [[NSUserDefaults standardUserDefaults] floatForKey:@"bezelAlpha"];
	CGFloat bezelWidth = [[NSUserDefaults standardUserDefaults] floatForKey:@"bezelWidth"];
	CGFloat bezelHeight = [[NSUserDefaults standardUserDefaults] floatForKey:@"bezelHeight"];
	
	// Use bezel dimensions as base, but ensure minimum size for search window
	CGFloat windowWidth = MAX(bezelWidth + 100, 600);  // At least 600px wide
	CGFloat windowHeight = MAX(bezelHeight + 150, 400); // At least 400px tall
	
	// Create the search window
	NSRect windowFrame = NSMakeRect(0, 0, windowWidth, windowHeight);
	searchWindow = [[NSWindow alloc] initWithContentRect:windowFrame
												styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
												  backing:NSBackingStoreBuffered
													defer:NO];
	
	[searchWindow setTitle:@"Search Clipboard"];
	[searchWindow setLevel:NSFloatingWindowLevel];
	[searchWindow setAlphaValue:1.0 - bezelAlpha + 0.2]; // Slightly more opaque than bezel
	[searchWindow center];
	
	// Create a background view with bezel-like appearance
	NSView *backgroundView = [[NSView alloc] initWithFrame:[[searchWindow contentView] bounds]];
	[backgroundView setWantsLayer:YES];
	backgroundView.layer.backgroundColor = [[NSColor colorWithCalibratedWhite:0.2 alpha:bezelAlpha] CGColor];
	backgroundView.layer.cornerRadius = 10.0;
	[[searchWindow contentView] addSubview:backgroundView];
	[backgroundView release];
	
	// Create the search field
	CGFloat fieldY = windowHeight - 50;
	searchWindowSearchField = [[NSSearchField alloc] initWithFrame:NSMakeRect(20, fieldY, windowWidth - 40, 25)];
	[searchWindowSearchField setTarget:self];
	[searchWindowSearchField setAction:@selector(searchWindowSearchFieldChanged:)];
	[searchWindowSearchField setFont:[NSFont systemFontOfSize:13]];
	[searchWindowSearchField setDelegate:self];  // Set delegate for keyboard handling
	[[searchWindow contentView] addSubview:searchWindowSearchField];
	
	// Create the table view
	CGFloat tableHeight = fieldY - 40;
	NSScrollView *scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(20, 20, windowWidth - 40, tableHeight)];
	[scrollView setHasVerticalScroller:YES];
	[scrollView setAutohidesScrollers:YES];
	[scrollView setBorderType:NSNoBorder];
	[scrollView setDrawsBackground:NO];
	
	searchWindowTableView = [[NSTableView alloc] init];
	[searchWindowTableView setDelegate:self];
	[searchWindowTableView setDataSource:self];
	[searchWindowTableView setTarget:self];
	[searchWindowTableView setDoubleAction:@selector(searchWindowItemSelected:)];
	[searchWindowTableView setBackgroundColor:[NSColor clearColor]];
	[searchWindowTableView setGridStyleMask:NSTableViewGridNone];
	[searchWindowTableView setRowHeight:24];
	[searchWindowTableView setIntercellSpacing:NSMakeSize(0, 2)];
	
	// Add a single column
	NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:@"content"];
	[column setTitle:@"Clipboard Content"];
	[column setWidth:windowWidth - 60];
	[searchWindowTableView addTableColumn:column];
	[column release];
	
	[scrollView setDocumentView:searchWindowTableView];
	[[searchWindow contentView] addSubview:scrollView];
	[scrollView release];
	
	// Set up window delegate
	[searchWindow setDelegate:self];
}

- (void)showSearchWindow
{
	// Rebuild window if appearance settings changed (but don't leak memory)
	if (searchWindow) {
		[searchResults release];
		searchResults = nil;
		[searchWindow orderOut:nil];
		[searchWindow release];
		searchWindow = nil;
		searchWindowSearchField = nil;  // Don't release this, it's owned by the window
		searchWindowTableView = nil;   // Don't release this, it's owned by the scroll view
	}
	
	if (!searchWindow) {
		[self buildSearchWindow];
	}
	
	[self updateSearchResults];
	[searchWindow makeKeyAndOrderFront:self];
	[searchWindow makeFirstResponder:searchWindowSearchField];
	isSearchWindowDisplayed = YES;
}

- (void)hideSearchWindow
{
	if (searchWindow) {
		[searchWindow orderOut:nil];
	}
	isSearchWindowDisplayed = NO;
}

- (IBAction)searchWindowSearchFieldChanged:(id)sender
{
	[self updateSearchResults];
}

- (void)updateSearchResults
{
	NSString *searchText = [searchWindowSearchField stringValue];
	
	// Release previous results
	[searchResults release];
	
	if (!searchText || [searchText length] == 0) {
		// Show all items
		searchResults = [flycutOperator previousDisplayStrings:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:nil];
	} else {
		// Search for matching items
		searchResults = [flycutOperator previousDisplayStrings:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:searchText];
	}
	
	[searchResults retain];
	[searchWindowTableView reloadData];
	
	// Auto-select first row for keyboard navigation
	if ([searchResults count] > 0) {
		[searchWindowTableView selectRowIndexes:[NSIndexSet indexSetWithIndex:0] byExtendingSelection:NO];
	}
}

- (IBAction)searchWindowItemSelected:(id)sender
{
	NSInteger selectedRow = [searchWindowTableView selectedRow];
	if (selectedRow < 0) {
		selectedRow = 0; // Default to first item if none selected
	}
	
	if (selectedRow < [searchResults count]) {
		// Get the content and paste it like bezel does
		NSString* searchText = [searchWindowSearchField stringValue];
		NSArray *mapping = nil;
		int position = (int)selectedRow;
		
		if (searchText && [searchText length] > 0) {
			mapping = [flycutOperator previousIndexes:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:searchText];
			position = [mapping[selectedRow] intValue];
		}
		
		NSString *content = [flycutOperator getPasteFromIndex:position];
		if (content) {
			[self addClipToPasteboard:content];
			[self updateMenu]; // Update menu like bezel does
			[self hideSearchWindow];
			
			// Always paste immediately (like bezel behavior), ignore menuSelectionPastes preference
			[self performSelector:@selector(fakeCommandV) withObject:nil afterDelay:0.2];
		}
	}
}

#pragma mark - Search Window Table View Data Source & Delegate

- (NSInteger)numberOfRowsInTableView:(NSTableView *)tableView
{
	if (tableView == searchWindowTableView) {
		return searchResults ? [searchResults count] : 0;
	}
	return 0;
}

- (id)tableView:(NSTableView *)tableView objectValueForTableColumn:(NSTableColumn *)tableColumn row:(NSInteger)row
{
	if (tableView == searchWindowTableView && searchResults && row < [searchResults count]) {
		return [searchResults objectAtIndex:row];
	}
	return nil;
}

- (void)tableView:(NSTableView *)tableView willDisplayCell:(id)cell forTableColumn:(NSTableColumn *)tableColumn row:(NSInteger)row
{
	if (tableView == searchWindowTableView) {
		// Customize cell appearance to match bezel style
		NSTextFieldCell *textCell = (NSTextFieldCell *)cell;
		[textCell setTextColor:[NSColor whiteColor]];
		[textCell setFont:[NSFont systemFontOfSize:12]];
	}
}

- (BOOL)tableView:(NSTableView *)tableView shouldSelectRow:(NSInteger)row
{
	// Allow selection for keyboard navigation
	return YES;
}

#pragma mark - Search Window Delegate

- (void)windowWillClose:(NSNotification *)notification
{
	if ([notification object] == searchWindow) {
		isSearchWindowDisplayed = NO;
	}
}

- (void) dealloc {
	[bezel release];
	[srTransformer release];
	[searchRecorder release];
	[searchWindow release]; // This will release its subviews automatically
	[searchResults release];
	[super dealloc];
}

@end
