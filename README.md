FULLY CLAUDE CODDED
# Brawlhalla True Random Picker

Tracks played legends, picks a random unplayed one, and draws a transparent overlay. 
It doesn't click for you. It just tells you who to play next.

## Features
- **Click-through overlay:** Game works perfectly underneath.
- **Native hotkeys:** Uses Win32 API. No admin rights, no background hooks.
- **DPI Aware:** Doesn't break or look blurry on 125%/150% Windows scaling.
- **Pink aesthetic:** Because serious grinders need pink sparkles.

## Requirements
- Python 3.8+
- `Pillow` (Optional: `pip install pillow` if you want actual character portraits instead of colored squares).

## Hotkeys (Default)
- `F6`: Show overlay
- `F7`: Pick random unplayed legend (highlights it, marks as played)
- `F8`: Hide overlay
- `F9`: Undo last pick
- `F10`: Reset all progress (press twice to confirm)

## How to use
1. Run `python brawl_picker.py`.
2. Open **Settings**.
3. Calibrate the grid. The default is measured on a 1366x768 screenshot. Adjust `left`, `top`, `right`, `bottom`, `cols`, `rows`, and `legends` until the preview boxes match your game screen.
4. (Optional) Click **Import portraits** and select a screenshot of your character select screen to load the icons.
5. Go to Brawlhalla. Press `F6` to see the grid, `F7` to get your next legend.

## Notes
- Slot 0 (Random) is ignored.
- State is saved in `brawl_state.json`. Delete it for a hard reset.
