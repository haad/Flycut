# Coding Conventions

**Analysis Date:** 2026-03-05

## Language & Environment

**Primary Language:** Objective-C
- Uses manual memory management with `retain`, `release`, and `autorelease`
- Targets macOS (AppKit framework)

## Naming Patterns

**Files:**
- Header files: `FileName.h`
- Implementation files: `FileName.m`
- Prefix header: `Flycut_Prefix.pch`
- Configuration files: `Debug.xcconfig`, `Release.xcconfig`
- Pattern: PascalCase for class names, lowercase with extensions for utility files

**Classes & Interfaces:**
- PascalCase: `AppController`, `FlycutOperator`, `FlycutStore`, `FlycutClipping`, `BezelWindow`
- Protocols end with descriptive suffixes: `FlycutStoreDelegate`, `BezelWindowDelegate`, `FlycutOperatorDelegate`

**Methods:**
- Instance methods use camelCase with descriptive action verbs
- Private methods use lowercase leading underscore prefix is NOT used; all methods start lowercase
- Action methods use `IBAction` prefix: `-(IBAction)clearClippingList:(id)sender`
- Getter/setter patterns: `-(void)setRememberNum:(int)newRemember`, `-(int)rememberNum`
- Navigation methods use directional/positional verbs: `stackUp`, `stackDown`, `moveItemAtStackPositionToTopOfStack`
- Boolean methods use predicate form: `removeDuplicates`, `stackPositionIsInBounds`, `storeDisabled`
- Update/refresh methods: `updateMenu`, `updateBezel`, `updateSearchResults`

**Variables & Properties:**
- Instance variables use prefix notation: `jcPasteboard`, `pbCount`, `pbBlockCount`, `flycutOperator`
- Common prefixes in codebase: `jc*` (Jumpcut legacy), `pb*` (pasteboard), `bezel*` (UI component)
- Boolean variables: `isBezelDisplayed`, `isSearchWindowDisplayed`, `modifiedSinceLastSaveStore`
- Integer counters: `jcRememberNum`, `jcDisplayNum`, `jcDisplayLen`, `stackPosition`

**Types:**
- Custom classes: `FlycutStore`, `FlycutOperator`, `FlycutClipping`, `BezelWindow`
- Standard types used: `NSString`, `NSMutableArray`, `NSArray`, `NSTimer`, `NSPasteboard`
- Primitive types: `int`, `BOOL`, `NSInteger`, `bool` (mix of Objective-C and C conventions)

## Code Style

**Formatting:**
- No explicit formatting tool configured (eslint/prettier equivalent)
- Manual indentation: tabs for method bodies
- Brace style: Opening braces on same line for methods and control structures
- Line length: Variable, some lines exceed 100 characters

**Comments & Documentation:**
- File headers include copyright, license, and purpose comment:
  ```objc
  //
  //  FileName.m
  //  Flycut
  //
  //  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
  //  Copyright 2011 General Arcade. All rights reserved.
  //
  //  This code is open-source software subject to the MIT License; see the homepage
  //  at <https://github.com/TermiT/Flycut> for details.
  //
  ```
- Class purpose documented above `@interface` or `@implementation`
- Method documentation uses `/*"` comment style for longer descriptions:
  ```objc
  /*" +fakeCommandV synthesizes keyboard events for Cmd-v Paste shortcut. "*/
  ```
- Pragma marks used to organize sections: `#pragma mark - Search Hotkey Methods`

**Linting:**
- Build configuration enables assertions: `ENABLE_NS_ASSERTIONS = YES`
- Warnings treated as errors disabled for development: `GCC_TREAT_WARNINGS_AS_ERRORS = NO`
- Debug preprocessor macro enabled: `GCC_PREPROCESSOR_DEFINITIONS = DEBUG=1`

## Logging

**Framework:** Standard `NSLog` with conditional `DLog` macro
- Defined in `Flycut_Prefix.pch`:
  ```objc
  #ifdef DEBUG
  #   define DLog(fmt, ...) NSLog((@"%s [Line %d] " fmt), __PRETTY_FUNCTION__, __LINE__, ##__VA_ARGS__);
  #else
  #   define DLog(...)
  #endif
  ```
- `DLog()` is conditional debug logging - only outputs in DEBUG builds
- `NSLog()` is used for non-debug informational/diagnostic logs

**Patterns:**
- Accessibility diagnostics use prefixed log messages: `NSLog(@"[Accessibility] ...")`
- Startup diagnostics: `NSLog(@"[Flycut Startup] ...")`
- Operation-specific logs: `NSLog(@"stackDown: ...")`, `NSLog(@"fakeCommandV ...")`, `NSLog(@"pasteFromStack ...")`
- Bundle diagnostic info always logged on startup for troubleshooting
- When to use NSLog: Accessibility permission checks, startup diagnostics, user actions (paste, stack changes)
- When to use DLog: Debug-only detailed tracing, line numbers captured automatically

**Example logging patterns:**
```objc
NSLog(@"[Flycut Startup] Bundle Path: %@", bundlePath);
NSLog(@"[Accessibility] Alert check - Bundle: %@, ID: %@, Trusted: %@",
      bundlePath, bundleID, trusted ? @"YES" : @"NO");
NSLog(@"pasteFromStack called");
DLog(@"list=%@, oldItems=%d, newItems=%d", returnedDisplayStrings, oldItems, newItems);
```

## Import Organization

**Order:**
1. Standard library frameworks (Cocoa, Foundation, ApplicationServices, CoreFoundation, ServiceManagement)
2. Custom project headers (AppController, FlycutOperator, UI components, third-party libraries)

