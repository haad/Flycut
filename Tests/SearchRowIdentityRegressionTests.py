#!/usr/bin/env python3
"""Displayed search rows retain identity across in-flight store mutations; a Return that pastes
nothing (the row is gone, nothing matches, no paste target) beeps once; a row chosen while
Flycut's own window was in front when the search window opened is copied, without a beep; with
Preferences open behind another application, which is in front, the row is pasted there."""
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
static int beeps;
void FCTestNSBeep(void) { beeps++; }
#import "AppController.h"
@interface AppController (SearchOwnWindow)
- (void)rememberFrontmostApplicationForPaste;
@end
// Flycut's Preferences window, shown.
@interface FCShownWindow : NSObject
@end
@implementation FCShownWindow
- (BOOL)isVisible { return YES; }
@end
// Another application, in front when the search window opens.
@interface FCOtherApp : NSObject
@end
@implementation FCOtherApp
- (pid_t)processIdentifier { return 4242; }
- (BOOL)isTerminated { return NO; }
@end
static BOOL otherAppInFront, pasteScheduled;
@interface AppController (SearchPaste)
- (void)completePasteInRememberedApplication:(id)transaction;
@end
@interface FCSearchOperator : NSObject
@property(retain) NSMutableArray *clippings;
@end
@implementation FCSearchOperator
- (int)jcListCount { return (int)[self.clippings count]; }
- (FlycutClipping *)clippingAtPosition:(int)i { return self.clippings[i]; }
// The image-aware store-position paste looks the clipping up through this accessor.
- (FlycutClipping *)clippingAtIndex:(int)i { return self.clippings[i]; }
- (NSString *)getPasteFromIndex:(int)i { return [self.clippings[i] contents]; }
- (NSArray *)previousIndexes:(int)limit containing:(NSString *)query {
    NSMutableArray *rows = [NSMutableArray array];
    for (NSUInteger i=0; i<[self.clippings count] && [rows count]<(NSUInteger)limit; i++)
        if (![query length] || [[[self.clippings objectAtIndex:i] contents] containsString:query])
            [rows addObject:@(i)];
    return rows;
}
- (NSArray *)previousDisplayStrings:(int)limit containing:(NSString *)query {
    NSMutableArray *rows = [NSMutableArray array];
    for (NSNumber *i in [self previousIndexes:limit containing:query])
        [rows addObject:[self.clippings[[i intValue]] displayString]];
    return rows;
}
// #4 reads a clipping's rich text (RTF/HTML) before its text; this fixture's
// clippings are plain text, so there is none.
- (NSDictionary *)getRichDataFromStackPosition { return nil; }
- (NSDictionary *)getRichDataFromIndex:(int)index { (void)index; return nil; }
@end
@interface FCSearchField : NSObject
@property(copy) NSString *stringValue;
@end
@implementation FCSearchField
@end
@interface FCSearchTable : NSObject
@end
@implementation FCSearchTable
- (NSInteger)selectedRow { return 1; }
- (NSInteger)clickedRow { return 1; }
- (void)reloadData {}
- (void)selectRowIndexes:(id)indexes byExtendingSelection:(BOOL)extend {}
@end
@interface FCSearchController : AppController
@property(copy) NSString *placed;
- (void)prepare:(FCSearchOperator *)op query:(NSString *)query;
@end
@implementation FCSearchController
- (void)prepare:(FCSearchOperator *)op query:(NSString *)query {
    flycutOperator = (id)[op retain];
    searchWindowTableView = (id)[FCSearchTable new];
    FCSearchField *field = [FCSearchField new]; field.stringValue = query;
    searchWindowSearchField = (id)field;
}
- (void)addClipToPasteboard:(NSString *)text { self.placed = text; }
// #4 writes text with its rich data through the two-argument variant; the
// clipboard write stays this fixture's recorded boundary.
- (void)addClipToPasteboard:(NSString *)content withRichData:(NSDictionary *)richData {
    (void)richData;
    [self addClipToPasteboard:content];
}

