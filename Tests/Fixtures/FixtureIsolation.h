// Test-only isolation for native fixtures that run Flycut or AppKit code.
//
// Import this header exactly once per fixture binary. Before main() runs it
// installs:
//  * FCMemoryDefaults, an in-memory NSUserDefaults that
//    +[NSUserDefaults standardUserDefaults] returns for the whole process, so
//    production code and AppKit keep every default in process memory and no
//    preferences domain is written through cfprefsd;
//  * tripwires on the writing methods of NSUserDefaults itself: a write that
//    still reaches a real defaults object (for example a separately created
//    suite) ends the fixture with exit status FC_FIXTURE_ISOLATION_EXIT
//    instead of persisting anything;
// and provides FCOffscreenStatusItem, a stand-in for NSStatusItem whose button
// lives in a borderless, non-activating panel that is never ordered on screen,
// so no item appears in the menu bar.
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <unistd.h>

#define FC_FIXTURE_ISOLATION_EXIT 86

@interface FCMemoryDefaults : NSUserDefaults {
    NSMutableDictionary *registeredValues;
    NSMutableDictionary *storedValues;
}
@end

@implementation FCMemoryDefaults

- (instancetype)init
{
    // The superclass state is never used: every accessor below is overridden
    // and none of them calls super.
    self = [super init];
    if (self != nil) {
        registeredValues = [[NSMutableDictionary alloc] init];
        storedValues = [[NSMutableDictionary alloc] init];
    }
    return self;
}

- (void)dealloc
{
    [registeredValues release];
    [storedValues release];
    [super dealloc];
}

- (id)objectForKey:(NSString *)key
{
    if (key == nil)
        return nil;
    id value = [storedValues objectForKey:key];
    return value != nil ? value : [registeredValues objectForKey:key];
}

- (void)setObject:(id)value forKey:(NSString *)key
{
    if (key == nil)
        return;
    if (value == nil) {
        [storedValues removeObjectForKey:key];
        return;
    }
    id copy = [value copy];
    [storedValues setObject:copy forKey:key];
    [copy release];
}

- (void)removeObjectForKey:(NSString *)key
{
    if (key != nil)
        [storedValues removeObjectForKey:key];
}

- (void)registerDefaults:(NSDictionary *)defaults
{
    [registeredValues addEntriesFromDictionary:defaults];
}

- (NSDictionary *)dictionaryRepresentation
{
    NSMutableDictionary *values = [NSMutableDictionary dictionaryWithDictionary:registeredValues];
    [values addEntriesFromDictionary:storedValues];
    return values;
}

- (id)valueForKey:(NSString *)key { return [self objectForKey:key]; }
- (void)setValue:(id)value forKey:(NSString *)key { [self setObject:value forKey:key]; }

- (BOOL)boolForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value respondsToSelector:@selector(boolValue)] ? [value boolValue] : NO;
}

- (NSInteger)integerForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value respondsToSelector:@selector(integerValue)] ? [value integerValue] : 0;
}

- (float)floatForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value respondsToSelector:@selector(floatValue)] ? [value floatValue] : 0.0f;
}

- (double)doubleForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value respondsToSelector:@selector(doubleValue)] ? [value doubleValue] : 0.0;
}

- (NSString *)stringForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    if ([value isKindOfClass:[NSString class]])
        return value;
    return [value isKindOfClass:[NSNumber class]] ? [value stringValue] : nil;
}

- (NSArray *)arrayForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSArray class]] ? value : nil;
}

- (NSArray *)stringArrayForKey:(NSString *)key
{
    NSArray *values = [self arrayForKey:key];
    for (id value in values) {
        if (![value isKindOfClass:[NSString class]])
            return nil;
    }
    return values;
}

- (NSDictionary *)dictionaryForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSDictionary class]] ? value : nil;
}

- (NSData *)dataForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    return [value isKindOfClass:[NSData class]] ? value : nil;
}

- (NSURL *)URLForKey:(NSString *)key
{
    id value = [self objectForKey:key];
    if ([value isKindOfClass:[NSURL class]])
        return value;
    if ([value isKindOfClass:[NSString class]])
        return [NSURL fileURLWithPath:[value stringByExpandingTildeInPath]];
    return nil;
}

- (void)setBool:(BOOL)value forKey:(NSString *)key { [self setObject:[NSNumber numberWithBool:value] forKey:key]; }
- (void)setInteger:(NSInteger)value forKey:(NSString *)key { [self setObject:[NSNumber numberWithInteger:value] forKey:key]; }
- (void)setFloat:(float)value forKey:(NSString *)key { [self setObject:[NSNumber numberWithFloat:value] forKey:key]; }
- (void)setDouble:(double)value forKey:(NSString *)key { [self setObject:[NSNumber numberWithDouble:value] forKey:key]; }
- (void)setURL:(NSURL *)value forKey:(NSString *)key { [self setObject:value forKey:key]; }
- (BOOL)synchronize { return YES; }

