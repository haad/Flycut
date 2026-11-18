// Native fixture for AccountShareEngineTests.py.
//
// Compiles the real FlycutAccountShare engine and the real FlycutOperator filter
// into this translation unit and drives two simulated accounts (A = 7001,
// B = 7002) plus a foreign account (C = 4242) inside one injected scratch root.
// No real account owns these UIDs; the fixture refuses to run if one does.
//
// Every real file belongs to the account running the tests, so the kernel's file
// owner is simulated: the engine's owner lookup reads a per-inode registry that
// the traced mkdirat/openat wrappers fill with the acting account, like the
// kernel stamps the creator's UID. Files the fixture plants itself are
// registered with the account that is supposed to have created them.
//
// The engine's filesystem-mutating calls are renamed to trace wrappers that
// record each mutation and fail the run if a target lies outside the injected
// root. NSUserDefaults is an in-memory fake; no pasteboard, app, network or real
// defaults API is used. Clipping texts are dummy strings and are never printed.

#import <Cocoa/Cocoa.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <membership.h>
#include <pwd.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/acl.h>
#include <sys/stat.h>
#include <sys/stdio.h>
#include <unistd.h>

@interface FCFakeDefaults : NSObject {
    NSMutableDictionary *values;
}
+ (FCFakeDefaults *)standardUserDefaults;
- (void)reset;
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
- (void)reset { [values removeAllObjects]; }
- (void)registerDefaults:(NSDictionary *)registration {
    for (id key in registration)
        if ([values objectForKey:key] == nil)
            [values setObject:[registration objectForKey:key] forKey:key];
}
- (id)objectForKey:(NSString *)key { return [values objectForKey:key]; }
- (id)valueForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSString *)stringForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [[values objectForKey:key] integerValue]; }
- (BOOL)boolForKey:(NSString *)key { return [[values objectForKey:key] boolValue]; }
- (NSURL *)URLForKey:(NSString *)key { return nil; }
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) [values setObject:value forKey:key]; else [values removeObjectForKey:key];
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

@interface FCOperator : FlycutOperator
@end

@implementation FCOperator
- (bool)saveFromStore:(FlycutStore *)store atIndex:(int)index withPrefix:(NSString *)prefix {
    fprintf(stderr, "FAIL: fixture reached the file-writing autosave path\n");
    abort();
}
@end

#undef NSUserDefaults
#undef NSSearchPathForDirectoriesInDomains

// ---------------------------------------------------------------------------
// Simulated kernel file owner and mutation trace.

enum { kA = 7001, kB = 7002, kC = 4242, kUnchosen = 7003 };

static uid_t gActor = 0;
static char gRoot[PATH_MAX];
static int gMutations = 0;
static int gViolations = 0;
static int gReads = 0;
static NSMutableArray *gTrace = nil;
static NSMutableDictionary *gOwners = nil;
static void (^gBeforeRename)(int toFD, const char *toName) = nil;
// Defence-in-depth hooks: run once before the engine's next read, after each engine openat.
static void (^gBeforeRead)(int fd) = nil;
static void (^gAfterOpen)(int fd, const char *name) = nil;
// Root-move hooks: after each engine rename (with its result), before each ACL write.
static void (^gAfterRename)(int toFD, const char *toName, int result) = nil;
static void (^gBeforeACL)(int fd) = nil;

static NSString *InodeKey(const struct stat *st) {
    return [NSString stringWithFormat:@"%llu:%llu", (unsigned long long)st->st_dev, (unsigned long long)st->st_ino];
}

static void RegisterOwnerOfFD(int fd, uid_t owner) {
    struct stat st;
    if (fstat(fd, &st) == 0)
        [gOwners setObject:[NSNumber numberWithUnsignedInt:owner] forKey:InodeKey(&st)];
}

static void RegisterOwnerAt(int dirFD, const char *name, uid_t owner) {
    struct stat st;
    if (fstatat(dirFD, name, &st, AT_SYMLINK_NOFOLLOW) == 0)
        [gOwners setObject:[NSNumber numberWithUnsignedInt:owner] forKey:InodeKey(&st)];
}

static void RegisterOwnerOfPath(NSString *path, uid_t owner) {
    RegisterOwnerAt(AT_FDCWD, [path fileSystemRepresentation], owner);
}

static uid_t LookupOwner(const struct stat *st) {
    NSNumber *owner = [gOwners objectForKey:InodeKey(st)];
    return owner != nil ? (uid_t)[owner unsignedIntValue] : st->st_uid;
}

static NSString *PathOfFD(int fd) {
    char buffer[PATH_MAX];
    if (fd == AT_FDCWD) {
        if (getcwd(buffer, sizeof buffer) == NULL) return nil;
    } else if (fcntl(fd, F_GETPATH, buffer) == -1) {
        return nil;
    }
    return [NSString stringWithUTF8String:buffer];
}

// Records a mutation; NO (errno EPERM, the call is not made) if it would leave
// the injected root, so a broken engine or test can never write elsewhere.
static BOOL NoteMutation(NSString *op, int dirFD, const char *name) {
    gMutations++;
    NSString *base = PathOfFD(dirFD);
    BOOL singleComponent = YES;
    NSString *path = base;
    if (name != NULL) {
        singleComponent = strchr(name, '/') == NULL && strcmp(name, "..") != 0 && strcmp(name, ".") != 0;
        path = [base stringByAppendingFormat:@"/%s", name];
    }
    NSString *root = [NSString stringWithUTF8String:gRoot];
    BOOL inside = base != nil && singleComponent && [path hasPrefix:[root stringByAppendingString:@"/"]];
    if (!inside) {
        gViolations++;
        fprintf(stderr, "FAIL: engine %s outside the injected root (refused)\n", [op UTF8String]);
        errno = EPERM;
    }
    [gTrace addObject:[NSString stringWithFormat:@"%@ %u %@", op, gActor,
                       inside ? [path substringFromIndex:[root length]] : @"<outside>"]];
    return inside;
}

static int FCT_openat(int fd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        NSString *op = [NSString stringWithFormat:@"create%s%s", (flags & O_EXCL) ? "-excl" : "",
                        (flags & O_NOFOLLOW) ? "-nofollow" : ""];
        if (!NoteMutation(op, fd, path)) return -1;
    }
    int result = openat(fd, path, flags, mode);
    if (result >= 0 && (flags & O_CREAT) && (flags & O_EXCL))
        RegisterOwnerOfFD(result, gActor);
    if (result >= 0 && gAfterOpen != nil)
        gAfterOpen(result, path);
    return result;
}

static int FCT_mkdirat(int fd, const char *path, mode_t mode) {
    if (!NoteMutation(@"mkdir", fd, path)) return -1;
    int result = mkdirat(fd, path, mode);
    if (result == 0)
        RegisterOwnerAt(fd, path, gActor);
    return result;
}

static int FCT_renameatx_np(int fromFD, const char *from, int toFD, const char *to, unsigned int flags) {
    BOOL fromInside = NoteMutation(@"rename-source", fromFD, from);
    if (!NoteMutation((flags & RENAME_EXCL) ? @"rename-excl" : @"rename", toFD, to) || !fromInside) return -1;
    if (gBeforeRename != nil)
        gBeforeRename(toFD, to);
    int result = renameatx_np(fromFD, from, toFD, to, flags);
    int saved = errno;
    if (gAfterRename != nil)
        gAfterRename(toFD, to, result);
    errno = saved;
    return result;
}

static int FCT_renameat(int fromFD, const char *from, int toFD, const char *to) {
    BOOL fromInside = NoteMutation(@"rename-source", fromFD, from);
    if (!NoteMutation(@"rename", toFD, to) || !fromInside) return -1;
    if (gBeforeRename != nil)
        gBeforeRename(toFD, to);
    return renameat(fromFD, from, toFD, to);
}

static int FCT_unlinkat(int fd, const char *path, int flags) {
    if (!NoteMutation(@"unlink", fd, path)) return -1;
    return unlinkat(fd, path, flags);
}

static int FCT_fchmod(int fd, mode_t mode) {
    if (!NoteMutation(@"chmod", fd, NULL)) return -1;
    return fchmod(fd, mode);
}

static int FCT_acl_set_fd_np(int fd, acl_t acl, acl_type_t type) {
    if (!NoteMutation(@"acl", fd, NULL)) return -1;
    if (gBeforeACL != nil)
        gBeforeACL(fd);
    return acl_set_fd_np(fd, acl, type);
}

static ssize_t FCT_write(int fd, const void *buffer, size_t length) {
    if (!NoteMutation(@"write", fd, NULL)) return -1;
    return write(fd, buffer, length);
}

static int FCT_futimens(int fd, const struct timespec times[2]) {
    if (!NoteMutation(@"utimes", fd, NULL)) return -1;
    return futimens(fd, times);
}

static ssize_t FCT_read(int fd, void *buffer, size_t length) {
    gReads++;
    if (gBeforeRead != nil) {
        void (^hook)(int) = gBeforeRead;
        gBeforeRead = nil;
        hook(fd);
    }
    return read(fd, buffer, length);
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
#define read(...) FCT_read(__VA_ARGS__)

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
#undef read

// ---------------------------------------------------------------------------
// Helpers.

static NSString *gShared = nil;
static NSTimeInterval gNow = 0;
static FCOperator *gOperator = nil;

static int Check(BOOL condition, const char *message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        return 1;
    }
    printf("PASS: %s\n", message);
    return 0;
}

static FCOperator *FreshOperator(void) {
    [[FCFakeDefaults standardUserDefaults] reset];
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    [defaults setObject:@0 forKey:@"savePreference"];
    FCOperator *op = [[FCOperator alloc] init];
    [op awakeFromNibDisplaying:10 withDisplayLength:40 withSaveSelector:NULL forTarget:nil];
    return op;
}

