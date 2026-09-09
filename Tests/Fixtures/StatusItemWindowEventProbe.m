#import <Cocoa/Cocoa.h>
#import "AppController.h"

@interface AppController (StatusItemWindowEventProbe)
- (void)configureStatusItemInteraction;
@end

@interface FCWindowEventProbeController : AppController {
    NSUInteger toggleCount;
    NSUInteger menuCount;
}
@property(nonatomic, assign) NSUInteger toggleCount;
@property(nonatomic, assign) NSUInteger menuCount;
@end

@implementation FCWindowEventProbeController
@synthesize toggleCount;
@synthesize menuCount;
- (IBAction)toggleClipboardTracking:(id)sender
{
    (void)sender;
    self.toggleCount = self.toggleCount + 1;
}
- (void)showStatusItemMenu
{
    self.menuCount = self.menuCount + 1;
}
@end

static NSEvent *MouseEvent(NSEventType type, NSWindow *window, NSPoint point,
                           NSEventModifierFlags flags, NSInteger eventNumber)
{
    return [NSEvent mouseEventWithType:type
                              location:point
                         modifierFlags:flags
                             timestamp:eventNumber / 100.0
                          windowNumber:[window windowNumber]
                               context:nil
                           eventNumber:eventNumber
                            clickCount:1
                              pressure:(type == NSEventTypeLeftMouseDown ||
                                        type == NSEventTypeRightMouseDown) ? 1.0 : 0.0];
}

static BOOL ResolveStatusButton(NSStatusItem *item, NSStatusBarButton **resolvedButton,
                                NSWindow **resolvedWindow, NSPoint *resolvedPoint)
{
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:1.0];
    do {
        NSStatusBarButton *button = [item button];
        NSWindow *window = [button window];
        if (button != nil && window != nil && [window windowNumber] != 0) {
            NSPoint buttonPoint = NSMakePoint(NSMidX([button bounds]), NSMidY([button bounds]));
            NSPoint point = [button convertPoint:buttonPoint toView:nil];
            NSView *hit = [[window contentView] hitTest:point];
            if (hit == button || [hit isDescendantOf:button]) {
                *resolvedButton = button;
                *resolvedWindow = window;
                *resolvedPoint = point;
                return YES;
            }
        }
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    } while ([deadline timeIntervalSinceNow] > 0.0);
    return NO;
}

static int ExerciseButton(NSEventType downType, NSEventType upType, BOOL option,
                          NSUInteger expectedToggle, NSUInteger expectedMenu)
{
    FCWindowEventProbeController *controller = [[FCWindowEventProbeController alloc] init];
    NSStatusItem *item = [[NSStatusBar systemStatusBar] statusItemWithLength:36.0];
    NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"Probe"] autorelease];
    [controller setValue:item forKey:@"statusItem"];
    [controller setValue:menu forKey:@"jcMenu"];
    [controller configureStatusItemInteraction];

    NSStatusBarButton *button = nil;
    NSWindow *window = nil;
    NSPoint point = NSZeroPoint;
    if (!ResolveStatusButton(item, &button, &window, &point)) {
        [[NSStatusBar systemStatusBar] removeStatusItem:item];
        return 10;
    }
    NSEventModifierFlags flags = option ? NSEventModifierFlagOption : 0;
    NSEvent *mouseUp = MouseEvent(upType, window, point, flags, 2);
    [NSApp postEvent:mouseUp atStart:YES];
    [NSApp sendEvent:MouseEvent(downType, window, point, flags, 1)];
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];

    NSUInteger toggles = controller.toggleCount;
    NSUInteger menus = controller.menuCount;
    [[NSStatusBar systemStatusBar] removeStatusItem:item];
    if (toggles != expectedToggle)
        return 20 + (int)toggles;
    if (menus != expectedMenu)
        return 30 + (int)menus;
    return 0;
}

