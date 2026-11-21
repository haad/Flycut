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

// The login accounts +[FlycutAccountShareService localLoginAccounts] answers here
// (dummy names and GeneratedUIDs; the real directory is never read).
static NSString *const kGuidA = @"0F0F0F0F-0000-4000-8000-000000007001";
static NSString *const kGuidB = @"0F0F0F0F-0000-4000-8000-000000007002";
static NSString *const kGuidU = @"0F0F0F0F-0000-4000-8000-000000007003";
static NSString *const kGuidNewB = @"0F0F0F0F-0000-4000-8000-00000000700B";
static NSArray *gAccounts = nil;
// Every account lookup is counted; gFailLookup > 0 makes the lookup with that
// number fail (nil) once.
static NSInteger gLookups = 0, gFailLookup = 0;
static NSArray *FCFixtureLoginAccounts(id self, SEL _cmd) {
    gLookups++;
    return gFailLookup > 0 && gLookups == gFailLookup ? nil : gAccounts;
}
static NSArray *DefaultAccounts(void) {
    return @[@{@"uid": @(kA), @"name": @"Account A", @"guid": kGuidA}, @{@"uid": @(kB), @"name": @"Account B", @"guid": kGuidB},
             @{@"uid": @(kUnopted), @"name": @"Account U", @"guid": kGuidU}];
}

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
- (void)copyText:(NSString *)text withTypes:(NSArray *)markers;
- (void)copyImage;
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
// One item holding every type, as -snapshotPasteboardItems reads it.
- (NSArray *)pasteboardItems {
    if ([types count] == 0) return @[];
    NSPasteboardItem *item = [[[NSPasteboardItem alloc] init] autorelease];
    for (NSString *type in types) {
        id value = values[type];
        [item setData:[value isKindOfClass:[NSString class]] ? [value dataUsingEncoding:NSUTF8StringEncoding] : value forType:type];
    }
    return @[item];
}
// Puts items back (a cancelled paste restores the earlier clipboard); no new generation.
- (BOOL)writeObjects:(NSArray *)objects {
    for (id object in objects) {
        if (![object isKindOfClass:[NSPasteboardItem class]]) return NO;
        for (NSString *type in [object types]) {
            NSData *data = [object dataForType:type];
            if ([type isEqualToString:NSPasteboardTypeString])
                values[type] = [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] autorelease];
            else
                values[type] = data;
            [self addType:type];
        }
    }
    return YES;
}
- (void)copyText:(NSString *)text {
    changeCount++; [types release]; types = [@[NSPasteboardTypeString] retain];
    [values removeAllObjects]; values[NSPasteboardTypeString] = text;
}
// A copy that carries marker types too (a password manager's concealed type).
- (void)copyText:(NSString *)text withTypes:(NSArray *)markers {
    [self copyText:text];
    for (NSString *marker in markers) { values[marker] = [NSData dataWithBytes:"1" length:1]; [self addType:marker]; }
}
// A picture only (no text type).
- (void)copyImage {
    changeCount++; [types release]; types = [@[NSPasteboardTypeTIFF] retain];
    [values removeAllObjects]; values[NSPasteboardTypeTIFF] = [NSData dataWithBytes:"II*\0" length:4];
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
- (void)accountSessionDidResignActive:(NSNotification *)notification;
- (void)noteAccountSharePasteboardAtLaunch;
- (NSString *)accountSharingStatusText;
- (IBAction)toggleShareClippingsAcrossAccounts:(id)sender;
- (void)rememberFrontmostApplicationForPaste;
- (void)clearRememberedPasteTarget;
- (IBAction)toggleSendToAccount:(id)sender;
- (IBAction)toggleReceiveFromAccount:(id)sender;
@end

// Each account chooses whom it sends to and whom it receives from.
@interface FlycutAccountShareService (OneWayTesting)
- (NSArray *)sendAccountUIDs;
- (NSArray *)receiveAccountUIDs;
@end

static NSString *const kSendKey = @"shareClippingsSendAccountIDs";
static NSString *const kReceiveKey = @"shareClippingsReceiveAccountIDs";

// The lists the service was given: the accounts it sends to and receives from.
static BOOL ServiceLists(FlycutAccountShareService *service, NSArray *send, NSArray *receive) {
    if (![service respondsToSelector:@selector(sendAccountUIDs)] || ![service respondsToSelector:@selector(receiveAccountUIDs)])
        return NO;
    NSArray *s = [service sendAccountUIDs], *r = [service receiveAccountUIDs];
    return (s == send || [s isEqual:send]) && (r == receive || [r isEqual:receive]);
}

static void StoreChoice(NSArray *send, NSArray *receive) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setObject:send forKey:kSendKey];
    [defaults setObject:receive forKey:kReceiveKey];
}

static BOOL Stored(NSArray *send, NSArray *receive) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    return [[defaults objectForKey:kSendKey] isEqual:send] && [[defaults objectForKey:kReceiveKey] isEqual:receive];
}