**Examples from codebase:**
```objc
// Frameworks first
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <CoreFoundation/CoreFoundation.h>
#import <ServiceManagement/ServiceManagement.h>

// Project headers
#import "AppController.h"
#import "SGHotKey.h"
#import "SGHotKeyCenter.h"
#import "SRRecorderCell.h"
#import "NSWindow+TrueCenter.h"
#import "NSWindow+ULIZoomEffect.h"
#import "BezelWindow.h"
#import "FlycutOperator.h"
```

**Path aliases:**
- No path aliases used; relative imports used throughout

## Error Handling

**Strategy:** Defensive programming with nil checks and error callbacks
- No try/catch blocks used
- Conditional checks for nil: `if (nil != content)`, `if (!accessibilityEnabled)`
- Optional delegate callbacks with respondsToSelector checks:
  ```objc
  if ( self.delegate && [self.delegate respondsToSelector:@selector(beginUpdates)] )
      [self.delegate beginUpdates];
  ```
- NSError patterns used for system APIs:
  ```objc
  NSError *error = nil;
  if (![loginItem registerAndReturnError:&error]) {
      NSLog(@"Failed to enable login item: %@", error);
  }
  ```

## Method Design

**Size Guidelines:**
- Methods range from 2 lines to 250+ lines
- Large methods like `awakeFromNib` exceed 300 lines - candidates for refactoring
- Preference for focused methods handling single responsibility
- Callback/delegate patterns used to handle complexity

**Parameters:**
- Single parameter methods common: `-(void)clearList`, `-(void)hideApp`
- Multi-parameter methods use descriptive names: `-(id)initRemembering:(int)nowRemembering displaying:(int)nowDisplaying withDisplayLength:(int)displayLength`
- IBAction methods always receive `(id)sender`
- Block parameters used in dispatch patterns: `dispatch_async(dispatch_get_main_queue(), ^{ ... })`

**Return Values:**
- Boolean returns indicate success/failure: `-(bool)addClipping:...`, `-(bool)removeDuplicates`
- Integer returns for counts/positions: `-(int)rememberNum`, `-(int)stackPosition`
- Object returns for retrieved data: `-(FlycutClipping*)clippingAtPosition:`
- Void returns for actions: `-(void)showBezel`, `-(void)hideApp`
- BOOL (Objective-C bool) preferred over bool (C bool) in newer code

## Module Design

**Exports:**
- All public methods declared in `.h` header file
- Private methods only in implementation files
- Properties declared with `@property` syntax when appropriate
- Delegate properties marked `(nonatomic, nullable, assign)`: `@property (nonatomic, nullable, assign) id<FlycutStoreDelegate> delegate;`

**Barrel Files:**
- Not used in this codebase

## Memory Management

**Pattern:** Manual reference counting (pre-ARC Objective-C)
- Explicit `retain` on initialization: `[settingsSyncList retain];`
- Manual `release` in dealloc: `[bezel release];`, `[srTransformer release];`
- `autorelease` used in array creation: `NSMutableArray *returnArray = [[[NSMutableArray alloc] init] autorelease];`
- Pasteboard/NS* object lifecycle managed explicitly
- String copies for safety: `[NSString stringWithString:value]`

**Dealloc pattern:**
```objc
- (void) dealloc {
    [bezel release];
    [srTransformer release];
    [searchRecorder release];
    [searchWindow release];
    [searchResults release];
    [super dealloc];
}
```

## Build Configuration

**Debug configuration (`Debug.xcconfig`):**
- `GCC_OPTIMIZATION_LEVEL = 0` - no optimization for debugging
- `DEBUG_INFORMATION_FORMAT = dwarf` - debugging symbols
- `ENABLE_NS_ASSERTIONS = YES` - assertions enabled
- `ENABLE_TESTABILITY = YES` - test code accessible
- `GCC_PREPROCESSOR_DEFINITIONS = DEBUG=1` - DEBUG macro defined
- `GCC_TREAT_WARNINGS_AS_ERRORS = NO` - warnings not errors
- `DEAD_CODE_STRIPPING = NO` - aid debugging

**Release configuration (`Release.xcconfig`):**
- Different optimization level (not examined, but standard Xcode pattern)

## Dispatch & Threading

**Grand Dispatch Center (GCD) usage:**
- Serial queue for menu updates: `dispatch_queue_create(@"com.Flycut.menuUpdateQueue", DISPATCH_QUEUE_SERIAL)`
- Async dispatch to main queue for UI updates: `dispatch_async(dispatch_get_main_queue(), ^{ ... })`
- Global queue for blocking operations: `dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0)`
- Delayed execution: `dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)), ...)`
- Block syntax used consistently for async operations

**NSTimer patterns:**
- Scheduled in NSRunLoopCommonModes to work while menu is open
- Manual timer creation with target/selector: `[[NSTimer alloc] initWithFireDate:... interval:... target:... selector:...`
- Blocks not used with NSTimer (manual reference-counted code predates modern block timers)

## Objective-C Conventions

**Message passing:**
- Bracket notation exclusively: `[object method:param]`
- Nested calls common: `[[[NSUserDefaults standardUserDefaults] valueForKey:@""] boolValue]`
- Nil is a valid receiver (returns nil/0)

**Categories & Extensions:**
- Custom categories used: `NSWindow+TrueCenter`, `NSWindow+ULIZoomEffect`
- Extends standard Framework classes with utility methods

**Protocols:**
- Delegate protocols with `@optional` methods common
- Example: `@protocol FlycutStoreDelegate <NSObject>` with optional `beginUpdates`, `endUpdates`, etc.

---

*Convention analysis: 2026-03-05*
