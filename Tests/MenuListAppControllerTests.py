#!/usr/bin/env python3
"""The status item opens the menu-bar list; AppController wires it to paste and commands.

The native fixture compiles the real controller and engine with UI and preferences
isolated (PasteNativeTestSupport: in-memory defaults, NSApp nil), a fake operator
with two lists, and a recording controller subclass at the clipboard and paste
boundaries. NSBeep is redirected to a counter. Nothing is shown, posted or pasted.
"""
from __future__ import annotations

import pathlib
import re
import unittest
import xml.etree.ElementTree as ET

from PasteNativeTestSupport import build_fixture, run_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONTROLLER = ROOT / "AppController.m"
HEADER = ROOT / "AppController.h"
XIB = ROOT / "English.lproj" / "MainMenu.xib"
PROJECT = ROOT / "Flycut.xcodeproj" / "project.pbxproj"

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import "AppController.h"
#import "FlycutListPanel.h"

static int gBeeps;
void FCFixtureBeep(void) { gBeeps++; }

@interface AppController (MenuListTesting)
- (NSArray *)listCommandItems;
- (void)updateSearchResults;
- (void)rememberFrontmostApplicationForPaste;
@end

@interface FCListTarget : NSObject
@end
@implementation FCListTarget
- (pid_t)processIdentifier { return 101; }
- (BOOL)isTerminated { return NO; }
@end

// Two lists; like FlycutOperator, the "current" store (the bezel's) is the history unless
// the favorites are selected, and the position-based calls work on the current store.
@interface FCListOperator : NSObject
@property(retain) NSMutableArray *history;
@property(retain) NSMutableArray *favorites;
@property(assign) int getPasteCalls;
@property(assign) BOOL favoritesSelected;
@end
@implementation FCListOperator
- (NSMutableArray *)list:(FlycutList)list { return list == FlycutListFavorites ? self.favorites : self.history; }
- (NSMutableArray *)current { return self.favoritesSelected ? self.favorites : self.history; }
- (int)indexOfClipping:(FlycutClipping *)c inList:(FlycutList)list {
    NSUInteger i = [[self list:list] indexOfObjectIdenticalTo:c];
    return i == NSNotFound ? -1 : (int)i;
}
- (bool)favoritesStoreIsSelected { return self.favoritesSelected; }
- (void)toggleToFromFavoritesStore { self.favoritesSelected = !self.favoritesSelected; }
- (int)jcListCount { return (int)[[self current] count]; }
- (FlycutClipping *)clippingAtIndex:(int)i { return [self current][i]; }
- (FlycutClipping *)clippingAtPosition:(int)i { return i >= 0 && i < (int)[[self current] count] ? [self current][i] : nil; }
- (NSDictionary *)getRichDataFromIndex:(int)i { return [[self current][i] richData]; }
- (NSString *)getPasteFromIndex:(int)i { self.getPasteCalls += 1; return [[self current][i] contents]; }
- (NSArray *)previousIndexes:(int)limit containing:(NSString *)query {
    NSMutableArray *rows = [NSMutableArray array];
    for (NSUInteger i = 0; i < [self.history count] && [rows count] < (NSUInteger)limit; i++)
        if (![query length] || [[self.history[i] contents] containsString:query]) [rows addObject:@(i)];
    return rows;
}
- (bool)storeDisabled { return NO; }
@end