// The session leaves the console: the controller notes what is on its pasteboard.
static void Leave(FCShareController *controller) {
    if ([controller respondsToSelector:@selector(accountSessionDidResignActive:)])
        [controller accountSessionDidResignActive:nil];
}

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
    gAccounts = [DefaultAccounts() retain];
    method_setImplementation(class_getClassMethod([FlycutAccountShareService class], @selector(localLoginAccounts)),
                             (IMP)FCFixtureLoginAccounts);
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
    // What -setUpAccountSharing does at launch: the pasteboard is empty here.
    if ([p.controller respondsToSelector:@selector(noteAccountSharePasteboardAtLaunch)])
        [p.controller noteAccountSharePasteboardAtLaunch];
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
    StoreChoice(@[kGuidA, kGuidB], @[kGuidA, kGuidB]);
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
    StoreChoice(@[], @[]);
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
    Copy(b, @"example-03 gamma");
    [b.service waitForQueue];
    f += Check([Top(b) isEqualToString:@"example-03 gamma"] && Waiting(kA, kB) == 0,
               "B's own copy made off the console stays in B");
    f += Check(b.pasteboard->changeCount == 101, "B's pasteboard holds only B's own copy");
    Leave(b.controller);
    Copy(a, @"example-02 beta");
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-02 beta"]; }, 3.0),
               "B, in the background, gets A's copy into its history");
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
    f += Check([b.op jcListCount] == count && [Top(b) isEqualToString:@"example-02 beta"],
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

// Diagnostics mode ("Diagnostics: save data type, not content") pauses pickup:
// a copy from another account waits in the inbox and is taken in once it is off.
static int RunDiagnosticsPausesPickup(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[kGuidA, kGuidB], @[kGuidA, kGuidB]);
    [a.controller setUpAccountSharing];
    [b.controller setUpAccountSharing];
    [a.service waitForQueue];
    [b.service waitForQueue];
    Copy(a, @"example-30 alpha");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A's copy waits in B's inbox");
    [defaults setBool:YES forKey:@"revealPasteboardTypes"];
    [center postNotificationName:NSUserDefaultsDidChangeNotification object:defaults];
    [b.service pickUp];
    [b.controller accountSessionDidBecomeActive:nil];
    [b.service waitForQueue];
    Spin(0.5);
    f += Check([b.op jcListCount] == 0 && Waiting(kB, kA) == 1 && b.pasteboard->changeCount == 100,
               "with pasteboard types in the list (diagnostics) B takes nothing in; the copy waits");
    [defaults setBool:NO forKey:@"revealPasteboardTypes"];
    [center postNotificationName:NSUserDefaultsDidChangeNotification object:defaults];
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-30 alpha"]; }, 3.0) && Waiting(kB, kA) == 0,
               "turning diagnostics off takes it in");
    [defaults setBool:YES forKey:@"revealPasteboardTypes"];
    Participant c = Make(kB);
    [c.controller setUpAccountSharing];
    BOOL paused = [c.service respondsToSelector:@selector(pickupPaused)] && [c.service pickupPaused];
    f += Check(paused && [c.service running], "Flycut started with diagnostics on runs sharing with pickup paused");
    [defaults setBool:NO forKey:@"revealPasteboardTypes"];
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[], @[]);
    [a.service stop];
    [b.service stop];
    [c.service stop];
    return f;
}

// Turning sharing off in A also deletes A's copy that still waits for B.
static int RunToggleWithdraws(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    StartBoth(a, b);
    Copy(a, @"example-31 beta");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A's copy waits in B's inbox");
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.controller toggleShareClippingsAcrossAccounts:nil];
    [a.service waitForQueue];
    f += Check(![a.service running] && Waiting(kB, kA) == 0 && Exists(FromPath(kB, kA)),
               "turning sharing off in A deletes it; B's folder for A stays");
    [b.service stop];
    return f;
}


static NSString *OnPasteboard(Participant p) {
    return [p.pasteboard stringForType:NSPasteboardTypeString];
}

// A copy from A arrives while B is off the console and is in B's history.
static BOOL ArrivesWhileAway(Participant a, Participant b, NSString *text) {
    Leave(b.controller);
    gActive[1] = NO;
    Copy(a, text);
    [a.service waitForQueue];
    [b.service pickUp];
    return WaitFor(^BOOL { return [Top(b) isEqualToString:text]; }, 3.0);
}

static void Return(Participant b) {
    gActive[1] = YES;
    [b.controller accountSessionDidBecomeActive:nil];
    [b.service waitForQueue];
    Spin(0.3);
}

