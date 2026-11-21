//
//  FlycutAccountShareService.m
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

#import "FlycutAccountShareService.h"
#import <CoreGraphics/CoreGraphics.h>
#import <CoreServices/CoreServices.h>
#include <fcntl.h>
#include <membership.h>
#include <pwd.h>
#include <unistd.h>

static const NSTimeInterval kDefaultSafetyInterval = 60.0;
// After a failed inbox setup the safety timer retries after 1, 2, 4 ... ticks,
// at most this many (30 minutes at the default interval).
static const NSUInteger kMaxRetryTicks = 30;
// At launch a waiting copy replaces the pasteboard only if it is younger.
static const NSTimeInterval kLaunchPasteboardAge = 10 * 60;
// getpwuid_r's buffer: the usual size first (_SC_GETPW_R_SIZE_MAX), doubled
// for a larger record (ERANGE) up to this bound.
static const size_t kPasswdBufferSize = 4096;
static const size_t kMaxPasswdBufferSize = 1024 * 1024;

// How a pickup came about; decides what may go to the pasteboard.
typedef NS_ENUM(NSInteger, FCShareArrival) {
	// Folder watch, safety timer, -pickUp: only while not on the console.
	FCShareArrivalLive,
	// The session came back to the console: everything that arrived meanwhile.
	FCShareArrivalAway,
	// -start (launch): what waited, if copied less than kLaunchPasteboardAge ago.
	FCShareArrivalLaunch,
};

@implementation FlycutAccountShareService {
	// Main thread.
	FlycutAccountShare *engine;
	FlycutAccountShareAccountList accountList;
	FlycutAccountShareSessionState sessionState;
	BOOL running;
	BOOL pickupPaused;
	NSArray *sendAccountUIDs;
	NSArray *receiveAccountUIDs;
	NSUInteger generation;
	FlycutSharedClipping *pendingPasteboardClipping;
	NSInteger inboxErrorCode;
	// The queue's own state, touched only on the queue.
	dispatch_queue_t queue;
	BOOL queueRunning;
	BOOL queuePickupPaused;
	NSArray *queueSend;
	NSArray *queueReceive;
	NSUInteger queueGeneration;
	NSArray *recipients;
	NSMutableArray *folderWatches;
	dispatch_source_t safetyTimer;
	BOOL needsRefresh;
	// A failed delete of the inbox (sharing off) waits to be tried again.
	BOOL wipePending;
	BOOL wipeRetryScheduled;
	NSTimeInterval wipeRetryInterval;
	BOOL loggedWipeFailure;
	NSUInteger refreshFailures;
	NSUInteger ticksUntilRetry;
	NSInteger loggedErrorCode;
}

@synthesize engine, delegate, running, pickupPaused, sendAccountUIDs, receiveAccountUIDs, safetyInterval, watchesSenderFolders,
	inboxErrorCode, logHandler;

+(NSString *)sharedRootPath
{
	return @"/Users/Shared";
}

+(NSArray<NSNumber *> *)loginAccountUIDsFromRecords:(NSArray<NSDictionary *> *)records
{
	NSMutableArray *uids = [NSMutableArray array];
	for ( NSDictionary *account in [self loginAccountsFromRecords:records] )
		[uids addObject:[account objectForKey:@"uid"]];
	return [uids sortedArrayUsingSelector:@selector(compare:)];
}

