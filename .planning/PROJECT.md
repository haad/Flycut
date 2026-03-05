# Flycut Swift

## What This Is

A modern macOS clipboard manager rewritten from scratch in Swift/SwiftUI. Flycut Swift replaces the legacy Objective-C codebase while preserving the core experience — clipboard history with a keyboard-driven bezel UI living in the menu bar — and adding new capabilities like a code snippet editor and GitHub Gist sharing.

## Core Value

Instant keyboard-driven access to clipboard history. Press a hotkey, navigate clippings, paste — without touching the mouse.

## Requirements

### Validated

<!-- Capabilities proven in the existing Objective-C Flycut that must survive the rewrite. -->

- ✓ Clipboard monitoring via pasteboard polling — existing
- ✓ Clipboard history with configurable max size — existing
- ✓ Bezel-style floating HUD for clipping selection — existing
- ✓ Global hotkey for activating bezel — existing
- ✓ Keyboard navigation through clipping history — existing
- ✓ Paste injection via synthesized Cmd-V — existing
- ✓ Menu bar app with no dock icon — existing
- ✓ Search/filter clippings — existing
- ✓ Duplicate removal — existing
- ✓ Pasteboard type filtering (exclude passwords, transient types) — existing
- ✓ Configurable preferences (history size, display length, hotkeys) — existing
- ✓ Launch at login — existing
- ✓ Favorites store for pinned clippings — existing

### Active

<!-- New capabilities for the Swift rewrite. -->

- [ ] Full SwiftUI-based UI with modern macOS design
- [ ] SwiftData persistence for clipboard history and snippets
- [ ] Code snippet editor with syntax highlighting and categories
- [ ] GitHub Gist sharing — create gists from clipboard entries
- [ ] Modern launch-at-login using ServiceManagement API
- [ ] Menu bar integration using SwiftUI MenuBarExtra
- [ ] Accessibility-first design for paste injection

### Out of Scope

- Sparkle update framework — direct download with notarized DMG, no in-app updater needed
- Sticky bezel positioning — unnecessary complexity
- iCloud sync — infrastructure existed in old app but was disabled; defer to future
- iOS/iPadOS version — macOS only
- Mac App Store distribution — direct download only
- Old-style login item management — use modern ServiceManagement
- Pastebin/generic paste services — GitHub Gist only for sharing

## Context

Flycut is an open-source macOS clipboard manager originally forked from Jumpcut. The current codebase is Objective-C with Carbon-era hotkey handling, AppKit UI, and NSUserDefaults-based persistence. The app works but the codebase shows its age — polling-based clipboard monitoring, manual memory patterns, third-party frameworks for basic functionality (Sparkle, SGHotKeysLib, ShortcutRecorder, UKPrefsPanel).

The rewrite targets macOS 15+ (Sequoia), enabling full use of modern Apple APIs: SwiftUI for UI, SwiftData for persistence, and native keyboard shortcut APIs. The existing bezel UI concept is retained but rebuilt in SwiftUI.

Key patterns from the existing app worth preserving:
- Three-tier architecture: UI → Operator/Logic → Store/Data
- Delegate pattern for store-to-UI updates (translates to SwiftUI observation)
- Stack position tracking for keyboard navigation
- Pasteboard type filtering to avoid capturing passwords and transient data

## Constraints

- **Platform**: macOS 15+ (Sequoia) — required for SwiftData and latest SwiftUI features
- **Language**: Swift 6 with strict concurrency
- **UI**: SwiftUI — no AppKit unless absolutely necessary for system integration
- **Persistence**: SwiftData — replaces NSUserDefaults-based clipping storage
- **Distribution**: Direct download, notarized DMG — no App Store
- **Accessibility**: Requires Accessibility permission for paste injection (CGEvent-based key simulation)
- **Privacy**: No analytics, no telemetry, no network calls except explicit GitHub Gist sharing

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full rewrite over incremental migration | Clean break enables modern patterns, no Obj-C/Swift bridging complexity | — Pending |
| SwiftUI over AppKit | Declarative UI, less boilerplate, native menu bar support via MenuBarExtra | — Pending |
| SwiftData over Core Data/SQLite | Modern persistence, seamless SwiftUI integration, macro-based models | — Pending |
| macOS 15+ minimum | Enables latest SwiftData/SwiftUI features, simplifies API surface | — Pending |
| GitHub Gist for sharing | Familiar developer workflow, well-documented API, avoids building/hosting a service | — Pending |
| Drop Sparkle updates | Direct download with notarization; users re-download for updates or use brew cask | — Pending |

---
*Last updated: 2026-03-05 after initialization*
