// Native fixture for AccountShareServiceTests.py.
//
// Compiles the real FlycutAccountShareService, the real engine (through
// AccountShareTrace.h: traced mutations, simulated file owners) and the real
// FlycutOperator as the engine's filter, and runs simulated accounts A = 7001 and
// B = 7002 (plus 7003, an account that never turns sharing on) as two services in
// one process, each with its own queue, inside an injected scratch root. No real
// account owns these UIDs; the fixture refuses to run if one does. Defaults are an
// in-memory fake; no pasteboard, app or network is used. Clipping texts are dummy
// strings and are never printed.

#import <Cocoa/Cocoa.h>
#include <pwd.h>
#include <stdlib.h>
#include <sys/xattr.h>

@interface FCFakeDefaults : NSObject {
    NSMutableDictionary *values;
}
+ (FCFakeDefaults *)standardUserDefaults;
- (void)registerDefaults:(NSDictionary *)registration;
- (id)objectForKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
- (NSDictionary *)dictionaryForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSURL *)URLForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (BOOL)synchronize;
@end

@implementation FCFakeDefaults
+ (FCFakeDefaults *)standardUserDefaults {
    static FCFakeDefaults *shared = nil;
    if (shared == nil) {
        shared = [[FCFakeDefaults alloc] init];
        shared->values = [[NSMutableDictionary alloc] init];
    }
    return shared;
}
- (void)registerDefaults:(NSDictionary *)registration {
    for (id key in registration)
        if ([values objectForKey:key] == nil)
            [values setObject:[registration objectForKey:key] forKey:key];
}
- (id)objectForKey:(NSString *)key { @synchronized (self) { return [[[values objectForKey:key] retain] autorelease]; } }
- (id)valueForKey:(NSString *)key { return [self objectForKey:key]; }
- (NSString *)stringForKey:(NSString *)key { return [self objectForKey:key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return [self objectForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [[self objectForKey:key] integerValue]; }
- (BOOL)boolForKey:(NSString *)key { return [[self objectForKey:key] boolValue]; }
- (NSURL *)URLForKey:(NSString *)key { return nil; }
- (void)setObject:(id)value forKey:(NSString *)key {
    @synchronized (self) { if (value) [values setObject:value forKey:key]; else [values removeObjectForKey:key]; }
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (BOOL)synchronize { return YES; }
@end

static NSArray *FCFakeSearchPath(NSSearchPathDirectory directory, NSSearchPathDomainMask mask, BOOL expand) {
    return @[NSTemporaryDirectory()];
}

#define NSUserDefaults FCFakeDefaults
#define NSSearchPathForDirectoriesInDomains FCFakeSearchPath
#define DLog(...) do {} while (0)

#include "FlycutEngine/FlycutClipping.m"
#include "FlycutEngine/FlycutStore.m"
#include "FlycutOperator.m"

@implementation FlycutImageStore
+ (FlycutImageStore *)sharedStore {
    fprintf(stderr, "FAIL: fixture reached the on-disk image store\n");
    abort();
}
+ (NSString *)fileExtensionForType:(NSString *)uti { return @"tiff"; }
@end

#undef NSUserDefaults
#undef NSSearchPathForDirectoriesInDomains

#include "AccountShareTrace.h"

// The directory lookup of the login accounts can be made to fail.
#import <CoreServices/CoreServices.h>
#include <membership.h>
static BOOL gFailQueryCreate = NO, gFailQueryExecute = NO, gFailGeneratedUID = NO;
static CSIdentityQueryRef FCT_CSIdentityQueryCreate(CFAllocatorRef allocator, CSIdentityClass identityClass,
                                                    CSIdentityAuthorityRef authority) {
    return gFailQueryCreate ? NULL : CSIdentityQueryCreate(allocator, identityClass, authority);
}
static Boolean FCT_CSIdentityQueryExecute(CSIdentityQueryRef query, CSIdentityQueryFlags flags, CFErrorRef *error) {
    return gFailQueryExecute ? false : CSIdentityQueryExecute(query, flags, error);
}
static int FCT_mbr_uid_to_uuid(uid_t uid, unsigned char *uu) {
    return gFailGeneratedUID ? EIO : mbr_uid_to_uuid(uid, uu);
}
// The next gPasswdErrors passwd lookups fail with an error (the directory
// cannot be asked), once the next gPasswdSkip ones went through; the next
// gPasswdMissing ones find no entry. A buffer smaller than gPasswdNeed bytes
// gets ERANGE (a record that large); gPasswdLargest is the largest one seen.
static int gPasswdErrors = 0, gPasswdMissing = 0, gPasswdSkip = 0;
static size_t gPasswdNeed = 0, gPasswdLargest = 0;
static int FCT_getpwuid_r(uid_t uid, struct passwd *entry, char *buffer, size_t size, struct passwd **found) {
    if (size > gPasswdLargest)
        gPasswdLargest = size;
    if (size < gPasswdNeed) {
        *found = NULL;
        return ERANGE;
    }
    if (gPasswdSkip > 0) {
        gPasswdSkip--;
        return getpwuid_r(uid, entry, buffer, size, found);
    }
    if (gPasswdErrors > 0) {
        gPasswdErrors--;
        *found = NULL;
        return EIO;
    }
    if (gPasswdMissing > 0) {
        gPasswdMissing--;
        *found = NULL;
        return 0;
    }
    return getpwuid_r(uid, entry, buffer, size, found);
}
#define CSIdentityQueryCreate(...) FCT_CSIdentityQueryCreate(__VA_ARGS__)
#define CSIdentityQueryExecute(...) FCT_CSIdentityQueryExecute(__VA_ARGS__)
#define mbr_uid_to_uuid(...) FCT_mbr_uid_to_uuid(__VA_ARGS__)
#define getpwuid_r(...) FCT_getpwuid_r(__VA_ARGS__)
// What the service logs with NSLog is kept here, never printed.
static NSMutableArray *gLogged = nil;
static void FCT_NSLog(NSString *format, ...) NS_FORMAT_FUNCTION(1, 2);
static void FCT_NSLog(NSString *format, ...) {
    va_list args;
    va_start(args, format);
    NSString *line = [[NSString alloc] initWithFormat:format arguments:args];
    va_end(args);
    @synchronized ([NSNull null]) {
        if (gLogged == nil)
            gLogged = [[NSMutableArray alloc] init];
        [gLogged addObject:line];
    }
    [line release];
}
static NSArray *Logged(void) {
    @synchronized ([NSNull null]) { return gLogged != nil ? [[gLogged copy] autorelease] : @[]; }
}
static NSUInteger LoggedWith(NSString *prefix) {
    NSUInteger n = 0;
    for (NSString *line in Logged())
        if ([line hasPrefix:prefix]) n++;
    return n;
}
#define NSLog(...) FCT_NSLog(__VA_ARGS__)
#include "FlycutEngine/FlycutAccountShareService.m"
#undef NSLog
#undef CSIdentityQueryCreate
#undef CSIdentityQueryExecute
#undef mbr_uid_to_uuid
#undef getpwuid_r

// ---------------------------------------------------------------------------

enum { kA = 7001, kB = 7002, kUnopted = 7003 };

static NSString *gShared = nil;
static FlycutOperator *gOperator = nil;
static BOOL gActive[3] = { YES, YES, YES };   // A, B, 7003: session on the console?

@interface FCRecorder : NSObject <FlycutAccountShareServiceDelegate> {
@public
    NSMutableArray *received;
    NSMutableArray *pasteboard;
    BOOL offMain;
    int stateChanges;
}
@end

@implementation FCRecorder
- (id)init {
    if ((self = [super init])) {
        received = [[NSMutableArray alloc] init];
        pasteboard = [[NSMutableArray alloc] init];
    }
    return self;
}
- (void)accountShareService:(FlycutAccountShareService *)service didReceiveClipping:(FlycutSharedClipping *)clipping {
    if (![NSThread isMainThread]) offMain = YES;
    [received addObject:clipping];
}
- (void)accountShareService:(FlycutAccountShareService *)service shouldPutOnPasteboard:(FlycutSharedClipping *)clipping {
    if (![NSThread isMainThread]) offMain = YES;
    [pasteboard addObject:clipping];
}
- (void)accountShareServiceDidChangeState:(FlycutAccountShareService *)service {
    if (![NSThread isMainThread]) offMain = YES;
    stateChanges++;
}
@end

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

// Lets the service's queue finish, then the main-thread deliveries it queued.
static void Settle(FlycutAccountShareService *service) {
    [service waitForQueue];
    Spin(0.1);
}

static int SlotOf(uid_t uid) { return uid == kA ? 0 : (uid == kB ? 1 : 2); }

static FlycutAccountShareService *Service(uid_t uid, FCRecorder *recorder) {
    int slot = SlotOf(uid);
    FlycutAccountShareService *service = [[FlycutAccountShareService alloc]
        initWithEngine:FCTracedEngineFor(gShared, uid, (id<FlycutAccountShareFilter>)gOperator)
              accounts:^NSArray *{ return @[@(kA), @(kB), @(kUnopted)]; }
       sessionIsActive:^BOOL { return gActive[slot]; }];
    [service setDelegate:recorder];
    [service setSafetyInterval:3600];
    return [service autorelease];
}

// A service with its own account list (nil: the lookup failed).
static FlycutAccountShareService *ServiceWithAccounts(uid_t uid, FCRecorder *recorder, FlycutAccountShareAccountList accounts) {
    int slot = SlotOf(uid);
    FlycutAccountShareService *service = [[FlycutAccountShareService alloc]
        initWithEngine:FCTracedEngineFor(gShared, uid, (id<FlycutAccountShareFilter>)gOperator)
              accounts:accounts
       sessionIsActive:^BOOL { return gActive[slot]; }];
    [service setDelegate:recorder];
    [service setSafetyInterval:3600];
    return [service autorelease];
}

// A service whose engine's clock runs `offset` seconds off the system clock, so
// its copies look as old as that to every other account.
static FlycutAccountShareService *ServiceAt(uid_t uid, FCRecorder *recorder, NSTimeInterval offset) {
    int slot = SlotOf(uid);
    FlycutAccountShareClock clock = ^NSTimeInterval { return [[NSDate date] timeIntervalSince1970] + offset; };
    FlycutAccountShareService *service = [[FlycutAccountShareService alloc]
        initWithEngine:FCTracedEngineWithClock(gShared, uid, (id<FlycutAccountShareFilter>)gOperator, clock)
              accounts:^NSArray *{ return @[@(kA), @(kB), @(kUnopted)]; }
       sessionIsActive:^BOOL { return gActive[slot]; }];
    [service setDelegate:recorder];
    [service setSafetyInterval:3600];
    return [service autorelease];
}

static NSString *TopPath(uid_t recipient) {
    return [gShared stringByAppendingPathComponent:[NSString stringWithFormat:@".flycut-share-%u", recipient]];
}

static NSString *FromPath(uid_t recipient, uid_t sender) {
    return [TopPath(recipient) stringByAppendingPathComponent:[NSString stringWithFormat:@"from-%u", sender]];
}

static NSArray *Entries(NSString *path) {
    return [[NSFileManager defaultManager] contentsOfDirectoryAtPath:path error:NULL];
}

static BOOL Exists(NSString *path) {
    struct stat st;
    return lstat([path fileSystemRepresentation], &st) == 0;
}

static NSArray *PlainTypes(void) { return @[@"public.utf8-plain-text"]; }

static void Offer(FlycutAccountShareService *service, NSString *text) {
    [service offerText:text ofType:@"public.utf8-plain-text" availableTypes:PlainTypes() richData:nil appName:@"Example App"];
}

static NSString *TextOf(id clipping) { return [(FlycutSharedClipping *)clipping text]; }

// ---------------------------------------------------------------------------

static int RunStartPreparesAllAccounts(void) {
    int f = 0;
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b = Service(kB, rb);
    f += Check(![b running] && !Exists(TopPath(kB)), "a new service touches nothing before it is started");
    [b start];
    Settle(b);
    f += Check([b running], "the service runs after -start");
    f += Check(Exists(FromPath(kB, kA)) && Exists(FromPath(kB, kUnopted)) && !Exists(FromPath(kB, kB))
               && [Entries(TopPath(kB)) count] == 2,
               "starting prepares one folder for every other account, none for this one");
    NSNumber *excluded = nil;
    [[NSURL fileURLWithPath:TopPath(kB) isDirectory:YES] getResourceValue:&excluded forKey:NSURLIsExcludedFromBackupKey error:NULL];
    f += Check([excluded boolValue], "the inbox is excluded from Time Machine backups");
    f += Check(!Exists(TopPath(kA)) && !Exists(TopPath(kUnopted)), "no inbox is made for the other accounts");
    [b stop];
    return f;
}

static int RunDeliverByFolderWatch(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    NSDictionary *rich = @{@"public.rtf": [@"{\\rtf1 example-01}" dataUsingEncoding:NSUTF8StringEncoding]};
    [a offerText:@"example-01 alpha" ofType:@"public.utf8-plain-text"
  availableTypes:@[@"public.utf8-plain-text", @"public.rtf"] richData:rich appName:@"Example App"];
    BOOL arrived = WaitFor(^BOOL { return [rb->received count] == 1; }, 3.0);
    f += Check(arrived, "B gets A's copy through the folder watch (safety timer one hour)");
    if (arrived) {
        FlycutSharedClipping *c = [rb->received objectAtIndex:0];
        f += Check([[c text] isEqualToString:@"example-01 alpha"] && [c senderUID] == kA
                   && [[[c richData] objectForKey:@"public.rtf"] isEqualToData:[rich objectForKey:@"public.rtf"]]
                   && [[c appName] isEqualToString:@"Example App"], "text, sender, rich text and app arrive");
    }
    f += Check(!rb->offMain, "the delegate is called on the main thread");
    f += Check([rb->pasteboard count] == 0, "B is on the console: the copy only goes to the list");
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "B deletes the file after pickup");
    f += Check([ra->received count] == 0, "A gets nothing back");
    [a stop];
    [b stop];
    return f;
}

static int RunSafetyTimer(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    Offer(a, @"example-02 beta");
    Settle(a);
    Spin(1.5);
    f += Check([rb->received count] == 0, "without the folder watch nothing arrives before the safety pickup");
    [b pickUp];
    f += Check(WaitFor(^BOOL { return [rb->received count] == 1; }, 3.0), "-pickUp takes the waiting copy in");
    [b stop];
    FlycutAccountShareService *b2 = Service(kB, rb);
    [b2 setWatchesSenderFolders:NO];
    [b2 setSafetyInterval:0.3];
    [b2 start];
    Settle(b2);
    Offer(a, @"example-03 gamma");
    f += Check(WaitFor(^BOOL { return [rb->received count] == 2; }, 3.0), "the safety timer picks up without the folder watch");
    [a stop];
    [b2 stop];
    return f;
}

static int RunAwayThenActive(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    gActive[1] = NO;
    Offer(a, @"example-04 delta");
    f += Check(WaitFor(^BOOL { return [rb->received count] == 1; }, 3.0), "B, in the background, gets the first copy");
    Offer(a, @"example-05 epsilon");
    f += Check(WaitFor(^BOOL { return [rb->received count] == 2; }, 3.0), "and the second");
    Spin(0.3);
    f += Check([rb->pasteboard count] == 0, "nothing goes to B's pasteboard while B is away");
    gActive[1] = YES;
    [b sessionDidBecomeActive];
    f += Check(WaitFor(^BOOL { return [rb->pasteboard count] == 1; }, 3.0)
               && [TextOf([rb->pasteboard lastObject]) isEqualToString:@"example-05 epsilon"],
               "when B comes to the console the newest copy goes to its pasteboard");
    [b sessionDidBecomeActive];
    Settle(b);
    f += Check([rb->pasteboard count] == 1 && [rb->received count] == 2, "only once, and nothing is added twice");
    Offer(a, @"example-06 zeta");
    f += Check(WaitFor(^BOOL { return [rb->received count] == 3; }, 3.0) && [rb->pasteboard count] == 1,
               "a copy that arrives while B is in front only goes to the list");
    [a stop];
    [b stop];
    gActive[1] = YES;
    return f;
}

static int RunLaunchPickup(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    [b stop];
    f += Check(Exists(FromPath(kB, kA)), "-stop keeps the inbox");
    Offer(a, @"example-07 eta");
    Offer(a, @"example-08 theta");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 2, "copies wait in B's inbox while B's Flycut is not running");
    Spin(0.5);
    f += Check([rb->received count] == 0, "a stopped service takes nothing in");
    FCRecorder *rb2 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b2 = Service(kB, rb2);
    [b2 start];
    f += Check(WaitFor(^BOOL { return [rb2->received count] == 2 && [rb2->pasteboard count] == 1; }, 3.0)
               && [TextOf([rb2->pasteboard lastObject]) isEqualToString:@"example-08 theta"],
               "at launch on the console B takes both in and puts the newest on its pasteboard");
    [b2 stop];
    gActive[1] = NO;
    Offer(a, @"example-09 iota");
    Settle(a);
    FCRecorder *rb3 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b3 = Service(kB, rb3);
    [b3 start];
    f += Check(WaitFor(^BOOL { return [rb3->received count] == 1; }, 3.0) && [rb3->pasteboard count] == 0,
               "at launch in the background B takes it in without touching the pasteboard");
    gActive[1] = YES;
    [b3 sessionDidBecomeActive];
    f += Check(WaitFor(^BOOL { return [rb3->pasteboard count] == 1; }, 3.0), "and puts it there when it comes to the console");
    [a stop];
    [b3 stop];
    return f;
}

static int RunSenderConditions(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [b start];
    Settle(b);
    Offer(a, @"example-10 kappa");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "a service that was never started sends nothing");
    [a start];
    Settle(a);
    gActive[0] = NO;
    Offer(a, @"example-11 lambda");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "nothing is sent while this session is not on the console");
    gActive[0] = YES;
    Offer(a, @"Ab3$efGh9!xY");
    [a offerText:@"example-12 mu" ofType:@"public.utf8-plain-text"
  availableTypes:@[@"public.utf8-plain-text", @"org.nspasteboard.ConcealedType"] richData:nil appName:nil];
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "the operator's sharing rule refuses a password and a concealed copy");
    f += Check(!Exists(TopPath(kUnopted)), "an account that never turned sharing on gets no inbox from anyone");
    [a stop];
    Offer(a, @"example-13 nu");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "nothing is sent after -stop");
    Spin(0.3);
    f += Check([rb->received count] == 0, "B got nothing");
    [b stop];
    return f;
}

