//
//  FlycutAccountShare.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// See FlycutAccountShare.h for the layout and the trust model. Every operation
// works relative to directory descriptors opened with O_NOFOLLOW and checked
// with fstat, so a path that is swapped while the engine works cannot redirect
// a read, a write or a deletion.

#import "FlycutAccountShare.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <membership.h>
#include <string.h>
#include <sys/acl.h>
#include <sys/stdio.h>
#include <unistd.h>

NSString *const FlycutAccountShareErrorDomain = @"FlycutAccountShareErrorDomain";

static const NSUInteger kPayloadLimit = 1048576;
static const NSUInteger kFilesPerSender = 10;
static const NSTimeInterval kMaxAge = 24 * 60 * 60;
static const NSTimeInterval kMaxFutureSkew = 5 * 60;
static const NSTimeInterval kStaleTemporaryAge = 5 * 60;
static const NSUInteger kMaxAppNameLength = 256;
static const NSInteger kPayloadVersion = 1;
static NSString *const kRTFType = @"public.rtf";
static NSString *const kHTMLType = @"public.html";

// One expected ACL entry: "allow <uid> <perms>" with inheritance flags, or
// (everyone set) "deny everyone <perms>".
typedef struct {
	uid_t uid;
	acl_perm_t perms;
	acl_flag_t flags;
	BOOL everyone;
} FCShareACE;

// The "everyone" group (gid 12), as chmod +a "everyone ..." and
// mbr_gid_to_uuid(12) write it: ABCDEFAB-CDEF-ABCD-EFAB-CDEF0000000C.
static const uuid_t kEveryoneUUID = { 0xAB, 0xCD, 0xEF, 0xAB, 0xCD, 0xEF, 0xAB, 0xCD,
	0xEF, 0xAB, 0xCD, 0xEF, 0x00, 0x00, 0x00, 0x0C };

static const acl_perm_t kAllPerms[] = {
	ACL_READ_DATA, ACL_WRITE_DATA, ACL_EXECUTE, ACL_DELETE, ACL_APPEND_DATA, ACL_DELETE_CHILD,
	ACL_READ_ATTRIBUTES, ACL_WRITE_ATTRIBUTES, ACL_READ_EXTATTRIBUTES, ACL_WRITE_EXTATTRIBUTES,
	ACL_READ_SECURITY, ACL_WRITE_SECURITY, ACL_CHANGE_OWNER, ACL_SYNCHRONIZE };
static const acl_flag_t kAllFlags[] = {
	ACL_ENTRY_INHERITED, ACL_ENTRY_FILE_INHERIT, ACL_ENTRY_DIRECTORY_INHERIT,
	ACL_ENTRY_LIMIT_INHERIT, ACL_ENTRY_ONLY_INHERIT };

// A sender only needs to reach its own folder through the inbox root.
static const acl_perm_t kTopSenderPerms = ACL_SEARCH;
// Nobody may rename or delete the inbox root itself, the owner included (it
// lifts the entry first): a node's own deny entry wins over the delete_child
// that the staff entry on /Users/Shared grants every standard account.
static const FCShareACE kTopDenyDelete = { 0, ACL_DELETE, 0, YES };
// In its folder a sender adds and prunes its own files and checks the folder's ACL.
static const acl_perm_t kFromSenderPerms = ACL_LIST_DIRECTORY | ACL_ADD_FILE | ACL_SEARCH |
	ACL_DELETE_CHILD | ACL_READ_ATTRIBUTES | ACL_READ_SECURITY;
// Every file a sender writes inherits read access for the recipient.
static const acl_perm_t kFromRecipientPerms = ACL_READ_DATA | ACL_READ_ATTRIBUTES |
	ACL_READ_EXTATTRIBUTES | ACL_READ_SECURITY;
static const acl_flag_t kFromRecipientFlags = ACL_ENTRY_FILE_INHERIT | ACL_ENTRY_ONLY_INHERIT;

static NSError *ShareError(NSInteger code)
{
	return [NSError errorWithDomain:FlycutAccountShareErrorDomain code:code userInfo:nil];
}

static BOOL Fail(NSError **error, NSInteger code)
{
	if ( error != NULL )
		*error = ShareError(code);
	return NO;
}

static NSString *InboxName(uid_t uid)
{
	return [NSString stringWithFormat:@".flycut-share-%u", uid];
}

static NSString *SenderFolderName(uid_t uid)
{
	return [NSString stringWithFormat:@"from-%u", uid];
}

