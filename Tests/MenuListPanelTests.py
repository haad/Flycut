#!/usr/bin/env python3
"""The menu-bar list panel, driven by keys in-process (no screen, no posted input).

The probe (Tests/Fixtures/MenuListPanelProbe.m) compiles the real engine, the list
model and UI/FlycutListPanel.m. The panel is laid out but never ordered on screen; key
events are NSEvent objects handed to it as -[NSApplication sendEvent:] would route
them. FixtureIsolation.h keeps defaults in memory, the image store records deletions in
memory, activation and window ordering are counted and never performed, and NSWorkspace's
notifications come from a private center (other applications activating in the session
cannot close the list). The probe's
JSON step log is kept in the artifacts directory.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "Tests" / "Fixtures"
PROBE = FIXTURES / "MenuListPanelProbe.m"
PANEL = ROOT / "UI" / "FlycutListPanel.m"


class MenuListPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-menu-list-panel-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name)
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.binary = cls.artifacts / "MenuListPanelProbe"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"), "-I", str(ROOT / "UI"), "-I", str(FIXTURES),
                   str(PROBE), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=240)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"probe compile failed ({build.returncode}):\n{build.stderr}")
        run = subprocess.run([str(cls.binary)], cwd=ROOT, text=True, capture_output=True, timeout=60)
        (cls.artifacts / "probe.json").write_text(run.stdout)
        (cls.artifacts / "probe.stderr.txt").write_text(run.stderr)
        cls.run_result = run
        try:
            cls.report = json.loads(run.stdout)
        except ValueError:
            cls.report = None

    def check(self, *names: str) -> None:
        self.assertIsNotNone(self.report, self.run_result.stdout[-2000:] + self.run_result.stderr[-2000:])
        checks = {c["check"]: c for c in self.report["checks"]}
        for name in names:
            self.assertIn(name, checks, f"probe did not reach: {name}\n{self.run_result.stderr[-2000:]}")
            self.assertTrue(checks[name]["pass"], f"{name}: {checks[name]['detail']}")

    def test_probe_runs_without_failures(self) -> None:
        self.assertEqual(self.run_result.returncode, 0, self.run_result.stderr[-4000:])

    def test_panel_is_a_non_activating_key_panel_with_the_search_field_focused(self) -> None:
        self.check("list opens", "panel is non-activating", "panel can become key, never main",
                   "panel stays while Flycut is inactive; key at once", "panel sits at menu level",
                   "search field has the keyboard focus", "search placeholder")

    def test_list_holds_all_clippings_in_one_list_and_matches_mockup_geometry(self) -> None:
        self.check("all 60 clippings in one list, favorites first, no header or divider rows",
                   "nothing highlighted at first (Return does nothing)",
                   "panel width 384 pt (today's menu width)", "20 rows: list height 468 pt, the 20th row cut in half",
                   "search field 5/374/22 pt, as wide as the highlight", "panel height = padding+search+separator+list+commands+padding")

    def test_arrows_move_from_the_favorites_straight_into_the_history(self) -> None:
        self.check("Down highlights the first favorite", "Down goes from the last favorite straight to the first history row",
                   "Up goes back to the last favorite")

    def test_row_icons_colours_and_accessibility(self) -> None:
        self.check("rows are entry views", "a plain history row shows no icons",
                   "a favorite that is not highlighted shows only its filled star",
                   "the highlighted row shows the trash and the star (outline: not a favorite)",
                   "a highlighted favorite shows the trash and its filled star",
                   "the highlight moving on hides the favorite's trash, keeps its star",
                   "star labels for VoiceOver", "trash label for VoiceOver", "filled star for favorites, outline otherwise",
                   "star in tertiaryLabelColor",
                   "highlighted row: star, trash and text in the selected-menu-item colour",
                   "row custom actions for VoiceOver", "VoiceOver hears which rows are favorites")

    def test_star_in_the_state_column_and_trash_at_the_right_edge_like_a_native_menu(self) -> None:
        # Sight test of build 9: the star back on the left (filled for favorites, outline only
        # on the highlighted row), the trash at the right edge, margins of a native menu.
        self.check("columns: star in the state column at the left, title at 28 like a native menu's, trash at the right edge",
                   "a click right of the star or on the title hits the row, not an icon",
                   "classic scroll bars: the trash stays 9 pt inside the narrower list, the star keeps its column")
        self.assertNotIn("kListIconGap", PANEL.read_text())

    # Sight test of the v4 renders: the stars and the search field's magnifier centred
    # between the native checkmark column's lines. Measured on the drawn ink, not on frames.
    def test_stars_are_centred_in_the_checkmark_column_in_pixels(self) -> None:
        self.check("pixels: the stars' ink is centred between the native checkmark column's lines (18.5 +-0.5 pt)")

    def test_search_magnifier_is_centred_in_the_checkmark_column_in_pixels(self) -> None:
        self.check("pixels: the search field's magnifier is centred in the same column (18.5 +-0.5 pt)")

    # Sight tests: "Instead of the eye the picture emoji, not larger than the rest of the text
    # in the row, with a space before the size text", and later: the emoji is much smaller than
    # the same emoji copied as text. An image row starts with U+1F5BC U+FE0F in the text
    # column, one space, then the size text; the emoji looks exactly like the same emoji at the
    # start of a copied text clipping (same font, size, baseline and colours).
    def test_image_rows_start_with_the_picture_emoji_and_one_space_before_the_size_text(self) -> None:
        self.check("image rows start with the picture emoji and one space before the size text; text rows are unchanged")

    def test_image_rows_have_no_quick_look_eye(self) -> None:
        self.check("no row has an image view: the Quick Look eye is gone")
        source = PANEL.read_text()
        for gone in ("NSImageNameQuickLookTemplate", "kListImageIconX", "kListImageTitleX", "iconView"):
            self.assertNotIn(gone, source)

    def test_image_rows_text_starts_in_the_text_rows_column(self) -> None:
        self.check("image rows' text starts in the text rows' column: the same text field frame",
                   "pixels: the picture emoji starts where the text rows' ink starts (+-0.75 pt) and is in colour")

    def test_image_rows_emoji_is_the_same_run_as_the_emoji_of_a_copied_text_clipping(self) -> None:
        self.check("an image row's emoji is the run of the same emoji at the start of a copied text clipping: same font, size and baseline")

    def test_image_rows_emoji_has_the_ink_of_the_same_emoji_in_a_text_row_in_pixels(self) -> None:
        self.check("pixels: an image row's emoji has the ink of the same emoji in a text row (+-0.25 pt), the size text after it the same baseline")

    def test_rows_with_the_emoji_are_not_cut_off_and_keep_the_row_pitch(self) -> None:
        self.check("pixels: rows with the emoji are not cut off, keep a text row's text field and the list's 24 pt row pitch")

    def test_image_rows_emoji_keeps_its_colours_when_highlighted_and_the_text_follows_the_highlight(self) -> None:
        self.check("highlighted image row: the emoji keeps its colours, the size text is in the selected-menu-item colour",
                   "highlighted: an image row's emoji keeps the ink and colours of the same emoji in a text row, both texts in the selected-menu-item colour")

    def test_image_rows_truncate_at_the_end_and_row_views_are_reused_correctly(self) -> None:
        self.check("image rows: a long size text is cut at the end inside the text field, the emoji stays at the start",
                   "image rows: the emoji has no font or baseline of its own, also after the highlight; a reused row view shows each kind right")

    def test_voiceover_reads_the_size_of_an_image_row_and_not_the_emoji(self) -> None:
        self.check("VoiceOver reads an image row as \"Image 1280 by 720\"",
                   "a text row's label stays its text",
                   "VoiceOver's tree: an image row's cell and its text read \"Image 1280 by 720\", the emoji in no label or value",
                   "a favorite image row has the emoji and the filled star and reads \"Image 1280 by 720, Favorite\"",
                   "undo returns the starred image to the history",
                   "an arrow-key move onto an image row announces \"Image 1280 by 720\", without the emoji")

    def test_search_matches_the_size_text_not_the_emoji_and_the_drag_file_name_is_unchanged(self) -> None:
        # Guards: these hold on the parent too and must keep holding.
        self.check("searching the size text finds the image rows",
                   "searching the emoji finds nothing: it is not part of the searchable text",
                   "Esc clears the emoji search",
                   "the promised file name has no emoji and no size text, as before")

    def test_command_delete_forward_delete_and_undo(self) -> None:
        self.check("Cmd-Delete deletes the highlighted row", "the highlight stays on the row that moved up",
                   "Cmd-Z restores it, highlighted", "Cmd-Forward-Delete deletes too", "and Cmd-Z restores")

    def test_typing_filters_and_escape_clears_search_first(self) -> None:
        self.check("typing goes to the search field", "search filters, only the matches are listed",
                   "first match highlighted", "Cmd-Delete in the search field deletes the row, not the search text",
                   "undo while searching", "Esc clears the search first, the list stays open")

    def test_search_shrinks_the_list_to_its_matches_under_the_status_item(self) -> None:
        self.check("search with one match: list shrinks to that row",
                   "the shrunken panel keeps its top edge (anchored under the status item)",
                   "no match: one row is left for the note", "the row says No Matches", "top edge still in place",
                   "clearing the search restores the opening height", "many matches: at most the opening height",
                   "12 matches: 12 rows tall", "deleting a match shrinks it by its row", "undo grows it back",
                   "and Esc restores the opening height")

    def test_star_click_toggles_without_closing(self) -> None:
        self.check("the pointer's row shows its star", "star click keeps the list open", "starred clipping is the top favorite",
                   "its star is filled now",
                   "star off returns it to its time position", "two undos revert star and star off")

    def test_return_chooses_and_closing_rules(self) -> None:
        self.check("Return closes the list", "Return chooses the highlighted clipping", "closing drops the undo steps",
                   "Esc with an empty search closes", "losing key status (click outside) closes",
                   "another app becoming active closes", "a Space switch closes", "Cmd-, runs Preferences… and closes",
                   "every opening is closed once")

    def test_keyboard_reaches_the_command_rows(self) -> None:
        self.check("Down from the last entry highlights the first command row",
                   "the highlighted command row draws the highlight",
                   "the entry row lost its highlight: one highlight at a time", "Down skips the disabled command row",
                   "Down skips the separator between the commands", "Down on the last command stays there",
                   "Up skips the disabled row back to the first command", "Up from the first command returns to the last entry",
                   "Page Up from a command goes back into the list", "no match: Down goes straight to the commands",
                   "typing drops the command highlight", "no match: Up goes to the last command",
                   "Esc clears the search and the highlight",
                   "command rows keep their VoiceOver label and menu-item role",
                   "the pointer on a command row takes the highlight from the entry",
                   "leaving the command row drops its highlight",
                   "the pointer on an entry takes the highlight from the command row",
                   "a disabled command row takes no highlight",
                   "Return runs the highlighted command and closes the list", "every opening is closed once (commands)")

    def test_voiceover_presses_rows_and_hears_highlight_moves(self) -> None:
        self.check("the panel has a VoiceOver label", "an arrow-key move announces the highlighted row (a favorite says so)",
                   "the highlighted row is the selected element", "the next move moves the selection and is announced",
                   "a history row is announced by its text alone",
                   "pointer moves are not announced", "moving onto a command row announces and selects it",
                   "the command row is deselected when the highlight leaves", "a Page Up move is announced",
                   "VoiceOver's press on an entry row pastes that clipping and closes the list",
                   "every opening is closed once (VoiceOver)")

    def test_voiceover_names_the_search_field_and_gets_one_row_per_clipping(self) -> None:
        self.check("the search field has an accessible name besides its placeholder",
                   "one table row per clipping, no headings",
                   "entry rows stay AppKit's table rows with their text; a favorite's says Favorite",
                   "every opening is closed once (rows)")

    def test_panel_source_has_no_section_headers(self) -> None:
        source = PANEL.read_text()
        for token in ("FlycutListHeaderView", "FlycutListSectionElement", "AXHeading", "rowOfSectionHeader"):
            self.assertNotIn(token, source)
        model = (ROOT / "FlycutClipList.h").read_text() + (ROOT / "FlycutClipList.m").read_text()
        for token in ("FlycutClipListRowHeader", "FlycutClipListRowSeparator"):
            self.assertNotIn(token, model)

    def test_command_rows_follow_their_menu_items_while_open(self) -> None:
        self.check("a command retitled while the list is open shows the new title (text and VoiceOver)",
                   "a command disabled while the list is open is shown disabled", "and the keyboard skips it",
                   "a highlighted command that gets disabled loses the highlight", "enabled again, the row is shown enabled",
                   "a title the delegate sets while the list opens is shown",
                   "every opening is closed once (live commands)")

    def test_clipping_landing_while_open_is_listed_keeping_highlight_and_scroll(self) -> None:
        self.check("a clipping that lands while the list is open is listed at once", "the highlight stays on the same clipping",
                   "the list keeps its scroll position", "arrows go on from the kept highlight",
                   "while searching, only a matching new clipping is added", "every opening is closed once (refresh)")

    def test_press_drag_release_chooses_like_a_menu(self) -> None:
        self.check("dragging over a row highlights it; releasing outside the list leaves it open",
                   "releasing on a row chooses that row and closes the list", "the same with the right button",
                   "releasing on a disabled command row does nothing", "releasing on a command row runs it",
                   "a long drag: each event is released before the next one is read",
                   "every opening is closed once (press-drag-release)")

    def test_status_item_press_drag_release_never_starts_a_drag(self) -> None:
        self.check("press, drag and release from the status item never starts a drag session")

    def test_a_click_pastes_and_moving_past_the_drag_threshold_drags_the_row(self) -> None:
        self.check("a press released within the drag threshold pastes the row, as a click",
                   "moving past the drag threshold drags the row from the list instead of pasting it",
                   "starting a drag changes no list", "sideways too",
                   "the dragged row is not highlighted; its drag image shows its title in the normal colour",
                   "other applications and the Finder may only copy a dragged row; inside the list it moves")

    def test_a_dragged_row_carries_its_text_rich_text_or_a_promised_image_file(self) -> None:
        self.check("a text row's drag carries its text, RTF and HTML",
                   "text is dragged as text, no file (the Finder makes its own clipping file of it)",
                   "an image row's drag promises a PNG file and carries the stored PNG data",
                   "the promised file is named \"Flycut Image <date> at <time>.png\"",
                   "the Finder's file gets exactly the stored image bytes", "the file is written off the main queue",
                   "dragging rows out changes no list and deletes no image")

    def test_drops_in_the_list_reorder_favorites_and_make_history_rows_favorites(self) -> None:
        self.check("a dragged favorite can be dropped anywhere in the favorites block",
                   "but not in the history block: the table shows no drop indicator there",
                   "a drag from another application is not taken", "the rows make room for a drop (gap feedback)",
                   "dropping the second favorite on the first row's place makes it the first favorite; the list stays open",
                   "after the drop every row is shown, in the new order",
                   "after pressing and dragging rows typing still goes to the search field", "Cmd-Z undoes the move",
                   "a dragged history row can be dropped into the favorites block only",
                   "a history row dropped between two favorites becomes a favorite there, with its filled star",
                   "Cmd-Z returns it to its place in the history",
                   "a favorite dropped on the history stays a favorite (only the star unstars)")

    def test_a_drop_elsewhere_closes_the_list_and_a_cancelled_drag_keeps_it(self) -> None:
        self.check("a cancelled drag leaves the list open with every row shown",
                   "a drop inside the list's own panel (its search field) keeps the list open",
                   "a drop in another application or the Finder closes the list; nothing is pasted, moved or deleted",
                   "every opening is closed once (drag)")

    def test_voiceover_moves_favorites_up_and_down(self) -> None:
        self.check("favorites have Move Up and Move Down actions where they can move; history rows have none",
                   "Move Down moves the favorite one place down and keeps it highlighted", "Cmd-Z undoes it")

    def test_trash_button_deletes_its_row_and_undo_restores_it(self) -> None:
        self.check("the trash button deletes its row and keeps the list open", "and Cmd-Z brings the row back")

    def test_open_geometry_below_the_status_item(self) -> None:
        self.check("the panel starts at the status item's left edge, 4 pt below the menu bar",
                   "near the right edge the panel keeps 8 pt from it", "left of the visible frame it keeps 8 pt from the left edge",
                   "on a display left of the main one the same rules apply in its coordinates",
                   "the top edge never goes above the visible frame (a taller menu bar, the notch)",
                   "a status item lower than the visible top: 4 pt below the item",
                   "the list gets the room down to 8 pt above the Dock, without search field and commands")
        # The real opening uses exactly this geometry.
        source = PANEL.read_text()
        start = source.index("- (void)openBelowRect:(NSRect)anchorRect onScreen:(NSScreen *)screen\n{")
        body = source[start:source.index("\n}\n", start)]
        self.assertIn("maximumListHeightBelowRect:anchorRect visibleFrame:visible chromeHeight:chrome", body)
        self.assertIn("panelOriginForSize:[panel frame].size belowRect:anchorRect visibleFrame:visible", body)

    def test_flycut_never_activates_and_nothing_is_shown(self) -> None:
        self.check("Flycut never became active", "no activation call", "the panel was never ordered on screen")
        self.assertTrue(all(not step["app_active"] for step in self.report["steps"]))

    def test_panel_source_never_activates_the_app(self) -> None:
        source = PANEL.read_text()
        for token in ("activateIgnoringOtherApps", "activateWithOptions", "NSApp activate", "unhide"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
