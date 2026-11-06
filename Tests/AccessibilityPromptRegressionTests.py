#!/usr/bin/env python3
"""Execute production permission methods without TCC, UI, or clipboard effects.

Whole Objective-C methods are extracted verbatim, not reimplemented. Only the
OS boundaries are replaced: TCC, alert/application/workspace UI, and protected
event delivery. Event construction and the production session policy stay real.
PR15 uses fakeCommandV and its original policy; no canonical paste code is copied.
The app's init/awakeFromNib are deliberately not executed (they access user data).
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def objective_c_method(source: str, signature: str) -> str:
    """Extract a complete method, ignoring braces in comments and literals."""
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        pair = source[index:index + 2]
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if pair == "*/":
                state = "code"
                index += 1
        elif state in ('"', "'"):
            if char == "\\":
                index += 1
            elif char == state:
                state = "code"
        elif pair == "//":
            state = "line"
            index += 1
        elif pair == "/*":
            state = "block"
            index += 1
        elif char in ('"', "'"):
            state = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError(f"Unterminated method: {signature}")


FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>
#import "AccessibilityPromptPolicy.h"
#import "ShortcutRecorder/SRKeyCodeTransformer.h"
#import "ShortcutRecorder/SRCommon.h"
#import "UI/BezelWindow.h"

__LOCALIZATION_CLASS__

static NSMutableArray *trace;
static BOOL trusted = NO;
static BOOL grantDuringPrompt = NO;
static BOOL grantBeforeShow = NO;
static NSUInteger passiveChecks = 0;
static NSUInteger alertAllocations = 0;
static NSUInteger modalCount = 0;
static NSUInteger settingsCount = 0;
static NSUInteger promptRequests = 0;
static NSUInteger postedEvents = 0;
static NSUInteger activations = 0;
static NSUInteger hides = 0;
static NSModalResponse modalResponse = NSAlertFirstButtonReturn;
static NSMutableArray *alertTitles;
static NSMutableArray *eventTaps;

static Boolean FCTrustImplementation(CFDictionaryRef options) {
    BOOL prompt = [((__bridge NSDictionary *)options)[(__bridge id)kAXTrustedCheckOptionPrompt] boolValue];
    [trace addObject:prompt ? @"trust:YES" : @"trust:NO"];
    if (prompt) {
        promptRequests += 1;
        if (grantDuringPrompt) trusted = YES;
    } else {
        passiveChecks += 1;
        if (grantBeforeShow && passiveChecks == 2) trusted = YES;
    }
    return trusted;
}

static Boolean (*FCTrust)(CFDictionaryRef) = FCTrustImplementation;

// The protected event-delivery boundary is inert; never post to any process.
static void FCPost(CGEventTapLocation location, CGEventRef event) {
    postedEvents += 1;
    [eventTaps addObject:@(location)];
    [trace addObject:@"post"];
}

@interface FCAlert : NSObject {
    NSString *_messageText;
    NSString *_informativeText;
}
@property(nonatomic, copy) NSString *messageText;
@property(nonatomic, copy) NSString *informativeText;
- (id)addButtonWithTitle:(NSString *)title;
- (NSModalResponse)runModal;
@end
@implementation FCAlert
@synthesize messageText = _messageText, informativeText = _informativeText;
- (id)init {
    if ((self = [super init])) alertAllocations += 1;
    return self;
}
- (id)addButtonWithTitle:(NSString *)title { return nil; }
- (NSModalResponse)runModal {
    modalCount += 1;
    [alertTitles addObject:self.messageText ?: @""];
    [trace addObject:@"custom-alert"];
    return modalResponse;
}
- (void)dealloc {
    [_messageText release];
    [_informativeText release];
    [super dealloc];
}
@end

@interface FCWorkspace : NSObject
+ (id)sharedWorkspace;
- (BOOL)openURL:(NSURL *)url;
@end
@implementation FCWorkspace
+ (id)sharedWorkspace { return [[[self alloc] init] autorelease]; }
- (BOOL)openURL:(NSURL *)url {
    settingsCount += 1;
    [trace addObject:@"settings"];
    return YES;
}
@end

@interface FCApplication : NSObject
- (void)activateIgnoringOtherApps:(BOOL)flag;
- (void)hide:(id)sender;
@end
@implementation FCApplication
- (void)activateIgnoringOtherApps:(BOOL)flag {
    activations += 1;
    [trace addObject:@"activate"];
}
- (void)hide:(id)sender {
    hides += 1;
    [trace addObject:@"hide"];
}
@end
static FCApplication *testApplication;

// Keep actual method bodies, including their trust guards and policy decisions.
#define AXIsProcessTrustedWithOptions (*FCTrust)
#define CGEventPost FCPost
#define NSAlert FCAlert
#define NSWorkspace FCWorkspace
#define NSApp testApplication
#define DLog(...) do {} while (0)

@interface AppController : NSObject {
    BOOL hasShownAccessibilityExplanationThisSession;
    SRKeyCodeTransformer *srTransformer;
    BezelWindow *bezel;
    BOOL isBezelDisplayed;
    BOOL isBezelPinned;
}
- (void)openAccessibilitySettings;
- (void)requestAccessibilityWithPrompt;
- (void)showAccessibilityAlert;
- (IBAction)recheckAccessibility:(id)sender;
- (void)fakeCommandV;
- (void)fakeKey:(NSNumber *)keyCode withCommandFlag:(BOOL)setFlag;
- (void)hideApp;
- (void)hideBezel;
@end
@implementation AppController
__PRODUCTION_METHODS__
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        trace = [NSMutableArray array];
        alertTitles = [NSMutableArray array];
        eventTaps = [NSMutableArray array];
        testApplication = [[[FCApplication alloc] init] autorelease];
        AppController *controller = [[[AppController alloc] init] autorelease];
        [controller setValue:[[[SRKeyCodeTransformer alloc] init] autorelease] forKey:@"srTransformer"];
        NSString *scenario = [NSString stringWithUTF8String:argv[1]];
        if ([scenario isEqualToString:@"paste"]) {
            [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"repeat"]) {
            for (int i = 0; i < 3; i++) [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"show-trusted"]) {
            trusted = YES;
            [controller showAccessibilityAlert];
        } else if ([scenario isEqualToString:@"paste-trusted"]) {
            trusted = YES;
            [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"request"]) {
            [controller requestAccessibilityWithPrompt];
        } else if ([scenario isEqualToString:@"recheck-denied"]) {
            [controller recheckAccessibility:nil];
        } else if ([scenario isEqualToString:@"recheck-trusted"]) {
            trusted = YES;
            [controller recheckAccessibility:nil];
        } else if ([scenario isEqualToString:@"recheck-after-paste"]) {
            [controller fakeCommandV];
            [controller recheckAccessibility:nil];
            [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"explicit-retry-after-grant"]) {
            [controller fakeCommandV];
            trusted = YES;
            [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"grant-during-prompt"]) {
            grantDuringPrompt = YES;
            [controller fakeCommandV];
        } else if ([scenario isEqualToString:@"grant-before-show"]) {
            grantBeforeShow = YES;
            [controller fakeCommandV];

        } else {
            return 3;
        }
        NSDictionary *result = @{
            @"trace": trace, @"alerts": @(alertAllocations), @"modals": @(modalCount),
            @"titles": alertTitles, @"settings": @(settingsCount),
            @"prompts": @(promptRequests), @"events": @(postedEvents),
            @"event_taps": eventTaps, @"activations": @(activations), @"hides": @(hides)
        };
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:NULL];
        puts([[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] UTF8String]);
    }
    return 0;
}
'''


class AccessibilityPromptRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-accessibility-prompt-")
        cls.addClassCleanup(cls.directory.cleanup)
        source = (ROOT / "AppController.m").read_text(encoding="utf-8")
        methods = "\n\n".join(objective_c_method(source, signature) for signature in (
            "- (void)openAccessibilitySettings {",
            "- (void)requestAccessibilityWithPrompt {",
            "- (void)showAccessibilityAlert {",
            "-(IBAction)recheckAccessibility:(id)sender {",
            "-(void)fakeCommandV {",
            "-(void)fakeKey:(NSNumber*) keyCode withCommandFlag:(BOOL) setFlag",
            "-(void)hideApp\n{",
            "- (void) hideBezel\n{",
        ))
        fixture = pathlib.Path(cls.directory.name) / "AccessibilityPromptFixture.m"
        cls.binary = pathlib.Path(cls.directory.name) / "AccessibilityPromptFixture"
        # This production class only provides a bundle identity for localization.
        common = (ROOT / "ShortcutRecorder/SRCommon.m").read_text(encoding="utf-8")
        localization_match = re.search(r"@implementation SRDummyClass\s+@end", common)
        assert localization_match is not None, "Production localization class is missing"
        localization_class = localization_match.group(0)
        fixture.write_text(FIXTURE.replace("__PRODUCTION_METHODS__", methods).replace(
            "__LOCALIZATION_CLASS__", localization_class), encoding="utf-8")
        command = [
            "/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fblocks", "-fmodules",
            "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-deprecated-declarations",
            # Preserve the PR's legacy transformer rather than changing vendor code.
            "-Wno-semicolon-before-method-body", "-Wno-misleading-indentation",
            "-I", str(ROOT), str(fixture), str(ROOT / "ShortcutRecorder/SRKeyCodeTransformer.m"),
            "-framework", "Cocoa",
            "-framework", "Carbon", "-o", str(cls.binary),
        ]
        build = subprocess.run(command, text=True, capture_output=True, timeout=60)
        if build.returncode:
            raise AssertionError(f"Fixture compilation failed:\n{build.stderr}")

    def run_scenario(self, scenario: str) -> dict:
        run = subprocess.run([str(self.binary), scenario], text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def assert_no_prerequisite_ui(self, result: dict) -> None:
        self.assertEqual(result["alerts"], 0, result)
        self.assertEqual(result["modals"], 0, result)
        self.assertEqual(result["settings"], 0, result)
        self.assertEqual(result["activations"], 0, result)
        self.assertEqual(result["hides"], 0, result)

    def test_denied_paste_requests_only_native_consent_and_aborts(self) -> None:
        result = self.run_scenario("paste")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 1, result)
        self.assertEqual(result["events"], 0, result)
        self.assertEqual(result["trace"], ["trust:NO", "trust:NO", "trust:YES"])

    def test_repeated_denied_paste_requests_native_consent_only_once(self) -> None:
        result = self.run_scenario("repeat")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 1, result)
        self.assertEqual(result["events"], 0, result)
        self.assertEqual(result["trace"], ["trust:NO", "trust:NO", "trust:YES", "trust:NO", "trust:NO"])

    def test_trusted_permission_check_is_silent(self) -> None:
        result = self.run_scenario("show-trusted")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["trace"], ["trust:NO"])

    def test_trusted_explicit_paste_preserves_existing_event_delivery(self) -> None:
        result = self.run_scenario("paste-trusted")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 0, result)
        self.assertEqual(result["events"], 2, result)

    def test_explicit_prompt_request_does_not_navigate_or_paste(self) -> None:
        result = self.run_scenario("request")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["trace"], ["trust:YES"])
        self.assertEqual(result["events"], 0, result)

    def test_trust_gained_during_prompt_does_not_resume_aborted_paste(self) -> None:
        result = self.run_scenario("grant-during-prompt")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 1, result)
        self.assertEqual(result["events"], 0, result)

    def test_untrusted_manual_recheck_requests_only_native_consent(self) -> None:
        result = self.run_scenario("recheck-denied")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 1, result)
        self.assertEqual(result["events"], 0, result)
        self.assertEqual(result["trace"], ["trust:NO", "trust:YES"])

    def test_trusted_manual_recheck_keeps_only_granted_information(self) -> None:
        result = self.run_scenario("recheck-trusted")
        self.assertEqual(result["prompts"], 0, result)
        self.assertEqual(result["settings"], 0, result)
        self.assertEqual(result["events"], 0, result)
        self.assertEqual(result["modals"], 1, result)
        self.assertEqual(result["titles"], ["Accessibility Access Granted"])
        self.assertEqual(result["trace"], ["trust:NO", "custom-alert"])

    def test_manual_recheck_can_retry_without_resetting_paste_session_gate(self) -> None:
        result = self.run_scenario("recheck-after-paste")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 2, result)
        self.assertEqual(result["events"], 0, result)
        self.assertEqual(result["trace"], [
            "trust:NO", "trust:NO", "trust:YES", "trust:NO", "trust:YES", "trust:NO",
        ])

    def test_permission_grant_requires_a_new_explicit_paste(self) -> None:
        result = self.run_scenario("explicit-retry-after-grant")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 1, result)
        self.assertEqual(result["events"], 2, result)
        self.assertEqual(result["trace"], [
            "trust:NO", "trust:NO", "trust:YES", "trust:NO", "post", "post",
        ])

    def test_trust_gained_before_prompt_is_silent_but_still_aborts_paste(self) -> None:
        result = self.run_scenario("grant-before-show")
        self.assert_no_prerequisite_ui(result)
        self.assertEqual(result["prompts"], 0, result)
        self.assertEqual(result["events"], 0, result)


if __name__ == "__main__":
    unittest.main()
