# Codebase Concerns

**Analysis Date:** 2026-03-05

## Tech Debt

**Memory Leaks - Unreleased FlycutStore Instances:**
- Issue: FlycutStore allocations are never explicitly deallocated in the application lifecycle
- Files: `FlycutOperator.m` (lines 100-124)
- Impact: Two store objects (clippingStore and favoritesStore) remain allocated throughout app lifetime; if the app is long-running or reloaded, this could accumulate memory
- Fix approach: Add explicit deallocation in `-applicationWillTerminate` method in `FlycutOperator.m`, or migrate to modern ARC memory management

**Manual Reference Counting in Modern codebase:**
- Issue: Codebase uses manual retain/release/autorelease patterns mixed with modern memory management
- Files: `AppController.m`, `FlycutOperator.m`, `UKPrefsPanel/UKPrefsPanel.m`, multiple usage sites (123 occurrences across 20 files)
- Impact: Difficult to maintain, prone to memory leaks, inconsistent with modern Objective-C best practices
- Fix approach: Migrate to Automatic Reference Counting (ARC) by enabling it in build settings and refactoring memory management calls

**Hardcoded Timing Values:**
- Issue: Multiple performSelector calls use arbitrary delay values (0.2s, 0.3s, 0.5s) without explanation
- Files: `AppController.m` (lines 1866, 1805+), multiple instances
- Impact: Race conditions possible if system is slow; delays may be insufficient on older hardware or under high load
- Fix approach: Document why each delay is needed, consider replacing with NSEvent-based triggers or completion handlers; use GCD for more reliable sequencing

**Unstructured String Constants for Preferences:**
- Issue: NSUserDefaults keys scattered throughout codebase as string literals (e.g., @"rememberNum", @"displayNum", @"skipPasswordFields")
- Files: `AppController.m` (lines 61-96), `FlycutOperator.m` (lines 29-58)
- Impact: Typos go undetected at compile time; refactoring preference names breaks the app silently
- Fix approach: Create a centralized preferences constants file (e.g., `PreferencesKeys.h`) with static NSString constants

## Known Bugs

**Accessibility Permission State Not Properly Cached:**
- Symptoms: App may show "accessibility denied" errors intermittently even after permission granted; users report needing to remove/re-add the app
- Files: `AppController.m` (lines 165-217), `FlycutOperator.m` (paste logic)
- Trigger: (1) Moving app after permission grant, (2) macOS permissions cache out of sync, (3) Both main app AND helper need permissions (for sandboxed builds)
- Workaround: Recheck button added in preferences; users can remove from Accessibility list and re-add; restart app

**performSelector Timing Fragility:**
- Symptoms: Paste operations occasionally fail to execute; bezel shows correct content but paste doesn't happen
- Files: `AppController.m` (multiple locations with performSelector:withObject:afterDelay)
- Trigger: System under high load, event queue backed up, or app in background
- Workaround: Increased delay values in recent commits; not a permanent fix

**Search Window May Not Release Search Results Properly:**
- Symptoms: Long-running app with heavy search usage may accumulate memory
- Files: `AppController.m` (lines 1820-1830)
- Trigger: Repeated searches without closing search window
- Fix approach: Verify searchResults array is properly released on window close; consider weak reference pattern

## Security Considerations

**Plaintext Clipboard Data Persistence:**
- Risk: Clipboard history is saved to NSUserDefaults in plaintext dictionary format
- Files: `FlycutOperator.m` (saveEngine method, line 1099), `Info.plist`
- Current mitigation: Option to skip password-like content based on type and length heuristics (`skipPasswordFields`, `skipPasswordLengthsList`)
- Recommendations:
  - Consider encrypting persisted clipboard data at rest
  - Document that app logs are NOT secure (contain clipboard content in debug builds)
  - Add option to auto-clear history on app quit
  - Warn users about security implications in Help

**Accessibility Permission Required for Core Functionality:**
- Risk: App cannot function without Accessibility permission on modern macOS; permission can be revoked at any time by OS or user
- Files: `AppController.m` (fakeCommandV implementation, paste operations), `FlycutOperator.m`
- Current mitigation: Startup alert asks user to grant permission; recheck action available
- Recommendations:
  - Add graceful fallback to copy-to-clipboard only mode if Accessibility unavailable
  - Document that permission is required for pasting to work
  - Regularly validate permission state and warn if it's been revoked

