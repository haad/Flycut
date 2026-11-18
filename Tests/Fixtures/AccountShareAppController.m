// Native fixture for AccountShareAppControllerTests.py.
//
// Compiles every app source (AppController, FlycutOperator, the account-share
// service) and the real engine through AccountShareTrace.h (traced mutations,
// simulated file owners), and runs two AppControllers as two simulated accounts,
// A = 7001 and B = 7002, each with its own FlycutOperator, an in-memory
// pasteboard and an account-share service on an injected scratch root. Copies go
// through the production -pollPB:, received clippings through the production
// delegate methods and -addClipToPasteboard:withRichData:.
//
// FixtureIsolation.h keeps defaults in memory; NSWorkspace is a stand-in; the
// general pasteboard, the status bar, the image store and the file-writing save
// end the fixture if reached. +[FlycutAccountShareService sharedRootPath] answers
// a decoy inside the injected root, and the trace refuses every write outside it,
// so nothing can be created under /Users/Shared. Clipping texts are dummy strings
// and are never printed.

#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#include <pwd.h>
#import "FixtureIsolation.h"
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutClipping.h"
#import "FlycutStore.h"
#include "AccountShareTrace.h"
#import "FlycutAccountShareService.h"

enum { kA = 7001, kB = 7002, kUnopted = 7003 };

@interface FCFakeApp : NSObject
@end
@implementation FCFakeApp
- (BOOL)isActive { return YES; }
- (NSString *)localizedName { return @"Example App"; }
- (NSURL *)bundleURL { return nil; }
@end

@interface FCFakeWorkspace : NSObject {
@public
    NSNotificationCenter *center;
}
@end
@implementation FCFakeWorkspace
- (id)init { if ((self = [super init])) center = [[NSNotificationCenter alloc] init]; return self; }
- (NSArray *)runningApplications { return @[[[[FCFakeApp alloc] init] autorelease]]; }
- (NSRunningApplication *)frontmostApplication { return nil; }
- (NSNotificationCenter *)notificationCenter { return center; }
@end

// An in-process pasteboard: generations, types, string/data per type.
@interface FCMemoryPasteboard : NSObject {
@public
    NSInteger changeCount;
    NSArray *types;
    NSMutableDictionary *values;
}
- (void)copyText:(NSString *)text;
@end
@implementation FCMemoryPasteboard
- (id)init {
    if ((self = [super init])) { changeCount = 100; types = [@[] retain]; values = [[NSMutableDictionary alloc] init]; }
    return self;
}
- (NSInteger)changeCount { return changeCount; }
- (NSArray *)types { return types; }
- (NSString *)availableTypeFromArray:(NSArray *)candidates {
    for (NSString *candidate in candidates) if ([types containsObject:candidate]) return candidate;
    return nil;
}
- (NSString *)stringForType:(NSString *)type { id v = values[type]; return [v isKindOfClass:[NSString class]] ? v : nil; }
- (NSData *)dataForType:(NSString *)type { id v = values[type]; return [v isKindOfClass:[NSData class]] ? v : nil; }
- (void)addType:(NSString *)type {
    if ([types containsObject:type]) return;
    NSArray *next = [[types arrayByAddingObject:type] retain]; [types release]; types = next;
}
- (NSInteger)declareTypes:(NSArray *)newTypes owner:(id)owner {
    changeCount++; [types release]; types = [newTypes copy]; [values removeAllObjects]; return changeCount;
}
- (NSInteger)clearContents { changeCount++; [types release]; types = [@[] retain]; [values removeAllObjects]; return changeCount; }
- (BOOL)setString:(NSString *)s forType:(NSString *)t { if (!s) return NO; values[t] = [[s copy] autorelease]; [self addType:t]; return YES; }
- (BOOL)setData:(NSData *)d forType:(NSString *)t { if (!d) return NO; values[t] = [[d copy] autorelease]; [self addType:t]; return YES; }
- (NSArray *)pasteboardItems { return @[]; }
- (BOOL)writeObjects:(NSArray *)objects { return NO; }
- (void)copyText:(NSString *)text {
    changeCount++; [types release]; types = [@[NSPasteboardTypeString] retain];
    [values removeAllObjects]; values[NSPasteboardTypeString] = text;
}
@end

