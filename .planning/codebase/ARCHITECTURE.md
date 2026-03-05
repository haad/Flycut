# Architecture

**Analysis Date:** 2026-03-05

## Pattern Overview

**Overall:** Layered MVC-like architecture with clear separation between data persistence, business logic, and UI.

**Key Characteristics:**
- Three-tier design: UI layer (AppController) → Logic layer (FlycutOperator) → Data layer (FlycutStore/FlycutClipping)
- Delegate pattern used throughout for event notification
- Polling-based clipboard monitoring with event-driven UI updates
- Multiple independent stores for clippings, favorites, and stashed clippings
- Hotkey-driven application with global keyboard shortcuts

## Layers

**UI Layer (Presentation):**
- Purpose: Handles all user interface rendering, event capture, and user interaction
- Location: `AppController.m/h`, `UI/` directory (BezelWindow, RoundRecTextField, custom NSWindow categories)
- Contains: Main application controller, bezel window rendering, search window, menu management, preference panel, hotkey recorders
- Depends on: FlycutOperator, SGHotKeysLib, ShortcutRecorder, UKPrefsPanel
- Used by: NSApplication (entry point), IB/NIB files

**Business Logic Layer (Operator):**
- Purpose: Orchestrates clipboard history management and provides high-level operations on stores
- Location: `FlycutOperator.m/h`
- Contains: Store lifecycle management, stack position tracking, clipping addition/retrieval, favorites/stashed store switching, preference handling, persistence orchestration
- Depends on: FlycutStore, FlycutClipping, NSUserDefaults
- Used by: AppController for clipboard operations and state management

**Data Layer (Storage):**
- Purpose: Manages in-memory clipboard history with persistence to NSUserDefaults
- Location: `FlycutEngine/` directory (FlycutStore.m/h, FlycutClipping.m/h)
- Contains: Clipping array management, display configuration, insertion/deletion journals for sync, duplicate removal logic, delegate-based notifications
- Depends on: Foundation framework only
- Used by: FlycutOperator for read/write operations

**Support Layers:**
- **Hotkey Library:** `SGHotKeysLib/` - Global hotkey registration and event handling via Carbon/CoreFoundation
- **UI Components:** `UI/` - Custom window/text field controls, zoom effects, window centering
- **Preferences Panel:** `UKPrefsPanel/` - Extensible preferences UI framework
- **Shortcut Recording:** `ShortcutRecorder/` - Keyboard shortcut capture and display
- **Helper Application:** `FlycutHelper/` - Launch agent for persistent clipboard monitoring when main app is minimized

## Data Flow

**Clipboard Monitoring → Clipping Addition:**

1. `pollPB:` timer fires every 0.5 seconds (configurable) in `AppController`
2. Reads NSPasteboard and compares `pbCount` (change indicator)
3. If changed, calls `FlycutOperator.addClipping:ofType:fromApp:withAppBundleURL:target:clippingAddedSelector:` with pasteboard contents
4. FlycutOperator creates `FlycutClipping` object and calls `FlycutStore.addClipping:ofType:fromAppLocalizedName:fromAppBundleURL:atTimestamp:`
5. FlycutStore inserts at index 0, removes duplicates if enabled, enforces max size via `jcRememberNum`
6. Store calls delegate methods on AppController to update UI (bezel, menu, search results)
7. FlycutOperator calls `saveEngine` to persist to NSUserDefaults if save preference enabled
8. `pbBlockCount` prevents internal Flycut paste operations from triggering new clipping additions

**User Selection → Paste Operation:**

1. User presses hotkey (global keyboard shortcut via SGHotKeysLib) or selects from menu/bezel/search
2. AppController method invoked (e.g., `hitMainHotKey:`, `processMenuClippingSelection:`)
3. Calls FlycutOperator to get clipping at selected position via `getPasteFromIndex:` or `clippingAtStackPosition`
4. Passes clipping text to `addClipToPasteboard:` in AppController
5. AppController sets NSPasteboard with content and optionally calls `fakeCommandV` to synthesize Command-V keystroke
6. Optional movement of selection in stack based on navigation hotkeys (up/down/first/last/ten-up/ten-down)

**Favorites/Stashed Store Management:**

1. User switches to favorites store via hotkey or menu
2. FlycutOperator `switchToFavoritesStore` stashes current clipping store and activates favorites store
3. Same workflow applies but with `favoritesStore` instead of `clippingStore`
4. Separate stack positions maintained: `stackPosition` vs `favoritesStackPosition` vs `stashedStackPosition`
5. `restoreStashedStore` returns to previous store