static int RunWipe(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    gActive[1] = NO;
    Offer(a, @"example-14 xi");
    Settle(a);
    [b stopAndWipeInbox];
    Settle(b);
    f += Check(![b running] && !Exists(TopPath(kB)), "turning sharing off deletes B's inbox with what waited in it");
    f += Check(Exists(TopPath(kA)), "A's inbox stays");
    Offer(a, @"example-15 omicron");
    Settle(a);
    f += Check(!Exists(TopPath(kB)), "A cannot write to B any more");
    gActive[1] = YES;
    [b sessionDidBecomeActive];
    [b pickUp];
    Settle(b);
    f += Check([rb->received count] == 0 && [rb->pasteboard count] == 0, "B takes nothing in after it turned sharing off");
    [a stop];
    return f;
}

// Turning sharing off while the inbox cannot be deleted (another account
// holds the name for a moment): it is deleted once it can, while sharing
// stays off; turned on again before the next try, the inbox stays.
static int RunOffWipeRetried(void) {
    int f = 0;
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    [b setSafetyInterval:0.3];
    [b start];
    Settle(b);
    NSString *top = TopPath(kB);
    f += Check(Exists(FromPath(kB, kA)), "B has an inbox");
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    [b stopAndWipeInbox];
    Settle(b);
    f += Check(![b running] && Exists(top), "while another account holds the name, turning sharing off cannot delete the inbox");
    Spin(0.9);
    f += Check(Exists(top), "held over the next two tries (0.3 s apart), the inbox is still there");
    NSArray *logged = Logged();
    f += Check(LoggedWith(@"Flycut: the inbox for other accounts cannot be deleted yet (error ") == 1 && [logged count] == 1
               && [[logged objectAtIndex:0] rangeOfString:@"/"].location == NSNotFound,
               "the failed delete is logged once, not at every try, and the line names no path");
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], kB);
    f += Check(WaitFor(^BOOL { return !Exists(top); }, 3.0) && ![b running],
               "it is deleted once it can, after several failed tries, and sharing stays off");
    [b start];
    Settle(b);
    f += Check(Exists(FromPath(kB, kA)), "turned on again, B has its inbox");
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    [b stopAndWipeInbox];
    Settle(b);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], kB);
    [b start];
    Settle(b);
    Spin(1.0);
    f += Check([b running] && Exists(FromPath(kB, kA)), "turned on again before the next try, the inbox stays");
    f += Check(LoggedWith(@"Flycut: the inbox for other accounts cannot be deleted yet (error ") == 1,
               "a delete that fails again after the same launch is not logged again");
    [b stop];
    return f;
}

