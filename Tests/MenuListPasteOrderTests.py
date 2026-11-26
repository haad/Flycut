#!/usr/bin/env python3
"""Pasting from the menu-bar list orders the lists exactly as the bezel and the old menu did.

History rows paste through #7's store-position path (-pasteStorePositionAndUpdate:), so
with "Move pasted item to top" the clipping moves to the top of the history, also while
the bezel shows the favorites. A favorite pastes the way the bezel pastes the selected
favorite (-[AppController pasteFromStack] -> -[FlycutOperator getPasteFromStackPosition]
-> -getPasteFromIndex:; an image favorite takes pasteFromStack's image branch), and there
the favorites keep their order: pasteMovesToTop reorders the history only. The fixture
runs the bezel path and the list path on the same data and compares the results. Only
the user changes the order of the favorites: by a drag in the list or by VoiceOver's Move
Up and Move Down (the list's own controller, never opened), which Cmd-Z undoes; pasting
keeps that order.

The fixture compiles the real AppController, FlycutOperator and engine sources. Only OS
boundaries are replaced: FixtureIsolation.h keeps defaults in memory, the clipboard write
is recorded, no screen is queried, the paste completion is a no-op, the image store is an
empty in-memory stand-in, and any access to the general pasteboard or NSWorkspace aborts
the fixture. NSApp is
never created; no window is shown and no event is posted.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#import <string.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutImageStore.h"
#import "FlycutListPanel.h"
#import "FlycutClipList.h"

static id FCNoScreen(id object, SEL selector) { return nil; }
static id FCForbidden(id object, SEL selector) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: +[%s %s]\n", class_getName(object), sel_getName(selector));
    abort();
}

// Image files are an OS boundary: the bezel reads an image row's preview from this memory
// store (it holds nothing, so the preview is empty). Deleting an image file fails the fixture.
@interface FCMemoryImageStore : NSObject
@end
@implementation FCMemoryImageStore
- (NSData *)imageDataForHash:(NSString *)hash { return nil; }
- (NSString *)imageFilePathForHash:(NSString *)hash { return nil; }
- (BOOL)hasImageForHash:(NSString *)hash { return NO; }
- (void)deleteImageForHash:(NSString *)hash { fprintf(stderr, "fixture deleted an image file\n"); abort(); }
@end
static FCMemoryImageStore *gImageStore;
static id FCMemorySharedStore(id object, SEL selector) { return gImageStore; }

static void InstallBoundaries(BOOL movesToTop) {
    gImageStore = [[FCMemoryImageStore alloc] init];
    method_setImplementation(class_getClassMethod([NSScreen class], @selector(mainScreen)), (IMP)FCNoScreen);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([FlycutImageStore class], @selector(sharedStore)), (IMP)FCMemorySharedStore);
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setObject:@0 forKey:@"savePreference"];
    [defaults setObject:@NO forKey:@"saveForgottenClippings"];
    [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
    [defaults setObject:@NO forKey:@"stickyBezel"];
    [defaults setObject:@NO forKey:@"menuSelectionPastes"];   // copy only: nothing is pasted anywhere
    [defaults setObject:@(movesToTop) forKey:@"pasteMovesToTop"];
}

@interface AppController (MenuListPasteOrderTesting)
- (void)pasteFromStack;
- (void)processBezelKeyDown:(NSEvent *)event;
- (void)stackDown;
@end

@interface FlycutListController (MenuListPasteOrderTesting)
- (NSArray *)customActionsForRow:(FlycutClipListRow *)row atIndex:(NSInteger)index;
- (void)undo;
@end

@interface FCPasteTarget : NSObject
@end
@implementation FCPasteTarget
- (pid_t)processIdentifier { return 4242; }
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { return YES; }
@end

@interface FCOrderController : AppController {
    NSMutableArray *_placed;
    FCPasteTarget *_target;
}
- (void)installOperator:(FlycutOperator *)op;
- (NSArray *)placed;
- (BOOL)bezelDisplayed;
@end

@implementation FCOrderController
- (void)installOperator:(FlycutOperator *)op {
    flycutOperator = op;
    _placed = [[NSMutableArray alloc] init];
    _target = [[FCPasteTarget alloc] init];
}
- (NSArray *)placed { return _placed; }
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
- (void)fixtureClippingAdded {}
// OS boundary: clipboard writes are recorded.
- (void)addClipToPasteboard:(NSString *)text { [_placed addObject:text]; }
- (void)addClipToPasteboard:(NSString *)text withRichData:(NSDictionary *)richData { [_placed addObject:text]; }
- (BOOL)addImageClipToPasteboard:(FlycutClipping *)clipping {
    [_placed addObject:[@"<image:" stringByAppendingFormat:@"%@>", [clipping imageHash]]];
    return YES;
}
// OS boundary: the frontmost application and the paste completion.
- (NSRunningApplication *)frontmostApplicationForPaste { return (NSRunningApplication *)_target; }
- (void)hideAppForPasteTransaction:(id)transaction {}
- (void)completePasteInRememberedApplication:(id)transaction {}
- (BOOL)pasteboardIsOwnedByTransaction:(id)transaction { return YES; }
@end

static NSEvent *KeyEvent(unsigned short keyCode, NSString *characters) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0
                        windowNumber:0 context:nil characters:characters charactersIgnoringModifiers:characters
                           isARepeat:NO keyCode:keyCode];
}

static FlycutClipping *Image(NSString *hash) {
    return [[[FlycutClipping alloc] initWithImageHash:hash withImageSize:NSMakeSize(4, 4) withImageType:NSPasteboardTypePNG
                                    withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil
                                        withTimestamp:0] autorelease];
}

static NSString *Name(FlycutClipping *c) {
    return [c isImageClipping] ? [NSString stringWithFormat:@"<image:%@>", [c imageHash]] : [c contents];
}

static NSArray *Order(FlycutOperator *op, FlycutList list) {
    NSMutableArray *names = [NSMutableArray array];
    for (FlycutClipping *c in [op clippingsInList:list matching:nil]) [names addObject:Name(c)];
    return names;
}

static int Pos(FlycutOperator *op, NSString *ivar) { return [[op valueForKey:ivar] intValue]; }

// history: newest first; an entry "<image:x>" is an image clipping with hash x.
static FCOrderController *Make(NSArray *history, NSArray *favorites, FlycutOperator **outOp) {
    FCOrderController *controller = [[FCOrderController alloc] init];
    FlycutOperator *op = [[FlycutOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:controller];
    for (int pass = 0; pass < 2; pass++) {
        NSArray *names = pass == 0 ? history : favorites;
        FlycutStore *store = pass == 0 ? [op valueForKey:@"clippingStore"] : [op valueForKey:@"favoritesStore"];
        for (NSString *name in [names reverseObjectEnumerator]) {
            if ([name hasPrefix:@"<image:"])
                [store addClipping:Image([name substringWithRange:NSMakeRange(7, [name length] - 8)])];
            else
                [store addClipping:[[[FlycutClipping alloc] initWithContents:name withType:NSPasteboardTypeString withDisplayLength:40
                                        withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:0] autorelease]];
        }
    }
    [controller installOperator:op];
    *outOp = op;
    return controller;
}

static FlycutClipping *ClippingNamed(FlycutOperator *op, FlycutList list, NSString *name) {
    for (FlycutClipping *c in [op clippingsInList:list matching:nil]) if ([Name(c) isEqual:name]) return c;
    return nil;
}

static void ChooseInList(FCOrderController *controller, FlycutOperator *op, FlycutList list, NSString *name) {
    [(id<FlycutListControllerDelegate>)controller listController:nil didChooseClipping:ClippingNamed(op, list, name) inList:list];
}

// VoiceOver's custom action `actionName` on the row of the clipping `name`, as the list's
// row view offers it (-customActionsForRow:atIndex:).
static BOOL Perform(FlycutListController *list, NSString *name, NSString *actionName) {
    NSArray *rows = [[list clipList] rows];
    for (NSUInteger i = 0; i < [rows count]; i++) {
        FlycutClipListRow *row = [rows objectAtIndex:i];
        if (![Name([row clipping]) isEqual:name]) continue;
        for (NSAccessibilityCustomAction *action in [list customActionsForRow:row atIndex:(NSInteger)i])
            if ([[action name] isEqual:actionName]) return [action handler]();
        return NO;
    }
    return NO;
}

// The bezel: open it, switch to the favorites, move down `steps`, confirm with Return.
static void PasteFavoriteFromBezel(FCOrderController *controller, int steps) {
    [controller hitMainHotKey:nil];
    [controller processBezelKeyDown:KeyEvent(3, @"f")];
    for (int i = 0; i < steps; i++) [controller stackDown];
    [controller processBezelKeyDown:KeyEvent(36, @"\r")];
}

static int Expect(const char *what, id actual, id expected) {
    if ([actual isEqual:expected]) return 0;
    fprintf(stderr, "FAIL %s: %s, expected %s\n", what, [[actual description] UTF8String], [[expected description] UTF8String]);
    return 1;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        const char *mode = argv[1];
        BOOL movesToTop = strstr(mode, "no-move") == NULL;
        InstallBoundaries(movesToTop);
        int failures = 0;
        FlycutOperator *op = nil, *ref = nil;

        if (strcmp(mode, "history-row-bezel-favorites") == 0 || strcmp(mode, "history-image-row-bezel-favorites") == 0) {
            BOOL image = strstr(mode, "image") != NULL;
            NSArray *history = image ? @[@"h0", @"<image:i1>", @"h2"] : @[@"h0", @"h1", @"h2"];
            NSString *row = image ? @"<image:i1>" : @"h2";
            // Reference: the same history row while the bezel shows the history (no bezel open).
            FCOrderController *reference = Make(history, @[@"f0", @"f1"], &ref);
            ChooseInList(reference, ref, FlycutListHistory, row);
            // The bezel is open on the favorites with f1 selected; then a history row is chosen.
            FCOrderController *controller = Make(history, @[@"f0", @"f1"], &op);
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:KeyEvent(3, @"f")];
            [controller stackDown];
            if (![op favoritesStoreIsSelected] || ![controller bezelDisplayed]) { fprintf(stderr, "FAIL setup: bezel not on the favorites\n"); return 20; }
            int favoritesSelection = [op stackPosition];
            ChooseInList(controller, op, FlycutListHistory, row);
            NSArray *moved = image ? @[@"<image:i1>", @"h0", @"h2"] : @[@"h2", @"h0", @"h1"];
            failures += Expect("reference history order (bezel on the history)", Order(ref, FlycutListHistory), moved);
            failures += Expect("history order while the bezel shows the favorites", Order(op, FlycutListHistory), moved);
            failures += Expect("same order as with the bezel on the history", Order(op, FlycutListHistory), Order(ref, FlycutListHistory));
            failures += Expect("favorites untouched", Order(op, FlycutListFavorites), @[@"f0", @"f1"]);
            failures += Expect("placed clipping", [controller placed], @[row]);
            failures += Expect("bezel still shows the favorites", @([op favoritesStoreIsSelected]), @YES);
            failures += Expect("bezel keeps its favorites selection", @([op stackPosition]), @(favoritesSelection));
            failures += Expect("history stack position as with the bezel on the history",
                               @(Pos(op, @"stashedStackPosition")), @([ref stackPosition]));
        } else if (strcmp(mode, "history-row-no-move-bezel-favorites") == 0) {
            FCOrderController *controller = Make(@[@"h0", @"h1", @"h2"], @[@"f0"], &op);
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:KeyEvent(3, @"f")];
            ChooseInList(controller, op, FlycutListHistory, @"h2");
            failures += Expect("history order without pasteMovesToTop", Order(op, FlycutListHistory), (@[@"h0", @"h1", @"h2"]));
            failures += Expect("placed clipping", [controller placed], @[@"h2"]);
        } else if (strcmp(mode, "favorite-row-like-bezel") == 0 || strcmp(mode, "favorite-row-no-move-like-bezel") == 0 ||
                   strcmp(mode, "favorite-image-like-bezel") == 0) {
            BOOL image = strstr(mode, "image") != NULL;
            NSArray *favorites = image ? @[@"f0", @"<image:i1>", @"f2"] : @[@"f0", @"f1", @"f2"];
            NSString *row = favorites[1];
            FCOrderController *bezel = Make(@[@"h0", @"h1"], favorites, &ref);
            PasteFavoriteFromBezel(bezel, 1);
            if ([ref favoritesStoreIsSelected]) { fprintf(stderr, "FAIL setup: the bezel paste left the favorites selected\n"); return 21; }
            FCOrderController *list = Make(@[@"h0", @"h1"], favorites, &op);
            ChooseInList(list, op, FlycutListFavorites, row);
            // The favorites keep their order, with or without pasteMovesToTop.
            failures += Expect("bezel: favorites order after pasting the second favorite", Order(ref, FlycutListFavorites), favorites);
            failures += Expect("list: favorites order after pasting the same favorite", Order(op, FlycutListFavorites), favorites);
            failures += Expect("list order equals the bezel's", Order(op, FlycutListFavorites), Order(ref, FlycutListFavorites));
            failures += Expect("history untouched", Order(op, FlycutListHistory), (@[@"h0", @"h1"]));
            failures += Expect("bezel placed it", [bezel placed], @[row]);
            failures += Expect("list placed it", [list placed], @[row]);
            failures += Expect("the bezel still shows the history", @([op favoritesStoreIsSelected]), @NO);
            failures += Expect("the bezel's favorites selection stays on the favorite it pasted",
                               @(Pos(ref, @"favoritesStackPosition")), @1);
            failures += Expect("the list paste leaves the bezel's favorites selection",
                               @(Pos(op, @"favoritesStackPosition")), @0);
        } else if (strcmp(mode, "favorite-row-bezel-favorites") == 0) {
            FCOrderController *controller = Make(@[@"h0", @"h1"], @[@"f0", @"f1", @"f2"], &op);
            [controller hitMainHotKey:nil];
            [controller processBezelKeyDown:KeyEvent(3, @"f")];
            [controller stackDown];                      // the bezel's selection: f1
            ChooseInList(controller, op, FlycutListFavorites, @"f2");
            failures += Expect("favorites order", Order(op, FlycutListFavorites), (@[@"f0", @"f1", @"f2"]));
            failures += Expect("history untouched", Order(op, FlycutListHistory), (@[@"h0", @"h1"]));
            failures += Expect("placed clipping", [controller placed], @[@"f2"]);
            failures += Expect("bezel still shows the favorites", @([op favoritesStoreIsSelected]), @YES);
            failures += Expect("bezel keeps its favorites selection", @([op stackPosition]), @1);
        } else if (strcmp(mode, "favorite-order-set-by-hand") == 0) {
            // The list's controller and model on the real operator (never opened, no window).
            FCOrderController *app = Make(@[@"h0", @"h1"], @[@"f0", @"f1", @"f2"], &op);
            FlycutListController *list = [[[FlycutListController alloc] initWithOperator:op delegate:(id)app] autorelease];
            FlycutClipList *model = [list clipList];
            [model beginSession];
            [model reload];
            ChooseInList(app, op, FlycutListFavorites, @"f2");
            [model reload];
            failures += Expect("a pasted favorite row keeps its place", Order(op, FlycutListFavorites), (@[@"f0", @"f1", @"f2"]));
            // A drag goes through the table's drop, -[FlycutClipList dropClipping:aboveRow:].
            failures += Expect("drag f2 above f0", @([model dropClipping:ClippingNamed(op, FlycutListFavorites, @"f2") aboveRow:0]), @YES);
            failures += Expect("order after the drag", Order(op, FlycutListFavorites), (@[@"f2", @"f0", @"f1"]));
            ChooseInList(app, op, FlycutListFavorites, @"f1");
            [model reload];
            failures += Expect("a paste keeps the dragged order", Order(op, FlycutListFavorites), (@[@"f2", @"f0", @"f1"]));
            failures += Expect("VoiceOver Move Down on f2", @(Perform(list, @"f2", @"Move Down")), @YES);
            failures += Expect("order after Move Down", Order(op, FlycutListFavorites), (@[@"f0", @"f2", @"f1"]));
            failures += Expect("VoiceOver Move Up on f1", @(Perform(list, @"f1", @"Move Up")), @YES);
            failures += Expect("order after Move Up", Order(op, FlycutListFavorites), (@[@"f0", @"f1", @"f2"]));
            ChooseInList(app, op, FlycutListFavorites, @"f2");
            [model reload];
            failures += Expect("a paste keeps the moved order", Order(op, FlycutListFavorites), (@[@"f0", @"f1", @"f2"]));
            [list undo];
            failures += Expect("Cmd-Z undoes Move Up", Order(op, FlycutListFavorites), (@[@"f0", @"f2", @"f1"]));
            [list undo];
            failures += Expect("Cmd-Z undoes Move Down", Order(op, FlycutListFavorites), (@[@"f2", @"f0", @"f1"]));
            [list undo];
            failures += Expect("Cmd-Z undoes the drag", Order(op, FlycutListFavorites), (@[@"f0", @"f1", @"f2"]));
            failures += Expect("history untouched", Order(op, FlycutListHistory), (@[@"h0", @"h1"]));
            failures += Expect("placed clippings", [app placed], (@[@"f2", @"f1", @"f2"]));
            [model endSession];
        } else {
            return 3;
        }
        printf("%s: %s\n", mode, failures ? "FAIL" : "PASS");
        return failures ? 10 : 0;
    }
}
'''

MODES = {
    "history-row-bezel-favorites":
        "a history row chosen while the bezel shows the favorites was not moved to the top as with the bezel on the history",
    "history-image-row-bezel-favorites":
        "a history image row chosen while the bezel shows the favorites was not moved to the top",
    "history-row-no-move-bezel-favorites": "without pasteMovesToTop a history row must stay in place",
    "favorite-row-like-bezel": "a favorite pasted from the list or the bezel moved; favorites keep their order",
    "favorite-row-no-move-like-bezel": "without pasteMovesToTop a favorite must stay in place, as in the bezel",
    "favorite-image-like-bezel": "an image favorite must stay in place, as in the bezel",
    "favorite-row-bezel-favorites": "a favorite pasted while the bezel shows the favorites moved or moved the selection",
    "favorite-order-set-by-hand":
        "a paste changed the order set by a drag or Move Up/Down, or those did not reorder or undo",
}


def fixture_sources() -> list[pathlib.Path]:
    try:
        listed = subprocess.check_output(["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True,
                                         stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError):
        listed = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.m")]
    return [ROOT / path for path in sorted(listed)
            if path != "main.m" and not path.startswith("FlycutHelper/") and not path.startswith("Tests/")]


class MenuListPasteOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-menu-list-paste-order-")
        cls.addClassCleanup(cls.directory.cleanup)
        temp = pathlib.Path(cls.directory.name)
        source = temp / "MenuListPasteOrderFixture.m"
        cls.binary = temp / "MenuListPasteOrderFixture"
        source.write_text(FIXTURE)
        sources = fixture_sources()
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include_dir in sorted({ROOT, ROOT / "Tests" / "Fixtures", *(path.parent for path in sources)}):
            command.extend(["-I", str(include_dir)])
        command.extend(str(path) for path in sources)
        command.append(str(source))
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command.extend(["-framework", framework])
        command.extend(["-o", str(cls.binary)])
        cls.build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)

    def run_mode(self, mode: str) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-4000:])
        run = subprocess.run([str(self.binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, f"{MODES[mode]}; exit={run.returncode}\n{run.stdout}{run.stderr}")

    def test_history_row_moves_to_top_while_the_bezel_shows_favorites(self) -> None:
        self.run_mode("history-row-bezel-favorites")

    def test_history_image_row_moves_to_top_while_the_bezel_shows_favorites(self) -> None:
        self.run_mode("history-image-row-bezel-favorites")

    def test_history_row_stays_without_paste_moves_to_top(self) -> None:
        self.run_mode("history-row-no-move-bezel-favorites")

    def test_favorite_row_keeps_its_place_like_the_bezel(self) -> None:
        self.run_mode("favorite-row-like-bezel")

    def test_favorite_row_stays_without_paste_moves_to_top_like_the_bezel(self) -> None:
        self.run_mode("favorite-row-no-move-like-bezel")

    def test_image_favorite_stays_in_place_like_the_bezel(self) -> None:
        self.run_mode("favorite-image-like-bezel")

    def test_favorite_row_keeps_its_place_while_the_bezel_shows_favorites(self) -> None:
        self.run_mode("favorite-row-bezel-favorites")

    def test_pasting_keeps_the_order_set_by_drag_and_move_actions_and_undo_restores(self) -> None:
        self.run_mode("favorite-order-set-by-hand")


if __name__ == "__main__":
    unittest.main(verbosity=2)