@interface FCShareController : AppController {
@public
    int added;
}
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard;
- (void)drainCaptures;
- (NSNumber *)blockedGeneration;
- (void)waitForReadsLeavingCommitsQueued;
@end
@implementation FCShareController
- (void)installOperator:(FlycutOperator *)op pasteboard:(FCMemoryPasteboard *)pasteboard {
    flycutOperator = op;
    jcPasteboard = (id)pasteboard;
    pbCount = [[NSNumber numberWithInteger:pasteboard->changeCount] retain];
    pbBlockCount = [[NSNumber numberWithInt:0] retain];
}
- (void)drainCaptures {
    __block BOOL drained = NO;
    dispatch_async(clipboardReadQueue, ^{ dispatch_async(dispatch_get_main_queue(), ^{ drained = YES; }); });
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5.0];
    while (!drained && [limit timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}
- (NSNumber *)blockedGeneration { return pbBlockCount; }
// Every read queued so far ends while the main thread stays busy, so the commits they hand to the
// main queue wait, as when a read ends while Flycut handles the user's next key.
- (void)waitForReadsLeavingCommitsQueued { dispatch_sync(clipboardReadQueue, ^{}); }
- (void)clippingWasAdded { added++; [super clippingWasAdded]; }
- (void)updateMenuBarIcon { }
- (void)updateClipboardTrackingMenuItem { }
@end

@interface AppController (AccountShareTesting)
- (void)pollPB:(NSTimer *)timer;
- (void)setClipboardTrackingPaused:(BOOL)paused;
- (void)setUpAccountSharing;
- (void)accountSessionDidBecomeActive:(NSNotification *)notification;
- (IBAction)toggleShareClippingsAcrossAccounts:(id)sender;
@end

static FCFakeWorkspace *fakeWorkspace;
static id FCSharedWorkspace(id self, SEL _cmd) { return fakeWorkspace; }
static id FCNoScreen(id self, SEL _cmd) { return nil; }
static id FCForbidden(id self, SEL _cmd) {
    fprintf(stderr, "fixture touched a forbidden OS boundary: %s\n", sel_getName(_cmd));
    _exit(99);
}
static BOOL FCForbiddenSave(id self, SEL _cmd, id store, int index, id prefix) {
    fprintf(stderr, "fixture reached -saveFromStore:atIndex:withPrefix: (writes files)\n");
    _exit(98);
}

static void InstallBoundaries(void) {
    fakeWorkspace = [[FCFakeWorkspace alloc] init];
    method_setImplementation(class_getClassMethod([NSWorkspace class], @selector(sharedWorkspace)), (IMP)FCSharedWorkspace);
    method_setImplementation(class_getClassMethod([NSScreen class], @selector(mainScreen)), (IMP)FCNoScreen);
    method_setImplementation(class_getClassMethod([NSPasteboard class], @selector(generalPasteboard)), (IMP)FCForbidden);
    method_setImplementation(class_getClassMethod([NSStatusBar class], @selector(systemStatusBar)), (IMP)FCForbidden);
    Class imageStore = NSClassFromString(@"FlycutImageStore");
    method_setImplementation(class_getClassMethod(imageStore, NSSelectorFromString(@"sharedStore")), (IMP)FCForbidden);
    method_setImplementation(class_getInstanceMethod([FlycutOperator class], @selector(saveFromStore:atIndex:withPrefix:)),
                             (IMP)FCForbiddenSave);
}

static int Check(BOOL ok, const char *what) {
    printf("%s: %s\n", ok ? "PASS" : "FAIL", what);
    return ok ? 0 : 1;
}

static void Spin(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([until timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
}

static BOOL WaitFor(BOOL (^condition)(void), NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while (!condition() && [until timeIntervalSinceNow] > 0)
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
    return condition();
}

// ---------------------------------------------------------------------------

static NSString *gShared = nil;
static NSString *gDecoy = nil;    // what +sharedRootPath returns here
static IMP gRealSharedRootPath = NULL;
static BOOL gActive[2] = { YES, YES };

static NSString *FCDecoySharedRoot(id self, SEL _cmd) { return gDecoy; }

typedef struct {
    FCShareController *controller;
    FlycutOperator *op;
    FCMemoryPasteboard *pasteboard;
    FlycutAccountShareService *service;
} Participant;

static Participant Make(uid_t uid) {
    Participant p;
    int slot = uid == kA ? 0 : 1;
    p.controller = [[FCShareController alloc] init];   // registers AppController's defaults
    p.op = [[FlycutOperator alloc] init];
    [p.op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:@selector(savePreferencesOnDict:) forTarget:p.controller];
    [p.op setClippingsStoreDelegate:(id)p.controller];
    [p.op setFavoritesStoreDelegate:(id)p.controller];
    p.pasteboard = [[FCMemoryPasteboard alloc] init];
    [p.controller installOperator:p.op pasteboard:p.pasteboard];
    p.service = [[FlycutAccountShareService alloc]
        initWithEngine:FCTracedEngineFor(gShared, uid, (id<FlycutAccountShareFilter>)p.op)
              accounts:^NSArray *{ return @[@(kA), @(kB), @(kUnopted)]; }
       sessionIsActive:^BOOL { return gActive[slot]; }];
    [p.service setSafetyInterval:3600];
    @try {
        [p.controller setValue:p.service forKey:@"accountShareService"];
    } @catch (NSException *exception) {
        printf("FAIL: AppController has no accountShareService\n");
    }
    [p.service setDelegate:(id)p.controller];
    return p;
}

static void Copy(Participant p, NSString *text) {
    [p.pasteboard copyText:text];
    [p.controller pollPB:nil];
    [p.controller drainCaptures];
}

static NSString *Top(Participant p) {
    return [p.op jcListCount] > 0 ? [p.op getPasteFromIndex:0] : nil;
}

static NSString *TopPath(uid_t recipient) {
    return [gShared stringByAppendingPathComponent:[NSString stringWithFormat:@".flycut-share-%u", recipient]];
}

static NSString *FromPath(uid_t recipient, uid_t sender) {
    return [TopPath(recipient) stringByAppendingPathComponent:[NSString stringWithFormat:@"from-%u", sender]];
}

static NSUInteger Waiting(uid_t recipient, uid_t sender) {
    return [[[NSFileManager defaultManager] contentsOfDirectoryAtPath:FromPath(recipient, sender) error:NULL] count];
}

static BOOL Exists(NSString *path) {
    struct stat st;
    return lstat([path fileSystemRepresentation], &st) == 0;
}

static void StartBoth(Participant a, Participant b) {
    [a.service start];
    [b.service start];
    [a.service waitForQueue];
    [b.service waitForQueue];
    Spin(0.1);
}

// ---------------------------------------------------------------------------

static int RunDefaults(void) {
    int f = 0;
    [[[FCShareController alloc] init] autorelease];   // registers AppController's defaults
    id value = [[NSUserDefaults standardUserDefaults] objectForKey:@"shareClippingsAcrossAccounts"];
    f += Check(value != nil && ![value boolValue], "sharing with other accounts is registered and off by default");
    return f;
}

static int RunSetUpOff(void) {
    int f = 0;
    Participant p;
    p.controller = [[FCShareController alloc] init];
    p.op = [[FlycutOperator alloc] init];
    p.pasteboard = [[FCMemoryPasteboard alloc] init];
    [p.controller installOperator:p.op pasteboard:p.pasteboard];
    if (![p.controller respondsToSelector:@selector(setUpAccountSharing)])
        return Check(NO, "AppController sets account sharing up at launch");
    [p.controller setUpAccountSharing];
    FlycutAccountShareService *service = [p.controller valueForKey:@"accountShareService"];
    f += Check(service != nil && ![service running], "with the setting off the service exists but does not run");
    FlycutAccountShare *engine = [service engine];
    NSString *real = ((NSString *(*)(id, SEL))gRealSharedRootPath)([FlycutAccountShareService class], @selector(sharedRootPath));
    f += Check([real isEqualToString:@"/Users/Shared"], "the app's shared root is /Users/Shared (not used here)");
    f += Check([[engine sharedRoot] isEqualToString:gDecoy] && [engine ownUID] == getuid()
               && [engine filter] == (id)p.op && [service delegate] == (id)p.controller,
               "the app's engine: +sharedRootPath (a scratch decoy here), this account, FlycutOperator as filter, the controller as delegate");
    __block BOOL observed = NO;
    id token = [fakeWorkspace->center addObserverForName:NSWorkspaceSessionDidBecomeActiveNotification object:nil queue:nil
                                              usingBlock:^(NSNotification *n) { observed = YES; }];
    Class cls = [FCShareController class];
    __block int handled = 0;
    IMP original = class_getMethodImplementation(cls, @selector(accountSessionDidBecomeActive:));
    IMP counting = imp_implementationWithBlock(^(id self, NSNotification *n) {
        handled++;
        ((void (*)(id, SEL, id))original)(self, @selector(accountSessionDidBecomeActive:), n);
    });
    class_addMethod(cls, @selector(accountSessionDidBecomeActive:), counting, "v@:@");
    [fakeWorkspace->center postNotificationName:NSWorkspaceSessionDidBecomeActiveNotification object:nil];
    [fakeWorkspace->center removeObserver:token];
    f += Check(observed && handled == 1, "the controller observes the workspace's session-became-active notification");
    f += Check(![service running], "and a session change does not start sharing that is off");
    [service waitForQueue];
    f += Check([[[NSFileManager defaultManager] contentsOfDirectoryAtPath:gDecoy error:NULL] count] == 0,
               "nothing is created in the shared folder while sharing is off");
    return f;
}

// Launch with sharing off and an inbox left over from an earlier run (a
// delete that failed when sharing was turned off, or a crash): it goes.
static int RunSetUpOffLeftover(void) {
    int f = 0;
    Participant p;
    p.controller = [[FCShareController alloc] init];
    p.op = [[FlycutOperator alloc] init];
    p.pasteboard = [[FCMemoryPasteboard alloc] init];
    [p.controller installOperator:p.op pasteboard:p.pasteboard];
    if (![p.controller respondsToSelector:@selector(setUpAccountSharing)])
        return Check(NO, "AppController sets account sharing up at launch");
    NSString *top = [gDecoy stringByAppendingPathComponent:[NSString stringWithFormat:@".flycut-share-%u", getuid()]];
    NSString *from = [top stringByAppendingPathComponent:@"from-7001"];
    BOOL planted = mkdir([top fileSystemRepresentation], 0700) == 0 && mkdir([from fileSystemRepresentation], 0700) == 0
        && [[@"example-60 left over" dataUsingEncoding:NSUTF8StringEncoding]
               writeToFile:[from stringByAppendingPathComponent:@"left-over.clip"] atomically:NO];
    f += Check(planted, "an inbox left over from an earlier run, with a copy in it, is in the (decoy) shared folder");
    [p.controller setUpAccountSharing];
    FlycutAccountShareService *service = [p.controller valueForKey:@"accountShareService"];
    [service waitForQueue];
    f += Check(service != nil && ![service running] && !Exists(top), "with sharing off, launch deletes the inbox left over");
    f += Check([[[NSFileManager defaultManager] contentsOfDirectoryAtPath:gDecoy error:NULL] count] == 0,
               "and creates nothing in the shared folder");
    return f;
}

// Launch with sharing on while a copy from another account waits since the
// last quit: it is taken in; only a launch with sharing off deletes the inbox.
static int RunSetUpOnWaiting(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    [a.controller setUpAccountSharing];
    [b.controller setUpAccountSharing];
    [a.service waitForQueue];
    [b.service waitForQueue];
    f += Check([b.service running] && Exists(FromPath(kB, kA)), "launched with sharing on, B runs with an inbox for A");
    [b.service stop];
    [b.service waitForQueue];
    Copy(a, @"example-62 alpha");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A's copy waits in B's inbox while B's Flycut is quit");
    Participant c = Make(kB);
    [c.service setWatchesSenderFolders:NO];
    [c.controller setUpAccountSharing];
    [c.service waitForQueue];
    f += Check(WaitFor(^BOOL { return [Top(c) isEqualToString:@"example-62 alpha"]; }, 3.0),
               "launched again with sharing on, B takes in the copy that waited instead of deleting the inbox");
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.service stop];
    [c.service stop];
    return f;
}

static int RunCaptureReachesOtherAccount(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    StartBoth(a, b);
    int before = b.controller->added;
    Copy(a, @"example-01 alpha");
    f += Check([Top(a) isEqualToString:@"example-01 alpha"], "A's copy is in A's history");
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-01 alpha"]; }, 3.0),
               "B's history gets A's copy through the account-share service");
    f += Check(b.controller->added == before + 1, "it is added the normal way (the store's added callback ran once)");
    FlycutClipping *clipping = [b.op clippingAtPosition:0];
    f += Check([[clipping appLocalizedName] isEqualToString:@"Example App"], "with the source app's name");
    f += Check(b.pasteboard->changeCount == 100, "B is in front: its pasteboard is left alone");
    Spin(0.5);
    f += Check([a.op jcListCount] == 1 && Waiting(kA, kB) == 0, "nothing comes back to A");
    [a.service stop];
    [b.service stop];
    return f;
}

static int RunAwayThenSwitchNoEcho(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    StartBoth(a, b);
    gActive[1] = NO;
    Copy(a, @"example-02 beta");
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-02 beta"]; }, 3.0),
               "B, in the background, gets A's copy into its history");
    Copy(b, @"example-03 gamma");
    [b.service waitForQueue];
    f += Check([Top(b) isEqualToString:@"example-03 gamma"] && Waiting(kA, kB) == 0,
               "B's own copy while in the background stays in B");
    f += Check(b.pasteboard->changeCount == 101, "B's pasteboard holds only B's own copy");
    gActive[1] = YES;
    if ([b.controller respondsToSelector:@selector(accountSessionDidBecomeActive:)])
        [b.controller accountSessionDidBecomeActive:nil];
    f += Check(WaitFor(^BOOL { return [[b.pasteboard stringForType:NSPasteboardTypeString] isEqualToString:@"example-02 beta"]; }, 3.0),
               "when B comes to the console A's copy is on B's pasteboard");
    f += Check([[b.controller blockedGeneration] integerValue] == b.pasteboard->changeCount,
               "written through -addClipToPasteboard:, which marks the generation as Flycut's own");
    NSUInteger count = [b.op jcListCount];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    [b.service waitForQueue];
    Spin(1.0);
    f += Check([b.op jcListCount] == count && [Top(b) isEqualToString:@"example-03 gamma"],
               "B's next poll does not capture it again");
    f += Check(Waiting(kA, kB) == 0 && [a.op jcListCount] == 1, "and does not send it back to A");
    [a.service stop];
    [b.service stop];
    return f;
}

