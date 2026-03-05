# Testing Patterns

**Analysis Date:** 2026-03-05

## Current State

**No automated tests found** - This project does not use XCTest, OCMock, or any testing frameworks. Testing is manual only.

## Test Framework

**Runner:** Not configured
- No `XCTest` framework integration
- No test target in Xcode project
- No test bundles or test schemes

**Testing approach:** Manual testing only
- Changes tested by running the compiled application
- User interaction testing through the macOS menu bar icon
- No unit tests, integration tests, or UI tests

## Build Configuration for Testability

**Current settings in `Debug.xcconfig`:**
```
ENABLE_TESTABILITY = YES
```

While testability is enabled in the build settings, no actual test code exists. This setting allows test code to access internal/private methods if tests were added.

## What Would Need Testing

Based on code analysis, the following areas would benefit from test coverage:

### Core Logic (High Priority)

**FlycutStore (`FlycutStore.h`, `FlycutStore.m`):**
- Add/insert/delete clipping operations
- Memory limit enforcement (rememberNum)
- Display string generation and truncation
- Search filtering with case-insensitive matching
- Clipping duplicate detection and removal
- Index-based movement operations

**FlycutOperator (`FlycutOperator.h`, `FlycutOperator.m`):**
- Stack position management (up, down, first, last)
- Store switching (primary vs. favorites)
- Clipping persistence to disk
- Password field detection
- Pasteboard type filtering

**FlycutClipping (`FlycutClipping.h`, `FlycutClipping.m`):**
- Content truncation for display
- Type preservation
- Timestamp handling
- App metadata association

### UI Logic (Medium Priority)

**AppController (`AppController.h`, `AppController.m`):**
- Hotkey detection and triggering
- Menu generation from clipping list
- Search field input handling
- Bezel display updates
- Keyboard navigation (arrow keys, numeric input)
- Paste simulation (fakeCommandV)

**BezelWindow:**
- Window layout and positioning
- Text display formatting
- Source app metadata display
- Mouse and keyboard event handling

### System Integration (Low Priority)

- Accessibility permission checking
- Clipboard polling
- Pasteboard change detection
- Login item registration
- App launch behavior

## Suggested Test Structure

If tests were to be added, the recommended structure would be:

```
Flycut/
├── Flycut.xcodeproj/
├── FlycutTests/                    # New test target
│   ├── FlycutTests.swift           # Or .m for Objective-C tests
│   ├── FlycutStoreTests.swift      # Store logic
│   ├── FlycutOperatorTests.swift   # Operator logic
│   ├── FlycutClippingTests.swift   # Clipping logic
│   ├── Fixtures/                   # Test data
│   │   ├── SampleClippings.h
│   │   └── MockPasteboard.h
│   └── Mocks/
│       ├── MockFlycutStoreDelegate.h
│       └── MockBezelWindowDelegate.h
├── [source files]
└── [existing test infrastructure]
```

## Manual Testing Patterns Currently Used

**Accessibility testing:**
- Manual verification via System Preferences
- Logs diagnostic info on startup: `NSLog(@"[Flycut Startup] Bundle ID: %@", bundleID);`
- Runtime permission checks without system prompts in tests

**Pasteboard testing:**
- Manual clipboard operations (copy, paste)
- Verbose logging when paste fails
- Test via menu interaction and bezel display

**Hotkey testing:**
- Manual hotkey presses to verify triggers
- No synthetic event generation in tests

## Testing Recommendations

### For New Code

1. **Add unit tests for data models:**
   - Create `FlycutStoreTests` for array manipulation logic
   - Create `FlycutClippingTests` for display string generation
   - Test boundary conditions (empty lists, max items, etc.)

2. **Use mocks for delegates:**
   - Mock `FlycutStoreDelegate` to verify UI updates triggered correctly
   - Mock `BezelWindowDelegate` to test keyboard event handling without UI

3. **Test error paths:**
   - Accessibility permission denied scenarios
   - Pasteboard unavailable scenarios
   - Disk I/O failures for persistence

4. **Add integration tests for core workflows:**
   - Add clipping → verify in list → paste workflow
   - Search → filter → select workflow
   - Hotkey → show bezel → navigate → paste workflow

### Test Infrastructure Needed

If adopting tests, consider:

1. **Modernize to Swift/XCTest:**
   - Better syntax than Objective-C XCTest
   - Easier mocking with Swift protocols
   - Async/await for complex UI testing

2. **Add test utilities:**
   ```objc
   // Proposed helper category for testing
   @interface FlycutStore (Testing)
   - (void)resetForTesting;
   - (NSArray *)allClippingsForTesting;
   @end
   ```

3. **Use OCMock or similar for complex mocks:**
   - Mock NSPasteboard without system pasteboard access
   - Mock NSRunLoop for timer-based testing
   - Mock Accessibility APIs without real permissions

### CI/CD Considerations

Currently no continuous integration. If added:

1. Test runner would need to:
   - Run XCTest schemes
   - Handle sandboxing/entitlements for Accessibility tests
   - Mock system APIs that require user permission

2. Test data:
   - Use temporary directories, not actual user defaults
   - Isolation between test runs
   - No dependency on system state (pasteboard, running apps)

## Code Areas Resistant to Testing

**Hard to test without refactoring:**

1. **AppController methods with UI side effects:**
   - `showBezel`, `hideBezel` directly manipulate window state
   - Would need BezelWindow dependency injection to mock
   - Currently tightly coupled to NSWindow

2. **Pasteboard polling (`pollPB:`):**
   - Uses NSPasteboard singleton
   - Timer-based dispatch to background queues
   - Would need abstraction layer for mock pasteboard

3. **File persistence:**
   - `loadEngineFromPList`, `saveEngine` use file paths directly
   - Would need temporary directory support or abstraction

4. **System hotkey registration:**
   - Uses SGHotKey framework
   - Requires Accessibility permissions
   - Cannot be tested in isolation

## Diagnostic Logging Available for Testing

The codebase includes extensive logging that aids manual testing:

- Accessibility permission state logged on startup and when checking
- Bundle path/ID logged for debugging permission issues
- Stack position changes logged: `NSLog(@"stackDown: moved to position=%d", [flycutOperator stackPosition]);`
- Paste operation logged: `NSLog(@"pasteFromStack called");`
- Search results logged: `DLog(@"list=%@, oldItems=%d, newItems=%d", ...);`

This logging can serve as a temporary test verification mechanism until automated tests are added.

---

*Testing analysis: 2026-03-05*
