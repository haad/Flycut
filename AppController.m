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
#import "ClipboardGenerationPolicy.h"
#import "FlycutMenuIcon.h"
#import "AccessibilityPromptPolicy.h"
#import "SGHotKey.h"
#import "SGHotKeyCenter.h"
#import "SRRecorderCell.h"
#import "NSWindow+TrueCenter.h"
#import "NSWindow+ULIZoomEffect.h"
#import "FlycutImageStore.h"
//#import "MJCloudKitUserDefaultsSync/MJCloudKitUserDefaultsSync.h"
#import <ApplicationServices/ApplicationServices.h>
#import <CoreFoundation/CoreFoundation.h>
#import <ServiceManagement/ServiceManagement.h>
#import "FlycutPasteKey.h"
#import <Carbon/Carbon.h>

@interface AppController ()
-(void)updateRestoreDefaultButtons;
-(void)updateSaveLocationButtonTitles;
-(void)storeSaveLocation:(NSURL *)url forButton:(NSButton *)button;
@end

// A Restore Default arrow, on every pane: a square of this side, this far
// right of the control it belongs to.
static const CGFloat FlycutRestoreArrowSide = 20.0;
static const CGFloat FlycutRestoreArrowGap = 4.0;

// What VoiceOver says about both hotkey fields (ShortcutRecorder has no
// accessibility support of its own).
static NSString *const FlycutHotkeyRecorderHelp = @"Click or press Space, then type the new shortcut. Escape cancels.";

// VoiceOver reads a cell-based control (slider, stepper, pop-up button, text
// field) through its cell, and the cell does not take the label set on the
// control, so both get it.
static void FlycutSetAccessibilityLabel(NSControl *control, NSString *label)
{
	[control setAccessibilityLabel:label];
	[[control cell] setAccessibilityLabel:label];
}

// Keeps the arrows in step with the values: typing in a General field, a
// bound stepper or field committing through the defaults controller, and the
// Preferences window coming up. Lives as long as the app; holds the
// controller weakly.
@interface FlycutRestoreDefaultsObserver : NSObject
{
	__weak AppController *controller;
}
- (instancetype)initWithController:(AppController *)aController;
@end

@implementation FlycutRestoreDefaultsObserver
- (instancetype)initWithController:(AppController *)aController
{
	self = [super init];
	if (self != nil)
		controller = aController;
	return self;
}
- (void)valuesChanged:(NSNotification *)notification
{
	(void)notification;
	[controller updateRestoreDefaultButtons];
}
- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object change:(NSDictionary *)change context:(void *)context
{
	(void)keyPath; (void)object; (void)change; (void)context;
	[controller updateRestoreDefaultButtons];
}
@end

// Custom search window that handles Cmd-W properly
@interface SearchWindow : NSWindow
@property (weak) AppController *appController;
@end

@implementation SearchWindow

- (void)performClose:(id)sender {
    if (self.appController) {
        [self.appController hideSearchWindow];
    }
}

- (BOOL)performKeyEquivalent:(NSEvent *)theEvent {
    // Handle Cmd-W specifically
    if ([theEvent type] == NSEventTypeKeyDown) {
        NSString *characters = [theEvent charactersIgnoringModifiers];
        NSUInteger modifierFlags = [theEvent modifierFlags];
        
        if ([characters isEqualToString:@"w"] && (modifierFlags & NSEventModifierFlagCommand)) {
            [self performClose:nil];
            return YES;
        }
    }
    
    return [super performKeyEquivalent:theEvent];
}

@end

@interface FCPasteTransaction : NSObject {
@private
	NSRunningApplication *_targetApplication;
	pid_t _targetProcessIdentifier;
	NSUInteger _generation;
	NSUInteger _focusCheckAttempts;
	BOOL _selectionStarted;
	NSString *_selectedPayload;
	NSString *_selectedPayloadType;
	NSData *_selectedPayloadData;
	NSInteger _ownedChangeCount;
	NSArray *_previousPasteboardItems;
	BOOL _clipboardCommitted;
}
@property(nonatomic, readonly, retain) NSRunningApplication *targetApplication;
@property(nonatomic, readonly) pid_t targetProcessIdentifier;
@property(nonatomic, readonly) NSUInteger generation;
@property(nonatomic, assign) NSUInteger focusCheckAttempts;
@property(nonatomic, assign) BOOL selectionStarted;
@property(nonatomic, copy) NSString *selectedPayload;
// An image selection owns one representation instead of text: its type and bytes.
@property(nonatomic, copy) NSString *selectedPayloadType;
@property(nonatomic, copy) NSData *selectedPayloadData;
@property(nonatomic, assign) NSInteger ownedChangeCount;
@property(nonatomic, copy) NSArray *previousPasteboardItems;
// YES once the selection is meant to stay on the clipboard: it was copied on purpose
// (the bezel's copy-only action) or the paste attempt ended without a cancellation.
@property(nonatomic, assign) BOOL clipboardCommitted;
- (id)initWithApplication:(NSRunningApplication *)application
		processIdentifier:(pid_t)processIdentifier
			 generation:(NSUInteger)generation;
- (BOOL)hasSelectedPayload;
@end

@implementation FCPasteTransaction
@synthesize targetApplication = _targetApplication;
@synthesize targetProcessIdentifier = _targetProcessIdentifier;
@synthesize generation = _generation;
@synthesize focusCheckAttempts = _focusCheckAttempts;
@synthesize selectionStarted = _selectionStarted;
@synthesize selectedPayload = _selectedPayload;
@synthesize selectedPayloadType = _selectedPayloadType;
@synthesize selectedPayloadData = _selectedPayloadData;
@synthesize ownedChangeCount = _ownedChangeCount;
@synthesize previousPasteboardItems = _previousPasteboardItems;
@synthesize clipboardCommitted = _clipboardCommitted;

- (id)initWithApplication:(NSRunningApplication *)application
		processIdentifier:(pid_t)processIdentifier
			 generation:(NSUInteger)generation
{
	self = [super init];
	if ( self ) {
		_targetApplication = [application retain];
		_targetProcessIdentifier = processIdentifier;
		_generation = generation;
		_focusCheckAttempts = 0;
		_ownedChangeCount = -1;
	}
	return self;
}

- (BOOL)hasSelectedPayload
{
	return _selectedPayload != nil || _selectedPayloadData != nil;
}

- (void)dealloc
{
	[_previousPasteboardItems release];
	[_selectedPayloadData release];
	[_selectedPayloadType release];
	[_selectedPayload release];
	[_targetApplication release];
	[super dealloc];
}
@end

@interface AppController ()
// Returns the source GIF URL embedded in the clipboard HTML (e.g. Chrome "Copy Image"),
// but only for https URLs that point at a .gif. nil otherwise.
-(NSURL *)animatedGifURLFromPasteboard;
// Asynchronously downloads url and, if it is an animated GIF, adds it as a clipping
// while the clipboard is still at the given generation.
-(void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL pasteboardGeneration:(NSInteger)generation;
// YES while an asynchronously read image may still be added for that clipboard generation.
-(BOOL)isImageCaptureCurrentForGeneration:(NSInteger)generation;
- (NSRunningApplication *)frontmostApplicationForPaste;
- (void)rememberFrontmostApplicationForPaste;
- (BOOL)pasteTransactionIsCurrent:(FCPasteTransaction *)transaction;
- (void)clearPasteTransactionIfCurrent:(FCPasteTransaction *)transaction;
- (void)finishPasteTransactionKeepingSelection:(FCPasteTransaction *)transaction;
- (void)clearRememberedPasteTarget;
- (void)hideAppForPasteTransaction:(FCPasteTransaction *)transaction;
- (void)completePasteInRememberedApplication:(FCPasteTransaction *)transaction;
- (void)postPasteAndClearRememberedApplication:(FCPasteTransaction *)transaction;
- (void)cancelPendingPasteCompletion;
- (NSArray *)snapshotPasteboardItems;
- (void)restorePasteboardForCancelledTransaction:(FCPasteTransaction *)transaction;
- (BOOL)pasteboardIsOwnedByTransaction:(FCPasteTransaction *)transaction;
- (void)hideSearchWindowPreservingPasteTransaction;
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier;
-(void)configureStatusItemInteraction;
-(IBAction)statusItemButtonPressed:(id)sender;
-(NSEvent *)handleStatusItemMouseDown:(NSEvent *)event;
-(void)handleStatusItemEvent:(NSEvent *)event;
-(void)showStatusItemMenu;
-(void)updateMenuBarIcon;
-(void)updateClipboardTrackingMenuItem;
-(void)setClipboardTrackingPaused:(BOOL)paused;
-(IBAction)toggleClipboardTracking:(id)sender;
-(void)setupClipboardTrackingMenuItem;
-(void)refreshMenuIconColorControls;
-(IBAction)toggleMenuIconCustomColors:(id)sender;
-(IBAction)setActiveMenuIconColor:(id)sender;
-(IBAction)setPausedMenuIconColor:(id)sender;
-(NSBox *)preferencePanelMenuIconColorRowWithFrameMaxY:(int)frameMaxY;
-(void)buildGeneralPermissionsPreferenceRow;
-(NSString *)bezelCounterString;
@end

// Clipping items that -updateMenuContaining: has removed from the status menu. jcMenu is
// their only owner (see the -release right after -insertItem: below), so they would be
// deallocated at once - while AppKit may still be about to deliver a click for one of them.
// Keeping the previous generation alive makes such a sender safe to inspect.
static NSArray *sRetiredMenuClippingItems = nil;
static const NSUInteger kPasteTargetActivationCheckLimit = 6;

@implementation AppController


- (id)init
{
	[[NSUserDefaults standardUserDefaults] registerDefaults:[NSDictionary dictionaryWithObjectsAndKeys:
		[NSDictionary dictionaryWithObjects:[NSArray arrayWithObjects:[NSNumber numberWithInt:9],[NSNumber numberWithLong:1179648],nil] forKeys:[NSArray arrayWithObjects:@"keyCode",@"modifierFlags",nil]],
		@"ShortcutRecorder mainHotkey",
		// Search window: Control-Shift-S (keyCode 1 is the S key; Cocoa flags Control|Shift =
		// 393216, stored like the main hotkey's Shift|Command = 1179648).  The old default,
		// Shift-Command-S, is Save As... or Duplicate in most document apps, and the other
		// Command combinations with S are mostly taken as well (Save, Save All, sidebar);
		// Control-Shift-S is in none of the shortcut lists checked.  A value the user has
		// stored, a cleared field included, lives in the user domain and wins over this.
		[NSDictionary dictionaryWithObjects:[NSArray arrayWithObjects:[NSNumber numberWithInt:1],[NSNumber numberWithLong:NSEventModifierFlagControl|NSEventModifierFlagShift],nil] forKeys:[NSArray arrayWithObjects:@"keyCode",@"modifierFlags",nil]],
		@"ShortcutRecorder searchHotkey",
		[NSNumber numberWithInt:10],
		@"displayNum",
		[NSNumber numberWithInt:40],
		@"displayLen",
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
        [NSNumber numberWithBool:YES],
        @"saveForgottenFavorites",
        [NSNumber numberWithBool:NO],
        @"suppressAccessibilityAlert",
        [NSNumber numberWithBool:YES],
        @"captureImages",
        [NSNumber numberWithInt:10240],
        @"maxImageSizeKB",
        // Off by default: this feature issues a network request to a URL taken
        // from copied HTML, which must be an explicit opt-in for a clipboard
        // manager that otherwise never touches the network.
        [NSNumber numberWithBool:NO],
        @"downloadAnimatedGIFs",
        nil]];

	/* For testing, the ability to force initial values of the sync settings:
	[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
											 forKey:@"syncSettingsViaICloud"];
	[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO]
											 forKey:@"syncClippingsViaICloud"];*/

	settingsSyncList = @[@"displayNum",
						 @"displayLen",
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

	clipboardReadQueue = dispatch_queue_create("com.Flycut.clipboardReadQueue", DISPATCH_QUEUE_SERIAL);

	// Initialize search window pointers to nil
	searchWindow = nil;
	searchWindowSearchField = nil;
	searchWindowTableView = nil;
	searchResults = nil;
	isSearchWindowDisplayed = NO;

	[FlycutMenuIcon registerColorDefaults:[NSUserDefaults standardUserDefaults]];

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

- (void)openAccessibilitySettings {
    NSString *urlString;
    NSOperatingSystemVersion ver = [[NSProcessInfo processInfo] operatingSystemVersion];
    if (ver.majorVersion >= 13) {
        urlString = @"x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility";
    } else {
        urlString = @"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility";
    }
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:urlString]];
}

- (void)requestAccessibilityWithPrompt {
    // Ask macOS to present consent asynchronously. The OS decides whether to show
    // a prompt; this call neither grants access nor resumes an aborted paste.
    NSLog(@"[Accessibility] User requested system prompt for accessibility permissions");
    
    NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
    NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
    
    NSDictionary* options = @{(id) (kAXTrustedCheckOptionPrompt): @YES};
    BOOL trusted = AXIsProcessTrustedWithOptions((CFDictionaryRef) (options));
    
    NSLog(@"[Accessibility] After prompt request - Bundle: %@, ID: %@, Trusted: %@", 
          bundlePath, bundleID, trusted ? @"YES" : @"NO");
}

- (void)showAccessibilityAlert {
    NSDictionary* options = @{(id) (kAXTrustedCheckOptionPrompt): @NO};
    BOOL trusted = AXIsProcessTrustedWithOptions((CFDictionaryRef) (options));
    
    // Log context for diagnostics
    NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
    NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
    NSLog(@"[Accessibility] Permission check - Bundle: %@, ID: %@, Trusted: %@",
          bundlePath, bundleID, trusted ? @"YES" : @"NO");
    
    if (&AXIsProcessTrustedWithOptions != NULL && !trusted) {
        // The paste paths (-fakeCommandV, -postCommandVToProcessIdentifier:) gate this
        // explicit paste action once per session.
        // Let macOS own consent and Settings navigation, without a prerequisite alert.
        [self requestAccessibilityWithPrompt];
    }
}


// The code-built rows of the Appearance pane are inset by this much on both
// sides of their content: row labels start at it, and whatever a row puts at
// its right end stops at it.
static const CGFloat FlycutAppearanceRowInset = 8.0;



- (void)checkAndPerformSandboxDataMigration
{
	NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];

	// Already offered migration once — don't ask again.
	if ([defaults boolForKey:@"sandboxMigrationCompleted"])
		return;

	NSString *oldPlistPath = [NSHomeDirectory() stringByAppendingPathComponent:
		@"Library/Containers/com.generalarcade.flycut/Data/Library/Preferences/com.generalarcade.flycut.plist"];

	if (![[NSFileManager defaultManager] fileExistsAtPath:oldPlistPath])
		return;

	// Don't overwrite if the user already has data in the new location.
	if ([defaults objectForKey:@"store"] != nil) {
		[defaults setBool:YES forKey:@"sandboxMigrationCompleted"];
		return;
	}

	NSString *choice = [self alertWithMessageText:@"Migrate Previous Data?"
								 informationText:@"Flycut found settings and clipboard history from a previous version. Would you like to import them?"
									buttonsTexts:@[@"Migrate", @"Don't Migrate"]];

	if ([choice isEqualToString:@"Migrate"]) {
		NSDictionary *oldData = [NSDictionary dictionaryWithContentsOfFile:oldPlistPath];
		if (oldData) {
			for (NSString *key in oldData) {
				[defaults setObject:oldData[key] forKey:key];
			}
			[defaults synchronize];
			NSLog(@"[Flycut] Sandbox data migration completed — %lu keys imported.", (unsigned long)[oldData count]);
		}
	}

	[defaults setBool:YES forKey:@"sandboxMigrationCompleted"];
}

