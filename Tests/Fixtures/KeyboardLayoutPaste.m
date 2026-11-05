// Native layout translation and the actual AppController paste methods.
// All event creation/posting and permission checks below are test doubles.
#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>
#import <ApplicationServices/ApplicationServices.h>

static int failures;
#define CHECK(condition, message) do { if (!(condition)) { \
    fprintf(stderr, "FAIL: %s\n", message); failures++; } } while (0)

static TISInputSourceRef activeLayout, asciiLayout;
static int activeCopies, asciiCopies, sourceReleases;
static TISInputSourceRef CopyActiveLayout(void) {
    activeCopies++;
    return activeLayout ? (TISInputSourceRef)CFRetain(activeLayout) : NULL;
}
static TISInputSourceRef CopyASCIILayout(void) {
    asciiCopies++;
    return asciiLayout ? (TISInputSourceRef)CFRetain(asciiLayout) : NULL;
}
static UInt8 fixtureKeyboardType = 40;
static UInt8 KeyboardType(void) { return fixtureKeyboardType; }
static void *FixtureProperty(TISInputSourceRef source, CFStringRef property) {
    // Dictionaries model unavailable data; installed sources use the real API.
    if (CFGetTypeID(source) == CFDictionaryGetTypeID())
        return (void *)CFDictionaryGetValue((CFDictionaryRef)source, property);
    return TISGetInputSourceProperty(source, property);
}
typedef enum { Native, LowerV, UpperV, NoV, TranslationError, Multiple, Dead, Empty, TooSmall } TranslationMode;
static TranslationMode translationMode;
static int translationCalls;
static UInt16 fixtureVCode = 47;
static OSStatus FixtureTranslate(const UCKeyboardLayout *layout, UInt16 code,
        UInt16 action, UInt32 modifiers, UInt32 keyboardType, OptionBits options,
        UInt32 *dead, UniCharCount capacity, UniCharCount *length, UniChar *characters) {
    if (translationMode == Native)
        return UCKeyTranslate(layout, code, action, modifiers, keyboardType, options,
                              dead, capacity, length, characters);
    // Synthetic outcomes for fault injection, NOT observations of OS behavior.
    translationCalls++;
    CHECK(action == kUCKeyActionDown && modifiers == ((cmdKey >> 8) & 0xff), "Command key-down translation");
    CHECK(keyboardType == fixtureKeyboardType, "uses current keyboard type");
    CHECK(*dead == 0 && options == kUCKeyTranslateNoDeadKeysMask, "fresh, disabled dead-key state");
    CHECK(capacity >= 2, "space for multi-character counterexample");
    *length = 1;
    characters[0] = code == fixtureVCode ? 'v' : 'x';
    if (translationMode == UpperV && code == fixtureVCode) characters[0] = 'V';
    if (translationMode == NoV) characters[0] = 'x';
    if (translationMode == Multiple) { *length = 2; characters[1] = 'x'; }
    if (translationMode == Dead) *dead = 1;
    if (translationMode == Empty) *length = 0;
    if (translationMode == TranslationError) return paramErr;
    if (translationMode == TooSmall) return kUCOutputBufferTooSmall;
    return noErr;
}