static FlycutAccountShare *Participant(uid_t uid) {
    FlycutAccountShare *share = [[FlycutAccountShare alloc]
        initWithSharedRoot:gShared
                    ownUID:uid
               ownerLookup:^uid_t(const struct stat *st) { return LookupOwner(st); }
                     clock:^NSTimeInterval { return gNow; }];
    [share setFilter:(id<FlycutAccountShareFilter>)gOperator];
    return [share autorelease];
}

static NSString *TopPath(uid_t recipient) {
    return [gShared stringByAppendingPathComponent:[NSString stringWithFormat:@".flycut-share-%u", recipient]];
}

static NSString *FromPath(uid_t recipient, uid_t sender) {
    return [TopPath(recipient) stringByAppendingPathComponent:[NSString stringWithFormat:@"from-%u", sender]];
}

static NSArray *Entries(NSString *dir) {
    NSMutableArray *names = [NSMutableArray array];
    DIR *d = opendir([dir fileSystemRepresentation]);
    if (d == NULL) return nil;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) continue;
        [names addObject:[NSString stringWithUTF8String:e->d_name]];
    }
    closedir(d);
    return [names sortedArrayUsingSelector:@selector(compare:)];
}

static BOOL Exists(NSString *path) {
    struct stat st;
    return lstat([path fileSystemRepresentation], &st) == 0;
}

static BOOL IsRealDirectory(NSString *path) {
    struct stat st;
    return lstat([path fileSystemRepresentation], &st) == 0 && S_ISDIR(st.st_mode);
}

static uid_t OwnerOf(NSString *path) {
    struct stat st;
    if (lstat([path fileSystemRepresentation], &st) != 0) return (uid_t)-1;
    return LookupOwner(&st);
}

static mode_t ModeOf(NSString *path) {
    struct stat st;
    if (lstat([path fileSystemRepresentation], &st) != 0) return 0;
    return st.st_mode & 07777;
}

static NSString *InodeOf(NSString *path) {
    struct stat st;
    if (lstat([path fileSystemRepresentation], &st) != 0) return nil;
    return InodeKey(&st);
}

static NSString *NewClipName(void) {
    return [[[NSUUID UUID] UUIDString] stringByAppendingString:@".clip"];
}

static NSData *Plist(id object, NSPropertyListFormat format) {
    return [NSPropertyListSerialization dataWithPropertyList:object format:format options:0 error:NULL];
}

static NSMutableDictionary *ValidPayload(NSString *name, NSString *text) {
    NSString *identifier = [name stringByDeletingPathExtension];
    return [NSMutableDictionary dictionaryWithObjectsAndKeys:
            @1, @"v", identifier, @"id", [NSNumber numberWithDouble:gNow], @"created", text, @"text", nil];
}

static BOOL Plant(NSString *dir, NSString *name, NSData *data, uid_t owner, NSTimeInterval mtime) {
    NSString *path = [dir stringByAppendingPathComponent:name];
    int fd = open([path fileSystemRepresentation], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) return NO;
    const char *bytes = [data bytes];
    size_t left = [data length];
    while (left > 0) {
        ssize_t n = write(fd, bytes, left);
        if (n <= 0) { close(fd); return NO; }
        bytes += n;
        left -= (size_t)n;
    }
    struct timespec times[2];
    times[0].tv_sec = times[1].tv_sec = (time_t)mtime;
    times[0].tv_nsec = times[1].tv_nsec = (long)((mtime - (time_t)mtime) * 1e9);
    futimens(fd, times);
    RegisterOwnerOfFD(fd, owner);
    close(fd);
    return YES;
}

static BOOL PlantValid(NSString *dir, NSString *name, NSString *text, uid_t owner) {
    return Plant(dir, name, Plist(ValidPayload(name, text), NSPropertyListBinaryFormat_v1_0), owner, gNow);
}

static BOOL PlantDir(NSString *path, uid_t owner, mode_t mode) {
    if (mkdir([path fileSystemRepresentation], mode) != 0) return NO;
    chmod([path fileSystemRepresentation], mode);
    RegisterOwnerOfPath(path, owner);
    return YES;
}

static NSString *AclEntry(BOOL allow, BOOL isUser, unsigned int qualifier, unsigned int perms, unsigned int flags) {
    return [NSString stringWithFormat:@"%@ %@=%u perms=%#x flags=%#x", allow ? @"allow" : @"deny",
            isUser ? @"uid" : @"gid", qualifier, perms, flags];
}

static NSArray *AclOf(NSString *path) {
    acl_t acl = acl_get_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED);
    if (acl == NULL) return errno == ENOENT ? @[] : nil;
    static const acl_perm_t perms[] = {
        ACL_READ_DATA, ACL_WRITE_DATA, ACL_EXECUTE, ACL_DELETE, ACL_APPEND_DATA, ACL_DELETE_CHILD,
        ACL_READ_ATTRIBUTES, ACL_WRITE_ATTRIBUTES, ACL_READ_EXTATTRIBUTES, ACL_WRITE_EXTATTRIBUTES,
        ACL_READ_SECURITY, ACL_WRITE_SECURITY, ACL_CHANGE_OWNER, ACL_SYNCHRONIZE };
    static const acl_flag_t flags[] = {
        ACL_ENTRY_INHERITED, ACL_ENTRY_FILE_INHERIT, ACL_ENTRY_DIRECTORY_INHERIT,
        ACL_ENTRY_LIMIT_INHERIT, ACL_ENTRY_ONLY_INHERIT };
    NSMutableArray *result = [NSMutableArray array];
    acl_entry_t entry;
    for (int which = ACL_FIRST_ENTRY; acl_get_entry(acl, which, &entry) == 0; which = ACL_NEXT_ENTRY) {
        acl_tag_t tag;
        acl_get_tag_type(entry, &tag);
        uuid_t *uu = (uuid_t *)acl_get_qualifier(entry);
        id_t qualifier = 0;
        int idType = -1;
        if (uu != NULL) {
            mbr_uuid_to_id(*uu, &qualifier, &idType);
            acl_free(uu);
        }
        acl_permset_t permset;
        acl_get_permset(entry, &permset);
        unsigned int permBits = 0;
        for (size_t i = 0; i < sizeof perms / sizeof perms[0]; i++)
            if (acl_get_perm_np(permset, perms[i]) == 1) permBits |= perms[i];
        acl_flagset_t flagset;
        acl_get_flagset_np(entry, &flagset);
        unsigned int flagBits = 0;
        for (size_t i = 0; i < sizeof flags / sizeof flags[0]; i++)
            if (acl_get_flag_np(flagset, flags[i]) == 1) flagBits |= flags[i];
        [result addObject:AclEntry(tag == ACL_EXTENDED_ALLOW, idType == ID_TYPE_UID, qualifier, permBits, flagBits)];
    }
    acl_free(acl);
    return [result sortedArrayUsingSelector:@selector(compare:)];
}

static BOOL AddAclEntry(NSString *path, BOOL isUser, unsigned int qualifier, acl_perm_t perms, acl_flag_t flagBits) {
    acl_t acl = acl_get_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED);
    if (acl == NULL) acl = acl_init(1);
    acl_entry_t entry;
    if (acl_create_entry(&acl, &entry) != 0) { acl_free(acl); return NO; }
    acl_set_tag_type(entry, ACL_EXTENDED_ALLOW);
    uuid_t uu;
    if (isUser) mbr_uid_to_uuid(qualifier, uu); else mbr_gid_to_uuid(qualifier, uu);
    acl_set_qualifier(entry, uu);
    acl_permset_t permset;
    acl_get_permset(entry, &permset);
    acl_clear_perms(permset);
    static const acl_perm_t all[] = {
        ACL_READ_DATA, ACL_WRITE_DATA, ACL_EXECUTE, ACL_DELETE, ACL_APPEND_DATA, ACL_DELETE_CHILD,
        ACL_READ_ATTRIBUTES, ACL_WRITE_ATTRIBUTES, ACL_READ_EXTATTRIBUTES, ACL_WRITE_EXTATTRIBUTES,
        ACL_READ_SECURITY, ACL_WRITE_SECURITY, ACL_CHANGE_OWNER, ACL_SYNCHRONIZE };
    for (size_t i = 0; i < sizeof all / sizeof all[0]; i++)
        if (perms & all[i]) acl_add_perm(permset, all[i]);
    acl_set_permset(entry, permset);
    acl_flagset_t flagset;
    acl_get_flagset_np(entry, &flagset);
    acl_clear_flags_np(flagset);
    static const acl_flag_t allFlags[] = { ACL_ENTRY_FILE_INHERIT, ACL_ENTRY_DIRECTORY_INHERIT, ACL_ENTRY_ONLY_INHERIT };
    for (size_t i = 0; i < sizeof allFlags / sizeof allFlags[0]; i++)
        if (flagBits & allFlags[i]) acl_add_flag_np(flagset, allFlags[i]);
    acl_set_flagset_np(entry, flagset);
    int rc = acl_set_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED, acl);
    acl_free(acl);
    return rc == 0;
}

// A deny entry for one account or group, added in front of the path's ACL.
static BOOL AddDenyEntry(NSString *path, BOOL isUser, unsigned int qualifier, acl_perm_t perms) {
    acl_t acl = acl_get_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED);
    if (acl == NULL) acl = acl_init(1);
    acl_entry_t entry;
    if (acl_create_entry_np(&acl, &entry, ACL_FIRST_ENTRY) != 0) { acl_free(acl); return NO; }
    acl_set_tag_type(entry, ACL_EXTENDED_DENY);
    uuid_t uu;
    if (isUser) mbr_uid_to_uuid(qualifier, uu); else mbr_gid_to_uuid(qualifier, uu);
    acl_set_qualifier(entry, uu);
    acl_permset_t permset;
    acl_get_permset(entry, &permset);
    acl_clear_perms(permset);
    acl_add_perm(permset, perms);
    acl_set_permset(entry, permset);
    int rc = acl_set_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED, acl);
    acl_free(acl);
    return rc == 0;
}