**Login Item (Helper) Security:**
- Risk: Sandboxed builds rely on helper app with login item; both main and helper need Accessibility permission to function
- Files: `Flycut.xcodeproj/project.pbxproj` (build config), `FlycutHelper/` directory
- Current mitigation: Logging added to identify when helper is running
- Recommendations:
  - Document why helper is necessary (app sandbox constraints)
  - Clarify in UI that both main app and helper need permissions
  - Consider if helper functionality can be moved to main app

## Performance Bottlenecks

**Linear Search in Clipboard History:**
- Problem: Search functionality scans all clippings linearly for matches
- Files: `FlycutOperator.m` (previousDisplayStrings, previousIndexes methods)
- Cause: Simple array enumeration without indexing; no caching of search results
- Improvement path: For large history (1000+ items), implement string search indexing or filtering before enumeration; cache recent searches

**NSUserDefaults Synchronize in Save Path:**
- Problem: FlycutOperator explicitly calls `synchronize` after saving store dictionary
- Files: `FlycutOperator.m` (line 1100)
- Cause: Old API; modern NSUserDefaults handles persistence automatically; explicit sync may block main thread
- Improvement path: Remove explicit synchronize call; verify modern NSUserDefaults behavior in target OS versions

**Bezel Rendering with Dispatch Queue:**
- Problem: Menu and bezel updates use serial dispatch queue which could serialize work
- Files: `AppController.m` (line 123, menuQueue creation)
- Cause: Queue may accumulate pending updates if rendering is slow
- Improvement path: Profile render time; consider CADisplayLink for synchronized rendering; use main thread for UI-critical paths

## Fragile Areas

**BezelWindow Custom Drawing:**
- Files: `UI/BezelWindow.m` (470 lines), `UI/NSWindow+ULIZoomEffect.m` (361 lines)
- Why fragile: Custom window rendering bypasses standard NSWindow behavior; deprecated animation methods used; heavily dependent on macOS version-specific behavior
- Safe modification:
  - Make changes to visual styling only (colors, fonts)
  - Do not modify animation timing without thorough testing
  - Test on multiple macOS versions (Big Sur through current)
- Test coverage: No automated tests visible; manual testing required

**ShortcutRecorder Integration:**
- Files: `ShortcutRecorder/` directory (multiple complex classes)
- Why fragile: Third-party hotkey capture code; keyboard event handling is OS-specific; state machine for recording vs. displaying
- Safe modification:
  - Avoid changing recorder state machine logic
  - Do not modify key code translation tables
  - Test all keyboard layouts if modifying key translation
- Test coverage: No tests for keyboard input; depends on system-level hotkey delivery

**Manual Preferences UI Binding:**
- Files: `AppController.m` (preference panel setup and handlers)
- Why fragile: Manual NSUserDefaults binding without bindings framework; scattered setters/getters for each preference
- Safe modification:
  - Add new preferences by following exact pattern of existing ones
  - Test both setting in UI and loading from prefs on app restart
  - Verify setter/getter names match in XIB file
- Test coverage: No automated preference tests; manual testing each pref change

**Accessibility Integration:**
- Files: `AppController.m` (multiple locations), `FlycutOperator.m` (paste logic)
- Why fragile: Accessibility API is Apple private/unstable; AXIsProcessTrustedWithOptions behavior varies by macOS version; paste simulation via CGEventPost unreliable
- Safe modification:
  - Do not change prompt/no-prompt logic without understanding side effects (focus stealing)
  - Do not change timing in accessibility checks
  - Always test paste functionality on new macOS releases
- Test coverage: No unit tests for accessibility; requires manual macOS testing

## Scaling Limits

**Clipboard History Size in Memory:**
- Current capacity: Default 40 clippings remembered in main store, 40 in favorites
- Limit: Each clipping stored in NSUserDefaults as dictionary; large clippings (>10MB) will degrade performance; storing 1000s of items causes NSUserDefaults to slow
- Scaling path: Implement on-disk SQLite backend for history when size exceeds threshold; compress old entries; move past items to archive database