static int RunNothingSent(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    StartBoth(a, b);
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setBool:YES forKey:@"revealPasteboardTypes"];
    Copy(a, @"example-04 delta");
    [a.service waitForQueue];
    f += Check([Top(a) isEqualToString:NSPasteboardTypeString] && Waiting(kB, kA) == 0,
               "with pasteboard types in the list (diagnostics) the copy is recorded as its type and not sent");
    [defaults setBool:NO forKey:@"revealPasteboardTypes"];
    [a.controller setClipboardTrackingPaused:YES];
    Copy(a, @"example-05 epsilon");
    [a.service waitForQueue];
    f += Check(![Top(a) isEqualToString:@"example-05 epsilon"] && Waiting(kB, kA) == 0, "while paused nothing is captured or sent");
    [a.controller setClipboardTrackingPaused:NO];
    gActive[0] = NO;
    Copy(a, @"example-06 zeta");
    [a.service waitForQueue];
    f += Check([Top(a) isEqualToString:@"example-06 zeta"] && Waiting(kB, kA) == 0,
               "a copy made while A's session is not on the console stays in A");
    gActive[0] = YES;
    Copy(a, @"Ab3$efGh9!xY");
    [a.service waitForQueue];
    f += Check([Top(a) isEqualToString:@"Ab3$efGh9!xY"] && Waiting(kB, kA) == 0,
               "a password-like copy kept locally (length check off) is not shared");
    Spin(0.5);
    f += Check([b.op jcListCount] == 0, "B got nothing");
    [a.service stop];
    [b.service stop];
    return f;
}