static BOOL ClearAclOf(NSString *path) {
    acl_t empty = acl_init(0);
    int rc = empty != NULL ? acl_set_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED, empty) : -1;
    if (empty != NULL) acl_free(empty);
    return rc == 0;
}

// The staff ACE measured on this Mac's /Users/Shared, applied to a scratch replica.
static const acl_perm_t kStaffPerms = ACL_LIST_DIRECTORY | ACL_ADD_FILE | ACL_SEARCH | ACL_DELETE |
    ACL_ADD_SUBDIRECTORY | ACL_DELETE_CHILD | ACL_READ_ATTRIBUTES | ACL_WRITE_ATTRIBUTES |
    ACL_READ_EXTATTRIBUTES | ACL_WRITE_EXTATTRIBUTES | ACL_READ_SECURITY;

// The replica parent's whole ACL: that one staff ACE, set by the fixture.
static NSArray *ReplicaAcl(void) {
    return @[AclEntry(YES, NO, 20, kStaffPerms, ACL_ENTRY_FILE_INHERIT | ACL_ENTRY_DIRECTORY_INHERIT)];
}

static NSString *kTopSenderEntry(uid_t sender) {
    return AclEntry(YES, YES, sender, ACL_SEARCH, 0);
}
static NSString *kFromSenderEntry(uid_t sender) {
    return AclEntry(YES, YES, sender, ACL_LIST_DIRECTORY | ACL_ADD_FILE | ACL_SEARCH | ACL_DELETE_CHILD |
                    ACL_READ_ATTRIBUTES | ACL_READ_SECURITY, 0);
}
static NSString *kFromRecipientEntry(uid_t recipient) {
    return AclEntry(YES, YES, recipient, ACL_READ_DATA | ACL_READ_ATTRIBUTES | ACL_READ_EXTATTRIBUTES |
                    ACL_READ_SECURITY, ACL_ENTRY_FILE_INHERIT | ACL_ENTRY_ONLY_INHERIT);
}
// Nobody, the owner included, may rename or delete the inbox root itself: the
// node's own deny entry wins over the staff ACE's delete_child on /Users/Shared.
static NSString *kTopDenyDeleteEntry(void) {
    return AclEntry(NO, NO, 12, ACL_DELETE, 0);
}
static NSArray *ExpectedTopAcl(NSArray *senders) {
    NSMutableArray *entries = [NSMutableArray arrayWithObject:kTopDenyDeleteEntry()];
    for (NSNumber *sender in senders) [entries addObject:kTopSenderEntry([sender unsignedIntValue])];
    return [entries sortedArrayUsingSelector:@selector(compare:)];
}
static NSArray *ExpectedFromAcl(uid_t recipient, uid_t sender) {
    return [@[kFromSenderEntry(sender), kFromRecipientEntry(recipient)] sortedArrayUsingSelector:@selector(compare:)];
}

static NSArray *ClipNames(NSString *dir) {
    NSMutableArray *names = [NSMutableArray array];
    for (NSString *name in Entries(dir))
        if ([name hasSuffix:@".clip"]) [names addObject:name];
    return names;
}

static BOOL Send(FlycutAccountShare *sender, NSString *text, NSArray *types, NSDictionary *rich, uid_t recipient,
                 NSInteger *code) {
    NSError *error = nil;
    gActor = [sender ownUID];
    BOOL ok = [sender sendText:text ofType:@"public.utf8-plain-text" availableTypes:types richData:rich
                       appName:@"Example App" toRecipient:recipient error:&error];
    if (code != NULL) *code = ok ? 0 : [error code];
    return ok;
}

static NSArray *Collect(FlycutAccountShare *recipient) {
    gActor = [recipient ownUID];
    return [recipient collectClippings];
}

static BOOL Prepare(FlycutAccountShare *recipient, NSArray *senders) {
    gActor = [recipient ownUID];
    return [recipient prepareInboxForSenders:senders error:NULL];
}

static BOOL TraceHas(NSString *prefix) {
    for (NSString *line in gTrace)
        if ([line hasPrefix:prefix]) return YES;
    return NO;
}

static NSArray *kPlainTypes(void) { return @[@"public.utf8-plain-text"]; }

// ---------------------------------------------------------------------------
// Cases.

static int RunRoundTrip(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    f += Check(Prepare(a, @[@(kB)]), "A creates its inbox for B");
    NSData *rtf = [@"{\\rtf1 example-01}" dataUsingEncoding:NSUTF8StringEncoding];
    NSData *html = [@"<b>example-01</b>" dataUsingEncoding:NSUTF8StringEncoding];
    NSDictionary *rich = @{@"public.rtf": rtf, @"public.html": html, @"com.example.private": rtf};
    NSArray *types = @[@"public.utf8-plain-text", @"public.rtf", @"public.html"];
    f += Check(Send(a, @"example-01 alpha", types, rich, kB, NULL), "A shares a formatted clipping with B");
    gNow += 1;
    f += Check(Send(a, @"example-02 beta", kPlainTypes(), nil, kB, NULL), "A shares a second clipping");
    gNow += 1;
    f += Check(Send(a, @"example-03 gamma", kPlainTypes(), nil, kB, NULL), "A shares a third clipping");
    f += Check([ClipNames(FromPath(kB, kA)) count] == 3, "three published files wait in B's inbox for A");
    NSArray *got = Collect(b);
    f += Check([got count] == 3, "B picks up all three clippings");
    if ([got count] == 3) {
        FlycutSharedClipping *first = [got objectAtIndex:0];
        f += Check([[first text] isEqualToString:@"example-01 alpha"]
                   && [[[got objectAtIndex:1] text] isEqualToString:@"example-02 beta"]
                   && [[[got objectAtIndex:2] text] isEqualToString:@"example-03 gamma"],
                   "clippings come back oldest first");
        f += Check([first senderUID] == kA, "the sender is the account that owns the inbox folder");
        f += Check([[[first richData] objectForKey:@"public.rtf"] isEqualToData:rtf]
                   && [[[first richData] objectForKey:@"public.html"] isEqualToData:html]
                   && [[first richData] count] == 2, "RTF and HTML arrive, other rich types are dropped");
        f += Check([[first appName] isEqualToString:@"Example App"], "the source app name arrives");
        f += Check(fabs([first created] - (gNow - 2)) < 0.001, "the sender's timestamp arrives");
        f += Check([[got objectAtIndex:1] richData] == nil, "a plain clipping carries no rich data");
    }
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "B deletes every file after pickup");
    f += Check([Collect(b) count] == 0, "a second pickup returns nothing");
    f += Check(Send(b, @"example-04 delta", kPlainTypes(), nil, kA, NULL), "B shares a clipping with A");
    NSArray *back = Collect(a);
    f += Check([back count] == 1 && [[back objectAtIndex:0] senderUID] == kB, "A picks up B's clipping");
    BOOL allCreatesExclusive = YES, publishedOnlyByRename = YES;
    for (NSString *line in gTrace) {
        if ([line hasPrefix:@"create"] && ![line hasPrefix:@"create-excl-nofollow "]) allCreatesExclusive = NO;
        if ([line hasPrefix:@"create"] && [line hasSuffix:@".clip"]) publishedOnlyByRename = NO;
        if ([line hasPrefix:@"rename "]) publishedOnlyByRename = NO;
    }
    f += Check(allCreatesExclusive, "every file is created with O_CREAT|O_EXCL|O_NOFOLLOW");
    f += Check(publishedOnlyByRename && TraceHas(@"rename-excl 7001 /shared/.flycut-share-7002/from-7001/"),
               "a clipping is published only by an exclusive rename of its temporary file");
    return f;
}

static int RunAclExact(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check([AclOf(gShared) isEqualToArray:ReplicaAcl()], "the replica parent carries exactly the staff ACE");
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox below the replica parent");
    NSString *top = TopPath(kB), *from = FromPath(kB, kA);
    f += Check(IsRealDirectory(top) && OwnerOf(top) == kB && ModeOf(top) == 0700, "inbox root: directory, owner B, mode 0700");
    f += Check([AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])],
               "inbox root ACL is exactly: nobody may delete or rename it, A may search");
    f += Check(IsRealDirectory(from) && OwnerOf(from) == kB && ModeOf(from) == 0700, "from-A: directory, owner B, mode 0700");
    f += Check([AclOf(from) isEqualToArray:ExpectedFromAcl(kB, kA)],
               "from-A ACL is exactly: A list/add_file/search/delete_child/readattr/readsecurity, B read on new files");
    BOOL noGroup = YES;
    for (NSString *entry in [AclOf(top) arrayByAddingObjectsFromArray:AclOf(from)])
        if ([entry rangeOfString:@"gid="].location != NSNotFound && ![entry isEqualToString:kTopDenyDeleteEntry()]) noGroup = NO;
    f += Check(noGroup, "no inherited staff entry is left on the inbox (only the root's deny entry names a group)");
    f += Check(Send(a, @"example-05", kPlainTypes(), nil, kB, NULL), "A writes into from-A");
    NSArray *names = ClipNames(from);
    if ([names count] == 1) {
        NSString *file = [from stringByAppendingPathComponent:[names objectAtIndex:0]];
        f += Check(OwnerOf(file) == kA && ModeOf(file) == 0600, "the published file belongs to A, mode 0600");
        f += Check([AclOf(file) isEqualToArray:@[AclEntry(YES, YES, kB, ACL_READ_DATA | ACL_READ_ATTRIBUTES |
                                                           ACL_READ_EXTATTRIBUTES | ACL_READ_SECURITY,
                                                           ACL_ENTRY_INHERITED)]],
                   "the published file carries only B's inherited read entry");
    } else {
        f += Check(NO, "exactly one published file");
    }
    return f;
}