@interface FlycutAccountShareService (LeftoverTesting)
- (void)wipeLeftoverInbox;
@end

// At launch with sharing off an inbox left from an earlier run goes, also when
// the first try fails; while sharing runs its inbox is no leftover.
static int RunLeftoverWipe(void) {
    int f = 0;
    FCRecorder *r1 = [[[FCRecorder alloc] init] autorelease], *r2 = [[[FCRecorder alloc] init] autorelease];
    FCRecorder *r3 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *before = Service(kB, r1);
    [before setWatchesSenderFolders:NO];
    [before start];
    Settle(before);
    [before stop];
    Settle(before);
    NSString *top = TopPath(kB);
    f += Check(Exists(FromPath(kB, kA)), "quitting leaves the inbox for the next launch");
    FlycutAccountShareService *b = Service(kB, r2);
    if (![b respondsToSelector:@selector(wipeLeftoverInbox)])
        return f + Check(NO, "the service can delete an inbox left over while sharing is off");
    [b setSafetyInterval:0.3];
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    [b wipeLeftoverInbox];
    Settle(b);
    f += Check(![b running] && Exists(top), "while another account holds the name, the inbox left over cannot be deleted");
    Spin(0.9);
    f += Check(Exists(top), "held over the next two tries (0.3 s apart), it is still there");
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], kB);
    f += Check(WaitFor(^BOOL { return !Exists(top); }, 3.0), "it is deleted once it can, after several failed tries");
    f += Check(![b running] && [r2->received count] == 0 && [r2->pasteboard count] == 0, "sharing stays off and takes nothing in");
    FlycutAccountShareService *c = Service(kB, r3);
    [c setWatchesSenderFolders:NO];
    [c setSafetyInterval:0.3];
    [c start];
    Settle(c);
    [c wipeLeftoverInbox];
    Settle(c);
    Spin(0.5);
    f += Check([c running] && Exists(FromPath(kB, kA)), "while sharing runs, its inbox is not deleted as a leftover");
    [c stop];
    return f;
}