- (void)awakeFromNib
{
	[self checkAndPerformSandboxDataMigration];

	// Log startup diagnostics for accessibility troubleshooting
	NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
	NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
	NSDictionary* options = @{(id) (kAXTrustedCheckOptionPrompt): @NO};
	BOOL initialTrustState = AXIsProcessTrustedWithOptions((CFDictionaryRef) (options));
	
	NSLog(@"[Flycut Startup] Bundle Path: %@", bundlePath);
	NSLog(@"[Flycut Startup] Bundle ID: %@", bundleID);
	NSLog(@"[Flycut Startup] Initial Accessibility Trust State: %@", initialTrustState ? @"TRUSTED" : @"NOT TRUSTED");
	
	[self buildAppearancesPreferencePanel];

	[self buildMainHotkeyRestoreDefaultButton];
	[self buildGeneralRestoreDefaultButtons];
	[self buildGeneralPermissionsPreferenceRow];
	[self buildGeneralAccessibilityLabels];
	[self loadHotkeyRecorderCombos];

	// Initialize the FlycutOperator
	flycutOperator = [[FlycutOperator alloc] init];
	// The operator has registered its defaults; nothing has filtered a copy yet.
	[FlycutOperator carryOverConcealedTypesSetting];
	flycutOperator.delegate = self;
	[flycutOperator setClippingsStoreDelegate:self];
	[flycutOperator setFavoritesStoreDelegate:self];
	[flycutOperator awakeFromNibDisplaying:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"]
						 withDisplayLength:[[NSUserDefaults standardUserDefaults] integerForKey:@"displayLen"]
						  withSaveSelector:@selector(savePreferencesOnDict:)
								 forTarget:self];
	// Creating the image store removes temporary image copies that an earlier Flycut
	// process left behind (it ended without cleaning up), even if no image is used.
	[FlycutImageStore sharedStore];

    [bezel setColor:NO];
    
	// Set up the bezel window
	[self setupBezel:nil];

	// Set up the bezel date formatter
	dateFormat = [[NSDateFormatter alloc] init];
	[dateFormat setDateFormat:@"EEEE, MMMM dd 'at' h:mm a"];

	// Observe the current pasteboard without replacing its contents.
    jcPasteboard = [NSPasteboard generalPasteboard];
    pbCount = [[NSNumber numberWithInt:[jcPasteboard changeCount]] retain];

	// Build the statusbar menu
    statusItem = [[[NSStatusBar systemStatusBar]
            statusItemWithLength:NSVariableStatusItemLength] retain];
    [statusItem setHighlightMode:YES];
	[self setupClipboardTrackingMenuItem];
	[self updateMenuBarIcon];
    [jcMenu setDelegate:self];
	[self configureStatusItemInteraction];
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
	// Assign it to NSRunLoopCommonModes so the timer keeps ticking while the menu is open.  Using a simple NSTimer scheduledTimerWithTimeInterval: would suspend polling during menu tracking.  Note that -pollPB: intentionally skips capture while the menu or search window is open (a new clipping inserted mid-selection would shift the indices and cause the wrong entry to be pasted); the tick still runs so capture resumes promptly, and menuDidClose: performs a catch-up poll.
	[[NSRunLoop currentRunLoop] addTimer:pollPBTimer forMode:NSRunLoopCommonModes];

    // Finish up
	srTransformer = [[[SRKeyCodeTransformer alloc] init] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
    [pollPBTimer fire];
    
    
    // Check if the app is registered as a login item
    SMAppService *loginItem = [SMAppService mainAppService];
    BOOL isEnabled = (loginItem.status == SMAppServiceStatusEnabled);
    [[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:isEnabled]
                                             forKey:@"loadOnStartup"];
//    [self registerOrDeregisterICloudSync];
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
    (void)menu;
    // Freeze clipping capture while the menu is open so the item indices the user sees stay
    // stable until they make a selection (see -pollPB:).
    isMenuOpen = YES;
    [self updateClipboardTrackingMenuItem];
    // Option-click is handled before AppKit starts tracking the menu (pause/resume goes
    // through -setClipboardTrackingPaused:, which also advances the capture epoch).
}

-(void)menuDidClose:(NSMenu *)menu
{
    // Resume clipping capture and immediately pick up anything that landed on the pasteboard
    // while the menu was open (a selection's own paste is ignored via pbBlockCount in -pollPB:).
    isMenuOpen = NO;
    [self pollPB:nil];
}

-(void)configureStatusItemInteraction
{
    NSStatusBarButton *button = [statusItem button];
    [statusItem setMenu:nil];
    [button setTarget:self];
    [button setAction:@selector(statusItemButtonPressed:)];
    [button sendActionOn:(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)];

    if (statusItemMouseDownMonitor != nil) {
        [NSEvent removeMonitor:statusItemMouseDownMonitor];
        [statusItemMouseDownMonitor release];
        statusItemMouseDownMonitor = nil;
    }

    __weak AppController *weakSelf = self;
    statusItemMouseDownMonitor = [[NSEvent
        addLocalMonitorForEventsMatchingMask:(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)
        handler:^NSEvent *(NSEvent *event) {
            AppController *controller = weakSelf;
            if (controller == nil)
                return event;
            return [controller handleStatusItemMouseDown:event];
        }] retain];
}

-(IBAction)statusItemButtonPressed:(id)sender
{
    (void)sender;
    [self showStatusItemMenu];
}

-(NSEvent *)handleStatusItemMouseDown:(NSEvent *)event
{
    NSStatusBarButton *button = [statusItem button];
    if (button == nil || [event window] != [button window])
        return event;

    NSPoint location = [button convertPoint:[event locationInWindow] fromView:nil];
    if (!NSPointInRect(location, [button bounds]))
        return event;

    [self handleStatusItemEvent:event];
    return nil;
}

-(void)handleStatusItemEvent:(NSEvent *)event
{
    NSEventType type = [event type];
    BOOL isMouseDown = event != nil &&
        (type == NSEventTypeLeftMouseDown || type == NSEventTypeRightMouseDown);
    NSEventModifierFlags eventModifiers = [event modifierFlags];
    CGEventFlags liveModifiers = CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState);
    BOOL optionKeyIsDown = (eventModifiers & NSEventModifierFlagOption) != 0 ||
        (liveModifiers & kCGEventFlagMaskAlternate) != 0;

    if (isMouseDown && optionKeyIsDown) {
        [self toggleClipboardTracking:nil];
        return;
    }

    [self showStatusItemMenu];
}

-(void)showStatusItemMenu
{
    if (statusItem == nil || jcMenu == nil)
        return;

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    [statusItem popUpStatusItemMenu:jcMenu];
#pragma clang diagnostic pop
}

-(void)updateMenuBarIcon
{
    BOOL paused = [flycutOperator storeDisabled];
    NSColor *tintColor = [FlycutMenuIcon tintColorForPaused:paused
                                               userDefaults:[NSUserDefaults standardUserDefaults]];
    statusItem.button.title = @"";
    statusItem.button.image = [FlycutMenuIcon imageForPaused:paused tintColor:tintColor];
    statusItem.button.contentTintColor = nil;
    statusItem.button.toolTip = paused ? @"Flycut – Clipboard Tracking Paused" : @"Flycut – Clipboard Tracking Active";
    statusItem.button.accessibilityLabel = paused ? @"Flycut, clipboard tracking paused" : @"Flycut, clipboard tracking active";
}

-(void)updateClipboardTrackingMenuItem
{
    BOOL paused = [flycutOperator storeDisabled];
    [clipboardTrackingMenuItem setTitle:paused ? @"Resume Clipboard Tracking" : @"Pause Clipboard Tracking"];
}

-(void)setClipboardTrackingPaused:(BOOL)paused
{
    BOOL wasPaused = [flycutOperator storeDisabled];
    [flycutOperator setDisableStoreTo:paused];

    // Captures still in flight belong to the previous epoch and are discarded,
    // even when capture is resumed before they finish.
    if (wasPaused != paused)
        clipboardCaptureEpoch += 1;

    // Ignore clipboard changes made intentionally while tracking was paused.
    if (wasPaused && !paused) {
        [pbCount release];
        pbCount = [[NSNumber numberWithInt:[jcPasteboard changeCount]] retain];
    }

    [self updateMenuBarIcon];
    [self updateClipboardTrackingMenuItem];
}

-(IBAction)toggleClipboardTracking:(id)sender
{
    (void)sender;
    [self setClipboardTrackingPaused:![flycutOperator storeDisabled]];
}

-(void)setupClipboardTrackingMenuItem
{
    clipboardTrackingMenuItem = [[NSMenuItem alloc] initWithTitle:@"Pause Clipboard Tracking"
                                                            action:@selector(toggleClipboardTracking:)
                                                     keyEquivalent:@""];
    [clipboardTrackingMenuItem setTarget:self];

    NSInteger insertionIndex = [jcMenu indexOfItemWithTarget:self andAction:@selector(showPreferencePanel:)];
    if (insertionIndex < 0)
        insertionIndex = [jcMenu numberOfItems];
    [jcMenu insertItem:clipboardTrackingMenuItem atIndex:insertionIndex];
    [self updateClipboardTrackingMenuItem];
}

-(void)refreshMenuIconColorControls
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    BOOL enabled = [defaults boolForKey:FlycutMenuIconCustomColorsEnabledKey];
    NSColor *activeColor = [FlycutMenuIcon configuredColorForPaused:NO userDefaults:defaults];
    NSColor *pausedColor = [FlycutMenuIcon configuredColorForPaused:YES userDefaults:defaults];

    [menuIconCustomColorsCheckbox setState:enabled ? NSControlStateValueOn : NSControlStateValueOff];
    [menuIconActiveColorWell setColor:activeColor];
    [menuIconPausedColorWell setColor:pausedColor];
    [menuIconActiveColorWell setEnabled:enabled];
    [menuIconPausedColorWell setEnabled:enabled];
    [menuIconActivePreview setContentTintColor:enabled ? activeColor : nil];
    [menuIconPausedPreview setContentTintColor:enabled ? pausedColor : nil];
}

-(IBAction)toggleMenuIconCustomColors:(id)sender
{
    BOOL enabled = [sender state] == NSControlStateValueOn;
    [[NSUserDefaults standardUserDefaults] setBool:enabled forKey:FlycutMenuIconCustomColorsEnabledKey];
    [self refreshMenuIconColorControls];
    [self updateMenuBarIcon];
}

-(IBAction)setActiveMenuIconColor:(id)sender
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [FlycutMenuIcon setTintColor:[sender color] forPaused:NO userDefaults:defaults];
    [self refreshMenuIconColorControls];
    [self updateMenuBarIcon];
}

-(IBAction)setPausedMenuIconColor:(id)sender
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [FlycutMenuIcon setTintColor:[sender color] forPaused:YES userDefaults:defaults];
    [self refreshMenuIconColorControls];
    [self updateMenuBarIcon];
}

-(NSBox *)preferencePanelMenuIconColorRowWithFrameMaxY:(int)frameMaxY
{
    // One line at the pitch of the checkbox rows above it, every control
    // exactly as high as the checkbox and centred on its line: the color wells
    // use the mini control size (16 pt) and the state labels take the font and
    // title colour of the checkbox itself. The hint below the line is made like
    // the other row labels of this pane (same label factory, so the same font
    // and colour) and starts at their left edge.
    NSRect panelFrame = [appearancePanel frame];
    const int height = 56;
    NSBox *row = [[[NSBox alloc] initWithFrame:NSMakeRect(0, frameMaxY - height + 5,
                                                          panelFrame.size.width - 10, height)] autorelease];
    [row setTitlePosition:NSNoTitle];
    [row setTransparent:YES];

    CGFloat contentWidth = [[row contentView] bounds].size.width;
    const CGFloat rowLabelX = FlycutAppearanceRowInset;  // where every row label of this pane starts
    const CGFloat lineMidY = 32.0;
    const NSSize wellSize = NSMakeSize(32.0, 16.0);  // NSColorWell at NSControlSizeMini
    const CGFloat previewSide = 16.0;                // the menu bar icon's own size

    menuIconCustomColorsCheckbox = [[NSButton alloc] initWithFrame:NSZeroRect];
    [menuIconCustomColorsCheckbox setButtonType:NSButtonTypeSwitch];
    [menuIconCustomColorsCheckbox setTitle:@"Use custom menu bar icon colors"];
    NSFont *checkboxFont = [menuIconCustomColorsCheckbox font];
    NSColor *checkboxTitleColor = [[menuIconCustomColorsCheckbox attributedTitle] attribute:NSForegroundColorAttributeName
                                                                                    atIndex:0
                                                                             effectiveRange:NULL];
    if (checkboxTitleColor == nil)
        checkboxTitleColor = [NSColor controlTextColor];  // NSButtonCell's title colour

    NSTextField *activeLabel = [NSTextField labelWithString:@"Active"];
    NSTextField *pausedLabel = [NSTextField labelWithString:@"Paused"];
    for (NSTextField *label in @[activeLabel, pausedLabel]) {
        [label setFont:checkboxFont];
        [label setTextColor:checkboxTitleColor];
    }
    NSSize activeLabelSize = [activeLabel fittingSize];
    NSSize pausedLabelSize = [pausedLabel fittingSize];

    CGFloat pausedPreviewX = contentWidth - FlycutAppearanceRowInset - previewSide;
    CGFloat pausedColorWellX = pausedPreviewX - 4.0 - wellSize.width;
    CGFloat pausedLabelX = pausedColorWellX - 4.0 - ceil(pausedLabelSize.width);
    CGFloat activePreviewX = pausedLabelX - 14.0 - previewSide;
    CGFloat activeColorWellX = activePreviewX - 4.0 - wellSize.width;
    CGFloat activeLabelX = activeColorWellX - 4.0 - ceil(activeLabelSize.width);

    CGFloat checkboxHeight = [menuIconCustomColorsCheckbox fittingSize].height;
    [menuIconCustomColorsCheckbox setFrame:NSMakeRect(rowLabelX, lineMidY - checkboxHeight / 2.0,
                                                      activeLabelX - rowLabelX - 8.0, checkboxHeight)];
    [menuIconCustomColorsCheckbox setIdentifier:@"menuIconCustomColorsCheckbox"];
    [menuIconCustomColorsCheckbox setTarget:self];
    [menuIconCustomColorsCheckbox setAction:@selector(toggleMenuIconCustomColors:)];
    [row addSubview:menuIconCustomColorsCheckbox];

    [activeLabel setFrame:NSMakeRect(activeLabelX, lineMidY - ceil(activeLabelSize.height) / 2.0,
                                     ceil(activeLabelSize.width), ceil(activeLabelSize.height))];
    [row addSubview:activeLabel];
    menuIconActiveColorWell = [[NSColorWell alloc] initWithFrame:NSMakeRect(activeColorWellX, lineMidY - wellSize.height / 2.0,
                                                                           wellSize.width, wellSize.height)];
    [menuIconActiveColorWell setColorWellStyle:NSColorWellStyleMinimal];
    [menuIconActiveColorWell setControlSize:NSControlSizeMini];
    [menuIconActiveColorWell setContinuous:YES];
    [menuIconActiveColorWell setIdentifier:@"menuIconActiveColorWell"];
    [menuIconActiveColorWell setAccessibilityLabel:@"Active menu bar icon color"];
    [menuIconActiveColorWell setTarget:self];
    [menuIconActiveColorWell setAction:@selector(setActiveMenuIconColor:)];
    [row addSubview:menuIconActiveColorWell];

    [pausedLabel setFrame:NSMakeRect(pausedLabelX, lineMidY - ceil(pausedLabelSize.height) / 2.0,
                                     ceil(pausedLabelSize.width), ceil(pausedLabelSize.height))];
    [row addSubview:pausedLabel];
    menuIconPausedColorWell = [[NSColorWell alloc] initWithFrame:NSMakeRect(pausedColorWellX, lineMidY - wellSize.height / 2.0,
                                                                           wellSize.width, wellSize.height)];
    [menuIconPausedColorWell setColorWellStyle:NSColorWellStyleMinimal];
    [menuIconPausedColorWell setControlSize:NSControlSizeMini];
    [menuIconPausedColorWell setContinuous:YES];
    [menuIconPausedColorWell setIdentifier:@"menuIconPausedColorWell"];
    [menuIconPausedColorWell setAccessibilityLabel:@"Paused menu bar icon color"];
    [menuIconPausedColorWell setTarget:self];
    [menuIconPausedColorWell setAction:@selector(setPausedMenuIconColor:)];
    [row addSubview:menuIconPausedColorWell];

    menuIconActivePreview = [[NSImageView alloc] initWithFrame:NSMakeRect(activePreviewX, lineMidY - previewSide / 2.0,
                                                                         previewSide, previewSide)];
    [menuIconActivePreview setImage:[FlycutMenuIcon imageForPaused:NO]];
    [menuIconActivePreview setImageScaling:NSImageScaleProportionallyUpOrDown];
    [menuIconActivePreview setIdentifier:@"menuIconActivePreview"];
    [menuIconActivePreview setAccessibilityLabel:@"Active menu bar icon preview"];
    [row addSubview:menuIconActivePreview];

    menuIconPausedPreview = [[NSImageView alloc] initWithFrame:NSMakeRect(pausedPreviewX, lineMidY - previewSide / 2.0,
                                                                         previewSide, previewSide)];
    [menuIconPausedPreview setImage:[FlycutMenuIcon imageForPaused:YES]];
    [menuIconPausedPreview setImageScaling:NSImageScaleProportionallyUpOrDown];
    [menuIconPausedPreview setIdentifier:@"menuIconPausedPreview"];
    [menuIconPausedPreview setAccessibilityLabel:@"Paused menu bar icon preview"];
    [row addSubview:menuIconPausedPreview];

    NSTextField *automaticLabel = [self preferencePanelSliderLabelForText:@"Off uses the automatic macOS color."
                                                                  aligned:NSTextAlignmentNatural
                                                                 andFrame:NSZeroRect];
    NSSize automaticSize = [[automaticLabel cell] cellSizeForBounds:NSMakeRect(0, 0, CGFLOAT_MAX, CGFLOAT_MAX)];
    [automaticLabel setFrame:NSMakeRect(rowLabelX, 4, MIN(ceil(automaticSize.width), contentWidth - rowLabelX - FlycutAppearanceRowInset),
                                        ceil(automaticSize.height))];
    [row addSubview:automaticLabel];
    [automaticLabel release];

    [self refreshMenuIconColorControls];
    return row;
}

// Makes the General pane taller by grow points at its bottom. The tab view is
// as tall as the tallest pane, and the General box is tied to it on every
// side; the other panes keep their height at its bottom. UKPrefsPanel fits the
// window to the box when the pane changes; if it already fitted the window to
// this pane, the window follows now.
-(void)growGeneralPaneBy:(CGFloat)grow
{
	NSView *pane = [savingSectionLabel superview];
	NSBox *box = (NSBox *)[pane superview];
	NSView *item = [box superview];
	NSTabView *tabs = (NSTabView *)[item superview];
	if (![tabs isKindOfClass:[NSTabView class]]) {
		tabs = nil;
		for (NSView *view in [[prefsPanel contentView] subviews])
			if ([view isKindOfClass:[NSTabView class]])
				for (NSTabViewItem *tab in [(NSTabView *)view tabViewItems])
					if ([tab view] == item)
						tabs = (NSTabView *)view;
	}
	if (grow <= 0 || ![box isKindOfClass:[NSBox class]] || item == nil || tabs == nil)
		return;
	CGFloat boxHeight = NSHeight([box frame]);
	[tabs setFrameSize:NSMakeSize(NSWidth([tabs frame]), NSHeight([tabs frame]) + grow)];
	// A pane that is not shown gets the tab view's size when it is selected.
	if ([item superview] != tabs)
		[item setFrameSize:NSMakeSize(NSWidth([item frame]), NSHeight([item frame]) + grow)];
	[item layoutSubtreeIfNeeded];
	NSWindow *window = [pane window];
	if (window != nil && NSHeight([[window contentView] frame]) == boxHeight) {
		NSRect windowFrame = [window frame];
		windowFrame.origin.y -= grow;
		windowFrame.size.height += grow;
		[window setFrame:windowFrame display:NO];
	}
}