- (void)updateMenu {}
- (void)hideSearchWindowPreservingPasteTransaction {}
- (void)hideSearchWindow {}
// The application in front when the search window opens: Flycut itself (its Preferences), or
// another application (prefs-behind).
- (NSRunningApplication *)frontmostApplicationForPaste {
    return otherAppInFront ? (NSRunningApplication *)[[FCOtherApp new] autorelease] : [NSRunningApplication currentApplication];
}
// The paste into the remembered application is scheduled, not run.
- (void)performSelector:(SEL)selector withObject:(id)object afterDelay:(NSTimeInterval)delay {
    (void)object; (void)delay;
    if (selector == @selector(completePasteInRememberedApplication:)) pasteScheduled = YES;
}
- (void)fakeCommandV { abort(); }
@end
static FlycutClipping *clip(NSString *text) {
    return [[[FlycutClipping alloc] initWithContents:text withType:NSPasteboardTypeString
        withDisplayLength:40 withAppLocalizedName:@"Fixture" withAppBundleURL:nil
        withTimestamp:0] autorelease];
}
int main(int argc, const char **argv) { @autoreleasepool {
    NSString *mode = @(argv[1]);
    FCSearchOperator *op = [FCSearchOperator new];
    op.clippings = [NSMutableArray arrayWithArray:@[clip(@"same title\nA"),clip(@"same title\nB"),clip(@"other")]];
    FCSearchController *controller = [FCSearchController new];
    [controller prepare:op query:[mode isEqual:@"filtered"] ? @"same" : [mode isEqual:@"no-match"] ? @"no such clipping" : @""];
    [controller updateSearchResults];
    if ([mode isEqual:@"own-window"] || [mode isEqual:@"prefs-behind"]) [controller setValue:[[FCShownWindow new] autorelease] forKey:@"prefsPanel"];
    otherAppInFront = [mode isEqual:@"prefs-behind"];
    if ([mode isEqual:@"own-window"] || [mode isEqual:@"flycut-windowless"] || [mode isEqual:@"prefs-behind"])
        [controller rememberFrontmostApplicationForPaste];
    if ([mode isEqual:@"deleted"]) [op.clippings removeObjectAtIndex:1];
    else [op.clippings insertObject:clip(@"same title\nin-flight arrival") atIndex:0];
    [controller searchWindowItemSelected:nil];
    BOOL nothing = [mode isEqual:@"deleted"] || [mode isEqual:@"no-match"];
    BOOL correct = nothing ? controller.placed == nil : [controller.placed isEqual:@"same title\nB"];
    if (!correct) { fprintf(stderr,"selected displayed identity B redirected: %s\n",[controller.placed UTF8String]); return 11; }
    // This fixture opens no paste transaction, so a placed row ends with that line and its beep.
    if (beeps != (([mode isEqual:@"own-window"] || [mode isEqual:@"flycut-windowless"] || [mode isEqual:@"prefs-behind"]) ? 0 : 1)) { fprintf(stderr,"%d beep(s) for mode %s\n",beeps,argv[1]); return 12; }
    // Pasted into the application in front, not copied only.
    if ([mode isEqual:@"prefs-behind"] && !pasteScheduled) { fprintf(stderr,"no paste was scheduled\n"); return 13; }
    printf("PASS search identity %s\n", argv[1]);
    [controller release]; [op release];
    return 0;
} }
'''
class SearchRowIdentityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'SearchRowIdentityFixture', ('-DNSBeep=FCTestNSBeep',))
    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
    def test_inflight_insert_does_not_redirect_displayed_row(self):
        self.check_mode('insert')
    def test_filtered_row_keeps_identity_when_a_matching_clipping_arrives(self):
        self.check_mode('filtered')
    def test_deleted_identity_does_not_fall_back_to_same_looking_title(self):
        self.check_mode('deleted')
    def test_a_row_chosen_over_flycuts_own_window_is_copied_without_a_beep(self):
        run = run_fixture(self.binary, 'own-window')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        line = 'Search window: no other application is in front, so the clipping is copied, not pasted'
        self.assertEqual(run.stderr.count(line), 1, run.stderr[-2000:])
    def test_a_row_chosen_with_flycut_in_front_but_no_window_is_pasted_as_before(self):
        run = run_fixture(self.binary, 'flycut-windowless')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        line = 'Search window: no other application is in front, so the clipping is copied, not pasted'
        self.assertEqual(run.stderr.count(line), 0, run.stderr[-2000:])
    def test_a_row_chosen_with_preferences_open_behind_another_app_is_pasted(self):
        run = run_fixture(self.binary, 'prefs-behind')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        line = 'Search window: no other application is in front, so the clipping is copied, not pasted'
        self.assertEqual(run.stderr.count(line), 0, run.stderr[-2000:])
    def test_return_without_a_matching_row_pastes_nothing_and_beeps(self):
        self.check_mode('no-match')
if __name__ == '__main__':
    unittest.main()
