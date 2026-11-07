"""
Brawlhalla Picker - true-random legend tracker (Windows)

Tracks which legends you've played, then highlights a random unplayed one on a
transparent, click-through overlay. It never clicks or sends input to the game.

Install:   pip install pillow     (optional: portraits; hotkeys use the native Windows API)
Run:       python brawl_picker.py
Game:      set Brawlhalla to Windowed Fullscreen / Borderless.
"""
import ctypes
import json
import math
import os
import queue
import random
import shutil
import threading
import time
import traceback
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

# Make Tk use real pixels on scaled (125% / 150%) displays so the overlay lines up.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "brawl_state.json"
THUMB_DIR = APP_DIR / "thumbs"

# Grid measured on a 1366x768 screenshot; scaled to your actual screen.
DEFAULT_GRID = {"left": 228, "top": 118, "right": 1155, "bottom": 333,
                "cols": 18, "rows": 4, "legends": 63, "base_w": 1366, "base_h": 768}
DEFAULT_HOTKEYS = {"show": "f6", "pick": "f7", "hide": "f8", "undo": "f9", "reset": "f10"}
DEFAULT_OPTS = {"auto_hide": 0, "auto_reset": False}
HK_LABELS = {"show": "Show overlay", "pick": "Pick next legend", "hide": "Hide overlay",
             "undo": "Undo last pick", "reset": "Reset all (press twice)"}

# ---- Light pink palette ---------------------------------------------------- #
BG, PANEL, PANEL2, GRID_BG = "#fde8f0", "#fff7fa", "#f9dbe7", "#fde9f1"
EDGE, FG, MUTED = "#f1b9cf", "#4a2335", "#a77b90"
HOT, HOT2, ROSE_D, PLUM = "#ff4f9a", "#ff9ac4", "#d63a78", "#3a1626"
KEY = "#010101"  # overlay transparency key