// The row ends the General pane, below everything the NIB and the builders
// before it put there; -awakeFromNib builds it after them. It is placed from
// the pane as laid out, so rows that a newer XIB adds above it cannot run
// into it, and the pane grows when it would not fit.
-(void)buildGeneralPermissionsPreferenceRow
{
    // The existing General outlet anchors this row without changing the NIB.
    NSView *generalContent = [savingSectionLabel superview];
    if (generalContent == nil)
        return;
    for (NSView *view in [generalContent subviews]) {
        if ([[view identifier] isEqualToString:@"accessibilityPermissionsRow"])
            return;
    }

    // The XIB holds the pane's controls 16 pt from its left and right edges
    // (leading and trailing constraints, which place alignment rects); the
    // button's bezel and the separator line up with them.
    const CGFloat margin = 16;
    NSView *row = [[[NSView alloc] initWithFrame:NSMakeRect(
        margin, 8, NSWidth([generalContent bounds]) - 2 * margin, 38)] autorelease];
    [row setIdentifier:@"accessibilityPermissionsRow"];
    [row setAutoresizingMask:NSViewWidthSizable | NSViewMaxYMargin];

    NSBox *separator = [[[NSBox alloc] initWithFrame:NSMakeRect(
        0, 34, NSWidth([row bounds]), 4)] autorelease];
    [separator setBoxType:NSBoxSeparator];
    [separator setAutoresizingMask:NSViewWidthSizable | NSViewMinYMargin];
    [row addSubview:separator];

    NSButton *button = [[[NSButton alloc] initWithFrame:NSMakeRect(0, 0, 250, 32)] autorelease];
    [button setTitle:@"Check Accessibility Permissions"];
    [button setButtonType:NSButtonTypeMomentaryPushIn];
    [button setBezelStyle:NSBezelStyleRounded];
    [button setFrameOrigin:NSMakePoint(NSMinX([button frame]) - NSMinX([button alignmentRectForFrame:[button frame]]), 0)];
    [button setTarget:self];
    [button setAction:@selector(recheckAccessibility:)];
    [row addSubview:button];
    [generalContent addSubview:row];

    // The separator one section gap (16 pt) below the lowest control shown,
    // read once the pane is laid out: views placed by constraints sit at the
    // pane's origin until then. The row's bottom stays 8 pt above the pane's;
    // the pane grows by what is missing.
    [generalContent layoutSubtreeIfNeeded];
    CGFloat lowest = NSHeight([generalContent bounds]);
    for (NSView *view in [generalContent subviews])
        if (view != row && ![view isHidden])
            lowest = MIN(lowest, NSMinY([view alignmentRectForFrame:[view frame]]));
    CGFloat y = lowest - 16 - NSMaxY([separator alignmentRectForFrame:[separator frame]]);
    if (y < 8) {
        [self growGeneralPaneBy:8 - y];
        y = 8;
    }
    [row setFrameOrigin:NSMakePoint(NSMinX([row frame]), y)];
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
    [self cancelPendingPasteCompletion];
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
	[self updateRestoreDefaultButtons];
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
	[self updateRestoreDefaultButtons];
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
	[self updateRestoreDefaultButtons];
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
	int setRemember = [flycutOperator setRememberNum:newRemember forPrimaryStore:isPrimaryStore];

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

	return setRemember;
}

-(IBAction) setFavoritesRememberNumPref:(id)sender
{
	[self checkFavoritesRememberNumPref:[sender intValue]];
}

-(void) checkFavoritesRememberNumPref:(int)newRemember
{
	BOOL temporarilySwitched = ![flycutOperator favoritesStoreIsSelected];
	if ( temporarilySwitched )
		[flycutOperator switchToFavoritesStore];

	[self checkRememberNumPref:newRemember forPrimaryStore:NO];

	if ( temporarilySwitched )
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

	// The Restore Default arrow ends at the row inset, in one column with the
	// other arrows of this pane; the slider ends one gap before it.
	CGFloat restoreX = NSWidth([[newRow contentView] bounds]) - FlycutAppearanceRowInset - FlycutRestoreArrowSide;
	CGFloat sliderMaxX = restoreX - FlycutRestoreArrowGap;

    [newRow addSubview:[self preferencePanelSliderLabelForText:title aligned:NSTextAlignmentNatural andFrame:NSMakeRect(8, 25, 100, 25)]];

    [newRow addSubview:[self preferencePanelSliderLabelForText:minText aligned:NSTextAlignmentLeft andFrame:NSMakeRect(113, 0, 151, 25)]];
    [newRow addSubview:[self preferencePanelSliderLabelForText:maxText aligned:NSTextAlignmentRight andFrame:NSMakeRect(sliderMaxX-151-4, 0, 151, 25)]];

	NSSlider *newControl = [[NSSlider alloc] initWithFrame:NSMakeRect(109, 29, sliderMaxX - 109, 25)];

	newControl.numberOfTickMarks=ticks;
	[newControl setMinValue:min];
	[newControl setMaxValue:max];
	FlycutSetAccessibilityLabel(newControl, title);

	[self setBinding:@"value" forKey:keyPath andOrAction:action on:newControl];

	[newRow addSubview:newControl];

	NSString *restoreIdentifier = [@"restoreDefault" stringByAppendingString:[[[keyPath substringToIndex:1] uppercaseString] stringByAppendingString:[keyPath substringFromIndex:1]]];
	NSButton *restoreButton = [self restoreDefaultButtonWithIdentifier:restoreIdentifier
	                                               accessibilityLabel:[@"Restore default " stringByAppendingString:[title lowercaseString]]];
	[restoreButton setFrame:NSMakeRect(restoreX, NSMidY([newControl frame]) - FlycutRestoreArrowSide / 2.0,
	                                   FlycutRestoreArrowSide, FlycutRestoreArrowSide)];
	[newRow addSubview:restoreButton];

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

	// Only the search hotkey row is built in code; the main hotkey's field
	// comes from the NIB.
	NSParameterAssert(recorder == &searchRecorder);

	// The recorder keeps its designed height (SRMaxHeight); the label and the
	// Restore Default button are centred on it. It ends where the sliders
	// end, so its arrow stands in their arrows' column.
	CGFloat restoreX = NSWidth([[newRow contentView] bounds]) - FlycutAppearanceRowInset - FlycutRestoreArrowSide;
	*recorder = [[SRRecorderControl alloc] initWithFrame:NSZeroRect];
	[*recorder setFrame:NSMakeRect(200, 14, restoreX - FlycutRestoreArrowGap - 200, 22)];
	[*recorder setDelegate:self];
	[*recorder setAccessibilityElement:YES];
	[*recorder setAccessibilityLabel:[title stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@": "]]];
	[*recorder setAccessibilityHelp:FlycutHotkeyRecorderHelp];
	[newRow addSubview:*recorder];
	CGFloat recorderMidY = NSMidY([*recorder frame]);

	NSTextField *label = [self preferencePanelSliderLabelForText:title aligned:NSTextAlignmentNatural andFrame:NSZeroRect];
	CGFloat labelHeight = ceil([label fittingSize].height);
	[label setFrame:NSMakeRect(8, recorderMidY - labelHeight / 2.0, 180, labelHeight)];
	[newRow addSubview:label];
	[label release];

	NSButton *restoreButton = [self restoreDefaultButtonWithIdentifier:@"restoreDefaultSearchHotkey"
	                                               accessibilityLabel:[@"Restore default " stringByAppendingString:[[title lowercaseString] stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@": "]]]];
	[restoreButton setFrame:NSMakeRect(restoreX, recorderMidY - FlycutRestoreArrowSide / 2.0, FlycutRestoreArrowSide, FlycutRestoreArrowSide)];
	[newRow addSubview:restoreButton];

	return newRow;
}

#pragma mark - Restore Default buttons

// The factory value of a setting is what -init and -[FlycutOperator init]
// registered: the registration domain is the one defaults table, and the
// Restore Default buttons keep no copy of their own.
static id FlycutRegisteredDefault(NSString *key)
{
	return [[[NSUserDefaults standardUserDefaults] volatileDomainForName:NSRegistrationDomain] objectForKey:key];
}

static const NSUInteger FlycutHotkeyModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagOption |
                                                   NSEventModifierFlagControl | NSEventModifierFlagShift;

// "restoreDefaultBezelWidth" <-> "bezelWidth"; the hotkeys keep their ShortcutRecorder keys.
static NSString *FlycutRestoreDefaultsIdentifier(NSString *key)
{
	return [@"restoreDefault" stringByAppendingString:[[[key substringToIndex:1] uppercaseString] stringByAppendingString:[key substringFromIndex:1]]];
}

static NSString *FlycutRestoreDefaultsKey(NSString *identifier)
{
	if ([identifier isEqualToString:@"restoreDefaultMainHotkey"]) return @"ShortcutRecorder mainHotkey";
	if ([identifier isEqualToString:@"restoreDefaultSearchHotkey"]) return @"ShortcutRecorder searchHotkey";
	if (![identifier hasPrefix:@"restoreDefault"] || [identifier length] <= [@"restoreDefault" length])
		return nil;
	NSString *rest = [identifier substringFromIndex:[@"restoreDefault" length]];
	return [[[rest substringToIndex:1] lowercaseString] stringByAppendingString:[rest substringFromIndex:1]];
}

// General settings with a factory value, left to right and top to bottom, and
// what VoiceOver says for their arrow.
static NSArray *FlycutGeneralRestoreKeys(void)
{
	return @[@"rememberNum", @"displayNum", @"favoritesRememberNum", @"skipPboardTypesList", @"skipPasswordLengthsList"];
}

// The two "Save ... to:" folders. Nothing is registered for them: while no
// folder is stored, Flycut saves to the Desktop (-[FlycutOperator
// saveFromStore:atIndex:withPrefix:]).
static NSArray *FlycutFolderRestoreKeys(void)
{
	return @[@"saveToLocation", @"autoSaveToLocation"];
}

static NSString *FlycutGeneralRestoreLabel(NSString *key)
{
	NSDictionary *labels = @{
		@"rememberNum": @"Restore default number of clippings to remember",
		@"displayNum": @"Restore default number of clippings in the menu",
		@"favoritesRememberNum": @"Restore default number of favorites to remember",
		@"skipPboardTypesList": @"Restore default pasteboard types",
		@"skipPasswordLengthsList": @"Restore default password lengths",
		@"saveToLocation": @"Restore default folder for clippings saved from the bezel",
		@"autoSaveToLocation": @"Restore default folder for forgotten clippings",
	};
	return [labels objectForKey:key];
}

static NSString *FlycutDesktopPath(void)
{
	return [NSSearchPathForDirectoriesInDomains(NSDesktopDirectory, NSUserDomainMask, YES) firstObject];
}

// No folder stored, or the Desktop itself, is the default.
static BOOL FlycutIsDesktopFolder(NSURL *url)
{
	if (url == nil)
		return YES;
	return [[[url path] stringByStandardizingPath] isEqualToString:[FlycutDesktopPath() stringByStandardizingPath]];
}

// The two folder buttons share their left edge (the one further right) and
// their width (the wider one's), so their arrows stand in one column. Each
// button's NIB constraint "leading = label.trailing + c" only holds it at
// least that far right, and pulls it left while nothing else holds it.
static void FlycutAlignFolderButtons(NSView *pane, NSButton *first, NSButton *second)
{
	if (first == nil || second == nil || [first superview] != pane || [second superview] != pane ||
	    [first translatesAutoresizingMaskIntoConstraints] || [second translatesAutoresizingMaskIntoConstraints])
		return;
	NSMutableArray *relaxed = [NSMutableArray array];
	for (NSButton *button in @[first, second]) {
		for (NSLayoutConstraint *constraint in [pane constraints]) {
			if ([constraint firstItem] == button && [constraint firstAttribute] == NSLayoutAttributeLeading &&
			    [constraint relation] == NSLayoutRelationEqual && [constraint secondAttribute] == NSLayoutAttributeTrailing) {
				[relaxed addObject:constraint];
				break;
			}
		}
	}
	if ([relaxed count] != 2)
		return;
	for (NSLayoutConstraint *constraint in relaxed) {
		[constraint setActive:NO];
		NSLayoutConstraint *pull = [NSLayoutConstraint constraintWithItem:[constraint firstItem] attribute:NSLayoutAttributeLeading
		                                                        relatedBy:NSLayoutRelationEqual toItem:[constraint secondItem]
		                                                        attribute:NSLayoutAttributeTrailing multiplier:1 constant:[constraint constant]];
		[pull setPriority:NSLayoutPriorityDefaultLow];
		[pane addConstraints:@[
			[NSLayoutConstraint constraintWithItem:[constraint firstItem] attribute:NSLayoutAttributeLeading
			                             relatedBy:NSLayoutRelationGreaterThanOrEqual toItem:[constraint secondItem]
			                             attribute:NSLayoutAttributeTrailing multiplier:1 constant:[constraint constant]],
			pull,
		]];
	}
	[pane addConstraints:@[
		[NSLayoutConstraint constraintWithItem:first attribute:NSLayoutAttributeLeading relatedBy:NSLayoutRelationEqual
		                                toItem:second attribute:NSLayoutAttributeLeading multiplier:1 constant:0],
		[NSLayoutConstraint constraintWithItem:first attribute:NSLayoutAttributeWidth relatedBy:NSLayoutRelationEqual
		                                toItem:second attribute:NSLayoutAttributeWidth multiplier:1 constant:0],
	]];
}

// The NIB control of a pane that is bound to values.<key>.
static NSControl *FlycutBoundControl(NSView *pane, NSString *key, Class kind)
{
	NSString *keyPath = [@"values." stringByAppendingString:key];
	for (NSView *view in [pane subviews]) {
		if ([view isKindOfClass:kind] &&
		    [[[view infoForBinding:NSValueBinding] objectForKey:NSObservedKeyPathKey] isEqualToString:keyPath])
			return (NSControl *)view;
	}
	return nil;
}

static void FlycutCollectRestoreDefaultButtons(NSView *view, NSMutableArray *buttons)
{
	if (view == nil)
		return;
	if ([view isKindOfClass:[NSButton class]] && [[view identifier] hasPrefix:@"restoreDefault"])
		[buttons addObject:view];
	for (NSView *child in [view subviews])
		FlycutCollectRestoreDefaultButtons(child, buttons);
}

// A borderless arrow button next to a setting that has a factory default,
// shown only while the value differs from it.
-(NSButton *)restoreDefaultButtonWithIdentifier:(NSString *)identifier accessibilityLabel:(NSString *)accessibilityLabel
{
	NSImage *image = [NSImage imageWithSystemSymbolName:@"arrow.counterclockwise" accessibilityDescription:@"Restore Default"];
	NSButton *button = [NSButton buttonWithImage:image target:self action:@selector(restoreDefault:)];
	[button setBordered:NO];
	[button setImagePosition:NSImageOnly];
	[button setSymbolConfiguration:[NSImageSymbolConfiguration configurationWithPointSize:12 weight:NSFontWeightRegular]];
	[button setContentTintColor:[NSColor secondaryLabelColor]];
	[button setToolTip:@"Restore Default"];
	[button setAccessibilityLabel:accessibilityLabel];
	[button setIdentifier:identifier];
	[button setHidden:YES];
	[button setEnabled:NO];
	return button;
}

// The Hotkeys pane comes from the NIB; its button is added next to the
// recorder, and the recorder gets the accessibility text the NIB lacks.
-(void)buildMainHotkeyRestoreDefaultButton
{
	NSView *pane = [mainRecorder superview];
	if (pane == nil)
		return;
	for (NSView *view in [pane subviews])
		if ([[view identifier] isEqualToString:@"restoreDefaultMainHotkey"])
			return;

	[mainRecorder setAccessibilityElement:YES];
	[mainRecorder setAccessibilityLabel:@"Main hotkey"];
	[mainRecorder setAccessibilityHelp:FlycutHotkeyRecorderHelp];
	NSRect recorderFrame = [mainRecorder frame];
	NSButton *button = [self restoreDefaultButtonWithIdentifier:@"restoreDefaultMainHotkey"
	                                        accessibilityLabel:@"Restore default main hotkey"];
	[button setFrame:NSMakeRect(NSMaxX(recorderFrame) + FlycutRestoreArrowGap, NSMidY(recorderFrame) - FlycutRestoreArrowSide / 2.0,
	                            FlycutRestoreArrowSide, FlycutRestoreArrowSide)];
	[button setAutoresizingMask:[mainRecorder autoresizingMask]];
	// The help text starts right after the recorder; it says what the arrow
	// does, moves over and grows downwards.
	for (NSView *view in [pane subviews]) {
		NSRect frame = [view frame];
		if (![view isKindOfClass:[NSTextField class]] || NSMinX(frame) < NSMaxX(recorderFrame))
			continue;
		NSTextField *help = (NSTextField *)view;
		NSString *text = [help stringValue];
		NSString *clear = @"click on the \"X\".";
		NSRange end = [text rangeOfString:clear];
		if (end.location != NSNotFound && [text rangeOfString:@"arrow"].location == NSNotFound)
			[help setStringValue:[text stringByReplacingCharactersInRange:end
			                                                    withString:[clear stringByAppendingString:@" To go back to the default, click the arrow that appears next to a changed hotkey."]]];
		CGFloat shift = MAX(0.0, NSMaxX([button frame]) + 8 - NSMinX(frame));
		frame.origin.x += shift;
		frame.size.width -= shift;
		CGFloat neededHeight = ceil([[help cell] cellSizeForBounds:NSMakeRect(0, 0, NSWidth(frame), CGFLOAT_MAX)].height);
		if (neededHeight > NSHeight(frame)) {
			frame.origin.y -= neededHeight - NSHeight(frame);
			frame.size.height = neededHeight;
		}
		[view setFrame:frame];
	}
	[pane addSubview:button];
}