static int OpenDirectoryAt(int dirFD, NSString *name)
{
	return openat(dirFD, [name UTF8String], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
}

// "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" in upper case, as NSUUID writes it.
static BOOL IsUUIDString(NSString *string)
{
	if ( [string length] != 36 )
		return NO;
	for ( NSUInteger i = 0; i < 36; i++ ) {
		unichar c = [string characterAtIndex:i];
		if ( i == 8 || i == 13 || i == 18 || i == 23 ) {
			if ( c != '-' )
				return NO;
		} else if ( !( ( c >= '0' && c <= '9' ) || ( c >= 'A' && c <= 'F' ) ) ) {
			return NO;
		}
	}
	return YES;
}

static BOOL HasUUIDName(NSString *name, NSString *extension)
{
	return [name hasSuffix:extension] && IsUUIDString([name substringToIndex:[name length] - [extension length]]);
}

static NSTimeInterval ModificationTime(const struct stat *st)
{
	return (NSTimeInterval)st->st_mtimespec.tv_sec + (NSTimeInterval)st->st_mtimespec.tv_nsec / 1e9;
}

// Names in a directory, without "." and "..". Reads through a separate
// descriptor so the caller's descriptor keeps its offset.
static NSArray *ListNames(int dirFD)
{
	int fd = openat(dirFD, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
	if ( fd < 0 )
		return nil;
	DIR *dir = fdopendir(fd);
	if ( dir == NULL ) {
		close(fd);
		return nil;
	}
	NSMutableArray *names = [NSMutableArray array];
	struct dirent *entry;
	while ( ( entry = readdir(dir) ) != NULL ) {
		if ( strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0 )
			continue;
		NSString *name = [NSString stringWithUTF8String:entry->d_name];
		if ( name != nil )
			[names addObject:name];
	}
	closedir(dir);
	return names;
}

// Removes one entry without following symlinks; directories are emptied up to
// `depth` levels below.
static BOOL RemoveEntry(int dirFD, NSString *name, int depth)
{
	const char *cname = [name UTF8String];
	if ( unlinkat(dirFD, cname, 0) == 0 || errno == ENOENT )
		return YES;
	int fd = OpenDirectoryAt(dirFD, name);
	if ( fd < 0 )
		return NO;
	if ( depth > 0 )
		for ( NSString *child in ListNames(fd) )
			RemoveEntry(fd, child, depth - 1);
	close(fd);
	return unlinkat(dirFD, cname, AT_REMOVEDIR) == 0 || errno == ENOENT;
}

static BOOL DirectoryIsEmpty(int dirFD)
{
	NSArray *names = ListNames(dirFD);
	return names != nil && [names count] == 0;
}

static acl_t BuildACL(const FCShareACE *entries, size_t count)
{
	acl_t acl = acl_init((int)count);
	if ( acl == NULL )
		return NULL;
	for ( size_t i = 0; i < count; i++ ) {
		acl_entry_t entry;
		uuid_t uu;
		acl_permset_t permset;
		acl_flagset_t flagset;
		if ( entries[i].everyone )
			memcpy(uu, kEveryoneUUID, sizeof uu);
		if ( acl_create_entry(&acl, &entry) != 0
			|| acl_set_tag_type(entry, entries[i].everyone ? ACL_EXTENDED_DENY : ACL_EXTENDED_ALLOW) != 0
			|| ( !entries[i].everyone && mbr_uid_to_uuid(entries[i].uid, uu) != 0 )
			|| acl_set_qualifier(entry, uu) != 0
			|| acl_get_permset(entry, &permset) != 0
			|| acl_clear_perms(permset) != 0
			|| acl_get_flagset_np(entry, &flagset) != 0
			|| acl_clear_flags_np(flagset) != 0 ) {
			acl_free(acl);
			return NULL;
		}
		for ( size_t p = 0; p < sizeof kAllPerms / sizeof kAllPerms[0]; p++ )
			if ( entries[i].perms & kAllPerms[p] )
				acl_add_perm(permset, kAllPerms[p]);
		for ( size_t f = 0; f < sizeof kAllFlags / sizeof kAllFlags[0]; f++ )
			if ( entries[i].flags & kAllFlags[f] )
				acl_add_flag_np(flagset, kAllFlags[f]);
		if ( acl_set_permset(entry, permset) != 0 || acl_set_flagset_np(entry, flagset) != 0 ) {
			acl_free(acl);
			return NULL;
		}
	}
	return acl;
}

static NSString *DescribeACE(BOOL everyone, uid_t uid, unsigned int perms, unsigned int flags)
{
	return everyone ? [NSString stringWithFormat:@"deny-everyone/%#x/%#x", perms, flags]
		: [NSString stringWithFormat:@"%u/%#x/%#x", uid, perms, flags];
}

// YES if the descriptor's extended ACL holds exactly these entries (in any
// order) and nothing else: allow entries for users, deny entries for everyone;
// no other deny, no group, no inherited entry.
static BOOL ACLMatches(int fd, const FCShareACE *entries, size_t count)
{
	NSMutableArray *expected = [NSMutableArray arrayWithCapacity:count];
	for ( size_t i = 0; i < count; i++ )
		[expected addObject:DescribeACE(entries[i].everyone, entries[i].uid, entries[i].perms, entries[i].flags)];
	acl_t acl = acl_get_fd_np(fd, ACL_TYPE_EXTENDED);
	if ( acl == NULL )
		return errno == ENOENT && count == 0;
	NSMutableArray *actual = [NSMutableArray array];
	BOOL ok = YES;
	acl_entry_t entry;
	for ( int which = ACL_FIRST_ENTRY; ok && acl_get_entry(acl, which, &entry) == 0; which = ACL_NEXT_ENTRY ) {
		acl_tag_t tag;
		acl_permset_t permset;
		acl_flagset_t flagset;
		if ( acl_get_tag_type(entry, &tag) != 0 || ( tag != ACL_EXTENDED_ALLOW && tag != ACL_EXTENDED_DENY )
			|| acl_get_permset(entry, &permset) != 0 || acl_get_flagset_np(entry, &flagset) != 0 ) {
			ok = NO;
			break;
		}
		uuid_t *uu = (uuid_t *)acl_get_qualifier(entry);
		id_t qualifier = 0;
		int idType = -1;
		BOOL everyone = tag == ACL_EXTENDED_DENY;
		if ( uu == NULL || ( everyone ? uuid_compare(*uu, kEveryoneUUID) != 0
							 : ( mbr_uuid_to_id(*uu, &qualifier, &idType) != 0 || idType != ID_TYPE_UID ) ) )
			ok = NO;
		if ( uu != NULL )
			acl_free(uu);
		unsigned int perms = 0, flags = 0;
		for ( size_t p = 0; p < sizeof kAllPerms / sizeof kAllPerms[0]; p++ )
			if ( acl_get_perm_np(permset, kAllPerms[p]) == 1 )
				perms |= kAllPerms[p];
		for ( size_t f = 0; f < sizeof kAllFlags / sizeof kAllFlags[0]; f++ )
			if ( acl_get_flag_np(flagset, kAllFlags[f]) == 1 )
				flags |= kAllFlags[f];
		[actual addObject:DescribeACE(everyone, (uid_t)qualifier, perms, flags)];
	}
	acl_free(acl);
	return ok && [[actual sortedArrayUsingSelector:@selector(compare:)]
				  isEqualToArray:[expected sortedArrayUsingSelector:@selector(compare:)]];
}

// Replaces the whole extended ACL, inherited entries included, and reads it back.
static BOOL SetExactACL(int fd, const FCShareACE *entries, size_t count)
{
	acl_t acl = BuildACL(entries, count);
	if ( acl == NULL )
		return NO;
	int rc = acl_set_fd_np(fd, acl, ACL_TYPE_EXTENDED);
	acl_free(acl);
	return rc == 0 && ACLMatches(fd, entries, count);
}

static BOOL ReadExactly(int fd, NSMutableData *data, size_t size)
{
	[data setLength:size];
	char *bytes = [data mutableBytes];
	size_t done = 0;
	while ( done < size ) {
		ssize_t n = read(fd, bytes + done, size - done);
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n <= 0 )
			return NO;
		done += (size_t)n;
	}
	char extra;
	ssize_t n;
	do {
		n = read(fd, &extra, 1);
	} while ( n < 0 && errno == EINTR );
	return n == 0;
}

static BOOL WriteAll(int fd, NSData *data)
{
	const char *bytes = [data bytes];
	size_t left = [data length];
	while ( left > 0 ) {
		ssize_t n = write(fd, bytes, left);
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n <= 0 )
			return NO;
		bytes += n;
		left -= (size_t)n;
	}
	return YES;
}