@end

static FCMemoryDefaults *FCFixtureDefaults;

static id FCFixtureStandardUserDefaults(id self, SEL _cmd)
{
    (void)self;
    (void)_cmd;
    return FCFixtureDefaults;
}

static void FCFixtureIgnoreReset(id self, SEL _cmd)
{
    (void)self;
    (void)_cmd;
}

static void FCRealDefaultsWrite(id self, SEL _cmd, ...)
{
    fprintf(stderr, "FixtureIsolation: -[%s %s] reached a real NSUserDefaults object; "
                    "the fixture would persist preferences outside the test\n",
            class_getName(object_getClass(self)), sel_getName(_cmd));
    NSArray *frames = [NSThread callStackSymbols];
    for (NSUInteger index = 1; index < [frames count] && index < 9; index++)
        fprintf(stderr, "  %s\n", [[frames objectAtIndex:index] UTF8String]);
    // _exit rather than abort(): no crash report is written for a test failure.
    _exit(FC_FIXTURE_ISOLATION_EXIT);
}

static BOOL FCIsPersistingDefaultsSelector(SEL selector)
{
    static const char *const names[] = {
        "setObject:forKey:", "removeObjectForKey:", "setBool:forKey:", "setInteger:forKey:",
        "setFloat:forKey:", "setDouble:forKey:", "setURL:forKey:", "setValue:forKey:",
        "setPersistentDomain:forName:", "removePersistentDomainForName:",
    };
    const char *name = sel_getName(selector);
    for (size_t index = 0; index < sizeof(names) / sizeof(names[0]); index++) {
        if (strcmp(name, names[index]) == 0)
            return YES;
    }
    return NO;
}

__attribute__((constructor)) static void FCInstallFixtureIsolation(void)
{
    @autoreleasepool {
        FCFixtureDefaults = [[FCMemoryDefaults alloc] init];
        if (![FCFixtureDefaults isMemberOfClass:[FCMemoryDefaults class]]) {
            fprintf(stderr, "FixtureIsolation: could not create in-memory defaults\n");
            _exit(FC_FIXTURE_ISOLATION_EXIT);
        }
        Class defaultsClass = [NSUserDefaults class];
        method_setImplementation(class_getClassMethod(defaultsClass, @selector(standardUserDefaults)),
                                 (IMP)FCFixtureStandardUserDefaults);
        Method reset = class_getClassMethod(defaultsClass, @selector(resetStandardUserDefaults));
        if (reset != NULL)
            method_setImplementation(reset, (IMP)FCFixtureIgnoreReset);

        // Only methods NSUserDefaults defines itself; inherited NSObject methods
        // (for example KVC's -setValue:forKey:) stay untouched.
        unsigned int count = 0;
        Method *methods = class_copyMethodList(defaultsClass, &count);
        for (unsigned int index = 0; index < count; index++) {
            if (FCIsPersistingDefaultsSelector(method_getName(methods[index])))
                method_setImplementation(methods[index], (IMP)FCRealDefaultsWrite);
        }
        free(methods);
    }
}

// Stand-in for NSStatusItem: production code only talks to -button and -setMenu:.
@interface FCOffscreenStatusItem : NSObject {
    NSPanel *hostPanel;
    NSStatusBarButton *statusButton;
    NSMenu *statusMenu;
}
- (instancetype)initWithLength:(CGFloat)length;
- (NSStatusBarButton *)button;
- (NSWindow *)hostWindow;
- (NSMenu *)menu;
- (void)setMenu:(NSMenu *)menu;
@end

@implementation FCOffscreenStatusItem

- (instancetype)initWithLength:(CGFloat)length
{
    self = [super init];
    if (self != nil) {
        NSRect frame = NSMakeRect(0, 0, length, 22);
        // Far outside every screen, borderless, non-activating, never ordered in.
        hostPanel = [[NSPanel alloc] initWithContentRect:NSOffsetRect(frame, -30000, -30000)
                                               styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                 backing:NSBackingStoreBuffered
                                                   defer:NO];
        [hostPanel setReleasedWhenClosed:NO];
        statusButton = [[NSStatusBarButton alloc] initWithFrame:frame];
        [[hostPanel contentView] addSubview:statusButton];
    }
    return self;
}

- (void)dealloc
{
    [statusButton removeFromSuperview];
    [statusButton release];
    [hostPanel release];
    [statusMenu release];
    [super dealloc];
}

- (NSStatusBarButton *)button { return statusButton; }
- (NSWindow *)hostWindow { return hostPanel; }
- (NSMenu *)menu { return statusMenu; }

- (void)setMenu:(NSMenu *)menu
{
    [menu retain];
    [statusMenu release];
    statusMenu = menu;
}

@end