// The NIB gives these controls no accessibility label, so VoiceOver said only
// "stepper", "pop up button" or the field's text. Each gets the label shown
// next to it, in code, so that it also works with an already compiled NIB.
// The number beside a stepper is display-only text that VoiceOver does not
// reach; the stepper's value is that number, so the label makes VoiceOver say
// "Remember, 40, stepper".
-(void)buildGeneralAccessibilityLabels
{
	NSView *pane = [savingSectionLabel superview];
	NSDictionary *steppers = @{@"rememberNum": @"Remember",
	                           @"displayNum": @"Display in menu",
	                           @"favoritesRememberNum": @"Favorites"};
	for (NSString *key in steppers)
		FlycutSetAccessibilityLabel(FlycutBoundControl(pane, key, [NSStepper class]), steppers[key]);
	// The two list fields get names of their own. The checkbox in front of each
	// is a sub-option of "Don't save passwords" in MainMenu.xib ("by data type:",
	// "by length & complexity:"), which alone does not say what the field holds.
	NSDictionary *fields = @{@"skipPboardTypesList": @"Password data types",
	                         @"skipPasswordLengthsList": @"Password lengths"};
	for (NSString *key in fields)
		FlycutSetAccessibilityLabel(FlycutBoundControl(pane, key, [NSTextField class]), fields[key]);
	for (NSView *view in [pane subviews]) {
		NSString *keyPath = [[view infoForBinding:NSSelectedIndexBinding] objectForKey:NSObservedKeyPathKey];
		if ([view isKindOfClass:[NSPopUpButton class]] && [keyPath isEqualToString:@"values.savePreference"])
			FlycutSetAccessibilityLabel((NSPopUpButton *)view, @"Save");
	}
	// The status menu's search field; its menu item is titled "Search...".
	FlycutSetAccessibilityLabel(searchBox, @"Search");
}

// The General pane comes from the NIB and is laid out with constraints. Each
// arrow is tied to the right edge of its field, or of the stepper or folder
// button next to it. The constraint that held the next control at that edge,
// or the field at the pane's right margin, makes room for it; the arrow keeps
// that room while hidden, so nothing moves when it appears.
// Arrows that end a line stand in one column: a field that reaches the right
// margin ends where the right-most stepper ends, so its arrow stands under
// that stepper's arrow. The two folder buttons share their left edge and
// width, so their arrows share a column as well.
-(void)buildGeneralRestoreDefaultButtons
{
	NSView *pane = [savingSectionLabel superview];
	if (pane == nil)
		return;
	NSMutableArray *existing = [NSMutableArray array];
	FlycutCollectRestoreDefaultButtons(pane, existing);
	if ([existing count] > 0)
		return;

	static FlycutRestoreDefaultsObserver *observer = nil;
	if (observer == nil)
		observer = [[FlycutRestoreDefaultsObserver alloc] initWithController:self];
	const CGFloat side = FlycutRestoreArrowSide, gap = FlycutRestoreArrowGap, margin = 16.0;
	FlycutAlignFolderButtons(pane, saveToLocationButton, autoSaveToLocationButton);
	NSMutableArray *heldAtMargin = [NSMutableArray array];  // @[arrow, the constraint holding its field at the margin]
	NSButton *columnArrow = nil;
	CGFloat columnAnchorMaxX = 0.0;
	for (NSString *key in [FlycutGeneralRestoreKeys() arrayByAddingObjectsFromArray:FlycutFolderRestoreKeys()]) {
		BOOL folder = [FlycutFolderRestoreKeys() containsObject:key];
		NSControl *field = folder ? [self saveLocationButtonForKey:key] : FlycutBoundControl(pane, key, [NSTextField class]);
		if (field == nil || [field superview] != pane)
			continue;
		NSView *stepper = folder ? nil : FlycutBoundControl(pane, key, [NSStepper class]);
		NSView *anchor = (stepper != nil && NSMinX([stepper frame]) >= NSMinX([field frame])) ? stepper : field;
		NSButton *button = [self restoreDefaultButtonWithIdentifier:FlycutRestoreDefaultsIdentifier(key)
		                                        accessibilityLabel:FlycutGeneralRestoreLabel(key)];
		[pane addSubview:button];

		if ([anchor translatesAutoresizingMaskIntoConstraints]) {
			// Frame layout: controls to the right on this line move over, or
			// a field reaching the right margin gets shorter.
			CGFloat x = NSMaxX([anchor frame]) + gap;
			CGFloat need = 0.0;
			for (NSView *view in [pane subviews]) {
				if (view == button || view == anchor || NSMinX([view frame]) < NSMaxX([anchor frame]) - 0.5 ||
				    NSMaxY([view frame]) <= NSMinY([field frame]) || NSMinY([view frame]) >= NSMaxY([field frame]))
					continue;
				need = MAX(need, x + side + 8.0 - NSMinX([view frame]));
			}
			if (need > 0.0) {
				for (NSView *view in [pane subviews]) {
					if (view != button && view != anchor && NSMinX([view frame]) >= NSMaxX([anchor frame]) - 0.5 &&
					    NSMaxY([view frame]) > NSMinY([field frame]) && NSMinY([view frame]) < NSMaxY([field frame]))
						[view setFrameOrigin:NSMakePoint(NSMinX([view frame]) + need, NSMinY([view frame]))];
				}
			} else if (anchor == field && x + side > NSWidth([pane bounds]) - margin) {
				NSRect frame = [field frame];
				frame.size.width -= x + side - (NSWidth([pane bounds]) - margin);
				[field setFrame:frame];
				x = NSMaxX(frame) + gap;
			}
			[button setFrame:NSMakeRect(x, NSMidY([field frame]) - side / 2.0, side, side)];
		} else {
			NSLayoutConstraint *margined = nil;
			BOOL followed = NO;
			for (NSLayoutConstraint *constraint in [pane constraints]) {
				if ([constraint relation] != NSLayoutRelationEqual)
					continue;
				id first = [constraint firstItem], second = [constraint secondItem];
				NSLayoutAttribute firstAttribute = [constraint firstAttribute], secondAttribute = [constraint secondAttribute];
				// next.leading = anchor.trailing + c, or the field held at the right margin
				BOOL atMargin = anchor == field && first == pane && firstAttribute == NSLayoutAttributeTrailing &&
				                second == field && secondAttribute == NSLayoutAttributeTrailing;
				if ((second == anchor && secondAttribute == NSLayoutAttributeTrailing && firstAttribute == NSLayoutAttributeLeading) || atMargin) {
					[constraint setConstant:[constraint constant] + side + gap];
					margined = atMargin ? constraint : nil;
					followed = !atMargin;
					break;
				}
				atMargin = anchor == field && first == field && firstAttribute == NSLayoutAttributeTrailing &&
				           second == pane && secondAttribute == NSLayoutAttributeTrailing;
				if ((first == anchor && firstAttribute == NSLayoutAttributeTrailing && secondAttribute == NSLayoutAttributeLeading) || atMargin) {
					[constraint setConstant:[constraint constant] - side - gap];
					margined = atMargin ? constraint : nil;
					followed = !atMargin;
					break;
				}
			}
			if (margined != nil)
				[heldAtMargin addObject:@[button, margined]];
			else if (!followed && !folder && anchor == stepper && NSMaxX([anchor frame]) > columnAnchorMaxX) {
				columnArrow = button;
				columnAnchorMaxX = NSMaxX([anchor frame]);
			}
			[button setTranslatesAutoresizingMaskIntoConstraints:NO];
			[pane addConstraints:@[
				[NSLayoutConstraint constraintWithItem:button attribute:NSLayoutAttributeLeading relatedBy:NSLayoutRelationEqual
				                                toItem:anchor attribute:NSLayoutAttributeTrailing multiplier:1 constant:gap],
				[NSLayoutConstraint constraintWithItem:button attribute:NSLayoutAttributeCenterY relatedBy:NSLayoutRelationEqual
				                                toItem:field attribute:NSLayoutAttributeCenterY multiplier:1 constant:0],
				[NSLayoutConstraint constraintWithItem:button attribute:NSLayoutAttributeWidth relatedBy:NSLayoutRelationEqual
				                                toItem:nil attribute:NSLayoutAttributeNotAnAttribute multiplier:1 constant:side],
				[NSLayoutConstraint constraintWithItem:button attribute:NSLayoutAttributeHeight relatedBy:NSLayoutRelationEqual
				                                toItem:nil attribute:NSLayoutAttributeNotAnAttribute multiplier:1 constant:side],
				[NSLayoutConstraint constraintWithItem:pane attribute:NSLayoutAttributeTrailing relatedBy:NSLayoutRelationGreaterThanOrEqual
				                                toItem:button attribute:NSLayoutAttributeTrailing multiplier:1 constant:margin],
			]];
		}
		if (folder)
			continue;  // a chosen folder updates the arrows itself (-storeSaveLocation:forButton:)
		[[NSNotificationCenter defaultCenter] addObserver:observer selector:@selector(valuesChanged:)
		                                             name:NSControlTextDidChangeNotification object:field];
		// The defaults controller the NIB binds this setting to (not necessarily
		// the shared one) reports stepper clicks, committed typing and direct
		// changes of the stored value.
		NSDictionary *binding = [field infoForBinding:NSValueBinding];
		[[binding objectForKey:NSObservedObjectKey] addObserver:observer
		                                              forKeyPath:[binding objectForKey:NSObservedKeyPathKey]
		                                                 options:0 context:NULL];
	}
	// A field at the margin ends under the right-most stepper instead (only
	// ever shorter), so its arrow stands in that stepper's arrow column.
	if (columnArrow != nil && columnAnchorMaxX + gap + side + margin <= NSWidth([pane bounds])) {
		for (NSArray *entry in heldAtMargin) {
			[(NSLayoutConstraint *)[entry objectAtIndex:1] setActive:NO];
			[pane addConstraint:[NSLayoutConstraint constraintWithItem:[entry objectAtIndex:0] attribute:NSLayoutAttributeLeading
			                                                 relatedBy:NSLayoutRelationEqual toItem:columnArrow
			                                                 attribute:NSLayoutAttributeLeading multiplier:1 constant:0]];
		}
	}
	if ([pane window] != nil)
		[[NSNotificationCenter defaultCenter] addObserver:observer selector:@selector(valuesChanged:)
		                                             name:NSWindowDidBecomeKeyNotification object:[pane window]];
	if (prefsPanel != nil && prefsPanel != [pane window])
		[[NSNotificationCenter defaultCenter] addObserver:observer selector:@selector(valuesChanged:)
		                                             name:NSWindowDidBecomeKeyNotification object:prefsPanel];
	// Values stored before the pane is built show their arrows right away.
	[self updateRestoreDefaultButtons];
}

// We no longer get autosave from ShortcutRecorder, so let's set the recorders by hand.
-(void)loadHotkeyRecorderCombos
{
	NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
	NSDictionary *main = [defaults dictionaryForKey:@"ShortcutRecorder mainHotkey"];
	if ( main )
		[mainRecorder setKeyCombo:SRMakeKeyCombo([[main objectForKey:@"keyCode"] intValue], [[main objectForKey:@"modifierFlags"] intValue])];
	NSDictionary *search = [defaults dictionaryForKey:@"ShortcutRecorder searchHotkey"];
	if ( search && searchRecorder )
		[searchRecorder setKeyCombo:SRMakeKeyCombo([[search objectForKey:@"keyCode"] intValue], [[search objectForKey:@"modifierFlags"] intValue])];
	[self updateRestoreDefaultButtons];
}

-(SRRecorderControl *)restoreDefaultRecorderForIdentifier:(NSString *)identifier
{
	if ([identifier isEqualToString:@"restoreDefaultMainHotkey"]) return mainRecorder;
	if ([identifier isEqualToString:@"restoreDefaultSearchHotkey"]) return searchRecorder;
	return nil;
}

// The registered combination of a hotkey; none registered means no shortcut.
static KeyCombo FlycutRegisteredKeyCombo(NSString *key)
{
	NSDictionary *value = FlycutRegisteredDefault(key);
	if (![value isKindOfClass:[NSDictionary class]] || [value objectForKey:@"keyCode"] == nil)
		return SRMakeKeyCombo(ShortcutRecorderEmptyCode, ShortcutRecorderEmptyFlags);
	return SRMakeKeyCombo([[value objectForKey:@"keyCode"] integerValue], [[value objectForKey:@"modifierFlags"] unsignedIntegerValue]);
}

static BOOL FlycutKeyComboIsRegistered(KeyCombo current, NSString *key)
{
	KeyCombo factory = FlycutRegisteredKeyCombo(key);
	if (factory.code == ShortcutRecorderEmptyCode)
		return current.code == ShortcutRecorderEmptyCode;
	return current.code == factory.code && (current.flags & FlycutHotkeyModifierMask) == (factory.flags & FlycutHotkeyModifierMask);
}

-(NSButton *)saveLocationButtonForKey:(NSString *)key
{
	if ([key isEqualToString:@"saveToLocation"]) return saveToLocationButton;
	if ([key isEqualToString:@"autoSaveToLocation"]) return autoSaveToLocationButton;
	return nil;
}

// A save button shows the name of its stored folder, or of the Desktop.
-(void)updateSaveLocationButtonTitles
{
	for (NSString *key in FlycutFolderRestoreKeys()) {
		NSURL *url = [[NSUserDefaults standardUserDefaults] URLForKey:key];
		[[self saveLocationButtonForKey:key] setTitle:url != nil ? [url lastPathComponent] : [FlycutDesktopPath() lastPathComponent]];
	}
}

// The folder chosen for a save button. The Desktop, where Flycut saves while
// no folder is stored, is not stored.
-(void)storeSaveLocation:(NSURL *)url forButton:(NSButton *)button
{
	NSString *key = nil;
	for (NSString *candidate in FlycutFolderRestoreKeys())
		if (button != nil && [self saveLocationButtonForKey:candidate] == button)
			key = candidate;
	if (key == nil || url == nil)
		return;
	if (FlycutIsDesktopFolder(url))
		[[NSUserDefaults standardUserDefaults] removeObjectForKey:key];
	else
		[[NSUserDefaults standardUserDefaults] setURL:url forKey:key];
	[self updateSaveLocationButtonTitles];
	[self updateRestoreDefaultButtons];
}

-(BOOL)restoreDefaultValueIsDefaultForIdentifier:(NSString *)identifier
{
	NSString *key = FlycutRestoreDefaultsKey(identifier);
	if (key == nil)
		return YES;
	SRRecorderControl *recorder = [self restoreDefaultRecorderForIdentifier:identifier];
	if ([key hasPrefix:@"ShortcutRecorder "]) {
		if (recorder == nil)
			return YES;
		return FlycutKeyComboIsRegistered([recorder keyCombo], key);
	}
	if ([FlycutFolderRestoreKeys() containsObject:key])
		return FlycutIsDesktopFolder([[NSUserDefaults standardUserDefaults] URLForKey:key]);
	id registered = FlycutRegisteredDefault(key);
	if (registered == nil)
		return YES;  // nothing to go back to
	// What the control shows right now, typing included.
	NSTextField *field = (NSTextField *)FlycutBoundControl([savingSectionLabel superview], key, [NSTextField class]);
	id current = [field currentEditor] != nil ? [[field currentEditor] string] : [[NSUserDefaults standardUserDefaults] objectForKey:key];
	if ([registered isKindOfClass:[NSString class]]) {
		// The lists are read with spaces removed (-[FlycutOperator shouldSkip:...]).
		NSString *(^compact)(id) = ^NSString *(id value) {
			return [[value description] stringByReplacingOccurrencesOfString:@" " withString:@""];
		};
		return [compact(current) isEqualToString:compact(registered)];
	}
	if (![current respondsToSelector:@selector(doubleValue)])
		return NO;
	double factory = [registered doubleValue];
	return fabs([current doubleValue] - factory) < 0.0005 * MAX(1.0, fabs(factory));
}

-(void)updateRestoreDefaultButtons
{
	NSMutableArray *buttons = [NSMutableArray array];
	FlycutCollectRestoreDefaultButtons(appearancePanel, buttons);
	FlycutCollectRestoreDefaultButtons([mainRecorder superview], buttons);
	FlycutCollectRestoreDefaultButtons([savingSectionLabel superview], buttons);
	for (NSButton *button in buttons) {
		BOOL atDefault = [self restoreDefaultValueIsDefaultForIdentifier:[button identifier]];
		[button setHidden:atDefault];
		[button setEnabled:!atDefault];
	}
}