static int RunAccountRule(void) {
    int f = 0;
    NSDictionary *(^Record)(id, BOOL, BOOL, NSString *, NSString *) = ^NSDictionary *(id uid, BOOL hidden, BOOL enabled, NSString *shell, NSString *home) {
        return @{@"uid": uid, @"hidden": @(hidden), @"enabled": @(enabled), @"shell": shell, @"home": home};
    };
    NSArray *records = @[Record(@7001, NO, YES, @"/bin/zsh", @"/Users/example-a"),
                         Record(@7002, NO, YES, @"/bin/bash", @"/Users/example-b"),
                         Record(@7001, NO, YES, @"/bin/zsh", @"/Users/example-a"),
                         Record(@500, NO, YES, @"/bin/zsh", @"/Users/example-low"),
                         Record(@201, NO, YES, @"/bin/zsh", @"/Users/Guest"),
                         Record(@248, YES, YES, @"/usr/bin/false", @"/var/setup"),
                         Record(@7004, YES, YES, @"/bin/zsh", @"/Users/example-hidden"),
                         Record(@7005, NO, NO, @"/bin/zsh", @"/Users/example-disabled"),
                         Record(@7006, NO, YES, @"/usr/bin/false", @"/Users/example-sharing-only"),
                         Record(@7007, NO, YES, @"/sbin/nologin", @"/Users/example-nologin"),
                         Record(@7008, NO, YES, @"", @"/Users/example-noshell"),
                         Record(@7009, NO, YES, @"/bin/zsh", @"/var/empty"),
                         Record(@7010, NO, YES, @"/bin/zsh", @"/Users/Shared"),
                         Record(@7011, NO, YES, @"/bin/zsh", @"/Users/a/b"),
                         Record(@-2, NO, YES, @"/bin/zsh", @"/Users/example-nobody"),
                         Record(@"7012", NO, YES, @"/bin/zsh", @"/Users/example-string")];
    NSArray *uids = [FlycutAccountShareService loginAccountUIDsFromRecords:records];
    f += Check([uids isEqualToArray:@[@7001, @7002]],
               "only enabled, visible accounts with UID >= 501, a login shell and a home in /Users count, once each");
    NSArray *local = [FlycutAccountShareService localLoginAccountUIDs];
    BOOL sane = [local containsObject:@(getuid())];
    for (NSNumber *uid in local)
        if ([uid unsignedIntValue] < 501 || getpwuid([uid unsignedIntValue]) == NULL) sane = NO;
    f += Check(sane, "the local directory lists this account and only accounts with UID >= 501 and a passwd entry");
    f += Check([[FlycutAccountShareService sharedRootPath] isEqualToString:@"/Users/Shared"], "the app's shared root is /Users/Shared");
    return f;
}

// At launch only a copy made in the last 10 minutes replaces the pasteboard; an
// older one only goes to the list. Coming back to the console is unchanged:
// every copy that arrived while away counts, however old.
static int RunLaunchAge(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *old = ServiceAt(kA, ra, -11 * 60), *b = Service(kB, rb);
    [old start];
    [b start];
    Settle(old);
    Settle(b);
    [b stop];
    Settle(b);
    Offer(old, @"example-20 old");
    Settle(old);
    FCRecorder *rb2 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b2 = Service(kB, rb2);
    [b2 start];
    f += Check(WaitFor(^BOOL { return [rb2->received count] == 1; }, 3.0), "at launch B takes in a copy made 11 minutes ago");
    Settle(b2);
    f += Check([rb2->pasteboard count] == 0, "but leaves the pasteboard alone: the copy is older than 10 minutes");
    [b2 stop];
    [old stop];
    Settle(b2);
    Settle(old);
    FlycutAccountShareService *recent = ServiceAt(kA, ra, -9 * 60);
    [recent start];
    Settle(recent);
    Offer(recent, @"example-21 recent");
    Settle(recent);
    FCRecorder *rb3 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b3 = Service(kB, rb3);
    // No folder watch: a sender whose clock runs 11 minutes behind stamps its
    // temporary file that old before the rename, and a pickup in between would
    // take it for a stale leftover. Same-Mac senders share the clock.
    [b3 setWatchesSenderFolders:NO];
    [b3 start];
    f += Check(WaitFor(^BOOL { return [rb3->received count] == 1 && [rb3->pasteboard count] == 1; }, 3.0)
               && [TextOf([rb3->pasteboard lastObject]) isEqualToString:@"example-21 recent"],
               "a copy made 9 minutes ago still goes to the pasteboard at launch");
    [recent stop];
    Settle(recent);
    FlycutAccountShareService *old2 = ServiceAt(kA, ra, -11 * 60);
    [old2 start];
    Settle(old2);
    gActive[1] = NO;
    Offer(old2, @"example-22 away");
    Settle(old2);
    Settle(b3);
    f += Check([rb3->received count] == 1, "B, in the background, has not taken the 11-minute-old copy in yet");
    gActive[1] = YES;
    [b3 sessionDidBecomeActive];
    f += Check(WaitFor(^BOOL { return [rb3->received count] == 2 && [rb3->pasteboard count] == 2; }, 3.0)
               && [TextOf([rb3->pasteboard lastObject]) isEqualToString:@"example-22 away"],
               "coming back to the console takes it in and puts it on the pasteboard: it arrived while B was away");
    [old2 stop];
    [b3 stop];
    gActive[1] = YES;
    return f;
}