// A shared copy goes on the pasteboard on return or at launch only if the
// pasteboard holds nothing the user copied after it: the change count must be
// the one noted when the session left (or at launch, then only an empty
// pasteboard), and -pollPB: must have seen it.
static int RunPasteboardGuard(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    StartBoth(a, b);
    if (![b.controller respondsToSelector:@selector(accountSessionDidResignActive:)])
        f += Check(NO, "the controller notes the pasteboard when its session leaves the console");
    // (a) Something lands on B's pasteboard while B is away (an app there writes it).
    f += Check(ArrivesWhileAway(a, b, @"example-50 alpha"), "A's copy reaches B's history while B is away");
    Copy(b, @"example-51 own");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-51 own"], "what B's pasteboard got while away stays on it");
    // (b) Nothing new on it: the shared copy goes there.
    f += Check(ArrivesWhileAway(a, b, @"example-52 beta"), "A's next copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-52 beta"], "with nothing new on it, A's copy is on B's pasteboard on return");
    // (c) B copies the moment it is back, before the delivery and before -pollPB: saw it.
    f += Check(ArrivesWhileAway(a, b, @"example-53 gamma"), "a third copy reaches B while away");
    gActive[1] = YES;
    [b.pasteboard copyText:@"example-54 own"];
    [b.controller accountSessionDidBecomeActive:nil];
    [b.service waitForQueue];
    Spin(0.3);
    f += Check([OnPasteboard(b) isEqualToString:@"example-54 own"], "a copy made right after coming back is not replaced");
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    // (d) B copied just before leaving and -pollPB: has not seen it yet.
    [b.pasteboard copyText:@"example-55 own"];
    f += Check(ArrivesWhileAway(a, b, @"example-56 delta"), "a fourth copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-55 own"], "a copy Flycut has not seen yet is not replaced");
    [a.service stop];
    [b.service stop];
    return f;
}

// At launch: what is on the pasteboard when Flycut starts was never captured,
// so a waiting shared copy replaces only an empty pasteboard.
static int RunLaunchPasteboardGuard(void) {
    int f = 0;
    if (![FCShareController instancesRespondToSelector:@selector(noteAccountSharePasteboardAtLaunch)])
        return Check(NO, "the controller notes the pasteboard at launch");
    for (int empty = 0; empty < 2; empty++) {
        Participant a = Make(kA), b = Make(kB);
        [b.service setWatchesSenderFolders:NO];
        StartBoth(a, b);
        [b.service stop];   // B quits
        [b.service waitForQueue];
        NSString *text = empty ? @"example-58 beta" : @"example-57 alpha";
        Copy(a, text);
        [a.service waitForQueue];
        // B starts again: a new controller; the pasteboard holds the user's copy or nothing.
        Participant c = Make(kB);
        [c.service setWatchesSenderFolders:NO];
        if (!empty)
            [c.pasteboard copyText:@"example-59 own"];
        [c.controller installOperator:c.op pasteboard:c.pasteboard];
        [c.controller noteAccountSharePasteboardAtLaunch];
        [c.service start];
        [c.service waitForQueue];
        f += Check(WaitFor(^BOOL { return [Top(c) isEqualToString:text]; }, 3.0), "at launch B takes in the copy that waited");
        Spin(0.3);
        if (empty)
            f += Check([OnPasteboard(c) isEqualToString:text], "and puts it on B's empty pasteboard");
        else
            f += Check([OnPasteboard(c) isEqualToString:@"example-59 own"], "but leaves what B's pasteboard held at launch");
        if (!empty) {
            // B leaves and comes back with that launch content still there: it stays too.
            Leave(c.controller);
            gActive[1] = NO;
            Copy(a, @"example-59 gamma");
            [a.service waitForQueue];
            [c.service pickUp];
            f += Check(WaitFor(^BOOL { return [Top(c) isEqualToString:@"example-59 gamma"]; }, 3.0), "a later copy reaches B while away");
            Return(c);
            f += Check([OnPasteboard(c) isEqualToString:@"example-59 own"], "and still does not replace the uncaptured launch content");
        }
        [a.service stop];
        [c.service stop];
    }
    return f;
}

// While clipboard tracking is paused nothing is taken in from the other
// accounts and nothing goes on the pasteboard; copies wait in the inbox.
static int RunTrackingPausePausesPickup(void) {
    int f = 0;
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    StartBoth(a, b);
    [b.controller setClipboardTrackingPaused:YES];
    f += Check([b.service pickupPaused], "pausing clipboard tracking in B pauses taking in shared copies");
    Leave(b.controller);
    gActive[1] = NO;
    Copy(a, @"example-60 alpha");
    [a.service waitForQueue];
    [b.service pickUp];
    Return(b);
    f += Check([b.op jcListCount] == 0 && Waiting(kB, kA) == 1 && b.pasteboard->changeCount == 100,
               "while paused B adds nothing to its history and leaves its pasteboard; the copy waits");
    [b.controller setClipboardTrackingPaused:NO];
    f += Check(![b.service pickupPaused], "resuming tracking resumes pickup");
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-60 alpha"]; }, 3.0) && Waiting(kB, kA) == 0,
               "and takes the waiting copy in");
    Spin(0.3);
    f += Check(b.pasteboard->changeCount == 100, "into the list only: the pasteboard is left alone");
    // The delegate keeps to the same rule when it is asked directly.
    FlycutSharedClipping *clipping = [[[FlycutSharedClipping alloc] initWithSender:kA created:[[NSDate date] timeIntervalSince1970]
                                                                               text:@"example-61 beta" richData:nil appName:nil] autorelease];
    [b.controller setClipboardTrackingPaused:YES];
    [b.controller accountShareService:b.service shouldPutOnPasteboard:clipping];
    f += Check(b.pasteboard->changeCount == 100, "asked to put a shared copy on the pasteboard while paused, B does not");
    [b.controller setClipboardTrackingPaused:NO];
    [b.controller accountShareService:b.service shouldPutOnPasteboard:clipping];
    f += Check([OnPasteboard(b) isEqualToString:@"example-61 beta"], "the same request is followed once tracking runs again");
    [b.controller setClipboardTrackingPaused:YES];
    [b.controller setUpAccountSharing];
    f += Check([b.service pickupPaused], "Flycut set up with tracking paused starts sharing with pickup paused");
    [b.controller setClipboardTrackingPaused:NO];
    [a.service stop];
    [b.service stop];
    return f;
}