**Pasteboard Polling Frequency:**
- Current capacity: Polls pasteboard every 0.5 seconds by default
- Limit: On systems with very high clipboard activity (rapid copy/paste), polling may miss events or lag; timer-based polling inherently lossy
- Scaling path: Consider pasteboard change notifications (NSPasteboard notifications) instead of polling; implement event coalescing

## Dependencies at Risk

**SGHotKeysLib (Custom Hotkey Framework):**
- Risk: Old, unmaintained third-party hotkey library; no Cocoa Services integration; may not work on Apple Silicon or future macOS versions
- Impact: App cannot respond to global hotkeys if library breaks; custom rebuilds needed for each macOS version
- Migration plan: Replace with modern frameworks (Sparkle, or custom CGEvent monitoring); or integrate with macOS Services/Events framework

**ShortcutRecorder (Custom Keyboard Recorder):**
- Risk: Complex third-party keyboard capture code; many deprecated APIs; inline key code translation tables require updates for new keyboards
- Impact: Keyboard shortcut recording may break with new keyboard layouts or macOS versions
- Migration plan: Use native macOS keyboard event handling; consider NSEvent monitoring framework; or switch to Recorder library if maintained

**UKPrefsPanel (Custom Preferences UI):**
- Risk: Old Cocoa framework; uses autorelease, manual toolbar setup; duplicated in codebase
- Impact: Preferences UI may not look or feel modern; accessibility issues possible
- Migration plan: Migrate to modern NSViewController-based preferences; use Xcode Interface Builder instead of manual code; or AppKit Preferences framework

## Missing Critical Features

**No Persistent Encryption for Stored Clipboard Data:**
- Problem: All clipboard history stored in plaintext in NSUserDefaults
- Blocks: Cannot safely use on shared/public computers; data vulnerable if device stolen; violates privacy best practices
- Priority: HIGH - blocks enterprise/sensitive use cases

**No Import/Export of Clipping History:**
- Problem: No way to backup or migrate clipboard history between computers
- Blocks: Switching computers loses all history; no disaster recovery
- Priority: MEDIUM - useful for power users, not critical to core function

**No Undo/Redo for Pastes:**
- Problem: If user pastes wrong item and it overwrites clipboard, no way to recover previous paste
- Blocks: Data loss scenarios possible
- Priority: LOW - edge case, workaround is using back/forward hotkeys

## Test Coverage Gaps

**Accessibility Permission Flow:**
- What's not tested: Permission checking, prompt behavior, failure recovery
- Files: `AppController.m` (showAccessibilityAlert, requestAccessibilityWithPrompt, fakeCommandV)
- Risk: Accessibility failures undetected until user reports; different behavior on different macOS versions
- Priority: HIGH - core functionality dependent on this

**Clipboard Change Detection and Deduplication:**
- What's not tested: Pasteboard polling, duplicate detection, store insertion logic
- Files: `AppController.m` (pollPB), `FlycutOperator.m` (addClipping, duplicate detection)
- Risk: Silent data loss if duplicate detection fails; race conditions in polling
- Priority: HIGH - affects core functionality

**Preferences Persistence and Sync:**
- What's not tested: NSUserDefaults save/load, iCloud sync (if enabled), preference validation
- Files: `AppController.m` (entire preferences section), `FlycutOperator.m` (settingsSyncList)
- Risk: Preference loss on crash; invalid preferences not caught
- Priority: MEDIUM - affects user experience

**Search Functionality:**
- What's not tested: Search filtering, case sensitivity, special characters, performance with large histories
- Files: `AppController.m` (updateSearchResults, search window methods), `FlycutOperator.m` (previousDisplayStrings)
- Risk: Search failures silent; poor performance on large histories
- Priority: MEDIUM - relatively new feature, not well covered

**Memory Lifecycle in Long-Running Sessions:**
- What's not tested: App behavior after hours of use; memory growth over time; reference cycle detection
- Files: All files with allocations
- Risk: Memory leaks manifest only in long-running sessions; crashes on user machines but not in testing
- Priority: MEDIUM - QA challenge but important for reliability

---

*Concerns audit: 2026-03-05*
