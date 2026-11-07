#!/usr/bin/env python3
"""Image clippings (merged image support) inside the owned paste transaction."""
import pathlib
import re
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import <objc/runtime.h>
#import "AppController.h"
#import "FlycutImageStore.h"
@interface AppController (ImageTransactionTest)
- (void)hitMainHotKey:(id)hotKey;
- (void)metaKeysReleased;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)processMenuClippingSelection:(id)sender;
@end
static int beeps;
void FCTestNSBeep(void) { beeps++; }

// In-memory, generation-counted board with arbitrary representations.
@interface ImageBoard : NSObject
@property NSInteger changeCount;
@property(retain) NSMutableDictionary *representations;
@end
@implementation ImageBoard
- (id)init { if ((self = [super init])) _representations = [NSMutableDictionary new]; return self; }
- (NSArray *)pasteboardItems {
    if ([self.representations count] == 0) return @[];
    NSPasteboardItem *item = [[[NSPasteboardItem alloc] init] autorelease];
    for (NSString *type in self.representations) [item setData:self.representations[type] forType:type];
    return @[item];
}
- (NSArray *)types { return [self.representations allKeys]; }
- (NSInteger)declareTypes:(id)types owner:(id)owner { self.changeCount++; [self.representations removeAllObjects]; return self.changeCount; }
- (NSInteger)clearContents { return [self declareTypes:nil owner:nil]; }
- (BOOL)setData:(NSData *)data forType:(NSString *)type { if (!data) return NO; self.representations[type] = [[data copy] autorelease]; return YES; }
- (NSData *)dataForType:(NSString *)type { return self.representations[type]; }
- (BOOL)setString:(NSString *)value forType:(NSString *)type { return [self setData:[value dataUsingEncoding:NSUTF8StringEncoding] forType:type]; }
- (NSString *)stringForType:(NSString *)type {
    NSData *data = self.representations[type];
    return data ? [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] autorelease] : nil;
}
- (BOOL)writeObjects:(NSArray *)objects {
    for (id object in objects) {
        if ([object isKindOfClass:[NSURL class]])
            [self setString:[(NSURL *)object absoluteString] forType:NSPasteboardTypeFileURL];
        else for (NSString *type in [object types]) [self setData:[object dataForType:type] forType:type];
    }
    return YES;
}
@end

// Image files are an OS boundary: the shared store is replaced by memory.
@interface MemoryImageStore : NSObject
@property(retain) NSMutableDictionary *images;
@property(copy) NSString *gifPath;
@end
@implementation MemoryImageStore
- (id)init { if ((self = [super init])) _images = [NSMutableDictionary new]; return self; }
- (NSData *)imageDataForHash:(NSString *)hash { return self.images[hash]; }
- (NSString *)imageFilePathForHash:(NSString *)hash { return self.images[hash] ? self.gifPath : nil; }
- (NSString *)hashForData:(NSData *)data { return [NSString stringWithFormat:@"hash-%lu", (unsigned long)[data hash]]; }
- (BOOL)saveImageData:(NSData *)data forHash:(NSString *)hash extension:(NSString *)ext { self.images[hash] = data; return YES; }
- (BOOL)hasImageForHash:(NSString *)hash { return self.images[hash] != nil; }
- (void)deleteImageForHash:(NSString *)hash { [self.images removeObjectForKey:hash]; }
@end
static MemoryImageStore *memoryStore;
static id MemorySharedStore(id self, SEL _cmd) { return memoryStore; }

static FlycutClipping *ImageClipping(NSString *hash, NSString *type) {
    return [[[FlycutClipping alloc] initWithImageHash:hash withImageSize:NSMakeSize(2, 2) withImageType:type
        withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:0] autorelease];
}