-(IBAction)restoreDefault:(id)sender
{
	NSString *identifier = [sender identifier];
	NSString *key = FlycutRestoreDefaultsKey(identifier);
	if (key == nil)
		return;
	NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
	SRRecorderControl *recorder = [self restoreDefaultRecorderForIdentifier:identifier];
	NSTextField *field = (NSTextField *)FlycutBoundControl([savingSectionLabel superview], key, [NSTextField class]);
	NSSlider *slider = nil;
	for (NSView *view in [[sender superview] subviews])
		if ([view isKindOfClass:[NSSlider class]])
			slider = (NSSlider *)view;

	if ([key hasPrefix:@"ShortcutRecorder "]) {
		// A running recording ends first. The combination then goes through
		// the recorder's delegate like a recorded one: the hotkey is
		// registered again, and as it equals the registered one, the stored
		// value is dropped (-setHotKeyPreferenceForRecorder:).
		if (recorder != nil && [[recorder window] firstResponder] == recorder)
			[[recorder window] makeFirstResponder:nil];
		[recorder setKeyCombo:FlycutRegisteredKeyCombo(key)];
	} else if ([FlycutFolderRestoreKeys() containsObject:key]) {
		// No stored folder means the Desktop again.
		[defaults removeObjectForKey:key];
		[self updateSaveLocationButtonTitles];
	} else if (slider != nil) {
		// Dropping the stored value brings back the registered default; the
		// slider shows it and its action applies it to the bezel. The slider's
		// value binding stores what it shows as it sends the action, so the
		// value is dropped once more afterwards.
		[defaults removeObjectForKey:key];
		[slider setDoubleValue:[defaults doubleForKey:key]];
		[slider sendAction:[slider action] to:[slider target]];
		[defaults removeObjectForKey:key];
	} else if (field != nil) {
		// Unfinished typing is dropped. Dropping the stored value through the
		// defaults controller the field is bound to brings back the registered
		// default, and the bound field and stepper show it at once.
		if ([field currentEditor] != nil)
			[field abortEditing];
		NSDictionary *binding = [field infoForBinding:NSValueBinding];
		[[binding objectForKey:NSObservedObjectKey] setValue:nil forKeyPath:[binding objectForKey:NSObservedKeyPathKey]];
		// The limits go the way a stepper click goes: shrinking below the
		// stored clippings asks first (Resize Stack), and Cancel keeps the
		// old limit.
		if ([key isEqualToString:@"rememberNum"])
			[self checkRememberNumPref:(int)[defaults integerForKey:key] forPrimaryStore:YES];
		else if ([key isEqualToString:@"favoritesRememberNum"])
			[self checkFavoritesRememberNumPref:(int)[defaults integerForKey:key]];
		else if ([key isEqualToString:@"displayNum"])
			[self setDisplayNumPref:sender];
	}
	[self updateRestoreDefaultButtons];
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
	if (menuIconCustomColorsCheckbox != nil)
		return;

	NSRect expandedPanelFrame = [appearancePanel frame];
	expandedPanelFrame.size.height += 70;
	[appearancePanel setFrame:expandedPanelFrame];

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

    row = [self preferencePanelCheckboxRowForText:@"Capture images from clipboard"
                                        frameMaxY:nextYMax
                                          binding:@"captureImages"
                                           action:nil];
    [appearancePanel addSubview:row];
    nextYMax = row.frame.origin.y;

    row = [self preferencePanelCheckboxRowForText:@"Download animated GIFs from web"
                                        frameMaxY:nextYMax
                                          binding:@"downloadAnimatedGIFs"
                                           action:nil];
    [appearancePanel addSubview:row];
    nextYMax = row.frame.origin.y;

    row = [self preferencePanelMenuIconColorRowWithFrameMaxY:nextYMax];
    [appearancePanel addSubview:row];
    nextYMax = row.frame.origin.y;
    
    // Size against the NSBox content view, not its outer frame. AppKit gives
    // NSBox a smaller inset content area; using the outer height placed the
    // final row at a negative y-coordinate and clipped its button.
    NSView *panelContentView = [appearancePanel contentView];
    NSArray *appearanceRows = [[panelContentView subviews] copy];
    NSRect rowUnion = NSZeroRect;
    BOOL hasRows = NO;
    for (NSView *appearanceRow in appearanceRows) {
        rowUnion = hasRows ? NSUnionRect(rowUnion, [appearanceRow frame]) : [appearanceRow frame];
        hasRows = YES;
    }
    if (hasRows) {
        const CGFloat panelVerticalPadding = 8.0;
        NSRect contentBounds = [panelContentView bounds];
        CGFloat requiredContentHeight = NSHeight(rowUnion) + (2.0 * panelVerticalPadding);
        CGFloat heightDelta = requiredContentHeight - NSHeight(contentBounds);
        if (heightDelta > 0.0) {
            NSRect resizedPanelFrame = [appearancePanel frame];
            resizedPanelFrame.size.height += heightDelta;
            [appearancePanel setFrame:resizedPanelFrame];
            contentBounds = [panelContentView bounds];
        }

        CGFloat rowOffset = NSMaxY(contentBounds) - panelVerticalPadding - NSMaxY(rowUnion);
        for (NSView *appearanceRow in appearanceRows) {
            NSRect rowFrame = [appearanceRow frame];
            rowFrame.origin.y += rowOffset;
            [appearanceRow setFrame:rowFrame];
        }
    }
    [appearanceRows release];

    (void)nextYMax;
    
}

-(IBAction) showPreferencePanel:(id)sender
{
    [self cancelPendingPasteCompletion];
	if ([prefsPanel respondsToSelector:@selector(setCollectionBehavior:)])
		[prefsPanel setCollectionBehavior:NSWindowCollectionBehaviorCanJoinAllSpaces];
	[NSApp activateIgnoringOtherApps: YES];

    // Set minimum width but let UKPrefsPanel control the height based on tab content
    NSRect currentFrame = [prefsPanel frame];
    if (currentFrame.size.width < 700) {
        NSRect newFrame = currentFrame;
        newFrame.size.width = 720;
        // Adjust position to keep window centered horizontally
        newFrame.origin.x = currentFrame.origin.x - (newFrame.size.width - currentFrame.size.width) / 2;
        [prefsPanel setFrame:newFrame display:NO animate:NO];
    }
	// Folder names and Restore Default arrows as they are now, before the
	// window shows.
	[self updateSaveLocationButtonTitles];
	[self updateRestoreDefaultButtons];
	[prefsPanel makeKeyAndOrderFront:self];
	NSString *fileRoot = [[NSBundle mainBundle] pathForResource:@"acknowledgements" ofType:@"txt"];
	NSString *contents = [NSString stringWithContentsOfFile:fileRoot
												   encoding:NSUTF8StringEncoding
													  error:NULL];
	[acknowledgementsView setString:contents];
	[flycutOperator willShowPreferences];
}

-(IBAction)toggleLoadOnStartup:(id)sender {
	// Since the control in Interface Builder is bound to User Defaults and sends this action, this method is called after User Defaults already reflects the newly-selected state and merely conveys that value to the relevant mechanisms rather than acting to negate the User Defaults state.
	SMAppService *loginItem = [SMAppService mainAppService];
	NSError *error = nil;
	if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"loadOnStartup"] ) {
		if (![loginItem registerAndReturnError:&error]) {
			NSLog(@"Failed to enable login item: %@", error);
		}
	} else {
		if (![loginItem unregisterAndReturnError:&error]) {
			NSLog(@"Failed to disable login item: %@", error);
		}
	}
}

-(IBAction)recheckAccessibility:(id)sender {
    // This explicit user action may request native consent when access is missing.
    NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
    NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
    NSDictionary* options = @{(id) (kAXTrustedCheckOptionPrompt): @NO};
    BOOL trusted = AXIsProcessTrustedWithOptions((CFDictionaryRef) (options));
    
    NSLog(@"[Accessibility] Manual recheck - Bundle: %@, ID: %@, Trusted: %@", 
          bundlePath, bundleID, trusted ? @"YES" : @"NO");
    
    if (trusted) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Accessibility Access Granted";
        alert.informativeText = [NSString stringWithFormat:@"Flycut has accessibility permissions.\n\nBundle: %@\nBundle ID: %@", bundlePath, bundleID];
        [alert addButtonWithTitle:@"OK"];
        [alert runModal];
        [alert release];
    } else {
        [self requestAccessibilityWithPrompt];
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

- (NSRunningApplication *)frontmostApplicationForPaste
{
	return [[NSWorkspace sharedWorkspace] frontmostApplication];
}

- (void)rememberFrontmostApplicationForPaste
{
	NSRunningApplication *frontmostApplication = [self frontmostApplicationForPaste];
	pid_t frontmostProcessIdentifier = [frontmostApplication processIdentifier];
	pid_t flycutProcessIdentifier = [[NSRunningApplication currentApplication] processIdentifier];
	if ( frontmostApplication == nil || frontmostProcessIdentifier <= 0 ||
		frontmostProcessIdentifier == flycutProcessIdentifier ) {
		frontmostApplication = nil;
		frontmostProcessIdentifier = 0;
	}

	nextPasteTransactionGeneration += 1;
	if ( nextPasteTransactionGeneration == 0 )
		nextPasteTransactionGeneration = 1;
	FCPasteTransaction *transaction = [[FCPasteTransaction alloc]
		initWithApplication:frontmostApplication
		processIdentifier:frontmostProcessIdentifier
		generation:nextPasteTransactionGeneration];
	[currentPasteTransaction release];
	currentPasteTransaction = transaction;
}

- (BOOL)pasteTransactionIsCurrent:(FCPasteTransaction *)transaction
{
	return transaction != nil && transaction == currentPasteTransaction &&
		[transaction generation] == nextPasteTransactionGeneration;
}

- (void)clearPasteTransactionIfCurrent:(FCPasteTransaction *)transaction
{
	if ( [self pasteTransactionIsCurrent:transaction] )
		[self clearRememberedPasteTarget];
}

// Ends a transaction that nobody cancelled although its paste was not delivered (no
// Accessibility access, no paste key, the target could not be activated or lost focus).
// The user chose this clipping, so it stays on the clipboard as it would without the
// transaction; only a cancellation (Escape, a superseding selection) rolls it back.
- (void)finishPasteTransactionKeepingSelection:(FCPasteTransaction *)transaction
{
	if ( ![self pasteTransactionIsCurrent:transaction] )
		return;
	[transaction setClipboardCommitted:YES];
	[self clearRememberedPasteTarget];
}

- (void)clearRememberedPasteTarget
{
	FCPasteTransaction *transaction = currentPasteTransaction;
	currentPasteTransaction = nil;
	[self restorePasteboardForCancelledTransaction:transaction];
	[transaction release];
}

- (void)hideAppForPasteTransaction:(FCPasteTransaction *)transaction
{
	if ( [self pasteTransactionIsCurrent:transaction] )
		[self hideApp];
}

- (void)completePasteInRememberedApplication:(FCPasteTransaction *)transaction
{
	if ( ![self pasteTransactionIsCurrent:transaction] )
		return;
	if (![self pasteboardIsOwnedByTransaction:transaction]) {
		[self clearPasteTransactionIfCurrent:transaction];
		return;
	}

	NSRunningApplication *pasteTarget = [transaction targetApplication];
	pid_t targetProcessIdentifier = [transaction targetProcessIdentifier];
	NSRunningApplication *frontmostApplication = [self frontmostApplicationForPaste];
	pid_t frontmostProcessIdentifier = [frontmostApplication processIdentifier];
	pid_t flycutProcessIdentifier = [[NSRunningApplication currentApplication] processIdentifier];
	BOOL targetIsValid = pasteTarget != nil && ![pasteTarget isTerminated] &&
		targetProcessIdentifier > 0;
	BOOL focusStillBelongsToTransaction = targetIsValid &&
		(frontmostProcessIdentifier == targetProcessIdentifier ||
		 frontmostProcessIdentifier == flycutProcessIdentifier);
	if ( !focusStillBelongsToTransaction ) {
		NSLog(@"Paste cancelled because focus left the original transaction before activation");
		[self finishPasteTransactionKeepingSelection:transaction];
		return;
	}

	BOOL targetReady =
		[pasteTarget activateWithOptions:NSApplicationActivateIgnoringOtherApps];
	if ( targetReady && [self pasteTransactionIsCurrent:transaction] ) {
		// Activation is requested synchronously, but AppKit may not finish moving key focus
		// until the next run-loop turn. Post Cmd-V only after that transition can settle.
		[self performSelector:@selector(postPasteAndClearRememberedApplication:)
				 withObject:transaction
				 afterDelay:0.05];
	} else {
		NSLog(@"Could not reactivate the application selected for paste");
		[self finishPasteTransactionKeepingSelection:transaction];
	}
}

- (void)postPasteAndClearRememberedApplication:(FCPasteTransaction *)transaction
{
	if ( ![self pasteTransactionIsCurrent:transaction] )
		return;
	if (![self pasteboardIsOwnedByTransaction:transaction]) {
		[self clearPasteTransactionIfCurrent:transaction];
		return;
	}

	NSRunningApplication *pasteTarget = [transaction targetApplication];
	pid_t targetProcessIdentifier = [transaction targetProcessIdentifier];
	NSRunningApplication *frontmostApplication = [self frontmostApplicationForPaste];
	BOOL targetIsValid = pasteTarget != nil && ![pasteTarget isTerminated] &&
		targetProcessIdentifier > 0;
	BOOL targetIsFrontmost = targetIsValid && frontmostApplication != nil &&
		targetProcessIdentifier == [frontmostApplication processIdentifier];
	if ( targetIsFrontmost ) {
		// Use the same immutable local PID for validation and posting.
		if ( ![self postCommandVToProcessIdentifier:targetProcessIdentifier] )
			NSLog(@"Paste could not be posted; the selection stays on the clipboard");
		[self finishPasteTransactionKeepingSelection:transaction];
		return;
	}

	NSRunningApplication *flycutApplication = [NSRunningApplication currentApplication];
	BOOL activationMayStillBeSettling = frontmostApplication == nil ||
		[frontmostApplication processIdentifier] == [flycutApplication processIdentifier];
	if ( targetIsValid && activationMayStillBeSettling &&
		[transaction focusCheckAttempts] < kPasteTargetActivationCheckLimit ) {
		[transaction setFocusCheckAttempts:[transaction focusCheckAttempts] + 1];
		[self performSelector:@selector(postPasteAndClearRememberedApplication:)
				 withObject:transaction
				 afterDelay:0.05];
		return;
	}

	NSLog(@"Paste cancelled because the original target did not become frontmost");
	[self finishPasteTransactionKeepingSelection:transaction];
}

- (NSArray *)snapshotPasteboardItems
{
	NSMutableArray *snapshot = [NSMutableArray array];
	for (NSPasteboardItem *item in [jcPasteboard pasteboardItems]) {
		NSMutableDictionary *representations = [NSMutableDictionary dictionary];
		for (NSString *type in [item types]) {
			NSData *data = [item dataForType:type];
			if (data == nil)
				return nil; // Never destroy a representation that cannot be restored.
			[representations setObject:[[data copy] autorelease] forKey:type];
		}
		[snapshot addObject:[[representations copy] autorelease]];
	}
	return [[snapshot copy] autorelease];
}

- (void)restorePasteboardForCancelledTransaction:(FCPasteTransaction *)transaction
{
	if (transaction == nil || [transaction clipboardCommitted] ||
		[transaction previousPasteboardItems] == nil || [transaction ownedChangeCount] < 0 ||
		[jcPasteboard changeCount] != [transaction ownedChangeCount])
		return;
	NSMutableArray *items = [NSMutableArray array];
	for (NSDictionary *representations in [transaction previousPasteboardItems]) {
		NSPasteboardItem *item = [[[NSPasteboardItem alloc] init] autorelease];
		for (NSString *type in representations)
			if (![item setData:[representations objectForKey:type] forType:type])
				return;
		[items addObject:item];
	}
	// The pasteboard API has no cross-process compare-and-swap. Recheck at the
	// last possible point, and never restore over an observed external copy.
	if ([jcPasteboard changeCount] != [transaction ownedChangeCount])
		return;
	[jcPasteboard clearContents];
	if ([items count] > 0 && ![jcPasteboard writeObjects:items])
		NSLog(@"Could not restore the cancelled paste's clipboard snapshot");
	[self setPBBlockCount:@([jcPasteboard changeCount])];
}

- (BOOL)pasteboardIsOwnedByTransaction:(FCPasteTransaction *)transaction
{
	if (transaction == nil || ![transaction hasSelectedPayload] ||
		[transaction ownedChangeCount] < 0 ||
		[jcPasteboard changeCount] != [transaction ownedChangeCount])
		return NO;
	BOOL contentsMatch;
	if ([transaction selectedPayload] != nil) {
		NSString *contents = [jcPasteboard stringForType:NSPasteboardTypeString];
		contentsMatch = [contents isEqualToString:[transaction selectedPayload]];
	} else {
		NSData *contents = [jcPasteboard dataForType:[transaction selectedPayloadType]];
		contentsMatch = [contents isEqualToData:[transaction selectedPayloadData]];
	}
	return contentsMatch && [jcPasteboard changeCount] == [transaction ownedChangeCount];
}

- (void)cancelPendingPasteCompletion
{
	FCPasteTransaction *transaction = [currentPasteTransaction retain];
	if ( transaction != nil ) {
		[NSObject cancelPreviousPerformRequestsWithTarget:self
								 selector:@selector(hideAppForPasteTransaction:)
								   object:transaction];
		[NSObject cancelPreviousPerformRequestsWithTarget:self
								 selector:@selector(completePasteInRememberedApplication:)
								   object:transaction];
		[NSObject cancelPreviousPerformRequestsWithTarget:self
								 selector:@selector(postPasteAndClearRememberedApplication:)
								   object:transaction];
	}
	[self clearRememberedPasteTarget];
	[transaction release];
}

- (void)pasteFromStack
{
	// A bezel selection is pasted at most once. Releasing the modifier keys and
	// pressing Return (or double-clicking) all confirm the same selection, so any
	// further confirmation before the bezel is opened again is a duplicate.
	if ( bezelSelectionFinished ) {
		NSLog(@"pasteFromStack ignored - this bezel selection was already pasted or cancelled");
		return;
	}
	bezelSelectionFinished = YES;
	NSLog(@"pasteFromStack called");
	FCPasteTransaction *transaction = [currentPasteTransaction retain];
	if (transaction == nil || [transaction selectionStarted]) {
		[transaction release];
		return;
	}
	// Completion belongs to the invocation, never to an elapsed-time window.
	[transaction setSelectionStarted:YES];
	FlycutClipping *clipping = [flycutOperator clippingAtStackPosition];
	BOOL selected = NO;
	if ( [clipping isImageClipping] ) {
		selected = YES;
		[self addImageClipToPasteboard:clipping];
	} else {
		// Read the rich data before the paste may move the clipping to the top.
		NSDictionary *richData = [flycutOperator getRichDataFromStackPosition];
		NSString *content = [flycutOperator getPasteFromStackPosition];
		if ( nil != content ) {
			selected = YES;
			[self addClipToPasteboard:content withRichData:richData];
		}
	}
	if ( selected ) {
		NSLog(@"Content found; adding it to the pasteboard and preparing to paste");
		if ( [self pasteTransactionIsCurrent:transaction] ) {
			[self performSelector:@selector(hideAppForPasteTransaction:)
					 withObject:transaction
					 afterDelay:0.2];
			[self performSelector:@selector(completePasteInRememberedApplication:)
					 withObject:transaction
					 afterDelay:0.5];
		} else if ( currentPasteTransaction == nil &&
			[transaction generation] == nextPasteTransactionGeneration ) {
			// Placement cleared this selection. Finish its UI without retrying the paste.
			// Snapshot/restore callbacks may have opened (and even cleared) a newer
			// selection, so nil alone does not establish ownership of the visible UI.
			[self hideApp];
		}
	} else {
		NSLog(@"No content found in stack position");
		if ( transaction == nil || [self pasteTransactionIsCurrent:transaction] )
			[self hideApp];
		[self clearPasteTransactionIfCurrent:transaction];
	}
	[transaction release];
    [self restoreStashedStoreAndUpdate];
}

- (void)moveItemAtStackPositionToTopOfStack
{
	if ( [flycutOperator stackPositionIsInBounds] ) {
		// stackPosition already IS a store position. It must never be run through the menu's
		// search-box mapping, which is what the old -pasteIndexAndUpdate: did.
		// The copy is final: a later Escape or hotkey press must not roll it back. The
		// transaction stays open, so a modifier release can still paste this clipping.
		FCPasteTransaction *transaction = [currentPasteTransaction retain];
		if ( [self pasteStorePositionAndUpdate: [flycutOperator stackPosition]] &&
			[self pasteTransactionIsCurrent:transaction] )
			[transaction setClipboardCommitted:YES];
		[transaction release];
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
	} else {
		[self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
	}
}

// Pastes the clipping at the given STORE position. Unlike the old -pasteIndexAndUpdate:
// this never reads the menu's search box: every caller resolves its own mapping while it
// still knows which list the position came from. Returns true when something actually
// reached the pasteboard, so the caller can skip faking cmd-V - otherwise the previous
// pasteboard contents (typically the last thing pasted) would be inserted again.
- (bool)pasteStorePositionAndUpdate:(int) position {
    if ( position < 0 || position >= [flycutOperator jcListCount] )
        return false;

    FlycutClipping *clipping = [flycutOperator clippingAtIndex:position];
    if (clipping && [clipping isImageClipping]) {
        if ( ! [self addImageClipToPasteboard:clipping] )
            return false;
        if ([[NSUserDefaults standardUserDefaults] boolForKey:@"pasteMovesToTop"]) {
            [flycutOperator getPasteFromIndex:position];
        }
        [self updateMenu];
        return true;
    }

    // Read the rich data before getPasteFromIndex: may move the clipping to the top.
    NSDictionary *richData = [flycutOperator getRichDataFromIndex: position];
    NSString *content = [flycutOperator getPasteFromIndex: position];
    if ( nil == content )
        return false;

    [self addClipToPasteboard:content withRichData:richData];
    [self updateMenu];
    return true;
}

- (void)metaKeysReleased
{
	NSLog(@"metaKeysReleased called - isBezelPinned: %@", isBezelPinned ? @"YES" : @"NO");
	if ( isBezelDisplayed && ! isBezelPinned ) {
		[self pasteFromStack];
	}
}

- (void)windowDidResignKey:(NSNotification *)notification {
	if ( [notification object] == searchWindow ) {
		// -hideApp does not close the search window properly, so isSearchWindowDisplayed
		// would stay set - and -pollPB: reads that as "a selection is in progress" and
		// stops capturing altogether, with nothing to show the user why. A successful
		// selection marks the window hidden before orderOut so its transaction survives.
		if ( isSearchWindowDisplayed )
			[self hideSearchWindow];
		return;
	}

	[self hideApp];
}

- (void)windowDidBecomeKey:(NSNotification *)notification {
	// The search window is opened from a global hotkey while another app is
	// active, and app activation is asynchronous on modern macOS.  A
	// makeFirstResponder: call at show time runs before the window can take
	// focus, so the field accepts keystrokes but never shows its caret.
	// Focus the field once the window has actually become key.
	if ( [notification object] == searchWindow ) {
		[searchWindow makeFirstResponder:searchWindowSearchField];
	}
}

-(void)fakeKey:(NSNumber*) keyCode withCommandFlag:(BOOL) setFlag
	/*" +fakeKey synthesizes keyboard events. "*/
{
    if (keyCode == nil)
    {
        DLog(@"No key code");
        return;
    }

    CGEventSourceRef sourceRef = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState);
    if (!sourceRef)
    {
        DLog(@"No event source");
        return;
    }
    CGKeyCode veeCode = (CGKeyCode)[keyCode intValue];
    CGEventRef eventDown = CGEventCreateKeyboardEvent(sourceRef, veeCode, true);
    CGEventRef eventUp = CGEventCreateKeyboardEvent(sourceRef, veeCode, false);
    if (!eventDown || !eventUp)
    {
        if (eventDown) CFRelease(eventDown);
        if (eventUp) CFRelease(eventUp);
        CFRelease(sourceRef);
        DLog(@"Could not create both keyboard events");
        return;
    }
    if ( setFlag )
        CGEventSetFlags(eventDown, kCGEventFlagMaskCommand|0x000008); // some apps want bit set for one of the command keys
    CGEventPost(kCGHIDEventTap, eventDown);
    CGEventPost(kCGHIDEventTap, eventUp);
    CFRelease(eventDown);
    CFRelease(eventUp);
    CFRelease(sourceRef);
}

/*" +fakeCommandV synthesizes keyboard events for Cmd-v Paste shortcut. "*/
-(void)fakeCommandV {
    NSLog(@"fakeCommandV called - attempting to paste");

    // Check without prompting; prompting here would steal focus and break paste.
    BOOL accessibilityEnabled = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)@{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @NO});

    if (!accessibilityEnabled) {
        // Consolidated failure log with all relevant context
        NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
        NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
        NSLog(@"[Accessibility FAILURE] Cannot simulate Cmd-V paste. Bundle: %@, ID: %@, Trusted: NO. User must grant Accessibility permission in System Settings.", bundlePath, bundleID);
        
        if (FlycutShouldShowAccessibilityExplanation(
                true,
                accessibilityEnabled,
                hasShownAccessibilityExplanationThisSession)) {
            hasShownAccessibilityExplanationThisSession = YES;
            [self showAccessibilityAlert];
        }
        return;
    }

    [self fakeKey:FlycutPasteKeyCode() withCommandFlag:TRUE];
}

- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier
{
    if ( processIdentifier <= 0 ) {
        DLog(@"No paste target process identifier");
        return NO;
    }

    BOOL accessibilityEnabled = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)@{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @NO});
    if ( !accessibilityEnabled ) {
        // An explicit paste may request native consent, never a prerequisite app
        // dialog, and only once per session (the same gate as -fakeCommandV), so a
        // repeated paste without access does not bring up the system dialog again.
        // Do not resume this transaction even if permission changes here.
        if (FlycutShouldShowAccessibilityExplanation(
                true,
                accessibilityEnabled,
                hasShownAccessibilityExplanationThisSession)) {
            hasShownAccessibilityExplanationThisSession = YES;
            [self showAccessibilityAlert];
        }
        return NO;
    }

    // Resolve at the actual post boundary, not when the selection first opened.
    NSNumber *resolvedKey = FlycutPasteKeyCode();
    if (resolvedKey == nil)
        return NO;
    CGKeyCode pasteKey = (CGKeyCode)[resolvedKey unsignedShortValue];

    CGEventSourceRef sourceRef = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState);
    if ( !sourceRef ) {
        DLog(@"No event source");
        return NO;
    }

    CGEventRef commandDown = CGEventCreateKeyboardEvent(sourceRef, kVK_Command, true);
    CGEventRef eventDown = CGEventCreateKeyboardEvent(sourceRef, pasteKey, true);
    CGEventRef eventUp = CGEventCreateKeyboardEvent(sourceRef, pasteKey, false);
    CGEventRef commandUp = CGEventCreateKeyboardEvent(sourceRef, kVK_Command, false);
    if ( !commandDown || !eventDown || !eventUp || !commandUp ) {
        DLog(@"Could not create targeted synthetic paste events");
        if ( commandDown ) CFRelease(commandDown);
        if ( eventDown ) CFRelease(eventDown);
        if ( eventUp ) CFRelease(eventUp);
        if ( commandUp ) CFRelease(commandUp);
        CFRelease(sourceRef);
        return NO;
    }

    CGEventSetFlags(commandDown, kCGEventFlagMaskCommand|0x000008);
    CGEventSetFlags(eventDown, kCGEventFlagMaskCommand|0x000008);
    CGEventSetFlags(eventUp, kCGEventFlagMaskCommand|0x000008);
    CGEventPostToPid(processIdentifier, commandDown);
    CGEventPostToPid(processIdentifier, eventDown);
    CGEventPostToPid(processIdentifier, eventUp);
    CGEventPostToPid(processIdentifier, commandUp);

    CFRelease(commandDown);
    CFRelease(eventDown);
    CFRelease(eventUp);
    CFRelease(commandUp);
    CFRelease(sourceRef);
    return YES;
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
        if( commandSelector == @selector(performClose:) ) // Cmd-W
        {
            [self hideSearchWindow];
            return YES;
        }
    }

    return NO;    // Default handling of the command
}

-(void)pollPB:(NSTimer *)timer
{
    // Do not capture new clippings while the user is picking one from the menu or the
    // search window. Because this timer runs in NSRunLoopCommonModes it fires during menu
    // tracking, and inserting a new clipping at the top of the store would make every row
    // jump down by one while the user is aiming at it. Correctness no longer depends on
    // this freeze - a selection is resolved by clipping identity, see
    // -storePositionForMenuItem: - but the list should not move under the pointer.
    // pbCount is left untouched so the change is still detected and captured once the menu
    // or search window closes (menuDidClose: fires a catch-up poll).
    if ( isMenuOpen || isSearchWindowDisplayed )
        return;

    NSInteger pasteboardGeneration = [jcPasteboard changeCount];
    if ( [pbCount integerValue] == pasteboardGeneration || [flycutOperator storeDisabled] )
        return;

    [pbCount release];
    pbCount = [[NSNumber numberWithInteger:pasteboardGeneration] retain];

    NSString *type = [jcPasteboard availableTypeFromArray:[NSArray arrayWithObject:NSPasteboardTypeString]];
    NSString *imageType = [jcPasteboard availableTypeFromArray:@[@"com.compuserve.gif", NSPasteboardTypeTIFF, NSPasteboardTypePNG]];
    if ( ![[NSUserDefaults standardUserDefaults] boolForKey:@"captureImages"] )
        imageType = nil;
    NSArray *availableTypes = [jcPasteboard types];
    NSInteger blockedGeneration = [pbBlockCount integerValue];
    NSUInteger captureEpoch = clipboardCaptureEpoch;
    if ( type == nil && imageType == nil )
        return;

    NSRunningApplication *currRunningApp = nil;
    for (NSRunningApplication *currApp in [[NSWorkspace sharedWorkspace] runningApplications])
        if ([currApp isActive])
            currRunningApp = currApp;

    if ( type != nil ) {
        // Reading remote clipboard data can block. Keep it off the main thread;
        // transfer activity must not change the user's explicit paused state.
        dispatch_async(clipboardReadQueue, ^{
            NSString *contents = [jcPasteboard stringForType:type];
            BOOL contentShouldBeSkipped = contents == nil;
            if (!contentShouldBeSkipped)
                contentShouldBeSkipped = [flycutOperator shouldSkip:contents ofType:type fromAvailableTypes:availableTypes];

            // Capture rich representations of the text so pasting an older clipping
            // can keep its formatting.  Only done after the skip checks above, and read
            // before the generation is sampled below, so a clipboard change during these
            // reads discards the whole capture and rich data of concealed/transient
            // clippings is never stored.
            NSMutableDictionary *richData = nil;
            if ( !contentShouldBeSkipped && [[NSUserDefaults standardUserDefaults] boolForKey:@"preserveTextFormatting"] ) {
                for ( NSString *richType in [NSArray arrayWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil] ) {
                    // Types come from the snapshot of the generation detected above.
                    if ( [availableTypes containsObject:richType] ) {
                        NSData *data = [jcPasteboard dataForType:richType];
                        // Cap the size so one giant rich clipping can't bloat the saved store.
                        if ( nil != data && [data length] > 0 && [data length] <= 1048576 ) {
                            if ( nil == richData )
                                richData = [NSMutableDictionary dictionaryWithCapacity:2];
                            [richData setObject:data forKey:richType];
                        }
                    }
                }
            }
            NSInteger pasteboardGenerationAfterRead = [jcPasteboard changeCount];

            dispatch_async(dispatch_get_main_queue(), ^{
                BOOL revealPasteboardTypes = [[NSUserDefaults standardUserDefaults] boolForKey:@"revealPasteboardTypes"];
                if (!FCShouldCommitClipboardRead(
                        pasteboardGeneration,
                        pasteboardGenerationAfterRead,
                        blockedGeneration,
                        captureEpoch,
                        clipboardCaptureEpoch,
                        [flycutOperator storeDisabled]
                    )) {
                    DLog(@"Contents: Blocked, paused, or changed during read");
                    return;
                }

                if (revealPasteboardTypes) {
                    [flycutOperator addClipping:type
                                         ofType:type
                                        fromApp:@"Flycut"
                               withAppBundleURL:nil
                                         target:self
                         clippingAddedSelector:@selector(clippingWasAdded)];
                    return;
                }

                if (contentShouldBeSkipped) {
                    DLog(@"Contents: Empty or skipped");
                    return;
                }

                [flycutOperator addClipping:contents
                                     ofType:type
                               withRichData:richData
                                    fromApp:[currRunningApp localizedName]
                           withAppBundleURL:currRunningApp.bundleURL.path
                                     target:self
                     clippingAddedSelector:@selector(clippingWasAdded)];
            });
        });
    }

    if ( imageType != nil ) {
        if ( [flycutOperator shouldSkip:@"" ofType:imageType fromAvailableTypes:availableTypes] ) {
            DLog(@"Image: skipped due to pasteboard type filter");
        } else {
            // When the clipboard carries only a flattened still but embeds the source
            // GIF's URL (e.g. Chrome "Copy Image" on an animated GIF), fetch the real
            // animated file instead of capturing the still.
            // Diagnostics record only the copy's type, so they never start a download;
            // the still then goes to the image job below, which records its type.
            BOOL haveDirectGIF = [imageType isEqualToString:@"com.compuserve.gif"];
            NSURL *gifURL = nil;
            if ( !haveDirectGIF && [[NSUserDefaults standardUserDefaults] boolForKey:@"downloadAnimatedGIFs"]
                 && ![[NSUserDefaults standardUserDefaults] boolForKey:@"revealPasteboardTypes"] )
                gifURL = [self animatedGifURLFromPasteboard];

            if ( gifURL != nil ) {
                // Skip the still entirely; the async download adds the animated GIF on success.
                [self downloadAndCaptureGIFFromURL:gifURL fromApp:[currRunningApp localizedName] withAppBundleURL:currRunningApp.bundleURL.path pasteboardGeneration:pasteboardGeneration];
            } else {
                NSString *captureType = imageType;
                BOOL textTypeRecordsDiagnostics = type != nil;
                dispatch_async(clipboardReadQueue, ^{
                    NSData *imageData = [[jcPasteboard dataForType:captureType] copy];
                    NSInteger pasteboardGenerationAfterRead = [jcPasteboard changeCount];
                    int maxSizeKB = (int)[[NSUserDefaults standardUserDefaults] integerForKey:@"maxImageSizeKB"];
                    if (maxSizeKB <= 0) maxSizeKB = 10240;
                    if (imageData == nil || [imageData length] == 0 || [imageData length] > (NSUInteger)maxSizeKB * 1024) {
                        [imageData release];
                        return;
                    }

                    dispatch_async(dispatch_get_main_queue(), ^{
                        BOOL revealPasteboardTypes = [[NSUserDefaults standardUserDefaults] boolForKey:@"revealPasteboardTypes"];
                        if (FCShouldCommitClipboardRead(
                                pasteboardGeneration,
                                pasteboardGenerationAfterRead,
                                blockedGeneration,
                                captureEpoch,
                                clipboardCaptureEpoch,
                                [flycutOperator storeDisabled]
                            )
                            // Also bound to the generation whose types were checked (the
                            // clipboard must still hold it) and to image capture being on.
                            && [self isImageCaptureCurrentForGeneration:pasteboardGeneration]) {
                            if (revealPasteboardTypes) {
                                // Diagnostics record the type instead of the payload, once per copy.
                                if (!textTypeRecordsDiagnostics)
                                    [flycutOperator addClipping:captureType
                                                         ofType:captureType
                                                        fromApp:@"Flycut"
                                               withAppBundleURL:nil
                                                         target:self
                                         clippingAddedSelector:@selector(clippingWasAdded)];
                            } else {
                                [flycutOperator addImageClipping:imageData fromApp:[currRunningApp localizedName] withAppBundleURL:currRunningApp.bundleURL.path imageType:captureType target:self clippingAddedSelector:@selector(clippingWasAdded)];
                            }
                        } else {
                            DLog(@"Image: Blocked, paused, or changed during read");
                        }
                        [imageData release];
                    });
                });
            }
        }
    }
}

- (void)cancelBezelSelection
{
	bezelSelectionFinished = YES;
	// Escape cancels what the selection already scheduled. The bezel paste is owned by a
	// transaction, so -cancelPendingPasteCompletion cancels its delayed hide, activation
	// and Cmd-V and restores the clipboard while the transaction still owns it.
	[self cancelPendingPasteCompletion];
	// Delayed requests queued without a transaction (the copy-only action's delayed hide)
	// must not run after the cancellation either, e.g. into a bezel opened again.
	[NSObject cancelPreviousPerformRequestsWithTarget:self selector:@selector(fakeCommandV) object:nil];
	[NSObject cancelPreviousPerformRequestsWithTarget:self selector:@selector(hideApp) object:nil];
	[self restoreStashedStoreAndUpdate];
	[self hideApp];
}

