//
//  FlycutAccountShare.h
//  Flycut
//
//  Flycut by Gennadiy Potapov and contributors. Based on Jumpcut by Steve Cook.
//  Copyright 2011 General Arcade. All rights reserved.
//
//  This code is open-source software subject to the MIT License; see the homepage
//  at <https://github.com/TermiT/Flycut> for details.
//

// Engine for sharing text clippings between the macOS accounts of one Mac.
//
// Transport: every receiving account R owns a hidden inbox directory in a shared
// root (in the app: /Users/Shared), ".flycut-share-<uid R>", and in it one folder
// per sending account S, "from-<uid S>". R creates both under a temporary name,
// replaces any inherited ACL with an exact one and publishes them with an
// exclusive rename:
//
//   .flycut-share-<R>/   owner R, mode 0700, ACL: per sender S "allow search"
//     from-<S>/          owner R, mode 0700, ACL: S may list, add files, search,
//                        delete entries, read attributes and the ACL; new files
//                        inherit "R may read"
//       <UUID>.clip      written by S (temporary name, then exclusive rename)
//
// The kernel records S as the owner of every file S writes, so R accepts a file
// in from-<S> only if S owns it. R deletes every entry it looked at, valid or not.
// No other account can enter R's inbox; an account R did not choose has no folder
// to write into. This class only moves data: it does not watch for changes, does
// not talk to the pasteboard and decides nothing about which accounts take part.
//
// The shared root, the own UID, the file-owner lookup and the clock are injected,
// so tests can simulate several accounts inside a scratch directory.

#import <Foundation/Foundation.h>
#include <sys/stat.h>
#include <sys/types.h>

extern NSString *const FlycutAccountShareErrorDomain;

typedef NS_ENUM(NSInteger, FlycutAccountShareErrorCode) {
	FlycutAccountShareErrorInvalidArgument = 1,
	// The shared root cannot be opened.
	FlycutAccountShareErrorRootUnavailable = 2,
	// The inbox exists but is not the recipient's (wrong owner, symlink, wrong
	// mode or ACL that could not be repaired). Nothing is read or written.
	FlycutAccountShareErrorUntrustedInbox = 3,
	// The recipient has no inbox for this sender (it did not opt in).
	FlycutAccountShareErrorNoInbox = 4,
	// The clipping must not leave the account (filter, no type list, empty).
	FlycutAccountShareErrorRefused = 5,
	FlycutAccountShareErrorTooLarge = 6,
	FlycutAccountShareErrorIO = 7,
};

// Returns the account that owns a file. The app uses st_uid; tests map inodes
// to simulated accounts.
typedef uid_t (^FlycutAccountShareOwnerLookup)(const struct stat *st);
// Seconds since 1970.
typedef NSTimeInterval (^FlycutAccountShareClock)(void);

// Whether a clipping may leave this account. FlycutOperator implements it
// (-mayShareClipping:ofType:fromAvailableTypes:): its password filters always
// on, plus a fixed list of types that are never shared.
@protocol FlycutAccountShareFilter <NSObject>
-(BOOL)mayShareClipping:(NSString *)contents ofType:(NSString *)type fromAvailableTypes:(NSArray<NSString *> *)availableTypes;
@end

// One clipping received from another account.
@interface FlycutSharedClipping : NSObject {
	uid_t senderUID;
	NSTimeInterval created;
	NSString *text;
	NSDictionary *richData;
	NSString *appName;
}
@property (nonatomic, readonly) uid_t senderUID;
// When the sender shared it, seconds since 1970 (sender's clock).
@property (nonatomic, readonly) NSTimeInterval created;
@property (nonatomic, readonly, copy) NSString *text;
// "public.rtf" and/or "public.html" -> NSData, in the format of
// -[FlycutOperator addClipping:ofType:withRichData:...]; nil if none.
@property (nonatomic, readonly, copy) NSDictionary *richData;
// The sender's localized app name, or nil.
@property (nonatomic, readonly, copy) NSString *appName;
@end

@interface FlycutAccountShare : NSObject {
	NSString *sharedRoot;
	uid_t ownUID;
	FlycutAccountShareOwnerLookup ownerLookup;
	FlycutAccountShareClock clock;
	id<FlycutAccountShareFilter> filter;
	NSArray *senderUIDs;
}

// Largest payload file, in bytes (1 MiB).
+(NSUInteger)payloadSizeLimit;
// Most files one sender may have waiting in one inbox; pickup also accepts at
// most this many per sender and pass (the newest) and deletes the rest unread.
+(NSUInteger)filesPerSenderLimit;

// rootPath: the directory that holds every account's inbox (/Users/Shared).
// lookup and now may be nil (st_uid, the system clock).
-(instancetype)initWithSharedRoot:(NSString *)rootPath
						   ownUID:(uid_t)uid
					  ownerLookup:(FlycutAccountShareOwnerLookup)lookup
							clock:(FlycutAccountShareClock)now;

@property (nonatomic, readonly, copy) NSString *sharedRoot;
@property (nonatomic, readonly) uid_t ownUID;
// Required for sending; without it nothing is shared.
@property (nonatomic, retain) id<FlycutAccountShareFilter> filter;
// The senders of the last successful -prepareInboxForSenders:error:.
@property (nonatomic, readonly, copy) NSArray<NSNumber *> *senderUIDs;

// Recipient: creates or verifies the own inbox with one folder per sender and
// repairs it if needed (an untrusted folder is emptied unread and recreated;
// entries for other accounts are removed). Refuses an inbox name that is a
// symlink or belongs to another account.
-(BOOL)prepareInboxForSenders:(NSArray<NSNumber *> *)uids error:(NSError **)error;

// Recipient: takes every waiting clipping out of the folders of the senders of
// the last prepare, oldest first, and deletes the files. Folders and files that
// fail a check are not read.
-(NSArray<FlycutSharedClipping *> *)collectClippings;

// Recipient: deletes the own inbox and everything in it (sharing turned off).
// Succeeds if there is none; refuses one that belongs to another account.
-(BOOL)wipeInbox:(NSError **)error;

// Sender: writes one clipping into the recipient's folder for this account.
// availableTypes is the pasteboard's type list of the copy; the clipping is
// refused if it is missing or if the filter refuses the clipping. Only
// "public.rtf" and "public.html" of richData are sent.
-(BOOL)sendText:(NSString *)text
		 ofType:(NSString *)type
 availableTypes:(NSArray<NSString *> *)availableTypes
	   richData:(NSDictionary *)richData
		appName:(NSString *)appName
	toRecipient:(uid_t)recipientUID
		  error:(NSError **)error;

@end