**State Management:**

- **Stack Position:** Integer tracking current selection within active store (0 = most recent)
- **Store Modification:** `modifiedSinceLastSaveStore` flag prevents redundant persistence
- **Journals:** Insertion and deletion journals track changes for iCloud sync capability (currently disabled)
- **Preferences:** NSUserDefaults holds all user settings, synchronized via AppController init and preference setters

## Key Abstractions

**FlycutClipping:**
- Purpose: Encapsulates a single clipboard item with metadata
- Examples: `FlycutEngine/FlycutClipping.m/h`
- Pattern: Value object holding content (NSString), type, display string, source app info (localized name, bundle URL), timestamp, display length configuration
- Comparison: Implements equality via content, type, app info, and timestamp for duplicate detection

**FlycutStore:**
- Purpose: In-memory collection managing ordered list of clippings with bounds enforcement
- Examples: `FlycutEngine/FlycutStore.m/h`
- Pattern: Observable collection using delegate pattern for UI updates; tracks configuration (remember count, display count, display length); maintains insertion/deletion journals for sync
- Key Methods: `addClipping:`, `insertClipping:atIndex:`, `clippingAtPosition:`, `clearList:`, `removeDuplicates`

**FlycutOperator:**
- Purpose: Facade providing high-level clipboard history operations and store orchestration
- Examples: `FlycutOperator.m/h`
- Pattern: Single point of control for store lifecycle, stack navigation, favorites/stashing, preference integration, persistence
- Key Methods: `addClipping:ofType:fromApp:withAppBundleURL:target:clippingAddedSelector:`, `getPasteFromIndex:`, `setStackPositionTo:`, `switchToFavoritesStore:`, `saveEngine:`, `loadEngineFromPList:`

**AppController Delegates:**
- Purpose: Implement FlycutStoreDelegate and FlycutOperatorDelegate to respond to data layer events
- Pattern: Called by stores when clipping state changes (insert/delete/move/reload) to trigger UI updates; called by operator for user alerts
- Key Methods: `insertClippingAtIndex:`, `deleteClippingAtIndex:`, `moveClippingAtIndex:toIndex:`, `reloadClippingAtIndex:`, `beginUpdates:`/`endUpdates:` for batch animation

## Entry Points

**Application Startup:**
- Location: `main.m`
- Triggers: macOS app launch
- Responsibilities: Calls NSApplicationMain to begin Cocoa event loop

**Main Application Delegate:**
- Location: AppController (implements NSApplicationDelegate)
- Triggers: NSApplication lifecycle events (app did finish launching, will terminate, etc.)
- Responsibilities: Initialize FlycutOperator, register hotkeys, start pasteboard polling, load preferences, set up menus, restore window state

**Main Hotkey Handler:**
- Location: `AppController.hitMainHotKey:`
- Triggers: Global hotkey press (default: Cmd-Shift-V)
- Responsibilities: Show/hide bezel window, advance through recent clippings

**Search Hotkey Handler:**
- Location: `AppController.hitSearchHotKey:`
- Triggers: Global search hotkey press (default: Cmd-Shift-B)
- Responsibilities: Show search window, allow text filtering of clippings

## Error Handling

**Strategy:** Non-fatal error handling with user dialogs for critical operations like resizing remembered clipping count.

**Patterns:**
- Resize stack validation: Shows alert via `delegateAlertWithMessageText:informationText:buttonsTexts:` if downsizing would lose data
- Empty clipping validation: Methods check for zero-length strings before adding clippings
- Bounds checking: `adjustStackPositionIfOutOfBounds` ensures stack position stays valid after deletions
- Preferences fallback: Default values registered in NSUserDefaults init prevent nil/invalid states
- Hotkey registration: Silently skips registration if conflicting; FlycutHelper monitors if main app fails

## Cross-Cutting Concerns

**Logging:** Console logging via NSLog for debug operations (hotkey events, paste operations, state changes)

**Validation:**
- Empty string checks before clipping creation
- Stack position bounds validation before operations
- Remember count validation (minimum 1)
- Pasteboard type filtering to exclude passwords, transient types, auto-generated types, OnePassword types

**Preference Synchronization:** AppController syncs user preferences between NSUserDefaults and UI controls; settings list supports iCloud sync via MJCloudKitUserDefaultsSync (currently disabled)

**Persistence:** Two-level strategy:
1. Real-time persistence to NSUserDefaults for clippings if "save preference" enabled
2. Optional iCloud sync via CloudKit (infrastructure in place but feature disabled)

---

*Architecture analysis: 2026-03-05*
