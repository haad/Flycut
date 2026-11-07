// Native fixture for the bezel selection -> Escape -> delayed paste lifecycle.
// It links the real Flycut sources and drives the real AppController and
// FlycutOperator methods. Only OS boundaries are replaced:
//   CGEventPost                          input posting (records, never posts)
//   AXIsProcessTrustedWithOptions        TCC consent (injected, never queried)
//   TISCopyCurrentKeyboardLayoutInputSource  current layout (pinned to U.S.)
//   NSApp                                app hiding (records hide: calls)
//   the controller's pasteboard          NSPasteboard (in memory, never general)
//   +[NSUserDefaults standardUserDefaults]   preferences storage (in memory)
// Guards abort the run if a case reaches +[FlycutImageStore sharedStore] (its
// -init creates the real Application Support image folder) or the general pasteboard.
#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>
#import <ApplicationServices/ApplicationServices.h>
#import <objc/runtime.h>
#import <string.h>
#import "AppController.h"
#import "FlycutOperator.h"
#import "FlycutImageStore.h"

static int failures;
#define CHECK(condition, ...) do { if (!(condition)) { \
    fprintf(stderr, "FAIL: "); fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n"); \
    failures++; } } while (0)

// The definitions below replace the framework symbols at static link time.
typedef struct { CGKeyCode code; bool down; CGEventFlags flags; } PostedEvent;
static PostedEvent posted[16];
static int postCount, trustChecks, layoutCopies;

void CGEventPost(CGEventTapLocation tap, CGEventRef event) {
    CHECK(tap == kCGHIDEventTap, "event tap");
    if (event && postCount < 16) {
        posted[postCount] = (PostedEvent){
            (CGKeyCode)CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode),
            CGEventGetType(event) == kCGEventKeyDown, CGEventGetFlags(event)};
    }
    postCount++;
}

Boolean AXIsProcessTrustedWithOptions(CFDictionaryRef options) {
    trustChecks++;
    CHECK(options && CFDictionaryGetValue(options, kAXTrustedCheckOptionPrompt) == kCFBooleanFalse,
          "paste permission check must not prompt");
    return true; // Injected consent, not an observed TCC state.
}

TISInputSourceRef TISCopyCurrentKeyboardLayoutInputSource(void) {
    layoutCopies++;
    NSDictionary *filter = @{(id)kTISPropertyInputSourceID: @"com.apple.keylayout.US"};
    CFArrayRef list = TISCreateInputSourceList((CFDictionaryRef)filter, true);
    TISInputSourceRef source = NULL;
    if (list && CFArrayGetCount(list))
        source = (TISInputSourceRef)CFRetain(CFArrayGetValueAtIndex(list, 0));
    if (list) CFRelease(list);
    return source;
}

static int Pastes(void) {
    int pastes = 0;
    for (int index = 0; index < postCount && index < 16; index++)
        if (posted[index].down && (posted[index].flags & kCGEventFlagMaskCommand)) pastes++;
    return pastes;
}

@interface FCApplicationBoundary : NSObject { @public int hides; }
- (void)hide:(id)sender;
@end
@implementation FCApplicationBoundary
- (void)hide:(id)sender { (void)sender; hides++; }
@end

@interface FCPasteboardBoundary : NSObject { @public NSInteger changes; NSString *string; }
@end
@implementation FCPasteboardBoundary
- (NSInteger)declareTypes:(NSArray *)types owner:(id)owner { (void)types; (void)owner; return ++changes; }
- (BOOL)setString:(NSString *)value forType:(NSString *)type {
    (void)type;
    [string release];
    string = [value copy];
    return YES;
}
- (NSInteger)changeCount { return changes; }
- (void)dealloc { [string release]; [super dealloc]; }
@end

