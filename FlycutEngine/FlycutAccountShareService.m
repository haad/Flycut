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
#include <pwd.h>
#include <unistd.h>

static const NSTimeInterval kDefaultSafetyInterval = 60.0;

@implementation FlycutAccountShareService {
	// Main thread.
	FlycutAccountShare *engine;
	FlycutAccountShareAccountList accountList;
	FlycutAccountShareSessionState sessionState;
	BOOL running;
	NSUInteger generation;
	FlycutSharedClipping *pendingPasteboardClipping;
	// The queue's own state, touched only on the queue.
	dispatch_queue_t queue;
	BOOL queueRunning;
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
}

@synthesize engine, delegate, running, safetyInterval, watchesSenderFolders;

+(NSString *)sharedRootPath
{
	return @"/Users/Shared";
}

+(NSArray<NSNumber *> *)loginAccountUIDsFromRecords:(NSArray<NSDictionary *> *)records
{
	NSSet *noLogin = [NSSet setWithObjects:@"", @"/usr/bin/false", @"/bin/false", @"/sbin/nologin",
					  @"/usr/sbin/nologin", nil];
	NSMutableSet *uids = [NSMutableSet set];
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
		[uids addObject:[NSNumber numberWithLongLong:value]];
	}
	return [[uids allObjects] sortedArrayUsingSelector:@selector(compare:)];
}

+(NSArray<NSNumber *> *)localLoginAccountUIDs
{
	NSMutableArray *records = [NSMutableArray array];
	CSIdentityQueryRef query = CSIdentityQueryCreate(kCFAllocatorDefault, kCSIdentityClassUser, CSGetLocalIdentityAuthority());
	if ( query == NULL )
		return @[];
	if ( CSIdentityQueryExecute(query, kCSIdentityQueryIncludeHiddenIdentities, NULL) ) {
		CFArrayRef identities = CSIdentityQueryCopyResults(query);
		for ( CFIndex i = 0; identities != NULL && i < CFArrayGetCount(identities); i++ ) {
			CSIdentityRef identity = (CSIdentityRef)CFArrayGetValueAtIndex(identities, i);
			uid_t uid = (uid_t)CSIdentityGetPosixID(identity);
			struct passwd entry, *found = NULL;
			char buffer[4096];
			if ( getpwuid_r(uid, &entry, buffer, sizeof buffer, &found) != 0 || found == NULL )
				continue;
			NSString *shell = found->pw_shell != NULL ? [NSString stringWithUTF8String:found->pw_shell] : nil;
			NSString *home = found->pw_dir != NULL ? [NSString stringWithUTF8String:found->pw_dir] : nil;
			[records addObject:@{@"uid": [NSNumber numberWithUnsignedInt:uid],
								 @"hidden": [NSNumber numberWithBool:CSIdentityIsHidden(identity)],
								 @"enabled": [NSNumber numberWithBool:CSIdentityIsEnabled(identity)],
								 @"shell": shell ?: @"", @"home": home ?: @""}];
		}
		if ( identities != NULL )
			CFRelease(identities);
	}
	CFRelease(query);
	return [self loginAccountUIDsFromRecords:records];
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
	[accountList release];
	[sessionState release];
	[engine release];
	[super dealloc];
}

-(BOOL)sessionIsActive
{
	return sessionState != nil && sessionState();
}

#pragma mark - Queue work

// The other accounts of this Mac, from the injected list.
-(NSArray *)otherAccountsOnQueue
{
	NSMutableArray *others = [NSMutableArray array];
	for ( id uid in ( accountList != nil ? accountList() : @[] ) )
		if ( [uid isKindOfClass:[NSNumber class]] && [uid unsignedIntValue] != [engine ownUID]
			&& ![others containsObject:uid] )
			[others addObject:uid];
	return others;
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
		[self collectOnQueueAway:NO];
	});
	dispatch_source_set_cancel_handler(source, ^{ close(fd); });
	[folderWatches addObject:source];
	dispatch_release(source);
	dispatch_resume(source);
}

// Prepares (or repairs) the inbox for the other accounts, keeps it out of Time
// Machine backups and watches every sender's folder.
-(void)refreshInboxOnQueue
{
	needsRefresh = NO;
	NSArray *others = [self otherAccountsOnQueue];
	[recipients release];
	recipients = [others copy];
	for ( dispatch_source_t source in folderWatches )
		dispatch_source_cancel(source);
	[folderWatches removeAllObjects];
	if ( ![engine prepareInboxForSenders:others error:NULL] ) {
		needsRefresh = YES;
		return;
	}
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
		if ( needsRefresh )
			[self refreshInboxOnQueue];
		[self collectOnQueueAway:NO];
	});
	dispatch_resume(safetyTimer);
}

// Takes in what waits and hands it to the main thread. away: the clippings
// arrived while this session was not on the console (launch, coming back).
-(void)collectOnQueueAway:(BOOL)away
{
	if ( !queueRunning )
		return;
	NSArray *clippings = [[engine collectClippings] retain];
	NSUInteger forGeneration = queueGeneration;
	dispatch_async(dispatch_get_main_queue(), ^{
		[self deliver:clippings away:away generation:forGeneration];
		[clippings release];
	});
}

#pragma mark - Main thread

-(void)deliver:(NSArray *)clippings away:(BOOL)away generation:(NSUInteger)forGeneration
{
	if ( !running || forGeneration != generation )
		return;
	for ( FlycutSharedClipping *clipping in clippings )
		[delegate accountShareService:self didReceiveClipping:clipping];
	BOOL active = [self sessionIsActive];
	if ( [clippings count] > 0 && ( away || !active ) ) {
		[pendingPasteboardClipping release];
		pendingPasteboardClipping = [[clippings lastObject] retain];
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
		[self stopWatchingOnQueue];
		[self refreshInboxOnQueue];
		[self startSafetyTimerOnQueue:interval];
		[self collectOnQueueAway:YES];
	});
}

-(void)stopRunning
{
	running = NO;
	generation++;
	[pendingPasteboardClipping release];
	pendingPasteboardClipping = nil;
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
		[self wipeInboxOnQueueRetryingEvery:interval];
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
		[self collectOnQueueAway:YES];
	});
}

-(void)pickUp
{
	if ( !running )
		return;
	dispatch_async(queue, ^{
		[self collectOnQueueAway:NO];
	});
}

-(void)waitForQueue
{
	dispatch_sync(queue, ^{ });
}

@end