static int RunTempThenExclusiveRename(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox");
    NSString *paths[2] = { @"/shared/.flycut-share-7002", @"/shared/.flycut-share-7002/from-7001" };
    for (int p = 0; p < 2; p++) {
        NSString *final = paths[p];
        NSInteger mkdirAt = -1, chmodAt = -1, aclAt = -1, renameAt = -1;
        BOOL directMkdir = NO;
        NSString *tmp = nil;
        for (NSUInteger i = 0; i < [gTrace count]; i++) {
            NSString *line = [gTrace objectAtIndex:i];
            NSString *target = [[line componentsSeparatedByString:@" "] lastObject];
            if ([line hasPrefix:@"mkdir "] && [target isEqualToString:final]) directMkdir = YES;
            if ([line hasPrefix:@"mkdir "] && [target hasPrefix:[final stringByAppendingString:@".tmp-"]] && mkdirAt < 0) {
                mkdirAt = (NSInteger)i;
                tmp = target;
            }
            if (tmp != nil && [line hasPrefix:@"chmod "] && [target isEqualToString:tmp] && chmodAt < 0) chmodAt = (NSInteger)i;
            if (tmp != nil && [line hasPrefix:@"acl "] && [target isEqualToString:tmp] && aclAt < 0) aclAt = (NSInteger)i;
            if ([line hasPrefix:@"rename-excl "] && [target isEqualToString:final] && renameAt < 0) renameAt = (NSInteger)i;
        }
        f += Check(!directMkdir, "the final name is never created directly");
        if (p == 0) {
            // The deny-delete entry would block the exclusive rename: the root gets it right after.
            NSInteger aclAfter = -1;
            for (NSUInteger i = renameAt >= 0 ? (NSUInteger)renameAt : [gTrace count]; i < [gTrace count]; i++) {
                NSString *line = [gTrace objectAtIndex:i];
                if ([line hasPrefix:@"acl "] && [[[line componentsSeparatedByString:@" "] lastObject] isEqualToString:final]) {
                    aclAfter = (NSInteger)i;
                    break;
                }
            }
            f += Check(aclAfter > renameAt && renameAt >= 0, "the root gets its full ACL (deny delete) right after the exclusive rename");
        }
        f += Check(mkdirAt >= 0 && chmodAt > mkdirAt && aclAt > mkdirAt && renameAt > aclAt && renameAt > chmodAt,
                   "created under a temporary name, mode and ACL set, then renamed with RENAME_EXCL");
    }
    BOOL tmpLeft = NO;
    for (NSString *name in [Entries(gShared) arrayByAddingObjectsFromArray:Entries(TopPath(kB))])
        if ([name rangeOfString:@".tmp-"].location != NSNotFound) tmpLeft = YES;
    f += Check(!tmpLeft, "no temporary directory is left behind");
    return f;
}

static int RunPreplantedRefused(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    // (a) A symlink at the final name, pointing at a decoy directory.
    NSString *decoy = [[NSString stringWithUTF8String:gRoot] stringByAppendingPathComponent:@"decoy"];
    PlantDir(decoy, kC, 0777);
    symlink([decoy fileSystemRepresentation], [TopPath(kB) fileSystemRepresentation]);
    f += Check(!Prepare(b, @[@(kA)]), "a symlink at the inbox name is refused");
    f += Check([Entries(decoy) count] == 0, "nothing is created through the symlink");
    unlink([TopPath(kB) fileSystemRepresentation]);
    // (b) A directory of another account at the final name.
    // Planted directories inherit the replica's staff ACE; it must stay as it is.
    PlantDir(TopPath(kB), kC, 0755);
    NSString *inode = InodeOf(TopPath(kB));
    NSArray *plantedAcl = AclOf(TopPath(kB));
    f += Check(!Prepare(b, @[@(kA)]), "a directory owned by another account is refused");
    f += Check([InodeOf(TopPath(kB)) isEqualToString:inode] && [Entries(TopPath(kB)) count] == 0
               && OwnerOf(TopPath(kB)) == kC && ModeOf(TopPath(kB)) == 0755 && [AclOf(TopPath(kB)) isEqualToArray:plantedAcl],
               "the foreign directory is left untouched: same inode, no entries, mode and ACL unchanged");
    rmdir([TopPath(kB) fileSystemRepresentation]);
    // (c) Another account wins the race between the temporary directory and the rename.
    NSString *target = TopPath(kB);
    __block NSString *planted = nil;
    __block NSArray *racedAcl = nil;
    gBeforeRename = ^(int toFD, const char *toName) {
        if (planted == nil && strcmp(toName, ".flycut-share-7002") == 0) {
            PlantDir(target, kC, 0755);
            planted = [InodeOf(target) retain];
            racedAcl = [AclOf(target) retain];
        }
    };
    f += Check(!Prepare(b, @[@(kA)]), "losing the creation race to another account is refused");
    gBeforeRename = nil;
    f += Check(planted != nil && [InodeOf(target) isEqualToString:planted] && OwnerOf(target) == kC
               && [Entries(target) count] == 0 && ModeOf(target) == 0755 && [AclOf(target) isEqualToArray:racedAcl],
               "the racing account's directory is not replaced, used or changed");
    BOOL tmpLeft = NO;
    for (NSString *name in Entries(gShared))
        if ([name rangeOfString:@".tmp-"].location != NSNotFound) tmpLeft = YES;
    f += Check(!tmpLeft, "the temporary directory is removed after the lost race");
    return f;
}

// Another account adds an entry to the temporary inbox before its exact ACL
// is set (until then the inherited staff entry lets it): right after the
// engine made it, and just before the ACL write. The inbox is not published
// with it, the temporary folder goes, and the next try works.
static int RunTempPlanted(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    const char *prefix = ".flycut-share-7002.tmp-";
    for (int round = 0; round < 2; round++) {
        __block BOOL planted = NO;
        gAfterOpen = ^(int fd, const char *name) {
            (void)fd;
            if (round != 0 || planted || strncmp(name, prefix, strlen(prefix)) != 0)
                return;
            NSString *tmp = [gShared stringByAppendingPathComponent:[NSString stringWithUTF8String:name]];
            planted = PlantValid(tmp, NewClipName(), @"example-tp1 alpha", kC);
        };
        gBeforeACL = ^(int fd) {
            NSString *tmp = PathOfFD(fd);
            if (round != 1 || planted || tmp == nil || ![[tmp lastPathComponent] hasPrefix:@(prefix)])
                return;
            planted = PlantDir([tmp stringByAppendingPathComponent:@"from-7001"], kC, 0755);
        };
        BOOL ok = Prepare(b, @[@(kA)]);
        gAfterOpen = nil;
        gBeforeACL = nil;
        f += Check(planted, round == 0 ? "another account adds a file to B's temporary inbox before its exact ACL"
                                       : "another account adds a from-7001 folder to B's temporary inbox before its exact ACL");
        f += Check(!ok && !Exists(TopPath(kB)), "the inbox is not published with the planted entry");
        BOOL tmpLeft = NO;
        for (NSString *name in Entries(gShared))
            if ([name rangeOfString:@".tmp-"].location != NSNotFound) tmpLeft = YES;
        f += Check(!tmpLeft, "the temporary folder is removed with what was planted in it");
    }
    f += Check(Prepare(b, @[@(kA)]) && IsRealDirectory(FromPath(kB, kA)) && [Entries(TopPath(kB)) count] == 1,
               "the next try sets the inbox up");
    return f;
}

static int RunRebuildWrongInbox(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    NSString *top = TopPath(kB), *from = FromPath(kB, kA);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox");
    // (a) An extra entry on from-A: pickup refuses the folder, preparing rebuilds it.
    PlantValid(from, NewClipName(), @"example-06", kA);
    AddAclEntry(from, NO, 20, ACL_LIST_DIRECTORY, 0);
    gReads = 0;
    f += Check([Collect(b) count] == 0 && gReads == 0, "pickup reads nothing from a folder with a wrong ACL");
    f += Check(Prepare(b, @[@(kA)]), "preparing again succeeds");
    f += Check([AclOf(from) isEqualToArray:ExpectedFromAcl(kB, kA)] && [Entries(from) count] == 0,
               "from-A is rebuilt with the exact ACL and without the unverified content");
    // (b) Wrong mode on the inbox root.
    chmod([top fileSystemRepresentation], 0755);
    PlantValid(from, NewClipName(), @"example-07", kA);
    gReads = 0;
    f += Check([Collect(b) count] == 0 && gReads == 0, "pickup reads nothing below a root with the wrong mode");
    f += Check(Prepare(b, @[@(kA)]) && ModeOf(top) == 0700 && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])],
               "the root's mode and ACL are restored");
    // (c) from-A replaced by a symlink to a decoy.
    NSString *decoy = [[NSString stringWithUTF8String:gRoot] stringByAppendingPathComponent:@"decoy"];
    PlantDir(decoy, kB, 0700);
    PlantValid(decoy, NewClipName(), @"example-08", kA);
    char tmpPath[PATH_MAX];
    snprintf(tmpPath, sizeof tmpPath, "%s.moved", [from fileSystemRepresentation]);
    rename([from fileSystemRepresentation], tmpPath);
    symlink([decoy fileSystemRepresentation], [from fileSystemRepresentation]);
    gReads = 0;
    f += Check([Collect(b) count] == 0 && gReads == 0, "pickup does not follow a symlinked sender folder");
    f += Check([Entries(decoy) count] == 1, "the symlink's target is left untouched by pickup");
    f += Check(Prepare(b, @[@(kA)]) && IsRealDirectory(from) && [AclOf(from) isEqualToArray:ExpectedFromAcl(kB, kA)],
               "the symlink is replaced by a real sender folder");
    f += Check([Entries(decoy) count] == 1, "the symlink's target is left untouched by preparing");
    // (d) The sender list changes: entries follow it.
    f += Check(Prepare(b, @[@(kA), @(kUnchosen)]) && IsRealDirectory(FromPath(kB, kUnchosen))
               && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA), @(kUnchosen)])],
               "adding a sender adds its folder and its search entry");
    f += Check(Prepare(b, @[@(kUnchosen)]) && !Exists(from) && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kUnchosen)])],
               "removing a sender removes its folder and its search entry");
    return f;
}