@interface FCMemoryDefaults : NSObject { NSMutableDictionary *values; }
@end
@implementation FCMemoryDefaults
- (id)init { if ((self = [super init])) values = [[NSMutableDictionary alloc] init]; return self; }
- (void)dealloc { [values release]; [super dealloc]; }
- (void)registerDefaults:(NSDictionary *)registration {
    for (id key in registration) if (!values[key]) values[key] = registration[key];
}
- (id)objectForKey:(NSString *)key { return values[key]; }
- (id)valueForKey:(NSString *)key { return values[key]; }
- (NSString *)stringForKey:(NSString *)key { return values[key]; }
- (NSInteger)integerForKey:(NSString *)key { return [values[key] integerValue]; }
- (BOOL)boolForKey:(NSString *)key { return [values[key] boolValue]; }
- (void)setObject:(id)value forKey:(NSString *)key {
    if (value) values[key] = value; else [values removeObjectForKey:key];
}
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (BOOL)synchronize { return YES; }
@end

static FCMemoryDefaults *memoryDefaults;
static id MemoryStandardDefaults(id object, SEL selector) { (void)object; (void)selector; return memoryDefaults; }
static id ForbiddenBoundary(id object, SEL selector) {
    fprintf(stderr, "FAIL: fixture reached +[%s %s], a real user data or pasteboard boundary\n",
            class_getName((Class)object), sel_getName(selector));
    fflush(stderr);
    abort();
}
static void InstallGuard(Class cls, SEL selector) {
    method_setImplementation(class_getClassMethod(cls, selector), (IMP)ForbiddenBoundary);
    CHECK(method_getImplementation(class_getClassMethod(cls, selector)) == (IMP)ForbiddenBoundary,
          "guard installed on +[%s %s]", class_getName(cls), sel_getName(selector));
}

// Only sets state the nib and -showBezel would set; no production method is overridden.
@interface FCBezelFixtureController : AppController
- (void)useOperator:(FlycutOperator *)anOperator pasteboard:(id)pasteboard;
- (void)setBezelDisplayed:(BOOL)displayed pinned:(BOOL)pinned;
- (BOOL)bezelDisplayed;
@end
@implementation FCBezelFixtureController
- (void)useOperator:(FlycutOperator *)anOperator pasteboard:(id)pasteboard {
    flycutOperator = anOperator;
    jcPasteboard = pasteboard;
}
- (void)setBezelDisplayed:(BOOL)displayed pinned:(BOOL)pinned {
    isBezelDisplayed = displayed;
    isBezelPinned = pinned;
}
- (BOOL)bezelDisplayed { return isBezelDisplayed; }
@end

static NSEvent *KeyDown(unsigned short keyCode, NSString *characters) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
                           timestamp:0 windowNumber:0 context:nil characters:characters
         charactersIgnoringModifiers:characters isARepeat:NO keyCode:keyCode];
}

static void RunPastDelays(void) {
    // -pasteFromStack queues -hideApp at 0.2 s and -fakeCommandV at 0.5 s.
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
}

typedef struct {
    FCBezelFixtureController *controller;
    FlycutOperator *flycutOperator;
    FCPasteboardBoundary *pasteboard;
    FCApplicationBoundary *application;
} Session;

static Session OpenVisibleBezel(void) {
    postCount = trustChecks = layoutCopies = 0;
    memset(posted, 0, sizeof(posted));
    Session session;
    session.application = [[FCApplicationBoundary alloc] init];
    NSApp = (id)session.application;
    session.pasteboard = [[FCPasteboardBoundary alloc] init];
    session.flycutOperator = [[FlycutOperator alloc] init];
    [session.flycutOperator awakeFromNibDisplaying:10 withDisplayLength:40
                                  withSaveSelector:@selector(class) forTarget:nil];
    [session.flycutOperator addClipping:@"older clip" ofType:NSPasteboardTypeString fromApp:nil
                       withAppBundleURL:nil target:nil clippingAddedSelector:@selector(class)];
    [session.flycutOperator addClipping:@"selected clip" ofType:NSPasteboardTypeString fromApp:nil
                       withAppBundleURL:nil target:nil clippingAddedSelector:@selector(class)];
    session.controller = [[FCBezelFixtureController alloc] init];
    [session.controller useOperator:session.flycutOperator pasteboard:session.pasteboard];
    [session.controller setBezelDisplayed:YES pinned:NO];
    return session;
}

static void CloseSession(Session session) {
    [session.controller release];
    [session.flycutOperator release];
    [session.pasteboard release];
    NSApp = nil;
    [session.application release];
}

