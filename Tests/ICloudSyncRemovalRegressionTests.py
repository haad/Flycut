#!/usr/bin/env python3
"""Preferences show no iCloud sync controls, and changing "Save" raises no iCloud alert.

This fork ships without iCloud sync since its first own commits (8b0caf2,
d737659): the MJCloudKitUserDefaultsSync library, every call into it and the
iCloud entitlements are gone (TermiT/Flycut#270 reports the same dead row
upstream). Preferences > General still showed an "iCloud Sync:" row with
"Settings" and "Clippings" checkboxes. They synced nothing; their actions,
and the "Save" pop-up while syncClippingsViaICloud was stored, only raised
alerts about it, and Cancel in the "Save" alert put "After each clip" back.

The XIB cases parse the tree's English.lproj/MainMenu.xib (no Xcode needed):
no iCloud control, label, binding or action is left; every id reference and
constraint item resolves; the "Clippings:" heading follows "Launch Flycut on
login" with the section gap of the other headings; and the frames written for
the edited part of the General pane match its constraints.

The fixture cases load the production NIB (master's compiled MainMenu.nib for
trees that carry only MainMenu.xib, see Tests/Fixtures/PreferencesNibFixture.py)
with syncClippingsViaICloud = YES stored, as an old install may have it, and
count -[NSAlert runModal] (answered with Cancel): changing "Save" through the
pop-up's own action keeps the chosen value and raises no alert; a NIB that
still carries the old checkboxes (master's) raises no alert and no exception
when they are clicked. Without a NIB, the operator registers no iCloud
default and neither object answers the old sync entry points; stored values
stay as they are (inert).
"""
from __future__ import annotations

import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Fixtures"))
from PreferencesNibFixture import PreferencesNibCase  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
XIB = ROOT / "English.lproj" / "MainMenu.xib"
REFERENCE_ATTRIBUTES = ("firstItem", "secondItem", "destination", "target", "selectedItem", "previousBinding")


def load_xib() -> ET.Element:
    return ET.parse(XIB).getroot()


def elements_with_ids(root: ET.Element) -> dict[str, ET.Element]:
    found: dict[str, ET.Element] = {}
    for element in root.iter():
        if "id" in element.attrib:
            found.setdefault(element.attrib["id"], element)
    return found


def general_content(root: ET.Element) -> ET.Element:
    """The General pane's box content view (the one holding the "Clippings:" heading)."""
    for item in root.iter("tabViewItem"):
        if item.get("identifier") == "net.sf.jumpcut.preferences.general.tiff":
            for view in item.iter("view"):
                if view.get("key") == "contentView":
                    return view
    raise AssertionError("General pane content view not found in MainMenu.xib")


def cell_title(element: ET.Element) -> str:
    for cell in element:
        if cell.get("key") == "cell":
            title = cell.get("title")
            if title is None:
                node = cell.find("string[@key='title']")
                title = node.text if node is not None else ""
            return (title or "").strip()
    return ""


def subview_titled(content: ET.Element, title: str) -> ET.Element:
    matches = [v for v in content.find("subviews") if cell_title(v) == title]
    if len(matches) != 1:
        raise AssertionError(f"expected one General view titled {title!r}, found {len(matches)}")
    return matches[0]


def frame(element: ET.Element) -> dict[str, float]:
    rect = element.find("rect[@key='frame']")
    return {k: float(rect.get(k)) for k in ("x", "y", "width", "height")}


def heading(element: ET.Element) -> bool:
    for cell in element:
        if cell.get("key") == "cell":
            font = cell.find("font")
            return element.tag == "textField" and font is not None and font.get("metaFont") == "systemSemibold"
    return False


def vertical_constraint(content: ET.Element, first: str) -> ET.Element:
    """The constraint that places `first`'s top below another view."""
    found = [c for c in content.find("constraints")
             if c.get("firstItem") == first and c.get("firstAttribute") == "top"]
    if len(found) != 1:
        raise AssertionError(f"expected one top constraint for {first}, found {len(found)}")
    return found[0]


