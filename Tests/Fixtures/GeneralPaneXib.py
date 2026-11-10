"""Turns the General pane of a loaded MainMenu NIB into the one of the tree's MainMenu.xib.

Imported by tests, not a test file itself. Without Xcode the tests load master's compiled NIB
(FLYCUT_TEST_RESOURCE_BUNDLE), so its General pane is master's, not this tree's. spec() reads
the tree's XIB; APPLY_SOURCE (Objective-C, appended to a fixture) applies it to the loaded pane
before -awakeFromNib's builders run:

- each XIB view is found in the NIB by its binding and class, its outlet, its title and exact
  class, or, for the unbound labels the stack retitled, its title in master's NIB (NIB_TITLES);
  a bound checkbox the NIB lacks is created; a NIB view the XIB lacks is removed;
- buttons and unbound labels get the XIB's title, every view the XIB's font;
- every constraint of the box's content view on a vertical attribute is replaced by the XIB's,
  and the XIB's other constraints on created views are added (the NIB keeps its horizontal
  constraints and each view's own size constraints: the stack does not change them);
- the tab view, the General pane and its box get the XIB's tab view height.

Checked when this was written: master's own XIB applied to master's NIB gives every view of
the pane the frame the NIB alone gives it. What it cannot show: Xcode's warnings, focus rings,
and the metrics of older macOS versions.
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

GENERAL = "net.sf.jumpcut.preferences.general.tiff"
VERTICAL = {"top", "bottom", "centerY", "firstBaseline", "lastBaseline", "height"}
CLASSES = {"button": "NSButton", "textField": "NSTextField", "popUpButton": "NSPopUpButton", "stepper": "NSStepper"}
# Unbound labels without an outlet whose title the stack changed: their title in master's NIB.
NIB_TITLES = {"IZZ-Ep-7nD": "Passwords:"}


def _title(cell: ET.Element | None) -> str | None:
    if cell is None:
        return None
    if cell.get("title") is not None:
        return cell.get("title")
    node = cell.find("string[@key='title']")
    return node.text if node is not None else None


def _constraint(c: ET.Element, content: str) -> dict:
    first, second = c.get("firstItem"), c.get("secondItem")
    out = {"id": c.get("id"), "first": first if first not in (None, content) else "SUPER",
           "fa": c.get("firstAttribute"), "rel": c.get("relation", "equal"), "c": float(c.get("constant", 0)),
           "m": float(c.get("multiplier", 1)), "prio": float(c.get("priority", 1000))}
    if c.get("secondAttribute"):
        out["second"] = second if second not in (None, content) else "SUPER"
        out["sa"] = c.get("secondAttribute")
    return out


def general_pane(xib: pathlib.Path) -> tuple[ET.Element, ET.Element, ET.Element]:
    """The General tab view item, its box's content view and the tab view, as XML elements."""
    root = ET.parse(xib).getroot()
    item = next(e for e in root.iter("tabViewItem") if e.get("identifier") == GENERAL)
    content = item.find("view[@key='view']/subviews/box/view[@key='contentView']")
    tabs = next(e for e in root.iter("tabView") if item in list(e.iter("tabViewItem")))
    return item, content, tabs


def spec(xib: pathlib.Path) -> dict:
    """What APPLY_SOURCE needs from the XIB, as JSON-ready data."""
    root = ET.parse(xib).getroot()
    item, content, tabs = general_pane(xib)
    outlets = {o.get("destination"): o.get("property") for o in root.iter("outlet")}
    views = []
    for v in content.findall("subviews/*"):
        cell = v.find("*[@key='cell']")
        font = cell.find("font[@key='font']") if cell is not None else None
        bound = [b.get("keyPath") for b in v.iter("binding") if b.get("name") in ("value", "selectedIndex")]
        views.append({"id": v.get("id"), "cls": CLASSES[v.tag], "title": _title(cell),
                      "font": dict(font.attrib) if font is not None else None, "bind": bound[0] if bound else None,
                      "outlet": outlets.get(v.get("id")), "nibTitle": NIB_TITLES.get(v.get("id"))})
    constraints = [_constraint(c, content.get("id")) for c in content.findall("constraints/constraint")]
    vertical = [c for c in constraints if c["fa"] in VERTICAL or c.get("sa") in VERTICAL]
    other = [c for c in constraints if c not in vertical]
    return {"views": views, "vertical": vertical, "other": other,
            "height": float(tabs.find("rect[@key='frame']").get("height"))}