@interface FCListController : AppController
@property(assign) int storePosition;
@property(copy) NSString *placedText;
@property(retain) NSDictionary *placedRich;
@property(retain) FlycutClipping *placedImage;
@property(assign) int remembered, polls, clears;
@property(retain) id completed, hidden;
@end
@implementation FCListController
- (bool)pasteStorePositionAndUpdate:(int)position { self.storePosition = position; return true; }
- (void)addClipToPasteboard:(NSString *)text withRichData:(NSDictionary *)rich { self.placedText = text; self.placedRich = rich; }
- (BOOL)addImageClipToPasteboard:(FlycutClipping *)clipping { self.placedImage = clipping; return YES; }
- (NSRunningApplication *)frontmostApplicationForPaste { return (NSRunningApplication *)[[FCListTarget new] autorelease]; }
- (void)rememberFrontmostApplicationForPaste { self.remembered += 1; [super rememberFrontmostApplicationForPaste]; }
- (void)hideAppForPasteTransaction:(id)transaction { self.hidden = transaction; }
- (void)completePasteInRememberedApplication:(id)transaction { self.completed = transaction; }
- (void)hideApp {}
- (void)pollPB:(NSTimer *)timer { self.polls += 1; }
- (IBAction)clearClippingList:(id)sender { self.clears += 1; }
- (void)updateMenu {}
- (id)transaction { return currentPasteTransaction; }
- (BOOL)menuOpen { return isMenuOpen; }
- (NSArray *)results { return searchResults; }
@end

static FlycutClipping *Clip(NSString *text) {
    FlycutClipping *c = [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:0] autorelease];
    [c setRichData:@{NSPasteboardTypeRTF: [text dataUsingEncoding:NSUTF8StringEncoding]}];
    return c;
}

static void Spin(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([until timeIntervalSinceNow] > 0) CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.02, true);
}

static int Fail(int code, NSString *why) { fprintf(stderr, "FAIL %d: %s\n", code, [why UTF8String]); return code; }