static BOOL IsNumber(id value)
{
	return [value isKindOfClass:[NSNumber class]] && CFGetTypeID((CFTypeRef)value) != CFBooleanGetTypeID();
}

@interface FlycutSharedClipping ()
-(instancetype)initWithSender:(uid_t)uid created:(NSTimeInterval)when text:(NSString *)string
					 richData:(NSDictionary *)rich appName:(NSString *)app;
@end

@implementation FlycutSharedClipping

@synthesize senderUID, created, text, richData, appName;

-(instancetype)initWithSender:(uid_t)uid created:(NSTimeInterval)when text:(NSString *)string
					 richData:(NSDictionary *)rich appName:(NSString *)app
{
	self = [super init];
	if ( self != nil ) {
		senderUID = uid;
		created = when;
		text = [string copy];
		richData = [rich copy];
		appName = [app copy];
	}
	return self;
}

-(void)dealloc
{
	[text release];
	[richData release];
	[appName release];
	[super dealloc];
}

@end

@implementation FlycutAccountShare

@synthesize sharedRoot, ownUID, filter, senderUIDs;

+(NSUInteger)payloadSizeLimit
{
	return kPayloadLimit;
}

+(NSUInteger)filesPerSenderLimit
{
	return kFilesPerSender;
}

-(instancetype)initWithSharedRoot:(NSString *)rootPath
						   ownUID:(uid_t)uid
					  ownerLookup:(FlycutAccountShareOwnerLookup)lookup
							clock:(FlycutAccountShareClock)now
{
	self = [super init];
	if ( self != nil ) {
		sharedRoot = [rootPath copy];
		ownUID = uid;
		ownerLookup = [( lookup != nil ? lookup : ^uid_t(const struct stat *st) { return st->st_uid; } ) copy];
		clock = [( now != nil ? now : ^NSTimeInterval { return [[NSDate date] timeIntervalSince1970]; } ) copy];
		senderUIDs = [[NSArray alloc] init];
	}
	return self;
}

-(void)dealloc
{
	[sharedRoot release];
	[ownerLookup release];
	[clock release];
	[filter release];
	[senderUIDs release];
	[super dealloc];
}

#pragma mark - Directories