// Writes a valid-looking file of `owner` with the given modification time
// straight into a folder (fixture code, not the engine).
static void PlantOld(NSString *dir, uid_t owner, NSTimeInterval mtime) {
    NSString *path = [dir stringByAppendingPathComponent:[[[NSUUID UUID] UUIDString] stringByAppendingString:@".clip"]];
    int fd = open([path fileSystemRepresentation], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) return;
    (void)!write(fd, "x", 1);
    struct timespec times[2] = { { (time_t)mtime, 0 }, { (time_t)mtime, 0 } };
    futimens(fd, times);
    close(fd);
    FCRegisterOwnerAt(AT_FDCWD, [path fileSystemRepresentation], owner);
}

// While pickup is paused (diagnostics mode) copies wait in the inbox; the
// limits and the 24-hour drop still apply; nothing reaches the delegate.
static int RunPausePickup(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [b setPickupPaused:YES];
    f += Check([b pickupPaused], "the service reports pickup as paused");
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    Offer(a, @"example-23 alpha");
    Offer(a, @"example-24 beta");
    Settle(a);
    Spin(0.3);
    Settle(b);
    f += Check([rb->received count] == 0 && [Entries(FromPath(kB, kA)) count] == 2,
               "while paused the folder watch takes nothing in; both copies wait");
    PlantOld(FromPath(kB, kA), kA, [[NSDate date] timeIntervalSince1970] - 25 * 3600);
    [b pickUp];
    gActive[1] = NO;
    Settle(b);
    gActive[1] = YES;
    [b sessionDidBecomeActive];
    Settle(b);
    f += Check([rb->received count] == 0 && [rb->pasteboard count] == 0 && [Entries(FromPath(kB, kA)) count] == 2,
               "a pickup and coming back take nothing in either; a file older than a day is still dropped");
    [b stop];
    Settle(b);
    FCRecorder *rb2 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b2 = Service(kB, rb2);
    [b2 setPickupPaused:YES];
    [b2 start];
    Settle(b2);
    f += Check([rb2->received count] == 0 && [rb2->pasteboard count] == 0 && [Entries(FromPath(kB, kA)) count] == 2,
               "a launch while paused takes nothing in and leaves the pasteboard alone");
    [b2 setPickupPaused:NO];
    f += Check(WaitFor(^BOOL { return [rb2->received count] == 2; }, 3.0), "when pickup resumes the waiting copies come in");
    Settle(b2);
    f += Check([rb2->pasteboard count] == 0 && [Entries(FromPath(kB, kA)) count] == 0,
               "B is in front: they go to the list only, and the files are deleted");
    [b2 stop];
    Settle(b2);
    // Taken in by the queue, then paused before the main thread got it: dropped.
    FCRecorder *rb3 = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b3 = Service(kB, rb3);
    [b3 setWatchesSenderFolders:NO];
    [b3 start];
    Settle(b3);
    Offer(a, @"example-27 late");
    Settle(a);
    [b3 pickUp];
    [b3 waitForQueue];
    [b3 setPickupPaused:YES];
    Spin(0.3);
    f += Check([rb3->received count] == 0, "a copy the queue took in just before pickup was paused is not added");
    [a stop];
    [b3 stop];
    return f;
}

// Turning sharing off also deletes this account's copies that still wait in the
// other accounts' inboxes.
static int RunWithdrawOnOff(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    Offer(a, @"example-25 gamma");
    Offer(a, @"example-26 delta");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 2, "two of A's copies wait for B");
    [a stopAndWipeInbox];
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "turning sharing off in A deletes them");
    f += Check(Exists(FromPath(kB, kA)) && !Exists(TopPath(kA)), "B's folder for A stays; A's own inbox is gone");
    [b pickUp];
    Settle(b);
    f += Check([rb->received count] == 0, "B takes nothing in");
    [b stop];
    return f;
}

// Choosing accounts: B keeps a folder only for the accounts it chose, A writes only
// to the accounts it chose, so a copy goes from A to B only if both chose each
// other. Unchoosing removes the folder with what waits in it and withdraws this
// account's own waiting copies.
static int RunChosenAccounts(void) {
    int f = 0;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra), *b = Service(kB, rb);
    [a setWatchesSenderFolders:NO];
    [b setWatchesSenderFolders:NO];
    [a setChosenAccountUIDs:@[@(kB)]];
    [b setChosenAccountUIDs:@[]];
    f += Check([[a chosenAccountUIDs] isEqualToArray:@[@(kB)]], "the service keeps the chosen accounts");
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    f += Check(Exists(FromPath(kA, kB)) && !Exists(FromPath(kA, kUnopted)) && [Entries(TopPath(kA)) count] == 1,
               "A keeps a folder only for the account it chose");
    f += Check(!Exists(TopPath(kB)), "B, which chose nobody, keeps no inbox at all");
    Offer(a, @"example-50 alpha");
    Settle(a);
    f += Check(!Exists(TopPath(kB)), "A's copy goes nowhere: B did not choose A");
    [b setChosenAccountUIDs:@[@(kA), @(kUnopted), @4242]];
    Settle(b);
    f += Check(Exists(FromPath(kB, kA)) && Exists(FromPath(kB, kUnopted)) && [Entries(TopPath(kB)) count] == 2,
               "B chooses A and 7003: their folders appear; 4242, not an account here, is ignored");
    Offer(a, @"example-51 beta");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 1, "now A's copy reaches B");
    Offer(b, @"example-52 gamma");
    Settle(b);
    f += Check([Entries(FromPath(kA, kB)) count] == 1 && !Exists(TopPath(kUnopted)),
               "B's copy reaches A, which chose B; 7003 chose nobody and gets nothing");
    [a setChosenAccountUIDs:@[]];
    Settle(a);
    f += Check(!Exists(TopPath(kA)), "A unchooses B: A's inbox goes, with B's copy waiting in it");
    f += Check([Entries(FromPath(kB, kA)) count] == 0 && Exists(FromPath(kB, kA)),
               "and A's own copy waiting for B is withdrawn; B's folder for A stays");
    Offer(a, @"example-53 delta");
    Settle(a);
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "A sends nothing to B any more");
    [a pickUp];
    [b pickUp];
    Settle(a);
    Settle(b);
    f += Check([ra->received count] == 0 && [rb->received count] == 0, "neither takes anything in");
    [b setChosenAccountUIDs:@[@(kA)]];
    Settle(b);
    f += Check(Exists(FromPath(kB, kA)) && !Exists(FromPath(kB, kUnopted)), "B unchooses 7003: only 7003's folder goes");
    [a setChosenAccountUIDs:@[@(kB)]];
    Settle(a);
    Offer(a, @"example-54 epsilon");
    Settle(a);
    [b pickUp];
    f += Check(WaitFor(^BOOL { return [rb->received count] == 1; }, 3.0) && [TextOf([rb->received lastObject]) isEqualToString:@"example-54 epsilon"],
               "choosing each other again shares again");
    [a stop];
    [b stop];
    return f;
}