int main(int argc, const char **argv) { @autoreleasepool {
    NSString *mode = @(argv[1]);
    [NSApplication sharedApplication];
    FCListOperator *op = [[FCListOperator new] autorelease];
    op.history = [NSMutableArray arrayWithObjects:Clip(@"h0"), Clip(@"h1"), Clip(@"h2"), nil];
    op.favorites = [NSMutableArray arrayWithObjects:Clip(@"f0"), Clip(@"f1"), nil];
    FCListController *c = [[FCListController new] autorelease];
    [c setValue:op forKey:@"flycutOperator"];
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setBool:NO forKey:@"menuSelectionPastes"];

    if ([mode isEqual:@"display-num-default"]) {
        if ([defaults integerForKey:@"displayNum"] != 20) return Fail(10, @"displayNum default is not 20");
    } else if ([mode isEqual:@"history-row"]) {
        FlycutClipping *h1 = op.history[1];
        [op.history insertObject:Clip(@"arrived") atIndex:0];   // a capture landed meanwhile
        [c listController:nil didChooseClipping:h1 inList:FlycutListHistory];
        if (c.storePosition != 2) return Fail(11, [NSString stringWithFormat:@"pasted store position %d, not the row's clipping", c.storePosition]);
    } else if ([mode isEqual:@"favorite-row"]) {
        c.storePosition = -1;
        [c listController:nil didChooseClipping:op.favorites[1] inList:FlycutListFavorites];
        if (![c.placedText isEqual:@"f1"]) return Fail(12, @"favorite text not placed");
        if (![[c.placedRich objectForKey:NSPasteboardTypeRTF] isEqual:[@"f1" dataUsingEncoding:NSUTF8StringEncoding]]) return Fail(13, @"rich data lost");
        // As the bezel pastes a favorite: -getPasteFromIndex: on the favorites store (that
        // the favorites keep their order is pinned with the real operator in
        // MenuListPasteOrderTests).
        if (c.storePosition != -1) return Fail(14, @"a favorite went through the history's store-position path");
        if (op.getPasteCalls != 1) return Fail(15, @"a favorite did not paste through -getPasteFromIndex:");
        if (op.favoritesSelected) return Fail(28, @"the bezel's store was not switched back after the paste");
    } else if ([mode isEqual:@"favorite-image"]) {
        FlycutClipping *image = [[[FlycutClipping alloc] initWithImageHash:@"abc" withImageSize:NSMakeSize(4, 4) withImageType:NSPasteboardTypePNG
            withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil withTimestamp:0] autorelease];
        [op.favorites addObject:image];
        [c listController:nil didChooseClipping:image inList:FlycutListFavorites];
        if (c.placedImage != image) return Fail(16, @"favorite image not placed");
    } else if ([mode isEqual:@"gone-row"]) {
        c.storePosition = -1;
        [c listController:nil didChooseClipping:Clip(@"h1") inList:FlycutListHistory];
        if (c.storePosition != -1 || c.placedText != nil) return Fail(17, @"an equal-looking clipping was pasted instead of nothing");
        if (gBeeps != 1) return Fail(18, @"no beep for a row whose clipping is gone");
    } else if ([mode isEqual:@"paste-transaction"]) {
        [defaults setBool:YES forKey:@"menuSelectionPastes"];
        [c listController:nil didChooseClipping:op.history[0] inList:FlycutListHistory];
        id transaction = [c transaction];
        if (c.remembered != 1 || transaction == nil) return Fail(19, @"the paste target was not bound at selection");
        Spin(0.8);
        if (c.hidden != transaction || c.completed != transaction) return Fail(20, @"paste did not complete through the transaction");
    } else if ([mode isEqual:@"copy-only"]) {
        c.storePosition = -1;
        [c listController:nil didChooseClipping:op.history[0] inList:FlycutListHistory];
        Spin(0.8);
        if (c.remembered != 0 || c.completed != nil || c.storePosition != 0) return Fail(21, @"copy-only selection must not paste");
    } else if ([mode isEqual:@"open-close"]) {
        [c listControllerDidOpen:nil];
        if (![c menuOpen]) return Fail(22, @"capture not frozen while the list is open");
        if (c.polls != 0) return Fail(23, @"polled while open");
        [c listControllerDidClose:nil];
        if ([c menuOpen] || c.polls != 1) return Fail(24, @"capture not resumed with a catch-up poll on close");
    } else if ([mode isEqual:@"commands"]) {
        NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"Menu"] autorelease];
        NSMenuItem *search = [[[NSMenuItem alloc] initWithTitle:@"Search..." action:NULL keyEquivalent:@"f"] autorelease];
        [search setView:[[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 384, 34)] autorelease]];
        [menu addItem:search];
        NSMenuItem *edit = [[[NSMenuItem alloc] initWithTitle:@"Edit" action:NULL keyEquivalent:@""] autorelease];
        [edit setHidden:YES];
        [menu addItem:edit];
        [menu addItem:[NSMenuItem separatorItem]];
        NSMenuItem *clear = [menu addItemWithTitle:@"Clear All" action:@selector(clearClippingList:) keyEquivalent:@""];
        [clear setTarget:c];
        [menu addItemWithTitle:@"Merge All" action:@selector(mergeClippingList:) keyEquivalent:@""];
        [menu addItemWithTitle:@"Pause Clipboard Tracking" action:@selector(toggleClipboardTracking:) keyEquivalent:@""];
        [menu addItemWithTitle:@"Preferences\u2026" action:@selector(showPreferencePanel:) keyEquivalent:@","];
        [menu addItemWithTitle:@"About Flycut" action:NULL keyEquivalent:@""];
        [menu addItem:[NSMenuItem separatorItem]];
        [menu addItemWithTitle:@"Quit" action:@selector(terminate:) keyEquivalent:@""];
        [menu insertItem:[[[NSMenuItem alloc] initWithTitle:@"a clipping row" action:NULL keyEquivalent:@""] autorelease] atIndex:0];
        [c setValue:menu forKey:@"jcMenu"];
        NSMutableArray *titles = [NSMutableArray array];
        for (NSMenuItem *item in [c listCommandItems]) [titles addObject:[item isSeparatorItem] ? @"-" : [item title]];
        NSArray *expected = @[@"Clear All", @"Merge All", @"Pause Clipboard Tracking", @"Preferences\u2026", @"About Flycut", @"-", @"Quit"];
        if (![titles isEqual:expected]) return Fail(25, [titles description]);
        [c listController:nil didChooseCommand:clear];
        if (c.clears != 1) return Fail(26, @"a command row did not run its menu action");
    } else if ([mode isEqual:@"search-window-limit"]) {
        [defaults setObject:@2 forKey:@"displayNum"];
        [op.history addObjectsFromArray:@[Clip(@"h3"), Clip(@"h4")]];
        [c setValue:[[NSSearchField new] autorelease] forKey:@"searchWindowSearchField"];
        [c updateSearchResults];
        if ([[c results] count] != 5) return Fail(27, [NSString stringWithFormat:@"search window lists %lu, not all 5", (unsigned long)[[c results] count]]);
    } else return 3;
    printf("PASS %s\n", argv[1]);
    return 0;
} }
'''


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    while ";" in source[start:brace]:
        start = source.index(signature, start + len(signature))
        brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated method: {signature}")


class MenuListAppControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, "MenuListAppControllerFixture", ("-DNSBeep=FCFixtureBeep",))

    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_display_in_menu_defaults_to_twenty_rows(self):
        self.check_mode("display-num-default")

    def test_history_row_pastes_its_own_clipping_after_an_insert(self):
        self.check_mode("history-row")

    def test_favorite_row_pastes_text_and_rich_data_as_the_bezel_does(self):
        self.check_mode("favorite-row")

    def test_favorite_image_row_places_the_image(self):
        self.check_mode("favorite-image")

    def test_row_whose_clipping_is_gone_pastes_nothing(self):
        self.check_mode("gone-row")

    def test_selection_pastes_through_the_bound_paste_transaction(self):
        self.check_mode("paste-transaction")

    def test_copy_only_selection_does_not_paste(self):
        self.check_mode("copy-only")

    def test_open_list_freezes_capture_and_close_catches_up(self):
        self.check_mode("open-close")

    def test_command_rows_are_the_status_menu_commands(self):
        self.check_mode("commands")

    def test_search_window_lists_all_matches_not_display_num(self):
        self.check_mode("search-window-limit")

    def test_status_item_opens_the_list_instead_of_the_menu(self):
        body = method_body(APP_CONTROLLER.read_text(), "-(void)showStatusItemMenu")
        self.assertNotIn("popUpStatusItemMenu", body)
        self.assertIn("openBelowRect:", body)
        self.assertIn("[listController isOpen]", body)

    def test_status_menu_builds_no_clipping_rows_any_more(self):
        # The list replaced the status menu's clipping rows, their click handling and the
        # menu's own search box; jcMenu still supplies the command rows.
        code = APP_CONTROLLER.read_text() + HEADER.read_text()
        for gone in (r"\bupdateMenu\b", r"\bupdateMenuContaining:", r"\bprocessMenuClippingSelection:",
                     r"\bstorePositionForMenuItem:", r"\bsRetiredMenuClippingItems\b", r"\bjcMenuBaseItemsCount\b",
                     r"\bneedMenuUpdate\b", r"\bactivateSearchBox\b", r"\bsearchItems:", r"\bfakeUpArrow\b",
                     r"\bfakeDownArrow\b", r"\bmenuFirstResponder\b", r"-\s*\(void\)\s*controlTextDidChange:"):
            self.assertIsNone(re.search(gone, code), gone)
        # The list's rows keep #10's width cap for wide-glyph titles.
        title = method_body(APP_CONTROLLER.read_text(),
                            "- (NSString *)listController:(FlycutListController *)controller titleForClipping:")
        self.assertIn("menuTitleFittingWidth:", title)

    def test_display_in_menu_texts_describe_the_list_height_in_rows(self):
        # "Display in menu" is the list's height in rows now; the list holds every clipping.
        labels = method_body(APP_CONTROLLER.read_text(), "static NSString *FlycutGeneralRestoreLabel(NSString *key)")
        self.assertIn('@"displayNum": @"Restore default number of rows in the menu"', labels)
        stepper = next(e for e in ET.parse(XIB).getroot().iter("stepper") if e.get("id") == "473")
        self.assertEqual("Controls how many rows the menu shows before it scrolls; the menu lists all clippings",
                         stepper.get("toolTip"))

    def test_every_action_the_nib_sends_to_the_controller_is_implemented(self):
        # A control keeps its target/action from the nib; sending a selector the controller
        # no longer implements throws (unrecognized selector).
        root = ET.parse(XIB).getroot()
        controller = next(e for e in root.iter("customObject") if e.get("customClass") == "AppController")
        selectors = sorted({a.get("selector") for a in root.iter("action") if a.get("target") == controller.get("id")})
        self.assertIn("showPreferencePanel:", selectors)
        source = APP_CONTROLLER.read_text()
        for selector in selectors:
            name = re.escape(selector.split(":")[0])
            pattern = r"(?m)^\s*-\s*\(\s*(?:IBAction|void)\s*\)\s*" + name + r"\s*:"
            self.assertTrue(re.search(pattern, source), f"the nib sends {selector} to AppController, which lacks it")

    def test_status_menu_and_its_old_search_field_are_never_shown(self):
        # Master's compiled MainMenu.nib (what a build without Xcode ships) still connects
        # the old search field in jcMenu's "Search..." item to -searchItems:, which is gone.
        # The field exists only in that item's view, so it can send nothing as long as jcMenu
        # is never shown: the status item has no menu, nothing pops jcMenu up, the list's
        # commands start after its first separator (mode "commands"), and no code touches
        # the field (searchBox stays an outlet only).
        source = APP_CONTROLLER.read_text()
        code = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S)
        self.assertIn("[statusItem setMenu:nil];", method_body(source, "-(void)configureStatusItemInteraction"))
        for token in ("popUpStatusItemMenu", "popUpMenuPositioningItem", "popUpContextMenu", "popUpMenu:",
                      "trackMenu", ".menu =", "setMenu:jcMenu", "searchBox"):
            self.assertNotIn(token, code, token)
        self.assertEqual(re.findall(r"\bsetMenu:\s*([^\]\s]+)", code), ["nil"])
        sent = sorted(set(re.findall(r"\[\s*jcMenu\s+(\w+:?)", code)))
        self.assertEqual(["indexOfItemWithTarget:", "insertItem:", "itemArray", "numberOfItems", "setDelegate:"], sent)
        passed = sorted(set(re.findall(r"(\w+:)\s*jcMenu\b", code)))
        self.assertEqual(["menuDidClose:", "menuWillOpen:"], passed)

    def test_every_outlet_the_nib_connects_is_still_declared(self):
        # Loading MainMenu.nib sets these by key; a missing one throws at launch. The
        # search field of the old status menu (searchBox) stays in the nib.
        root = ET.parse(XIB).getroot()
        controller = next(e for e in root.iter("customObject") if e.get("customClass") == "AppController")
        outlets = sorted(o.get("property") for o in controller.iter("outlet"))
        self.assertIn("searchBox", outlets)
        header = HEADER.read_text()
        for name in outlets:
            self.assertRegex(header, r"IBOutlet\s+\w+\s*\*\s*" + re.escape(name) + r"\s*;", name)

    def test_new_sources_are_part_of_the_xcode_target(self):
        project = PROJECT.read_text()
        for name in ("FlycutListPanel.m", "FlycutClipList.m"):
            self.assertGreaterEqual(len(re.findall(re.escape(name), project)), 3, name)
            self.assertRegex(project, re.escape(name) + r" in Sources \*/,")
        for name in ("FlycutListPanel.h", "FlycutClipList.h"):
            self.assertGreaterEqual(len(re.findall(re.escape(name), project)), 2, name)


if __name__ == "__main__":
    unittest.main()
