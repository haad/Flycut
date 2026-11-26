// Shared by the native fixtures of AccountShareServiceTests.py and
// AccountShareAppControllerTests.py: compiles the real FlycutAccountShare engine
// into the including translation unit with its filesystem-mutating calls renamed
// to trace wrappers, and simulates the kernel's file owner for accounts that do
// not exist on this Mac.
//
// Each simulated account's engine is an FCTracedEngine: while one of its public
// methods runs, the calling thread's actor is that account, so a directory or
// file the engine creates is registered (per inode) as owned by it, like the
// kernel stamps the creator's UID. Engines of several accounts may run on their
// own queues at the same time. Every mutation must resolve inside the injected
// root (FCTraceSetRoot); anything else counts as a violation and is refused
// (EPERM) before it reaches the file system, so a bug or a mutant that points an
// engine at a real path cannot create anything there. Setting a resource value
// (the Time Machine exclusion) is held to the same root.
//
// Include once, after <Foundation/Foundation.h>, before the fixture's own code.

#import <objc/runtime.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/acl.h>
#include <sys/stat.h>
#include <sys/stdio.h>
#include <unistd.h>

static __thread uid_t tFCActor = 0;
static char gFCTraceRoot[PATH_MAX];
static int gFCMutations = 0;
static int gFCViolations = 0;
static NSMutableDictionary *gFCOwners = nil;
static NSObject *gFCTraceLock = nil;

static BOOL FCInsideRoot(NSString *path) {
    NSString *root = [[NSString stringWithUTF8String:gFCTraceRoot] stringByAppendingString:@"/"];
    return gFCTraceRoot[0] != 0 && path != nil && [path hasPrefix:root]
           && ![[path pathComponents] containsObject:@".."];
}

static IMP gFCSetResourceValue = NULL;

static BOOL FCGuardedSetResourceValue(NSURL *self, SEL _cmd, id value, NSString *key, NSError **error) {
    BOOL inside = [self isFileURL] && FCInsideRoot([self path]);
    @synchronized (gFCTraceLock) {
        gFCMutations++;
        if (!inside) {
            gFCViolations++;
            fprintf(stderr, "FAIL: resource value set outside the injected root (refused)\n");
        }
    }
    if (!inside) {
        if (error) *error = [NSError errorWithDomain:NSPOSIXErrorDomain code:EPERM userInfo:nil];
        return NO;
    }
    return ((BOOL (*)(id, SEL, id, NSString *, NSError **))gFCSetResourceValue)(self, _cmd, value, key, error);
}

static void FCTraceSetRoot(const char *root) {
    strlcpy(gFCTraceRoot, root, sizeof gFCTraceRoot);
    if (gFCOwners == nil) gFCOwners = [[NSMutableDictionary alloc] init];
    if (gFCTraceLock == nil) gFCTraceLock = [[NSObject alloc] init];
    if (gFCSetResourceValue == NULL)
        gFCSetResourceValue = method_setImplementation(
            class_getInstanceMethod([NSURL class], @selector(setResourceValue:forKey:error:)), (IMP)FCGuardedSetResourceValue);
}

static NSString *FCInodeKey(const struct stat *st) {
    return [NSString stringWithFormat:@"%llu:%llu", (unsigned long long)st->st_dev, (unsigned long long)st->st_ino];
}

static void FCRegisterOwnerOfFD(int fd, uid_t owner) {
    struct stat st;
    if (fstat(fd, &st) == 0)
        @synchronized (gFCTraceLock) { [gFCOwners setObject:@(owner) forKey:FCInodeKey(&st)]; }
}

static void FCRegisterOwnerAt(int dirFD, const char *name, uid_t owner) {
    struct stat st;
    if (fstatat(dirFD, name, &st, AT_SYMLINK_NOFOLLOW) == 0)
        @synchronized (gFCTraceLock) { [gFCOwners setObject:@(owner) forKey:FCInodeKey(&st)]; }
}

static uid_t FCLookupOwner(const struct stat *st) {
    NSNumber *owner = nil;
    @synchronized (gFCTraceLock) { owner = [[[gFCOwners objectForKey:FCInodeKey(st)] retain] autorelease]; }
    return owner != nil ? (uid_t)[owner unsignedIntValue] : st->st_uid;
}

// Records a mutation; NO (and errno EPERM) if it would leave the injected root.
static BOOL FCNoteMutation(int dirFD, const char *name) {
    char buffer[PATH_MAX];
    BOOL known = dirFD == AT_FDCWD ? getcwd(buffer, sizeof buffer) != NULL : fcntl(dirFD, F_GETPATH, buffer) != -1;
    NSString *path = known ? [NSString stringWithUTF8String:buffer] : nil;
    BOOL single = YES;
    if (name != NULL) {
        single = strchr(name, '/') == NULL && strcmp(name, "..") != 0 && strcmp(name, ".") != 0;
        path = [path stringByAppendingFormat:@"/%s", name];
    }
    BOOL allowed = path != nil && single && FCInsideRoot(path);
    @synchronized (gFCTraceLock) {
        gFCMutations++;
        if (!allowed) {
            gFCViolations++;
            fprintf(stderr, "FAIL: engine mutation outside the injected root (refused)\n");
        }
    }
    if (!allowed) errno = EPERM;
    return allowed;
}

static int FCT_openat(int fd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        if (!FCNoteMutation(fd, path)) return -1;
    }
    int result = openat(fd, path, flags, mode);
    if (result >= 0 && (flags & O_CREAT) && (flags & O_EXCL))
        FCRegisterOwnerOfFD(result, tFCActor);
    return result;
}

