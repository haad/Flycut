#!/usr/bin/env python3
"""Native tests for the data behind the menu-bar list.

The fixture (Tests/Fixtures/MenuListModel.m) compiles the real FlycutClipping,
FlycutStore, FlycutOperator and FlycutClipList sources. Only OS boundaries are
doubles: in-memory user defaults, an image store that records deletions in memory
and an autosave export that is recorded instead of written. Nothing is launched,
no pasteboard, preferences domain or Application Support data is read or written.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "Tests/Fixtures/MenuListModel.m"


class MenuListModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="flycut-menu-list-model-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.artifacts = pathlib.Path(os.environ.get("FLYCUT_TEST_ARTIFACTS") or cls.temporary.name)
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.binary = cls.artifacts / "MenuListModel"
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-I", str(ROOT), "-I", str(ROOT / "FlycutEngine"),
                   str(FIXTURE), "-framework", "Cocoa", "-o", str(cls.binary)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
        (cls.artifacts / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise AssertionError(f"Native fixture compile failed ({build.returncode}):\n{build.stderr}")

    def run_case(self, case: str) -> None:
        run = subprocess.run([str(self.binary), case], cwd=ROOT, text=True,
                             capture_output=True, timeout=30)
        output = run.stdout + run.stderr
        (self.artifacts / f"{case}.log").write_text(output)
        print(output, end="")
        self.assertEqual(run.returncode, 0, output)

    # Rows and search
    def test_favorites_on_top_then_whole_history_independent_of_bezel_store(self) -> None:
        self.run_case("rows-order")

    def test_an_empty_list_leaves_no_trace(self) -> None:
        self.run_case("rows-empty-lists")

    def test_search_filters_both_lists_with_favorite_matches_first(self) -> None:
        self.run_case("search")

    # Star, star off, delete
    def test_star_moves_history_clipping_to_top_of_favorites(self) -> None:
        self.run_case("star-to-top")

    def test_star_with_full_favorites_drops_oldest_as_shift_f_and_undo_restores(self) -> None:
        self.run_case("star-full-favorites")

    def test_star_with_remove_duplicates_takes_the_place_of_the_equal_favorite(self) -> None:
        self.run_case("star-remove-duplicates-equal")

    def test_star_off_returns_to_old_time_position(self) -> None:
        self.run_case("unstar-time-position")

    def test_star_off_into_unsorted_history_goes_below_newer_entries(self) -> None:
        self.run_case("unstar-unsorted")

    def test_star_off_without_timestamp_goes_to_top(self) -> None:
        self.run_case("unstar-unknown-time")

    def test_star_off_into_full_history_never_drops_the_returning_entry(self) -> None:
        self.run_case("unstar-full-history-oldest")

    def test_star_off_into_full_history_keeps_time_position(self) -> None:
        self.run_case("unstar-full-history-middle")

    # "Remove duplicates" on: the insert drops equal history entries first
    def test_star_off_with_remove_duplicates_replaces_equal_entry_at_time_position(self) -> None:
        self.run_case("unstar-remove-duplicates-equal")

    def test_star_off_with_remove_duplicates_ignores_a_newer_equal_entry(self) -> None:
        self.run_case("unstar-remove-duplicates-newer")

    def test_star_off_with_remove_duplicates_drops_an_older_equal_entry(self) -> None:
        self.run_case("unstar-remove-duplicates-older")

    def test_star_off_with_remove_duplicates_into_full_history_drops_nothing(self) -> None:
        self.run_case("unstar-remove-duplicates-full")

    def test_star_off_without_remove_duplicates_keeps_both_equal_entries(self) -> None:
        self.run_case("unstar-duplicates-kept-when-off")

    def test_delete_removes_from_own_list_without_export(self) -> None:
        self.run_case("delete-not-exported")

    # Undo, image files, saving
    def test_undo_reverts_several_steps_in_reverse_order(self) -> None:
        self.run_case("undo-multi-step")

    def test_undo_is_refused_when_a_capture_landed_meanwhile(self) -> None:
        self.run_case("undo-refused-after-external-change")

    def test_image_files_are_deleted_only_when_the_list_closes(self) -> None:
        self.run_case("image-deletion-deferred")

    def test_closing_the_list_drops_undo(self) -> None:
        self.run_case("session-drops-undo")

    def test_changes_are_saved_and_undo_data_is_never_written(self) -> None:
        self.run_case("save-after-change")

    # displayNum as list height
    def test_display_num_is_the_list_height_in_rows(self) -> None:
        self.run_case("list-height")

    # Dragging rows inside the list: favorites can be reordered, a history clipping
    # dropped into the favorites becomes a favorite there, the history keeps its order
    def test_drop_reorders_favorites_as_one_undo_step_each(self) -> None:
        self.run_case("drop-favorite-reorder")

    def test_drop_of_a_favorite_into_the_history_is_refused_and_does_not_unstar(self) -> None:
        self.run_case("drop-favorite-refused-in-history")

    def test_drop_of_a_history_clipping_into_the_favorites_makes_it_a_favorite_there(self) -> None:
        self.run_case("drop-history-into-favorites")

    def test_drop_below_the_last_favorite_appends_it(self) -> None:
        self.run_case("drop-history-at-end-of-favorites")

    def test_history_cannot_be_reordered(self) -> None:
        self.run_case("drop-history-refused-in-history")

    def test_drop_into_full_favorites_drops_the_last_as_the_star_does(self) -> None:
        self.run_case("drop-history-full-favorites")

    def test_drop_with_remove_duplicates_counts_without_the_equal_favorite(self) -> None:
        self.run_case("drop-history-remove-duplicates")

    def test_drop_while_searching_goes_next_to_the_shown_favorite(self) -> None:
        self.run_case("drop-while-searching")

    def test_dropped_order_is_saved_with_the_favorites_store(self) -> None:
        self.run_case("drop-persists")

    def test_drop_of_an_unlisted_clipping_is_refused(self) -> None:
        self.run_case("drop-refuses-unlisted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