@interface ImageTarget : NSObject
@property NSInteger activations;
@end
@implementation ImageTarget
- (pid_t)processIdentifier { return 4242; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { self.activations++; return YES; }
@end

@interface ImageOperator : NSObject
@property(retain) NSMutableArray *clippings;
@end
@implementation ImageOperator
- (BOOL)setStackPositionToFirstItem { return YES; }
- (BOOL)restoreStashedStore { return NO; }
- (FlycutClipping *)clippingAtStackPosition { return [self.clippings count] ? self.clippings[0] : nil; }
// The real operator answers an image clipping's empty contents; pasting that would be wrong.
- (NSString *)getPasteFromStackPosition { return [self.clippings count] ? [self.clippings[0] contents] : nil; }
- (NSString *)getPasteFromIndex:(int)i { return [self.clippings[i] contents]; }
- (int)jcListCount { return (int)[self.clippings count]; }
- (FlycutClipping *)clippingAtPosition:(int)i { return i >= 0 && i < (int)[self.clippings count] ? self.clippings[i] : nil; }
- (FlycutClipping *)clippingAtIndex:(int)i { return [self clippingAtPosition:i]; }
@end

@interface ImageController : AppController
@property(retain) ImageTarget *target;
@property NSInteger posts;
@property NSInteger hides;
@property(copy) NSData *postedImage;
@property(copy) NSString *postedFileURL;
- (void)prepare:(ImageBoard *)board operator:(ImageOperator *)op;
- (BOOL)ownsTransaction;
@end
@implementation ImageController
- (void)prepare:(ImageBoard *)board operator:(ImageOperator *)op {
    jcPasteboard = (id)[board retain]; flycutOperator = (id)[op retain];
}
- (BOOL)ownsTransaction { return currentPasteTransaction != nil; }
- (NSRunningApplication *)frontmostApplicationForPaste { return (id)self.target; }
- (void)showBezel { isBezelDisplayed = YES; }
- (void)hideApp { self.hides++; isBezelDisplayed = NO; isBezelPinned = NO; }
- (void)updateMenu {}
- (void)fakeCommandV { abort(); }
- (BOOL)postCommandVToProcessIdentifier:(pid_t)pid {
    self.posts++;
    self.postedImage = [jcPasteboard dataForType:NSPasteboardTypePNG];
    self.postedFileURL = [jcPasteboard stringForType:NSPasteboardTypeFileURL];
    return YES;
}
@end

@interface AddedTarget : NSObject
@end
@implementation AddedTarget
- (void)clippingWasAdded {}
@end

static NSEvent *Escape(void) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
        windowNumber:0 context:nil characters:@"" charactersIgnoringModifiers:@"" isARepeat:NO keyCode:53];
}

