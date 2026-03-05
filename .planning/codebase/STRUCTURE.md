# Codebase Structure

**Analysis Date:** 2026-03-05

## Directory Layout

```
/Volumes/Devel/apple/Flycut/
├── AppController.m/h          # Main application controller, UI orchestration
├── FlycutOperator.m/h         # Business logic facade for clipboard operations
├── main.m                      # Application entry point
├── FlycutEngine/               # Data persistence layer
│   ├── FlycutStore.m/h         # Ordered clipping collection with bounds management
│   └── FlycutClipping.m/h      # Value object representing single clipboard item
├── UI/                         # Custom UI components and window controllers
│   ├── BezelWindow.m/h         # Popup window rendering clippings
│   ├── RoundRecTextField.m/h   # Search field with rounded corners
│   ├── RoundRecBezierPath.m/h  # Rounded rectangle path drawing utility
│   └── NSWindow+*.m/h          # Window category extensions (centering, zoom effects)
├── SGHotKeysLib/               # Global hotkey registration library
│   ├── SGHotKeyCenter.m/h      # Manages registered hotkeys
│   ├── SGHotKey.m/h            # Individual hotkey representation
│   ├── SGKeyCombo.m/h          # Keyboard key combination encoding
│   └── SGKeyCodeTranslator.m/h # macOS keycode to character translation
├── ShortcutRecorder/           # Keyboard shortcut capture UI framework
├── UKPrefsPanel/               # Preferences window framework
├── FlycutHelper/               # Helper application (launch agent)
│   ├── AppDelegate.m/h
│   ├── main.m
│   └── Info.plist
├── MJCloudKitUserDefaultsSync/ # CloudKit sync library (infrastructure only, currently disabled)
├── English.lproj/              # Localization bundle
│   └── MainMenu.nib            # IB-designed main menu and UI
├── Resources/                  # Images, icons, documentation
├── Flycut.xcodeproj/           # Xcode project configuration
├── Info.plist                  # Application metadata
├── Flycut.entitlements         # App entitlements (release build)
├── FlycutDebug.entitlements    # App entitlements (debug build)
├── Flycut_Prefix.pch           # Precompiled header
└── Debug.xcconfig / Release.xcconfig  # Build configuration settings
```

## Directory Purposes

**FlycutEngine:**
- Purpose: Manages all data persistence and in-memory clipboard history
- Contains: Core data model classes (FlycutClipping, FlycutStore) with no UI dependencies
- Key files: `FlycutStore.m/h` (main collection), `FlycutClipping.m/h` (item model)
- Patterns: Value objects with observable collections via delegate pattern

**UI:**
- Purpose: Custom macOS UI components and window behavior extensions
- Contains: Bezel popup window, search field variants, window positioning/animation utilities, text field with rounded corners
- Key files: `BezelWindow.m/h` (main display popup), `NSWindow+TrueCenter.m/h` (center calculation), `NSWindow+ULIZoomEffect.m/h` (zoom animation)
- Patterns: Category extensions for NSWindow behavior, custom NSWindow subclasses

**SGHotKeysLib:**
- Purpose: Global keyboard hotkey registration and monitoring
- Contains: Low-level hotkey management via Carbon API, keycode translation, hotkey center singleton
- Key files: `SGHotKeyCenter.m/h` (singleton manager), `SGHotKey.m/h` (individual key), `SGKeyCombo.m/h` (key combination)
- Patterns: Singleton pattern, Carbon API wrapping, delegate callbacks on hotkey events

**ShortcutRecorder:**
- Purpose: UI framework for recording and displaying keyboard shortcuts
- Contains: Pre-built controls and utilities for shortcut capture
- Key files: `SRRecorderControl` (main control), `SRKeyCodeTransformer` (keycode to string conversion)
- Patterns: Reusable IB-compatible control, bindings-ready

**UKPrefsPanel:**
- Purpose: Extensible preferences window framework
- Contains: Base classes for preference pane management, tabbed interface handling
- Key files: Preference pane base classes, window management
- Patterns: Reusable framework for plugin-style preference panes

**FlycutHelper:**
- Purpose: Separate helper application running as launch agent for clipboard monitoring
- Contains: Lightweight app delegate managing pasteboard monitoring when main app is hidden/minimized
- Key files: `AppDelegate.m/h`, `main.m`
- Patterns: Standard Cocoa app template, runs in background via LaunchAgent

**English.lproj:**
- Purpose: UI localization and IB-designed interface definitions
- Contains: MainMenu.nib containing all menu structure, preferences window, search window definitions
- Key files: `MainMenu.nib` (primary UI definition)
- Patterns: Xcode IB-compatible NIB format, outlet connections to AppController

## Key File Locations

**Entry Points:**
- `main.m`: Standard macOS app entry point, calls NSApplicationMain
- `AppController.m/h`: Main application delegate implementing NSApplicationDelegate, FlycutStoreDelegate, FlycutOperatorDelegate, NSMenuDelegate

**Configuration:**
- `Info.plist`: App bundle metadata (name, version, bundle ID, executable)
- `Flycut.entitlements` / `FlycutDebug.entitlements`: App sandbox/entitlements (release vs debug)
- `Flycut_Prefix.pch`: Precompiled header with common includes (Cocoa, ApplicationServices)
- `Debug.xcconfig` / `Release.xcconfig`: Build settings for each configuration

