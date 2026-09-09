# Paste transaction regression fixtures

Run on macOS with the command-line developer tools:

```sh
/usr/bin/env -u TMPDIR python3 -B -m unittest discover -s Tests -p '*Tests.py' -v
```

These fixtures compile the actual controller, engine and supporting Objective-C
sources. They do not build/install an application bundle or load a NIB. Defaults
are redirected to an in-memory object and `NSApp` calls are disabled. Tests never
use the general clipboard, post global input, request real Accessibility consent,
open Settings or terminate another application.

## Evidence boundaries

- **Trigger:** production hotkey/modifier release, Escape, menu/search selection,
  and transaction callbacks run in native fixture processes.
- **Boundary:** a displayed row can outlive an insertion or deletion; an invocation
  can outlive focus, clipboard-generation or activation changes.
- **Transport:** the real controller methods run. The target tests inject the
  clipboard and final posting boundaries; the ownership tests run real placement,
  snapshot and restore methods against an in-memory generation-counted board.
  The event sink compiles the real posting method with trust/post functions
  redirected, and inspects all four event-construction/routing calls with inert event objects.
- **Observable:** exact selected identity/payload, activation and post counts,
  original PID, clipboard contents/generation and rollback representations.
- **Isolation:** stale callbacks cannot post for or clear a newer invocation;
  external copies are not overwritten when their changed generation is observed.

`FC_PASTE_TEST_BUILD_ROOT` optionally preserves generated fixture sources,
binaries and complete compiler output for hash-bound review. Without it, temporary
build directories are removed at process exit.

These are source-level integration tests, not live desktop input/TCC or packaged
application acceptance. The pasteboard has no atomic cross-process compare-and-
swap, and posting an event does not acknowledge that the target consumed it.
The unchanged resolver from the keyboard-layout fix is consumed immediately at
the targeted-post boundary. These tests inject translation results (including no
mapping) and verify nil fails before allocation, and both key events use the
resolved code. Native installed-layout mapping is covered by that separate fix.