static void TestSelectionPastesOnce(void) {
    Session session = OpenVisibleBezel();
    [session.controller metaKeysReleased];
    RunPastDelays();
    printf("selection: pasteboard=\"%s\" posts=%d pastes=%d trustChecks=%d hides=%d\n",
           session.pasteboard->string ? session.pasteboard->string.UTF8String : "", postCount, Pastes(), trustChecks, session.application->hides);
    CHECK([session.pasteboard->string isEqualToString:@"selected clip"], "selected clip written to the pasteboard");
    CHECK(postCount == 2 && Pastes() == 1, "a normal selection pastes exactly once (posts=%d)", postCount);
    CHECK(posted[0].code == kVK_ANSI_V && posted[1].code == kVK_ANSI_V && posted[0].down && !posted[1].down,
          "Command-V key-down then key-up on the U.S. layout");
    CHECK(trustChecks == 1 && layoutCopies == 1, "one nonprompting permission check and one layout read");
    CHECK(session.application->hides == 1 && ![session.controller bezelDisplayed], "bezel hidden once");
    CloseSession(session);
}

static void TestEscapeAfterSelection(NSString *name, NSEvent *escape) {
    Session session = OpenVisibleBezel();
    [session.controller metaKeysReleased];
    CHECK([session.pasteboard->string isEqualToString:@"selected clip"], "%s: a real selection precedes Escape",
          name.UTF8String);
    CHECK([session.controller bezelDisplayed], "%s: bezel still visible after the selection", name.UTF8String);
    [session.controller processBezelKeyDown:escape];
    int hidesAtEscape = session.application->hides;
    CHECK(hidesAtEscape == 1 && ![session.controller bezelDisplayed], "%s: Escape hides the bezel at once",
          name.UTF8String);
    RunPastDelays();
    int lateHides = session.application->hides - hidesAtEscape;
    printf("%s: paste events posted after Escape: %d (expected 0); pastes=%d trustChecks=%d late hides=%d (expected 0)\n",
           name.UTF8String, postCount, Pastes(), trustChecks, lateHides);
    CHECK(postCount == 0 && trustChecks == 0, "%s: a cancelled selection must not paste", name.UTF8String);
    CHECK(lateHides == 0, "%s: no delayed hide may outlive the cancelled selection", name.UTF8String);
    CloseSession(session);
}

static void TestEscapeRestoresFavorites(void) {
    Session session = OpenVisibleBezel();
    [session.flycutOperator toggleToFromFavoritesStore];
    CHECK([session.flycutOperator favoritesStoreIsSelected], "favorites selected before Escape");
    [session.controller processBezelKeyDown:KeyDown(53, @"")];
    RunPastDelays();
    printf("favorites: selected after Escape=%d hides=%d posts=%d\n",
           [session.flycutOperator favoritesStoreIsSelected], session.application->hides, postCount);
    CHECK(![session.flycutOperator favoritesStoreIsSelected], "Escape restores the clipping store");
    CHECK(session.application->hides == 1 && postCount == 0, "Escape hides once and posts nothing");
    CloseSession(session);
}

int main(int argc, const char *argv[]) { @autoreleasepool {
    if (argc != 2) return 2;
    CHECK(NSApp == nil, "fixture has no real NSApplication");
    memoryDefaults = [[FCMemoryDefaults alloc] init];
    [memoryDefaults setObject:@0 forKey:@"savePreference"];
    method_setImplementation(class_getClassMethod([NSUserDefaults class], @selector(standardUserDefaults)),
                             (IMP)MemoryStandardDefaults);
    InstallGuard([FlycutImageStore class], @selector(sharedStore));
    InstallGuard([NSPasteboard class], @selector(generalPasteboard));
    if (!strcmp(argv[1], "selection")) {
        TestSelectionPastesOnce();
    } else if (!strcmp(argv[1], "escape-after-selection")) {
        TestEscapeAfterSelection(@"keycode-53", KeyDown(53, @""));
        TestEscapeAfterSelection(@"escape-character", KeyDown(1, @"\033"));
    } else if (!strcmp(argv[1], "favorites")) {
        TestEscapeRestoresFavorites();
    } else {
        return 2;
    }
    printf("%s: %s (%d assertion failures)\n", argv[1], failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
}}
