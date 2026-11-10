#!/usr/bin/env python3
"""Displayed search rows retain identity across in-flight store mutations."""
import unittest
from PasteNativeTestSupport import build_fixture, run_fixture

FIXTURE = r'''
#include "PasteTestEnvironmentImplementation.h"
#import "AppController.h"
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
- (void)updateMenu {}
- (void)hideSearchWindowPreservingPasteTransaction {}
- (void)hideSearchWindow {}
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
    [controller prepare:op query:[mode isEqual:@"filtered"] ? @"same" : @""];
    [controller updateSearchResults];
    if ([mode isEqual:@"deleted"]) [op.clippings removeObjectAtIndex:1];
    else [op.clippings insertObject:clip(@"same title\nin-flight arrival") atIndex:0];
    [controller searchWindowItemSelected:nil];
    BOOL correct = [mode isEqual:@"deleted"] ? controller.placed == nil : [controller.placed isEqual:@"same title\nB"];
    if (!correct) { fprintf(stderr,"selected displayed identity B redirected: %s\n",[controller.placed UTF8String]); return 11; }
    printf("PASS search identity %s\n", argv[1]);
    [controller release]; [op release];
    return 0;
} }
'''
class SearchRowIdentityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_fixture(FIXTURE, 'SearchRowIdentityFixture')
    def check_mode(self, mode):
        run = run_fixture(self.binary, mode)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
    def test_inflight_insert_does_not_redirect_displayed_row(self):
        self.check_mode('insert')
    def test_filtered_row_keeps_identity_when_a_matching_clipping_arrives(self):
        self.check_mode('filtered')
    def test_deleted_identity_does_not_fall_back_to_same_looking_title(self):
        self.check_mode('deleted')
if __name__ == '__main__':
    unittest.main()