static int RunSenderRefusesUntrustedInbox(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    NSInteger code = 0;
    // (a) No inbox: B has not opted in.
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, &code) && code == FlycutAccountShareErrorNoInbox,
               "without B's inbox A writes nothing");
    f += Check(!Exists(TopPath(kB)), "A creates no directory in B's place");
    // (b) The inbox root belongs to another account.
    PlantDir(TopPath(kB), kC, 0700);
    PlantDir(FromPath(kB, kA), kC, 0700);
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, NULL), "A refuses an inbox root owned by another account");
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "nothing is written into the foreign inbox");
    rmdir([FromPath(kB, kA) fileSystemRepresentation]);
    rmdir([TopPath(kB) fileSystemRepresentation]);
    // (c) B's root, but from-A belongs to another account.
    f += Check(Prepare(b, @[@(kA), @(kUnchosen)]), "B creates its inbox");
    NSString *from = FromPath(kB, kA);
    NSString *moved = [TopPath(kB) stringByAppendingPathComponent:@"moved"];
    rename([from fileSystemRepresentation], [moved fileSystemRepresentation]);
    PlantDir(from, kC, 0700);
    acl_t acl = acl_get_link_np([moved fileSystemRepresentation], ACL_TYPE_EXTENDED);
    acl_set_link_np([from fileSystemRepresentation], ACL_TYPE_EXTENDED, acl);
    acl_free(acl);
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, NULL) && [Entries(from) count] == 0,
               "A refuses a sender folder owned by another account");
    rmdir([from fileSystemRepresentation]);
    rename([moved fileSystemRepresentation], [from fileSystemRepresentation]);
    // (d) An extra ACL entry on from-A.
    AddAclEntry(from, NO, 20, ACL_LIST_DIRECTORY, 0);
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, NULL) && [Entries(from) count] == 0,
               "A refuses a sender folder whose ACL grants anyone else access");
    f += Check(Prepare(b, @[@(kA), @(kUnchosen)]), "B repairs its inbox");
    // (e) Wrong mode on from-A.
    chmod([from fileSystemRepresentation], 0755);
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, NULL) && [Entries(from) count] == 0,
               "A refuses a sender folder with the wrong mode");
    f += Check(Prepare(b, @[@(kA), @(kUnchosen)]), "B repairs its inbox again");
    // (f) from-A is a symlink to a folder that B made for someone else.
    rename([from fileSystemRepresentation], [moved fileSystemRepresentation]);
    symlink([FromPath(kB, kUnchosen) fileSystemRepresentation], [from fileSystemRepresentation]);
    f += Check(!Send(a, @"example-09", kPlainTypes(), nil, kB, NULL) && [Entries(FromPath(kB, kUnchosen)) count] == 0,
               "A does not follow a symlinked sender folder");
    // An unchosen account has no folder and cannot write either.
    FlycutAccountShare *c = Participant(kC);
    f += Check(!Send(c, @"example-09", kPlainTypes(), nil, kB, &code) && code == FlycutAccountShareErrorNoInbox,
               "an account B did not choose has no inbox to write into");
    f += Check(!TraceHas(@"mkdir 7001 ") && !TraceHas(@"mkdir 4242 "), "senders never create directories");
    return f;
}

static int RunForeignOwner(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    f += Check(PlantValid(from, NewClipName(), @"example-10", kC), "a file owned by another account lands in from-A");
    f += Check(PlantValid(from, NewClipName(), @"example-11", kB), "a file owned by B itself lands in from-A");
    gReads = 0;
    NSArray *got = Collect(b);
    f += Check([got count] == 0, "files whose owner is not A are rejected");
    f += Check(gReads == 0, "rejected files are never read");
    f += Check([Entries(from) count] == 0, "rejected files are deleted");
    return f;
}

static int RunSpecialFiles(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    NSString *root = [NSString stringWithUTF8String:gRoot];
    NSString *decoy = [root stringByAppendingPathComponent:@"decoy.clip"];
    for (int round = 0; round < 2; round++) {
        PlantValid(root, @"decoy.clip", @"example-12", kA);
        NSString *decoyInode = InodeOf(decoy);
        NSString *symlinkPath = [from stringByAppendingPathComponent:NewClipName()];
        symlink([decoy fileSystemRepresentation], [symlinkPath fileSystemRepresentation]);
        RegisterOwnerOfPath(symlinkPath, kA);
        NSString *hard = NewClipName();
        PlantValid(from, hard, @"example-13", kA);
        link([[from stringByAppendingPathComponent:hard] fileSystemRepresentation],
             [[from stringByAppendingPathComponent:NewClipName()] fileSystemRepresentation]);
        NSString *fifo = [from stringByAppendingPathComponent:NewClipName()];
        mkfifo([fifo fileSystemRepresentation], 0600);
        RegisterOwnerOfPath(fifo, kA);
        PlantDir([from stringByAppendingPathComponent:NewClipName()], kA, 0700);
        NSMutableData *big = [NSMutableData dataWithLength:[FlycutAccountShare payloadSizeLimit] + 1];
        Plant(from, NewClipName(), big, kA, gNow);
        Plant(from, NewClipName(), [NSData data], kA, gNow);
        if (round == 1)
            PlantValid(from, NewClipName(), @"example-14", kA);
        gReads = 0;
        NSArray *got = Collect(b);
        if (round == 0) {
            f += Check([got count] == 0 && gReads == 0,
                       "symlink, hard links, FIFO, directory, oversize and empty files are rejected unread");
        } else {
            f += Check([got count] == 1 && [[[got objectAtIndex:0] text] isEqualToString:@"example-14"],
                       "a valid file next to rejected ones is still picked up");
        }
        f += Check([Entries(from) count] == 0, "every rejected entry is removed");
        f += Check([InodeOf(decoy) isEqualToString:decoyInode], "the symlink's target is untouched");
        unlink([decoy fileSystemRepresentation]);
    }
    return f;
}

static int RunUnknownSenderFolder(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A only");
    NSString *unknown = FromPath(kB, kC);
    PlantDir(unknown, kB, 0700);
    PlantValid(unknown, NewClipName(), @"example-15", kC);
    f += Check(Send(a, @"example-16", kPlainTypes(), nil, kB, NULL), "A shares a clipping");
    gReads = 0;
    NSArray *got = Collect(b);
    f += Check([got count] == 1 && [[got objectAtIndex:0] senderUID] == kA, "only the chosen sender's clipping is returned");
    f += Check([Entries(unknown) count] == 1, "a folder for an unchosen sender is not read or emptied by pickup");
    f += Check(Prepare(b, @[@(kA)]) && !Exists(unknown), "preparing removes the folder of an unchosen sender");
    return f;
}

static int RunNeverShareFilters(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    NSArray *factoryTypes = [[[[defaults stringForKey:@"skipPboardTypesList"] stringByAppendingFormat:@",%@",
                               [defaults stringForKey:@"skipConcealedTypesList"]]
                              stringByReplacingOccurrencesOfString:@" " withString:@""] componentsSeparatedByString:@","];
    NSArray *floor = [FlycutOperator neverSharedTypes];
    BOOL covered = [factoryTypes count] == 5;
    for (NSString *type in factoryTypes)
        if (![floor containsObject:type]) covered = NO;
    f += Check(covered, "the operator's never-share list holds every type of Flycut's factory skip lists");
    NSArray *types = [factoryTypes arrayByAddingObjectsFromArray:
                      @[@"de.petermaurer.TransientPasteboardType", @"com.typeit4me.clipping", @"Pasteboard generator type"]];
    NSDictionary *rich = @{@"public.rtf": [@"{\\rtf1 x}" dataUsingEncoding:NSUTF8StringEncoding]};
    BOOL allRefused = YES;
    for (int setting = 0; setting < 3; setting++) {
        [gOperator release];
        gOperator = FreshOperator();
        [a setFilter:(id<FlycutAccountShareFilter>)gOperator];
        if (setting == 1) {
            [defaults setObject:@NO forKey:@"skipPboardTypes"];
            [defaults setObject:@NO forKey:@"skipConcealedTypes"];
            [defaults setObject:@NO forKey:@"skipPasswordFields"];
        } else if (setting == 2) {
            [defaults setObject:@"" forKey:@"skipPboardTypesList"];
            [defaults setObject:@"" forKey:@"skipConcealedTypesList"];
        }
        for (NSString *type in types) {
            NSInteger code = 0;
            BOOL sent = Send(a, @"example-17", @[@"public.utf8-plain-text", @"public.rtf", type], rich, kB, &code);
            if (sent || code != FlycutAccountShareErrorRefused) allRefused = NO;
        }
    }
    f += Check(allRefused, "password-manager, concealed, transient and auto-generated clippings are refused "
                           "with the local filters on, off and with emptied lists");
    f += Check([Entries(from) count] == 0, "no file and no rich data reach the inbox for them");
    // The password check is the operator's, always on for sharing.
    [defaults reset];
    [gOperator release];
    gOperator = FreshOperator();
    [a setFilter:(id<FlycutAccountShareFilter>)gOperator];
    NSInteger code = 0;
    BOOL heuristicRefused = YES;
    for (NSNumber *local in @[@YES, @NO]) {
        [defaults setObject:local forKey:@"skipPasswordFields"];
        [defaults setObject:local forKey:@"skipPasswordLengths"];
        code = 0;
        if (Send(a, @"Ab3$efGh9!xY", kPlainTypes(), nil, kB, &code) || code != FlycutAccountShareErrorRefused)
            heuristicRefused = NO;
    }
    f += Check(heuristicRefused && [Entries(from) count] == 0,
               "a text the operator's password check flags is refused, also with the local check off");
    f += Check(Send(a, @"example-17 ordinary", kPlainTypes(), nil, kB, NULL),
               "an ordinary text is shared with the local check off");
    f += Check([Collect(b) count] == 1, "and picked up");
    f += Check(!Send(a, @"example-18", nil, nil, kB, &code) && code == FlycutAccountShareErrorRefused,
               "a clipping without a type snapshot is refused");
    f += Check(!Send(a, @"", kPlainTypes(), nil, kB, &code) && code == FlycutAccountShareErrorRefused,
               "an empty clipping is refused");
    [a setFilter:nil];
    f += Check(!Send(a, @"example-19", kPlainTypes(), nil, kB, &code) && code == FlycutAccountShareErrorRefused,
               "without a filter nothing is shared");
    f += Check([Entries(from) count] == 0, "none of the refused clippings left a file");
    return f;
}