// The account list for Preferences: the login-account rule plus the full name,
// sorted by name.
// A failed inbox setup is reported (state on the main thread, one log line
// without names or paths) and retried with growing pauses, not on every tick.
static int RunSetupFailure(void) {
    int f = 0;
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    NSString *top = TopPath(kB);
    // Another account (4242) holds B's inbox name.
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    FlycutAccountShareService *b = Service(kB, rb);
    if (![b respondsToSelector:@selector(setLogHandler:)] || ![b respondsToSelector:@selector(inboxErrorCode)])
        return Check(NO, "the service reports a failed inbox setup");
    NSMutableArray *logged = [NSMutableArray array];
    [b setLogHandler:^(NSString *line) { @synchronized (logged) { [logged addObject:line]; } }];
    [b setSafetyInterval:0.05];
    int before = gFCPrepareCalls;
    [b start];
    Settle(b);
    f += Check([b inboxErrorCode] == FlycutAccountShareErrorUntrustedInbox && rb->stateChanges == 1 && !rb->offMain,
               "a taken inbox name is reported to the delegate on the main thread");
    Spin(1.6);
    int attempts = gFCPrepareCalls - before;
    printf("setup attempts in 1.6 s at a 0.05 s tick: %d\n", attempts);
    f += Check(attempts >= 3 && attempts <= 10, "it is retried, with growing pauses instead of on every tick");
    NSString *line = [logged count] == 1 ? [logged objectAtIndex:0] : nil;
    f += Check(line != nil && rb->stateChanges == 1, "the failure is logged once and reported once");
    f += Check(line != nil && [line rangeOfString:@"/"].location == NSNotFound && [line rangeOfString:@"Account"].location == NSNotFound
               && [line rangeOfString:@"unavailable"].location != NSNotFound, "the log line names no path and no account");
    rmdir([top fileSystemRepresentation]);
    f += Check(WaitFor(^BOOL { return [b inboxErrorCode] == 0 && Exists(FromPath(kB, kA)); }, 5.0) && rb->stateChanges == 2,
               "once the name is free a retry sets the inbox up and the report clears");
    // Sharing turned off: no report even while the setup would fail.
    [b stopAndWipeInbox];
    Settle(b);
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    [b start];
    Settle(b);
    f += Check([b inboxErrorCode] == FlycutAccountShareErrorUntrustedInbox, "turning it on again reports at once");
    [b stopAndWipeInbox];
    Settle(b);
    f += Check([b inboxErrorCode] == 0 && rb->stateChanges == 4, "turning it off clears the report");
    f += Check([logged count] == 2, "a new failure after the inbox worked again is logged again, once");
    rmdir([top fileSystemRepresentation]);
    return f;
}

// An account lookup that fails gives nil, not an empty list, and the
// service then changes nothing: no inbox is wiped, no copy withdrawn, no
// folder removed; once the lookup works again it goes on as before.
static int RunLookupFailure(void) {
    int f = 0;
    gFailQueryCreate = YES;
    f += Check([FlycutAccountShareService localLoginAccounts] == nil && [FlycutAccountShareService localLoginAccountUIDs] == nil,
               "a directory query that cannot be made gives no account list (nil), not an empty one");
    gFailQueryCreate = NO;
    gFailQueryExecute = YES;
    f += Check([FlycutAccountShareService localLoginAccounts] == nil && [FlycutAccountShareService localLoginAccountUIDs] == nil,
               "a directory query that fails gives none either");
    gFailQueryExecute = NO;
    gFailGeneratedUID = YES;
    f += Check([FlycutAccountShareService localLoginAccounts] == nil,
               "an account whose GeneratedUID cannot be read gives none either");
    gFailGeneratedUID = NO;
    gPasswdErrors = 1;
    BOOL accountsFail = [FlycutAccountShareService localLoginAccounts] == nil;
    gPasswdErrors = 1;
    BOOL uidsFail = [FlycutAccountShareService localLoginAccountUIDs] == nil;
    gPasswdErrors = 0;
    f += Check(accountsFail && uidsFail, "a passwd lookup error for one account gives none either, not a list without it");
    for (int skip = 1; skip <= 3; skip += 2) {
        gPasswdSkip = skip;
        gPasswdErrors = 1;
        BOOL none = [FlycutAccountShareService localLoginAccounts] == nil;
        BOOL reached = gPasswdErrors == 0;
        gPasswdSkip = 0;
        gPasswdErrors = 0;
        f += Check(reached && none, skip == 1 ? "a passwd error after one record was read fails the whole lookup too"
                                              : "and after three records were read");
    }
    gPasswdMissing = 1;
    f += Check([FlycutAccountShareService localLoginAccounts] != nil, "a UID without a passwd entry only leaves that account out");
    gPasswdMissing = 0;
    f += Check([FlycutAccountShareService localLoginAccounts] != nil && [FlycutAccountShareService localLoginAccountUIDs] != nil,
               "with the lookup working the list is there (none is printed)");
    __block BOOL works = YES;
    FCRecorder *ra = [[[FCRecorder alloc] init] autorelease], *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *a = Service(kA, ra);
    FlycutAccountShareService *b = ServiceWithAccounts(kB, rb, ^NSArray *{ return works ? @[@(kA), @(kB), @(kUnopted)] : nil; });
    [a setWatchesSenderFolders:NO];
    [b setWatchesSenderFolders:NO];
    [a start];
    [b start];
    Settle(a);
    Settle(b);
    Offer(a, @"example-90 alpha");
    Settle(a);
    Offer(b, @"example-91 beta");
    Settle(b);
    f += Check([Entries(FromPath(kB, kA)) count] == 1 && [Entries(FromPath(kA, kB)) count] == 1 && Exists(FromPath(kB, kUnopted)),
               "a copy waits in each direction; B keeps a folder for 7003 too");
    works = NO;
    [b setChosenAccountUIDs:@[@(kA)]];
    Settle(b);
    f += Check([Entries(FromPath(kB, kA)) count] == 1 && Exists(FromPath(kB, kUnopted)),
               "while B's lookup fails, a new choice wipes nothing in B's inbox");
    f += Check([Entries(FromPath(kA, kB)) count] == 1, "and withdraws nothing B sent");
    [b sessionDidBecomeActive];
    Settle(b);
    f += Check(Exists(FromPath(kB, kA)) && Exists(FromPath(kB, kUnopted)) && [Entries(FromPath(kA, kB)) count] == 1,
               "a return to the console wipes and withdraws nothing either");
    f += Check([rb->received count] == 1 && [TextOf([rb->received lastObject]) isEqualToString:@"example-90 alpha"],
               "and still takes in what waited");
    f += Check([b inboxErrorCode] == 0 && rb->stateChanges == 0, "no inbox failure is reported");
    works = YES;
    [b sessionDidBecomeActive];
    Settle(b);
    f += Check(Exists(FromPath(kB, kA)) && !Exists(FromPath(kB, kUnopted)) && [Entries(FromPath(kA, kB)) count] == 1,
               "once it works again the new choice applies: 7003's folder goes, the rest stays");
    [a stop];
    [b stop];
    return f;
}