+(NSArray<NSDictionary *> *)loginAccountsFromRecords:(NSArray<NSDictionary *> *)records
{
	NSSet *noLogin = [NSSet setWithObjects:@"", @"/usr/bin/false", @"/bin/false", @"/sbin/nologin",
					  @"/usr/sbin/nologin", nil];
	NSMutableSet *uids = [NSMutableSet set];
	NSMutableArray *accounts = [NSMutableArray array];
	for ( NSDictionary *record in records ) {
		id uid = [record objectForKey:@"uid"], shell = [record objectForKey:@"shell"], home = [record objectForKey:@"home"];
		if ( ![uid isKindOfClass:[NSNumber class]] || ![shell isKindOfClass:[NSString class]]
			|| ![home isKindOfClass:[NSString class]] )
			continue;
		long long value = [uid longLongValue];
		// Below 501: system and service accounts and Guest (201).
		if ( value < 501 || value >= 0x7fffffff )
			continue;
		if ( [[record objectForKey:@"hidden"] boolValue] || ![[record objectForKey:@"enabled"] boolValue] )
			continue;
		if ( [noLogin containsObject:shell] )
			continue;
		if ( ![[home stringByDeletingLastPathComponent] isEqualToString:@"/Users"] || [home isEqualToString:@"/Users/Shared"] )
			continue;
		NSNumber *number = [NSNumber numberWithLongLong:value];
		if ( [uids containsObject:number] )
			continue;
		[uids addObject:number];
		id name = [record objectForKey:@"name"], guid = [record objectForKey:@"guid"];
		NSMutableDictionary *account = [NSMutableDictionary dictionaryWithObjectsAndKeys:number, @"uid",
			[name isKindOfClass:[NSString class]] ? name : @"", @"name", nil];
		if ( [guid isKindOfClass:[NSString class]] && [guid length] > 0 )
			[account setObject:guid forKey:@"guid"];
		[accounts addObject:account];
	}
	[accounts sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
		NSComparisonResult byName = [[a objectForKey:@"name"] localizedStandardCompare:[b objectForKey:@"name"]];
		return byName != NSOrderedSame ? byName : [[a objectForKey:@"uid"] compare:[b objectForKey:@"uid"]];
	}];
	return accounts;
}

+(NSArray<NSNumber *> *)localLoginAccountUIDs
{
	NSArray *accounts = [self localLoginAccounts];
	if ( accounts == nil )
		return nil;
	NSMutableArray *uids = [NSMutableArray array];
	for ( NSDictionary *account in accounts )
		[uids addObject:[account objectForKey:@"uid"]];
	return [uids sortedArrayUsingSelector:@selector(compare:)];
}

// getpwuid_r with a buffer that grows on ERANGE (a record larger than the
// usual 4 KB, say a very long full name) up to kMaxPasswdBufferSize: 0, or
// the error that fails the lookup. *buffer and *size carry the buffer from
// one account to the next (both 0 at first).
static int LookUpPasswd(uid_t uid, struct passwd *entry, char **buffer, size_t *size, struct passwd **found)
{
	*found = NULL;
	for ( size_t want = *size > 0 ? *size : kPasswdBufferSize; ; want *= 2 ) {
		if ( want > *size ) {
			char *larger = realloc(*buffer, want);
			if ( larger == NULL )
				return ENOMEM;
			*buffer = larger;
			*size = want;
		}
		int error = getpwuid_r(uid, entry, *buffer, *size, found);
		if ( error != ERANGE || *size >= kMaxPasswdBufferSize )
			return error;
	}
}

// A failed account lookup is logged once per launch, with a fixed reason and
// no account name; later failures, of any kind, are not.
static void LogLookupFailure(NSString *reason)
{
	static dispatch_once_t once;
	dispatch_once(&once, ^{
		NSLog(@"Flycut: the accounts on this Mac cannot be read for sharing (%@)", reason);
	});
}

