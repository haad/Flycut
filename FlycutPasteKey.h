#ifndef FlycutPasteKey_h
#define FlycutPasteKey_h

#import <Foundation/Foundation.h>
#import <Carbon/Carbon.h>

// Resolve the shortcut, not unmodified text: Dvorak and Dvorak-QWERTY-Cmd
// intentionally use different keys for Command-V. Do not cache layout state.
static inline NSNumber *FlycutPasteKeyCode(void)
{
    TISInputSourceRef source = TISCopyCurrentKeyboardLayoutInputSource();
    CFDataRef data = source ? (CFDataRef)TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) : NULL;
    if (!data) {
        // Input methods/legacy layouts can lack Unicode data. Use the system's
        // ASCII-capable layout only in that case, never to override a known map.
        if (source) CFRelease(source);
        source = TISCopyCurrentASCIICapableKeyboardLayoutInputSource();
        data = source ? (CFDataRef)TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) : NULL;
    }
    NSNumber *keyCode = nil;
    if (data && CFDataGetLength(data) >= (CFIndex)sizeof(UCKeyboardLayout)) {
        const UCKeyboardLayout *layout = (const UCKeyboardLayout *)CFDataGetBytePtr(data);
        UInt32 keyboardType = LMGetKbdType();
        for (UInt16 code = 0; code < 128; code++) {
            UInt32 deadKeyState = 0;
            UniChar characters[4];
            UniCharCount length = 0;
            OSStatus status = UCKeyTranslate(layout, code, kUCKeyActionDown,
                (cmdKey >> 8) & 0xff, keyboardType, kUCKeyTranslateNoDeadKeysMask,
                &deadKeyState, 4, &length, characters);
            if (status == noErr && deadKeyState == 0 && length == 1 &&
                (characters[0] == 'v' || characters[0] == 'V')) {
                keyCode = @(code);
                break;
            }
        }
    }
    if (source) CFRelease(source);
    // Never guess keycode zero (Command-A) or ANSI-V for an unknown layout.
    return keyCode;
}

#endif