class ICloudSyncXibTests(unittest.TestCase):
    def test_the_xib_has_no_icloud_control_label_binding_or_action(self) -> None:
        offenders = []
        for element in load_xib().iter():
            texts = list(element.attrib.items()) + ([("text", element.text)] if element.text else [])
            for key, value in texts:
                if "icloud" in value.lower():
                    offenders.append(f"<{element.tag} id={element.get('id')}> {key}={value!r}")
        self.assertEqual(offenders, [], "MainMenu.xib still carries the dead iCloud sync row")

    def test_every_xib_reference_and_constraint_item_resolves(self) -> None:
        root = load_xib()
        ids: dict[str, int] = {}
        for element in root.iter():
            if "id" in element.attrib:
                ids[element.attrib["id"]] = ids.get(element.attrib["id"], 0) + 1
        self.assertEqual({k: n for k, n in ids.items() if n > 1}, {}, "duplicate ids in MainMenu.xib")
        dangling = [f"<{e.tag} id={e.get('id')}> {a}={e.get(a)}" for e in root.iter()
                    for a in REFERENCE_ATTRIBUTES if a in e.attrib and e.get(a) not in ids]
        self.assertEqual(dangling, [], "references to ids that MainMenu.xib does not define")
        outside = []
        for owner in root.iter():
            constraints = owner.find("constraints")
            if constraints is None or "id" not in owner.attrib:
                continue
            subtree = {e.get("id") for e in owner.iter() if "id" in e.attrib}
            for c in constraints:
                for attribute in ("firstItem", "secondItem"):
                    item = c.get(attribute)
                    if item is not None and item not in subtree:
                        outside.append(f"{c.get('id')} {attribute}={item} not inside {owner.get('id')}")
        self.assertEqual(outside, [], "constraints that name views outside their owner view")

    def test_the_clippings_heading_follows_launch_on_login_with_the_section_gap(self) -> None:
        content = general_content(load_xib())
        launch = subview_titled(content, "Launch Flycut on login")
        clippings = subview_titled(content, "Clippings:")
        placed = vertical_constraint(content, clippings.get("id"))
        self.assertEqual((placed.get("secondItem"), placed.get("secondAttribute")), (launch.get("id"), "bottom"),
                         "the \"Clippings:\" heading must sit right below \"Launch Flycut on login\"")
        gaps = {float(vertical_constraint(content, v.get("id")).get("constant", "0"))
                for v in content.find("subviews") if heading(v)}
        self.assertEqual(len(gaps), 1, f"section headings use different gaps: {sorted(gaps)}")
        self.assertEqual(float(placed.get("constant", "0")), gaps.pop())

    def test_the_general_pane_frames_match_its_constraints_around_the_edit(self) -> None:
        root = load_xib()
        content = general_content(root)
        found = elements_with_ids(root)
        # The pane, its box and the tab view share one height: the window takes the
        # General pane's height from the box (UKPrefsPanel -resizeToFit:).
        box = next(b for b in root.iter("box") if b.find("view[@key='contentView']") is content)
        heights = {name: frame(found[name])["height"] for name in ("345", "360")}
        heights.update(box=frame(box)["height"], content=frame(content)["height"])
        self.assertEqual(len(set(heights.values())), 1, f"General pane heights differ: {heights}")
        # A regular checkbox's alignment rect is inset from its 18 pt frame; read the
        # inset from an untouched pair of rows instead of assuming it.
        menu = subview_titled(content, "Menu selection pastes")
        launch = subview_titled(content, "Launch Flycut on login")
        step = vertical_constraint(content, launch.get("id"))
        self.assertEqual(step.get("secondItem"), menu.get("id"))
        inset = (float(step.get("constant")) - (frame(menu)["y"] - frame(launch)["y"] - frame(launch)["height"])) / 2
        top = subview_titled(content, "Sticky bezel (bezel, or pop-up, stays visible after hotkey is released)")
        margin = vertical_constraint(content, top.get("id"))
        self.assertEqual(margin.get("secondItem"), content.get("id"))
        written = frame(content)["height"] - (frame(top)["y"] + frame(top)["height"] - inset)
        self.assertEqual(written, float(margin.get("constant")), "top row frame vs. the pane's top margin")
        rows = [top, subview_titled(content, "Wraparound bezel (the first and last items are adjacent in order)"),
                menu, launch]
        for upper, lower in zip(rows, rows[1:]):
            gap = vertical_constraint(content, lower.get("id"))
            self.assertEqual(gap.get("secondItem"), upper.get("id"))
            self.assertEqual(frame(upper)["y"] - frame(lower)["y"] - frame(lower)["height"] + 2 * inset,
                             float(gap.get("constant")), f"frames of {cell_title(upper)!r} / {cell_title(lower)!r}")
        clippings = subview_titled(content, "Clippings:")
        placed = vertical_constraint(content, clippings.get("id"))
        anchor = found[placed.get("secondItem")]
        anchor_bottom = frame(anchor)["y"] + (inset if anchor.tag == "button" else 0)
        self.assertEqual(anchor_bottom - frame(clippings)["y"] - frame(clippings)["height"], float(placed.get("constant")),
                         "the \"Clippings:\" heading's frame does not match its constraint")