// On return a shared copy replaces only what Flycut keeps: the last copy it
// took into the history, or a clipping it put on the pasteboard from its list.
// A copy it skipped (a password manager's), one made while tracking was paused,
// one recorded only by its type (diagnostics), a picture it did not capture and
// a clipboard put back after a cancelled paste stay on the pasteboard. A copy
// of the text the history's newest clipping holds is kept too.
static int RunKeptPasteboard(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    NSArray *concealed = @[@"org.nspasteboard.ConcealedType"];
    Participant a = Make(kA), b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    StartBoth(a, b);
    // (a) A password manager's copy: Flycut skips it.
    [b.pasteboard copyText:@"example-70 own" withTypes:concealed];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    f += Check([b.op jcListCount] == 0, "B skips a concealed copy");
    f += Check(ArrivesWhileAway(a, b, @"example-71 alpha"), "A's copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-70 own"], "a concealed copy Flycut skipped is not replaced");
    // (b) A copy made while tracking was paused; tracking runs again before B leaves.
    [b.controller setClipboardTrackingPaused:YES];
    [b.pasteboard copyText:@"example-72 own"];
    [b.controller pollPB:nil];
    [b.controller setClipboardTrackingPaused:NO];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    f += Check(![Top(b) isEqualToString:@"example-72 own"], "a copy made while paused is not captured");
    f += Check(ArrivesWhileAway(a, b, @"example-73 beta"), "A's next copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-72 own"], "a copy made while tracking was paused is not replaced");
    // (c) Diagnostics on: the copy goes into the list as its type only.
    [defaults setBool:YES forKey:@"revealPasteboardTypes"];
    [center postNotificationName:NSUserDefaultsDidChangeNotification object:defaults];
    Copy(b, @"example-74 own");
    f += Check([Top(b) isEqualToString:NSPasteboardTypeString], "with diagnostics on B records the copy's type only");
    [defaults setBool:NO forKey:@"revealPasteboardTypes"];
    [center postNotificationName:NSUserDefaultsDidChangeNotification object:defaults];
    f += Check(ArrivesWhileAway(a, b, @"example-75 gamma"), "a third copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-74 own"], "a copy recorded only by its type is not replaced");
    // (d) A picture, with image capture off.
    [b.pasteboard copyImage];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    f += Check(ArrivesWhileAway(a, b, @"example-76 delta"), "a fourth copy reaches B while away");
    Return(b);
    f += Check([[b.pasteboard types] isEqualToArray:@[NSPasteboardTypeTIFF]] && OnPasteboard(b) == nil,
               "a picture Flycut did not capture is not replaced");
    // (e) A paste from Flycut's list is cancelled: the skipped copy comes back.
    [b.pasteboard copyText:@"example-77 own" withTypes:concealed];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    [b.controller rememberFrontmostApplicationForPaste];
    [b.controller addClipToPasteboard:Top(b) withRichData:nil];
    f += Check([OnPasteboard(b) isEqualToString:@"example-76 delta"], "a paste from the list puts that clipping on the pasteboard");
    [b.controller clearRememberedPasteTarget];
    f += Check([OnPasteboard(b) isEqualToString:@"example-77 own"] && [[b.pasteboard types] containsObject:concealed[0]],
               "cancelling the paste puts the skipped copy back");
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    f += Check(ArrivesWhileAway(a, b, @"example-78 epsilon"), "a fifth copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-77 own"], "a copy put back after a cancelled paste is not replaced");
    // (f) What Flycut keeps is replaced: a clipping it put there from its list ...
    [b.controller addClipToPasteboard:@"example-75 gamma" withRichData:nil];
    [b.controller pollPB:nil];
    [b.controller drainCaptures];
    f += Check(ArrivesWhileAway(a, b, @"example-79 zeta"), "a sixth copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-79 zeta"], "a clipping Flycut put on the pasteboard from its list is replaced");
    // ... and the last copy it took into the history.
    Copy(b, @"example-80 own");
    f += Check([Top(b) isEqualToString:@"example-80 own"], "B takes its own copy into the history");
    f += Check(ArrivesWhileAway(a, b, @"example-81 eta"), "a seventh copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-81 eta"], "the last copy Flycut took into the history is replaced");
    // ... also when that copy's text already was the history's newest clipping.
    Copy(b, @"example-82 own");
    Copy(b, @"example-82 own");
    f += Check([Top(b) isEqualToString:@"example-82 own"] && [[b.op clippingAtPosition:1] contents] != nil
               && ![[[b.op clippingAtPosition:1] contents] isEqualToString:@"example-82 own"],
               "B copies the same text twice: it is in the history once");
    f += Check(ArrivesWhileAway(a, b, @"example-83 theta"), "an eighth copy reaches B while away");
    Return(b);
    f += Check([OnPasteboard(b) isEqualToString:@"example-83 theta"],
               "a copy of the history's newest text is replaced too: the history holds it");
    [a.service stop];
    [b.service stop];
    return f;
}