// A copy of the text that the history's newest clipping already holds is
// not added a second time, but the history holds it all the same: it is offered
// like a new copy, also while the bezel shows the favorites (the history is
// stashed then and the bezel's store is the favorites).
static int RunRecopyOfNewestIsShared(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    StartBoth(a, b);
    gActive[0] = NO;
    Copy(a, @"example-07 eta");
    [a.service waitForQueue];
    f += Check([Top(a) isEqualToString:@"example-07 eta"] && Waiting(kB, kA) == 0,
               "a copy made while A's session is not on the console stays in A");
    gActive[0] = YES;
    int added = a.controller->added;
    Copy(a, @"example-07 eta");
    [a.service waitForQueue];
    f += Check([a.op jcListCount] == 1 && a.controller->added == added, "copied again, the same text is not added a second time");
    f += Check(Waiting(kB, kA) == 1, "but the history holds it: the copy is offered to B");
    [b.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-07 eta"]; }, 3.0) && Waiting(kB, kA) == 0,
               "and reaches B's history");
    gActive[0] = NO;
    Copy(a, @"example-08 theta");
    [a.service waitForQueue];
    gActive[0] = YES;
    [a.op switchToFavoritesStore];
    Copy(a, @"example-08 theta");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "the same while A's bezel shows the favorites");
    [a.op restoreStashedStore];
    f += Check([a.op jcListCount] == 2 && [Top(a) isEqualToString:@"example-08 theta"], "A's history holds each text once");
    [b.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-08 theta"]; }, 3.0), "and B gets it");
    Spin(0.3);
    f += Check(Waiting(kA, kB) == 0 && [a.op jcListCount] == 2, "nothing comes back to A");
    [a.service stop];
    [b.service stop];
    return f;
}