// nil (not an empty list) when the local directory cannot be asked or a login
// account's GeneratedUID cannot be read: a failed lookup must change nothing.
+(NSArray<NSDictionary *> *)localLoginAccounts
{
	NSMutableArray *records = [NSMutableArray array];
	CSIdentityQueryRef query = CSIdentityQueryCreate(kCFAllocatorDefault, kCSIdentityClassUser, CSGetLocalIdentityAuthority());
	if ( query == NULL ) {
		LogLookupFailure(@"the directory cannot be asked");
		return nil;
	}
	BOOL executed = CSIdentityQueryExecute(query, kCSIdentityQueryIncludeHiddenIdentities, NULL);
	BOOL failed = NO;
	NSString *failure = nil;
	char *buffer = NULL;
	size_t bufferSize = 0;
	if ( executed ) {
		CFArrayRef identities = CSIdentityQueryCopyResults(query);
		for ( CFIndex i = 0; identities != NULL && i < CFArrayGetCount(identities); i++ ) {
			CSIdentityRef identity = (CSIdentityRef)CFArrayGetValueAtIndex(identities, i);
			uid_t uid = (uid_t)CSIdentityGetPosixID(identity);
			struct passwd entry, *found = NULL;
			// An error (the directory cannot be asked, a record over 1 MB) fails the
			// whole lookup; a UID without an entry only leaves that account out.
			int error = LookUpPasswd(uid, &entry, &buffer, &bufferSize, &found);
			if ( error != 0 ) {
				failure = [NSString stringWithFormat:@"passwd lookup error %d", error];
				failed = YES;
				break;
			}
			if ( found == NULL )
				continue;
			NSString *shell = found->pw_shell != NULL ? [NSString stringWithUTF8String:found->pw_shell] : nil;
			NSString *home = found->pw_dir != NULL ? [NSString stringWithUTF8String:found->pw_dir] : nil;
			NSString *name = (NSString *)CSIdentityGetFullName(identity);
			if ( [name length] == 0 )
				name = (NSString *)CSIdentityGetPosixName(identity);
			// The account's GeneratedUID (the ACL entries name it too); asked only
			// for an account that exists, as mbr_uid_to_uuid makes one up otherwise.
			uuid_t generated;
			uuid_string_t text;
			NSString *guid = @"";
			if ( mbr_uid_to_uuid(uid, generated) == 0 ) {
				uuid_unparse_upper(generated, text);
				guid = [NSString stringWithUTF8String:text];
			}
			[records addObject:@{@"uid": [NSNumber numberWithUnsignedInt:uid],
								 @"hidden": [NSNumber numberWithBool:CSIdentityIsHidden(identity)],
								 @"enabled": [NSNumber numberWithBool:CSIdentityIsEnabled(identity)],
								 @"shell": shell ?: @"", @"home": home ?: @"", @"name": name ?: @"", @"guid": guid}];
		}
		if ( identities != NULL )
			CFRelease(identities);
	}
	CFRelease(query);
	free(buffer);
	if ( !executed || failed ) {
		LogLookupFailure(failure ?: @"the directory query fails");
		return nil;
	}
	NSArray *accounts = [self loginAccountsFromRecords:records];
	for ( NSDictionary *account in accounts )
		if ( [[account objectForKey:@"guid"] length] == 0 ) {
			LogLookupFailure(@"an account's GeneratedUID cannot be read");
			return nil;
		}
	return accounts;
}

+(BOOL)currentSessionIsOnConsole
{
	CFDictionaryRef session = CGSessionCopyCurrentDictionary();
	if ( session == NULL )
		return NO;
	CFTypeRef onConsole = CFDictionaryGetValue(session, kCGSessionOnConsoleKey);
	BOOL result = onConsole != NULL && CFGetTypeID(onConsole) == CFBooleanGetTypeID() && CFBooleanGetValue(onConsole);
	CFRelease(session);
	return result;
}

-(instancetype)initWithEngine:(FlycutAccountShare *)anEngine
					 accounts:(FlycutAccountShareAccountList)accounts
			  sessionIsActive:(FlycutAccountShareSessionState)sessionIsActive
{
	self = [super init];
	if ( self != nil ) {
		engine = [anEngine retain];
		accountList = [accounts copy];
		sessionState = [sessionIsActive copy];
		queue = dispatch_queue_create("com.Flycut.accountShare", DISPATCH_QUEUE_SERIAL);
		folderWatches = [[NSMutableArray alloc] init];
		safetyInterval = kDefaultSafetyInterval;
		watchesSenderFolders = YES;
	}
	return self;
}

// The folder watches and the safety timer hold the service, so it only goes away
// after -stop or -stopAndWipeInbox cancelled them; it may go on the queue itself.
-(void)dealloc
{
	dispatch_release(queue);
	[folderWatches release];
	[recipients release];
	[pendingPasteboardClipping release];
	[sendAccountUIDs release];
	[receiveAccountUIDs release];
	[queueSend release];
	[queueReceive release];
	[accountList release];
	[sessionState release];
	[logHandler release];
	[engine release];
	[super dealloc];
}

-(BOOL)sessionIsActive
{
	return sessionState != nil && sessionState();
}

#pragma mark - Queue work

// The other accounts of this Mac: the injected list without this one; nil if
// the lookup failed.
-(NSArray *)otherAccountsOnQueue
{
	NSArray *accounts = accountList != nil ? accountList() : @[];
	if ( ![accounts isKindOfClass:[NSArray class]] )
		return nil;   // the lookup failed
	NSMutableArray *others = [NSMutableArray array];
	for ( id uid in accounts )
		if ( [uid isKindOfClass:[NSNumber class]] && [uid unsignedIntValue] != [engine ownUID] && ![others containsObject:uid] )
			[others addObject:uid];
	return others;
}

