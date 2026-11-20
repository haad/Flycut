### Flycut Help

**Basics**

Copy the same way as always.

Paste the same way as always.

Press the Main Hotkey (Shift-Command-V, by default) to access your clipboard history. Or just use the Flycut menu in the menu bar.

**The Bezel**

The Bezel is what you see when you press the Main Hotkey. It's the semi-transparent box that appears in the middle of your screen, showing you your clipboard history. Use the arrow keys to step through your history.

If the "sticky bezel" option is enabled, there is no need to hold the command key. When you find something you want to paste, press Return and it is pasted while the Bezel closes automatically. If you don't want to paste, just press the Esc key.

**Bezel Keystrokes**

Here's a complete list of keys you can use in the Bezel.

**Navigation:**

**Down Arrow**, **Right Arrow**, or **J**: Move backward in your clipboard history (older items).

**Up Arrow**, **Left Arrow**, or **K**: Move forward in your clipboard history (newer items).

**Home**: Move to the most recent item in your clipboard history.

**End**: Move to the least recent item in your clipboard history.

**Page Down**: Move backward ten positions in your clipboard history.

**Page Up**: Move forward ten positions in your clipboard history.

**1** through **9** and **0**: Jump to the clipboard history position indicated by the number, or position 10 for zero.

**Scroll Wheel**: Navigate through clipboard history.

**Actions:**

**Return**: Paste the clipboard history item currently displayed, closing the Bezel.

**Esc**: Close the Bezel without pasting, preserving bezel position in the history.

**Enter** (Fn-Return): Copy the item currently displayed to the clipboard, closing the Bezel. If "Move pasted item to top of stack" is on in Preferences, a clipboard history item also moves to the front of the history; a favorite always keeps its place.

**Backspace** or **Delete**: Delete the clipboard history item currently displayed, closing the Bezel.

**Double-Click**: Paste the item under the cursor.

**Command-,**: Display the Flycut preferences panel.

**Saving and Favorites:**

**S**: Save the clipboard history item currently displayed to a file on the Desktop, closing the Bezel. e.g. "Desktop/Clipping 2015-07-15 at 08.35.10.txt"

**Shift-S**: Save the item to a file and delete it from the clipboard history.

**F**: Switch between the main clipboard history store and the favorites store. The favorites store appears in the Bezel with a yellow tint and a star after the counter at the bottom ("1 of 2 ★"), and works in the same way as the main clipboard history store, except that pasting never changes the order of your favorites: "Move pasted item to top of stack" in Preferences applies to the clipboard history only.

**Shift-F**: Save the clipboard history item currently displayed to the favorites store, deleting it from the main clipboard history store and closing the Bezel. A new favorite goes to the top of the favorites. If the favorites are full (the Favorites number in Preferences), it drops the last one; with the Favorites box of "Save forgotten items to:" checked, as it is by default, that one is saved to a file first. If "Remove duplicates" is on in Preferences and the item already is a favorite, it replaces that favorite in its place instead of adding a second copy.

**Space**: Pin the bezel open so it stays visible after releasing modifier keys. You can then browse freely and press Return to paste or Escape to cancel. While the bezel is pinned, its counter says "(pinned)".

**Right-Click**: Same as Space — pins the bezel open.

**Search Window**

Press the Search Hotkey (Control-Shift-S by default) to open the search window. Type to filter your clipboard history, use the arrow keys to navigate results and press Return to paste the selected item. You can change or clear the shortcut under "Search clipboard hotkey" in Preferences.

**Text Formatting**

Flycut preserves the formatting (RTF and HTML) of copied text, so pasting an older clipping into a rich text editor keeps its bold, fonts, links, and colors. Plain-text-only targets are unaffected – they always receive the plain text. RTF and HTML are each kept up to 1 MiB; a larger format is dropped, and the plain text is always kept. Formatting data can contain more than the visible text, such as hidden markup or links; previews and search show the plain text only.

To disable this and store plain text only, run:

    defaults write com.generalarcade.flycut preserveTextFormatting -bool NO

**Menu Features**

The Flycut menu allows you to select from the most recent items in the main clipboard history store, clear all of them, merge them all into one entry, or access the preferences panel. You can also Option-Click the Flycut menu icon to disable or reenable clipboard tracking, in case you are copying sensitive information such as passwords.

**Preferences Panel**

The preferences panel allows you to customize settings including:

- Main and Search hotkeys
- Number of clippings to remember and display
- Bezel appearance (size, position, transparency)
- Sticky bezel mode
- Removing duplicate clippings
- Skipping password manager entries

A setting that differs from its factory value shows a small round arrow next to it (tooltip "Restore Default"). Click the arrow to go back to the default; for the two "Save … to:" folders that is the Desktop. The arrow disappears once the default is back.

To change Remember, Display in menu or Favorites, click the number and type a new one (up to three digits). A typed number is applied when you press Return or Tab, click into another field, switch to another pane or close Preferences; Escape brings back the previous one. A number outside the allowed range becomes the nearest allowed one: Remember and Favorites take 10 to 999, Display in menu 5 up to the Remember number.
