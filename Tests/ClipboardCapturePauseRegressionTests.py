#!/usr/bin/env python3
"""Regression tests: pausing capture discards every capture that was in flight,
and diagnostics mode stores the copy's type, never a payload (also for the
opt-in animated-GIF download).

The fixture compiles the real AppController, FlycutOperator and engine sources and
runs the production pollPB:, menuWillOpen: (Option-click pause/resume) and GIF
download completion. Only OS boundaries are replaced: user defaults live in
memory, the pasteboard is an in-process object whose reads can be held on a
semaphore, NSApp (only while the Option-click handler runs), the status item and
its icon lookup, and running-application queries are inert objects, the
image store writes below the test's temporary directory, and NSURLSession hands
its completion handler to the fixture instead of using the network. The general
pasteboard is never touched (access aborts the fixture), no NIB is loaded and no
app bundle is built or launched.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <ImageIO/ImageIO.h>
#import <objc/runtime.h>
#import <string.h>
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutClipping.h"
#import "FlycutImageStore.h"

// ---- OS boundary: persistent preferences are replaced by an in-memory store ----
@interface FCMemoryDefaults : NSObject { NSMutableDictionary *_values; }
@end
@implementation FCMemoryDefaults
- (id)init { if ((self = [super init])) _values = [[NSMutableDictionary alloc] init]; return self; }
- (void)registerDefaults:(NSDictionary *)values {
    for (id key in values) if (_values[key] == nil) _values[key] = values[key];
}
- (id)objectForKey:(NSString *)key { return _values[key]; }
- (id)valueForKey:(NSString *)key { return _values[key]; }
- (NSString *)stringForKey:(NSString *)key { return _values[key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return _values[key]; }
- (NSArray *)arrayForKey:(NSString *)key { return _values[key]; }
- (NSInteger)integerForKey:(NSString *)key { return [_values[key] integerValue]; }
- (float)floatForKey:(NSString *)key { return [_values[key] floatValue]; }
- (double)doubleForKey:(NSString *)key { return [_values[key] doubleValue]; }
- (BOOL)boolForKey:(NSString *)key { return [_values[key] boolValue]; }
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) _values[key] = value; else [_values removeObjectForKey:key];
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (void)setInteger:(NSInteger)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (void)removeObjectForKey:(NSString *)key { [_values removeObjectForKey:key]; }
- (BOOL)synchronize { return YES; }
@end

// ---- OS boundary: application object, status item and running applications ----
@interface FCFakeApplication : NSObject
@end
@implementation FCFakeApplication
- (NSEvent *)currentEvent {
    // An Option-click on the menu bar icon toggles "pause capture".
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                       modifierFlags:NSEventModifierFlagOption timestamp:0 windowNumber:0
                             context:nil characters:@"" charactersIgnoringModifiers:@""
                           isARepeat:NO keyCode:0];
}
- (void)hide:(id)sender { }
@end

@interface FCFakeStatusButton : NSObject { NSString *_title; NSImage *_image; }
@property(nonatomic, copy) NSString *title;
@property(nonatomic, retain) NSImage *image;
@end
@implementation FCFakeStatusButton
@synthesize title = _title;
@synthesize image = _image;
@end

@interface FCFakeStatusItem : NSObject { FCFakeStatusButton *_button; }
- (FCFakeStatusButton *)button;
- (BOOL)isEnabled;
@end
@implementation FCFakeStatusItem
- (id)init {
    if ((self = [super init])) { _button = [[FCFakeStatusButton alloc] init]; [_button setTitle:@"Flycut"]; }
    return self;
}
- (FCFakeStatusButton *)button { return _button; }
- (BOOL)isEnabled { return NO; }   // no menu is rebuilt in the fixture
@end

@interface FCFakeWorkspace : NSObject
@end
@implementation FCFakeWorkspace
- (NSArray *)runningApplications { return @[]; }
@end

// ---- OS boundary: an in-process pasteboard whose reads can be held ----
@interface FCHeldPasteboard : NSObject {
@public
    NSInteger changeCount;
    NSArray *types;
    NSString *text;
    NSData *image;
    NSData *html;
    BOOL holdNextRead;
    dispatch_semaphore_t readStarted;
    dispatch_semaphore_t releaseRead;
}
@end
@implementation FCHeldPasteboard
- (NSInteger)changeCount { return changeCount; }
- (NSArray *)types { return types; }
- (NSString *)availableTypeFromArray:(NSArray *)candidates {
    for (NSString *candidate in candidates) if ([types containsObject:candidate]) return candidate;
    return nil;
}
- (void)holdIfRequested {
    if (!holdNextRead) return;
    holdNextRead = NO;
    dispatch_semaphore_signal(readStarted);
    dispatch_semaphore_wait(releaseRead, DISPATCH_TIME_FOREVER);
}
- (NSString *)stringForType:(NSString *)type { [self holdIfRequested]; return text; }
- (NSData *)dataForType:(NSString *)type {
    if ([type isEqualToString:@"public.html"]) return html;
    [self holdIfRequested];
    return image;
}
@end

// ---- OS boundary: network. The fixture delivers the download result itself. ----
static void (^pendingDownload)(NSData *, NSURLResponse *, NSError *);
@interface FCFakeTask : NSObject
@end
@implementation FCFakeTask
- (void)resume { }
@end
@interface FCFakeSession : NSObject
@end
@implementation FCFakeSession
- (id)dataTaskWithURL:(NSURL *)url completionHandler:(void (^)(NSData *, NSURLResponse *, NSError *))handler {
    pendingDownload = [handler copy];
    return [[[FCFakeTask alloc] init] autorelease];
}
- (void)finishTasksAndInvalidate { }
@end

static FCMemoryDefaults *memoryDefaults;
static FCFakeWorkspace *fakeWorkspace;
static FCFakeSession *fakeSession;
static FlycutImageStore *temporaryImageStore;
static id FCStandardDefaults(id object, SEL selector) { return memoryDefaults; }
static id FCSharedWorkspace(id object, SEL selector) { return fakeWorkspace; }
static id FCSession(id object, SEL selector, id configuration) { return fakeSession; }
static id FCImageStore(id object, SEL selector) { return temporaryImageStore; }
// The status item icon is menu-bar UI; the fixture has no bundle resources to load.
static id FCNoImage(id object, SEL selector, NSString *name) { return nil; }
static FCFakeApplication *fakeApplication;
static id FCForbidden(id object, SEL selector) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: +[%s %s]\n",
            class_getName(object), sel_getName(selector));
    abort();
}

static void InstallBoundaries(const char *imageDirectory) {
    memoryDefaults = [[FCMemoryDefaults alloc] init];
    fakeWorkspace = [[FCFakeWorkspace alloc] init];
    fakeSession = [[FCFakeSession alloc] init];
    method_setImplementation(class_getClassMethod([NSUserDefaults class], @selector(standardUserDefaults)),
                             (IMP)FCStandardDefaults);
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)),
                             (IMP)FCSharedWorkspace);
    method_setImplementation(class_getClassMethod([NSURLSession class], @selector(sessionWithConfiguration:)),
                             (IMP)FCSession);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)),
                             (IMP)FCForbidden);
    // The image store writes below the test's temporary directory, never the user's.
    temporaryImageStore = [FlycutImageStore alloc];
    NSString *directory = [NSString stringWithUTF8String:imageDirectory];
    [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES
                                               attributes:nil error:nil];
    [temporaryImageStore setValue:directory forKey:@"imagesDirectoryPath"];
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)),
                             (IMP)FCImageStore);
    method_setImplementation(class_getClassMethod([NSImage class], @selector(imageNamed:)), (IMP)FCNoImage);
    fakeApplication = [[FCFakeApplication alloc] init];
    [memoryDefaults setObject:@0 forKey:@"savePreference"];
    [memoryDefaults setObject:@NO forKey:@"saveForgottenClippings"];
    [memoryDefaults setObject:@NO forKey:@"saveForgottenFavorites"];
}

@interface AppController (CapturePauseTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)menuWillOpen:(NSMenu *)menu;
- (void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL;
@end

@interface FCCapturePauseController : AppController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCHeldPasteboard *)pasteboard;
- (void)drainCaptures;
- (void)drainMainQueue;
@end
@implementation FCCapturePauseController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCHeldPasteboard *)pasteboard {
    flycutOperator = op;
    jcPasteboard = (id)pasteboard;
    statusItem = (id)[[FCFakeStatusItem alloc] init];
    pbCount = [[NSNumber numberWithInteger:pasteboard->changeCount] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
}
// Waits until every queued read and its main-thread commit have run.
- (void)drainCaptures {
    __block BOOL drained = NO;
    dispatch_async(clipboardReadQueue, ^{
        dispatch_async(dispatch_get_main_queue(), ^{ drained = YES; });
    });
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5.0];
    while (!drained && [limit timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
}
// Runs the main queue until everything enqueued so far (e.g. a download commit) has run.
- (void)drainMainQueue {
    __block BOOL drained = NO;
    dispatch_async(dispatch_get_main_queue(), ^{ drained = YES; });
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5.0];
    while (!drained && [limit timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
}
@end

static NSData *TIFFImage(void) {
    NSBitmapImageRep *rep = [[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:2 pixelsHigh:2
        bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace
        bytesPerRow:0 bitsPerPixel:0] autorelease];
    return [rep TIFFRepresentation];
}

static NSData *AnimatedGIF(void) {
    NSMutableData *data = [NSMutableData data];
    CGImageDestinationRef destination = CGImageDestinationCreateWithData((CFMutableDataRef)data,
        CFSTR("com.compuserve.gif"), 2, NULL);
    if (destination == NULL) return nil;
    for (int frame = 0; frame < 2; frame++) {
        NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:2 pixelsHigh:2
            bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace
            bytesPerRow:0 bitsPerPixel:0];
        memset([rep bitmapData], frame ? 0xFF : 0x20, [rep bytesPerRow] * 2);
        CGImageDestinationAddImage(destination, [rep CGImage], NULL);
        [rep release];
    }
    bool finalized = CGImageDestinationFinalize(destination);
    CFRelease(destination);
    return finalized ? data : nil;
}

// The production Option-click handler reads the triggering event from NSApp, which the
// fixture provides only for the duration of that call.
static void OptionClickMenuIcon(FCCapturePauseController *controller) {
    NSApp = (id)fakeApplication;
    [controller menuWillOpen:nil];
    NSApp = nil;
}

static void HoldNextRead(FCHeldPasteboard *pasteboard) {
    pasteboard->holdNextRead = YES;
}

static int WaitForHeldRead(FCHeldPasteboard *pasteboard) {
    return dispatch_semaphore_wait(pasteboard->readStarted, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)) == 0;
}

static int Report(const char *mode, FlycutOperator *op, int expected, NSString *expectedTop) {
    int count = [op jcListCount];
    FlycutClipping *top = count > 0 ? [op clippingAtIndex:0] : nil;
    NSString *topText = top == nil ? @"<none>" : ([top isImageClipping] ? [@"<image " stringByAppendingFormat:@"%@>", [top type]] : [top contents]);
    printf("%s: clippings=%d expected=%d top=%s\n", mode, count, expected, [topText UTF8String]);
    if (count != expected) return 10;
    if (expectedTop != nil && ![topText isEqualToString:expectedTop]) return 11;
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        const char *mode = argv[1];
        InstallBoundaries(argv[2]);

        FCHeldPasteboard *pasteboard = [[FCHeldPasteboard alloc] init];
        pasteboard->changeCount = 10;
        pasteboard->types = [@[NSPasteboardTypeString] retain];
        pasteboard->readStarted = dispatch_semaphore_create(0);
        pasteboard->releaseRead = dispatch_semaphore_create(0);

        FCCapturePauseController *controller = [[FCCapturePauseController alloc] init];
        FlycutOperator *op = [[FlycutOperator alloc] init];
        [op awakeFromNibDisplaying:10 withDisplayLength:40
                  withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
        [controller installOperator:op pasteboard:pasteboard];

        size_t modeLength = strlen(mode);
        BOOL pauseResume = strstr(mode, "pause-resume") != NULL;
        BOOL pauseOnly = modeLength > 7 && strcmp(mode + modeLength - 7, "-paused") == 0;

        if (strncmp(mode, "text-", 5) == 0) {
            // A new copy (generation 11) whose read is still in flight.
            pasteboard->changeCount = 11;
            pasteboard->text = @"copied before the pause";
            HoldNextRead(pasteboard);
            [controller pollPB:nil];
            if (!WaitForHeldRead(pasteboard)) return 30;
            if (pauseResume || pauseOnly) OptionClickMenuIcon(controller);   // pause capture
            if (pauseResume) OptionClickMenuIcon(controller);                // resume capture
            dispatch_semaphore_signal(pasteboard->releaseRead);
            [controller drainCaptures];
            if (strcmp(mode, "text-unpaused") == 0)
                return Report(mode, op, 1, @"copied before the pause");
            if (strcmp(mode, "text-pause-resume-then-new-copy") == 0) {
                pasteboard->changeCount = 12;
                pasteboard->text = @"copied after resuming";
                [controller pollPB:nil];
                [controller drainCaptures];
                return Report(mode, op, 1, @"copied after resuming");
            }
            return Report(mode, op, 0, nil);
        }

        if (strncmp(mode, "image-", 6) == 0) {
            pasteboard->changeCount = 11;
            [pasteboard->types release];
            pasteboard->types = [@[NSPasteboardTypeTIFF] retain];
            pasteboard->image = [TIFFImage() retain];
            HoldNextRead(pasteboard);
            [controller pollPB:nil];
            if (!WaitForHeldRead(pasteboard)) return 31;
            if (pauseResume || pauseOnly) OptionClickMenuIcon(controller);
            if (pauseResume) OptionClickMenuIcon(controller);
            dispatch_semaphore_signal(pasteboard->releaseRead);
            [controller drainCaptures];
            if (strcmp(mode, "image-unpaused") == 0)
                return Report(mode, op, 1, @"<image public.tiff>");
            return Report(mode, op, 0, nil);
        }

        if (strcmp(mode, "mixed-unpaused") == 0 || strcmp(mode, "mixed-diagnostics") == 0 ||
            strcmp(mode, "diagnostics-image-only") == 0) {
            // A copy carrying text and an image (or only an image), without any pause.
            BOOL diagnostics = strstr(mode, "diagnostics") != NULL;
            BOOL withText = strncmp(mode, "mixed-", 6) == 0;
            [memoryDefaults setObject:@(diagnostics) forKey:@"revealPasteboardTypes"];
            pasteboard->changeCount = 11;
            [pasteboard->types release];
            pasteboard->types = [(withText ? @[NSPasteboardTypeString, NSPasteboardTypeTIFF]
                                           : @[NSPasteboardTypeTIFF]) retain];
            pasteboard->text = @"copied text";
            pasteboard->image = [TIFFImage() retain];
            [controller pollPB:nil];
            [controller drainCaptures];
            if (strcmp(mode, "mixed-unpaused") == 0)
                return Report(mode, op, 2, @"<image public.tiff>");
            // Diagnostics record the copy's type once and never its payload.
            return Report(mode, op, 1, withText ? NSPasteboardTypeString : NSPasteboardTypeTIFF);
        }

        if (strcmp(mode, "diagnostics-gif-download") == 0) {
            // Diagnostics on and the animated-GIF download opted in. The copy is a
            // flattened still whose HTML points at an https .gif: diagnostics record
            // the still's type and neither download nor store the GIF.
            NSData *gif = AnimatedGIF();
            if (gif == nil) return 32;
            [memoryDefaults setObject:@YES forKey:@"downloadAnimatedGIFs"];
            [memoryDefaults setObject:@YES forKey:@"revealPasteboardTypes"];
            pasteboard->changeCount = 11;
            [pasteboard->types release];
            pasteboard->types = [@[NSPasteboardTypeTIFF, @"public.html"] retain];
            pasteboard->image = [TIFFImage() retain];
            pasteboard->html = [[@"<img src=\"https://example.invalid/animated.gif\">"
                                 dataUsingEncoding:NSUTF8StringEncoding] retain];
            [controller pollPB:nil];
            [controller drainCaptures];
            BOOL downloadStarted = pendingDownload != nil;
            if (downloadStarted) {
                // Deliver the download so a stored payload shows up in the report.
                NSHTTPURLResponse *response = [[[NSHTTPURLResponse alloc]
                    initWithURL:[NSURL URLWithString:@"https://example.invalid/animated.gif"]
                     statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:@{}] autorelease];
                pendingDownload(gif, response, nil);
                [controller drainMainQueue];
            }
            printf("%s: download started=%s\n", mode, downloadStarted ? "YES" : "NO");
            int result = Report(mode, op, 1, NSPasteboardTypeTIFF);
            if (result == 0 && downloadStarted) return 12;
            return result;
        }

        if (strncmp(mode, "gif-", 4) == 0) {
            // Opt-in animated GIF download: the copied HTML points at an https .gif.
            NSData *gif = AnimatedGIF();
            if (gif == nil) return 32;
            [memoryDefaults setObject:@YES forKey:@"downloadAnimatedGIFs"];
            pasteboard->changeCount = 11;
            [pasteboard->types release];
            pasteboard->types = [@[NSPasteboardTypeTIFF, @"public.html"] retain];
            pasteboard->image = [TIFFImage() retain];
            pasteboard->html = [[@"<img src=\"https://example.invalid/animated.gif\">"
                                 dataUsingEncoding:NSUTF8StringEncoding] retain];
            [controller pollPB:nil];
            if (pendingDownload == nil) return 33;
            if (pauseResume || pauseOnly) OptionClickMenuIcon(controller);
            if (pauseResume) OptionClickMenuIcon(controller);
            if (strcmp(mode, "gif-diagnostics-on-during-download") == 0)
                [memoryDefaults setObject:@YES forKey:@"revealPasteboardTypes"];
            NSHTTPURLResponse *response = [[[NSHTTPURLResponse alloc]
                initWithURL:[NSURL URLWithString:@"https://example.invalid/animated.gif"]
                 statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:@{}] autorelease];
            pendingDownload(gif, response, nil);
            [controller drainMainQueue];
            if (strcmp(mode, "gif-unpaused") == 0)
                return Report(mode, op, 1, @"<image com.compuserve.gif>");
            return Report(mode, op, 0, nil);
        }
    }
    return 3;
}
'''

MODES = {
    "text-unpaused": "an ordinary text copy was not captured",
    "text-paused": "a text read in flight when capture was paused was committed",
    "text-pause-resume": "a text read in flight across pause and resume was committed after resuming",
    "text-pause-resume-then-new-copy": "a new copy after resuming was not captured (or a stale one was)",
    "image-unpaused": "an ordinary image copy was not captured",
    "image-paused": "an image read in flight when capture was paused was committed",
    "image-pause-resume": "an image read in flight across pause and resume was committed after resuming",
    "mixed-unpaused": "a copy with text and an image did not capture both",
    "mixed-diagnostics": "diagnostics saved a payload or more than one type record",
    "diagnostics-image-only": "diagnostics saved an image payload instead of its type",
    "diagnostics-gif-download": "diagnostics downloaded or saved the animated GIF instead of the copy's type",
    "gif-unpaused": "an opted-in animated GIF download was not captured",
    "gif-paused": "a GIF download in flight when capture was paused was committed",
    "gif-pause-resume": "a GIF download in flight across pause and resume was committed after resuming",
    "gif-diagnostics-on-during-download": "a GIF download was saved although diagnostics were turned on before it finished",
}


def fixture_sources() -> list[pathlib.Path]:
    try:
        listed = subprocess.check_output(
            ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        listed = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.m")]
    return [
        ROOT / path
        for path in sorted(listed)
        if path != "main.m"
        and not path.startswith("FlycutHelper/")
        and not path.startswith("Tests/")
    ]


class ClipboardCapturePauseRegressionTests(unittest.TestCase):
    binary: pathlib.Path
    directory: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-capture-pause-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "CapturePauseFixture.m"
        cls.binary = temp / "CapturePauseFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = [
            "/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
            "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
            "-include", str(ROOT / "Flycut_Prefix.pch"),
        ]
        for include_dir in sorted({ROOT, *(path.parent for path in sources)}):
            command.extend(["-I", str(include_dir)])
        command.extend(str(path) for path in sources)
        command.append(str(source))
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command.extend(["-framework", framework])
        command.extend(["-o", str(cls.binary)])
        cls.build = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def run_mode(self, mode: str) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        images = pathlib.Path(self.directory.name) / f"images-{mode}"
        run = subprocess.run(
            [str(self.binary), mode, str(images)], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        boundary = [line for line in run.stderr.splitlines() if "forbidden OS boundary" in line]
        self.assertEqual(
            run.returncode, 0,
            f"{MODES[mode]}; exit={run.returncode}; {run.stdout.strip()} {' '.join(boundary)}".strip(),
        )

    def test_text_copy_is_captured(self) -> None:
        self.run_mode("text-unpaused")

    def test_text_read_in_flight_is_dropped_while_paused(self) -> None:
        self.run_mode("text-paused")

    def test_text_read_in_flight_is_dropped_after_pause_and_resume(self) -> None:
        self.run_mode("text-pause-resume")

    def test_new_copy_after_resume_is_captured(self) -> None:
        self.run_mode("text-pause-resume-then-new-copy")

    def test_image_copy_is_captured(self) -> None:
        self.run_mode("image-unpaused")

    def test_image_read_in_flight_is_dropped_while_paused(self) -> None:
        self.run_mode("image-paused")

    def test_image_read_in_flight_is_dropped_after_pause_and_resume(self) -> None:
        self.run_mode("image-pause-resume")

    def test_text_and_image_copy_captures_both(self) -> None:
        self.run_mode("mixed-unpaused")

    def test_diagnostics_record_one_type_without_payload(self) -> None:
        self.run_mode("mixed-diagnostics")

    def test_diagnostics_record_image_type_without_payload(self) -> None:
        self.run_mode("diagnostics-image-only")

    def test_diagnostics_do_not_download_or_store_an_animated_gif(self) -> None:
        self.run_mode("diagnostics-gif-download")

    def test_gif_download_is_captured(self) -> None:
        self.run_mode("gif-unpaused")

    def test_gif_download_in_flight_is_dropped_while_paused(self) -> None:
        self.run_mode("gif-paused")

    def test_gif_download_in_flight_is_dropped_after_pause_and_resume(self) -> None:
        self.run_mode("gif-pause-resume")

    def test_gif_download_is_dropped_when_diagnostics_are_turned_on_before_it_finishes(self) -> None:
        self.run_mode("gif-diagnostics-on-during-download")


if __name__ == "__main__":
    unittest.main()