// Those of the other accounts that a list names (nil: all of them).
static NSArray *ChosenAccounts(NSArray *others, NSArray *chosen)
{
	NSMutableArray *accounts = [NSMutableArray array];
	for ( NSNumber *uid in others )
		if ( chosen == nil || [chosen containsObject:uid] )
			[accounts addObject:uid];
	return accounts;
}

-(void)stopWatchingOnQueue
{
	for ( dispatch_source_t source in folderWatches )
		dispatch_source_cancel(source);
	[folderWatches removeAllObjects];
	if ( safetyTimer != NULL ) {
		dispatch_source_cancel(safetyTimer);
		dispatch_release(safetyTimer);
		safetyTimer = NULL;
	}
}

-(void)watchFolderOfSender:(uid_t)sender
{
	NSString *path = [engine inboxFolderPathForSender:sender];
	int fd = path != nil ? open([path fileSystemRepresentation], O_EVTONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) : -1;
	if ( fd < 0 ) {
		needsRefresh = YES;
		return;
	}
	dispatch_source_t source = dispatch_source_create(DISPATCH_SOURCE_TYPE_VNODE, (uintptr_t)fd,
		DISPATCH_VNODE_WRITE | DISPATCH_VNODE_DELETE | DISPATCH_VNODE_RENAME | DISPATCH_VNODE_REVOKE, queue);
	if ( source == NULL ) {
		close(fd);
		needsRefresh = YES;
		return;
	}
	dispatch_source_set_event_handler(source, ^{
		if ( dispatch_source_get_data(source) & ( DISPATCH_VNODE_DELETE | DISPATCH_VNODE_RENAME | DISPATCH_VNODE_REVOKE ) )
			needsRefresh = YES;
		[self collectOnQueue:FCShareArrivalLive];
	});
	dispatch_source_set_cancel_handler(source, ^{ close(fd); });
	[folderWatches addObject:source];
	dispatch_release(source);
	dispatch_resume(source);
}

// Short, fixed reasons for the log: no account name, no path.
static NSString *FailureReason(NSInteger code)
{
	switch ( code ) {
		case FlycutAccountShareErrorRootUnavailable:
			return @"the shared folder cannot be opened";
		case FlycutAccountShareErrorUntrustedInbox:
			return @"the inbox folder name is taken or cannot be created";
		default:
			return @"the inbox could not be set up";
	}
}

// The inbox setup failed (code) or worked (0): logged once per failure,
// published on the main thread, retried by the safety timer with growing pauses.
-(void)noteRefreshResultOnQueue:(NSInteger)code
{
	if ( code == 0 ) {
		refreshFailures = 0;
		ticksUntilRetry = 0;
		loggedErrorCode = 0;
	} else {
		refreshFailures++;
		NSUInteger pause = refreshFailures >= 6 ? kMaxRetryTicks : MIN((NSUInteger)1 << ( refreshFailures - 1 ), kMaxRetryTicks);
		ticksUntilRetry = pause - 1;
		if ( code != loggedErrorCode ) {
			loggedErrorCode = code;
			NSString *line = [NSString stringWithFormat:@"Flycut: sharing with other accounts is unavailable: %@ (error %ld)",
							  FailureReason(code), (long)code];
			if ( logHandler != nil )
				logHandler(line);
			else
				NSLog(@"%@", line);
		}
	}
	NSUInteger forGeneration = queueGeneration;
	dispatch_async(dispatch_get_main_queue(), ^{
		[self publishInboxErrorCode:code generation:forGeneration];
	});
}

-(void)publishInboxErrorCode:(NSInteger)code generation:(NSUInteger)forGeneration
{
	if ( ( code != 0 && ( !running || forGeneration != generation ) ) || code == inboxErrorCode )
		return;
	inboxErrorCode = code;
	if ( [delegate respondsToSelector:@selector(accountShareServiceDidChangeState:)] )
		[delegate accountShareServiceDidChangeState:self];
}