- (void)processBezelKeyDown:(NSEvent *)theEvent {
	int newStackPosition;
	// AppControl should only be getting these directly from bezel via delegation
    if ([theEvent type] == NSEventTypeKeyDown) {
        // The Escape key is identified by its layout-independent macOS virtual keycode.
        // Some AppKit events carry no characters, so handle Escape before reading them.
        if ([theEvent keyCode] == 53) {
            [self cancelBezelSelection];
            return;
        }
		if ([theEvent keyCode] == [mainRecorder keyCombo].code ) {
            if ([theEvent modifierFlags] & NSEventModifierFlagShift) [self stackUp];
			 else [self stackDown];
			return;
		}
        NSString *characters = [theEvent charactersIgnoringModifiers];
        if ([characters length] == 0)
            return;
		unichar pressed = [characters characterAtIndex:0];
        NSUInteger modifiers = [theEvent modifierFlags];
		switch (pressed) {
			case 0x1B:
				[self cancelBezelSelection];
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

                    // Delete while the store that was saved from is still the current one.
                    // -restoreStashedStore swaps the store AND the stack position back, so
                    // deleting after it removed an entry from the main list - at whatever
                    // position the user had been at there - instead of the clipping that had
                    // just been saved.  Saving a favorite therefore destroyed an unrelated
                    // clipping.
                    if ( success && ( modifiers & NSEventModifierFlagShift ) ) {
                        [flycutOperator clearItemAtStackPosition];
                        [self updateBezel];
                        [self updateMenu];
                    }

                    [self performSelector:@selector(hideApp) withObject:nil afterDelay:0.2];
                    [self restoreStashedStoreAndUpdate];
                }
                break;
            case 'f':
                // Switch lists in the open bezel. It used to be ordered out and in
                // again for this; as the key window it then resigned key, and
                // -windowDidResignKey: took that for the bezel closing (-hideApp):
                // a pinned bezel lost its pin, so releasing the keys pasted, and
                // Flycut was hidden. The bezel's -update, which AppKit sends after
                // each event, repaints its background in the list's color.
                [flycutOperator toggleToFromFavoritesStore];
                [bezel setColor:[flycutOperator favoritesStoreIsSelected]];
                [self updateBezel];
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
            case ' ':
                isBezelPinned = YES;
                [bezel setCharString:[self bezelCounterString]];
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
    } else if (theEvent.type == NSEventTypeRightMouseUp) {
        isBezelPinned = YES;
        [bezel setCharString:[self bezelCounterString]];
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
		[bezel setCharString:[self bezelCounterString]];
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
	// The bezel's Favorites view ends with the bezel, however it closes: focus moved
	// elsewhere (Cmd-, opening Preferences, a click while it is pinned) or the delayed
	// hide after Shift-F or the copy-only key. Escape and a paste restore the history
	// themselves. Left swapped in, the favorites stayed the current list: the menu, the
	// search window and the next bezel showed them in place of the history.
	if ( isBezelDisplayed )
		[self restoreStashedStoreAndUpdate];
	isBezelPinned = NO;
	// Hiding the app tears down any open menu and the search window anyway, so clear both
	// freeze flags here as a backstop.  Neither is meant to outlive its surface, and a
	// stale one silently stops -pollPB: from capturing anything at all.
	isMenuOpen = NO;
	isSearchWindowDisplayed = NO;
	[self hideBezel];
	[NSApp hide:self];
}

- (void) applicationWillResignActive:(NSApplication *)app; {
	// This should be hidden anyway, but just in case it's not.
	// Only the bezel's Favorites view ends here: the Favorites stepper swaps the
	// favorites in for its check and may be waiting in its "Resize Stack" alert, and
	// restoring under it would apply the favorites limit to the history.
	if ( isBezelDisplayed )
		[self restoreStashedStoreAndUpdate];
	[self hideBezel];
}


- (void)hitMainHotKey:(SGHotKey *)hotKey
{
	if ( ! isBezelDisplayed ) {
		// Opening the bezel starts a new selection, which may be pasted once.
		bezelSelectionFinished = NO;
		// A newly opened selection owns its own eventual paste.  It must never inherit a
		// delayed activation or Cmd-V callback from the selection that just closed.
		[self cancelPendingPasteCompletion];
		[self rememberFrontmostApplicationForPaste];
		//Do NOT activate the app so focus stays on app the user is interacting with
		//https://github.com/TermiT/Flycut/issues/45
		//[NSApp activateIgnoringOtherApps:YES];
		if ( [[NSUserDefaults standardUserDefaults] boolForKey:@"stickyBezel"] ) {
			isBezelPinned = YES;
		}
		// The stack position is bezel state, so a new selection starts at the newest clipping.
		// This used to happen as a side effect of -addClipping: resetting it, which meant a
		// clipping arriving mid-selection moved the selection instead of the list moving under
		// a selection that stays put.  Note this is deliberately not in -showBezel or -updateBezel:
		// the favourites toggle ("f") refills the bezel after -toggleToFromFavoritesStore has
		// swapped in that store's own remembered position, which must stay.
		[flycutOperator setStackPositionToFirstItem];
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
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithBool:NO] forKey:@"syncClippingsViaICloud"];
			}
			else
			{
				[[NSUserDefaults standardUserDefaults] setValue:[NSNumber numberWithInt:2] forKey:@"savePreference"];
			}
			[alert release];
		}
	}
}