static int RunFlood(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    NSUInteger limit = [FlycutAccountShare filesPerSenderLimit];
    f += Check(limit == 10, "the per-sender limit is 10 files");
    for (int i = 0; i < 15; i++) {
        gNow += 1;
        Send(a, [NSString stringWithFormat:@"example-flood-%02d", i], kPlainTypes(), nil, kB, NULL);
    }
    f += Check([ClipNames(from) count] == limit, "the sender keeps at most 10 files in the inbox");
    NSArray *got = Collect(b);
    BOOL newestInOrder = [got count] == limit;
    for (NSUInteger i = 0; newestInOrder && i < limit; i++)
        if (![[[got objectAtIndex:i] text] isEqualToString:[NSString stringWithFormat:@"example-flood-%02lu", (unsigned long)(i + 5)]])
            newestInOrder = NO;
    f += Check(newestInOrder, "the 10 newest survive, returned oldest first");
    // A sender that ignores the limit: the recipient reads at most 10 per pass.
    for (int i = 0; i < 15; i++) {
        NSString *name = NewClipName();
        NSMutableDictionary *payload = ValidPayload(name, [NSString stringWithFormat:@"example-burst-%02d", i]);
        [payload setObject:[NSNumber numberWithDouble:gNow - 15 + i] forKey:@"created"];
        Plant(from, name, Plist(payload, NSPropertyListBinaryFormat_v1_0), kA, gNow - 15 + i);
    }
    NSString *stale = NewClipName();
    Plant(from, stale, Plist(ValidPayload(stale, @"example-stale"), NSPropertyListBinaryFormat_v1_0), kA,
          gNow - 25 * 3600);
    got = Collect(b);
    newestInOrder = [got count] == limit;
    for (NSUInteger i = 0; newestInOrder && i < limit; i++)
        if (![[[got objectAtIndex:i] text] isEqualToString:[NSString stringWithFormat:@"example-burst-%02lu", (unsigned long)(i + 5)]])
            newestInOrder = NO;
    f += Check(newestInOrder, "a flooding sender gets at most its 10 newest files accepted");
    f += Check([Entries(from) count] == 0, "the rest, and a file older than 24 hours, are deleted");
    return f;
}

static int RunMalformed(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    NSMutableArray *bad = [NSMutableArray array];
    NSString *n;
    n = NewClipName(); [bad addObject:@[n, [@"not a property list" dataUsingEncoding:NSUTF8StringEncoding]]];
    n = NewClipName(); [bad addObject:@[n, Plist(ValidPayload(n, @"example-20"), NSPropertyListXMLFormat_v1_0)]];
    NSMutableDictionary *p;
    n = NewClipName(); p = ValidPayload(n, @"example-21"); [p setObject:@2 forKey:@"v"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-22"); [p setObject:(id)kCFBooleanTrue forKey:@"v"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-23"); [p setObject:@"x" forKey:@"extra"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-24"); [p setObject:[NSData data] forKey:@"text"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(NewClipName(), @"example-25");
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-26"); [p setObject:[NSNumber numberWithDouble:gNow - 25 * 3600] forKey:@"created"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-27"); [p setObject:[NSNumber numberWithDouble:gNow + 3600] forKey:@"created"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @""); [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-28"); [p removeObjectForKey:@"text"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-29"); [p setObject:@"rtf" forKey:@"rtf"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); p = ValidPayload(n, @"example-30"); [p setObject:@7 forKey:@"app"];
    [bad addObject:@[n, Plist(p, NSPropertyListBinaryFormat_v1_0)]];
    n = NewClipName(); [bad addObject:@[n, Plist(@[@1, @2], NSPropertyListBinaryFormat_v1_0)]];
    NSString *lower = [[[[NSUUID UUID] UUIDString] lowercaseString] stringByAppendingString:@".clip"];
    [bad addObject:@[lower, Plist(ValidPayload(lower, @"example-31"), NSPropertyListBinaryFormat_v1_0)]];
    [bad addObject:@[@"foo.clip", Plist(ValidPayload(@"foo.clip", @"example-32"), NSPropertyListBinaryFormat_v1_0)]];
    NSString *bare = [[NSUUID UUID] UUIDString];
    [bad addObject:@[bare, Plist(ValidPayload(bare, @"example-33"), NSPropertyListBinaryFormat_v1_0)]];
    NSString *staleTmp = [[[NSUUID UUID] UUIDString] stringByAppendingString:@".tmp"];
    Plant(from, staleTmp, [NSData dataWithBytes:"x" length:1], kA, gNow - 3600);
    NSString *freshTmp = [[[NSUUID UUID] UUIDString] stringByAppendingString:@".tmp"];
    Plant(from, freshTmp, [NSData dataWithBytes:"x" length:1], kA, gNow);
    // Batches stay below the per-pass limit, so the parser reads every bad file.
    BOOL onlyGood = YES, allGone = YES;
    for (NSUInteger start = 0; start < [bad count]; start += 5) {
        for (NSUInteger i = start; i < start + 5 && i < [bad count]; i++)
            Plant(from, [[bad objectAtIndex:i] objectAtIndex:0], [[bad objectAtIndex:i] objectAtIndex:1], kA, gNow);
        PlantValid(from, NewClipName(), @"example-34", kA);
        NSArray *got = Collect(b);
        if (!([got count] == 1 && [[[got objectAtIndex:0] text] isEqualToString:@"example-34"])) onlyGood = NO;
        if (![Entries(from) isEqualToArray:@[freshTmp]]) allGone = NO;
    }
    f += Check(onlyGood, "only the well-formed clipping is accepted");
    f += Check(allGone, "malformed, misnamed, expired and stale entries are deleted; an in-progress temporary file is kept");
    return f;
}

static int RunSizeLimit(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSUInteger limit = [FlycutAccountShare payloadSizeLimit];
    f += Check(limit == 1048576, "the payload limit is 1 MiB");
    NSMutableString *huge = [NSMutableString stringWithCapacity:limit + 1];
    while ([huge length] <= limit) [huge appendString:@"x"];
    NSInteger code = 0;
    f += Check(!Send(a, huge, kPlainTypes(), nil, kB, &code) && code == FlycutAccountShareErrorTooLarge,
               "a clipping above 1 MiB is refused");
    f += Check([Entries(FromPath(kB, kA)) count] == 0, "and leaves no file, not even a temporary one");
    NSString *large = [huge substringToIndex:limit / 2];
    f += Check(Send(a, large, kPlainTypes(), nil, kB, NULL), "half a MiB is shared");
    NSArray *got = Collect(b);
    f += Check([got count] == 1 && [[[got objectAtIndex:0] text] isEqualToString:large], "and arrives complete");
    return f;
}

static int RunWipe(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]) && Prepare(a, @[@(kB)]), "both inboxes exist");
    Send(a, @"example-35", kPlainTypes(), nil, kB, NULL);
    Send(a, @"example-36", kPlainTypes(), nil, kB, NULL);
    Send(b, @"example-37", kPlainTypes(), nil, kA, NULL);
    PlantValid(FromPath(kB, kA), [[[NSUUID UUID] UUIDString] stringByAppendingString:@".tmp"], @"example-38", kA);
    gActor = kB;
    f += Check([b wipeInbox:NULL], "B wipes its inbox");
    f += Check(!Exists(TopPath(kB)), "B's inbox and everything in it are gone");
    f += Check([ClipNames(FromPath(kA, kB)) count] == 1, "A's inbox is untouched");
    f += Check([b wipeInbox:NULL], "wiping again succeeds");
    PlantDir(TopPath(kB), kC, 0700);
    PlantValid(TopPath(kB), NewClipName(), @"example-39", kC);
    f += Check(![b wipeInbox:NULL] && [Entries(TopPath(kB)) count] == 1, "a foreign directory at B's name is not wiped");
    return f;
}

// Any account in staff may delete_child in /Users/Shared (sticky bit or
// not), so without its own deny entry a recipient's inbox root could be
// renamed away and its name squatted. The node's deny entry wins and binds the
// owner too, so this same-UID fixture can show it.
static int RunRootCannotBeMoved(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB), *u = Participant(kUnchosen);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *top = TopPath(kB);
    NSString *inode = InodeOf(top);
    NSString *squat = [gShared stringByAppendingPathComponent:@"squatted"];
    errno = 0;
    BOOL renamed = rename([top fileSystemRepresentation], [squat fileSystemRepresentation]) == 0;
    int renameErrno = errno;
    f += Check(!renamed && renameErrno == EACCES && !Exists(squat), "the inbox root cannot be renamed away (EACCES)");
    f += Check(Prepare(u, @[]), "7003 makes an inbox for nobody (an empty root)");
    errno = 0;
    BOOL removed = rmdir([TopPath(kUnchosen) fileSystemRepresentation]) == 0;
    int rmdirErrno = errno;
    f += Check(!removed && rmdirErrno == EACCES && IsRealDirectory(TopPath(kUnchosen)),
               "an empty inbox root cannot be deleted (EACCES)");
    f += Check([InodeOf(top) isEqualToString:inode] && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])]
               && [AclOf(TopPath(kUnchosen)) isEqualToArray:ExpectedTopAcl(@[])],
               "both stay where they were made, each with exactly its ACL");
    // The sender checks the root's owner, the pickup its exact ACL: both still agree.
    f += Check(Send(a, @"example-f12", kPlainTypes(), nil, kB, NULL), "A still writes into from-A");
    f += Check([Collect(b) count] == 1, "and B's pickup, which reads the root's ACL back exactly, takes it in");
    // An inbox made before the deny entry existed: pickup refuses it, prepare repairs it.
    BOOL old = ClearAclOf(top) && AddAclEntry(top, YES, kA, ACL_SEARCH, 0);
    f += Check(old && [AclOf(top) isEqualToArray:@[kTopSenderEntry(kA)]], "an older inbox root has only A's search entry");
    PlantValid(FromPath(kB, kA), NewClipName(), @"example-f12b", kA);
    gReads = 0;
    f += Check([Collect(b) count] == 0 && gReads == 0, "pickup reads nothing below a root without the deny entry");
    f += Check(Prepare(b, @[@(kA)]) && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])], "preparing adds the deny entry back");
    // The owner still removes it when sharing goes off: the ACL goes first.
    gActor = kB;
    f += Check([b wipeInbox:NULL] && !Exists(top), "B still wipes its own inbox");
    gActor = kUnchosen;
    f += Check([u wipeInbox:NULL] && !Exists(TopPath(kUnchosen)), "and so does 7003");
    return f;
}