// A passwd record larger than the first 4 KB buffer (getpwuid_r answers
// ERANGE) is read with a larger buffer, grown up to 1 MB; one that needs more
// fails the lookup. Nothing is logged while it works.
static int RunPasswdBuffer(void) {
    int f = 0;
    gPasswdNeed = 100 * 1024;
    gPasswdLargest = 0;
    BOOL read = [FlycutAccountShareService localLoginAccounts] != nil;
    f += Check(read && gPasswdLargest >= gPasswdNeed && gPasswdLargest <= 1024 * 1024 && [Logged() count] == 0,
               "a record that needs 100 KB is read with a grown buffer, and nothing is logged");
    gPasswdNeed = 2 * 1024 * 1024;
    gPasswdLargest = 0;
    BOOL none = [FlycutAccountShareService localLoginAccounts] == nil;
    f += Check(none && gPasswdLargest == 1024 * 1024,
               "one that needs more than 1 MB fails the lookup: the buffer grows to 1 MB and no further");
    gPasswdNeed = 0;
    NSArray *lines = Logged();
    f += Check([lines count] == 1 && [[lines objectAtIndex:0] isEqualToString:
                   @"Flycut: the accounts on this Mac cannot be read for sharing (passwd lookup error 34)"],
               "that failure is logged, with the error code");
    return f;
}

// A lookup that keeps failing is logged once per launch, with a fixed text and
// the error code and no account name, not at every lookup.
static int RunLookupLoggedOnce(void) {
    int f = 0;
    gPasswdErrors = 1000;
    BOOL none = YES;
    for (int i = 0; i < 3; i++)
        none = none && [FlycutAccountShareService localLoginAccounts] == nil;
    gPasswdErrors = 0;
    gFailQueryExecute = YES;
    none = none && [FlycutAccountShareService localLoginAccountUIDs] == nil;
    gFailQueryExecute = NO;
    NSArray *lines = Logged();
    f += Check(none, "a passwd error that persists fails every lookup");
    f += Check([lines count] == 1, "it is logged once, not at every lookup, nor again for another kind of failure");
    f += Check([lines count] == 1 && [[lines objectAtIndex:0] isEqualToString:
                   @"Flycut: the accounts on this Mac cannot be read for sharing (passwd lookup error 5)"],
               "with a fixed text and the error code, no account name");
    f += Check([FlycutAccountShareService localLoginAccounts] != nil && [Logged() count] == 1,
               "once it works the list is there again");
    return f;
}

// Turning sharing off and on again while the inbox still cannot be set
// up logs the failure again (once), as the note under the account list comes
// back too; retries within one start stay quiet.
static int RunRestartLogsAgain(void) {
    int f = 0;
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    NSString *top = TopPath(kB);
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);   // another account holds B's name
    FlycutAccountShareService *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    NSMutableArray *logged = [NSMutableArray array];
    [b setLogHandler:^(NSString *line) { @synchronized (logged) { [logged addObject:line]; } }];
    [b start];
    Settle(b);
    f += Check([logged count] == 1 && [b inboxErrorCode] == FlycutAccountShareErrorUntrustedInbox, "a taken inbox name is logged once");
    [b stopAndWipeInbox];
    Settle(b);
    [b start];
    Settle(b);
    f += Check([logged count] == 2 && [b inboxErrorCode] == FlycutAccountShareErrorUntrustedInbox,
               "sharing turned off and on with the same failure logs it again");
    [b sessionDidBecomeActive];
    Settle(b);
    f += Check([logged count] == 2, "a retry within the same start logs nothing new");
    [b stop];
    Settle(b);
    [b start];
    Settle(b);
    f += Check([logged count] == 3, "a stop and a new start log it again too");
    [b stopAndWipeInbox];
    Settle(b);
    struct stat st;
    f += Check(lstat([top fileSystemRepresentation], &st) == 0 && FCLookupOwner(&st) == 4242, "the other account's folder is left alone");
    rmdir([top fileSystemRepresentation]);
    return f;
}

// A setup failure the queue reports for an earlier start,
// or once sharing is off, is not published: main-thread blocks run only when
// this fixture spins, so the stale report is still queued when it stops.
static int RunStaleFailureIgnored(void) {
    int f = 0;
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    NSString *top = TopPath(kB);
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);   // another account holds B's name
    FlycutAccountShareService *b = Service(kB, rb);
    [b setWatchesSenderFolders:NO];
    [b setLogHandler:^(NSString *line) { (void)line; }];
    // (a) The failure arrives after sharing was turned off.
    [b start];
    [b waitForQueue];
    [b stop];
    [b waitForQueue];
    Spin(0.2);
    f += Check([b inboxErrorCode] == 0 && rb->stateChanges == 0, "a failure reported after sharing went off is not published");
    // (b) The failure of an earlier start arrives while a later start works.
    [b start];
    [b waitForQueue];
    [b stop];
    rmdir([top fileSystemRepresentation]);
    [b start];
    [b waitForQueue];
    Spin(0.2);
    f += Check([b running] && [b inboxErrorCode] == 0 && rb->stateChanges == 0 && Exists(FromPath(kB, kA)),
               "a failure of an earlier start is not published while the current one works");
    // The current start's own failure is.
    [b stopAndWipeInbox];
    Settle(b);
    mkdir([top fileSystemRepresentation], 0700);
    FCRegisterOwnerAt(AT_FDCWD, [top fileSystemRepresentation], 4242);
    [b start];
    Settle(b);
    f += Check([b inboxErrorCode] == FlycutAccountShareErrorUntrustedInbox && rb->stateChanges == 1,
               "the current start's failure is published");
    [b stopAndWipeInbox];
    Settle(b);
    rmdir([top fileSystemRepresentation]);
    return f;
}

