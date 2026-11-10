#!/usr/bin/env python3
"""Targeted four-event sink ported from the keyboard-layout regression fixture.

This tests the targeted-post consumer of the unchanged keyboard-layout resolver.
Layout data, translation and all event allocation/posting boundaries are inert.
No event reaches another process and no real Accessibility request is made.
"""
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture
FIXTURE = r'''

#include "PasteTestEnvironmentImplementation.h"
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>
#import "AppController.h"

typedef struct {
    pid_t pid;
    CGEventType type;
    CGKeyCode keyCode;
    CGEventFlags flags;
} FCPostedEvent;

static FCPostedEvent posted[8];
static int postedCount = 0;
static BOOL trusted = YES;
static int prompts = 0;
static int legacyCalls = 0;
static BOOL missingLayout = NO;
static int sourceCreates = 0;
static int layoutReads = 0;
TISInputSourceRef FCTestCopyLayout(void) {
    layoutReads++;
    if (missingLayout) return NULL;
    return (TISInputSourceRef)CFRetain((CFTypeRef)@{(id)kTISPropertyUnicodeKeyLayoutData:
        [NSMutableData dataWithLength:sizeof(UCKeyboardLayout)]});
}
TISInputSourceRef FCTestCopyASCIILayout(void) { return NULL; }
void *FCTestLayoutProperty(TISInputSourceRef source, CFStringRef property) {
    return (void *)CFDictionaryGetValue((CFDictionaryRef)source,property);
}
UInt8 FCTestKeyboardType(void) { return 41; }
OSStatus FCTestTranslate(const UCKeyboardLayout *layout, UInt16 code, UInt16 action,
    UInt32 modifiers, UInt32 keyboardType, OptionBits options, UInt32 *dead,
    UniCharCount capacity, UniCharCount *length, UniChar *characters) {
    if (action!=kUCKeyActionDown || modifiers!=((cmdKey>>8)&0xff) || keyboardType!=41)
        abort();
    *dead=0; *length=1; characters[0]=code==47 ? 'v' : 'x'; return noErr;
}
CGEventSourceRef FCTestCreateSource(CGEventSourceStateID state) {
    sourceCreates++; return (CGEventSourceRef)CFRetain((CFTypeRef)@{});
}
CGEventRef FCTestCreateEvent(CGEventSourceRef source, CGKeyCode code, bool down) {
    // Opaque in-memory stand-ins: no real event objects or OS input delivery.
    return (CGEventRef)[@{@"code":@(code), @"type":@(code==kVK_Command ?
        kCGEventFlagsChanged : (down ? kCGEventKeyDown : kCGEventKeyUp)), @"flags":@0} mutableCopy];
}
void FCTestSetFlags(CGEventRef event, CGEventFlags flags) {
    [(NSMutableDictionary *)event setObject:@(flags) forKey:@"flags"];
}

Boolean FCTestAXIsProcessTrustedWithOptions(CFDictionaryRef options) {
    if (CFBooleanGetValue(CFDictionaryGetValue(options,kAXTrustedCheckOptionPrompt))) prompts++;
    return trusted;
}

void FCTestCGEventPostToPid(pid_t pid, CGEventRef event) {
    if (postedCount >= 8) return;
    posted[postedCount].pid = pid;
    posted[postedCount].type = (CGEventType)[[(NSDictionary *)event objectForKey:@"type"] unsignedIntValue];
    posted[postedCount].keyCode = (CGKeyCode)[[(NSDictionary *)event objectForKey:@"code"] unsignedShortValue];
    posted[postedCount].flags = [[(NSDictionary *)event objectForKey:@"flags"] unsignedLongLongValue];
    postedCount += 1;
}

@interface AppController (TargetedPasteTesting)
- (BOOL)postCommandVToProcessIdentifier:(pid_t)processIdentifier;
@end

@interface FCTargetTestController : AppController
@end
@implementation FCTargetTestController
- (void)fakeCommandV { legacyCalls++; }
@end
int main(int argc, const char **argv) {
    @autoreleasepool {
        AppController *controller = [[FCTargetTestController alloc] init];
        trusted = strcmp(argv[1],"denied") != 0;
        missingLayout = strcmp(argv[1],"nil-layout") == 0;
        BOOL postedResult = [controller postCommandVToProcessIdentifier:4242];
        if (missingLayout) {
            if (postedResult || postedCount || sourceCreates || layoutReads != 1) {
                fprintf(stderr,"missing layout did not fail closed before allocations\n"); return 61;
            }
            return 0;
        }
        if (!trusted) {
            if (postedCount || legacyCalls || prompts != 1) {
                fprintf(stderr,"denied paste used legacy dialog helper instead of native-only consent: legacy=%d prompts=%d\n",legacyCalls,prompts);
                return 60;
            }
            return 0;
        }
        if (postedCount != 4 || !postedResult || layoutReads != 1) return 10;

        CGEventType expectedTypes[] = {
            kCGEventFlagsChanged, kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged
        };
        CGKeyCode expectedCodes[] = {
            kVK_Command, 47, 47, kVK_Command
        };
        for (int index = 0; index < 4; index += 1) {
            if (posted[index].pid != 4242) return 20 + index;
            if (posted[index].type != expectedTypes[index]) return 30 + index;
            if (posted[index].keyCode != expectedCodes[index]) return 40 + index;
        }
        for (int index = 0; index < 3; index += 1)
            if (!(posted[index].flags & kCGEventFlagMaskCommand)) return 50 + index;
        [controller release];
    }
    return 0;
}

'''
class KeyboardLayoutPasteRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'TargetedEventFixture', (
            '-DAXIsProcessTrustedWithOptions=FCTestAXIsProcessTrustedWithOptions',
            '-DCGEventPostToPid=FCTestCGEventPostToPid',
            '-DTISCopyCurrentKeyboardLayoutInputSource=FCTestCopyLayout',
            '-DTISCopyCurrentASCIICapableKeyboardLayoutInputSource=FCTestCopyASCIILayout',
            '-DTISGetInputSourceProperty=FCTestLayoutProperty',
            '-DLMGetKbdType=FCTestKeyboardType', '-DUCKeyTranslate=FCTestTranslate',
            '-DCGEventSourceCreate=FCTestCreateSource',
            '-DCGEventCreateKeyboardEvent=FCTestCreateEvent',
            '-DCGEventSetFlags=FCTestSetFlags'))
    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
    def test_targeted_paste_executes_four_events_for_the_exact_process(self):
        self.check_mode('trusted')
    def test_nil_layout_returns_no_before_allocating_or_posting_events(self):
        self.check_mode('nil-layout')
    def test_denied_paste_uses_native_consent_without_legacy_dialog(self):
        self.check_mode('denied')
if __name__ == '__main__':
    unittest.main()