// While the inbox cannot be set up the sharing section says why; the
// note goes once it works again or sharing is turned off.
static int RunSetupFailureNote(void) {
    int f = 0;
    if (![FCShareController instancesRespondToSelector:@selector(accountSharingStatusText)])
        return Check(NO, "the controller has a note for a failed inbox setup");
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    NSString *top = TopPath(kB);
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);   // another account holds B's name
    Participant b = Make(kB);
    [b.service setLogHandler:^(NSString *line) { (void)line; }];
    [b.service setWatchesSenderFolders:NO];
    f += Check([b.controller accountSharingStatusText] == nil, "no note while sharing is off");
    [b.service start];
    NSString *taken = @"Sharing is unavailable: its folder in /Users/Shared is taken.";
    f += Check(WaitFor(^BOOL { return [[b.controller accountSharingStatusText] isEqualToString:taken]; }, 3.0),
               "a taken inbox name shows: Sharing is unavailable: its folder in /Users/Shared is taken.");
    rmdir([top fileSystemRepresentation]);
    [b.controller accountSessionDidBecomeActive:nil];   // retried at once
    f += Check(WaitFor(^BOOL { return [b.controller accountSharingStatusText] == nil; }, 3.0) && Exists(FromPath(kB, kA)),
               "the note goes once the inbox is set up");
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [b.controller toggleShareClippingsAcrossAccounts:nil];
    [b.service waitForQueue];
    f += Check([b.controller accountSharingStatusText] == nil && ![b.service running], "and while sharing is off there is none");
    return f;
}

// Stands in for an account's checkbox (an NSButton would ask the swizzled
// NSWorkspace for accessibility display options): its tag and state.
@interface FCAccountCheckbox : NSObject {
@public
    NSInteger tag, state;
}
@end
@implementation FCAccountCheckbox
- (NSInteger)tag { return tag; }
- (NSInteger)state { return state; }
- (void)setState:(NSInteger)value { state = value; }
@end

static FCAccountCheckbox *AccountCheckbox(uid_t uid, BOOL on) {
    FCAccountCheckbox *box = [[[FCAccountCheckbox alloc] init] autorelease];
    box->tag = uid;
    box->state = on ? NSControlStateValueOn : NSControlStateValueOff;
    return box;
}

// Clicks a Send or Receive checkbox of an account row (the fixture's stand-in).
static BOOL Click(Participant p, SEL action, FCAccountCheckbox *box) {
    if (![p.controller respondsToSelector:action])
        return NO;
    [p.controller performSelector:action withObject:box];
    [p.service waitForQueue];
    return YES;
}