// Opaque stand-ins, never real CGEvent objects.
static char eventSource;
typedef struct { CGKeyCode code; bool down; CGEventFlags flags; } Event;
static Event downEvent, upEvent, posted[2];
static int sourceCreates, eventCreates, posts, eventReleases, invalidCalls;
static int allocationFailure; // 1: source, 2: key-down, 3: key-up.
static CGEventSourceRef CreateSource(CGEventSourceStateID state) {
    CHECK(state == kCGEventSourceStateCombinedSessionState, "event source state");
    sourceCreates++;
    if (allocationFailure == 1) return NULL;
    return (CGEventSourceRef)&eventSource;
}
static CGEventRef FixtureCreateEvent(CGEventSourceRef source, CGKeyCode code, bool down) {
    CHECK(source == (CGEventSourceRef)&eventSource, "event source identity");
    eventCreates++;
    if ((down && allocationFailure == 2) || (!down && allocationFailure == 3)) return NULL;
    Event *event = down ? &downEvent : &upEvent;
    *event = (Event){code, down, 0};
    return (CGEventRef)event;
}
static void SetFlags(CGEventRef event, CGEventFlags flags) {
    if (!event) { invalidCalls++; return; }
    ((Event *)event)->flags = flags;
}
static void Post(CGEventTapLocation tap, CGEventRef event) {
    CHECK(tap == kCGHIDEventTap, "event tap");
    if (!event) { invalidCalls++; posts++; return; }
    if (posts < 2) posted[posts] = *(Event *)event;
    posts++;
}
static void Release(CFTypeRef value) {
    if (!value) { invalidCalls++; return; }
    if (value == &eventSource || value == &downEvent || value == &upEvent) {
        eventReleases++;
    } else {
        if (value == activeLayout || value == asciiLayout) sourceReleases++;
        CFRelease(value);
    }
}
static Boolean Trusted(CFDictionaryRef options) {
    CHECK(CFDictionaryGetValue(options, kAXTrustedCheckOptionPrompt) == kCFBooleanFalse,
          "test permission check must be nonprompting");
    return true; // Injected permission result, not an observed OS return value.
}
static void NoDispatch(dispatch_queue_t queue, dispatch_block_t block) {
    (void)queue; (void)block;
    CHECK(false, "unexpected UI dispatch; block was not executed");
}

#define TISCopyCurrentKeyboardLayoutInputSource CopyActiveLayout
#define TISCopyCurrentASCIICapableKeyboardLayoutInputSource CopyASCIILayout
#define TISGetInputSourceProperty FixtureProperty
#define LMGetKbdType KeyboardType
#define UCKeyTranslate FixtureTranslate
#define CGEventSourceCreate CreateSource
#define CGEventCreateKeyboardEvent FixtureCreateEvent
#define CGEventSetFlags SetFlags
#define CGEventPost Post
#define CFRelease Release
#define AXIsProcessTrustedWithOptions Trusted
#define dispatch_async NoDispatch
#define DLog(...) do {} while (0)

// Optional only so this regression also compiles against the pre-fix source.
#if __has_include("FlycutPasteKey.h")
#import "FlycutPasteKey.h"
#endif
@interface PasteHarness : NSObject
- (void)fakeKey:(NSNumber *)code withCommandFlag:(BOOL)flag;
- (void)fakeCommandV;
- (void)openAccessibilitySettings;
@end
@implementation PasteHarness
#include "PasteMethods.inc"
- (void)openAccessibilitySettings { CHECK(false, "unexpected Settings call"); }
@end

