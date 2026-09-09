#import "PasteTestEnvironment.h"

@implementation FCPasteTestDefaults
static NSMutableDictionary *values;
+ (id)standardUserDefaults {
    static id instance;
    if (!instance) { instance = [self new]; values = [NSMutableDictionary new]; }
    return instance;
}
- (void)registerDefaults:(NSDictionary *)defaults {
    for (id key in defaults) if (!values[key]) values[key] = defaults[key];
}
- (id)objectForKey:(NSString *)key { return values[key]; }
- (void)setObject:(id)value forKey:(NSString *)key { values[key] = value; }
- (BOOL)boolForKey:(NSString *)key { return [values[key] boolValue]; }
- (NSInteger)integerForKey:(NSString *)key { return [values[key] integerValue]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { values[key] = @(value); }
@end