APPLY_SOURCE = r'''
// Tests/Fixtures/GeneralPaneXib.py: the loaded General pane becomes the tree's XIB's.
static NSString *GPXText(NSView *v)
{
    if ([v isKindOfClass:[NSPopUpButton class]]) return nil;
    if ([v isKindOfClass:[NSButton class]]) return [(NSButton *)v title];
    if ([v isKindOfClass:[NSTextField class]]) return [(NSTextField *)v stringValue];
    return nil;
}

static NSString *GPXBound(NSView *v)
{
    for (NSString *name in @[NSValueBinding, NSSelectedIndexBinding]) {
        NSString *keyPath = [[v infoForBinding:name] objectForKey:NSObservedKeyPathKey];
        if (keyPath != nil) return keyPath;
    }
    return nil;
}

static NSFont *GPXFont(NSDictionary *f)
{
    NSString *meta = f[@"metaFont"];
    CGFloat size = f[@"size"] ? [f[@"size"] doubleValue] : 0;
    if ([meta isEqualToString:@"system"]) return [NSFont systemFontOfSize:size ?: [NSFont systemFontSize]];
    if ([meta isEqualToString:@"systemSemibold"]) return [NSFont systemFontOfSize:size ?: [NSFont systemFontSize] weight:NSFontWeightSemibold];
    if ([meta isEqualToString:@"systemBold"]) return [NSFont boldSystemFontOfSize:size ?: [NSFont systemFontSize]];
    if ([meta isEqualToString:@"smallSystem"]) return [NSFont systemFontOfSize:size ?: [NSFont smallSystemFontSize]];
    if ([meta isEqualToString:@"label"]) return [NSFont labelFontOfSize:size ?: [NSFont labelFontSize]];
    if ([meta isEqualToString:@"menu"]) return [NSFont menuFontOfSize:size];
    if (f[@"name"]) return [NSFont fontWithName:f[@"name"] size:size];
    return nil;
}

static NSLayoutAttribute GPXAttribute(NSString *name)
{
    NSDictionary *names = @{@"top": @(NSLayoutAttributeTop), @"bottom": @(NSLayoutAttributeBottom),
                            @"leading": @(NSLayoutAttributeLeading), @"trailing": @(NSLayoutAttributeTrailing),
                            @"centerY": @(NSLayoutAttributeCenterY), @"centerX": @(NSLayoutAttributeCenterX),
                            @"firstBaseline": @(NSLayoutAttributeFirstBaseline), @"lastBaseline": @(NSLayoutAttributeLastBaseline),
                            @"height": @(NSLayoutAttributeHeight), @"width": @(NSLayoutAttributeWidth)};
    NSNumber *n = names[name];
    return n ? (NSLayoutAttribute)[n integerValue] : NSLayoutAttributeNotAnAttribute;
}

static BOOL GPXIsVertical(NSLayoutAttribute a)
{
    return a == NSLayoutAttributeTop || a == NSLayoutAttributeBottom || a == NSLayoutAttributeCenterY ||
           a == NSLayoutAttributeFirstBaseline || a == NSLayoutAttributeLastBaseline || a == NSLayoutAttributeHeight;
}

static NSView *GPXFind(NSView *content, id controller, NSDictionary *v, NSSet *taken)
{
    Class cls = NSClassFromString(v[@"cls"]);
    NSString *trimmed = [v[@"title"] isKindOfClass:[NSString class]]
        ? [v[@"title"] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] : nil;
    for (int pass = 0; pass < 4; pass++) {
        NSView *found = nil;
        int count = 0;
        if (pass == 1) {
            if (![v[@"outlet"] isKindOfClass:[NSString class]]) continue;
            Ivar ivar = class_getInstanceVariable([controller class], [v[@"outlet"] UTF8String]);
            NSView *outlet = ivar ? object_getIvar(controller, ivar) : nil;
            if ([outlet superview] == content && ![taken containsObject:[NSValue valueWithPointer:outlet]]) return outlet;
            continue;
        }
        for (NSView *candidate in [content subviews]) {
            if ([taken containsObject:[NSValue valueWithPointer:candidate]]) continue;
            NSString *text = [GPXText(candidate) stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
            BOOL match = NO;
            if (pass == 0) match = [v[@"bind"] isKindOfClass:[NSString class]] && [candidate isKindOfClass:cls] &&
                                   [GPXBound(candidate) isEqualToString:v[@"bind"]];
            if (pass == 2) match = trimmed != nil && [candidate class] == cls && GPXBound(candidate) == nil && [text isEqualToString:trimmed];
            if (pass == 3) match = [v[@"nibTitle"] isKindOfClass:[NSString class]] && [candidate class] == cls &&
                                   [text isEqualToString:v[@"nibTitle"]];
            if (match) { found = candidate; count++; }
        }
        if (count == 1) return found;
    }
    return nil;
}

// Returns what could not be applied (empty: the pane is the XIB's).
static NSArray *GPXApply(NSView *content, NSTabView *tabs, id controller, NSDictionary *spec)
{
    NSMutableArray *problems = [NSMutableArray array];
    NSMutableDictionary *byId = [NSMutableDictionary dictionary];
    NSMutableSet *taken = [NSMutableSet set];
    NSMutableArray *created = [NSMutableArray array];
    for (NSDictionary *v in spec[@"views"]) {
        NSView *view = GPXFind(content, controller, v, taken);
        if (view == nil && [v[@"cls"] isEqualToString:@"NSButton"] && [v[@"bind"] isKindOfClass:[NSString class]]) {
            NSButton *checkbox = [NSButton checkboxWithTitle:v[@"title"] target:nil action:nil];
            [checkbox setTranslatesAutoresizingMaskIntoConstraints:NO];
            [checkbox setIdentifier:[@"xib-" stringByAppendingString:v[@"id"]]];
            [content addSubview:checkbox];
            [created addObject:v[@"id"]];
            view = checkbox;
        }
        if (view == nil) { [problems addObject:[@"not found: " stringByAppendingString:v[@"id"]]]; continue; }
        byId[v[@"id"]] = view;
        [taken addObject:[NSValue valueWithPointer:view]];
    }
    for (NSView *view in [[[content subviews] copy] autorelease])
        if (![taken containsObject:[NSValue valueWithPointer:view]]) [view removeFromSuperview];
    for (NSDictionary *v in spec[@"views"]) {
        NSView *view = byId[v[@"id"]];
        if (view == nil) continue;
        NSString *title = [v[@"title"] isKindOfClass:[NSString class]] ? v[@"title"] : nil;
        if (title && [view isKindOfClass:[NSButton class]] && ![view isKindOfClass:[NSPopUpButton class]])
            [(NSButton *)view setTitle:title];
        else if (title && [view isKindOfClass:[NSTextField class]] && GPXBound(view) == nil)
            [(NSTextField *)view setStringValue:title];
        NSFont *font = [v[@"font"] isKindOfClass:[NSDictionary class]] ? GPXFont(v[@"font"]) : nil;
        if (font && [view respondsToSelector:@selector(setFont:)]) [(NSControl *)view setFont:font];
    }
    NSMutableArray *gone = [NSMutableArray array];
    for (NSLayoutConstraint *k in [content constraints])
        if ([k isMemberOfClass:[NSLayoutConstraint class]] && (GPXIsVertical([k firstAttribute]) || GPXIsVertical([k secondAttribute])))
            [gone addObject:k];
    [content removeConstraints:gone];
    NSMutableArray *added = [NSMutableArray array];
    NSMutableArray *wanted = [NSMutableArray arrayWithArray:spec[@"vertical"]];
    for (NSDictionary *c in spec[@"other"])
        if ([created containsObject:c[@"first"]] || [created containsObject:c[@"second"] ?: @""]) [wanted addObject:c];
    for (NSDictionary *c in wanted) {
        NSView *first = [c[@"first"] isEqualToString:@"SUPER"] ? content : byId[c[@"first"]];
        NSView *second = c[@"second"] == nil ? nil : ([c[@"second"] isEqualToString:@"SUPER"] ? content : byId[c[@"second"]]);
        if (first == nil || (c[@"second"] != nil && second == nil)) { [problems addObject:[@"constraint: " stringByAppendingString:c[@"id"]]]; continue; }
        NSLayoutRelation relation = [c[@"rel"] isEqualToString:@"greaterThanOrEqual"] ? NSLayoutRelationGreaterThanOrEqual
                                  : ([c[@"rel"] isEqualToString:@"lessThanOrEqual"] ? NSLayoutRelationLessThanOrEqual : NSLayoutRelationEqual);
        NSLayoutConstraint *k = [NSLayoutConstraint constraintWithItem:first attribute:GPXAttribute(c[@"fa"]) relatedBy:relation
                                                                toItem:second attribute:second ? GPXAttribute(c[@"sa"]) : NSLayoutAttributeNotAnAttribute
                                                            multiplier:[c[@"m"] doubleValue] constant:[c[@"c"] doubleValue]];
        [k setPriority:[c[@"prio"] floatValue]];
        [k setIdentifier:c[@"id"]];
        [added addObject:k];
    }
    [content addConstraints:added];
    CGFloat height = [spec[@"height"] doubleValue];
    NSView *item = [[tabs tabViewItemAtIndex:[tabs indexOfTabViewItemWithIdentifier:@"net.sf.jumpcut.preferences.general.tiff"]] view];
    NSView *box = [[item subviews] firstObject];
    [tabs setFrameSize:NSMakeSize(NSWidth([tabs frame]), height)];
    [item setFrameSize:NSMakeSize(NSWidth([item frame]), height)];
    [box setFrameSize:NSMakeSize(NSWidth([box frame]), height)];
    return problems;
}
'''
