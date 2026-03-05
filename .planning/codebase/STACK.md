# Technology Stack

**Analysis Date:** 2026-03-05

## Languages

**Primary:**
- Objective-C - Core application logic, UI controllers, and data management
- Objective-C++ - Limited use for C++ interoperability

**Secondary:**
- C - Legacy components and low-level system interactions

## Runtime

**Environment:**
- macOS 12.3+ (MACOSX_DEPLOYMENT_TARGET = 12.3)
- Xcode 26.3+ (per recent build configuration updates)

**Build System:**
- Xcode project (`Flycut.xcodeproj`)
- Build configurations: Debug and Release with .xcconfig files

## Frameworks

**Core Cocoa:**
- Cocoa.framework - Main macOS application framework
- AppKit.framework - Window and UI management
- Foundation.framework - Basic data structures and utilities

**System Integration:**
- ApplicationServices.framework - Clipboard and pasteboard access
- Carbon.framework - Legacy system events (keyboard capture)
- ServiceManagement.framework - Login item management
- CoreFoundation.framework - Low-level system services

**Data & Preferences:**
- NSUserDefaults - Settings persistence (standard defaults system)
- Foundation collections - Dictionary, Array storage

## Key Dependencies

**Critical:**
- SGHotKeysLib (`/Volumes/Devel/apple/Flycut/SGHotKeysLib/`) - Global hotkey registration and management
  - Components: SGHotKey, SGHotKeyCenter, SGKeyCombo, SGKeyCodeTranslator
  - Purpose: Enables system-wide hotkey capture for clipboard history access

- ShortcutRecorder (`/Volumes/Devel/apple/Flycut/ShortcutRecorder/`) - Keyboard shortcut UI recording
  - Components: SRRecorderControl, SRValidator, SRKeyCodeTransformer
  - Purpose: Provides hotkey input UI in preferences panel

- UKPrefsPanel (`/Volumes/Devel/apple/Flycut/UKPrefsPanel/`) - Preferences panel management
  - Purpose: Tabbed preferences window framework

**UI/UX:**
- BezelWindow - Custom window class for clipboard display bezel
- RoundRecBezierPath, RoundRecTextField - Custom UI components
- NSWindow+TrueCenter, NSWindow+ULIZoomEffect - Window animation extensions

**Storage Engine:**
- FlycutStore (`/Volumes/Devel/apple/Flycut/FlycutEngine/FlycutStore.h`) - In-memory clipboard history storage
- FlycutClipping - Clipboard item data model
- FlycutOperator - Storage manipulation logic

## Configuration

**Environment:**
- Build configurations in `.xcconfig` files:
  - `Debug.xcconfig` - Development settings (no optimization, debug symbols enabled)
  - `Release.xcconfig` - Production settings (optimization level -s, symbol stripping enabled)
  - Common settings referenced from "Common.xcconfig"

**Build Settings:**
- GCC_PRECOMPILE_PREFIX_HEADER enabled with `Flycut_Prefix.pch`
- Deployment postprocessing enabled in Release builds
- Code signing with manual identity

**Version Management:**
- Current Version: 2.0.0
- Marketing Version: 2.0.0.latest
- Version scheme: Apple generic

## Platform Requirements

**Development:**
- Xcode 26.3 or later
- macOS SDK 12.3+
- C/Objective-C compiler support

**Runtime/Production:**
- macOS 12.3 or later
- Accessibility permissions (for AppleEvents and paste injection)
- Login item privileges (for startup launch via ServiceManagement)
- No external runtime dependencies or package managers

## Storage & Persistence

**Local Storage:**
- NSUserDefaults system preferences database
- Plist format for application settings
- In-memory arrays for clipboard history (not persisted by default)

**Memory-Based:**
- NSMutableArray for active clipboard history stack
- NSMutableDictionary for clipping storage
- Insertion/deletion journals for tracking changes

## Compilation & Linking

**Frameworks Path:**
- Framework search includes `$(SRCROOT)` for embedded frameworks

**Linker Settings:**
- Runpath search paths: `@executable_path/../Frameworks` (for embedded frameworks)

**Code Generation:**
- Dynamic linking (GCC_DYNAMIC_NO_PIC = NO in Debug)
- Objective-C weak references enabled (CLANG_ENABLE_OBJC_WEAK = YES)
- Automatic reference counting (ARC) preferred in newer code

---

*Stack analysis: 2026-03-05*