// The stored choice reaches the service at launch, and a click on an account's
// Send or Receive checkbox stores it and passes it on. Both controllers share
// one in-memory defaults here, as if both accounts had stored the same lists;
// the service leaves the account itself out (the lists it gets name it too).
// So "A sends to B, B receives from A" is Send [B], Receive [A]. A copy goes from A to B only if A sends to B and B receives
// from A; unchecking Send withdraws the copies waiting there, unchecking
// Receive removes that account's folder with what waits in it.
static int RunChooseAccounts(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA), b = Make(kB);   // AppController's -init registers the defaults
    id send = [defaults objectForKey:kSendKey], receive = [defaults objectForKey:kReceiveKey];
    f += Check([send isKindOfClass:[NSArray class]] && [send count] == 0 && [receive isKindOfClass:[NSArray class]]
               && [receive count] == 0, "no account is chosen to send to or to receive from by default");
    [a.service setWatchesSenderFolders:NO];
    [b.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[kGuidB], @[]);
    [a.controller setUpAccountSharing];
    [b.controller setUpAccountSharing];
    [a.service waitForQueue];
    [b.service waitForQueue];
    f += Check(ServiceLists(a.service, @[@(kB)], @[]) && ServiceLists(b.service, @[@(kB)], @[]),
               "at launch the stored lists go to the service: A sends to B and receives from nobody");
    f += Check(!Exists(TopPath(kA)) && !Exists(TopPath(kB)), "neither receives from anybody: no inbox");
    Copy(a, @"example-40 alpha");
    [a.service waitForQueue];
    f += Check(!Exists(TopPath(kB)) && [b.op jcListCount] == 0, "B does not receive from A: A's copy does not reach B");
    if (!Click(b, @selector(toggleReceiveFromAccount:), AccountCheckbox(kA, YES)))
        return f + Check(NO, "the Receive checkboxes have an action");
    f += Check(Stored(@[kGuidB], @[kGuidA]), "checking Receive for Account A stores its GeneratedUID in the receive list");
    f += Check(ServiceLists(b.service, @[@(kB)], @[@(kA)]) && Exists(FromPath(kB, kA)) && [[[NSFileManager defaultManager]
               contentsOfDirectoryAtPath:TopPath(kB) error:NULL] count] == 1, "B now keeps a folder for A, only for A");
    Copy(a, @"example-41 beta");
    [a.service waitForQueue];
    [b.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(b) isEqualToString:@"example-41 beta"]; }, 3.0), "A's next copy reaches B");
    // A receives from B, but B does not send to A.
    Click(a, @selector(toggleReceiveFromAccount:), AccountCheckbox(kB, YES));
    NSArray *both = [@[kGuidA, kGuidB] sortedArrayUsingSelector:@selector(compare:)];
    f += Check(Stored(@[kGuidB], both) && ServiceLists(a.service, @[@(kB)], @[@(kA), @(kB)]) && Exists(FromPath(kA, kB)),
               "checking Receive for Account B gives A a folder for B");
    Copy(b, @"example-42 gamma");
    [b.service waitForQueue];
    [a.service pickUp];
    [a.service waitForQueue];
    Spin(0.3);
    f += Check(Waiting(kA, kB) == 0 && ![Top(a) isEqualToString:@"example-42 gamma"],
               "B does not send to A: B's copy does not reach A although A receives from B");
    if (!Click(b, @selector(toggleSendToAccount:), AccountCheckbox(kA, YES)))
        return f + Check(NO, "the Send checkboxes have an action");
    f += Check(Stored(both, both) && ServiceLists(b.service, @[@(kA), @(kB)], @[@(kA), @(kB)]),
               "checking Send for Account A stores its GeneratedUID in the send list");
    Copy(b, @"example-43 delta");
    [b.service waitForQueue];
    [a.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(a) isEqualToString:@"example-43 delta"]; }, 3.0), "now B's copy reaches A: both ways");
    // A stops sending to B while a copy waits there.
    Copy(a, @"example-44 epsilon");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A's copy waits for B");
    Click(a, @selector(toggleSendToAccount:), AccountCheckbox(kB, NO));
    f += Check(Stored(@[kGuidA], both) && ServiceLists(a.service, @[@(kA)], @[@(kA), @(kB)]),
               "unchecking Send for Account B stores that");
    f += Check(Waiting(kB, kA) == 0 && Exists(FromPath(kB, kA)) && Exists(FromPath(kA, kB)),
               "A's copy waiting for B is withdrawn; B's folder for A and A's inbox stay");
    Copy(a, @"example-45 zeta");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 0, "A sends nothing to B any more");
    // B stops receiving from A while a copy waits.
    Click(a, @selector(toggleSendToAccount:), AccountCheckbox(kB, YES));
    Copy(a, @"example-46 eta");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A sends to B again: its copy waits for B");
    Click(b, @selector(toggleReceiveFromAccount:), AccountCheckbox(kA, NO));
    f += Check(Stored(both, @[kGuidB]) && ServiceLists(b.service, @[@(kA), @(kB)], @[@(kB)]),
               "unchecking Receive for Account A stores that");
    f += Check(!Exists(TopPath(kB)), "B's folder for A goes with the copy in it; B, receiving from nobody, keeps no inbox");
    Copy(b, @"example-47 theta");
    [b.service waitForQueue];
    [a.service pickUp];
    f += Check(WaitFor(^BOOL { return [Top(a) isEqualToString:@"example-47 theta"]; }, 3.0), "B still sends to A");
    [b.service pickUp];
    [b.service waitForQueue];
    Spin(0.3);
    f += Check(![Top(b) isEqualToString:@"example-46 eta"], "B never takes in the copy that waited when it stopped receiving");
    StoreChoice(@[], @[]);
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.service stop];
    [b.service stop];
    return f;
}

// A click looks the accounts up once: when the lookup works for the click and
// fails right after it, the click still reaches the service. Unchecking Send
// withdraws A's copy waiting at B and sends nothing more; unchecking Receive
// removes B's folder in A's inbox and takes nothing more in.
static int RunLookupFailsAfterTheClick(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA), b = Make(kB);
    [a.service setWatchesSenderFolders:NO];
    [b.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    NSArray *both = [@[kGuidA, kGuidB] sortedArrayUsingSelector:@selector(compare:)];
    StoreChoice(both, both);
    [a.controller setUpAccountSharing];
    [b.controller setUpAccountSharing];
    [a.service waitForQueue];
    [b.service waitForQueue];
    Copy(a, @"example-80 alpha");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1, "A's copy waits for B");
    gFailLookup = gLookups + 2;   // the click's lookup works, the next one fails
    if (!Click(a, @selector(toggleSendToAccount:), AccountCheckbox(kB, NO)))
        return f + Check(NO, "the Send checkboxes have an action");
    gFailLookup = 0;
    f += Check(Stored(@[kGuidA], both) && ServiceLists(a.service, @[@(kA)], @[@(kA), @(kB)]),
               "the click is stored and reaches the service although the lookup after it fails");
    f += Check(Waiting(kB, kA) == 0, "A's copy waiting at B is withdrawn");
    Copy(a, @"example-81 beta");
    [a.service waitForQueue];
    f += Check(Waiting(kB, kA) == 0, "A sends nothing more to B");
    Copy(b, @"example-82 gamma");
    [b.service waitForQueue];
    f += Check(Waiting(kA, kB) == 1, "B's copy waits for A");
    gFailLookup = gLookups + 2;
    Click(a, @selector(toggleReceiveFromAccount:), AccountCheckbox(kB, NO));
    gFailLookup = 0;
    f += Check(Stored(@[kGuidA], @[kGuidA]) && ServiceLists(a.service, @[@(kA)], @[@(kA)]),
               "unchecking Receive is stored and reaches the service too");
    f += Check(!Exists(FromPath(kA, kB)), "B's folder in A's inbox goes with B's copy in it");
    Copy(b, @"example-83 delta");
    [b.service waitForQueue];
    [a.service pickUp];
    [a.service waitForQueue];
    Spin(0.3);
    f += Check(![Top(a) isEqualToString:@"example-82 gamma"] && ![Top(a) isEqualToString:@"example-83 delta"],
               "A takes in nothing from B");
    StoreChoice(@[], @[]);
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.service stop];
    [b.service stop];
    return f;
}