- (IBAction)selectSaveLocation:(id)sender {
	// Create and configure the panel.
	NSOpenPanel* panel = [NSOpenPanel openPanel];
	[panel setCanChooseFiles:NO];
	[panel setCanChooseDirectories:YES];
	[panel setCanCreateDirectories:YES];
	[panel setAllowsMultipleSelection:NO];
	[panel setMessage:@"Select a directory."];

	// Display the panel attached to the document's window.
	[panel beginSheetModalForWindow:prefsPanel completionHandler:^(NSInteger result){
        if (result == NSModalResponseOK) {
			NSURL* url = [[panel URLs] firstObject];

			if (!url) { return; }

			[self storeSaveLocation:url forButton:sender];
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

// Cap a menu-item title to a consistent rendered width.
//
// FlycutClipping truncates display strings by character count (displayLen), not
// by rendered width. In a proportional font a run of wide glyphs -- a pasted
// horizontal rule of em dashes or box-drawing characters, or CJK text -- reaches
// the character limit while taking up far more horizontal space than the same
// number of average Latin characters. Because NSMenu sizes itself to its widest
// item, one such clipping balloons the whole menu and leaves every other row
// padded with trailing space. Bound the rendered width here so the menu width
// stays consistent regardless of glyph width, using the same measure-and-trim
// approach the bezel already applies to its source-app label in
// -[BezelWindow setSource:].
- (NSString *)menuTitleFittingWidth:(NSString *)title
{
	// Headroom above the nominal displayLen-character width, so normal clippings
	// (already capped at displayLen characters) are not trimmed further here;
	// only rows of unusually wide glyphs are.
	const CGFloat kMenuTitleWidthHeadroom = 1.2;

	NSDictionary *attributes = @{NSFontAttributeName: [NSFont menuFontOfSize:0.0]};

	NSInteger displayLen = [[NSUserDefaults standardUserDefaults] integerForKey:@"displayLen"];
	if ( displayLen <= 0 )
		displayLen = 40;

	// Estimate the width of displayLen characters of ordinary text from a pangram.
	NSString *reference = @"The quick brown fox jumps over the lazy dog ";
	CGFloat averageCharWidth = [reference sizeWithAttributes:attributes].width / (CGFloat)[reference length];
	CGFloat maxWidth = averageCharWidth * displayLen * kMenuTitleWidthHeadroom;

	if ( [title sizeWithAttributes:attributes].width <= maxWidth )
		return title;

	// Trim whole composed-character sequences (not UTF-16 units) so we never
	// split a surrogate pair or a base+combining-mark cluster before the ellipsis.
	NSString *fitted = title;
	while ( [fitted length] > 0
			&& [[fitted stringByAppendingString:@"…"] sizeWithAttributes:attributes].width > maxWidth )
	{
		NSRange lastChar = [fitted rangeOfComposedCharacterSequenceAtIndex:[fitted length] - 1];
		fitted = [fitted substringToIndex:lastChar.location];
	}

	return [fitted stringByAppendingString:@"…"];
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

		int menuDisplayNum = (int)[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"];
		BOOL filtering = ( nil != search && 0 != [search length] );

		NSArray *returnedDisplayStrings = [flycutOperator previousDisplayStrings:menuDisplayNum containing:search];

		// previousDisplayStrings: and previousIndexes: are both newest-first and element-wise
		// aligned, so the store position of every row is known right here. Recording it now is
		// what allows the selection to be resolved later without asking the menu where the
		// clicked item sits and without re-reading the search box.
		NSArray *returnedIndexes = filtering ? [flycutOperator previousIndexes:menuDisplayNum containing:search] : nil;

		NSArray *menuItems = [[[jcMenu itemArray] reverseObjectEnumerator] allObjects];

		NSArray *clipStrings = [[returnedDisplayStrings reverseObjectEnumerator] allObjects];

		// Figure out if the number of menu items is changing and add or remove entries as necessary.
		// If we remove all of them and add all new ones, the menu won't redraw if the count is unchanged, so just reuse them by changing their title.
		int oldItems = [menuItems count]-jcMenuBaseItemsCount;
		int newItems = [clipStrings count];
        DLog(@"oldItems=%d, newItems=%d", oldItems, newItems);

        // Hold on to the outgoing items for one generation instead of letting jcMenu drop
        // their last reference, so that a click AppKit delivers after this rebuild still
        // has a valid sender.
        NSMutableArray *retiringItems = [NSMutableArray array];
        for ( int i = 0; i < oldItems; i++ )
        {
            [retiringItems addObject:[jcMenu itemAtIndex:0]];
            [jcMenu removeItemAtIndex:0];
        }
        [sRetiredMenuClippingItems release];
        sRetiredMenuClippingItems = [[NSArray alloc] initWithArray:retiringItems];

        for ( int i = 0; i < newItems; i++ )
        {
            // clipStrings is oldest-first (it was reversed above), everything coming from
            // the store is newest-first.
            int newestFirst = newItems - 1 - i;
            int storePosition = newestFirst;
            if ( filtering )
            {
                if ( newestFirst >= (int)[returnedIndexes count] )
                    continue; // The store changed while the menu was being built.
                storePosition = [[returnedIndexes objectAtIndex:newestFirst] intValue];
            }

            // Remember what the row stands for rather than where it sits: the clipping object
            // itself is the identity, the position is only a hint that
            // -storePositionForMenuItem: re-validates.
            //
            // The display string deliberately is NOT the identity: it is the first line
            // truncated to displayLen, and short strings are tagged pointers, so two
            // different clippings whose first lines happen to match compare pointer-equal.
            FlycutClipping *clipping = [flycutOperator clippingAtPosition:storePosition];
            if ( nil == clipping )
                continue; // The store changed while the menu was being built.

            NSMenuItem *item;
            item = [[NSMenuItem alloc] initWithTitle:[self menuTitleFittingWidth:[clipStrings objectAtIndex:i]]
                                              action:@selector(processMenuClippingSelection:)
                                       keyEquivalent:@""];
            [item setTarget:self];
            [item setEnabled:YES];
            // representedObject is a strong property, so the item keeps the clipping alive
            // even if the store drops it in the meantime.
            [item setRepresentedObject:[NSArray arrayWithObjects:
                                        [NSNumber numberWithInt:storePosition],
                                        clipping,
                                        nil]];
            if ([[clipStrings objectAtIndex:i] hasPrefix:@"[Image"]) {
                NSImage *imgIcon = [NSImage imageNamed:NSImageNameQuickLookTemplate];
                [imgIcon setSize:NSMakeSize(16, 16)];
                [item setImage:imgIcon];
            }
            [jcMenu insertItem:item atIndex:0];
            [item release];
        }
    });
}

// Works out which clipping a menu item stands for. The item carries the clipping itself
// plus the store position it had when the menu was built; that position is only trusted
// while the store still agrees with it. Returns -1 when the clipping can no longer be
// found, in which case the caller must not paste anything.
- (int)storePositionForMenuItem:(NSMenuItem *)item
{
	id represented = [item representedObject];
	if ( ! [represented isKindOfClass:[NSArray class]] || 2 != [(NSArray *)represented count] )
		return -1;

	id hintNumber = [(NSArray *)represented objectAtIndex:0];
	id clipping = [(NSArray *)represented objectAtIndex:1];
	if ( ! [hintNumber isKindOfClass:[NSNumber class]] || ! [clipping isKindOfClass:[FlycutClipping class]] )
		return -1;

	int hint = [hintNumber intValue];
	int count = [flycutOperator jcListCount];

	// The clipping object itself is the identity, so the position it happened to have when
	// the menu was built is only a hint - checking it first keeps the common case O(1).
	if ( hint >= 0 && hint < count && [flycutOperator clippingAtPosition:hint] == clipping )
		return hint;

	for ( int i = 0; i < count; i++ )
		if ( [flycutOperator clippingAtPosition:i] == clipping )
			return i;

	// Reloading the store from disk builds new clipping objects, so fall back to clipping
	// equality: identical text contents, or for an image the same image hash. Image
	// clippings all have empty contents, so comparing contents alone would let a deleted
	// image row paste whichever other image is listed.
	for ( int i = 0; i < count; i++ )
		if ( [(FlycutClipping *)clipping isEqual:[flycutOperator clippingAtPosition:i]] )
			return i;

	return -1;
}

-(IBAction)processMenuClippingSelection:(id)sender
{
	BOOL shouldPasteImmediately = [[NSUserDefaults standardUserDefaults] boolForKey:@"menuSelectionPastes"];
	FCPasteTransaction *transaction = nil;

	// Any new menu selection changes the pasteboard and therefore invalidates older
	// delayed paste callbacks, including when this selection is configured as copy-only.
	[self cancelPendingPasteCompletion];

	if ( shouldPasteImmediately ) {
		// Capture the target before the status-menu action finishes. A delayed global Cmd-V
		// could otherwise follow an unrelated focus change into the wrong application.
		[self rememberFrontmostApplicationForPaste];
		transaction = [currentPasteTransaction retain];
	}

	// Never derive the selection from the item's position in the menu. -updateMenuContaining:
	// runs on the main queue via dispatch_async and replaces every clipping item, which can
	// happen between the click and the delivery of this action. The previous code did
	//     int index = [[sender menu] indexOfItem:sender];
	// and an item that had just been removed from the menu answers nil to -menu, so the
	// message to nil returned 0 - silently pasting the newest clipping instead of the one the
	// user clicked. Resolving by identity makes a rebuild in that window harmless.
	int position = -1;
	if ( [sender isKindOfClass:[NSMenuItem class]] )
		position = [self storePositionForMenuItem:(NSMenuItem *)sender];

	bool pasted = ( position >= 0 ) ? [self pasteStorePositionAndUpdate:position] : false;

	if ( ! pasted ) {
		// Log without any clipping contents, so a "nothing happened" report can be told
		// apart from a wrong paste later on.
		NSLog(@"processMenuClippingSelection: unresolved menu item (position=%d, item=%@) - nothing pasted",
		      position,
		      ( [sender isKindOfClass:[NSMenuItem class]] && nil != [(NSMenuItem *)sender menu] ) ? @"still in menu" : @"detached");
		NSBeep(); // Pasting some other clipping would be worse than pasting nothing at all.
	}

	if ( shouldPasteImmediately ) {
		if ( pasted && transaction != nil ) {
			[self performSelector:@selector(hideAppForPasteTransaction:)
					 withObject:transaction
					 afterDelay:0.2];
			[self performSelector:@selector(completePasteInRememberedApplication:)
					 withObject:transaction
					 afterDelay:0.5];
		} else {
			// Hide either way, so focus returns to the application the user was working in.
			[self performSelector:@selector(hideApp) withObject:nil];
			[self clearPasteTransactionIfCurrent:transaction];
		}
	}
	[transaction release];
}

-(void) setPBBlockCount:(NSNumber *)newPBBlockCount
{
    [newPBBlockCount retain];
    [pbBlockCount release];
    pbBlockCount = newPBBlockCount;
}

-(void)addClipToPasteboard:(NSString*)pbFullText
{
    [self addClipToPasteboard:pbFullText withRichData:nil];
}

// Writes the text (plus its RTF/HTML representations, when given) to the pasteboard.
// Inside a paste transaction the placement is owned: the previous clipboard is
// snapshotted first, and the written text becomes the transaction's payload.
-(void)addClipToPasteboard:(NSString*)pbFullText withRichData:(NSDictionary *)richData
{
    FCPasteTransaction *transaction = [currentPasteTransaction retain];
    if (transaction != nil) {
        if ([transaction hasSelectedPayload]) {
            [transaction release];
            return;
        }
        NSInteger originalCount = [jcPasteboard changeCount];
        NSArray *snapshot = [self snapshotPasteboardItems];
        if (snapshot == nil || [jcPasteboard changeCount] != originalCount ||
            ![self pasteTransactionIsCurrent:transaction]) {
            [self clearPasteTransactionIfCurrent:transaction];
            [transaction release];
            return;
        }
        [transaction setPreviousPasteboardItems:snapshot];
        [transaction setSelectedPayload:pbFullText];
        pbFullText = [transaction selectedPayload];
    }
    NSMutableArray *pbTypes = [NSMutableArray arrayWithObject:NSPasteboardTypeString];
    if ( nil != richData )
        [pbTypes addObjectsFromArray:[richData allKeys]];
    NSInteger declaredCount = [jcPasteboard declareTypes:pbTypes owner:nil];
    [transaction setOwnedChangeCount:declaredCount];
    BOOL written = [jcPasteboard setString:pbFullText forType:NSPasteboardTypeString];
    for ( NSString *richType in richData )
        [jcPasteboard setData:[richData objectForKey:richType] forType:richType];
    [self setPBBlockCount:@(declaredCount)];
    if (!written || [jcPasteboard changeCount] != declaredCount)
        [self clearPasteTransactionIfCurrent:transaction];
    [transaction release];
}

// Returns YES when the image (or the GIF's file reference) was placed on the pasteboard.
// Inside a paste transaction the placement is owned exactly like text: the previous
// clipboard is snapshotted first and the written representation becomes the payload.
-(BOOL)addImageClipToPasteboard:(FlycutClipping *)clipping
{
    NSString *type = [clipping type];
    if (!type || [type length] == 0)
        type = NSPasteboardTypeTIFF;

    // Animated GIFs must be offered as a FILE reference ONLY. Apps like Slack/Discord
    // upload the actual .gif file (preserving animation); if raw image data is also on
    // the pasteboard they grab that instead and flatten it to a single frame. Pointing
    // at the store file (with Save: Never, its temporary copy) is safe — it lives as
    // long as the clipping does.
    NSURL *fileURL = nil;
    NSData *imageData = nil;
    if ([type isEqualToString:@"com.compuserve.gif"]) {
        NSString *path = [[FlycutImageStore sharedStore] imageFilePathForHash:[clipping imageHash]];
        if (path)
            fileURL = [NSURL fileURLWithPath:path];
    }
    if (fileURL == nil)
        imageData = [[FlycutImageStore sharedStore] imageDataForHash:[clipping imageHash]];

    FCPasteTransaction *transaction = [currentPasteTransaction retain];
    if (transaction != nil && [transaction hasSelectedPayload]) {
        // The transaction's first placement stays its payload, as for text.
        [transaction release];
        return YES;
    }
    if (fileURL == nil && imageData == nil) {
        // Nothing can be placed, so this selection must not paste whatever is there now.
        [self clearPasteTransactionIfCurrent:transaction];
        [transaction release];
        return NO;
    }
    if (transaction != nil) {
        NSInteger originalCount = [jcPasteboard changeCount];
        NSArray *snapshot = [self snapshotPasteboardItems];
        if (snapshot == nil || [jcPasteboard changeCount] != originalCount ||
            ![self pasteTransactionIsCurrent:transaction]) {
            [self clearPasteTransactionIfCurrent:transaction];
            [transaction release];
            return NO;
        }
        [transaction setPreviousPasteboardItems:snapshot];
        if (fileURL != nil) {
            [transaction setSelectedPayloadType:NSPasteboardTypeFileURL];
            [transaction setSelectedPayloadData:[[fileURL absoluteString] dataUsingEncoding:NSUTF8StringEncoding]];
        } else {
            [transaction setSelectedPayloadType:type];
            [transaction setSelectedPayloadData:imageData];
        }
    }

    NSInteger declaredCount;
    BOOL written;
    if (fileURL != nil) {
        declaredCount = [jcPasteboard clearContents];
        [transaction setOwnedChangeCount:declaredCount];
        written = [jcPasteboard writeObjects:@[fileURL]];
    } else {
        declaredCount = [jcPasteboard declareTypes:@[type] owner:nil];
        [transaction setOwnedChangeCount:declaredCount];
        written = [jcPasteboard setData:imageData forType:type];
    }
    [self setPBBlockCount:@(declaredCount)];
    if (!written || [jcPasteboard changeCount] != declaredCount) {
        [self clearPasteTransactionIfCurrent:transaction];
        written = NO;
    }
    [transaction release];
    return written;
}

-(NSURL *)animatedGifURLFromPasteboard
{
    NSData *htmlData = [jcPasteboard dataForType:@"public.html"];
    if (htmlData == nil || [htmlData length] == 0)
        return nil;

    NSString *html = [[[NSString alloc] initWithData:htmlData encoding:NSUTF8StringEncoding] autorelease];
    if (html == nil || [html length] == 0)
        return nil;

    // Pull the first <img ... src="..."> URL out of the clipboard HTML.
    NSRegularExpression *re = [NSRegularExpression regularExpressionWithPattern:@"<img[^>]+src=[\"']([^\"']+)[\"']"
                                                                       options:NSRegularExpressionCaseInsensitive
                                                                         error:nil];
    if (re == nil)
        return nil;
    NSTextCheckingResult *match = [re firstMatchInString:html options:0 range:NSMakeRange(0, [html length])];
    if (match == nil || [match numberOfRanges] < 2)
        return nil;

    NSString *src = [html substringWithRange:[match rangeAtIndex:1]];
    NSURL *url = [NSURL URLWithString:src];
    if (url == nil)
        return nil;

    // Only fetch over HTTPS, and only when the URL actually points at a GIF.
    if (![[[url scheme] lowercaseString] isEqualToString:@"https"])
        return nil;
    if (![[[url path] lowercaseString] hasSuffix:@".gif"])
        return nil;

    return url;
}

-(void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL pasteboardGeneration:(NSInteger)generation
{
    // Pausing capture while the download runs discards it, as for clipboard reads.
    NSUInteger captureEpoch = clipboardCaptureEpoch;
    int maxSizeKB = (int)[[NSUserDefaults standardUserDefaults] integerForKey:@"maxImageSizeKB"];
    if (maxSizeKB <= 0) maxSizeKB = 10240;
    NSUInteger maxBytes = (NSUInteger)maxSizeKB * 1024;

    NSURLSessionConfiguration *config = [NSURLSessionConfiguration ephemeralSessionConfiguration];
    config.timeoutIntervalForRequest = 5.0;
    config.timeoutIntervalForResource = 10.0;
    NSURLSession *session = [NSURLSession sessionWithConfiguration:config];

    NSURLSessionDataTask *task = [session dataTaskWithURL:url completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        // On any failure (offline, timeout, non-200, too big, not an animated GIF) do
        // nothing — per design we skip the entry rather than fall back to a still.
        if (error != nil || data == nil || [data length] == 0)
            return;
        if ([response isKindOfClass:[NSHTTPURLResponse class]] && [(NSHTTPURLResponse *)response statusCode] != 200)
            return;
        if ([data length] > maxBytes || [data length] < 6)
            return;

        // Verify GIF magic bytes ("GIF87a"/"GIF89a")...
        const unsigned char *bytes = (const unsigned char *)[data bytes];
        if (!(bytes[0] == 'G' && bytes[1] == 'I' && bytes[2] == 'F'))
            return;

        // ...and that it is actually animated (more than one frame).
        NSBitmapImageRep *rep = [NSBitmapImageRep imageRepWithData:data];
        NSNumber *frames = rep ? [rep valueForProperty:NSImageFrameCount] : nil;
        if (frames == nil || [frames integerValue] <= 1)
            return;

        NSData *gifData = [data retain];
        dispatch_async(dispatch_get_main_queue(), ^{
            // The download can finish after the user copied something else, paused
            // capture, turned diagnostics on, or turned image capture or GIF downloads off.
            // Diagnostics turned on during the download: save no payload.
            BOOL revealPasteboardTypes = [[NSUserDefaults standardUserDefaults] boolForKey:@"revealPasteboardTypes"];
            if ( captureEpoch == clipboardCaptureEpoch && ! [pbCount isEqualTo:pbBlockCount] && !revealPasteboardTypes
                 && [self isImageCaptureCurrentForGeneration:generation]
                 && [[NSUserDefaults standardUserDefaults] boolForKey:@"downloadAnimatedGIFs"] ) {
                [flycutOperator addImageClipping:gifData fromApp:appName withAppBundleURL:bundleURL imageType:@"com.compuserve.gif" target:self clippingAddedSelector:@selector(clippingWasAdded)];
            }
            [gifData release];
        });
    }];
    [task resume];
    [session finishTasksAndInvalidate];
}

-(BOOL)isImageCaptureCurrentForGeneration:(NSInteger)generation
{
    return [jcPasteboard changeCount] == generation
        && [pbBlockCount integerValue] != generation
        && ![flycutOperator storeDisabled]
        && [[NSUserDefaults standardUserDefaults] boolForKey:@"captureImages"];
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

    if ([clipping isImageClipping]) {
        NSData *imageData = [[FlycutImageStore sharedStore] imageDataForHash:[clipping imageHash]];
        if (imageData) {
            NSImage *image = [[NSImage alloc] initWithData:imageData];
            [bezel setImage:image];
            [image release];
        } else {
            [bezel setText:@"[Image not found]"];
        }
    } else {
        [bezel setText:[NSString stringWithFormat:@"%@", [clipping contents]]];
    }

    [bezel setCharString:[self bezelCounterString]];

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

// The counter below the bezel's text: "2 of 12", or "Empty". The Favorites view adds a
// star (U+2605, a text glyph in the counter's grey, not the colour emoji U+2B50), so "f"
// visibly switches lists; the history gets no mark. A pinned bezel adds "(pinned)" after
// every key, not only after the Space or right click that pinned it.
-(NSString *)bezelCounterString
{
	int count = [flycutOperator jcListCount];
	NSString *counter = count == 0 ? @"Empty" :
		[NSString stringWithFormat:@"%d of %d", [flycutOperator stackPosition] + 1, count];
	if ( [flycutOperator favoritesStoreIsSelected] )
		counter = [counter stringByAppendingString:@" \u2605"];
	if ( isBezelPinned )
		counter = [counter stringByAppendingString:@" (pinned)"];
	return counter;
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
    NSString *key = aRecorder == mainRecorder ? @"ShortcutRecorder mainHotkey" :
                    aRecorder == searchRecorder ? @"ShortcutRecorder searchHotkey" : nil;
    if (key == nil)
        return;
    // The registered shortcut applies while none is stored, so a shortcut
    // equal to it is not stored: restoring the default drops the stored one.
    if (FlycutKeyComboIsRegistered([aRecorder keyCombo], key)) {
        [[NSUserDefaults standardUserDefaults] removeObjectForKey:key];
        return;
    }
    NSDictionary *hotKeyDict = @{
        @"keyCode": @([aRecorder keyCombo].code),
        @"modifierFlags": @([aRecorder keyCombo].flags)
    };
    [[NSUserDefaults standardUserDefaults] setObject:hotKeyDict forKey:key];
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
	[self updateRestoreDefaultButtons];
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

// Called by -[FlycutOperator addClipping:...] once the store has been changed AND the stack
// position has been moved to follow the user's selection across that change.
- (void)clippingWasAdded
{
	[self updateMenu];

	// The store redraws the bezel from inside its own insert, by way of -endUpdates, which is
	// before the stack position has been settled.  Left at that, the bezel would show the
	// neighbour of the clipping a paste would actually deliver.  Redraw now that it is settled.
	if ( isBezelDisplayed )
		[self updateBezel];
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

	// Create a normal window with standard controls
	CGFloat windowWidth = 600;
	CGFloat windowHeight = 400;

	NSRect windowFrame = NSMakeRect(0, 0, windowWidth, windowHeight);
	searchWindow = [[SearchWindow alloc] initWithContentRect:windowFrame
													styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
													  backing:NSBackingStoreBuffered
														defer:NO];
	((SearchWindow *)searchWindow).appController = self;

	[searchWindow setTitle:@"Search Clipboard"];
	[searchWindow setLevel:NSFloatingWindowLevel];
	[searchWindow center];

	// Create the search field at the top
	CGFloat fieldY = windowHeight - 60;
	searchWindowSearchField = [[NSSearchField alloc] initWithFrame:NSMakeRect(20, fieldY, windowWidth - 40, 25)];
	[searchWindowSearchField setTarget:self];
	[searchWindowSearchField setAction:@selector(searchWindowSearchFieldChanged:)];
	[searchWindowSearchField setFont:[NSFont systemFontOfSize:13]];
	[searchWindowSearchField setDelegate:self];  // Set delegate for keyboard handling
	FlycutSetAccessibilityLabel(searchWindowSearchField, [searchWindow title]);
	[[searchWindow contentView] addSubview:searchWindowSearchField];

	// Create the table view
	CGFloat tableHeight = fieldY - 20;
	NSScrollView *scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(20, 20, windowWidth - 40, tableHeight)];
	[scrollView setHasVerticalScroller:YES];
	[scrollView setAutohidesScrollers:YES];
	[scrollView setBorderType:NSBezelBorder];

	searchWindowTableView = [[NSTableView alloc] init];
	[searchWindowTableView setDelegate:self];
	[searchWindowTableView setDataSource:self];
	[searchWindowTableView setTarget:self];
	[searchWindowTableView setDoubleAction:@selector(searchWindowItemSelected:)];
	[searchWindowTableView setRowHeight:24];
	[searchWindowTableView setIntercellSpacing:NSMakeSize(3, 2)];

	// Add a single column
	NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:@"content"];
	[column setTitle:@"Clipboard Content"];
	[column setWidth:windowWidth - 60];
	[searchWindowTableView addTableColumn:column];
	[searchWindowTableView setAccessibilityLabel:[column title]];
	[column release];

	[scrollView setDocumentView:searchWindowTableView];
	[[searchWindow contentView] addSubview:scrollView];
	[scrollView release];

	// Set up window delegate
	[searchWindow setDelegate:self];

	// Set initial first responder for proper focus
	[searchWindow setInitialFirstResponder:searchWindowSearchField];
}

- (void)showSearchWindow
{
	// Capture the user's current application before Flycut activates its search window.
	// A search selection must use the same immutable PID/focus transaction as the bezel
	// and menu paste paths rather than posting a delayed global Cmd-V.
	[self cancelPendingPasteCompletion];
	[self rememberFrontmostApplicationForPaste];

	if (!searchWindow) {
		[self buildSearchWindow];
	}

	[self updateSearchResults];

	// Activate app and show window
	[NSApp activateIgnoringOtherApps:YES];
	[searchWindow makeKeyAndOrderFront:self];

	// Set focus on search field
	[searchWindow makeFirstResponder:searchWindowSearchField];

	isSearchWindowDisplayed = YES;
}

- (void)hideSearchWindow
{
	[self cancelPendingPasteCompletion];
	[self hideSearchWindowPreservingPasteTransaction];
}

- (void)hideSearchWindowPreservingPasteTransaction
{
	[searchResultClippings release];
	searchResultClippings = nil;
	// Set this before orderOut: its resign-key notification must not cancel the
	// successful selection's still-pending PID-bound transaction.
	isSearchWindowDisplayed = NO;
	if (searchWindow) {
		[searchWindow orderOut:nil];
		// Clear the search field for next time
		[searchWindowSearchField setStringValue:@""];
	}

	// Clean up search results
	if (searchResults) {
		[searchResults release];
		searchResults = nil;
	}
}

- (IBAction)searchWindowSearchFieldChanged:(id)sender
{
	[self updateSearchResults];
}

- (void)updateSearchResults
{
	NSString *searchText = [searchWindowSearchField stringValue];

	// Publish titles and retained identities from the same main-thread snapshot.
	// An in-flight capture may insert into the store after this method returns.
	NSMutableArray *titles = [NSMutableArray array];
	NSMutableArray *clippings = [NSMutableArray array];
	NSArray *indexes = [flycutOperator previousIndexes:
		[[NSUserDefaults standardUserDefaults] integerForKey:@"displayNum"] containing:searchText];
	for (NSNumber *index in indexes) {
		FlycutClipping *clipping = [flycutOperator clippingAtPosition:[index intValue]];
		if (clipping != nil) {
			[titles addObject:[clipping displayString]];
			[clippings addObject:clipping];
		}
	}
	[searchResults release];
	searchResults = [titles copy];
	[searchResultClippings release];
	searchResultClippings = [clippings copy];

	[searchWindowTableView reloadData];

	// Auto-select first row for keyboard navigation
	if (searchResults && [searchResults count] > 0) {
		[searchWindowTableView selectRowIndexes:[NSIndexSet indexSetWithIndex:0] byExtendingSelection:NO];
	}
}

- (IBAction)searchWindowItemSelected:(id)sender
{
	NSInteger selectedRow;
	if ( sender == searchWindowTableView ) {
		// A double click below the last row still fires the table's double action, but with
		// clickedRow == -1 and the selection cleared. Falling back to row 0 would paste the
		// newest clipping instead of doing nothing.
		selectedRow = [searchWindowTableView clickedRow];
		if (selectedRow < 0) {
			return;
		}
	} else {
		selectedRow = [searchWindowTableView selectedRow];
		if (selectedRow < 0) {
			selectedRow = 0; // Default to first item if none selected
		}
	}

	if (selectedRow < [searchResults count]) {
		if (selectedRow >= (NSInteger)[searchResultClippings count])
			return;
		FlycutClipping *selectedClipping = [searchResultClippings objectAtIndex:selectedRow];
		int position = -1;
		for (int index = 0; index < [flycutOperator jcListCount]; index++) {
			if ([flycutOperator clippingAtPosition:index] == selectedClipping) {
				position = index;
				break;
			}
		}
		// Evicted/reloaded identities must never redirect to another visible row.
		if (position < 0) {
			[self cancelPendingPasteCompletion];
			return;
		}

		FCPasteTransaction *transaction = [currentPasteTransaction retain];
		if ( [self pasteStorePositionAndUpdate:position] ) {
			[self hideSearchWindowPreservingPasteTransaction];

			// Search selection always pastes, independent of menuSelectionPastes, but only
			// through the transaction captured before this window took focus.
			if ( [self pasteTransactionIsCurrent:transaction] ) {
				[self performSelector:@selector(completePasteInRememberedApplication:)
						 withObject:transaction
						 afterDelay:0.3];
			} else {
				NSLog(@"Search-window paste cancelled because no current target transaction exists");
			}
		}
		[transaction release];
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
		// Customize cell appearance to match bezel style with modern system colors
		NSTextFieldCell *textCell = (NSTextFieldCell *)cell;
		if (@available(macOS 10.14, *)) {
			[textCell setTextColor:[NSColor labelColor]];
		} else {
			[textCell setTextColor:[NSColor whiteColor]];
		}
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

- (BOOL)windowShouldClose:(NSWindow *)sender
{
	if (sender == searchWindow) {
		[self hideSearchWindow];
		return NO; // We handle the closing ourselves
	}
	return YES;
}

- (void)cancelOperation:(id)sender
{
	// Handle ESC key for search window
	NSLog(@"cancelOperation called, isSearchWindowDisplayed: %d", isSearchWindowDisplayed);
	if (isSearchWindowDisplayed) {
		[self hideSearchWindow];
	}
}

- (void)performClose:(id)sender
{
	// Handle cmd-W for search window
	NSLog(@"performClose called, isSearchWindowDisplayed: %d", isSearchWindowDisplayed);
	if (isSearchWindowDisplayed) {
		[self hideSearchWindow];
	}
}

- (void) dealloc {
	[searchResultClippings release];
	[self cancelPendingPasteCompletion];
	if (statusItemMouseDownMonitor != nil) {
		[NSEvent removeMonitor:statusItemMouseDownMonitor];
		[statusItemMouseDownMonitor release];
		statusItemMouseDownMonitor = nil;
	}
	[clipboardTrackingMenuItem release];
	[menuIconCustomColorsCheckbox release];
	[menuIconActiveColorWell release];
	[menuIconPausedColorWell release];
	[menuIconActivePreview release];
	[menuIconPausedPreview release];

	[bezel release];
	[srTransformer release];
	[searchRecorder release];
	[searchWindow release]; // This will release its subviews automatically
	[searchResults release];
	[sRetiredMenuClippingItems release];
	sRetiredMenuClippingItems = nil;
	[super dealloc];
}

@end