// While the account list cannot be read nothing is added, but what the lists
// no longer name goes: this account's copies waiting for an account it no
// longer sends to are withdrawn, and the folders of the accounts it no longer
// receives from are removed (with none left, the inbox). The safety timer
// tries the rest again.
-(void)applyRemovalsOnQueue
{
	NSMutableArray *kept = [NSMutableArray array];
	for ( NSNumber *previous in recipients ) {
		if ( queueSend == nil || [queueSend containsObject:previous] )
			[kept addObject:previous];
		else
			[engine withdrawFromRecipient:[previous unsignedIntValue] error:NULL];
	}
	[recipients release];
	recipients = [kept copy];
	if ( queueReceive == nil )
		return;
	NSArray *before = [engine senderUIDs];
	NSMutableArray *senders = [NSMutableArray array];
	for ( NSNumber *sender in before )
		if ( [queueReceive containsObject:sender] )
			[senders addObject:sender];
	if ( [senders count] == [before count] )
		return;
	for ( dispatch_source_t source in folderWatches )
		dispatch_source_cancel(source);
	[folderWatches removeAllObjects];
	if ( [senders count] == 0 ) {
		[engine wipeInbox:NULL];
		return;
	}
	[engine prepareInboxForSenders:senders error:NULL];
	if ( watchesSenderFolders )
		for ( NSNumber *sender in [engine senderUIDs] )
			[self watchFolderOfSender:[sender unsignedIntValue]];
}

// Notes the accounts this one sends to, prepares (or repairs) the inbox for the
// accounts it receives from, keeps it out of Time Machine backups and watches
// every sender's folder.
-(void)refreshInboxOnQueue
{
	needsRefresh = NO;
	NSArray *others = [self otherAccountsOnQueue];
	// The account list could not be read: nothing is added (no account is
	// sent to or received from anew), only what was unchecked goes, and the
	// safety timer tries again.
	if ( others == nil ) {
		needsRefresh = YES;
		[self applyRemovalsOnQueue];
		return;
	}
	NSArray *sendTo = ChosenAccounts(others, queueSend), *receiveFrom = ChosenAccounts(others, queueReceive);
	// An account no longer sent to loses this account's copies waiting for it.
	for ( NSNumber *previous in recipients )
		if ( ![sendTo containsObject:previous] )
			[engine withdrawFromRecipient:[previous unsignedIntValue] error:NULL];
	[recipients release];
	recipients = [sendTo copy];
	for ( dispatch_source_t source in folderWatches )
		dispatch_source_cancel(source);
	[folderWatches removeAllObjects];
	// Receiving from nobody: no inbox, it would only tell the others that this
	// account turned sharing on. An inbox that cannot be deleted now is
	// deleted at the next safety tick.
	if ( [receiveFrom count] == 0 ) {
		if ( ![engine wipeInbox:NULL] )
			needsRefresh = YES;
		[self noteRefreshResultOnQueue:0];
		return;
	}
	NSError *error = nil;
	if ( ![engine prepareInboxForSenders:receiveFrom error:&error] ) {
		needsRefresh = YES;
		[self noteRefreshResultOnQueue:[error code] != 0 ? [error code] : FlycutAccountShareErrorIO];
		return;
	}
	[self noteRefreshResultOnQueue:0];
	[[NSURL fileURLWithPath:[engine inboxPath] isDirectory:YES] setResourceValue:[NSNumber numberWithBool:YES]
																		  forKey:NSURLIsExcludedFromBackupKey error:NULL];
	if ( watchesSenderFolders )
		for ( NSNumber *sender in [engine senderUIDs] )
			[self watchFolderOfSender:[sender unsignedIntValue]];
}

-(void)startSafetyTimerOnQueue:(NSTimeInterval)interval
{
	safetyTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, queue);
	uint64_t nanoseconds = (uint64_t)( interval * NSEC_PER_SEC );
	dispatch_source_set_timer(safetyTimer, dispatch_time(DISPATCH_TIME_NOW, (int64_t)nanoseconds), nanoseconds, nanoseconds / 10);
	dispatch_source_set_event_handler(safetyTimer, ^{
		if ( needsRefresh && ticksUntilRetry > 0 )
			ticksUntilRetry--;
		else if ( needsRefresh )
			[self refreshInboxOnQueue];
		[self collectOnQueue:FCShareArrivalLive];
	});
	dispatch_resume(safetyTimer);
}

