### Flycut Help

**Basics**

Copy the same way as always.

Paste the same way as always.

Press the Main Hotkey (Shift-Command-V, by default) to access your clipboard history. Or just click the Flycut icon in the menu bar.

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

Press the Search Hotkey (Control-Shift-S by default) to open the search window. Type to filter your clipboard history, use the arrow keys to navigate results and press Return to paste the selected item. You can change or clear the shortcut under "Search clipboard hotkey:" in Preferences.

**Text Formatting**

Flycut preserves the formatting (RTF and HTML) of copied text, so pasting an older clipping into a rich text editor keeps its bold, fonts, links, and colors. Plain-text-only targets are unaffected – they always receive the plain text. RTF and HTML are each kept up to 1 MiB; a larger format is dropped, and the plain text is always kept. Formatting data can contain more than the visible text, such as hidden markup or links; previews and search show the plain text only.

To disable this and store plain text only, run:

    defaults write com.generalarcade.flycut preserveTextFormatting -bool NO

**Menu Bar List**

Click the Flycut icon in the menu bar to open the clipping list. It has a search field at the top, then one list that scrolls: your favorites first, then your clipboard history. The commands are at the bottom: Clear All, Merge All, Pause Clipboard Tracking, Preferences…, About Flycut and Quit. Clear All asks first and clears the clipboard history only, never your favorites; Merge All merges the history into one entry.

Click an item to paste it into the app you were using; Flycut stays in the background. If "Menu selection pastes" is turned off in Preferences, clicking copies the item instead. While a Flycut window such as Preferences is in front, choosing an item here, in the Bezel or in the search window only copies it, and that window stays open. As in a menu, you can also press the icon, drag to an item and release. Pasting from the history moves the item to the top of the history if "Move pasted item to top of stack" is on in Preferences, as Enter does in the Bezel; your favorites keep their order.

A favorite shows a filled star at the left, where a menu shows a checkmark. The highlighted item also shows a trash icon at the right edge and, if it is not a favorite, the outline of a star at the left. Click the star to move the item to the favorites or to remove it from them; the list stays open, and a removed favorite goes back to its place in the history. Click the trash to delete the item; there is no confirmation.

Drag an item out of the list into another app or the Finder to drop its content there; a picture becomes an image file in the Finder, and text becomes a text clipping. The item stays in the list. Drag a favorite up or down to reorder your favorites, or drag a history item into the favorites to make it a favorite at that place; the history itself stays in time order. If you have no favorites yet, dropping an item at the very top makes it the first one.

Type to filter both lists. Click the icon again, click outside the list or switch to another app to close it.

"Display in menu:" in Preferences sets how many rows the list shows before it scrolls: 20 by default, at most as many as fit on the screen. The list always holds all your clippings.

You can also Option-Click the Flycut menu icon to disable or reenable clipboard tracking, in case you are copying sensitive information such as passwords.

**Menu Bar List Keystrokes**

**Up Arrow** and **Down Arrow**: Move the highlight through the items and on into the commands at the bottom.

**Page Up** and **Page Down**: Move the highlight one page.

**Return**: Paste the highlighted item, or run the highlighted command.

**Command-Delete** or **Command-Forward-Delete**: Delete the highlighted item, without a confirmation.

**Command-Z**: Undo deletes, star changes and moved favorites, as long as the list is open.

**Esc**: Clear the search. If the search field is empty, close the list.

**Preferences Panel**

The preferences panel allows you to customize settings including:

- Main and Search hotkeys
- Number of clippings to remember, and how many rows the menu bar list shows
- Bezel appearance (size, position, transparency)
- Sticky bezel mode
- Removing duplicate clippings
- Skipping password manager entries
- Sharing copied text with other accounts on this Mac

A setting that differs from its factory value shows a small round arrow next to it (tooltip "Restore Default"). Click the arrow to go back to the default; for the two "Save … to:" folders that is the Desktop. The arrow disappears once the default is back.

The two "Save … to:" buttons show the name of their folder; a long name is shortened in the middle ("…"). Point at a button to see the folder's full path.

Command-W closes Preferences, like its close button. While a hotkey field is waiting for a new shortcut, Command-W becomes that shortcut instead.

To change Remember, Display in menu or Favorites, click the number and type a new one (up to three digits). A typed number is applied when you press Return or Tab, click into another field, switch to another pane or close Preferences; Escape brings back the previous one. A number outside the allowed range becomes the nearest allowed one: Remember and Favorites take 10 to 999, Display in menu 5 up to the Remember number.

**Sharing With Other Accounts on This Mac**

Flycut can pass copied text between the accounts of one Mac. Turn on "Share copied text with other accounts on this Mac" under "Other accounts on this Mac:" in the General pane, in every account that should take part; it is off by default. Text you copy then also goes to Flycut in each other account on this Mac that has turned it on too, and shows up in its clipboard history. When you switch to such an account, the newest text that arrived while you were away is on its clipboard, ready to paste. A copy that waited for more than a day is dropped.

Only text is shared, with its formatting (up to 1 MB in all); pictures are not. Nothing is sent while clipboard tracking is paused, while "Diagnostics: save data type, not content" is on, or while your account is not the one in front. Passwords Flycut recognizes are never shared: copies from password managers and password fields, copies marked as private or temporary, and text that the "by length & complexity" check (under "Don't save passwords") takes for a password. These checks always apply to sharing, even when they are turned off for your own history. Text that only looks ordinary, such as a password typed into a document, is shared like any other text.

The copies for an account wait in a hidden folder in /Users/Shared, in one subfolder per sending account; another account can only add its own copies there, and Time Machine skips the folder. Any other account on this Mac can see that the folder exists and which accounts may add copies to it, but not the copies; an account that sends to you can also tell how many copies from the others wait there and when they came or were taken in. Turning the option off deletes your folder with everything in it (if it cannot be deleted at once, Flycut tries again every minute, also after it restarts).