def mix(c1, c2, t):
    """Blend two #rrggbb colours (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def rr(x0, y0, x1, y1, r):
    """Points for a rounded rectangle (use with create_polygon(..., smooth=True))."""
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
            x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


# --------------------------------------------------------------------------- #
class HotkeyManager:
    """Native Windows global hotkeys. Avoids a long-running low-level keyboard hook."""

    WM_HOTKEY, WM_QUIT, PM_NOREMOVE = 0x0312, 0x0012, 0x0000
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
    MODIFIERS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
                 "shift": MOD_SHIFT, "win": MOD_WIN, "windows": MOD_WIN}

    VK = {
        "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
        "pause": 0x13, "caps lock": 0x14, "esc": 0x1B, "escape": 0x1B,
        "space": 0x20, "page up": 0x21, "pageup": 0x21,
        "page down": 0x22, "pagedown": 0x22, "end": 0x23, "home": 0x24,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "print screen": 0x2C, "insert": 0x2D, "delete": 0x2E,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
        "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
        "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
        "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
        "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
        "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
        "z": 0x5A, "left windows": 0x5B, "right windows": 0x5C,
        "numpad 0": 0x60, "numpad 1": 0x61, "numpad 2": 0x62,
        "numpad 3": 0x63, "numpad 4": 0x64, "numpad 5": 0x65,
        "numpad 6": 0x66, "numpad 7": 0x67, "numpad 8": 0x68,
        "numpad 9": 0x69, "multiply": 0x6A, "add": 0x6B,
        "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
        "num lock": 0x90, "scroll lock": 0x91,
        "semicolon": 0xBA, "equals": 0xBB, "comma": 0xBC,
        "minus": 0xBD, "period": 0xBE, "slash": 0xBF,
        "grave": 0xC0, "left bracket": 0xDB, "backslash": 0xDC,
        "right bracket": 0xDD, "quote": 0xDE,
    }

    def __init__(self):
        if os.name != "nt":
            raise OSError("Native global hotkeys are supported by this version on Windows only.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class _MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD), ("pt", _POINT)]

        self.MSG = _MSG
        u = self.user32
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL
        u.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u.PeekMessageW.restype = wintypes.BOOL
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.PostThreadMessageW.restype = wintypes.BOOL
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread = None
        self.thread_id = None
        self._lock = threading.RLock()

    @classmethod
    def parse(cls, hotkey):
        """Convert a simple key or modifier+key chord into RegisterHotKey values."""
        parts = [p.strip().lower() for p in str(hotkey).split("+") if p.strip()]
        if not parts:
            raise ValueError("Hotkey is empty")
        modifiers, key_parts = 0, []
        for part in parts:
            if part in cls.MODIFIERS:
                modifiers |= cls.MODIFIERS[part]
            else:
                key_parts.append(part)
        if len(key_parts) != 1:
            raise ValueError("Use one key, optionally with Ctrl, Alt, Shift or Win")
        key = key_parts[0]
        if key.startswith("f") and key[1:].isdigit():
            n = int(key[1:])
            if not 1 <= n <= 24:
                raise ValueError(f"Unsupported key: {key}")
            vk = 0x70 + n - 1
        else:
            vk = cls.VK.get(key)
        if vk is None:
            raise ValueError(f"Unsupported key: {key}")
        return modifiers | cls.MOD_NOREPEAT, vk

    def start(self, hotkeys, on_press):
        """Replace current registrations and return a list of registration errors."""
        with self._lock:
            self.stop()
            ready = threading.Event()
            outcome = {"errors": []}
            thread = threading.Thread(target=self._message_loop,
                                      args=(dict(hotkeys), on_press, ready, outcome),
                                      name="BrawlhallaPicker-Hotkeys", daemon=True)
            self.thread = thread
            thread.start()
            if not ready.wait(2.0):
                self.stop()
                return ["The Windows hotkey message thread did not start in time."]
            return outcome["errors"]

    def _message_loop(self, hotkeys, on_press, ready, outcome):
        msg = self.MSG()
        registered = []
        self.thread_id = int(self.kernel32.GetCurrentThreadId())
        # Force creation of this thread's message queue before the UI posts WM_QUIT.
        self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
        try:
            for hotkey_id, (action, value) in enumerate(hotkeys.items(), start=1):
                try:
                    modifiers, vk = self.parse(value)
                except ValueError as exc:
                    outcome["errors"].append(f"{action}: {value!r} - {exc}")
                    continue
                ctypes.set_last_error(0)
                if self.user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered.append(hotkey_id)
                else:
                    error = ctypes.get_last_error()
                    reason = ("this combination is already used by another program"
                              if error == 1409 else f"Windows error {error}")
                    outcome["errors"].append(f"{action}: {value.upper()} - {reason}")
            ready.set()
            while True:
                if self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                    break
                if msg.message == self.WM_HOTKEY:
                    n = int(msg.wParam)
                    if 1 <= n <= len(hotkeys):
                        try:
                            on_press(list(hotkeys.keys())[n - 1])
                        except Exception:
                            pass  # never let a callback kill the message loop
        finally:
            for hotkey_id in registered:
                self.user32.UnregisterHotKey(None, hotkey_id)
            self.thread_id = None
            ready.set()

    def stop(self):
        thread, thread_id = self.thread, self.thread_id
        if thread and thread.is_alive() and thread_id:
            self.user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)
            thread.join(timeout=2.0)
        self.thread = None
        if thread and thread.is_alive():
            raise RuntimeError("Windows hotkey thread did not stop cleanly")


# --------------------------------------------------------------------------- #
class Store:
    """All persistent state: grid geometry, hotkeys, options, progress."""

    def __init__(self):
        self.grid = dict(DEFAULT_GRID)
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.opts = dict(DEFAULT_OPTS)
        self.played, self.history = set(), []
        self.last = None  # final legend of the previous cycle
        self._load()

    def _load(self):
        try:
            d = json.loads(DATA_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return
        self.grid.update(d.get("grid", d.get("cfg", {})))  # "cfg" = old prototype file
        self.hotkeys.update(d.get("hotkeys", {}))
        self.opts.update(d.get("opts", {}))
        self.played = set(d.get("played", []))
        self.history = list(d.get("history", []))
        self.last = d.get("last")

    def save(self):
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"grid": self.grid, "hotkeys": self.hotkeys,
                                   "opts": self.opts, "played": sorted(self.played),
                                   "history": self.history, "last": self.last}, indent=2), "utf-8")
        os.replace(tmp, DATA_FILE)

    @property
    def legends(self):
        return self.grid["legends"]

    def unplayed(self):
        return [i for i in range(self.legends) if i not in self.played]

    def mark(self, i):
        self.played.add(i)
        self.history.append(i)

    def undo(self):
        if not self.history:
            return None
        i = self.history.pop()
        self.played.discard(i)
        return i

    def reset(self):
        if self.history:
            self.last = self.history[-1]
        self.played.clear()
        self.history.clear()

    def cell(self, i):
        """(row, col) of legend i. Slot 0 of the grid is the Random tile."""
        return divmod(i + 1, self.grid["cols"])

    def rect(self, i, sw, sh):
        g = self.grid
        r, c = self.cell(i)
        cw = (g["right"] - g["left"]) / g["cols"]
        ch = (g["bottom"] - g["top"]) / g["rows"]
        sx, sy = sw / g["base_w"], sh / g["base_h"]
        return ((g["left"] + c * cw) * sx, (g["top"] + r * ch) * sy,
                (g["left"] + (c + 1) * cw) * sx, (g["top"] + (r + 1) * ch) * sy)


# --------------------------------------------------------------------------- #
class Overlay:
    """Transparent, click-through, always-on-top layer drawn over the game.

    Unplayed legends: glowing pink badge.  Played legends: softly dimmed + check badge.
    The pick: everything else dims (spotlight) and the chosen tile gets a pulsing pink
    frame, a rippling halo and twinkling sparkles.
    """

    def __init__(self, root, store):
        self.root, self.st = root, store
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", KEY)
        self.sw, self.sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.win.geometry(f"{self.sw}x{self.sh}+0+0")
        self.cv = tk.Canvas(self.win, bg=KEY, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.visible = self.align = False
        self.highlight, self.message = None, ""
        self._hide_job, self._t, self._hl = None, 0, None
        self.win.update_idletasks()
        self._click_through()
        self.win.withdraw()
        self._animate()

    def _click_through(self):
        try:
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            style = u.GetWindowLongW(hwnd, -20)
            u.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80)  # layered|transparent|toolwindow
        except Exception:
            pass

    # -- visibility
    def show(self, message="", highlight=None):
        self.message, self.highlight = message, highlight
        self.visible = True
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.redraw()
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        secs = self.st.opts["auto_hide"]
        if secs > 0 and not self.align:
            self._hide_job = self.root.after(int(secs * 1000), self.hide)

    def hide(self):
        self.visible = self.align = False
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self.win.withdraw()

    # -- drawing
    def redraw(self):
        if not self.visible:
            return
        cv, st, spot = self.cv, self.st, self.highlight
        cv.delete("all")
        self._hl = None
        for i in range(st.legends):
            x0, y0, x1, y1 = st.rect(i, self.sw, self.sh)
            x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
            if self.align:
                cv.create_rectangle(x0, y0, x1, y1, outline=HOT, width=2)
            played = i in st.played
            if spot is not None and i != spot:
                cv.create_rectangle(x0, y0, x1, y1, fill=PLUM, stipple="gray50", outline="")
            elif spot is None and played:
                cv.create_rectangle(x0, y0, x1, y1, fill=PLUM, stipple="gray25", outline="")
            if i != spot:
                self._badge(x1, y1, x1 - x0, played)
        if spot is not None:
            self._spotlight(*st.rect(spot, self.sw, self.sh))
        self._pill(self.message or f"{len(st.unplayed())} of {st.legends} unplayed")

    def _badge(self, x1, y1, w, played):
        cv = self.cv
        r = max(6, w * 0.15)
        cx, cy = x1 - r - 3, y1 - r - 3
        if played:
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=PLUM, outline="white", width=2)
            cv.create_text(cx, cy - 1, text="✓", fill="white",
                           font=("Segoe UI Symbol", max(7, int(r)), "bold"))
        else:
            cv.create_oval(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3, fill="", outline=HOT2, width=2)
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=HOT, outline="white", width=2)
            k = r * 0.28
            cv.create_oval(cx - k, cy - k, cx + k, cy + k, fill="white", outline="")

    def _spotlight(self, x0, y0, x1, y1):
        cv = self.cv
        self._hl = (x0, y0, x1, y1)
        rad = 9
        cv.create_polygon(rr(x0 - 4, y0 - 4, x1 + 4, y1 + 4, rad), smooth=True, fill="",
                          outline=PLUM, width=11)
        cv.create_polygon(rr(x0 - 4, y0 - 4, x1 + 4, y1 + 4, rad), smooth=True, fill="",
                          outline="white", width=8)
        cv.create_polygon(rr(x0 - 4, y0 - 4, x1 + 4, y1 + 4, rad), smooth=True, fill="",
                          outline=HOT, width=5, tags="pulse")
        cv.create_polygon(rr(x0, y0, x1, y1, rad), smooth=True, fill="", outline=HOT,
                          width=3, tags="ripple")
        corners = [(x0 - 6, y0 - 6, "a"), (x1 + 6, y1 + 6, "a"), (x1 + 6, y0 - 6, "b"), (x0 - 6, y1 + 6, "b")]
        for cx, cy, grp in corners:
            font = ("Segoe UI Symbol", 17, "bold")
            cv.create_text(cx + 1, cy + 2, text="✦", fill=PLUM, font=font, tags="spark_" + grp)
            cv.create_text(cx, cy, text="✦", fill="white", font=font, tags="spark_" + grp)

    def _pill(self, text):
        g, cv = self.st.grid, self.cv
        cx = (g["left"] + g["right"]) / 2 * self.sw / g["base_w"]
        cy = (g["bottom"] + 26) * self.sh / g["base_h"]
        if self.highlight is not None:
            text = f"✦  {text}  ✦"
        t = cv.create_text(cx, cy, text=text, fill=PLUM, font=("Segoe UI Semibold", 14))
        x0, y0, x1, y1 = cv.bbox(t)
        x0, x1, y0, y1 = x0 - 20, x1 + 20, y0 - 8, y1 + 8
        rad = (y1 - y0) / 2
        shadow = cv.create_polygon(rr(x0 + 2, y0 + 3, x1 + 2, y1 + 3, rad), smooth=True, fill=PLUM, outline="")
        box = cv.create_polygon(rr(x0, y0, x1, y1, rad), smooth=True, fill="#fff5f9", outline=HOT, width=3)
        cv.tag_lower(box, t)
        cv.tag_lower(shadow, box)

    def _animate(self):
        if self.visible and self.highlight is not None and self._hl:
            self._t += 1
            ph = (self._t % 28) / 28
            s = (math.sin(self._t * 0.35) + 1) / 2
            cv = self.cv
            cv.itemconfigure("pulse", outline=mix(HOT, "#ffd0e4", s), width=4 + 2 * s)
            x0, y0, x1, y1 = self._hl
            off = 4 + ph * 22
            cv.coords("ripple", *rr(x0 - off, y0 - off, x1 + off, y1 + off, 9 + off * 0.4))
            cv.itemconfigure("ripple", outline=mix(HOT, "#ffffff", ph), width=max(1, 4 * (1 - ph)))
            a = (self._t // 7) % 2 == 0
            cv.itemconfigure("spark_a", state="normal" if a else "hidden")
            cv.itemconfigure("spark_b", state="hidden" if a else "normal")
        self.root.after(45, self._animate)


# --------------------------------------------------------------------------- #
class App:
    CELL, PAD = 42, 8

    def __init__(self):
        self.st = Store()
        self.root = tk.Tk()
        self.root.title("Brawlhalla Picker")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.minsize(620, 300)
        self.q = queue.Queue()
        self.thumbs, self.thumbs_played = {}, {}
        self.hotkeys = HotkeyManager()
        self._closing = False
        self._hotkey_capture = False
        self._hotkey_watchdog_at = 0.0
        self.ov = Overlay(self.root, self.st)
        self._armed = 0.0
        self._cal_job = None
        self._stats = (0, 1)
        self._style()
        self._build()
        self.root.update_idletasks()
        self._center_window()
        self.load_thumbs()
        errors = self.bind_hotkeys()
        if errors:
            self.root.after(350, lambda: messagebox.showwarning(
                "Some hotkeys were not registered",
                "The following hotkeys could not be enabled:\n\n" + "\n".join(errors)
                + "\n\nChoose different keys in Settings."))
        self.refresh()
        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def _center_window(self):
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    # ---------------------------------------------------------------- style
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10), borderwidth=0)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("Card.TLabel", background=PANEL, foreground=FG)
        s.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED)
        s.configure("H.TLabel", background=PANEL, foreground=ROSE_D, font=("Segoe UI Semibold", 11))
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("TButton", background="#ffe3ed", foreground=FG, bordercolor=EDGE,
                    lightcolor="#ffe3ed", darkcolor="#ffe3ed", borderwidth=1,
                    padding=(14, 8), focusthickness=0)
        s.map("TButton", background=[("active", "#ffd0e1")], bordercolor=[("active", HOT)])
        s.configure("Accent.TButton", background=HOT, foreground="white", bordercolor=HOT,
                    lightcolor=HOT, darkcolor=HOT, font=("Segoe UI Semibold", 10))
        s.map("Accent.TButton", background=[("active", "#ff74ae")], bordercolor=[("active", "#ff74ae")])
        s.configure("TNotebook", background=BG, tabmargins=(2, 0, 0, 0))
        s.configure("TNotebook.Tab", background="#f8d3e2", foreground=MUTED, padding=(20, 9))
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ROSE_D)])
        s.configure("TCheckbutton", background=PANEL, foreground=FG, indicatorcolor="white")
        s.map("TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", HOT)])
        s.configure("TSpinbox", fieldbackground="white", foreground=FG, bordercolor=EDGE,
                    arrowcolor=ROSE_D, background="#ffe3ed", insertcolor=FG)

    # ----------------------------------------------------------------- build
    def _build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=14, pady=14)
        self.tab_main = ttk.Frame(nb, style="Card.TFrame", padding=16)
        self.tab_set = ttk.Frame(nb, style="Card.TFrame", padding=16)
        nb.add(self.tab_main, text="✿  Tracker")
        nb.add(self.tab_set, text="Settings")
        self._build_tracker(self.tab_main)
        self._build_settings(self.tab_set)

    def _build_tracker(self, p):
        gw = self.st.grid["cols"] * self.CELL + self.PAD * 2 - 3
        self.hdr = tk.Canvas(p, width=gw, height=72, highlightthickness=0, bg=PANEL)
        self.hdr.pack(fill="x")
        self.hdr.bind("<Configure>", lambda e: self._draw_header())

        self.pbar = tk.Canvas(p, height=18, highlightthickness=0, bg=PANEL)
        self.pbar.pack(fill="x", pady=(10, 8))
        self.pbar.bind("<Configure>", lambda e: self._draw_progress())

        frame = tk.Frame(p, bg=EDGE, padx=1, pady=1)
        frame.pack()
        self.gcv = tk.Canvas(frame, bg=GRID_BG, highlightthickness=0, cursor="hand2")
        self.gcv.pack()
        self.gcv.bind("<Button-1>", self._on_click)
        self.gcv.bind("<Motion>", self._on_hover)
        self.gcv.bind("<Leave>", self._on_leave)

        self._default_hint = "Click a portrait to toggle played / unplayed   ·   pink ring = still to play"
        self.hint = ttk.Label(p, text=self._default_hint, style="CardMuted.TLabel")
        self.hint.pack(anchor="w", pady=(8, 4))

        self.rcv = tk.Canvas(p, height=48, highlightthickness=0, bg=PANEL)
        self.rcv.pack(fill="x", pady=(0, 10))

        bar = ttk.Frame(p, style="Card.TFrame")
        bar.pack(fill="x")
        ttk.Button(bar, text="✦  Pick random", style="Accent.TButton", command=self.pick).pack(side="left")
        ttk.Button(bar, text="Undo last", command=self.undo).pack(side="left", padx=6)
        ttk.Button(bar, text="Reset cycle", command=self.reset_confirm).pack(side="left")
        ttk.Button(bar, text="Hide overlay", command=self.ov.hide).pack(side="right")
        ttk.Button(bar, text="Show overlay", command=lambda: self.ov.show()).pack(side="right", padx=6)

    def _build_settings(self, p):
        ttk.Label(p, text="Hotkeys", style="H.TLabel").grid(row=0, column=0, sticky="w")
        self.hk_btns = {}
        for n, (act, label) in enumerate(HK_LABELS.items(), start=1):
            ttk.Label(p, text=label, style="Card.TLabel").grid(row=n, column=0, sticky="w", pady=3)
            b = ttk.Button(p, width=14, command=lambda a=act: self.rebind(a))
            b.grid(row=n, column=1, sticky="w", padx=10)
            self.hk_btns[act] = b

        r = len(HK_LABELS) + 2
        ttk.Label(p, text="Overlay", style="H.TLabel").grid(row=r, column=0, sticky="w", pady=(18, 4))
        ttk.Label(p, text="Auto-hide after (seconds, 0 = off)", style="Card.TLabel").grid(row=r + 1, column=0, sticky="w")
        self.v_hide = tk.IntVar(value=self.st.opts["auto_hide"])
        ttk.Spinbox(p, from_=0, to=60, width=6, textvariable=self.v_hide,
                    command=self._save_opts).grid(row=r + 1, column=1, sticky="w", padx=10)
        self.v_hide.trace_add("write", lambda *_: self._save_opts())
        self.v_auto = tk.BooleanVar(value=self.st.opts["auto_reset"])
        ttk.Checkbutton(p, text="Start a new cycle automatically when everyone has been played",
                        variable=self.v_auto, command=self._save_opts).grid(
            row=r + 2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        r += 4
        ttk.Label(p, text="Grid calibration (1366x768 reference pixels)", style="H.TLabel").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(18, 4))
        box = ttk.Frame(p, style="Card.TFrame")
        box.grid(row=r + 1, column=0, columnspan=3, sticky="w")
        self.gvars = {}
        for n, key in enumerate(["left", "top", "right", "bottom", "cols", "rows", "legends"]):
            ttk.Label(box, text=key, style="CardMuted.TLabel").grid(row=0, column=n, sticky="w", padx=3)
            v = tk.IntVar(value=self.st.grid[key])
            self.gvars[key] = v
            ttk.Spinbox(box, from_=0, to=2000, width=6, textvariable=v,
                        command=self._cal_soon).grid(row=1, column=n, padx=3)
            v.trace_add("write", lambda *_: self._cal_soon())
        btns = ttk.Frame(p, style="Card.TFrame")
        btns.grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(btns, text="Preview alignment", command=self.preview).pack(side="left")
        ttk.Button(btns, text="Restore defaults", command=self.restore_grid).pack(side="left", padx=6)
        ttk.Button(btns, text="Import portraits…", command=self.import_thumbs).pack(side="left")
        data = ttk.Frame(p, style="Card.TFrame")
        data.grid(row=r + 3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(data, text="Export backup…", command=self.export_state).pack(side="left")
        ttk.Button(data, text="Import backup…", command=self.import_state).pack(side="left", padx=6)
        self.refresh_hotkey_labels()

    # ------------------------------------------------------------ rendering
    @staticmethod
    def _make_played(src, dst):
        """Soft pink-grey version of a portrait for the 'already played' look."""
        try:
            im = Image.open(src).convert("RGB")
            gray = ImageOps.grayscale(im).convert("RGB")
            wash = Image.new("RGB", gray.size, (253, 224, 235))
            Image.blend(gray, wash, 0.55).save(dst)
        except Exception:
            pass

    def load_thumbs(self):
        self.thumbs.clear()
        self.thumbs_played.clear()
        for i in range(self.st.legends):
            f = THUMB_DIR / f"{i + 1:02d}.png"
            if not f.exists():
                continue
            g = THUMB_DIR / f"{i + 1:02d}_played.png"
            if Image and not g.exists():
                self._make_played(f, g)
            try:
                self.thumbs[i] = tk.PhotoImage(file=str(f))
            except tk.TclError:
                continue
            if g.exists():
                try:
                    self.thumbs_played[i] = tk.PhotoImage(file=str(g))
                except tk.TclError:
                    pass

    def _draw_header(self):
        cv = self.hdr
        w, h = cv.winfo_width(), 72
        if w < 20:
            return
        cv.delete("all")
        for x in range(0, w, 3):
            cv.create_line(x, 0, x, h, fill=mix(HOT, HOT2, x / w), width=3)
        cv.create_text(21, 27, text="✿  Legend Tracker", anchor="w", fill=ROSE_D, font=("Segoe UI Semibold", 18))
        cv.create_text(20, 26, text="✿  Legend Tracker", anchor="w", fill="white", font=("Segoe UI Semibold", 18))
        cv.create_text(22, 53, text="Your random rotation, one legend at a time", anchor="w",
                       fill="#fff0f6", font=("Segoe UI", 9))
        done, total = self._stats
        cv.create_text(w - 20, 26, text=f"{done} / {total}", anchor="e", fill="white",
                       font=("Segoe UI Semibold", 19))
        cv.create_text(w - 20, 53, text=f"played  ·  {max(0, total - done)} left", anchor="e",
                       fill="#fff0f6", font=("Segoe UI", 9))

    def _draw_progress(self):
        cv = self.pbar
        w = cv.winfo_width()
        if w < 30:
            return
        cv.delete("all")
        done, total = self._stats
        frac = done / max(1, total)
        cv.create_line(9, 9, w - 9, 9, width=12, capstyle="round", fill=PANEL2)
        if frac > 0:
            end = 9 + (w - 18) * frac
            cv.create_line(9, 9, max(end, 10), 9, width=12, capstyle="round", fill=HOT)
            cv.create_line(9, 7, max(end, 10), 7, width=3, capstyle="round", fill=HOT2)

    def _draw_recent(self):
        cv, st = self.rcv, self.st
        cv.delete("all")
        cv.create_text(2, 24, text="RECENT", anchor="w", fill=MUTED, font=("Segoe UI Semibold", 8))
        picks = st.history[-8:]
        if not picks:
            cv.create_text(62, 24, text="no picks yet", anchor="w", fill=MUTED, font=("Segoe UI", 9, "italic"))
            return
        size = self.CELL - 3
        for k, i in enumerate(picks):
            x, y = 62 + k * (size + 6), 4
            if i in self.thumbs:
                cv.create_image(x, y, image=self.thumbs[i], anchor="nw")
            else:
                cv.create_rectangle(x, y, x + size, y + size, fill=PANEL2, outline="")
                cv.create_text(x + size / 2, y + size / 2, text=str(i + 1), fill=MUTED, font=("Segoe UI", 9))
            newest = k == len(picks) - 1
            cv.create_rectangle(x, y, x + size, y + size, outline=HOT if newest else EDGE,
                                width=3 if newest else 1)
            if k < len(picks) - 1:
                cv.create_text(x + size + 3, y + size / 2, text="›", fill=EDGE, font=("Segoe UI", 12, "bold"))

    def refresh(self):
        st, cv, C, P = self.st, self.gcv, self.CELL, self.PAD
        cols, rows = st.grid["cols"], st.grid["rows"]
        cv.delete("all")
        cv.configure(width=cols * C + P * 2 - 3, height=rows * C + P * 2 - 3)
        last = st.history[-1] if st.history else None
        for s in range(cols * rows):
            r, c = divmod(s, cols)
            x, y = P + c * C, P + r * C
            x1, y1, i = x + C - 3, y + C - 3, s - 1
            if s == 0:
                cv.create_rectangle(x, y, x1, y1, fill=PANEL2, outline=EDGE)
                cv.create_text((x + x1) / 2, (y + y1) / 2, text="RND", fill=MUTED, font=("Segoe UI", 8, "bold"))
                continue
            if i >= st.legends:
                cv.create_rectangle(x, y, x1, y1, outline=EDGE, dash=(2, 3))
                continue
            played = i in st.played
            img = (self.thumbs_played.get(i) if played else None) or self.thumbs.get(i)
            if img:
                cv.create_image(x, y, image=img, anchor="nw")
            else:
                cv.create_rectangle(x, y, x1, y1, fill=PANEL2, outline="")
                cv.create_text((x + x1) / 2, (y + y1) / 2, text=str(i + 1), fill=MUTED, font=("Segoe UI", 9))
            if played and i not in self.thumbs_played:  # no Pillow: fall back to a pink veil
                cv.create_rectangle(x, y, x1, y1, fill="#fde0eb", stipple="gray50", outline="")
            cv.create_rectangle(x, y, x1, y1, outline=EDGE if played else HOT, width=1 if played else 2)
            cx, cy = x1 - 8, y1 - 8
            if played:
                cv.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill="white", outline=EDGE)
                cv.create_text(cx, cy - 1, text="✓", fill=ROSE_D, font=("Segoe UI Symbol", 8, "bold"))
            else:
                cv.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=HOT, outline="white", width=2)
            if i == last:
                cv.create_rectangle(x - 1, y - 1, x1 + 1, y1 + 1, outline=PLUM, width=2)
                cv.create_oval(x + 1, y + 1, x + 15, y + 15, fill=HOT, outline="white", width=1)
                cv.create_text(x + 8, y + 8, text="✦", fill="white", font=("Segoe UI Symbol", 8, "bold"))
        self._stats = (len(st.played), st.legends)
        self._draw_header()
        self._draw_progress()
        self._draw_recent()
        self.ov.redraw()

    def _legend_at(self, e):
        c, r = (e.x - self.PAD) // self.CELL, (e.y - self.PAD) // self.CELL
        if not (0 <= c < self.st.grid["cols"]):
            return None
        i = r * self.st.grid["cols"] + c - 1
        return i if 0 <= i < self.st.legends else None

    def _on_leave(self, _e):
        self.gcv.delete("hover")
        self.hint.config(text=self._default_hint)

    def _on_hover(self, e):
        i = self._legend_at(e)
        self.gcv.delete("hover")
        if i is None:
            self.hint.config(text=self._default_hint)
            return
        state = "played" if i in self.st.played else "unplayed"
        self.hint.config(text=f"Legend #{i + 1}   ·   {state}   ·   click to toggle")
        row, col = divmod(i + 1, self.st.grid["cols"])
        x0, y0 = self.PAD + col * self.CELL, self.PAD + row * self.CELL
        self.gcv.create_rectangle(x0 - 1, y0 - 1, x0 + self.CELL - 2, y0 + self.CELL - 2,
                                  outline=ROSE_D, width=2, tags="hover")

    def _on_click(self, e):
        i = self._legend_at(e)
        if i is not None:
            self.st.played ^= {i}
            self.st.history = [h for h in self.st.history if h != i]
            if i in self.st.played:
                self.st.history.append(i)
            self.st.save()
            self.refresh()

    # -------------------------------------------------------------- actions
    def key(self, act):
        return self.st.hotkeys[act].upper()

    def pick(self):
        st, note = self.st, ""
        pool = st.unplayed()
        if not pool:
            if st.opts["auto_reset"]:
                st.reset()
                pool, note = st.unplayed(), "New cycle!  "
            else:
                self.ov.show(f"Everyone's been played - press {self.key('reset')} twice to reset")
                return
        if not st.history and st.last in pool and len(pool) > 1:
            pool = [x for x in pool if x != st.last]  # never open a new cycle with the legend that closed the last one
        i = random.SystemRandom().choice(pool)
        st.mark(i)
        st.save()
        self.refresh()
        self.ov.show(f"{note}Play legend #{i + 1}  ·  {len(st.unplayed())} left", highlight=i)

    def undo(self):
        if self.st.undo() is not None:
            self.st.save()
            self.refresh()
            if self.ov.visible:
                self.ov.show("Last pick undone")

    def reset(self):
        self.st.reset()
        self.st.save()
        self.refresh()
        self.ov.show("Reset - every legend is unplayed")

    def reset_confirm(self):
        if messagebox.askyesno("Reset", "Mark every legend as unplayed?"):
            self.reset()

    def hotkey_reset(self):
        """In-game reset needs two presses so it can't happen by accident."""
        now = time.monotonic()
        if now - self._armed < 3:
            self._armed = 0
            self.reset()
        else:
            self._armed = now
            self.ov.show(f"Press {self.key('reset')} again to reset everything")

    # -------------------------------------------------------------- settings
    def _save_opts(self):
        try:
            self.st.opts["auto_hide"] = max(0, int(self.v_hide.get()))
        except (tk.TclError, ValueError):
            return
        self.st.opts["auto_reset"] = bool(self.v_auto.get())
        self.st.save()

    def _cal_soon(self):
        if self._cal_job:
            self.root.after_cancel(self._cal_job)
        self._cal_job = self.root.after(250, self.apply_grid)

    def apply_grid(self):
        g = self.st.grid
        try:
            for k, v in self.gvars.items():
                g[k] = max(1, int(v.get()))
        except (tk.TclError, ValueError):
            return
        g["legends"] = min(g["legends"], g["cols"] * g["rows"] - 1)
        self.st.played = {i for i in self.st.played if i < g["legends"]}
        self.st.save()
        self.load_thumbs()
        self.refresh()

    def restore_grid(self):
        self.st.grid.update(DEFAULT_GRID)
        for k, v in self.gvars.items():
            v.set(self.st.grid[k])

    def preview(self):
        if self.ov.visible and self.ov.align:
            self.ov.hide()
        else:
            self.ov.align = True
            self.ov.show("Alignment preview - tune the numbers until the boxes fit")

    def import_thumbs(self):
        if Image is None:
            messagebox.showinfo("Pillow needed", "Run:  pip install pillow\nthen try again.")
            return
        path = filedialog.askopenfilename(
            title="Screenshot of the character select screen",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        img = Image.open(path).convert("RGB")
        THUMB_DIR.mkdir(exist_ok=True)
        size = self.CELL - 3
        for i in range(self.st.legends):
            x0, y0, x1, y1 = self.st.rect(i, img.width, img.height)
            tile = img.crop((int(x0) + 2, int(y0) + 2, int(x1) - 2, int(y1) - 2))
            dst = THUMB_DIR / f"{i + 1:02d}.png"
            tile.resize((size, size), Image.LANCZOS).save(dst)
            self._make_played(dst, THUMB_DIR / f"{i + 1:02d}_played.png")
        self.load_thumbs()
        self.refresh()
        messagebox.showinfo("Done", "Portraits imported. If they look misaligned, "
                                    "adjust the calibration and import again.")

    # ---------------------------------------------------------- data backup
    def export_state(self):
        path = filedialog.asksaveasfilename(
            title="Export Brawlhalla Picker progress", defaultextension=".json",
            initialfile="brawlhalla_picker_backup.json", filetypes=[("JSON backup", "*.json")])
        if not path:
            return
        try:
            self.st.save()
            target = Path(path)
            if target.resolve() != DATA_FILE.resolve():
                shutil.copy2(DATA_FILE, target)
            messagebox.showinfo("Backup exported", f"Progress and settings saved to:\n{target}")
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export the backup:\n{exc}")

    def import_state(self):
        path = filedialog.askopenfilename(
            title="Import Brawlhalla Picker backup",
            filetypes=[("JSON backup", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("The file does not contain a valid backup.")
            grid_data = data.get("grid", data.get("cfg", {}))
            hotkeys_data = data.get("hotkeys", {})
            opts_data = data.get("opts", {})
            played_data = data.get("played", [])
            history_data = data.get("history", [])
            if not all(isinstance(x, dict) for x in (grid_data, hotkeys_data, opts_data)):
                raise ValueError("Grid, hotkeys or options have an invalid format.")
            if not isinstance(played_data, list) or not isinstance(history_data, list):
                raise ValueError("Played list or history has an invalid format.")

            grid = dict(DEFAULT_GRID)
            for key in grid:
                if key in grid_data:
                    grid[key] = int(grid_data[key])
            if min(grid["cols"], grid["rows"], grid["base_w"], grid["base_h"]) < 1:
                raise ValueError("Grid dimensions must be positive.")
            if grid["right"] <= grid["left"] or grid["bottom"] <= grid["top"]:
                raise ValueError("Grid right/bottom coordinates must be larger than left/top.")
            grid["legends"] = max(1, min(grid["legends"], grid["cols"] * grid["rows"] - 1))

            hotkeys = dict(DEFAULT_HOTKEYS)
            for key in hotkeys:
                if key in hotkeys_data:
                    value = str(hotkeys_data[key]).strip().lower()
                    if not value or value == "esc":
                        raise ValueError(f"Invalid hotkey for '{key}'.")
                    hotkeys[key] = value
            if len(set(hotkeys.values())) != len(hotkeys):
                raise ValueError("The backup assigns the same hotkey to multiple actions.")

            opts = dict(DEFAULT_OPTS)
            opts.update({k: opts_data[k] for k in DEFAULT_OPTS if k in opts_data})
            opts["auto_hide"] = max(0, min(60, int(opts["auto_hide"])))
            opts["auto_reset"] = bool(opts["auto_reset"])

            played = {int(i) for i in played_data if 0 <= int(i) < grid["legends"]}
            history = [int(i) for i in history_data if 0 <= int(i) < grid["legends"] and int(i) in played]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror("Import failed", f"This backup could not be loaded:\n{exc}")
            return

        if not messagebox.askyesno("Import backup", "Replace the current progress and settings "
                                                    "with this backup?"):
            return
        try:
            self.st.save()
            shutil.copy2(DATA_FILE, DATA_FILE.with_name("brawl_state_before_import.json"))
            self.st.grid, self.st.hotkeys, self.st.opts = grid, hotkeys, opts
            self.st.played, self.st.history = played, history
            self.st.save()
            for key, var in self.gvars.items():
                var.set(self.st.grid[key])
            self.v_hide.set(self.st.opts["auto_hide"])
            self.v_auto.set(self.st.opts["auto_reset"])
            self.refresh_hotkey_labels()
            self.bind_hotkeys(show_errors=True)
            self.load_thumbs()
            self.refresh()
            self.ov.hide()
            messagebox.showinfo("Backup imported", "Progress and settings were restored successfully.")
        except Exception as exc:
            messagebox.showerror("Import failed", f"The backup could not be applied:\n{exc}")

    # --------------------------------------------------------------- hotkeys
    def refresh_hotkey_labels(self):
        for act, b in self.hk_btns.items():
            b.config(text=self.key(act))

    def bind_hotkeys(self, show_errors=False):
        actions = {"show": lambda: self.ov.show(), "pick": self.pick, "hide": self.ov.hide,
                   "undo": self.undo, "reset": self.hotkey_reset}
        errors = self.hotkeys.start(
            self.st.hotkeys,
            lambda action: self.q.put(actions[action]) if not self._closing else None)
        if errors and show_errors:
            messagebox.showwarning(
                "Some hotkeys were not registered",
                "The following hotkeys could not be enabled:\n\n" + "\n".join(errors)
                + "\n\nChoose different keys in Settings.")
        return errors

    def rebind(self, act):
        """Capture a new shortcut in a focused dialog; no background keyboard reader."""
        self.hotkeys.stop()
        self._hotkey_capture = True

        dialog = tk.Toplevel(self.root)
        dialog.title("Set hotkey")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text=f"Press a key for: {HK_LABELS[act]}",
                  style="Title.TLabel").pack(padx=24, pady=(20, 8))
        ttk.Label(dialog, text="You can combine it with Ctrl, Alt or Shift.\nPress Esc to cancel.",
                  style="Muted.TLabel", justify="center").pack(padx=24, pady=(0, 18))

        finished = {"value": False}

        def finish(value=None):
            if finished["value"]:
                return
            finished["value"] = True
            self._hotkey_capture = False
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            try:
                dialog.destroy()
            except tk.TclError:
                pass
            self._set_hotkey(act, value)

        def on_key(event):
            name = event.keysym
            if name in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                        "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Win_L", "Win_R"):
                return "break"
            if name == "Escape":
                finish(None)
                return "break"
            aliases = {
                "Return": "enter", "KP_Enter": "enter", "Prior": "page up", "Next": "page down",
                "BackSpace": "backspace", "Page_Up": "page up", "Page_Down": "page down",
                "Print": "print screen", "equal": "equals", "bracketleft": "left bracket",
                "bracketright": "right bracket", "apostrophe": "quote",
            }
            key = aliases.get(name, name.lower())
            state = int(event.state)
            mods = []
            if state & 0x0004:
                mods.append("ctrl")
            if state & 0x0008:
                mods.append("alt")
            if state & 0x0001:
                mods.append("shift")
            finish("+".join(mods + [key]))
            return "break"

        dialog.bind("<KeyPress>", on_key)
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        dialog.focus_force()
        dialog.wait_window()

    def _set_hotkey(self, act, key):
        if key:
            key = key.strip().lower()
            taken = [a for a, v in self.st.hotkeys.items() if v.strip().lower() == key and a != act]
            try:
                HotkeyManager.parse(key)
                valid = True
            except ValueError as exc:
                valid = False
                messagebox.showwarning("Unsupported hotkey", str(exc))
            if valid and taken:
                names = ", ".join(HK_LABELS[a] for a in taken)
                messagebox.showwarning("Hotkey already in use",
                                       f"{key.upper()} is already assigned to: {names}.\n\n"
                                       "The previous binding was kept.")
            elif valid:
                self.st.hotkeys[act] = key
                self.st.save()
        self.refresh_hotkey_labels()
        self.bind_hotkeys(show_errors=True)

    def _log(self, title):
        try:
            with (APP_DIR / "brawl_picker_errors.log").open("a", encoding="utf-8") as f:
                f.write(f"\n--- {title} ---\n{traceback.format_exc()}")
        except Exception:
            pass

    def _poll(self):
        """Drain queued actions without letting one bad action kill the poll loop."""
        try:
            for _ in range(100):
                try:
                    action = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    action()
                except Exception:
                    self._log("UI action error")
                    try:
                        self.hint.config(text="An action failed; details saved to brawl_picker_errors.log")
                    except Exception:
                        pass
        finally:
            if not self._closing:
                now = time.monotonic()
                if not self._hotkey_capture and now - self._hotkey_watchdog_at >= 3.0:
                    self._hotkey_watchdog_at = now
                    thread = self.hotkeys.thread
                    if thread is None or not thread.is_alive():
                        try:
                            self.bind_hotkeys(show_errors=False)
                        except Exception:
                            self._log("Hotkey recovery error")
                try:
                    self.root.after(50, self._poll)
                except tk.TclError:
                    pass

    def quit(self):
        self._closing = True
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.st.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()