//
//  FlycutAccountShareService.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// Runs FlycutAccountShare for the app: "Share copied text with other accounts on
// this Mac". While it runs, this account keeps an inbox for every other login
// account of the Mac, watches it and hands what arrives to its delegate; copies
// the delegate offers go to every other account that turned sharing on too (an
// account that did not has no inbox to write into).
//
// All file work runs on one private serial queue; the public methods and the
// delegate calls belong to the main thread. The engine, the list of accounts and
// the "is this session on the console?" check are injected, so tests can run
// several simulated accounts in one process.

#import <Foundation/Foundation.h>
#import "FlycutAccountShare.h"

@class FlycutAccountShareService;

@protocol FlycutAccountShareServiceDelegate <NSObject>
// Main thread: a clipping another account shared. Add it to the history.
-(void)accountShareService:(FlycutAccountShareService *)service didReceiveClipping:(FlycutSharedClipping *)clipping;
// Main thread: this session is on the console again (or Flycut started in it), and
// this is the newest clipping that arrived while it was not. Put it on the pasteboard.
-(void)accountShareService:(FlycutAccountShareService *)service shouldPutOnPasteboard:(FlycutSharedClipping *)clipping;
@end

// UIDs of the login accounts of this Mac (this one may be among them).
typedef NSArray<NSNumber *> *(^FlycutAccountShareAccountList)(void);
// YES while this account's session is on the console (in front).
typedef BOOL (^FlycutAccountShareSessionState)(void);

@interface FlycutAccountShareService : NSObject

// The app's shared root for the inboxes.
+(NSString *)sharedRootPath;
// The local login accounts: UID >= 501, enabled, not hidden, a login shell and a
// home folder directly in /Users (no Guest, service or system accounts).
+(NSArray<NSNumber *> *)localLoginAccountUIDs;
// The same rule applied to records @{uid, hidden, enabled, shell, home}.
+(NSArray<NSNumber *> *)loginAccountUIDsFromRecords:(NSArray<NSDictionary *> *)records;
// Whether the current session is on the console (CGSessionCopyCurrentDictionary).
+(BOOL)currentSessionIsOnConsole;

-(instancetype)initWithEngine:(FlycutAccountShare *)engine
					 accounts:(FlycutAccountShareAccountList)accounts
			  sessionIsActive:(FlycutAccountShareSessionState)sessionIsActive;

@property (nonatomic, readonly, retain) FlycutAccountShare *engine;
@property (nonatomic, assign) id<FlycutAccountShareServiceDelegate> delegate;
// YES between -start and -stop / -stopAndWipeInbox.
@property (nonatomic, readonly) BOOL running;
// Seconds between the safety pickups that also catch a missed folder event (60).
@property (nonatomic) NSTimeInterval safetyInterval;
// YES while "Diagnostics: save data type, not content" is on:
// nothing is taken in, copies wait in the inbox (the pickup limits and the
// 24-hour drop still apply). Turning it off takes in what waits. Main thread.
@property (nonatomic) BOOL pickupPaused;
// Whether each sender's folder is watched for changes (YES; tests turn it off to
// see the safety pickup alone).
@property (nonatomic) BOOL watchesSenderFolders;

// Sharing is on: prepares the inbox for every other account, excludes it from
// Time Machine, watches it and takes in what waits there.
-(void)start;
// Sharing is turned off: stops, deletes the inbox with everything in it and
// this account's copies that still wait in the other accounts' inboxes.
-(void)stopAndWipeInbox;
// Sharing is off at launch: deletes an inbox left over from an earlier run.
// A delete that fails, here or in -stopAndWipeInbox, is tried again every
// safetyInterval until it works or sharing is turned on again; the first
// failure after a launch is logged (NSLog), once.
-(void)wipeLeftoverInbox;
// Flycut quits: stops watching; the inbox stays for the next launch.
-(void)stop;

// A copy was added to the history. While running and on the console it is sent
// to every other account in the background; FlycutOperator (the engine's filter)
// decides whether it may leave the account at all.
-(void)offerText:(NSString *)text
		  ofType:(NSString *)type
  availableTypes:(NSArray<NSString *> *)availableTypes
		richData:(NSDictionary *)richData
		 appName:(NSString *)appName;

// The session came to the console: refresh the inbox, take in what waits and
// hand the newest clipping that came while away to the pasteboard. At -start
// (Flycut's launch) only a clipping copied less than 10 minutes ago goes there.
-(void)sessionDidBecomeActive;
// Takes in what waits now (also done by the folder watch and the safety timer).
-(void)pickUp;

// Tests: returns once the queue has done everything queued before the call.
-(void)waitForQueue;

@end