FIXTURE = r'''
static NSInteger alertCount = 0;
static NSMutableArray *alertTexts = nil;

static NSModalResponse CountedAlert(NSAlert *self, SEL cmd)
{
    (void)cmd;
    alertCount++;
    [alertTexts addObject:[NSString stringWithFormat:@"%@ | %@", [self messageText], [self informativeText]]];
    return NSAlertSecondButtonReturn;   // Cancel
}

static void CollectControls(NSView *view, NSMutableArray *into)
{
    if ([view isKindOfClass:[NSControl class]]) [into addObject:view];
    for (NSView *sub in [view subviews]) CollectControls(sub, into);
}

static NSArray *GeneralControls(void)
{
    NSMutableArray *controls = [NSMutableArray array];
    CollectControls(PaneView(generalPane), controls);
    return controls;
}

static NSArray *SyncSelectors(void)
{
    return @[@"toggleICloudSyncSettings:", @"toggleICloudSyncClippings:", @"setSavePreference:",
             @"checkPreferencesChanges:", @"checkPreferencesConflicts:", @"checkPreferencesSaveSuccess:",
             @"integrateAllStores", @"registerOrDeregisterICloudSync", @"checkCloudKitUpdates",
             @"application:didRegisterForRemoteNotificationsWithDeviceToken:",
             @"application:didFailToRegisterForRemoteNotificationsWithError:",
             @"application:didReceiveRemoteNotification:"];
}

static int Defaults(void)
{
    // An old install may have stored the keys; they stay untouched (inert).
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    InstallBoundaries();   // also creates an operator, which registers its defaults
    NSMutableArray *registered = [NSMutableArray array];
    for (NSString *key in @[@"syncSettingsViaICloud", @"syncClippingsViaICloud"])
        if ([defaults objectForKey:key] != nil) [registered addObject:key];
    [defaults setBool:YES forKey:@"syncClippingsViaICloud"];
    [[[FlycutOperator alloc] init] autorelease];
    BOOL storedKept = [defaults boolForKey:@"syncClippingsViaICloud"];
    NSMutableArray *answered = [NSMutableArray array];
    for (NSString *name in SyncSelectors()) {
        SEL selector = NSSelectorFromString(name);
        if ([AppController instancesRespondToSelector:selector]) [answered addObject:[@"AppController " stringByAppendingString:name]];
        if ([FlycutOperator instancesRespondToSelector:selector]) [answered addObject:[@"FlycutOperator " stringByAppendingString:name]];
    }
    Emit(@{@"registered": registered, @"answered": answered, @"storedValueKept": @(storedKept)});
    if ([registered count]) return 20;
    if ([answered count]) return 21;
    return storedKept ? 0 : 22;
}

static int SavePopUp(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setInteger:2 forKey:@"savePreference"];
    [defaults setBool:YES forKey:@"syncClippingsViaICloud"];
    ChangePane(generalPane);
    NSPopUpButton *popup = nil;
    for (NSControl *control in GeneralControls())
        if ([control isKindOfClass:[NSPopUpButton class]] && [BoundKeyPath(control) isEqualToString:@"values.savePreference"])
            popup = (NSPopUpButton *)control;
    if (popup == nil) { Emit(@{@"error": @"no Save pop-up bound to values.savePreference"}); return 30; }
    NSString *action = [popup action] ? NSStringFromSelector([popup action]) : @"(none)";
    NSString *exception = @"";
    BOOL sent = NO;
    @try {
        // The user picks "Never": the binding stores 0, then the pop-up sends its action.
        [popup selectItemAtIndex:0];
        [defaults setInteger:0 forKey:@"savePreference"];
        if ([popup action]) sent = [popup sendAction:[popup action] to:[popup target]];
    } @catch (NSException *e) {
        exception = [NSString stringWithFormat:@"%@: %@", [e name], [e reason]];
    }
    NSInteger save = [defaults integerForKey:@"savePreference"];
    BOOL stored = [defaults boolForKey:@"syncClippingsViaICloud"];
    Emit(@{@"action": action, @"sent": @(sent), @"alerts": @(alertCount), @"alertTexts": alertTexts,
           @"exception": exception, @"savePreferenceAfter": @(save), @"storedSyncClippingsAfter": @(stored)});
    if ([exception length]) return 31;
    if (alertCount) return 32;
    if (save != 0) return 33;
    return stored ? 0 : 34;
}

static int OldCheckboxes(void)
{
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setInteger:1 forKey:@"savePreference"];
    ChangePane(generalPane);
    NSMutableArray *clicked = [NSMutableArray array];
    NSString *exception = @"";
    for (NSControl *control in GeneralControls()) {
        NSString *keyPath = BoundKeyPath(control);
        if (![control isKindOfClass:[NSButton class]] || ![keyPath hasSuffix:@"ViaICloud"]) continue;
        [clicked addObject:[NSString stringWithFormat:@"%@ -> %@", keyPath,
                            [control action] ? NSStringFromSelector([control action]) : @"(none)"]];
        @try {
            [(NSButton *)control performClick:nil];
        } @catch (NSException *e) {
            exception = [NSString stringWithFormat:@"%@: %@", [e name], [e reason]];
        }
    }
    NSInteger save = [defaults integerForKey:@"savePreference"];
    Emit(@{@"clicked": clicked, @"alerts": @(alertCount), @"alertTexts": alertTexts, @"exception": exception,
           @"savePreferenceAfter": @(save),
           @"note": [clicked count] ? @"the NIB still carries the old row" : @"the NIB has no iCloud row"});
    if ([exception length]) return 41;
    if (alertCount) return 42;
    return save == 1 ? 0 : 43;
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        alertTexts = [[NSMutableArray alloc] init];
        method_setImplementation(class_getInstanceMethod([NSAlert class], @selector(runModal)), (IMP)CountedAlert);
        NSString *mode = [NSString stringWithUTF8String:argc > 2 ? argv[2] : ""];
        if (![[NSUserDefaults standardUserDefaults] isMemberOfClass:[FCMemoryDefaults class]]) return 3;
        if ([mode isEqualToString:@"defaults"]) return Defaults();
        int failed = LoadNib(argc, argv);
        if (failed) return failed;
        ChangePane(generalPane);   // stands in for -[UKPrefsPanel awakeFromNib]
        if ([mode isEqualToString:@"save-popup"]) return SavePopUp();
        if ([mode isEqualToString:@"old-checkboxes"]) return OldCheckboxes();
        return 4;
    }
}
'''


class ICloudSyncFixtureTests(PreferencesNibCase):
    FIXTURE = FIXTURE
    NAME = "ICloudSyncRemoval"
    NO_NIB_MODES = ("defaults",)

    def test_no_icloud_default_is_registered_and_no_sync_entry_point_is_left(self) -> None:
        self.run_mode("defaults", "the operator still registers an iCloud default, the controller or operator still "
                                  "answers an iCloud sync entry point, or a stored value was changed")

    def test_changing_save_keeps_the_choice_and_raises_no_icloud_alert(self) -> None:
        self.run_mode("save-popup", "changing \"Save\" with syncClippingsViaICloud stored raised an alert or did not "
                                    "keep the chosen value")

    def test_a_nib_that_still_has_the_old_checkboxes_raises_no_alert(self) -> None:
        self.run_mode("old-checkboxes", "clicking the old iCloud checkboxes of a NIB that still has them raised an "
                                        "alert or an exception")


if __name__ == "__main__":
    unittest.main()