// Three defence-in-depth checks that no other case pins: without them
// any one of these checks could go and every other case would still pass.

// The sender appends to a file after pickup checked its size: the read must
// reach the end exactly where the size said, else the file is not taken in.
static int RunGrowsAfterCheck(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    NSString *name = NewClipName();
    PlantValid(from, name, @"example-f13a", kA);
    NSString *path = [from stringByAppendingPathComponent:name];
    __block BOOL grown = NO;
    gBeforeRead = ^(int fd) {
        (void)fd;
        int w = open([path fileSystemRepresentation], O_WRONLY | O_APPEND);
        if (w >= 0) {
            grown = write(w, "x", 1) == 1;
            close(w);
        }
    };
    NSArray *got = Collect(b);
    gBeforeRead = nil;
    f += Check(grown, "A appends to its file after B's pickup checked the size");
    f += Check([got count] == 0, "a file that grew after its size was checked is not taken in");
    f += Check(!Exists(path), "and it is deleted");
    PlantValid(from, NewClipName(), @"example-f13b", kA);
    f += Check([Collect(b) count] == 1, "a file that does not change is taken in");
    return f;
}

// B's folder for A is moved out of B's inbox right after A opened it: A must
// see that the folder's parent is no longer the inbox root it opened.
static int RunFolderMovedAfterOpen(void) {
    int f = 0;
    FlycutAccountShare *a = Participant(kA), *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *elsewhere = [gShared stringByAppendingPathComponent:@"elsewhere"];
    PlantDir(elsewhere, kB, 0700);
    NSString *moved = [elsewhere stringByAppendingPathComponent:@"from-7001"];
    NSString *original = FromPath(kB, kA);
    __block BOOL didMove = NO;
    gAfterOpen = ^(int fd, const char *name) {
        (void)fd;
        if (!didMove && gActor == kA && strcmp(name, "from-7001") == 0)
            didMove = rename([original fileSystemRepresentation], [moved fileSystemRepresentation]) == 0;
    };
    NSInteger code = 0;
    BOOL sent = Send(a, @"example-f13c", kPlainTypes(), nil, kB, &code);
    gAfterOpen = nil;
    f += Check(didMove, "B's folder for A is moved elsewhere right after A opened it");
    f += Check(!sent && code == FlycutAccountShareErrorUntrustedInbox, "A refuses a folder that is no longer inside B's inbox");
    f += Check([Entries(moved) count] == 0, "and writes nothing into it");
    return f;
}

// The sender replaces a file under the same name while pickup reads it:
// pickup deletes only the file it checked, the new one waits for the next pass.
static int RunReplacedBeforeDelete(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    NSString *from = FromPath(kB, kA);
    NSString *name = NewClipName();
    PlantValid(from, name, @"example-f13d", kA);
    NSString *path = [from stringByAppendingPathComponent:name];
    NSString *part = [from stringByAppendingPathComponent:@"replacement.part"];
    NSData *replacement = Plist(ValidPayload(name, @"example-f13e"), NSPropertyListBinaryFormat_v1_0);
    __block BOOL replaced = NO;
    gBeforeRead = ^(int fd) {
        (void)fd;
        replaced = Plant(from, @"replacement.part", replacement, kA, gNow)
            && rename([part fileSystemRepresentation], [path fileSystemRepresentation]) == 0;
    };
    NSArray *got = Collect(b);
    gBeforeRead = nil;
    f += Check(replaced, "A replaces its file under the same name while B's pickup reads it");
    f += Check([got count] == 1 && [[[got objectAtIndex:0] text] isEqualToString:@"example-f13d"],
               "pickup takes in the file it checked");
    f += Check(Exists(path), "the replacement under the same name is not deleted unread");
    NSArray *next = Collect(b);
    f += Check([next count] == 1 && [[[next objectAtIndex:0] text] isEqualToString:@"example-f13e"] && !Exists(path),
               "the next pickup takes it in");
    return f;
}

// Until the inbox root carries its deny entry another account can still
// move it away (the name is published in a folder every staff account may
// change). After setting the entry the engine must find the folder under its
// name; if not, it lifts the ACL from the moved folder (the entry would bind
// its owner too) and fails, instead of building the inbox in the moved folder.
// The moves happen right before the root's full ACL is written: after the
// check -createDirectoryNamed: does right after its rename.
static int RunMovedBeforeDeny(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    NSString *top = TopPath(kB);
    NSString *squat = [gShared stringByAppendingPathComponent:@"squatted"];
    NSString *squatFrom = [squat stringByAppendingPathComponent:@"from-7001"];
    const char *ctop = [top fileSystemRepresentation], *csquat = [squat fileSystemRepresentation];
    __block int step = 0;   // what the other account does: 1 move, 2 move + own dir, 3 move + symlink
    __block BOOL didMove = NO;
    __block NSArray *plantedAcl = nil;
    __block NSString *plantedInode = nil;
    gBeforeACL = ^(int fd) {
        if (didMove || step == 0 || ![PathOfFD(fd) hasSuffix:@"/.flycut-share-7002"] || rename(ctop, csquat) != 0)
            return;
        didMove = YES;
        if (step == 2) {
            PlantDir(top, kC, 0755);
            plantedInode = [InodeOf(top) retain];
            plantedAcl = [AclOf(top) retain];
        } else if (step == 3) {
            symlink("squatted", ctop);
        }
    };
    NSError *error = nil;
    // (a) Moved away; nothing at the name.
    step = 1;
    gActor = kB;
    BOOL ok = [b prepareInboxForSenders:@[@(kA)] error:&error];
    f += Check(didMove, "another account moves B's new inbox away before its deny entry is set");
    f += Check(!ok && [error code] == FlycutAccountShareErrorUntrustedInbox, "B notices and reports an untrusted inbox");
    f += Check([AclOf(squat) count] == 0 && !Exists(squatFrom), "the moved folder keeps no ACL entry and gets no sender folder");
    f += Check(rmdir(csquat) == 0 && !Exists(top), "so its owner can remove it; the inbox name is free again");
    // (b) Moved away and the name taken by another account's directory.
    step = 2;
    didMove = NO;
    error = nil;
    gActor = kB;
    ok = [b prepareInboxForSenders:@[@(kA)] error:&error];
    f += Check(didMove && !ok && [error code] == FlycutAccountShareErrorUntrustedInbox,
               "with another account's directory put at the name B fails too");
    f += Check(plantedInode != nil && [InodeOf(top) isEqualToString:plantedInode] && OwnerOf(top) == kC && ModeOf(top) == 0755
               && [AclOf(top) isEqualToArray:plantedAcl] && [Entries(top) count] == 0,
               "that directory is left untouched");
    f += Check([AclOf(squat) count] == 0 && !Exists(squatFrom) && rmdir(csquat) == 0, "and B's moved folder keeps no ACL entry");
    rmdir(ctop);
    // (c) Moved away and a symlink to it put at the name.
    step = 3;
    didMove = NO;
    error = nil;
    gActor = kB;
    ok = [b prepareInboxForSenders:@[@(kA)] error:&error];
    f += Check(didMove && !ok && [error code] == FlycutAccountShareErrorUntrustedInbox,
               "a symlink at the name that leads to the moved folder does not count as the inbox");
    f += Check([AclOf(squat) count] == 0 && !Exists(squatFrom), "the moved folder keeps no ACL entry");
    unlink(ctop);
    rmdir(csquat);
    // (d) An older inbox without the deny entry, moved while it is repaired.
    step = 0;
    f += Check(Prepare(b, @[@(kA)]), "B sets its inbox up");
    BOOL old = ClearAclOf(top) && AddAclEntry(top, YES, kA, ACL_SEARCH, 0);
    step = 1;
    didMove = NO;
    error = nil;
    gActor = kB;
    ok = [b prepareInboxForSenders:@[@(kA)] error:&error];
    f += Check(old && didMove && !ok && [error code] == FlycutAccountShareErrorUntrustedInbox,
               "an older inbox moved away while its deny entry is added is refused as well");
    f += Check([AclOf(squat) count] == 0, "and keeps no ACL entry");
    step = 0;
    gBeforeACL = nil;
    ClearAclOf(squatFrom);
    rmdir([squatFrom fileSystemRepresentation]);
    rmdir(csquat);
    // (e) Moved right after the exclusive rename: -createDirectoryNamed:'s own check.
    __block BOOL early = NO;
    gAfterRename = ^(int toFD, const char *toName, int result) {
        (void)toFD;
        if (!early && result == 0 && strcmp(toName, ".flycut-share-7002") == 0)
            early = rename(ctop, csquat) == 0;
    };
    error = nil;
    gActor = kB;
    ok = [b prepareInboxForSenders:@[@(kA)] error:&error];
    gAfterRename = nil;
    f += Check(early && !ok && [error code] == FlycutAccountShareErrorUntrustedInbox
               && ![AclOf(squat) containsObject:kTopDenyDeleteEntry()] && rmdir(csquat) == 0,
               "a move right after the rename is refused at once, the moved folder has no deny entry");
    // An inbox that stayed where it was made passes the same check.
    f += Check(Prepare(b, @[@(kA)]) && Prepare(b, @[@(kA)]) && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])]
               && IsRealDirectory(FromPath(kB, kA)), "an inbox in place passes, also when it is prepared again");
    return f;
}