static int StressOptionButtons(NSUInteger repetitions)
{
    FCWindowEventProbeController *controller = [[FCWindowEventProbeController alloc] init];
    NSStatusItem *item = [[NSStatusBar systemStatusBar] statusItemWithLength:36.0];
    NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"Stress Probe"] autorelease];
    [controller setValue:item forKey:@"statusItem"];
    [controller setValue:menu forKey:@"jcMenu"];
    [controller configureStatusItemInteraction];

    NSStatusBarButton *button = nil;
    NSWindow *window = nil;
    NSPoint point = NSZeroPoint;
    if (!ResolveStatusButton(item, &button, &window, &point)) {
        [[NSStatusBar systemStatusBar] removeStatusItem:item];
        return 10;
    }

    NSUInteger expected = 0;
    NSInteger eventNumber = 100;
    const NSEventType downTypes[] = { NSEventTypeRightMouseDown, NSEventTypeLeftMouseDown };
    const NSEventType upTypes[] = { NSEventTypeRightMouseUp, NSEventTypeLeftMouseUp };
    for (NSUInteger buttonIndex = 0; buttonIndex < 2; buttonIndex++) {
        for (NSUInteger iteration = 0; iteration < repetitions; iteration++) {
            NSEvent *mouseUp = MouseEvent(upTypes[buttonIndex], window, point,
                                          NSEventModifierFlagOption, eventNumber++);
            [NSApp postEvent:mouseUp atStart:YES];
            [NSApp sendEvent:MouseEvent(downTypes[buttonIndex], window, point,
                                         NSEventModifierFlagOption, eventNumber++)];
            expected++;
            if (controller.toggleCount != expected || controller.menuCount != 0) {
                [[NSStatusBar systemStatusBar] removeStatusItem:item];
                return 20 + (int)buttonIndex;
            }
        }
    }
    [[NSStatusBar systemStatusBar] removeStatusItem:item];
    printf("OPTION_STRESS=PASS RIGHT=%lu LEFT=%lu\n",
           (unsigned long)repetitions, (unsigned long)repetitions);
    return 0;
}

static int VerifyProgrammaticPressIgnoresStaleOptionEvent(void)
{
    FCWindowEventProbeController *controller = [[FCWindowEventProbeController alloc] init];
    NSStatusItem *item = [[NSStatusBar systemStatusBar] statusItemWithLength:36.0];
    NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"Programmatic Probe"] autorelease];
    [controller setValue:item forKey:@"statusItem"];
    [controller setValue:menu forKey:@"jcMenu"];
    [controller configureStatusItemInteraction];

    NSStatusBarButton *button = nil;
    NSWindow *window = nil;
    NSPoint point = NSZeroPoint;
    if (!ResolveStatusButton(item, &button, &window, &point)) {
        [[NSStatusBar systemStatusBar] removeStatusItem:item];
        return 10;
    }

    NSEvent *stale = [NSEvent mouseEventWithType:NSEventTypeRightMouseDown
                                         location:point
                                    modifierFlags:NSEventModifierFlagOption
                                        timestamp:1.0
                                     windowNumber:[window windowNumber]
                                          context:nil
                                      eventNumber:900
                                       clickCount:1
                                         pressure:1.0];
    [NSApp postEvent:stale atStart:YES];
    NSEvent *retrieved = [NSApp nextEventMatchingMask:NSEventMaskRightMouseDown
                                             untilDate:[NSDate dateWithTimeIntervalSinceNow:1.0]
                                                inMode:NSDefaultRunLoopMode
                                               dequeue:YES];
    if (retrieved == nil || [NSApp currentEvent] != retrieved) {
        [[NSStatusBar systemStatusBar] removeStatusItem:item];
        return 11;
    }
    [button performClick:nil];
    NSUInteger toggles = controller.toggleCount;
    NSUInteger menus = controller.menuCount;
    [[NSStatusBar systemStatusBar] removeStatusItem:item];
    if (toggles != 0)
        return 20 + (int)toggles;
    if (menus != 1)
        return 30 + (int)menus;
    return 0;
}

int main(void)
{
    @autoreleasepool {
        [NSApplication sharedApplication];
        int rightOption = ExerciseButton(NSEventTypeRightMouseDown, NSEventTypeRightMouseUp,
                                         YES, 1, 0);
        int leftOption = ExerciseButton(NSEventTypeLeftMouseDown, NSEventTypeLeftMouseUp,
                                        YES, 1, 0);
        int rightPlain = ExerciseButton(NSEventTypeRightMouseDown, NSEventTypeRightMouseUp,
                                        NO, 0, 1);
        int leftPlain = ExerciseButton(NSEventTypeLeftMouseDown, NSEventTypeLeftMouseUp,
                                       NO, 0, 1);
        printf("RIGHT_OPTION=%d LEFT_OPTION=%d RIGHT_PLAIN=%d LEFT_PLAIN=%d\n",
               rightOption, leftOption, rightPlain, leftPlain);
        if (rightOption != 0)
            return 100 + rightOption;
        if (leftOption != 0)
            return 200 + leftOption;
        if (rightPlain != 0)
            return 300 + rightPlain;
        if (leftPlain != 0)
            return 400 + leftPlain;
        int programmatic = VerifyProgrammaticPressIgnoresStaleOptionEvent();
        if (programmatic != 0)
            return 500 + programmatic;
        int stress = StressOptionButtons(100);
        if (stress != 0)
            return 600 + stress;
        printf("STATUS_ITEM_WINDOW_EVENT_MATRIX=PASS\n");
    }
    return 0;
}