**Core Logic:**
- `FlycutOperator.m/h`: High-level clipboard history API and store orchestration
- `FlycutEngine/FlycutStore.m/h`: In-memory clipping collection with persistence interface
- `FlycutEngine/FlycutClipping.m/h`: Single clipboard item data model
- `AppController.m/h`: UI orchestration, delegate implementations, preference handling (largest file at ~73KB)

**Testing:**
- No dedicated test directory; testing appears to be manual/integration only

**UI Components:**
- `UI/BezelWindow.m/h`: Main popup UI for displaying recent clippings
- `UI/NSWindow+TrueCenter.m/h`: Window centering utility
- `UI/NSWindow+ULIZoomEffect.m/h`: Zoom in/out animation effects
- `UI/RoundRecTextField.m/h`: Search field with rounded rectangle appearance
- `UI/RoundRecBezierPath.m/h`: Geometry utility for rounded corners

## Naming Conventions

**Files:**
- Objective-C implementation: `.m` (e.g., `AppController.m`)
- Objective-C headers: `.h` (e.g., `AppController.h`)
- Category methods: `NSWindow+FeatureName.m/h` (e.g., `NSWindow+TrueCenter.h`)
- Classes prefixed with project name: `Flycut*` (e.g., `FlycutOperator`, `FlycutStore`)
- External libraries unprefixed or with library name: `SG*` (SGHotKeysLib), `SR*` (ShortcutRecorder), `UK*` (UKPrefsPanel)

**Classes:**
- PascalCase with descriptive names: `AppController`, `FlycutOperator`, `FlycutStore`, `FlycutClipping`
- Delegate protocol names follow `ClassName` + `Delegate`: `FlycutStoreDelegate`, `FlycutOperatorDelegate`
- Window subclasses: `BezelWindow`, `SearchWindow`

**Methods:**
- camelCase with method name prefix for clarity: `addClipping:ofType:fromApp:...`, `hitMainHotKey:`, `pollPB:`
- Boolean methods: `favoritesStoreIsSelected`, `stackPositionIsInBounds`, `removeDuplicates`
- Action methods: `-(IBAction)toggleMainHotKey:(id)sender`
- Delegate callbacks: `-(void)insertClippingAtIndex:(int)index`

**Properties & Variables:**
- Instance variables: prefix with type hint where convention used (`jc` = Jumpcut era prefix for legacy compatibility)
- Boolean flags: `isBezelDisplayed`, `isSearchWindowDisplayed`, `modifiedSinceLastSaveStore`
- Preference keys: camelCase with compound words: `displayNum`, `bezelAlpha`, `saveForgottenClippings`
- Temporary variables: concise lowercase: `i`, `count`, `index`, `newRemember`

## Where to Add New Code

**New Clipboard History Feature:**
- Primary logic: `FlycutOperator.m/h` (e.g., new stack navigation method, new store type)
- Data model: `FlycutEngine/FlycutStore.m/h` or `FlycutClipping.m/h` if extending item metadata
- UI updates: `AppController.m` method to call operator and update UI
- Preferences: Add key to AppController init() default prefs and settingsSyncList array

**New UI Component:**
- Implementation: Create new file in `UI/` directory (e.g., `CustomControl.m/h`)
- Integration: Design in `English.lproj/MainMenu.nib` via Xcode IB
- Controller: Add IBOutlet in `AppController.h` and connect in IB
- Behavior: Implement in `AppController.m` delegate methods or action handlers

**New Hotkey Feature:**
- Hotkey registration: Add `SGHotKey` property and registration in `AppController.awakeFromNib`
- Handler method: Create `-(void)hitNewHotKey:(SGHotKey *)hotKey` in AppController
- Operator call: Call appropriate `FlycutOperator` method for logic execution
- UI feedback: Add bezel/menu/search updates via delegate pattern

**Shared Utilities:**
- General utilities: `FlycutEngine/` if data-related, otherwise top-level `.m/h` file
- String formatting: Category methods on NSString (not currently used, but add in `NSString+FlycutExtensions.m/h`)
- UI helpers: Category methods on NSWindow or custom control classes in `UI/` directory

## Special Directories

**build/**
- Purpose: Xcode build artifacts
- Generated: Yes (by Xcode build process)
- Committed: No (in .gitignore)

**Flycut.xcodeproj/**
- Purpose: Xcode project configuration and workspace settings
- Generated: No (hand-edited by Xcode)
- Committed: Yes (necessary for building)

**English.lproj/**
- Purpose: Localization bundle containing UI definitions
- Generated: Partially (MainMenu.nib edited in IB)
- Committed: Yes (required for app bundle)

**Resources/**
- Purpose: Static assets (icons, images, documentation)
- Generated: No
- Committed: Yes

**FlycutHelper/**
- Purpose: Separate Xcode project for helper application
- Generated: No
- Committed: Yes (target built and bundled with main app)

**MJCloudKitUserDefaultsSync/**
- Purpose: Infrastructure for future iCloud sync feature
- Generated: No
- Committed: Yes (though feature currently disabled)

---

*Structure analysis: 2026-03-05*
