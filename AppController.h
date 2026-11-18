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

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import "BezelWindow.h"
#import "SRRecorderControl.h"
#import "SRKeyCodeTransformer.h"
#import "FlycutOperator.h"
#import "SGHotKey.h"

@class SGHotKey;
@class FlycutClipping;
@class FlycutListController;
@class FCClipboardCatchUp;
@class FlycutAccountShareService;

@interface AppController : NSResponder <NSMenuDelegate, NSApplicationDelegate, FlycutStoreDelegate, FlycutOperatorDelegate, BezelWindowDelegate> {
    BezelWindow					*bezel;
	SGHotKey					*mainHotKey;
	IBOutlet SRRecorderControl	*mainRecorder;
	SGHotKey					*searchHotKey;
	SRRecorderControl			*searchRecorder;
	IBOutlet NSPanel			*prefsPanel;
	IBOutlet NSTextView			*acknowledgementsView;
	IBOutlet NSBox			  *appearancePanel;
	int							mainHotkeyModifiers;
	SRKeyCodeTransformer        *srTransformer;
	BOOL						isBezelDisplayed;
	BOOL						isBezelPinned;
	BOOL						bezelSelectionFinished;	// the shown bezel was pasted or cancelled
	BOOL						isMenuOpen;
	NSUInteger nextPasteTransactionGeneration;
	id currentPasteTransaction;
	BOOL						hasShownAccessibilityExplanationThisSession;
	NSString					*currentKeycodeCharacter;
    NSDateFormatter*            dateFormat;
	
	// Search window components
	NSWindow					*searchWindow;
	NSSearchField				*searchWindowSearchField;
	NSTableView					*searchWindowTableView;
	NSArray						*searchResults;
	NSArray *searchResultClippings;
	BOOL						isSearchWindowDisplayed;

    FlycutOperator				*flycutOperator;

    // Status item -- the little icon in the menu bar
    NSStatusItem *statusItem;
    id statusItemMouseDownMonitor;
    // When the mouse-down monitor last finished with a press (seconds since startup).
    NSTimeInterval statusItemMouseDownHandledAt;
    NSMenuItem *clipboardTrackingMenuItem;
    NSButton *menuIconCustomColorsCheckbox;
    NSColorWell *menuIconActiveColorWell;
    NSColorWell *menuIconPausedColorWell;
    NSImageView *menuIconActivePreview;
    NSImageView *menuIconPausedPreview;
    // "Share copied text with other accounts on this Mac" (General pane).
    FlycutAccountShareService *accountShareService;
    NSInteger accountShareOfferedGeneration;   // the clipboard generation offered last (-pollPB:)
    NSButton *accountSharingCheckbox;

    IBOutlet NSTextField *savingSectionLabel;
    IBOutlet NSTextField *saveFromBezelToLabel;
    IBOutlet NSTextField *forgottenItemLabel;
    IBOutlet NSButton *forgottenFavoritesCheckbox;
    IBOutlet NSButton *forgottenClippingsCheckbox;
    IBOutlet NSButton *saveToLocationButton;
    IBOutlet NSButton *autoSaveToLocationButton;
    // The menu attatched to same
    IBOutlet NSMenu *jcMenu;
    // The list the status item opens (search, favorites, history, commands).
    FlycutListController *listController;
    // The search field of the status menu in MainMenu.nib. The menu-bar list has its own;
    // the outlet stays because loading the nib sets it.
    IBOutlet NSSearchField *searchBox;
    dispatch_queue_t clipboardReadQueue;
    FCClipboardCatchUp *clipboardCatchUp; // -captureClipboardChangeNow waits for this poll's reads
    BOOL bezelClosesKeepingFlycutShown;   // -closeBezelKeepingFlycutShown is ordering the bezel out
    NSEvent *menuOpenEvent;
    IBOutlet NSSlider * heightSlider;
    IBOutlet NSSlider * widthSlider;
    
    // A timer which will let us check the pasteboard;
    // this should default to every .5 seconds but be user-configurable
    NSTimer *pollPBTimer;
    // We want an interface to the pasteboard
    NSPasteboard *jcPasteboard;
    // Track the clipboard count so we only act when its contents change
    NSNumber *pbCount;
    //stores PasteboardCount for internal Flycut pasteboard actions so they don't trigger any events
    NSNumber *pbBlockCount;
    // Advanced whenever clipboard capture is paused or resumed; a capture commits only in the epoch it started in
    NSUInteger clipboardCaptureEpoch;
    //Preferences
	NSDictionary *standardPreferences;
    int jcDisplayNum;
	BOOL needBezelUpdate;
}

// Basic functionality
-(void) pollPB:(NSTimer *)timer;
-(void) addClipToPasteboard:(NSString*)pbFullText;
-(BOOL) addImageClipToPasteboard:(FlycutClipping *)clipping;
-(void) addClipToPasteboard:(NSString*)pbFullText withRichData:(NSDictionary *)richData;
-(void) setPBBlockCount:(NSNumber *)newPBBlockCount;
-(void) hideApp;
-(void) fakeCommandV;
-(IBAction)clearClippingList:(id)sender;
-(IBAction)mergeClippingList:(id)sender;
-(BOOL)control:(NSControl *)control textView:(NSTextView *)fieldEditor doCommandBySelector:(SEL)commandSelector;

// Hotkey related
-(void)hitMainHotKey:(SGHotKey *)hotKey;
-(void)hitSearchHotKey:(SGHotKey *)hotKey;
-(IBAction)toggleSearchHotKey:(id)sender;

// Search window related
-(void) showSearchWindow;
-(void) hideSearchWindow;
-(void) buildSearchWindow;
-(void) updateSearchResults;
-(IBAction)searchWindowItemSelected:(id)sender;
-(void) cancelOperation:(id)sender;
-(void) performClose:(id)sender;

// Bezel related
-(void) updateBezel;
-(void) showBezel;
-(void) hideBezel;
-(void) processBezelKeyDown:(NSEvent *)theEvent;
-(void) processBezelMouseEvents:(NSEvent *)theEvent;
-(void) metaKeysReleased;
-(void) windowDidResignKey:(NSNotification *)notification;

// Menu related
-(IBAction) activateAndOrderFrontStandardAboutPanel:(id)sender;

// Preference related
-(IBAction) showPreferencePanel:(id)sender;
-(IBAction) setRememberNumPref:(id)sender;
-(IBAction) setFavoritesRememberNumPref:(id)sender;
-(IBAction) setDisplayNumPref:(id)sender;
-(IBAction) setBezelAlpha:(id)sender;
-(IBAction) setBezelHeight:(id)sender;
-(IBAction) setBezelWidth:(id)sender;
-(void)updateMenuBarIcon;
-(IBAction)toggleClipboardTracking:(id)sender;
-(IBAction)toggleMenuIconCustomColors:(id)sender;
-(IBAction)setActiveMenuIconColor:(id)sender;
-(IBAction)setPausedMenuIconColor:(id)sender;
-(IBAction) toggleLoadOnStartup:(id)sender;
-(IBAction) toggleMainHotKey:(id)sender;
-(IBAction) recheckAccessibility:(id)sender;
-(void) setHotKeyPreferenceForRecorder:(SRRecorderControl *)aRecorder;

@end