static int FCT_mkdirat(int fd, const char *path, mode_t mode) {
    if (!FCNoteMutation(fd, path)) return -1;
    int result = mkdirat(fd, path, mode);
    if (result == 0)
        FCRegisterOwnerAt(fd, path, tFCActor);
    return result;
}

static int FCT_renameatx_np(int fromFD, const char *from, int toFD, const char *to, unsigned int flags) {
    BOOL fromAllowed = FCNoteMutation(fromFD, from), toAllowed = FCNoteMutation(toFD, to);
    if (!fromAllowed || !toAllowed) return -1;
    return renameatx_np(fromFD, from, toFD, to, flags);
}

static int FCT_renameat(int fromFD, const char *from, int toFD, const char *to) {
    BOOL fromAllowed = FCNoteMutation(fromFD, from), toAllowed = FCNoteMutation(toFD, to);
    if (!fromAllowed || !toAllowed) return -1;
    return renameat(fromFD, from, toFD, to);
}

static int FCT_unlinkat(int fd, const char *path, int flags) {
    if (!FCNoteMutation(fd, path)) return -1;
    return unlinkat(fd, path, flags);
}

static int FCT_fchmod(int fd, mode_t mode) {
    if (!FCNoteMutation(fd, NULL)) return -1;
    return fchmod(fd, mode);
}

static int FCT_acl_set_fd_np(int fd, acl_t acl, acl_type_t type) {
    if (!FCNoteMutation(fd, NULL)) return -1;
    return acl_set_fd_np(fd, acl, type);
}

static ssize_t FCT_write(int fd, const void *buffer, size_t length) {
    if (!FCNoteMutation(fd, NULL)) return -1;
    return write(fd, buffer, length);
}

static int FCT_futimens(int fd, const struct timespec times[2]) {
    if (!FCNoteMutation(fd, NULL)) return -1;
    return futimens(fd, times);
}

#define openat(...) FCT_openat(__VA_ARGS__)
#define mkdirat(...) FCT_mkdirat(__VA_ARGS__)
#define renameatx_np(...) FCT_renameatx_np(__VA_ARGS__)
#define renameat(...) FCT_renameat(__VA_ARGS__)
#define unlinkat(...) FCT_unlinkat(__VA_ARGS__)
#define fchmod(...) FCT_fchmod(__VA_ARGS__)
#define acl_set_fd_np(...) FCT_acl_set_fd_np(__VA_ARGS__)
#define write(...) FCT_write(__VA_ARGS__)
#define futimens(...) FCT_futimens(__VA_ARGS__)

#include "FlycutEngine/FlycutAccountShare.m"

#undef openat
#undef mkdirat
#undef renameatx_np
#undef renameat
#undef unlinkat
#undef fchmod
#undef acl_set_fd_np
#undef write
#undef futimens

// An engine whose public methods act as its simulated account.
@interface FCTracedEngine : FlycutAccountShare
@end

// How often an inbox was prepared (any engine), for retry counts.
static volatile int gFCPrepareCalls = 0;

@implementation FCTracedEngine
- (BOOL)prepareInboxForSenders:(NSArray<NSNumber *> *)uids error:(NSError **)error {
    __sync_fetch_and_add(&gFCPrepareCalls, 1);
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    BOOL ok = [super prepareInboxForSenders:uids error:error];
    tFCActor = saved;
    return ok;
}
- (NSArray<FlycutSharedClipping *> *)collectClippings {
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    NSArray *result = [super collectClippings];
    tFCActor = saved;
    return result;
}
- (BOOL)wipeInbox:(NSError **)error {
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    BOOL ok = [super wipeInbox:error];
    tFCActor = saved;
    return ok;
}
- (void)pruneInbox {
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    [super pruneInbox];
    tFCActor = saved;
}
- (BOOL)withdrawFromRecipient:(uid_t)recipientUID error:(NSError **)error {
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    BOOL ok = [super withdrawFromRecipient:recipientUID error:error];
    tFCActor = saved;
    return ok;
}
- (BOOL)sendText:(NSString *)text ofType:(NSString *)type availableTypes:(NSArray<NSString *> *)availableTypes
        richData:(NSDictionary *)richData appName:(NSString *)appName toRecipient:(uid_t)recipientUID
           error:(NSError **)error {
    uid_t saved = tFCActor;
    tFCActor = [self ownUID];
    BOOL ok = [super sendText:text ofType:type availableTypes:availableTypes richData:richData appName:appName
                  toRecipient:recipientUID error:error];
    tFCActor = saved;
    return ok;
}
@end

// clock nil: the system clock.
static FCTracedEngine *FCTracedEngineWithClock(NSString *root, uid_t uid, id<FlycutAccountShareFilter> filter,
                                               FlycutAccountShareClock clock) {
    FCTracedEngine *engine = [[FCTracedEngine alloc] initWithSharedRoot:root ownUID:uid
                                                            ownerLookup:^uid_t(const struct stat *st) { return FCLookupOwner(st); }
                                                                  clock:clock];
    [engine setFilter:filter];
    return [engine autorelease];
}

static FCTracedEngine *FCTracedEngineFor(NSString *root, uid_t uid, id<FlycutAccountShareFilter> filter) {
    return FCTracedEngineWithClock(root, uid, filter, nil);
}

static void FCTraceReport(void) {
    @synchronized (gFCTraceLock) {
        printf("TRACE mutations=%d violations=%d\n", gFCMutations, gFCViolations);
    }
}
