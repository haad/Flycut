# Paste key regression tests

Run on macOS with Command Line Tools:

```sh
python3 Tests/KeyboardLayoutPasteRegressionTests.py
```

Set `FLYCUT_TEST_ARTIFACTS` to an output directory to retain the native executable,
extracted methods, build log, and per-case logs. A missing installed fixture is a
failure, not a silent skip. The suite requires US, Dvorak, Dvorak-QWERTY-Cmd, and
Russian layout data.

## Resolution contract

`FlycutPasteKeyCode()` is a header-only helper returning an autoreleased NSNumber
(or nil), suitable for this manual-reference-counted target. Import
`FlycutPasteKey.h` and resolve immediately before submitting the synthetic Paste:

```objc
[self fakeKey:FlycutPasteKeyCode() withCommandFlag:TRUE];
```

It reads `TISCopyCurrentKeyboardLayoutInputSource()` for each Paste, translates
virtual keys with the **Command** modifier and the current `LMGetKbdType()`, and
accepts exactly one `v` or `V` with no dead-key state. An unmodified-text lookup
would break Dvorak-QWERTY-Cmd; a hardcoded ANSI-V breaks ordinary Dvorak.

Only when the source or its Unicode layout property is absent does it try
`TISCopyCurrentASCIICapableKeyboardLayoutInputSource()`. This is a bounded fallback,
not a claim that every input method or legacy layout shares its command mapping.
A present but truncated layout, failed translation, or layout with no matching
Command-V returns nil instead of overriding a known map with an unrelated one.
An unresolved fallback also returns nil. The existing `fakeKey:` nil guard must
remain: converting nil with `intValue` would silently produce keycode zero.
Both synthetic events must be allocated before either is flagged or posted;
partial allocations are released and no keystroke is posted.

## What the fixture proves (and does not)

The native fixture compiles the exact `fakeKey:` and `fakeCommandV` method text
from `AppController.m`, plus the real resolver header. It does not instantiate
AppController, initialize the application, or run its other methods.

- Real `TISCreateInputSourceList`, `TISGetInputSourceProperty`, and `UCKeyTranslate`
  read installed layout data; no input source is enabled or selected.
- Current-source retrieval and hardware type are injected, so all four layouts
  can be tested without changing the user's active layout. Their native tests
  use keyboard type 40; a fake test checks forwarding a different hardware type.
- Event source/event creation, flags, posts, and releases are intercepted using
  opaque test objects. The fixture never creates or posts a real CGEvent.
- The permission result is an explicitly injected test double, not a measured
  TCC result. UI dispatch is blocked; Settings calls fail the test.
- Translation errors, no-match/multicharacter/dead-key outputs, truncated data,
  missing sources, and allocation failures are fault injections, not claims
  about observed OS error returns.
- A symbol audit rejects links to the real input-posting, input-selection,
  current-layout retrieval, and permission functions in the fixture executable.

This is native layout/method coverage, not an end-to-end editor paste test.
The clipboard, privacy grants, active layout, and user input remain untouched.

## Apple SDK contracts

The authoritative declarations/comments are shipped in the macOS SDK:

- `Carbon.framework/Frameworks/HIToolbox.framework/Headers/TextInputSources.h`:
  `kTISPropertyUnicodeKeyLayoutData` can be NULL for non-layout or KCHR-only sources;
  the current-layout accessor returns the layout underlying an input method;
  the ASCII-layout accessor returns the most recently used/default ASCII layout.
- `CoreServices.framework/Frameworks/CarbonCore.framework/Headers/UnicodeUtilities.h`:
  `UCKeyTranslate` documents modifier state as `(modifiers >> 8) & 0xFF`, ADB keycodes
  0–127, `LMGetKbdType`, zero-initialized dead-key state, and output/status rules.
  Current SDKs discourage this API for processing existing NSEvents in favor of
  `charactersByApplyingModifiers:`. This resolver instead searches installed
  layout data for a synthetic shortcut without constructing a real input event.
- `CoreGraphics.framework/Headers/CGEvent.h` declares the return from
  `CGEventCreateKeyboardEvent` nullable.

A Command Line Tools syntax/link check cannot validate nib compilation, signing,
packaging, or a running app. Do not describe such a check as an Xcode app build.
