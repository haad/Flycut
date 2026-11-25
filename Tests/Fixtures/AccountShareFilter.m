// Native fixture for AccountShareFilterTests.py.
//
// Compiles the real FlycutOperator (with FlycutStore and FlycutClipping) and asks
// -mayShareClipping:ofType:fromAvailableTypes:, the decision whether a clipping
// may be shared with another account of this Mac, and -shouldSkip:..., the local
// capture decision, about the same copies under different local settings.
// NSUserDefaults is an in-memory fake that counts writes; the on-disk image store
// and the autosave path abort. No pasteboard, file, app or network is used.
// Clipping texts are dummy strings and are never printed.

#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <stdlib.h>

@interface FCFakeDefaults : NSObject {
    NSMutableDictionary *values;
    NSUInteger writes;
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
- (NSUInteger)writes;
- (NSDictionary *)snapshot;
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
- (id)objectForKey:(NSString *)key { return [values objectForKey:key]; }
- (id)valueForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSString *)stringForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSDictionary *)dictionaryForKey:(NSString *)key { return [values objectForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [[values objectForKey:key] integerValue]; }
- (BOOL)boolForKey:(NSString *)key { return [[values objectForKey:key] boolValue]; }
- (NSURL *)URLForKey:(NSString *)key { return nil; }
- (void)setObject:(id)value forKey:(NSString *)key {
    writes++;
    if (value) [values setObject:value forKey:key]; else [values removeObjectForKey:key];
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { [self setObject:@(value) forKey:key]; }
- (BOOL)synchronize { return YES; }
- (NSUInteger)writes { return writes; }
- (NSDictionary *)snapshot { return [[values copy] autorelease]; }
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

static int Check(BOOL ok, const char *what) {
    printf("%s: %s\n", ok ? "PASS" : "FAIL", what);
    return ok ? 0 : 1;
}

static NSArray *PlainTypes(void) { return @[@"public.utf8-plain-text"]; }
static NSArray *With(NSString *type) { return @[@"public.utf8-plain-text", @"public.rtf", type]; }

// A fresh operator on factory settings plus the given stored values.
static FCOperator *Operator(NSDictionary *stored) {
    static FCOperator *current = nil;
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    for (NSString *key in [[defaults snapshot] allKeys])
        [defaults setObject:nil forKey:key];
    [current release];
    current = [[FCOperator alloc] init];   // registers the factory values
    for (NSString *key in stored)
        [defaults setObject:[stored objectForKey:key] forKey:key];
    return current;
}

static BOOL MayShare(FlycutOperator *op, NSString *text, NSArray *types) {
    return [op mayShareClipping:text ofType:@"public.utf8-plain-text" fromAvailableTypes:types];
}

static BOOL Skips(FlycutOperator *op, NSString *text, NSArray *types) {
    return [op shouldSkip:text ofType:@"public.utf8-plain-text" fromAvailableTypes:types];
}

// Every local password switch off: what sharing must still refuse.
static NSDictionary *AllOff(void) {
    return @{@"skipPboardTypes": @NO, @"skipConcealedTypes": @NO,
             @"skipPasswordFields": @NO, @"skipPasswordLengths": @NO};
}

static NSDictionary *Merged(NSDictionary *a, NSDictionary *b) {
    NSMutableDictionary *merged = [[a mutableCopy] autorelease];
    [merged addEntriesFromDictionary:b];
    return merged;
}

static NSArray *FactoryTypes(void) {
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    Operator(@{});
    NSString *joined = [NSString stringWithFormat:@"%@,%@", [defaults stringForKey:@"skipPboardTypesList"],
                        [defaults stringForKey:@"skipConcealedTypesList"]];
    return [[joined stringByReplacingOccurrencesOfString:@" " withString:@""] componentsSeparatedByString:@","];
}

static int RunForcedTypes(void) {
    int f = 0;
    NSArray *factory = FactoryTypes();
    f += Check([factory count] == 5, "the factory type lists hold five types");
    BOOL refused = YES, keptLocally = YES;
    for (NSDictionary *stored in @[@{}, AllOff()]) {
        FlycutOperator *op = Operator(stored);
        for (NSString *type in factory) {
            if (MayShare(op, @"example-01 alpha", With(type))) refused = NO;
            if ([stored count] > 0 && Skips(op, @"example-01 alpha", With(type))) keptLocally = NO;
        }
    }
    f += Check(refused, "a copy with a factory password or concealed type is never shared, "
                        "with the local type filters on and off");
    f += Check(keptLocally, "with the local type filters off the same copies are still kept locally");
    FlycutOperator *op = Operator(@{@"skipPboardTypes": @NO, @"skipPboardTypesList": @"com.example.secret-type",
                                    @"skipConcealedTypes": @NO, @"skipConcealedTypesList": @"com.example.private-marker"});
    f += Check(!MayShare(op, @"example-02 beta", With(@"com.example.secret-type"))
               && !MayShare(op, @"example-02 beta", With(@"com.example.private-marker")),
               "a type the user added to a list is never shared, also with that filter off");
    f += Check(!Skips(op, @"example-02 beta", With(@"com.example.secret-type"))
               && !Skips(op, @"example-02 beta", With(@"com.example.private-marker")),
               "locally the switched-off filters still keep those copies");
    return f;
}

static int RunForcedLength(void) {
    int f = 0;
    NSArray *passwordLike = @[@"Ab3$efGh9!xY", @"Ab3$efGh9!xYz7#Kq2W%", @"Ab3$efGh9!xYz7#Kq2W%Mn5&pR8*sT1@"];
    f += Check([passwordLike[0] length] == 12 && [passwordLike[1] length] == 20 && [passwordLike[2] length] == 32,
               "the probes have the factory lengths 12, 20 and 32");
    BOOL refused = YES, keptLocally = YES;
    for (NSDictionary *stored in @[@{}, AllOff(), @{@"skipPasswordFields": @YES, @"skipPasswordLengths": @NO}]) {
        FlycutOperator *op = Operator(stored);
        for (NSString *text in passwordLike) {
            if (MayShare(op, text, PlainTypes())) refused = NO;
            if (Skips(op, text, PlainTypes())) keptLocally = NO;
        }
    }
    f += Check(refused, "a text that passes the length and character check is never shared, "
                        "also with the local check off (its factory setting)");
    f += Check(keptLocally, "locally the same texts are kept while the check is off");
    FlycutOperator *op = Operator(AllOff());
    f += Check(MayShare(op, @"abcdefghijkl", PlainTypes()) && MayShare(op, @"Ab3$efGh9!xYq", PlainTypes())
               && MayShare(op, @"Ab3 efGh9!xY", PlainTypes()),
               "texts of another length or without the character mix are shared");
    for (NSString *list in @[@"", @"16", @" "]) {
        op = Operator(@{@"skipPasswordLengths": @NO, @"skipPasswordLengthsList": list});
        if (MayShare(op, passwordLike[0], PlainTypes())) refused = NO;
    }
    f += Check(refused, "an emptied or changed length list does not drop the factory lengths for sharing");
    op = Operator(@{@"skipPasswordLengths": @NO, @"skipPasswordLengthsList": @"16"});
    f += Check(!MayShare(op, @"Ab3$efGh9!xYz7#K", PlainTypes()) && !Skips(op, @"Ab3$efGh9!xYz7#K", PlainTypes()),
               "a length the user added applies to sharing too, while the local check stays off");
    return f;
}

static int RunNeverSharedTypes(void) {
    int f = 0;
    NSArray *never = [FlycutOperator neverSharedTypes];
    NSArray *extra = @[@"de.petermaurer.TransientPasteboardType", @"com.typeit4me.clipping", @"Pasteboard generator type"];
    NSArray *factory = FactoryTypes();
    BOOL covered = [never count] == 8;
    for (NSString *type in [factory arrayByAddingObjectsFromArray:extra])
        if (![never containsObject:type]) covered = NO;
    f += Check(covered, "the never-share list is the factory type lists plus the other nspasteboard.org markers");
    BOOL refused = YES;
    NSArray *settings = @[@{}, AllOff(),
                          @{@"skipPboardTypesList": @"", @"skipConcealedTypesList": @""},
                          Merged(AllOff(), @{@"skipPboardTypesList": @"", @"skipConcealedTypesList": @""})];
    for (NSDictionary *stored in settings) {
        FlycutOperator *op = Operator(stored);
        for (NSString *type in never)
            if (MayShare(op, @"example-03 gamma", With(type))) refused = NO;
    }
    f += Check(refused, "never-share types are refused with the local filters on, off and with emptied lists");
    FlycutOperator *op = Operator(@{});
    BOOL keptLocally = YES;
    for (NSString *type in extra)
        if (Skips(op, @"example-03 gamma", With(type))) keptLocally = NO;
    f += Check(keptLocally, "the three extra markers do not change local capture");
    return f;
}

static int RunOrdinary(void) {
    int f = 0;
    FlycutOperator *op = Operator(@{});
    f += Check(MayShare(op, @"example-04 delta", PlainTypes()), "an ordinary plain text copy may be shared");
    f += Check(MayShare(op, @"example-04 delta", @[@"public.utf8-plain-text", @"public.rtf", @"public.html"]),
               "an ordinary rich text copy may be shared");
    f += Check(!MayShare(op, @"example-04 delta", nil), "a copy without a type list is not shared");
    f += Check(!MayShare(op, @"", PlainTypes()) && !MayShare(op, nil, PlainTypes()), "an empty copy is not shared");
    FCFakeDefaults *defaults = [FCFakeDefaults standardUserDefaults];
    op = Operator(AllOff());
    NSDictionary *before = [defaults snapshot];
    NSUInteger writes = [defaults writes];
    MayShare(op, @"Ab3$efGh9!xY", PlainTypes());
    MayShare(op, @"example-04 delta", With(@"org.nspasteboard.ConcealedType"));
    f += Check([defaults writes] == writes && [[defaults snapshot] isEqualToDictionary:before],
               "deciding about sharing never changes the stored settings");
    return f;
}

// A file copied in Finder gives its name as text too; neither the name nor the file is shared.
static int RunFileCopies(void) {
    int f = 0;
    FlycutOperator *op = Operator(@{});
    f += Check(!MayShare(op, @"example-06 zeta.txt", @[@"public.file-url", @"public.utf8-plain-text"]),
               "a file copied in Finder is not shared, not even its name");
    f += Check(!MayShare(op, @"example-06 zeta.txt", @[@"NSFilenamesPboardType", @"public.utf8-plain-text"]),
               "nor one listed the older way");
    op = Operator(AllOff());
    f += Check(!MayShare(op, @"example-06 zeta.txt", @[@"public.file-url", @"public.utf8-plain-text"]),
               "with the local filters off neither");
    f += Check(MayShare(op, @"example-06 zeta", @[@"public.utf8-plain-text", @"public.url"]),
               "a web address is no file and may be shared");
    return f;
}

static int RunLocalUnchanged(void) {
    int f = 0;
    FlycutOperator *op = Operator(@{});
    f += Check(Skips(op, @"example-05 epsilon", With(@"org.nspasteboard.ConcealedType"))
               && Skips(op, @"example-05 epsilon", With(@"PasswordPboardType"))
               && !Skips(op, @"Ab3$efGh9!xY", PlainTypes()) && !Skips(op, @"example-05 epsilon", PlainTypes()),
               "factory settings: types skipped, length check off, ordinary text kept");
    op = Operator(@{@"skipPasswordLengths": @YES});
    f += Check(Skips(op, @"Ab3$efGh9!xY", PlainTypes()), "the local length check still skips when it is on");
    op = Operator(@{@"skipPasswordFields": @NO, @"skipPasswordLengths": @YES});
    f += Check(!Skips(op, @"Ab3$efGh9!xY", PlainTypes()), "the local length check stays behind its master switch");
    return f;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 2) return 2;
        NSDictionary *modes = @{@"forced-types": [NSValue valueWithPointer:RunForcedTypes],
                                @"forced-length": [NSValue valueWithPointer:RunForcedLength],
                                @"never-shared-types": [NSValue valueWithPointer:RunNeverSharedTypes],
                                @"ordinary": [NSValue valueWithPointer:RunOrdinary],
                                @"file-copies": [NSValue valueWithPointer:RunFileCopies],
                                @"local-unchanged": [NSValue valueWithPointer:RunLocalUnchanged]};
        NSValue *run = [modes objectForKey:[NSString stringWithUTF8String:argv[1]]];
        if (run == nil) return 3;
        int failures = ((int (*)(void))[run pointerValue])();
        printf("RESULT failures=%d\n", failures);
        return failures == 0 ? 0 : 1;
    }
}