#undef CFRelease
#undef UCKeyTranslate
static void Reset(void) {
    activeCopies = asciiCopies = sourceReleases = 0;
    sourceCreates = eventCreates = posts = eventReleases = invalidCalls = 0;
    translationCalls = 0;
    memset(posted, 0, sizeof(posted));
}
static TISInputSourceRef CopyInstalledLayout(NSString *identifier) {
    NSDictionary *filter = @{(id)kTISPropertyInputSourceID: identifier};
    CFArrayRef list = TISCreateInputSourceList((CFDictionaryRef)filter, true);
    TISInputSourceRef result = NULL;
    if (list && CFArrayGetCount(list)) result = (TISInputSourceRef)CFRetain(CFArrayGetValueAtIndex(list, 0));
    if (list) CFRelease(list);
    return result;
}
static NSString *Translate(CFDataRef data, UInt16 code, UInt32 modifiers) {
    UInt32 dead = 0;
    UniChar chars[16];
    UniCharCount count = 0;
    OSStatus status = UCKeyTranslate((const UCKeyboardLayout *)CFDataGetBytePtr(data),
        code, kUCKeyActionDown, modifiers, 40, kUCKeyTranslateNoDeadKeysMask,
        &dead, 16, &count, chars);
    CHECK(status == noErr, "native oracle translation succeeds");
    return status == noErr ? [NSString stringWithCharacters:chars length:count] : nil;
}
static void CheckPaste(CGKeyCode expected) {
    CHECK(sourceCreates == 1 && eventCreates == 2, "one source and two events");
    CHECK(posts == 2, "exactly two intercepted posts");
    CHECK(posted[0].code == expected && posted[1].code == expected, "both events use semantic Paste key");
    CHECK(posted[0].down && !posted[1].down, "key-down precedes key-up");
    CHECK((posted[0].flags & kCGEventFlagMaskCommand) != 0, "Command flag on key-down");
    CHECK(eventReleases == 3 && invalidCalls == 0, "events and source released safely");
}
static void TestLayouts(PasteHarness *harness) {
    NSArray *identifiers = @[@"com.apple.keylayout.US", @"com.apple.keylayout.Dvorak",
        @"com.apple.keylayout.DVORAK-QWERTYCMD", @"com.apple.keylayout.Russian"];
    const CGKeyCode expected[] = {9, 47, 9, 9};
    NSUInteger tested = 0;
    for (NSString *identifier in identifiers) {
        activeLayout = CopyInstalledLayout(identifier);
        CHECK(activeLayout != NULL, "required installed layout fixture exists (not skipped)");
        if (!activeLayout) continue;
        CFDataRef data = TISGetInputSourceProperty(activeLayout, kTISPropertyUnicodeKeyLayoutData);
        CHECK(data != NULL, "required installed Unicode layout data exists");
        if (data) {
            Reset();
            NSString *plain = Translate(data, kVK_ANSI_V, 0);
            NSString *command = Translate(data, kVK_ANSI_V, (cmdKey >> 8) & 0xff);
            NSString *resolved = Translate(data, expected[tested], (cmdKey >> 8) & 0xff);
            CHECK([resolved.lowercaseString isEqualToString:@"v"], "expected key really translates to Command-V");
            [harness fakeCommandV];
            printf("%s: ANSI-V=%s Command-ANSI-V=%s expected=%u posted=%u\n",
                identifier.UTF8String, plain.UTF8String, command.UTF8String, expected[tested], posted[0].code);
            CheckPaste(expected[tested]);
            CHECK(activeCopies == 1, "active layout is read afresh for every Paste");
            CHECK(asciiCopies == 0, "valid active layout must not use ASCII fallback");
            CHECK(sourceReleases == activeCopies, "copied active layout is released");
        }
        CFRelease(activeLayout);
        activeLayout = NULL;
        tested++;
    }
    CHECK(tested == 4, "all four installed layout fixtures tested");
}
static void TestFallback(PasteHarness *harness) {
    asciiLayout = CopyInstalledLayout(@"com.apple.keylayout.Dvorak");
    CHECK(asciiLayout != NULL, "Dvorak ASCII fallback fixture exists");
    if (!asciiLayout) return;
    for (int missingSource = 0; missingSource < 2; missingSource++) {
        activeLayout = missingSource ? NULL : (TISInputSourceRef)CFRetain((CFDictionaryRef)@{});
        Reset();
        [harness fakeCommandV];
        CheckPaste(47);
        CHECK(activeCopies == 1 && asciiCopies == 1, "missing Unicode data uses ASCII layout once");
        CHECK(sourceReleases == (missingSource ? 1 : 2), "all copied layout sources released");
        printf("fallback missing-source=%d: expected=47 posted=%u\n", missingSource, posted[0].code);
        if (activeLayout) CFRelease(activeLayout);
        activeLayout = NULL;
    }
    CFRelease(asciiLayout);
    asciiLayout = NULL;
    Reset();
    [harness fakeCommandV];
    CHECK(sourceCreates == 0 && eventCreates == 0 && posts == 0, "no layout means no input");
    CHECK(invalidCalls == 0, "no invalid release when both sources are absent");
    asciiLayout = (TISInputSourceRef)CFRetain((CFDictionaryRef)@{});
    Reset();
    [harness fakeCommandV];
    CHECK(sourceCreates == 0 && eventCreates == 0 && posts == 0, "no fallback Unicode data means no input");
    CHECK(sourceReleases == 1, "fallback without data is released");
    CFRelease(asciiLayout);
    asciiLayout = NULL;
}
static void TestTranslation(PasteHarness *harness, BOOL truncatedData) {
    asciiLayout = CopyInstalledLayout(@"com.apple.keylayout.US");
    fixtureKeyboardType = 41; // Proves the resolver does not hardcode ANSI 40.
    const NSUInteger lengths[] = {0, sizeof(UCKeyboardLayout) - 1, sizeof(UCKeyboardLayout)};
    for (NSUInteger index = truncatedData ? 0 : 2; index < (truncatedData ? 2 : 3); index++) {
        NSData *data = [NSMutableData dataWithLength:lengths[index]];
        activeLayout = (TISInputSourceRef)CFRetain((CFDictionaryRef)@{(id)kTISPropertyUnicodeKeyLayoutData:data});
        for (TranslationMode mode = LowerV; mode <= (truncatedData ? LowerV : TooSmall); mode++) {
            translationMode = mode;
            Reset();
            [harness fakeCommandV];
            if (!truncatedData && (mode == LowerV || mode == UpperV)) CheckPaste(47);
            else CHECK(sourceCreates == 0 && eventCreates == 0 && posts == 0, "unusable translation posts nothing");
            CHECK(activeCopies == 1 && asciiCopies == 0 && sourceReleases == 1,
                  "known active map is not replaced with unrelated ASCII layout; source released");
            if (truncatedData) CHECK(translationCalls == 0, "truncated layout data never reaches translation");
            printf("translation mode=%d bytes=%lu: translations=%d posts=%d\n",
                   mode, (unsigned long)lengths[index], translationCalls, posts);
        }
        CFRelease(activeLayout);
        activeLayout = NULL;
    }
    CFRelease(asciiLayout);
    asciiLayout = NULL;
    translationMode = Native;
}
static void TestFallbackErrors(PasteHarness *harness) {
    const TranslationMode modes[] = {NoV, TranslationError, Multiple};
    for (NSUInteger index = 0; index < sizeof(modes) / sizeof(modes[0]); index++) {
        NSData *data = [NSMutableData dataWithLength:sizeof(UCKeyboardLayout)];
        asciiLayout = (TISInputSourceRef)CFRetain((CFDictionaryRef)@{(id)kTISPropertyUnicodeKeyLayoutData:data});
        translationMode = modes[index];
        Reset();
        [harness fakeCommandV];
        CHECK(sourceCreates == 0 && eventCreates == 0 && posts == 0, "unresolved fallback posts nothing");
        CHECK(activeCopies == 1 && asciiCopies == 1 && sourceReleases == 1, "fallback error releases its source");
        CFRelease(asciiLayout);
        asciiLayout = NULL;
    }
    translationMode = Native;
}
static void TestAllocation(PasteHarness *harness) {
    for (allocationFailure = 1; allocationFailure <= 3; allocationFailure++) {
        Reset();
        [harness fakeKey:@47 withCommandFlag:YES];
        CHECK(posts == 0, "partial event allocation never posts a partial keystroke");
        CHECK(invalidCalls == 0, "never flags/posts/releases a NULL event");
        CHECK(eventReleases == (allocationFailure == 1 ? 0 : 2), "releases every successful allocation");
        printf("allocation-failure=%d: creates=%d posts=%d releases=%d invalid=%d\n",
               allocationFailure, eventCreates, posts, eventReleases, invalidCalls);
    }
    allocationFailure = 0;
    Reset();
    [harness fakeKey:@125 withCommandFlag:NO];
    CHECK(posts == 2 && posted[0].code == 125 && posted[1].code == 125, "non-Paste keys unchanged");
    CHECK(posted[0].flags == 0 && posted[1].flags == 0, "unmodified arrow has no Command flag");
}
int main(int argc, const char *argv[]) { @autoreleasepool {
    if (argc != 2) return 2;
    PasteHarness *harness = [[PasteHarness alloc] init];
    if (!strcmp(argv[1], "layouts")) TestLayouts(harness);
    else if (!strcmp(argv[1], "fallback")) TestFallback(harness);
    else if (!strcmp(argv[1], "translation")) TestTranslation(harness, NO);
    else if (!strcmp(argv[1], "truncated")) TestTranslation(harness, YES);
    else if (!strcmp(argv[1], "allocation")) TestAllocation(harness);
    else if (!strcmp(argv[1], "fallback-errors")) TestFallbackErrors(harness);
    else if (!strcmp(argv[1], "nil")) {
        Reset();
        [harness fakeKey:nil withCommandFlag:YES];
        CHECK(sourceCreates == 0 && eventCreates == 0 && posts == 0, "nil key creates/posts nothing");
    } else return 2;
    [harness release];
    printf("%s: %s (%d assertion failures)\n", argv[1], failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
}}