static int RunToggle(void) {
    int f = 0;
    Participant b = Make(kB);
    if (![b.controller respondsToSelector:@selector(toggleShareClippingsAcrossAccounts:)])
        return Check(NO, "the checkbox has an action");
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    [b.controller toggleShareClippingsAcrossAccounts:nil];
    [b.service waitForQueue];
    f += Check([b.service running] && Exists(FromPath(kB, kA)) && Exists(FromPath(kB, kUnopted)),
               "turning it on prepares the inbox for every other account");
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [b.controller toggleShareClippingsAcrossAccounts:nil];
    [b.service waitForQueue];
    f += Check(![b.service running] && !Exists(TopPath(kB)), "turning it off wipes the inbox");
    return f;
}

@interface AppController (AccountShareCatchUp)
- (void)captureClipboardChangeNow;
- (void)addClipToPasteboard:(NSString *)pbFullText withRichData:(NSDictionary *)richData;
@end

// A formatted copy, shared with its formatting: taken in by the poll, or caught up by a
// selection (-captureClipboardChangeNow). Written by the independent review as a probe.
static int RunRichShare(BOOL catchUp) {
    int f = 0;
    [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"preserveTextFormatting"];
    Participant a = Make(kA), b = Make(kB);
    StartBoth(a, b);
    [a.pasteboard copyText:@"example-91 rich"];
    [a.pasteboard setData:[@"{\\rtf1 example}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
    if (catchUp) [a.controller captureClipboardChangeNow];
    else [a.controller pollPB:nil];
    [a.controller drainCaptures];
    Spin(0.3);
    [a.controller drainCaptures];
    BOOL arrived = WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-91 rich"]; }, 3.0);
    FlycutClipping *ca = [a.op jcListCount] > 0 ? [a.op clippingAtPosition:0] : nil;
    FlycutClipping *cb = [b.op jcListCount] > 0 ? [b.op clippingAtPosition:0] : nil;
    f += Check(arrived, "B's history gets A's formatted copy");
    f += Check([[ca richData] objectForKey:NSPasteboardTypeRTF] != nil, "A's row has the formatting");
    f += Check([[cb richData] objectForKey:NSPasteboardTypeRTF] != nil, "B's row has the formatting too");
    [a.service stop];
    [b.service stop];
    return f;
}
static int RunRichPoll(void) { return RunRichShare(NO); }
static int RunRichCatchUp(void) { return RunRichShare(YES); }

// Holds A's formatting read on the read queue until the test lets it end. It then answers as a
// real pasteboard does: with the copy's data if the clipboard did not change, with Flycut's own
// newer write for that type, or with nothing after another application's copy; never with the
// copy's data once the clipboard changed.
static dispatch_semaphore_t gRichGate = NULL;
static BOOL gGatedLastWriteWasFlycuts;   // the last change: Flycut's write, or another application's copy
@interface FCGatedPasteboard : FCMemoryPasteboard
@end
@implementation FCGatedPasteboard
- (NSData *)dataForType:(NSString *)type {
    if (gRichGate == NULL || ![type isEqual:NSPasteboardTypeRTF] || [NSThread isMainThread])
        return [super dataForType:type];
    NSInteger asked = changeCount;
    dispatch_semaphore_wait(gRichGate, DISPATCH_TIME_FOREVER);
    if (changeCount != asked && !gGatedLastWriteWasFlycuts)
        return nil;
    return [super dataForType:type];
}
// Flycut writes with -declareTypes:owner: or -clearContents; -copyText: is another application's copy.
- (NSInteger)declareTypes:(NSArray *)newTypes owner:(id)owner {
    gGatedLastWriteWasFlycuts = YES;
    return [super declareTypes:newTypes owner:owner];
}
- (NSInteger)clearContents {
    gGatedLastWriteWasFlycuts = YES;
    return [super clearContents];
}
- (void)copyText:(NSString *)text {
    gGatedLastWriteWasFlycuts = NO;
    [super copyText:text];
}
@end

// A formatted copy whose read ended before a newer copy was shared, but whose row went in after
// it (the main thread was busy when the read ended): it goes into A's history below the newer
// copy, complete, and is not shared above it.
static int RunLateRichBelowNewer(void) {
    int f = 0;
    [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"preserveTextFormatting"];
    Participant a = Make(kA), b = Make(kB);
    object_setClass(a.pasteboard, [FCGatedPasteboard class]);
    StartBoth(a, b);
    gRichGate = dispatch_semaphore_create(0);
    [a.pasteboard copyText:@"example-92 older rich"];
    [a.pasteboard setData:[@"{\\rtf1 older}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
    [a.controller captureClipboardChangeNow];   // its formatting read starts and is held
    f += Check([a.op jcListCount] == 0, "the formatted copy gets no row of its text alone");
    dispatch_semaphore_signal(gRichGate);       // the read ends, the copy still on the clipboard ...
    [a.controller waitForReadsLeavingCommitsQueued];   // ... while the main thread is busy
    [a.pasteboard copyText:@"example-93 newer"];
    [a.controller captureClipboardChangeNow];   // plain text alone: in at once, and offered
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-93 newer"]; }, 3.0),
               "B gets the newer copy");
    [a.controller drainCaptures];               // the older copy's commit runs
    Spin(0.3);
    [a.controller drainCaptures];
    FlycutClipping *older = [a.op jcListCount] > 1 ? [a.op clippingAtPosition:1] : nil;
    f += Check([Top(a) isEqualToString:@"example-93 newer"] && [[older contents] isEqualToString:@"example-92 older rich"]
               && [[older richData] objectForKey:NSPasteboardTypeRTF] != nil,
               "in A's history the older copy goes in below the newer one, with its formatting");
    [a.service waitForQueue];
    [b.service pickUp];
    BOOL above = WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-92 older rich"]; }, 1.5);
    f += Check(!above && [Top(b) isEqualToString:@"example-93 newer"],
               "B's newest row stays the newer copy: the older one is not shared above it");
    [a.service stop];
    [b.service stop];
    dispatch_release(gRichGate);
    gRichGate = NULL;
    return f;
}

// The user's choice replaces a formatted copy on the clipboard while its formatting is read; the
// read answers with the choice's RTF. The copy gets no row and is not shared, never with the
// choice's formatting. Written by an independent review as a probe.
static int RunLateRichChoice(void) {
    int f = 0;
    [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"preserveTextFormatting"];
    Participant a = Make(kA), b = Make(kB);
    object_setClass(a.pasteboard, [FCGatedPasteboard class]);
    StartBoth(a, b);
    gRichGate = dispatch_semaphore_create(0);
    [a.pasteboard copyText:@"example-95 late rich"];
    [a.pasteboard setData:[@"{\\rtf1 own}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
    [a.controller captureClipboardChangeNow];   // the RTF read starts and is held
    [a.controller addClipToPasteboard:@"example-96 chosen"
                         withRichData:@{NSPasteboardTypeRTF: [@"{\\rtf1 chosen}" dataUsingEncoding:NSUTF8StringEncoding]}];
    dispatch_semaphore_signal(gRichGate);       // the read ends after the choice
    [a.controller drainCaptures];
    Spin(0.3);
    [a.controller drainCaptures];
    [a.service waitForQueue];
    [b.service pickUp];
    BOOL arrived = WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-95 late rich"]; }, 1.5);
    BOOL kept = NO;
    for (int i = 0; i < [a.op jcListCount]; i++)
        if ([[[a.op clippingAtPosition:i] contents] isEqualToString:@"example-95 late rich"]) kept = YES;
    f += Check(!kept, "A's history has no row of the copy, none with the choice's formatting");
    f += Check(!arrived, "B does not get the copy, none with the choice's formatting");
    [a.service stop];
    [b.service stop];
    dispatch_release(gRichGate);
    gRichGate = NULL;
    return f;
}

// B shares a copy while A's formatted copy is still read: the shared copy came later, so A's
// formatted copy goes in below it when its read ends with the copy still on A's clipboard.
static int RunReceivedAboveLate(void) {
    int f = 0;
    [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"preserveTextFormatting"];
    Participant a = Make(kA), b = Make(kB);
    object_setClass(a.pasteboard, [FCGatedPasteboard class]);
    StartBoth(a, b);
    gRichGate = dispatch_semaphore_create(0);
    [a.pasteboard copyText:@"example-97 late rich"];
    [a.pasteboard setData:[@"{\\rtf1 late}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
    [a.controller captureClipboardChangeNow];   // the RTF read starts and is held
    Copy(b, @"example-98 shared");
    [b.service waitForQueue];
    [a.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(a) isEqualToString:@"example-98 shared"]; }, 3.0),
               "A gets B's copy while its own read runs");
    dispatch_semaphore_signal(gRichGate);       // A's read ends, its copy still on A's clipboard
    [a.controller drainCaptures];
    Spin(0.3);
    [a.controller drainCaptures];
    FlycutClipping *late = [a.op jcListCount] > 1 ? [a.op clippingAtPosition:1] : nil;
    f += Check([Top(a) isEqualToString:@"example-98 shared"] && [[late contents] isEqualToString:@"example-97 late rich"]
               && [[late richData] objectForKey:NSPasteboardTypeRTF] != nil,
               "A's formatted copy goes in below the copy B shared meanwhile, with its formatting");
    [a.service stop];
    [b.service stop];
    dispatch_release(gRichGate);
    gRichGate = NULL;
    return f;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 3) return 2;
        const uid_t simulated[] = { kA, kB, kUnopted };
        for (size_t i = 0; i < sizeof simulated / sizeof simulated[0]; i++)
            if (getpwuid(simulated[i]) != NULL) {
                fprintf(stderr, "FAIL: simulated UID %u belongs to a real account; refusing to run\n", simulated[i]);
                return 2;
            }
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 2;
        char root[PATH_MAX];
        if (realpath(argv[2], root) == NULL) return 2;
        FCTraceSetRoot(root);
        gShared = [[[NSString stringWithUTF8String:root] stringByAppendingPathComponent:@"shared"] retain];
        if (mkdir([gShared fileSystemRepresentation], 0777) != 0 || chmod([gShared fileSystemRepresentation], 01777) != 0)
            return 2;
        // The production-wired service (setup-off) must never see the real shared
        // folder, also not when a bug or a mutant starts it: +sharedRootPath answers
        // a decoy inside the injected root, and the trace refuses any write outside it.
        gDecoy = [[[NSString stringWithUTF8String:root] stringByAppendingPathComponent:@"decoy-shared"] retain];
        if (mkdir([gDecoy fileSystemRepresentation], 0777) != 0 || chmod([gDecoy fileSystemRepresentation], 01777) != 0)
            return 2;
        gRealSharedRootPath = method_setImplementation(
            class_getClassMethod([FlycutAccountShareService class], @selector(sharedRootPath)), (IMP)FCDecoySharedRoot);
        InstallBoundaries();
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setObject:@0 forKey:@"savePreference"];
        [defaults setObject:@NO forKey:@"saveForgottenClippings"];
        [defaults setObject:@NO forKey:@"saveForgottenFavorites"];
        [defaults setObject:@NO forKey:@"captureImages"];
        NSDictionary *modes = @{@"defaults": [NSValue valueWithPointer:RunDefaults],
                                @"rich-poll": [NSValue valueWithPointer:RunRichPoll],
                                @"rich-catch-up": [NSValue valueWithPointer:RunRichCatchUp],
                                @"late-rich-below-newer": [NSValue valueWithPointer:RunLateRichBelowNewer],
                                @"late-rich-choice": [NSValue valueWithPointer:RunLateRichChoice],
                                @"received-above-late": [NSValue valueWithPointer:RunReceivedAboveLate],
                                @"setup-off": [NSValue valueWithPointer:RunSetUpOff],
                                @"setup-off-leftover": [NSValue valueWithPointer:RunSetUpOffLeftover],
                                @"setup-on-waiting": [NSValue valueWithPointer:RunSetUpOnWaiting],
                                @"capture": [NSValue valueWithPointer:RunCaptureReachesOtherAccount],
                                @"away-no-echo": [NSValue valueWithPointer:RunAwayThenSwitchNoEcho],
                                @"nothing-sent": [NSValue valueWithPointer:RunNothingSent],
                                @"recopy": [NSValue valueWithPointer:RunRecopyOfNewestIsShared],
                                @"toggle": [NSValue valueWithPointer:RunToggle]};
        NSValue *run = [modes objectForKey:[NSString stringWithUTF8String:argv[1]]];
        if (run == nil) return 3;
        int failures = ((int (*)(void))[run pointerValue])();
        FCTraceReport();
        printf("RESULT failures=%d\n", failures);
        fflush(stdout);
        return failures == 0 ? 0 : 1;
    }
}