// Unchecking Send for B while A receives from nobody withdraws A's copy
// waiting at B, and B takes in nothing.
static int RunSendOnlyUntick(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA), b = Make(kB);
    [a.service setWatchesSenderFolders:NO];
    [b.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[kGuidB], @[kGuidA]);       // A sends to B; B receives from A; A receives from nobody
    [a.controller setUpAccountSharing];
    [b.controller setUpAccountSharing];
    [a.service waitForQueue];
    [b.service waitForQueue];
    Copy(a, @"example-84 alpha");
    [a.service waitForQueue];
    f += Check(!Exists(TopPath(kA)) && Waiting(kB, kA) == 1, "A receives from nobody; its copy waits for B");
    if (!Click(a, @selector(toggleSendToAccount:), AccountCheckbox(kB, NO)))
        return f + Check(NO, "the Send checkboxes have an action");
    f += Check(Stored(@[], @[kGuidA]) && ServiceLists(a.service, @[], @[@(kA)]), "unchecking Send for B is stored and passed on");
    f += Check(Waiting(kB, kA) == 0, "A's copy waiting at B is withdrawn");
    [b.service pickUp];
    [b.service waitForQueue];
    Spin(0.3);
    f += Check([b.op jcListCount] == 0, "B takes in nothing");
    StoreChoice(@[], @[]);
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.service stop];
    [b.service stop];
    return f;
}

// The choice is stored by the account's GeneratedUID, so an account that
// later gets a deleted account's UID does not inherit it, in either list.
static int RunChoiceFollowsTheAccount(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    Participant a = Make(kA);
    [a.service setWatchesSenderFolders:NO];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[kGuidB], @[kGuidB]);
    [a.controller setUpAccountSharing];
    [a.service waitForQueue];
    f += Check(ServiceLists(a.service, @[@(kB)], @[@(kB)]) && Exists(FromPath(kA, kB)), "A sends to B and receives from B");
    // B's account is deleted and a new account gets UID 7002.
    [gAccounts release];
    gAccounts = [@[@{@"uid": @(kA), @"name": @"Account A", @"guid": kGuidA},
                   @{@"uid": @(kB), @"name": @"Account New", @"guid": kGuidNewB},
                   @{@"uid": @(kUnopted), @"name": @"Account U", @"guid": kGuidU}] retain];
    [a.controller accountSessionDidBecomeActive:nil];
    [a.service waitForQueue];
    f += Check(ServiceLists(a.service, @[], @[]) && !Exists(TopPath(kA)),
               "the new account with B's old UID is not chosen: back at the console A drops its inbox for it");
    f += Check(Stored(@[kGuidB], @[kGuidB]), "the stored lists still name the old account only");
    NSArray *both = [@[kGuidB, kGuidNewB] sortedArrayUsingSelector:@selector(compare:)];
    if (![a.controller respondsToSelector:@selector(toggleSendToAccount:)] || ![a.controller respondsToSelector:@selector(toggleReceiveFromAccount:)])
        return f + Check(NO, "the Send and Receive checkboxes have actions");
    Click(a, @selector(toggleSendToAccount:), AccountCheckbox(kB, YES));
    f += Check(Stored(both, @[kGuidB]) && ServiceLists(a.service, @[@(kB)], @[]) && !Exists(TopPath(kA)),
               "checking Send for the new account stores its own GeneratedUID; A sends to it but does not receive yet");
    Click(a, @selector(toggleReceiveFromAccount:), AccountCheckbox(kB, YES));
    f += Check(Stored(both, both) && ServiceLists(a.service, @[@(kB)], @[@(kB)]) && Exists(FromPath(kA, kB)),
               "checking Receive for it too gives A a folder for it");
    FCAccountCheckbox *send = AccountCheckbox(4999, YES), *receive = AccountCheckbox(4999, YES);
    Click(a, @selector(toggleSendToAccount:), send);
    Click(a, @selector(toggleReceiveFromAccount:), receive);
    f += Check(Stored(both, both), "a checkbox for a UID that is no login account stores nothing, in either list");
    f += Check(send->state == NSControlStateValueOff && receive->state == NSControlStateValueOff,
               "and the click is undone on both checkboxes");
    [gAccounts release];
    gAccounts = [DefaultAccounts() retain];
    StoreChoice(@[], @[]);
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
    [a.service stop];
    return f;
}

