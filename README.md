FULLY CLAUDE CODDED
# Brawlhalla True Random Picker

Tracks played legends, picks a random unplayed one, and draws a transparent overlay. 
It never clicks or sends input to the game.

## Features
- **Click-through overlay:** Game works perfectly underneath.
- **Native hotkeys:** Uses Win32 API. No admin rights, no background hooks.
- **DPI Aware:** Doesn't break or look blurry on 125%/150% Windows scaling.
- **Cursor Tracking:** Scans the screen to find your blinking "P1" cursor and draws a visual route to your next pick.
- **Legend Exclusions:** Right-click any legend to permanently exclude it from the random pool.
- **Auto-Detect:** Automatically detects and adds new legends when they are released (if enabled).
- **Pink aesthetic:** Because serious grinders need pink sparkles.

## Requirements
- Python 3.8+
- `Pillow` (`pip install pillow`) – *Highly recommended*. Required for cursor scanning, auto-detect, and character portraits. (Script runs without it, but with limited functionality).

## Hotkeys (Default)
- `F4`: Skip current pick (marks it unplayed and draws a new random one)
- `F5`: Find my cursor (scans screen and highlights your current position)
- `F6`: Show overlay
- `F7`: Pick next legend (scans cursor, highlights pick, marks as played)
- `F8`: Hide overlay
- `F9`: Undo last pick
- `F10`: Reset all progress (press twice to confirm)

## How to use
1. Run `python brawl_picker.py`.
2. Open the **Settings** tab.
3. Calibrate the grid. The default is measured on a 1366x768 screenshot. Adjust `left`, `top`, `right`, `bottom`, `cols`, `rows`, and `legends` until the preview boxes match your game screen.
4. (Recommended) Click **Import portraits** and select a screenshot of your character select screen. This loads the icons and enables accurate cursor scanning.
5. Launch Brawlhalla in **Windowed Fullscreen** or **Borderless** mode.
6. Press `F6` to show the overlay, `F7` to get your next legend.
7. Right-click any legend in the grid to exclude/include it from the random pool.

## Notes
- Slot 0 (Random) is ignored.
- State is saved in `brawl_state.json`. Delete it for a hard reset.
- Excluded legends are saved separately and can be bulk-cleared in Settings.