static int CaptureFollowsSelection(void) {
    // Real operator and store; only image files are kept in memory.
    [[NSUserDefaults standardUserDefaults] setObject:@0 forKey:@"savePreference"];
    FlycutOperator *op = [[FlycutOperator alloc] init];
    AddedTarget *added = [[AddedTarget new] autorelease];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(clippingWasAdded) forTarget:added];
    for (NSString *text in @[@"oldest", @"chosen", @"newest"])
        [op addClipping:text ofType:NSPasteboardTypeString fromApp:@"Fixture" withAppBundleURL:nil
                 target:added clippingAddedSelector:@selector(clippingWasAdded)];
    if (![op setStackPositionTo:1] || ![[[op clippingAtPosition:[op stackPosition]] contents] isEqual:@"chosen"]) return 70;
    bool stored = [op addImageClipping:[@"png bytes" dataUsingEncoding:NSUTF8StringEncoding] fromApp:@"Fixture"
        withAppBundleURL:nil imageType:NSPasteboardTypePNG target:added clippingAddedSelector:@selector(clippingWasAdded)];
    if (!stored || ![[op clippingAtPosition:0] isImageClipping]) return 71;
    FlycutClipping *selected = [op clippingAtPosition:[op stackPosition]];
    if (![[selected contents] isEqual:@"chosen"]) {
        fprintf(stderr, "image capture moved the bezel selection to position %d\n", [op stackPosition]);
        return 72;
    }
    printf("PASS image capture keeps selection\n");
    return 0;
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]);
    memoryStore = [MemoryImageStore new];
    memoryStore.gifPath = @"/nonexistent/flycut-test/animated.gif";
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)), (IMP)MemorySharedStore);
    if ([mode isEqual:@"capture-follows-selection"]) return CaptureFollowsSelection();

    NSData *png = [@"png bytes" dataUsingEncoding:NSUTF8StringEncoding];
    if (![mode isEqual:@"missing-data"]) memoryStore.images[@"A"] = png;
    memoryStore.images[@"B"] = [@"other png" dataUsingEncoding:NSUTF8StringEncoding];
    ImageBoard *board = [[ImageBoard new] autorelease];
    [board declareTypes:nil owner:nil]; [board setString:@"original" forType:NSPasteboardTypeString];
    ImageOperator *op = [[ImageOperator new] autorelease];
    NSString *type = [mode isEqual:@"bezel-gif"] ? @"com.compuserve.gif" : NSPasteboardTypePNG;
    op.clippings = [NSMutableArray arrayWithObject:ImageClipping(@"A", type)];
    ImageController *c = [[ImageController new] autorelease];
    c.target = [[ImageTarget new] autorelease];
    [c prepare:board operator:op];

    if ([mode isEqual:@"menu-image-deleted"]) {
        [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"menuSelectionPastes"];
        NSMenuItem *item = [[[NSMenuItem alloc] initWithTitle:@"[Image 2x2]" action:nil keyEquivalent:@""] autorelease];
        [item setRepresentedObject:@[@0, op.clippings[0]]];
        // The clicked image is gone; a different image (equal empty contents) is now listed.
        op.clippings = [NSMutableArray arrayWithObject:ImageClipping(@"B", NSPasteboardTypePNG)];
        [c processMenuClippingSelection:item];
    } else {
        [c hitMainHotKey:nil];
        [c metaKeysReleased];
        if ([mode isEqual:@"escape"]) [c processBezelKeyDown:Escape()];
        if ([mode isEqual:@"external"]) { [board declareTypes:nil owner:nil]; [board setString:@"external copy" forType:NSPasteboardTypeString]; }
    }
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];

    if ([mode isEqual:@"bezel-image"]) {
        if (c.posts != 1 || ![c.postedImage isEqual:png]) { fprintf(stderr, "image paste: posts=%ld image=%d\n", (long)c.posts, [c.postedImage isEqual:png]); return 11; }
        if ([c ownsTransaction] || c.target.activations != 1) return 12;
    } else if ([mode isEqual:@"bezel-gif"]) {
        NSString *expected = [[NSURL fileURLWithPath:memoryStore.gifPath] absoluteString];
        if (c.posts != 1 || ![c.postedFileURL isEqual:expected]) { fprintf(stderr, "gif paste: posts=%ld url=%s\n", (long)c.posts, [c.postedFileURL UTF8String]); return 21; }
        if ([board dataForType:NSPasteboardTypePNG] != nil) return 22; // GIFs stay a file reference only.
    } else if ([mode isEqual:@"escape"]) {
        if (c.posts != 0) return 31;
        if (![[board stringForType:NSPasteboardTypeString] isEqual:@"original"] || [board dataForType:NSPasteboardTypePNG]) {
            fprintf(stderr, "Escape did not restore the clipboard the image selection replaced\n"); return 32;
        }
        if ([c ownsTransaction]) return 33;
    } else if ([mode isEqual:@"external"]) {
        if (c.posts != 0 || ![[board stringForType:NSPasteboardTypeString] isEqual:@"external copy"]) return 41;
    } else if ([mode isEqual:@"missing-data"]) {
        if (c.posts != 0 || ![[board stringForType:NSPasteboardTypeString] isEqual:@"original"]) return 51;
        if ([c ownsTransaction] || c.hides != 1) return 52;
    } else if ([mode isEqual:@"menu-image-deleted"]) {
        if (c.posts != 0 || [board dataForType:NSPasteboardTypePNG] != nil) {
            fprintf(stderr, "a deleted image menu row pasted a different image\n"); return 61;
        }
        if (![[board stringForType:NSPasteboardTypeString] isEqual:@"original"] || beeps != 1) return 62;
    } else return 3;
    printf("PASS image transaction %s\n", argv[1]);
    return 0;
} }
'''


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Unclosed method: {signature}")


class ImagePasteTransactionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'ImagePasteTransactionFixture',
                                   extra_flags=('-DNSBeep=FCTestNSBeep',))

    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_bezel_image_selection_pastes_through_the_transaction(self):
        self.check_mode('bezel-image')

    def test_bezel_gif_selection_pastes_its_file_reference(self):
        self.check_mode('bezel-gif')

    def test_escape_restores_the_clipboard_an_image_selection_replaced(self):
        self.check_mode('escape')

    def test_external_copy_after_image_placement_is_never_pasted_or_overwritten(self):
        self.check_mode('external')

    def test_missing_image_data_tears_down_without_pasting(self):
        self.check_mode('missing-data')

    def test_deleted_image_menu_row_does_not_fall_back_to_another_image(self):
        self.check_mode('menu-image-deleted')

    def test_image_capture_keeps_the_bezel_selection_on_its_clipping(self):
        self.check_mode('capture-follows-selection')

    def test_image_capture_redraws_after_the_selection_settles(self):
        source = (ROOT / 'AppController.m').read_text()
        poll = method_body(source, '-(void)pollPB:(NSTimer *)timer')
        calls = re.findall(r'addImageClipping:[^;]*;', poll)
        self.assertTrue(calls, 'pollPB: no longer captures images')
        for call in calls:
            self.assertIn('clippingAddedSelector:@selector(clippingWasAdded)', call)

    def test_gif_download_capture_redraws_after_the_selection_settles(self):
        # The opt-in GIF download adds its clipping later, on the main queue. It must
        # redraw the settled bezel selection exactly like the direct image capture.
        source = (ROOT / 'AppController.m').read_text()
        download = method_body(source, '-(void)downloadAndCaptureGIFFromURL:(NSURL *)url '
                               'fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL\n{')
        calls = re.findall(r'addImageClipping:[^;]*;', download)
        self.assertTrue(calls, 'the GIF download no longer captures images')
        for call in calls:
            self.assertIn('clippingAddedSelector:@selector(clippingWasAdded)', call)


if __name__ == '__main__':
    unittest.main()