// Takes in what waits and hands it to the main thread. While pickup is paused
// only the inbox limits are applied and the files stay.
-(void)collectOnQueue:(FCShareArrival)arrival
{
	if ( !queueRunning )
		return;
	if ( queuePickupPaused ) {
		[engine pruneInbox];
		return;
	}
	NSArray *clippings = [[engine collectClippings] retain];
	NSUInteger forGeneration = queueGeneration;
	dispatch_async(dispatch_get_main_queue(), ^{
		[self deliver:clippings arrival:arrival generation:forGeneration];
		[clippings release];
	});
}

#pragma mark - Main thread

-(void)deliver:(NSArray *)clippings arrival:(FCShareArrival)arrival generation:(NSUInteger)forGeneration
{
	// Paused after the queue took them in: nothing may be added with content now.
	if ( !running || forGeneration != generation || pickupPaused )
		return;
	// Taken in just before its sender left the Receive list: not added.
	NSMutableArray *received = [NSMutableArray array];
	for ( FlycutSharedClipping *clipping in clippings )
		if ( receiveAccountUIDs == nil || [receiveAccountUIDs containsObject:[NSNumber numberWithUnsignedInt:[clipping senderUID]]] )
			[received addObject:clipping];
	for ( FlycutSharedClipping *clipping in received )
		[delegate accountShareService:self didReceiveClipping:clipping];
	BOOL active = [self sessionIsActive];
	FlycutSharedClipping *newest = [received lastObject];
	if ( arrival == FCShareArrivalLaunch && newest != nil && [engine currentTime] - [newest created] >= kLaunchPasteboardAge )
		newest = nil;
	if ( newest != nil && ( arrival != FCShareArrivalLive || !active ) ) {
		[pendingPasteboardClipping release];
		pendingPasteboardClipping = [newest retain];
	}
	if ( active && pendingPasteboardClipping != nil ) {
		FlycutSharedClipping *newest = [pendingPasteboardClipping autorelease];
		pendingPasteboardClipping = nil;
		[delegate accountShareService:self shouldPutOnPasteboard:newest];
	}
}

-(void)start
{
	if ( running )
		return;
	running = YES;
	generation++;
	NSUInteger forGeneration = generation;
	NSTimeInterval interval = safetyInterval > 0 ? safetyInterval : kDefaultSafetyInterval;
	dispatch_async(queue, ^{
		queueRunning = YES;
		queueGeneration = forGeneration;
		// Sharing runs again: its own setup keeps the inbox; a pending delete is dropped.
		wipePending = NO;
		refreshFailures = 0;
		ticksUntilRetry = 0;
		// A new start logs a failure that persists once more, as the note shows it again.
		loggedErrorCode = 0;
		[self stopWatchingOnQueue];
		[self refreshInboxOnQueue];
		[self startSafetyTimerOnQueue:interval];
		[self collectOnQueue:FCShareArrivalLaunch];
	});
}

-(void)stopRunning
{
	running = NO;
	generation++;
	[pendingPasteboardClipping release];
	pendingPasteboardClipping = nil;
	[self publishInboxErrorCode:0 generation:generation];
}

-(void)stop
{
	[self stopRunning];
	dispatch_async(queue, ^{
		queueRunning = NO;
		[self stopWatchingOnQueue];
	});
}

// Deletes the inbox while sharing is off. A delete that fails (a sender still
// writing through a folder it opened before, another account holding the name
// for a moment) is tried again every `interval` seconds until it works or
// sharing is turned on again (-start drops it).
-(void)wipeInboxOnQueueRetryingEvery:(NSTimeInterval)interval
{
	wipePending = YES;
	wipeRetryInterval = interval;
	[self retryPendingWipeOnQueue];
}

-(void)retryPendingWipeOnQueue
{
	if ( !wipePending )
		return;
	NSError *error = nil;
	if ( [engine wipeInbox:&error] ) {
		wipePending = NO;
		return;
	}
	// Logged once per launch, not at every try: a fixed reason and the error
	// code, no path.
	if ( !loggedWipeFailure ) {
		loggedWipeFailure = YES;
		NSLog(@"Flycut: the inbox for other accounts cannot be deleted yet (error %ld); Flycut tries again until it can", (long)[error code]);
	}
	if ( wipeRetryScheduled )
		return;
	wipeRetryScheduled = YES;
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)( wipeRetryInterval * NSEC_PER_SEC )), queue, ^{
		wipeRetryScheduled = NO;
		[self retryPendingWipeOnQueue];
	});
}