// While the account lookup fails (nil) nothing changes: the service keeps
// its accounts (nothing wiped or withdrawn) and a click on Send or Receive
// changes nothing and is undone; at launch sharing waits for a working lookup
// instead of running with no account or with every account.
static int RunLookupFailure(void) {
    int f = 0;
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setBool:YES forKey:@"shareClippingsAcrossAccounts"];
    StoreChoice(@[kGuidB], @[kGuidB]);
    // (a) Flycut starts while the lookup fails.
    [gAccounts release];
    gAccounts = nil;
    Participant a = Make(kA);
    [a.service setWatchesSenderFolders:NO];
    [a.controller setUpAccountSharing];
    [a.service waitForQueue];
    f += Check(Stored(@[kGuidB], @[kGuidB]), "with the account lookup failing the stored lists stay as they are");
    f += Check(![a.service running] && ServiceLists(a.service, nil, nil) && !Exists(TopPath(kA)),
               "and sharing waits: it runs neither with no account nor with every account");
    [a.controller toggleShareClippingsAcrossAccounts:nil];
    [a.service waitForQueue];
    f += Check(![a.service running] && ServiceLists(a.service, nil, nil) && !Exists(TopPath(kA)),
               "the sharing checkbox does not start it meanwhile either");
    // (b) The lookup works at the next return to the console.
    gAccounts = [DefaultAccounts() retain];
    [a.controller accountSessionDidBecomeActive:nil];
    [a.service waitForQueue];
    f += Check([a.service running] && ServiceLists(a.service, @[@(kB)], @[@(kB)]) && Exists(FromPath(kA, kB)),
               "once the lookup works sharing starts with the stored lists");
    // (c) Running, with copies waiting both ways; the lookup fails at a return.
    Participant b = Make(kB);
    [b.service setWatchesSenderFolders:NO];
    [b.service start];
    [b.service waitForQueue];
    Copy(a, @"example-92 alpha");
    [a.service waitForQueue];
    Copy(b, @"example-93 beta");
    [b.service waitForQueue];
    f += Check(Waiting(kB, kA) == 1 && Waiting(kA, kB) == 1, "a copy waits in each direction");
    [gAccounts release];
    gAccounts = nil;
    [a.controller accountSessionDidBecomeActive:nil];
    [a.service waitForQueue];
    f += Check(ServiceLists(a.service, @[@(kB)], @[@(kB)]) && Exists(FromPath(kA, kB)) && Waiting(kB, kA) == 1,
               "a failed lookup at a return keeps the choice: A's inbox stays, its copy for B is not withdrawn");
    f += Check(WaitFor(^BOOL { return [Top(a) isEqualToString:@"example-93 beta"]; }, 3.0), "and A still takes in B's copy");
    FCAccountCheckbox *send = AccountCheckbox(kB, NO), *receive = AccountCheckbox(kB, NO);
    if (!Click(a, @selector(toggleSendToAccount:), send) || !Click(a, @selector(toggleReceiveFromAccount:), receive))
        return f + Check(NO, "the Send and Receive checkboxes have actions");
    f += Check(Stored(@[kGuidB], @[kGuidB]) && ServiceLists(a.service, @[@(kB)], @[@(kB)]) && Exists(FromPath(kA, kB))
               && Waiting(kB, kA) == 1, "and a click on Send or Receive changes nothing meanwhile");
    f += Check(send->state == NSControlStateValueOn && receive->state == NSControlStateValueOn,
               "and each click is undone on its checkbox");
    [gAccounts release];
    gAccounts = [DefaultAccounts() retain];
    [a.service stop];
    [b.service stop];
    StoreChoice(@[], @[]);
    [defaults setBool:NO forKey:@"shareClippingsAcrossAccounts"];
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
                                @"toggle": [NSValue valueWithPointer:RunToggle],
                                @"diagnostics-pause": [NSValue valueWithPointer:RunDiagnosticsPausesPickup],
                                @"toggle-withdraws": [NSValue valueWithPointer:RunToggleWithdraws],
                                @"choose-accounts": [NSValue valueWithPointer:RunChooseAccounts],
                                @"pasteboard-guard": [NSValue valueWithPointer:RunPasteboardGuard],
                                @"launch-pasteboard-guard": [NSValue valueWithPointer:RunLaunchPasteboardGuard],
                                @"tracking-pause": [NSValue valueWithPointer:RunTrackingPausePausesPickup],
                                @"choice-follows-account": [NSValue valueWithPointer:RunChoiceFollowsTheAccount],
                                @"setup-failure-note": [NSValue valueWithPointer:RunSetupFailureNote],
                                @"kept-pasteboard": [NSValue valueWithPointer:RunKeptPasteboard],
                                @"lookup-failure": [NSValue valueWithPointer:RunLookupFailure],
                                @"lookup-fails-after-click": [NSValue valueWithPointer:RunLookupFailsAfterTheClick],
                                @"send-only-untick": [NSValue valueWithPointer:RunSendOnlyUntick]};
        NSValue *run = [modes objectForKey:[NSString stringWithUTF8String:argv[1]]];
        if (run == nil) return 3;
        int failures = ((int (*)(void))[run pointerValue])();
        FCTraceReport();
        printf("RESULT failures=%d\n", failures);
        fflush(stdout);
        return failures == 0 ? 0 : 1;
    }
}
