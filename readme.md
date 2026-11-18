# Flycut
<a href="https://github.com/haad/Flycut/releases"><img src="http://a3.mzstatic.com/us/r1000/047/Purple/fb/53/f2/mzi.mcaxwyjm.175x175-75.png" /></a>
<a href="https://macdownload.informer.com/flycut/"><img src="award-2021.png" /></a>
<a href="https://macdownload.informer.com/flycut/"><img src="award-2022.png" /></a>
<br />

I have reimplemented Flycut with Swift [CLipsmith](https://github.com/haad/Clipsmith). 

Flycut is a clean and simple clipboard manager for developers. Based on the open source app [Jumpcut](https://github.com/snark/jumpcut).

This is an actively maintained fork, updated to work on the latest macOS versions.

Every time you copy a code piece, Flycut stores it in history. Later, you can paste it using Shift-Command-V even if you have something different in your current clipboard. You can change the hotkey and other settings in preferences.

## Install

1. Download the latest `.dmg` from [Releases](https://github.com/haad/Flycut/releases)
2. Open the `.dmg` and drag Flycut to your Applications folder
3. Launch Flycut — macOS will show a warning because the app is not from the App Store
4. Go to **System Settings -> Privacy & Security**, scroll down and click **Open Anyway**
5. Launch Flycut again
6. Go to **System Settings -> Privacy & Security -> Accessibility** and enable Flycut — this is required for Flycut to paste on your behalf

## Keyboard Shortcuts

### Global

| Shortcut | Action |
|----------|--------|
| Shift+Command+V | Open clipboard history (bezel) |
| Control+Shift+S | Open search window |

### Bezel Navigation

| Shortcut | Action |
|----------|--------|
| Up/Left Arrow or K | Move to newer item |
| Down/Right Arrow or J | Move to older item |
| Home | Jump to most recent item |
| End | Jump to oldest item |
| Page Up / Page Down | Move 10 items forward/back |
| 1-9, 0 | Jump to position (0 = 10th) |
| Scroll Wheel | Navigate history |

### Bezel Actions

| Shortcut | Action |
|----------|--------|
| Return | Paste selected item |
| Fn+Return | Move item to top of history |
| Backspace/Delete | Delete selected item |
| Escape | Close without pasting |
| Double-Click | Paste item |
| Command+, | Open preferences |
| S | Save item to Desktop |
| Shift+S | Save to Desktop and delete |
| F | Toggle favorites store |
| Shift+F | Move item to favorites |
| Space | Pin bezel open (sticky mode) |
| Right-Click | Pin bezel open (sticky mode) |

### Menu Bar

| Shortcut | Action |
|----------|--------|
| Click menu icon | Open the clipping list |
| Option+Click menu icon | Toggle clipboard tracking on/off |

### Menu Bar List

The list has a search field at the top, then your favorites (each with a filled star at the left) and your clipboard history in one list, and the menu commands at the bottom. The highlighted item shows a trash icon at the right edge and, if it is not a favorite, a star outline at the left: click the star to add the item to or remove it from the favorites, or the trash to delete it. Drag an item into another app or the Finder to drop its content there, drag favorites to reorder them, or drag a history item into the favorites to make it a favorite.

| Shortcut | Action |
|----------|--------|
| Type | Filter favorites and history |
| Up/Down Arrow | Move the highlight (items, then commands) |
| Page Up / Page Down | Move the highlight one page |
| Return or Click | Paste item or run command |
| Command+Delete | Delete highlighted item |
| Command+Z | Undo delete, star change or moved favorite |
| Escape | Clear search, then close the list |

## Sharing With Other Accounts

Turn on "Share copied text with these accounts:" in Preferences > General and check the accounts to share with, in each account that should take part; text you copy then also shows up in Flycut in the accounts that checked each other. It is off by default; passwords Flycut recognizes and copies marked as private are never shared. See the [Help File](help.md) for details.

## Why Flycut?

Flycut is a free, open-source alternative to paid clipboard managers for macOS:

- [Maccy](https://maccy.app) - $9.99 on the App Store
- [Paste](https://pasteapp.io) - $29.99/year subscription
- [PastePal](https://indiegoodies.com/pastepal) - $17.99
- [PasteBot](https://tapbots.com/pastebot/) - $12.99

Flycut provides the same core clipboard history functionality with keyboard-driven navigation, search, and favorites — completely free.

## Documentation

See the full [Help File](help.md) for more details.

## Develop

**Contributors:**
Check the list of contributors [here](https://github.com/haad/Flycut/graphs/contributors)

**License:**
MIT