-(void)wipeLeftoverInbox
{
	if ( running )
		return;
	NSTimeInterval interval = safetyInterval > 0 ? safetyInterval : kDefaultSafetyInterval;
	dispatch_async(queue, ^{
		[self wipeInboxOnQueueRetryingEvery:interval];
	});
}

-(void)stopAndWipeInbox
{
	[self stopRunning];
	NSTimeInterval interval = safetyInterval > 0 ? safetyInterval : kDefaultSafetyInterval;
	dispatch_async(queue, ^{
		queueRunning = NO;
		[self stopWatchingOnQueue];
		// Own copies the others have not taken in yet go too.
		NSArray *others = [self otherAccountsOnQueue];
		NSMutableArray *withdraw = [NSMutableArray arrayWithArray:others != nil ? ChosenAccounts(others, queueSend) : @[]];
		for ( NSNumber *recipient in recipients )
			if ( ![withdraw containsObject:recipient] )
				[withdraw addObject:recipient];
		for ( NSNumber *recipient in withdraw )
			[engine withdrawFromRecipient:[recipient unsignedIntValue] error:NULL];
		[self wipeInboxOnQueueRetryingEvery:interval];
	});
}

// Both lists at once: the inbox is set up once, never from one new list and
// one old one.
-(void)setSendAccountUIDs:(NSArray<NSNumber *> *)send receiveAccountUIDs:(NSArray<NSNumber *> *)receive
{
	NSArray *sendTo = [[send copy] autorelease], *receiveFrom = [[receive copy] autorelease];
	if ( ( sendTo == sendAccountUIDs || [sendTo isEqual:sendAccountUIDs] )
		&& ( receiveFrom == receiveAccountUIDs || [receiveFrom isEqual:receiveAccountUIDs] ) )
		return;
	[sendAccountUIDs release];
	sendAccountUIDs = [sendTo retain];
	[receiveAccountUIDs release];
	receiveAccountUIDs = [receiveFrom retain];
	dispatch_async(queue, ^{
		[queueSend release];
		queueSend = [sendTo retain];
		[queueReceive release];
		queueReceive = [receiveFrom retain];
		if ( queueRunning )
			[self refreshInboxOnQueue];
	});
}

-(void)setPickupPaused:(BOOL)paused
{
	if ( paused == pickupPaused )
		return;
	pickupPaused = paused;
	dispatch_async(queue, ^{
		queuePickupPaused = paused;
		if ( !paused )
			[self collectOnQueue:FCShareArrivalLive];
	});
}

-(void)offerText:(NSString *)text
		  ofType:(NSString *)type
  availableTypes:(NSArray<NSString *> *)availableTypes
		richData:(NSDictionary *)richData
		 appName:(NSString *)appName
{
	if ( !running || ![self sessionIsActive] || [text length] == 0 )
		return;
	NSString *sentText = [[text copy] autorelease], *sentType = [[type copy] autorelease];
	NSArray *sentTypes = [[availableTypes copy] autorelease];
	NSDictionary *sentRich = [[richData copy] autorelease];
	NSString *sentApp = [[appName copy] autorelease];
	dispatch_async(queue, ^{
		if ( !queueRunning )
			return;
		for ( NSNumber *recipient in recipients )
			[engine sendText:sentText ofType:sentType availableTypes:sentTypes richData:sentRich appName:sentApp
				 toRecipient:[recipient unsignedIntValue] error:NULL];
	});
}

-(void)sessionDidBecomeActive
{
	if ( !running )
		return;
	dispatch_async(queue, ^{
		[self refreshInboxOnQueue];
		[self collectOnQueue:FCShareArrivalAway];
	});
}

-(void)pickUp
{
	if ( !running )
		return;
	dispatch_async(queue, ^{
		[self collectOnQueue:FCShareArrivalLive];
	});
}

-(void)waitForQueue
{
	dispatch_sync(queue, ^{ });
}

@end