static int RunAccountNames(void) {
    int f = 0;
    NSArray *records = @[@{@"uid": @7002, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-b", @"name": @"Account B"},
                         @{@"uid": @7001, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-a", @"name": @"Account A"},
                         @{@"uid": @7004, @"hidden": @YES, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-h", @"name": @"Hidden"},
                         @{@"uid": @7005, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-n"},
                         @{@"uid": @7001, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-a", @"name": @"Account A again"}];
    NSArray *accounts = [FlycutAccountShareService loginAccountsFromRecords:records];
    NSArray *expected = @[@{@"uid": @7005, @"name": @""}, @{@"uid": @7001, @"name": @"Account A"}, @{@"uid": @7002, @"name": @"Account B"}];
    f += Check([accounts isEqualToArray:expected], "login accounts with their names, once each, sorted by name (no name first)");
    NSString *guid = @"0F0F0F0F-0000-4000-8000-000000007001";
    NSArray *withGuid = [FlycutAccountShareService loginAccountsFromRecords:@[
        @{@"uid": @7001, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-a", @"name": @"Account A", @"guid": guid},
        @{@"uid": @7002, @"hidden": @NO, @"enabled": @YES, @"shell": @"/bin/zsh", @"home": @"/Users/example-b", @"name": @"Account B", @"guid": @7}]];
    f += Check([withGuid isEqualToArray:@[@{@"uid": @7001, @"name": @"Account A", @"guid": guid}, @{@"uid": @7002, @"name": @"Account B"}]],
               "an account's GeneratedUID is passed on, a malformed one is not");
    f += Check([[FlycutAccountShareService loginAccountUIDsFromRecords:records] isEqualToArray:@[@7001, @7002, @7005]],
               "the UID list follows the same rule");
    BOOL sane = YES;
    NSArray *local = [FlycutAccountShareService localLoginAccounts];
    for (NSDictionary *account in local)
        if (![[account objectForKey:@"uid"] isKindOfClass:[NSNumber class]] || ![[account objectForKey:@"name"] isKindOfClass:[NSString class]]
            || ![[account objectForKey:@"guid"] isKindOfClass:[NSString class]] || [(NSString *)[account objectForKey:@"guid"] length] != 36
            || [[[NSUUID alloc] initWithUUIDString:[account objectForKey:@"guid"]] autorelease] == nil)
            sane = NO;
    NSMutableArray *localUIDs = [NSMutableArray array];
    for (NSDictionary *account in local) [localUIDs addObject:[account objectForKey:@"uid"]];
    f += Check(sane && [[localUIDs sortedArrayUsingSelector:@selector(compare:)] isEqualToArray:[FlycutAccountShareService localLoginAccountUIDs]],
               "the local directory gives a UID, a name and a GeneratedUID per account (none is printed)");
    return f;
}

// The trace must refuse, not only count, what would leave the injected root: an
// engine pointed at a directory outside it (standing in for a real shared folder)
// creates nothing there.
static int RunContainment(void) {
    int f = 0;
    NSString *outside = [[NSString stringWithUTF8String:gFCTraceRoot] stringByAppendingString:@"-outside"];
    FCRecorder *rb = [[[FCRecorder alloc] init] autorelease];
    FlycutAccountShareService *b = [[[FlycutAccountShareService alloc]
        initWithEngine:FCTracedEngineFor(outside, kB, (id<FlycutAccountShareFilter>)gOperator)
              accounts:^NSArray *{ return @[@(kA), @(kB)]; }
       sessionIsActive:^BOOL { return YES; }] autorelease];
    [b setDelegate:rb];
    [b setSafetyInterval:3600];
    [b start];
    Settle(b);
    [b stopAndWipeInbox];
    Settle(b);
    int violations;
    @synchronized (gFCTraceLock) { violations = gFCViolations; }
    f += Check(violations > 0, "the trace saw the engine try to write outside the injected root");
    f += Check([Entries(outside) count] == 0, "and nothing was created there");
    BOOL refused = ![[NSURL fileURLWithPath:outside isDirectory:YES] setResourceValue:@YES
                                                                            forKey:NSURLIsExcludedFromBackupKey error:NULL];
    f += Check(refused, "a resource value outside the injected root is refused too");
    return f;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 3) return 2;
        const uid_t simulated[] = { kA, kB, kUnopted };
        for (size_t i = 0; i < sizeof simulated / sizeof simulated[0]; i++) {
            if (getpwuid(simulated[i]) != NULL) {
                fprintf(stderr, "FAIL: simulated UID %u belongs to a real account; refusing to run\n", simulated[i]);
                return 2;
            }
        }
        char root[PATH_MAX];
        if (realpath(argv[2], root) == NULL) return 2;
        FCTraceSetRoot(root);
        gShared = [[[NSString stringWithUTF8String:root] stringByAppendingPathComponent:@"shared"] retain];
        if (mkdir([gShared fileSystemRepresentation], 0777) != 0 || chmod([gShared fileSystemRepresentation], 01777) != 0)
            return 2;
        [[FCFakeDefaults standardUserDefaults] setObject:@0 forKey:@"savePreference"];
        gOperator = [[FlycutOperator alloc] init];
        NSDictionary *modes = @{@"start": [NSValue valueWithPointer:RunStartPreparesAllAccounts],
                                @"folder-watch": [NSValue valueWithPointer:RunDeliverByFolderWatch],
                                @"safety-timer": [NSValue valueWithPointer:RunSafetyTimer],
                                @"away-then-active": [NSValue valueWithPointer:RunAwayThenActive],
                                @"launch-pickup": [NSValue valueWithPointer:RunLaunchPickup],
                                @"sender-conditions": [NSValue valueWithPointer:RunSenderConditions],
                                @"wipe": [NSValue valueWithPointer:RunWipe],
                                @"off-wipe-retried": [NSValue valueWithPointer:RunOffWipeRetried],
                                @"leftover-wipe": [NSValue valueWithPointer:RunLeftoverWipe],
                                @"account-rule": [NSValue valueWithPointer:RunAccountRule],
                                @"containment": [NSValue valueWithPointer:RunContainment],
                                @"launch-age": [NSValue valueWithPointer:RunLaunchAge],
                                @"pause-pickup": [NSValue valueWithPointer:RunPausePickup],
                                @"withdraw-on-off": [NSValue valueWithPointer:RunWithdrawOnOff],
                                @"chosen-accounts": [NSValue valueWithPointer:RunChosenAccounts],
                                @"account-names": [NSValue valueWithPointer:RunAccountNames],
                                @"setup-failure": [NSValue valueWithPointer:RunSetupFailure],
                                @"lookup-failure": [NSValue valueWithPointer:RunLookupFailure],
                                @"passwd-buffer": [NSValue valueWithPointer:RunPasswdBuffer],
                                @"lookup-logged-once": [NSValue valueWithPointer:RunLookupLoggedOnce],
                                @"restart-logs-again": [NSValue valueWithPointer:RunRestartLogsAgain],
                                @"stale-failure-ignored": [NSValue valueWithPointer:RunStaleFailureIgnored]};
        NSValue *run = [modes objectForKey:[NSString stringWithUTF8String:argv[1]]];
        if (run == nil) return 3;
        int failures = ((int (*)(void))[run pointerValue])();
        FCTraceReport();
        printf("RESULT failures=%d\n", failures);
        return failures == 0 ? 0 : 1;
    }
}