// Only a deny entry for everyone counts as the root's own.
// One that names a single group or account leaves the root movable by all
// the others: pickup refuses such a root, preparing puts the right one back.
static int CheckDenyQualifier(FlycutAccountShare *b, BOOL isUser, unsigned int qualifier, const char *refused,
                              const char *repaired) {
    int f = 0;
    NSString *top = TopPath(kB);
    BOOL set = ClearAclOf(top) && AddAclEntry(top, YES, kA, ACL_SEARCH, 0) && AddDenyEntry(top, isUser, qualifier, ACL_DELETE);
    NSArray *acl = AclOf(top);
    BOOL planted = set && [acl count] == 2 && [acl containsObject:kTopSenderEntry(kA)] && ![acl containsObject:kTopDenyDeleteEntry()]
        && PlantValid(FromPath(kB, kA), NewClipName(), @"example-g5", kA);
    gReads = 0;
    f += Check(planted && [Collect(b) count] == 0 && gReads == 0, refused);
    f += Check(Prepare(b, @[@(kA)]) && [AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])] && [Collect(b) count] == 1, repaired);
    return f;
}

static int RunDenyOnlyForEveryone(void) {
    int f = 0;
    FlycutAccountShare *b = Participant(kB);
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox for A");
    f += CheckDenyQualifier(b, NO, 20, "pickup refuses a root whose deny entry names the staff group instead of everyone",
                            "preparing puts the deny entry for everyone back, then the copy is taken in");
    f += CheckDenyQualifier(b, YES, kC, "pickup refuses a root whose deny entry names one account instead of everyone",
                            "preparing puts it back here too");
    return f;
}

// ---------------------------------------------------------------------------

// A replica of /Users/Shared: mode 1777 and exactly the staff ACE measured there.
// What the new directory inherited from the folders above the test root (the
// project tree carries an inheritable staff ACE, a temp dir may not) is replaced
// first, so every case sees the same parent wherever the root lies.
static BOOL ClearAcl(NSString *path) {
    acl_t empty = acl_init(0);
    int rc = empty != NULL ? acl_set_link_np([path fileSystemRepresentation], ACL_TYPE_EXTENDED, empty) : -1;
    if (empty != NULL) acl_free(empty);
    return rc == 0;
}

static BOOL MakeReplicaParent(NSString *path) {
    if (mkdir([path fileSystemRepresentation], 0777) != 0) return NO;
    if (chmod([path fileSystemRepresentation], 01777) != 0) return NO;
    RegisterOwnerOfPath(path, 0);
    if (!ClearAcl(path)) return NO;
    return AddAclEntry(path, NO, 20, kStaffPerms, ACL_ENTRY_FILE_INHERIT | ACL_ENTRY_DIRECTORY_INHERIT);
}


// Regression: a test root below a folder whose ACL hands an inheritable staff
// ACE down (as the project tree does) must not change the replica parent. The
// replica made below such a folder carries exactly the one staff ACE, and an
// inbox prepared there has its exact ACL.
static int RunReplicaUnderInheritingRoot(void) {
    int f = 0;
    NSString *above = [[NSString stringWithUTF8String:gRoot] stringByAppendingPathComponent:@"inheriting"];
    BOOL made = mkdir([above fileSystemRepresentation], 0755) == 0 && ClearAcl(above)
        && AddAclEntry(above, NO, 20, kStaffPerms, ACL_ENTRY_FILE_INHERIT | ACL_ENTRY_DIRECTORY_INHERIT);
    f += Check(made, "a folder with an inheritable staff ACE stands above the replica");
    NSString *replica = [above stringByAppendingPathComponent:@"shared"];
    NSString *probe = [above stringByAppendingPathComponent:@"probe"];
    BOOL inherits = mkdir([probe fileSystemRepresentation], 0700) == 0 && [AclOf(probe) count] == 1
        && [[AclOf(probe) objectAtIndex:0] hasSuffix:[NSString stringWithFormat:@"flags=%#x",
                                                         ACL_ENTRY_INHERITED | ACL_ENTRY_FILE_INHERIT |
                                                         ACL_ENTRY_DIRECTORY_INHERIT]];
    f += Check(inherits, "a plain directory made there inherits that ACE");
    f += Check(MakeReplicaParent(replica), "the replica parent is made below it");
    f += Check([AclOf(replica) isEqualToArray:ReplicaAcl()] && ModeOf(replica) == 01777,
               "the replica parent carries exactly the one staff ACE, not inherited, mode 1777");
    FlycutAccountShare *b = [[[FlycutAccountShare alloc]
        initWithSharedRoot:replica ownUID:kB
               ownerLookup:^uid_t(const struct stat *st) { return LookupOwner(st); }
                     clock:^NSTimeInterval { return gNow; }] autorelease];
    f += Check(Prepare(b, @[@(kA)]), "B creates its inbox there");
    NSString *top = [replica stringByAppendingPathComponent:@".flycut-share-7002"];
    f += Check([AclOf(top) isEqualToArray:ExpectedTopAcl(@[@(kA)])]
               && [AclOf([top stringByAppendingPathComponent:@"from-7001"]) isEqualToArray:ExpectedFromAcl(kB, kA)],
               "its inbox has the exact ACL there too");
    return f;
}

// The trace must refuse, not only count, what would leave the injected root: an
// engine pointed at a directory beside it (standing in for a real shared folder)
// creates nothing there. Run alone; it is the one case with violations.
static int RunTraceRefusesOutside(void) {
    int f = 0;
    NSString *outside = [[NSString stringWithUTF8String:gRoot] stringByAppendingString:@"-outside"];
    FlycutAccountShare *b = [[[FlycutAccountShare alloc]
        initWithSharedRoot:outside ownUID:kB
               ownerLookup:^uid_t(const struct stat *st) { return LookupOwner(st); }
                     clock:^NSTimeInterval { return gNow; }] autorelease];
    gActor = kB;
    BOOL prepared = [b prepareInboxForSenders:@[@(kA)] error:NULL];
    f += Check(!prepared, "an engine outside the injected root cannot prepare an inbox");
    f += Check(gViolations > 0, "the trace saw it try");
    f += Check([Entries(outside) count] == 0, "and nothing was created there");
    printf("REFUSED violations=%d\n", gViolations);
    gViolations = 0;
    return f;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        const uid_t simulated[] = { kA, kB, kC, kUnchosen };
        for (size_t i = 0; i < sizeof simulated / sizeof simulated[0]; i++) {
            if (getpwuid(simulated[i]) != NULL) {
                fprintf(stderr, "FAIL: simulated UID %u belongs to a real account; refusing to run\n", simulated[i]);
                return 2;
            }
        }
        if (realpath(argv[2], gRoot) == NULL) return 2;
        gTrace = [[NSMutableArray alloc] init];
        gOwners = [[NSMutableDictionary alloc] init];
        gNow = floor([[NSDate date] timeIntervalSince1970]);
        gShared = [[[NSString stringWithUTF8String:gRoot] stringByAppendingPathComponent:@"shared"] retain];
        if (!MakeReplicaParent(gShared)) {
            fprintf(stderr, "FAIL: could not build the replica parent\n");
            return 2;
        }
        gOperator = FreshOperator();
        const char *mode = argv[1];
        int failures = 3;
        if (strcmp(mode, "round-trip") == 0) failures = RunRoundTrip();
        else if (strcmp(mode, "acl-exact") == 0) failures = RunAclExact();
        else if (strcmp(mode, "temp-then-exclusive-rename") == 0) failures = RunTempThenExclusiveRename();
        else if (strcmp(mode, "preplanted-refused") == 0) failures = RunPreplantedRefused();
        else if (strcmp(mode, "temp-planted") == 0) failures = RunTempPlanted();
        else if (strcmp(mode, "rebuild-wrong-inbox") == 0) failures = RunRebuildWrongInbox();
        else if (strcmp(mode, "sender-refuses-untrusted-inbox") == 0) failures = RunSenderRefusesUntrustedInbox();
        else if (strcmp(mode, "foreign-owner") == 0) failures = RunForeignOwner();
        else if (strcmp(mode, "special-files") == 0) failures = RunSpecialFiles();
        else if (strcmp(mode, "unknown-sender-folder") == 0) failures = RunUnknownSenderFolder();
        else if (strcmp(mode, "never-share-filters") == 0) failures = RunNeverShareFilters();
        else if (strcmp(mode, "flood") == 0) failures = RunFlood();
        else if (strcmp(mode, "malformed") == 0) failures = RunMalformed();
        else if (strcmp(mode, "size-limit") == 0) failures = RunSizeLimit();
        else if (strcmp(mode, "wipe") == 0) failures = RunWipe();
        else if (strcmp(mode, "replica-under-inheriting-root") == 0) failures = RunReplicaUnderInheritingRoot();
        else if (strcmp(mode, "trace-refuses-outside") == 0) failures = RunTraceRefusesOutside();
        else if (strcmp(mode, "root-cannot-be-moved") == 0) failures = RunRootCannotBeMoved();
        else if (strcmp(mode, "grows-after-check") == 0) failures = RunGrowsAfterCheck();
        else if (strcmp(mode, "folder-moved-after-open") == 0) failures = RunFolderMovedAfterOpen();
        else if (strcmp(mode, "replaced-before-delete") == 0) failures = RunReplacedBeforeDelete();
        else if (strcmp(mode, "moved-before-deny") == 0) failures = RunMovedBeforeDeny();
        else if (strcmp(mode, "deny-only-for-everyone") == 0) failures = RunDenyOnlyForEveryone();
        printf("TRACE mutations=%d violations=%d\n", gMutations, gViolations);
        return failures + gViolations;
    }
}