-(int)openSharedRoot
{
	if ( [sharedRoot length] == 0 )
		return -1;
	return openat(AT_FDCWD, [sharedRoot fileSystemRepresentation], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
}

// The inbox root ACL for a list of senders: the deny entry first, then one
// search entry per sender; returns the entry count (capacity: senders + 1).
static size_t TopEntries(NSArray *senders, FCShareACE *entries, size_t capacity)
{
	size_t count = 0;
	if ( capacity > 0 )
		entries[count++] = kTopDenyDelete;
	for ( NSNumber *sender in senders )
		if ( count < capacity )
			entries[count++] = (FCShareACE){ (uid_t)[sender unsignedIntValue], kTopSenderPerms, 0, NO };
	return count;
}

static size_t FromEntries(uid_t recipient, uid_t sender, FCShareACE *entries)
{
	entries[0] = (FCShareACE){ sender, kFromSenderPerms, 0, NO };
	entries[1] = (FCShareACE){ recipient, kFromRecipientPerms, kFromRecipientFlags, NO };
	return 2;
}

// A directory is trusted if it is a real directory of `owner`, mode 0700, with
// exactly the expected ACL.
-(BOOL)directory:(int)fd isOwnedBy:(uid_t)owner withEntries:(const FCShareACE *)entries count:(size_t)count
{
	struct stat st;
	return fstat(fd, &st) == 0 && S_ISDIR(st.st_mode) && ownerLookup(&st) == owner
		&& ( st.st_mode & 07777 ) == 0700 && ACLMatches(fd, entries, count);
}

// Creates `name` in parentFD: a temporary directory first, its mode and ACL
// set and checked while nobody else can know it, then published with an
// exclusive rename. Returns the open directory or -1 (errno EEXIST if the name
// was taken meanwhile).
-(int)createDirectoryNamed:(NSString *)name in:(int)parentFD entries:(const FCShareACE *)entries count:(size_t)count
{
	NSString *temporary = [NSString stringWithFormat:@"%@.tmp-%@", name, [[NSUUID UUID] UUIDString]];
	const char *ctemporary = [temporary UTF8String];
	if ( mkdirat(parentFD, ctemporary, 0700) != 0 )
		return -1;
	int fd = OpenDirectoryAt(parentFD, temporary);
	struct stat st;
	BOOL ready = fd >= 0 && fstat(fd, &st) == 0 && S_ISDIR(st.st_mode) && ownerLookup(&st) == ownUID
		&& fchmod(fd, 0700) == 0 && SetExactACL(fd, entries, count) && DirectoryIsEmpty(fd)
		&& [self directory:fd isOwnedBy:ownUID withEntries:entries count:count];
	if ( !ready ) {
		if ( fd >= 0 )
			close(fd);
		RemoveEntry(parentFD, temporary, 1);
		errno = EACCES;
		return -1;
	}
	if ( renameatx_np(parentFD, ctemporary, parentFD, [name UTF8String], RENAME_EXCL) != 0 ) {
		int saved = errno;
		close(fd);
		RemoveEntry(parentFD, temporary, 0);
		errno = saved;
		return -1;
	}
	struct stat published;
	if ( fstatat(parentFD, [name UTF8String], &published, AT_SYMLINK_NOFOLLOW) != 0
		|| published.st_dev != st.st_dev || published.st_ino != st.st_ino ) {
		close(fd);
		errno = EACCES;
		return -1;
	}
	return fd;
}

// Normalizes a set of sender UIDs: numbers only, no duplicates, not this account.
-(NSArray *)normalizedSenders:(NSArray *)uids
{
	NSMutableSet *set = [NSMutableSet set];
	for ( id uid in uids ) {
		if ( !IsNumber(uid) )
			return nil;
		long long value = [uid longLongValue];
		if ( value <= 0 || value >= 0x7fffffff || (uid_t)value == ownUID )
			continue;
		[set addObject:[NSNumber numberWithUnsignedInt:(uid_t)value]];
	}
	return [[set allObjects] sortedArrayUsingSelector:@selector(compare:)];
}

-(BOOL)prepareInboxForSenders:(NSArray<NSNumber *> *)uids error:(NSError **)error
{
	NSArray *senders = [self normalizedSenders:uids];
	if ( senders == nil || [senders count] > 4096 )
		return Fail(error, FlycutAccountShareErrorInvalidArgument);
	size_t topCount = [senders count] + 1;
	FCShareACE *topEntries = calloc(topCount, sizeof(FCShareACE));
	if ( topEntries == NULL )
		return Fail(error, FlycutAccountShareErrorIO);
	topCount = TopEntries(senders, topEntries, topCount);
	BOOL ok = [self prepareWithSenders:senders topEntries:topEntries count:topCount error:error];
	free(topEntries);
	if ( ok ) {
		[senderUIDs release];
		senderUIDs = [senders copy];
	}
	return ok;
}

-(BOOL)prepareWithSenders:(NSArray *)senders topEntries:(const FCShareACE *)topEntries count:(size_t)topCount
					error:(NSError **)error
{
	int rootFD = [self openSharedRoot];
	if ( rootFD < 0 )
		return Fail(error, FlycutAccountShareErrorRootUnavailable);
	NSString *topName = InboxName(ownUID);
	int topFD = OpenDirectoryAt(rootFD, topName);
	if ( topFD < 0 && errno == ENOENT ) {
		// The deny-delete entry would also block the exclusive rename that
		// publishes the folder: it is made with the allow entries and gets the
		// whole ACL right below.
		topFD = [self createDirectoryNamed:topName in:rootFD entries:topEntries + 1 count:topCount - 1];
		if ( topFD < 0 && errno == EEXIST )
			topFD = OpenDirectoryAt(rootFD, topName);
	}
	if ( topFD < 0 ) {
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	// An existing inbox must be ours; a symlink, a file or another account's
	// directory at our name is never used or touched.
	struct stat st;
	if ( fstat(topFD, &st) != 0 || !S_ISDIR(st.st_mode) || ownerLookup(&st) != ownUID ) {
		close(topFD);
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	if ( ( st.st_mode & 07777 ) != 0700 && fchmod(topFD, 0700) != 0 ) {
		close(topFD);
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorIO);
	}
	if ( !ACLMatches(topFD, topEntries, topCount) && !SetExactACL(topFD, topEntries, topCount) ) {
		close(topFD);
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorIO);
	}
	if ( ![self directory:topFD isOwnedBy:ownUID withEntries:topEntries count:topCount] ) {
		close(topFD);
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	// Until the deny entry was on it, another account could still move the
	// folder away (its name is in a folder every account may change); from now
	// on nobody can. So it must still be the one under the name: else the moved
	// folder must not keep an entry that also binds its owner, and the setup
	// fails instead of building the inbox where nobody looks.
	struct stat named;
	BOOL inPlace = fstatat(rootFD, [topName UTF8String], &named, AT_SYMLINK_NOFOLLOW) == 0
		&& named.st_dev == st.st_dev && named.st_ino == st.st_ino;
	close(rootFD);
	if ( !inPlace ) {
		SetExactACL(topFD, NULL, 0);
		close(topFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	// Nothing but the chosen senders' folders may remain in the inbox.
	NSMutableSet *wanted = [NSMutableSet set];
	for ( NSNumber *sender in senders )
		[wanted addObject:SenderFolderName([sender unsignedIntValue])];
	BOOL ok = YES;
	for ( NSString *name in ListNames(topFD) )
		if ( ![wanted containsObject:name] && !RemoveEntry(topFD, name, 1) )
			ok = NO;
	for ( NSNumber *sender in senders ) {
		uid_t senderUID = [sender unsignedIntValue];
		NSString *name = SenderFolderName(senderUID);
		FCShareACE fromEntries[2];
		size_t fromCount = FromEntries(ownUID, senderUID, fromEntries);
		int fromFD = OpenDirectoryAt(topFD, name);
		if ( fromFD >= 0 && ![self directory:fromFD isOwnedBy:ownUID withEntries:fromEntries count:fromCount] ) {
			// Its content was written under an ACL we did not set: drop it unread.
			close(fromFD);
			fromFD = -1;
			if ( !RemoveEntry(topFD, name, 1) )
				ok = NO;
		} else if ( fromFD < 0 && errno != ENOENT ) {
			if ( !RemoveEntry(topFD, name, 1) )
				ok = NO;
		}
		if ( fromFD < 0 )
			fromFD = [self createDirectoryNamed:name in:topFD entries:fromEntries count:fromCount];
		if ( fromFD < 0 )
			ok = NO;
		else
			close(fromFD);
	}
	close(topFD);
	return ok ? YES : Fail(error, FlycutAccountShareErrorIO);
}

-(NSString *)inboxPath
{
	return [sharedRoot stringByAppendingPathComponent:InboxName(ownUID)];
}

-(NSString *)inboxFolderPathForSender:(uid_t)uid
{
	return [[self inboxPath] stringByAppendingPathComponent:SenderFolderName(uid)];
}

-(BOOL)wipeInbox:(NSError **)error
{
	int rootFD = [self openSharedRoot];
	if ( rootFD < 0 )
		return Fail(error, FlycutAccountShareErrorRootUnavailable);
	NSString *topName = InboxName(ownUID);
	int topFD = OpenDirectoryAt(rootFD, topName);
	if ( topFD < 0 ) {
		BOOL absent = errno == ENOENT;
		close(rootFD);
		return absent ? YES : Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	struct stat st;
	if ( fstat(topFD, &st) != 0 || !S_ISDIR(st.st_mode) || ownerLookup(&st) != ownUID ) {
		close(topFD);
		close(rootFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	// Close the door first: without the search entries no sender reaches a
	// folder; without the deny entry the folder can be removed.
	SetExactACL(topFD, NULL, 0);
	for ( NSString *name in ListNames(topFD) )
		RemoveEntry(topFD, name, 1);
	close(topFD);
	struct stat now;
	BOOL same = fstatat(rootFD, [topName UTF8String], &now, AT_SYMLINK_NOFOLLOW) == 0
		&& now.st_dev == st.st_dev && now.st_ino == st.st_ino;
	BOOL removed = same && unlinkat(rootFD, [topName UTF8String], AT_REMOVEDIR) == 0;
	close(rootFD);
	if ( removed ) {
		[senderUIDs release];
		senderUIDs = [[NSArray alloc] init];
	}
	return removed ? YES : Fail(error, FlycutAccountShareErrorIO);
}

#pragma mark - Pickup

// Parses one payload with a closed schema; nil if anything is off.
-(FlycutSharedClipping *)clippingFromPayload:(NSData *)data name:(NSString *)name sender:(uid_t)sender
{
	NSPropertyListFormat format = 0;
	id plist = [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable
														  format:&format error:NULL];
	if ( format != NSPropertyListBinaryFormat_v1_0 || ![plist isKindOfClass:[NSDictionary class]] )
		return nil;
	NSSet *allowed = [NSSet setWithObjects:@"v", @"id", @"created", @"text", @"rtf", @"html", @"app", nil];
	for ( id key in plist )
		if ( ![key isKindOfClass:[NSString class]] || ![allowed containsObject:key] )
			return nil;
	id version = [plist objectForKey:@"v"];
	id identifier = [plist objectForKey:@"id"];
	id created = [plist objectForKey:@"created"];
	id text = [plist objectForKey:@"text"];
	id rtf = [plist objectForKey:@"rtf"];
	id html = [plist objectForKey:@"html"];
	id app = [plist objectForKey:@"app"];
	if ( !IsNumber(version) || [version integerValue] != kPayloadVersion
		|| [version doubleValue] != (double)kPayloadVersion )
		return nil;
	if ( ![identifier isKindOfClass:[NSString class]]
		|| ![[identifier stringByAppendingString:@".clip"] isEqualToString:name] )
		return nil;
	NSTimeInterval now = clock();
	if ( !IsNumber(created) || [created doubleValue] < now - kMaxAge || [created doubleValue] > now + kMaxFutureSkew )
		return nil;
	if ( ![text isKindOfClass:[NSString class]] || [text length] == 0 )
		return nil;
	if ( ( rtf != nil && ( ![rtf isKindOfClass:[NSData class]] || [rtf length] == 0 ) )
		|| ( html != nil && ( ![html isKindOfClass:[NSData class]] || [html length] == 0 ) ) )
		return nil;
	if ( app != nil && ( ![app isKindOfClass:[NSString class]] || [app length] > kMaxAppNameLength ) )
		return nil;
	NSMutableDictionary *rich = nil;
	if ( rtf != nil || html != nil ) {
		rich = [NSMutableDictionary dictionaryWithCapacity:2];
		if ( rtf != nil )
			[rich setObject:rtf forKey:kRTFType];
		if ( html != nil )
			[rich setObject:html forKey:kHTMLType];
	}
	return [[[FlycutSharedClipping alloc] initWithSender:sender created:[created doubleValue] text:text
												richData:rich appName:app] autorelease];
}

// Opens a pickup candidate and checks it before any byte is read: a regular
// file of the folder's sender with one link, a size within the limit and a
// plausible time. Returns the open file or -1.
-(int)openCandidate:(NSString *)name in:(int)fromFD sender:(uid_t)sender now:(NSTimeInterval)now stat:(struct stat *)st
{
	// O_NONBLOCK: a FIFO must not block the pickup; it is rejected below.
	int fd = openat(fromFD, [name UTF8String], O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
	if ( fd < 0 )
		return -1;
	if ( fstat(fd, st) != 0 || !S_ISREG(st->st_mode) || ownerLookup(st) != sender || st->st_nlink != 1
		|| st->st_size <= 0 || (unsigned long long)st->st_size > kPayloadLimit
		|| ModificationTime(st) < now - kMaxAge || ModificationTime(st) > now + kMaxFutureSkew ) {
		close(fd);
		return -1;
	}
	return fd;
}

// Deletes `name` only if it is still the file that was checked.
static void UnlinkIfSame(int dirFD, NSString *name, ino_t inode)
{
	struct stat st;
	if ( fstatat(dirFD, [name UTF8String], &st, AT_SYMLINK_NOFOLLOW) == 0 && st.st_ino == inode )
		unlinkat(dirFD, [name UTF8String], 0);
}

-(void)collectFrom:(int)fromFD sender:(uid_t)sender into:(NSMutableArray *)results
{
	NSTimeInterval now = clock();
	NSMutableArray *candidates = [NSMutableArray array];
	NSMutableArray *rejected = [NSMutableArray array];
	// Check every entry before removing any, so a second name of a hard-linked
	// file is judged while the first one still exists.
	for ( NSString *name in ListNames(fromFD) ) {
		if ( HasUUIDName(name, @".tmp") ) {
			// A sender may be writing it right now; only stale ones go.
			struct stat st;
			if ( !( fstatat(fromFD, [name UTF8String], &st, AT_SYMLINK_NOFOLLOW) == 0 && S_ISREG(st.st_mode)
				   && ModificationTime(&st) >= now - kStaleTemporaryAge && ModificationTime(&st) <= now + kMaxFutureSkew ) )
				[rejected addObject:name];
			continue;
		}
		struct stat st;
		int fd = HasUUIDName(name, @".clip") ? [self openCandidate:name in:fromFD sender:sender now:now stat:&st] : -1;
		if ( fd < 0 ) {
			[rejected addObject:name];
			continue;
		}
		close(fd);
		[candidates addObject:@[[NSNumber numberWithDouble:ModificationTime(&st)], name,
								[NSNumber numberWithUnsignedLongLong:st.st_ino]]];
	}
	for ( NSString *name in rejected )
		RemoveEntry(fromFD, name, 0);
	// The newest files win; a sender that floods its folder loses the rest unread.
	[candidates sortUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
		NSComparisonResult byTime = [[b objectAtIndex:0] compare:[a objectAtIndex:0]];
		return byTime != NSOrderedSame ? byTime : [[b objectAtIndex:1] compare:[a objectAtIndex:1]];
	}];
	NSMutableArray *accepted = [NSMutableArray array];
	for ( NSUInteger i = 0; i < [candidates count]; i++ ) {
		NSString *name = [[candidates objectAtIndex:i] objectAtIndex:1];
		ino_t inode = (ino_t)[[[candidates objectAtIndex:i] objectAtIndex:2] unsignedLongLongValue];
		if ( i < kFilesPerSender ) {
			struct stat st;
			int fd = [self openCandidate:name in:fromFD sender:sender now:now stat:&st];
			if ( fd >= 0 ) {
				NSMutableData *data = [NSMutableData data];
				FlycutSharedClipping *clipping = nil;
				if ( st.st_ino == inode && ReadExactly(fd, data, (size_t)st.st_size) )
					clipping = [self clippingFromPayload:data name:name sender:sender];
				close(fd);
				if ( clipping != nil )
					[accepted insertObject:clipping atIndex:0];
			}
		}
		UnlinkIfSame(fromFD, name, inode);
	}
	[results addObjectsFromArray:accepted];
}

-(NSArray<FlycutSharedClipping *> *)collectClippings
{
	NSMutableArray *results = [NSMutableArray array];
	if ( [senderUIDs count] == 0 )
		return results;
	size_t topCount = [senderUIDs count] + 1;
	FCShareACE *topEntries = calloc(topCount, sizeof(FCShareACE));
	if ( topEntries == NULL )
		return results;
	topCount = TopEntries(senderUIDs, topEntries, topCount);
	int rootFD = [self openSharedRoot];
	int topFD = rootFD >= 0 ? OpenDirectoryAt(rootFD, InboxName(ownUID)) : -1;
	if ( rootFD >= 0 )
		close(rootFD);
	BOOL trusted = topFD >= 0 && [self directory:topFD isOwnedBy:ownUID withEntries:topEntries count:topCount];
	free(topEntries);
	if ( trusted ) {
		for ( NSNumber *sender in senderUIDs ) {
			uid_t senderUID = [sender unsignedIntValue];
			FCShareACE fromEntries[2];
			size_t fromCount = FromEntries(ownUID, senderUID, fromEntries);
			int fromFD = OpenDirectoryAt(topFD, SenderFolderName(senderUID));
			if ( fromFD < 0 )
				continue;
			if ( [self directory:fromFD isOwnedBy:ownUID withEntries:fromEntries count:fromCount] )
				[self collectFrom:fromFD sender:senderUID into:results];
			close(fromFD);
		}
	}
	if ( topFD >= 0 )
		close(topFD);
	return [results sortedArrayWithOptions:NSSortStable usingComparator:^NSComparisonResult(id a, id b) {
		NSTimeInterval ta = [(FlycutSharedClipping *)a created], tb = [(FlycutSharedClipping *)b created];
		return ta < tb ? NSOrderedAscending : ( ta > tb ? NSOrderedDescending : NSOrderedSame );
	}];
}

#pragma mark - Sending

-(BOOL)mayShareText:(NSString *)text ofType:(NSString *)type availableTypes:(NSArray *)availableTypes
{
	if ( [text length] == 0 || availableTypes == nil || filter == nil )
		return NO;
	for ( id availableType in availableTypes )
		if ( ![availableType isKindOfClass:[NSString class]] )
			return NO;
	return [filter mayShareClipping:text ofType:type fromAvailableTypes:availableTypes];
}

// Keeps the own files in the folder within the limits before one more is added.
-(void)pruneOwnFilesIn:(int)fromFD
{
	NSTimeInterval now = clock();
	NSMutableArray *kept = [NSMutableArray array];
	for ( NSString *name in ListNames(fromFD) ) {
		BOOL clip = HasUUIDName(name, @".clip");
		if ( !clip && !HasUUIDName(name, @".tmp") )
			continue;
		struct stat st;
		if ( fstatat(fromFD, [name UTF8String], &st, AT_SYMLINK_NOFOLLOW) != 0 || ownerLookup(&st) != ownUID )
			continue;
		NSTimeInterval age = now - ModificationTime(&st);
		if ( clip ? age > kMaxAge : age > kStaleTemporaryAge )
			unlinkat(fromFD, [name UTF8String], 0);
		else if ( clip )
			[kept addObject:@[[NSNumber numberWithDouble:ModificationTime(&st)], name]];
	}
	[kept sortUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
		NSComparisonResult byTime = [[a objectAtIndex:0] compare:[b objectAtIndex:0]];
		return byTime != NSOrderedSame ? byTime : [[a objectAtIndex:1] compare:[b objectAtIndex:1]];
	}];
	for ( NSUInteger i = 0; i + kFilesPerSender <= [kept count]; i++ )
		unlinkat(fromFD, [[[kept objectAtIndex:i] objectAtIndex:1] UTF8String], 0);
}

-(BOOL)sendText:(NSString *)text
		 ofType:(NSString *)type
 availableTypes:(NSArray<NSString *> *)availableTypes
	   richData:(NSDictionary *)richData
		appName:(NSString *)appName
	toRecipient:(uid_t)recipientUID
		  error:(NSError **)error
{
	if ( recipientUID == ownUID || recipientUID == 0 )
		return Fail(error, FlycutAccountShareErrorInvalidArgument);
	// Decide before touching the disk: a refused clipping leaves no trace.
	if ( ![self mayShareText:text ofType:type availableTypes:availableTypes] )
		return Fail(error, FlycutAccountShareErrorRefused);
	NSString *identifier = [[NSUUID UUID] UUIDString];
	NSTimeInterval created = clock();
	NSMutableDictionary *payload = [NSMutableDictionary dictionaryWithObjectsAndKeys:
		[NSNumber numberWithInteger:kPayloadVersion], @"v", identifier, @"id",
		[NSNumber numberWithDouble:created], @"created", text, @"text", nil];
	id rtf = [richData objectForKey:kRTFType], html = [richData objectForKey:kHTMLType];
	if ( [rtf isKindOfClass:[NSData class]] && [rtf length] > 0 )
		[payload setObject:rtf forKey:@"rtf"];
	if ( [html isKindOfClass:[NSData class]] && [html length] > 0 )
		[payload setObject:html forKey:@"html"];
	if ( [appName length] > 0 )
		[payload setObject:( [appName length] > kMaxAppNameLength ? [appName substringToIndex:kMaxAppNameLength] : appName )
					forKey:@"app"];
	NSData *data = [NSPropertyListSerialization dataWithPropertyList:payload format:NSPropertyListBinaryFormat_v1_0
															 options:0 error:NULL];
	if ( data == nil )
		return Fail(error, FlycutAccountShareErrorIO);
	if ( [data length] > kPayloadLimit )
		return Fail(error, FlycutAccountShareErrorTooLarge);

	int rootFD = [self openSharedRoot];
	if ( rootFD < 0 )
		return Fail(error, FlycutAccountShareErrorRootUnavailable);
	// The sender may only search the recipient's inbox root, not list it.
	int topFD = openat(rootFD, [InboxName(recipientUID) UTF8String], O_SEARCH | O_NOFOLLOW | O_CLOEXEC);
	int topErrno = errno;
	close(rootFD);
	if ( topFD < 0 )
		return Fail(error, topErrno == ENOENT ? FlycutAccountShareErrorNoInbox : FlycutAccountShareErrorUntrustedInbox);
	struct stat top;
	if ( fstat(topFD, &top) != 0 || !S_ISDIR(top.st_mode) || ownerLookup(&top) != recipientUID ) {
		close(topFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	int fromFD = OpenDirectoryAt(topFD, SenderFolderName(ownUID));
	int fromErrno = errno;
	close(topFD);
	if ( fromFD < 0 )
		return Fail(error, fromErrno == ENOENT ? FlycutAccountShareErrorNoInbox : FlycutAccountShareErrorUntrustedInbox);
	FCShareACE fromEntries[2];
	size_t fromCount = FromEntries(recipientUID, ownUID, fromEntries);
	struct stat parent;
	if ( ![self directory:fromFD isOwnedBy:recipientUID withEntries:fromEntries count:fromCount]
		|| fstatat(fromFD, "..", &parent, AT_SYMLINK_NOFOLLOW) != 0
		|| parent.st_dev != top.st_dev || parent.st_ino != top.st_ino ) {
		close(fromFD);
		return Fail(error, FlycutAccountShareErrorUntrustedInbox);
	}
	[self pruneOwnFilesIn:fromFD];

	NSString *temporary = [identifier stringByAppendingString:@".tmp"];
	NSString *final = [identifier stringByAppendingString:@".clip"];
	int fd = openat(fromFD, [temporary UTF8String], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if ( fd < 0 ) {
		close(fromFD);
		return Fail(error, FlycutAccountShareErrorIO);
	}
	struct timespec times[2];
	times[0].tv_sec = times[1].tv_sec = (time_t)created;
	times[0].tv_nsec = times[1].tv_nsec = (long)( ( created - (time_t)created ) * 1e9 );
	BOOL written = WriteAll(fd, data) && fsync(fd) == 0 && futimens(fd, times) == 0;
	close(fd);
	if ( !written || renameatx_np(fromFD, [temporary UTF8String], fromFD, [final UTF8String], RENAME_EXCL) != 0 ) {
		unlinkat(fromFD, [temporary UTF8String], 0);
		close(fromFD);
		return Fail(error, FlycutAccountShareErrorIO);
	}
	fsync(fromFD);
	close(fromFD);
	return YES;
}

@end
