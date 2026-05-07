#!/usr/bin/env python3
"""
ScreenClick Pro
───────────────
Floating cursor sleeps in a corner. When OCR finds matching text it
wakes up, glides to the target, clicks, then returns to rest.
"""

import sys, os, re, json, time, uuid, queue, threading, traceback
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from typing import Optional, List, Callable

# ── crash logger (always write errors to file so nothing is silent) ───────────
LOG_FILE = os.path.join(os.path.expanduser("~"), "screenclick_crash.log")

def _crash(exc):
    msg = traceback.format_exc()
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"\n[{datetime.now()}]\n{msg}\n")
    except Exception:
        pass
    try:
        messagebox.showerror("ScreenClick crashed", f"{exc}\n\nFull log: {LOG_FILE}")
    except Exception:
        print(msg)

# ── dependency check ──────────────────────────────────────────────────────────
_MISS = []
for _pkg, _mod in [("mss","mss"),("Pillow","PIL"),
                   ("pytesseract","pytesseract"),("pyautogui","pyautogui")]:
    try:
        __import__(_mod)
    except ImportError:
        _MISS.append(_pkg)

if _MISS:
    _r = tk.Tk(); _r.withdraw()
    messagebox.showerror("Missing packages",
        f"Run:  pip install {' '.join(_MISS)}\n\n"
        "Also install Tesseract-OCR:\n"
        "  https://github.com/UB-Mannheim/tesseract/wiki")
    sys.exit(1)

import mss
from PIL import Image
import pytesseract
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.015

# ── paths / defaults ──────────────────────────────────────────────────────────
SAVE_PATH = os.path.join(os.path.expanduser("~"), ".screenclick_pro.json")
MATCH_TYPES = ["contains", "exact word", "starts-with", "regex"]
CORNERS     = ["bottom-right", "bottom-left", "top-right", "top-left"]

# ── palette (6-digit hex only — tkinter rejects 8-digit rgba) ────────────────
BG      = "#0f0f1a"
PANEL   = "#1a1a2e"
CARD    = "#16213e"
BORDER  = "#2d3561"
ACCENT  = "#7c3aed"
TEAL    = "#22d3ee"
GREEN   = "#4ade80"
RED     = "#f87171"
AMBER   = "#fbbf24"
TEXT    = "#e2e8f0"
MUTED   = "#64748b"

# cursor overlay colours
CUR_IDLE  = "#a78bfa"   # soft purple  — sleeping chibi

# chibi character palette
HEAD_FILL  = "#fde68a"   # warm skin tone
HAIR_FILL  = "#1e293b"   # dark hair
BODY_FILL  = "#f472b6"   # cute pink outfit
HAMMER_COL = "#6b7280"   # grey hammer head
HANDLE_COL = "#92400e"   # brown handle

CURSOR_W, CURSOR_H = 80, 96


def corner_pos(corner: str, sw: int, sh: int) -> tuple:
    m = 14
    return {
        "top-left":     (m,              m),
        "top-right":    (sw-CURSOR_W-m,  m),
        "bottom-left":  (m,              sh-CURSOR_H-m),
        "bottom-right": (sw-CURSOR_W-m,  sh-CURSOR_H-m),
    }.get(corner, (sw-CURSOR_W-m, sh-CURSOR_H-m))


# ─────────────────────────────────────────────────────────────────────────────
# FloatingCursor  — cute anime chibi with hammer
# ─────────────────────────────────────────────────────────────────────────────
class FloatingCursor:
    """
    Tiny always-on-top transparent window with a cute anime chibi character.
    Sleeps in a corner. On a match: glides over, shows angry face + raises
    hammer → SMASH + POW! (click fires here) → holds 700 ms → returns home.
    """

    def __init__(self, root: tk.Tk, corner: str = "bottom-right"):
        self._root   = root
        self._corner = corner
        self._cx = self._cy = 0
        self._pulse_job: Optional[str] = None
        self._pulse_val = 0.0
        self._pulse_dir = 1
        self.busy   = False
        self._alive = True

        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.9)
        self._win.configure(bg="black")
        try:
            self._win.wm_attributes("-transparentcolor", "black")
        except tk.TclError:
            pass

        self._cv = tk.Canvas(self._win, width=CURSOR_W, height=CURSOR_H,
                             bg="black", highlightthickness=0)
        self._cv.pack()

        # body (drawn first so head overlaps it)
        self._body_sh = self._cv.create_oval(
            18, 52, 62, 76, fill=BODY_FILL, outline="#be185d", width=1.5)

        # head base
        self._head_sh = self._cv.create_oval(
            6, 2, 74, 58, fill=HEAD_FILL, outline="#d97706", width=1.5)

        # hair (smooth polygon on top of head)
        self._hair_sh = self._cv.create_polygon(
            6, 32,   6, 14,  14,  4,  28,  0,  40,  0,
            52,  2,  66, 10,  74, 24,  74, 36,
            66, 22,  54, 12,  40,  8,  26,  8,  14, 16,
            fill=HAIR_FILL, outline="", smooth=True)

        # closed eyes (sleeping arcs, shown in idle)
        self._eye_l_c = self._cv.create_arc(
            16, 24, 34, 38, start=0, extent=180,
            style="arc", outline=HAIR_FILL, width=2.5)
        self._eye_r_c = self._cv.create_arc(
            46, 24, 64, 38, start=0, extent=180,
            style="arc", outline=HAIR_FILL, width=2.5)

        # open anime eyes (hidden until wake / angry)
        self._eye_l_o = self._cv.create_oval(
            14, 20, 36, 42, fill="white", outline=HAIR_FILL, width=1.5, state="hidden")
        self._eye_r_o = self._cv.create_oval(
            44, 20, 66, 42, fill="white", outline=HAIR_FILL, width=1.5, state="hidden")
        self._pupil_l = self._cv.create_oval(
            20, 25, 30, 37, fill=HAIR_FILL, outline="", state="hidden")
        self._pupil_r = self._cv.create_oval(
            50, 25, 60, 37, fill=HAIR_FILL, outline="", state="hidden")
        self._shine_l = self._cv.create_oval(
            22, 27, 26, 31, fill="white", outline="", state="hidden")
        self._shine_r = self._cv.create_oval(
            52, 27, 56, 31, fill="white", outline="", state="hidden")

        # angry diagonal eyebrows (hidden until angry / smash)
        self._brow_l = self._cv.create_line(
            14, 17, 36, 23, fill=HAIR_FILL, width=3, capstyle="round", state="hidden")
        self._brow_r = self._cv.create_line(
            44, 23, 66, 17, fill=HAIR_FILL, width=3, capstyle="round", state="hidden")

        # rosy cheeks (shown when running / happy)
        self._cheek_l = self._cv.create_oval(
            8, 34, 22, 44, fill="#f9a8d4", outline="", state="hidden")
        self._cheek_r = self._cv.create_oval(
            58, 34, 72, 44, fill="#f9a8d4", outline="", state="hidden")

        # smile arc
        self._mouth_smile = self._cv.create_arc(
            28, 42, 52, 54, start=200, extent=140,
            style="arc", outline=HAIR_FILL, width=2)

        # gritted-teeth mouth (angry, hidden by default)
        self._mouth_bar = self._cv.create_rectangle(
            28, 46, 52, 54, fill=HAIR_FILL, outline="", state="hidden")
        self._teeth     = self._cv.create_rectangle(
            30, 47, 50, 52, fill="white",   outline="", state="hidden")

        # sleeping zzz
        self._zzz = self._cv.create_text(
            76, 0, text="zzz", anchor="ne",
            fill=CUR_IDLE, font=("Segoe UI", 7, "bold"))

        # hammer arm — hidden until click states
        # raised  coords: arm(60,64→74,46)  handle(74,46→76,22)  head rect(64,8→80,24)
        # smashed coords: arm(60,64→74,80)  handle(74,80→76,94)  head rect(64,90→80,104)
        self._arm    = self._cv.create_line(
            60, 64, 74, 46, fill=HEAD_FILL,  width=6, capstyle="round", state="hidden")
        self._handle = self._cv.create_line(
            74, 46, 76, 22, fill=HANDLE_COL, width=4, capstyle="round", state="hidden")
        self._hammer = self._cv.create_rectangle(
            64, 8, 80, 24, fill=HAMMER_COL, outline="#374151", width=2, state="hidden")

        # impact lines radiating from hammer strike point
        self._impact = []
        for x0, y0, x1, y1 in [
            (56, 58, 44, 50), (62, 54, 54, 44), (68, 58, 78, 50),
            (66, 64, 78, 70), (58, 68, 48, 76),
        ]:
            self._impact.append(self._cv.create_line(
                x0, y0, x1, y1, fill="#fbbf24", width=2,
                capstyle="round", state="hidden"))

        self._pow = self._cv.create_text(
            40, 82, text="POW!", anchor="center",
            fill="#fbbf24", font=("Segoe UI", 10, "bold"), state="hidden")

        self._snap()
        self._start_pulse()

    # ── safe canvas / window helpers ──────────────────────────────────────────
    def _cfg(self, item, **kw):
        if not self._alive: return
        try: self._cv.itemconfig(item, **kw)
        except Exception: pass

    def _coords(self, item, *args):
        if not self._alive: return
        try: self._cv.coords(item, *args)
        except Exception: pass

    def _win_alpha(self, a: float):
        if not self._alive: return
        try: self._win.attributes("-alpha", a)
        except Exception: pass

    def _state(self, s: str):
        if not self._alive: return

        def sh(*items):
            for it in items: self._cfg(it, state="normal")

        def hd(*items):
            for it in items: self._cfg(it, state="hidden")

        open_eyes  = [self._eye_l_o, self._eye_r_o,
                      self._pupil_l, self._pupil_r,
                      self._shine_l, self._shine_r]
        close_eyes = [self._eye_l_c, self._eye_r_c]
        brows      = [self._brow_l, self._brow_r]
        cheeks     = [self._cheek_l, self._cheek_r]
        mouth_ang  = [self._mouth_bar, self._teeth]
        hammer_all = [self._arm, self._handle, self._hammer]
        impact_all = self._impact + [self._pow]

        if s == "idle":
            sh(*close_eyes, self._mouth_smile)
            hd(*open_eyes, *brows, *cheeks, *mouth_ang, *hammer_all, *impact_all)
            self._cfg(self._zzz, text="zzz", fill=CUR_IDLE)
            self._cfg(self._head_sh, fill=HEAD_FILL)

        elif s == "wake":
            sh(*open_eyes, *cheeks, self._mouth_smile)
            hd(*close_eyes, *brows, *mouth_ang, *hammer_all, *impact_all)
            self._cfg(self._zzz, text="")
            self._cfg(self._head_sh, fill=HEAD_FILL)
            self._win_alpha(1.0)

        elif s == "angry":
            # hammer raised, angry face
            sh(*open_eyes, *brows, *mouth_ang, *hammer_all)
            hd(*close_eyes, *cheeks, self._mouth_smile, *impact_all)
            self._cfg(self._zzz, text="!!")
            self._cfg(self._head_sh, fill="#ffc8a0")
            self._coords(self._arm,    60, 64, 74, 46)
            self._coords(self._handle, 74, 46, 76, 22)
            self._coords(self._hammer, 64,  8, 80, 24)
            self._win_alpha(1.0)

        elif s == "smash":
            # hammer slammed down + POW!
            sh(*open_eyes, *brows, *mouth_ang, *hammer_all, *impact_all)
            hd(*close_eyes, *cheeks, self._mouth_smile)
            self._cfg(self._zzz, text="")
            self._cfg(self._head_sh, fill="#ffc8a0")
            self._coords(self._arm,    60, 64, 74, 80)
            self._coords(self._handle, 74, 80, 76, 94)
            self._coords(self._hammer, 64, 90, 80, 104)
            self._win_alpha(1.0)

    # ── idle pulse ────────────────────────────────────────────────────────────
    def _start_pulse(self):
        self._pulse_val = 0.0; self._pulse_dir = 1
        self._pulse()

    def _pulse(self):
        if not self._alive: return
        self._pulse_val += 0.06 * self._pulse_dir
        if   self._pulse_val >= 1.0: self._pulse_val = 1.0; self._pulse_dir = -1
        elif self._pulse_val <= 0.0: self._pulse_val = 0.0; self._pulse_dir =  1
        self._win_alpha(0.50 + 0.40 * self._pulse_val)
        self._pulse_job = self._root.after(55, self._pulse)

    def _stop_pulse(self):
        if self._pulse_job:
            try: self._root.after_cancel(self._pulse_job)
            except Exception: pass
            self._pulse_job = None

    # ── positioning ───────────────────────────────────────────────────────────
    def _snap(self):
        if not self._alive: return
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x, y = corner_pos(self._corner, sw, sh)
        self._cx, self._cy = x, y
        try: self._win.geometry(f"{CURSOR_W}x{CURSOR_H}+{x}+{y}")
        except Exception: pass

    def set_corner(self, corner: str):
        self._corner = corner
        self._snap()

    # ── smooth movement ───────────────────────────────────────────────────────
    def _move(self, tx: int, ty: int, steps: int, ms: int, done: Callable):
        if not self._alive: return
        sx, sy = self._cx, self._cy
        dx, dy = tx-sx, ty-sy

        def step(i):
            if not self._alive: return
            t = 1 - (1 - i/steps)**2
            x = int(sx + dx*t); y = int(sy + dy*t)
            self._cx, self._cy = x, y
            try: self._win.geometry(f"{CURSOR_W}x{CURSOR_H}+{x}+{y}")
            except Exception: pass
            if i < steps:
                self._root.after(ms, lambda: step(i+1))
            else:
                done()
        step(1)

    # ── glide → angry → SMASH → click → hold → return ────────────────────────
    def wake_and_click(self, sx: int, sy: int,
                       on_at_target: Callable,
                       on_done: Callable):
        if self.busy or not self._alive: return
        self.busy = True
        self._stop_pulse()
        self._state("wake")

        def arrived():
            if not self._alive: return
            self._state("angry")               # hammer raised, angry face
            self._root.after(420, smash)       # hold raised pose then swing

        def smash():
            if not self._alive: return
            self._state("smash")               # hammer down + POW!
            self._root.after(60, lambda: on_at_target(go_home))  # fire click

        def go_home():
            if not self._alive: return
            self._root.after(700, _return)     # hold smash so POW! is visible

        def _return():
            if not self._alive: return
            self._state("wake")
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            rx, ry = corner_pos(self._corner, sw, sh)
            self._move(rx, ry, steps=16, ms=13, done=finished)

        def finished():
            if not self._alive: return
            self._snap()
            self._state("idle")
            self._start_pulse()
            self.busy = False
            on_done()

        self._move(sx - 4, sy - 4, steps=22, ms=11, done=arrived)

    def destroy(self):
        self._alive = False
        self._stop_pulse()
        try: self._win.destroy()
        except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# Rule helpers
# ─────────────────────────────────────────────────────────────────────────────
def make_rule(trigger="", match="contains", delay=0.3, cooldown=3.0) -> dict:
    return {"id": str(uuid.uuid4()), "trigger": trigger, "match": match,
            "delay": delay, "cooldown": cooldown, "enabled": True}

def text_matches(ocr: str, trigger: str, match: str) -> bool:
    lo = ocr.lower(); tl = trigger.lower()
    if match == "contains":   return tl in lo
    if match == "exact word": return bool(re.search(r'\b'+re.escape(tl)+r'\b', lo))
    if match == "starts-with":
        return any(ln.strip().lower().startswith(tl) for ln in lo.splitlines())
    if match == "regex":
        try:    return bool(re.search(trigger, ocr, re.IGNORECASE))
        except: return False
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ScreenMonitor  (background thread)
# ─────────────────────────────────────────────────────────────────────────────
class ScreenMonitor(threading.Thread):
    def __init__(self, region: dict, rules: List[dict],
                 msg_q: queue.Queue, interval: float):
        super().__init__(daemon=True, name="monitor")
        self.region   = region
        self.rules    = rules
        self.msg_q    = msg_q
        self.interval = interval
        self._stop    = threading.Event()
        self._ack     = threading.Event()
        self._last: dict = {}

    def stop(self): self._stop.set(); self._ack.set()
    def ack(self):  self._ack.set()

    def run(self):
        with mss.MSS() as sct:
            while not self._stop.is_set():
                try:
                    self._cycle(sct)
                except Exception as exc:
                    self.msg_q.put(("log", "error", f"Scan error: {exc}"))
                self._stop.wait(self.interval)

    def _grab(self, sct) -> Image.Image:
        raw = sct.grab(self.region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        w, h = img.size
        if w < 600:
            img = img.resize((w*2, h*2), Image.LANCZOS)
        return img

    def _cycle(self, sct):
        pil  = self._grab(sct)
        # One OCR call gives us both the full text and per-word bounding boxes
        data = pytesseract.image_to_data(
            pil, output_type=pytesseract.Output.DICT, config="--psm 6")
        ocr  = " ".join(str(t) for t in data["text"] if str(t).strip())
        now  = time.time()

        for rule in list(self.rules):
            if not rule.get("enabled"):
                continue
            trigger = rule["trigger"].strip()
            if not trigger:
                continue
            rid = rule["id"]
            if now - self._last.get(rid, 0.0) < float(rule.get("cooldown", 3.0)):
                continue
            if not text_matches(ocr, trigger, rule.get("match", "contains")):
                continue

            delay = float(rule.get("delay", 0.3))
            self.msg_q.put(("log", "match", f'Matched "{trigger}" — clicking in {delay}s'))

            self._stop.wait(delay)
            if self._stop.is_set(): return

            # Re-grab + fresh OCR after delay for accurate position
            pil2  = self._grab(sct)
            data2 = pytesseract.image_to_data(
                pil2, output_type=pytesseract.Output.DICT, config="--psm 6")
            sx, sy = self._find_target(trigger, data2)

            self._last[rid] = time.time()
            self._ack.clear()
            self.msg_q.put(("click", rid, trigger, sx, sy))
            self._ack.wait(timeout=10.0)

    # ------------------------------------------------------------------
    # _find_target  — word-boundary aware, no false substring hits
    # ------------------------------------------------------------------
    def _find_target(self, trigger: str, data: dict) -> tuple:
        """
        Return screen (x, y) of matched text using word-level OCR data.
        Match priority:
          1. Exact whole-word match  (trigger == word)
          2. Exact multi-word phrase (trigger == "two words")
          3. Word starts with trigger
          4. Trigger is substring of word  (last resort)
          5. Region centre fallback
        """
        scale = 2 if self.region["width"] < 600 else 1
        tl    = trigger.lower().strip()

        try:
            # Build clean word list — skip empty strings and noise entries
            words = []
            for i in range(len(data["text"])):
                txt  = str(data["text"][i]).strip()
                conf = int(data["conf"][i])
                if not txt or conf < 0:
                    continue
                words.append({
                    "txt":    txt.lower(),
                    "left":   data["left"][i],
                    "top":    data["top"][i],
                    "right":  data["left"][i] + data["width"][i],
                    "bottom": data["top"][i]  + data["height"][i],
                })

            def to_screen(ws):
                cx = (min(w["left"] for w in ws) + max(w["right"]  for w in ws)) // 2
                cy = (min(w["top"]  for w in ws) + max(w["bottom"] for w in ws)) // 2
                return (self.region["left"] + cx // scale,
                        self.region["top"]  + cy // scale)

            # 1. Exact single-word match
            for w in words:
                if w["txt"] == tl:
                    return to_screen([w])

            # 2. Exact multi-word phrase
            parts = tl.split()
            np    = len(parts)
            if np > 1:
                for i in range(len(words) - np + 1):
                    if [words[i+j]["txt"] for j in range(np)] == parts:
                        return to_screen(words[i:i+np])

            # 3. Word starts with trigger
            for w in words:
                if w["txt"].startswith(tl):
                    return to_screen([w])

            # 4. Trigger is anywhere inside a word
            for w in words:
                if tl in w["txt"]:
                    return to_screen([w])

        except Exception:
            pass

        # 5. Region centre fallback
        return (self.region["left"] + self.region["width"]  // 2,
                self.region["top"]  + self.region["height"] // 2)


# ─────────────────────────────────────────────────────────────────────────────
# Region selector overlay
# ─────────────────────────────────────────────────────────────────────────────
class RegionSelector:
    def __init__(self, root: tk.Tk, cb: Callable):
        self._cb = cb; self._s = self._r = None
        w = tk.Toplevel(root)
        w.attributes("-fullscreen", True)
        w.attributes("-alpha", 0.30)
        w.attributes("-topmost", True)
        w.overrideredirect(True)
        w.configure(bg="#000018")
        self._win = w
        cv = tk.Canvas(w, bg="#000018", cursor="crosshair", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_text(w.winfo_screenwidth()//2, 38,
            text="Drag to select monitoring area   •   Esc = cancel",
            fill="white", font=("Segoe UI", 13))
        self._cv = cv
        cv.bind("<ButtonPress-1>",   self._press)
        cv.bind("<B1-Motion>",       self._drag)
        cv.bind("<ButtonRelease-1>", self._release)
        w.bind("<Escape>", lambda _: (w.destroy(), cb(None)))

    def _press(self, e):
        self._s = (e.x, e.y)
        if self._r: self._cv.delete(self._r)

    def _drag(self, e):
        if not self._s: return
        if self._r: self._cv.delete(self._r)
        self._r = self._cv.create_rectangle(*self._s, e.x, e.y,
                      outline="#34d399", width=2, fill="#1a3a2a")

    def _release(self, e):
        if not self._s: return
        x0,y0 = min(self._s[0],e.x), min(self._s[1],e.y)
        x1,y1 = max(self._s[0],e.x), max(self._s[1],e.y)
        self._win.destroy()
        if x1-x0 > 20 and y1-y0 > 20:
            self._cb({"left":x0,"top":y0,"width":x1-x0,"height":y1-y0})
        else:
            self._cb(None)


# ─────────────────────────────────────────────────────────────────────────────
# Rule dialog
# ─────────────────────────────────────────────────────────────────────────────
class RuleDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, rule: Optional[dict] = None):
        super().__init__(parent)
        self.result: Optional[dict] = None
        self.title("Edit Rule" if rule else "New Rule")
        self.geometry("440x300")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.focus_set()
        self._build(rule or {})
        self.wait_window()

    def _build(self, r: dict):
        f = tk.Frame(self, bg=BG, padx=22, pady=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        def lbl(text, row):
            tk.Label(f, text=text, bg=BG, fg=MUTED, font=("Segoe UI", 9)
                     ).grid(row=row, column=0, sticky="w", pady=(8,1))

        lbl("Trigger text — what to look for on screen:", 0)
        self._t = tk.StringVar(value=r.get("trigger",""))
        tk.Entry(f, textvariable=self._t, width=44, bg=CARD, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=("Segoe UI", 10), bd=6
                 ).grid(row=1, column=0, sticky="ew")

        lbl("Match type:", 2)
        self._m = tk.StringVar(value=r.get("match","contains"))
        ttk.Combobox(f, textvariable=self._m, values=MATCH_TYPES,
                     state="readonly", width=22
                     ).grid(row=3, column=0, sticky="w")

        num = tk.Frame(f, bg=BG)
        num.grid(row=4, column=0, sticky="w", pady=(10,0))
        for ltext, attr, val, lo, hi, inc in [
            ("Click delay (s)", "_dv", r.get("delay",   0.3), 0.0,   60.0, 0.1),
            ("Cooldown (s)",    "_cv", r.get("cooldown", 3.0), 0.5,  300.0, 0.5),
        ]:
            col = tk.Frame(num, bg=BG)
            col.pack(side="left", padx=(0,24))
            tk.Label(col, text=ltext, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            var = tk.DoubleVar(value=val)
            setattr(self, attr, var)
            tk.Spinbox(col, from_=lo, to=hi, increment=inc, textvariable=var,
                       width=9, bg=CARD, fg=TEXT, font=("Segoe UI", 10),
                       relief="flat", bd=0, highlightthickness=1,
                       highlightbackground=BORDER, buttonbackground=PANEL,
                       insertbackground=TEXT).pack()

        btns = tk.Frame(self, bg=BG)
        btns.pack(pady=(0,14))
        self._mk(btns,"Save",  ACCENT,"#5b21b6",self._save ).pack(side="left",padx=6)
        self._mk(btns,"Cancel",BORDER,PANEL,    self.destroy).pack(side="left")

    @staticmethod
    def _mk(p, t, bg, hov, cmd):
        b = tk.Button(p, text=t, bg=bg, fg=TEXT, font=("Segoe UI",10,"bold"),
                      relief="flat", padx=20, pady=6, command=cmd, cursor="hand2",
                      activebackground=hov, activeforeground=TEXT)
        b.bind("<Enter>", lambda _: b.config(bg=hov))
        b.bind("<Leave>", lambda _: b.config(bg=bg))
        return b

    def _save(self):
        t = self._t.get().strip()
        if not t:
            messagebox.showwarning("Required","Trigger text is empty.", parent=self); return
        self.result = {"trigger":t, "match":self._m.get(),
                       "delay":round(float(self._dv.get()),2),
                       "cooldown":round(float(self._cv.get()),2)}
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.rules:   List[dict]              = []
        self.region:  Optional[dict]          = None
        self.cfg      = {"scan_interval":0.8, "corner":"bottom-right", "tess_path":""}
        self.monitor: Optional[ScreenMonitor] = None
        self.cursor:  Optional[FloatingCursor]= None
        self.running  = False
        self.msg_q    = queue.Queue()
        self._dpi     = 1.0   # updated at _start() time

        self._root = tk.Tk()
        self._root.title("ScreenClick Pro")
        self._root.geometry("960x680")
        self._root.minsize(780, 540)
        self._root.configure(bg=BG)
        self._root.protocol("WM_DELETE_WINDOW", self._quit)

        self._setup_styles()
        self._build_ui()
        self._load()
        self._poll()

    # ── styles ────────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(); s.theme_use("clam")
        s.configure("TFrame",    background=BG)
        s.configure("TLabel",    background=BG, foreground=TEXT, font=("Segoe UI",10))
        s.configure("Treeview",  background=PANEL, fieldbackground=PANEL,
                    foreground=TEXT, font=("Segoe UI",10), rowheight=30)
        s.configure("Treeview.Heading", background=BG, foreground=MUTED,
                    font=("Segoe UI",9,"bold"), relief="flat")
        s.map("Treeview", background=[("selected",ACCENT)], foreground=[("selected","white")])
        s.configure("TCombobox", fieldbackground=CARD, foreground=TEXT,
                    selectbackground=ACCENT, font=("Segoe UI",10))
        s.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL)

    # ── ui ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._topbar()
        body = tk.Frame(self._root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(8,12))

        left = tk.Frame(body, bg=PANEL)
        left.pack(side="left", fill="both", expand=True, padx=(0,6))
        self._rules_panel(left)

        right = tk.Frame(body, bg=BG, width=310)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)
        self._side_panel(right)

    def _topbar(self):
        bar = tk.Frame(self._root, bg=PANEL, height=54)
        bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar, text="ScreenClick Pro", bg=PANEL, fg=TEXT,
                 font=("Segoe UI",14,"bold")).pack(side="left", padx=18, pady=12)
        self._sbtn = tk.Button(bar, text="Start",
            bg=GREEN, fg="#0f0f1a", font=("Segoe UI",10,"bold"),
            relief="flat", padx=20, pady=7, command=self._toggle,
            cursor="hand2", activebackground="#22c55e")
        self._sbtn.pack(side="right", padx=14, pady=10)
        self._dot  = tk.Label(bar, text="  ", bg=RED, width=2)
        self._dot.pack(side="right", padx=(0,4), pady=16)
        self._slbl = tk.Label(bar, text="Idle", bg=PANEL, fg=MUTED, font=("Segoe UI",9))
        self._slbl.pack(side="right")

    def _rules_panel(self, p):
        hdr = tk.Frame(p, bg=PANEL)
        hdr.pack(fill="x", padx=14, pady=(12,6))
        tk.Label(hdr, text="Automation Rules", bg=PANEL, fg=TEXT,
                 font=("Segoe UI",12,"bold")).pack(side="left")
        self._mk_btn(hdr,"+  Add Rule",ACCENT,"#5b21b6",self._add).pack(side="right")

        tw = tk.Frame(p, bg=PANEL)
        tw.pack(fill="both", expand=True, padx=14)
        cols = ("trigger","match","delay","cooldown","on")
        self._tree = ttk.Treeview(tw, columns=cols, show="headings", selectmode="browse")
        for c,(h,w,a) in zip(cols,[("Trigger Text",190,"w"),("Match",88,"center"),
                                    ("Delay",60,"center"),("Cooldown",80,"center"),
                                    ("On",40,"center")]):
            self._tree.heading(c, text=h)
            self._tree.column(c, width=w, anchor=a, minwidth=36)
        vsb = ttk.Scrollbar(tw, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", lambda _: self._edit())

        act = tk.Frame(p, bg=PANEL)
        act.pack(fill="x", padx=14, pady=(7,4))
        for txt,cmd,fg in [("Edit",self._edit,TEAL),
                            ("Toggle",self._toggle_rule,AMBER),
                            ("Delete",self._delete,RED)]:
            tk.Button(act, text=txt, bg=BORDER, fg=fg,
                      font=("Segoe UI",9), relief="flat", padx=10, pady=4,
                      command=cmd, cursor="hand2",
                      activebackground=CARD, activeforeground=fg
                      ).pack(side="left", padx=(0,6))

        io = tk.Frame(p, bg=PANEL)
        io.pack(fill="x", padx=14, pady=(2,10))
        for txt,cmd in [("Export rules",self._export),("Import rules",self._import_rules)]:
            tk.Button(io, text=txt, bg=PANEL, fg=MUTED, font=("Segoe UI",8),
                      relief="flat", padx=8, pady=2, command=cmd, cursor="hand2",
                      activebackground=CARD).pack(side="left", padx=(0,8))

    def _side_panel(self, p):
        box = tk.Frame(p, bg=PANEL)
        box.pack(fill="x", pady=(0,6))

        # Floating cursor section
        tk.Label(box, text="Floating Cursor", bg=PANEL, fg=TEXT,
                 font=("Segoe UI",11,"bold")).pack(anchor="w", padx=14, pady=(12,4))
        crow = tk.Frame(box, bg=PANEL)
        crow.pack(fill="x", padx=14)
        tk.Label(crow, text="Rest corner:", bg=PANEL, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="left")
        self._corner_var = tk.StringVar(value=self.cfg["corner"])
        cb = ttk.Combobox(crow, textvariable=self._corner_var,
                          values=CORNERS, state="readonly", width=14)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", self._on_corner_change)

        tk.Frame(box, bg=BORDER, height=1).pack(fill="x", padx=14, pady=8)

        # Region section
        tk.Label(box, text="Monitoring Region", bg=PANEL, fg=TEXT,
                 font=("Segoe UI",11,"bold")).pack(anchor="w", padx=14)
        self._rlbl = tk.Label(box, text="No region selected",
                              bg=PANEL, fg=MUTED, font=("Segoe UI",9))
        self._rlbl.pack(anchor="w", padx=14, pady=(4,6))
        rbtns = tk.Frame(box, bg=PANEL)
        rbtns.pack(fill="x", padx=14, pady=(0,10))
        self._mk_btn(rbtns,"Draw Region",TEAL,"#0369a1",self._pick).pack(side="left",padx=(0,8))
        self._mk_btn(rbtns,"Full Screen",BORDER,CARD,   self._full).pack(side="left")

        tk.Frame(box, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(2,8))

        # Config
        cfg = tk.Frame(box, bg=PANEL)
        cfg.pack(fill="x", padx=14, pady=(0,12))
        tk.Label(cfg, text="Scan interval (s):", bg=PANEL, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w")
        self._intv = tk.DoubleVar(value=self.cfg["scan_interval"])
        tk.Spinbox(cfg, from_=0.2, to=30.0, increment=0.1,
                   textvariable=self._intv, width=8,
                   bg=CARD, fg=TEXT, font=("Segoe UI",9), relief="flat",
                   bd=0, highlightthickness=1, highlightbackground=BORDER,
                   buttonbackground=PANEL, insertbackground=TEXT
                   ).pack(anchor="w", pady=(2,8))
        tk.Label(cfg, text="Tesseract path (leave blank if in PATH):",
                 bg=PANEL, fg=MUTED, font=("Segoe UI",9)).pack(anchor="w")
        tp = tk.Frame(cfg, bg=PANEL)
        tp.pack(fill="x", pady=(2,0))
        self._tess = tk.StringVar(value=self.cfg.get("tess_path",""))
        tk.Entry(tp, textvariable=self._tess, width=22,
                 bg=CARD, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI",8), bd=4
                 ).pack(side="left", fill="x", expand=True)
        tk.Button(tp, text="...", bg=BORDER, fg=TEXT, font=("Segoe UI",9),
                  relief="flat", padx=6, pady=3, command=self._browse_tess,
                  cursor="hand2", activebackground=CARD
                  ).pack(side="right", padx=(4,0))

        # Log
        log = tk.Frame(p, bg=PANEL)
        log.pack(fill="both", expand=True)
        lh = tk.Frame(log, bg=PANEL)
        lh.pack(fill="x", padx=14, pady=(10,4))
        tk.Label(lh, text="Activity Log", bg=PANEL, fg=TEXT,
                 font=("Segoe UI",11,"bold")).pack(side="left")
        tk.Button(lh, text="Clear", bg=PANEL, fg=MUTED, font=("Segoe UI",8),
                  relief="flat", padx=8, pady=2, command=self._clear_log,
                  cursor="hand2", activebackground=CARD).pack(side="right")
        self._log_w = tk.Text(log, bg="#080814", fg=MUTED,
                              font=("Consolas",8), relief="flat",
                              wrap="word", state="disabled",
                              padx=8, pady=6, bd=0,
                              selectbackground=ACCENT, insertbackground=TEXT)
        self._log_w.pack(fill="both", expand=True, padx=14, pady=(0,12))
        for tag,col in [("match",TEAL),("click",GREEN),("info",MUTED),
                         ("warn",AMBER),("error",RED),("ts","#2d3561")]:
            self._log_w.tag_configure(tag, foreground=col)

    @staticmethod
    def _mk_btn(parent, text, bg, hover, cmd):
        b = tk.Button(parent, text=text, bg=bg, fg=TEXT,
                      font=("Segoe UI",9,"bold"), relief="flat",
                      padx=12, pady=5, command=cmd, cursor="hand2",
                      activebackground=hover, activeforeground=TEXT)
        b.bind("<Enter>", lambda _: b.config(bg=hover))
        b.bind("<Leave>", lambda _: b.config(bg=bg))
        return b

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def _add(self):
        d = RuleDialog(self._root)
        if d.result:
            r = make_rule(**d.result)
            self.rules.append(r); self._refresh(); self._save()
            self._log("info", f'Added: "{r["trigger"]}"')

    def _edit(self):
        r = self._sel()
        if not r: return
        d = RuleDialog(self._root, r)
        if d.result:
            r.update(d.result); self._refresh(); self._save()
            self._log("info", f'Updated: "{r["trigger"]}"')

    def _toggle_rule(self):
        r = self._sel()
        if not r: return
        r["enabled"] = not r["enabled"]
        self._refresh(); self._save()
        self._log("info", f'"{r["trigger"]}" {"on" if r["enabled"] else "off"}')

    def _delete(self):
        r = self._sel()
        if not r: return
        if messagebox.askyesno("Delete", f'Delete "{r["trigger"]}"?', parent=self._root):
            self.rules.remove(r); self._refresh(); self._save()
            self._log("warn", f'Deleted: "{r["trigger"]}"')

    def _sel(self) -> Optional[dict]:
        s = self._tree.selection()
        if not s:
            messagebox.showinfo("Select a rule","Click on a rule first.", parent=self._root)
            return None
        return next((r for r in self.rules if r["id"]==s[0]), None)

    def _refresh(self):
        for i in self._tree.get_children(): self._tree.delete(i)
        for r in self.rules:
            self._tree.insert("","end", iid=r["id"],
                values=(r["trigger"],r["match"],
                        f'{r["delay"]}s',f'{r["cooldown"]}s',
                        "Yes" if r["enabled"] else "No"))

    # ── region ────────────────────────────────────────────────────────────────
    def _pick(self):
        self._root.iconify()
        self._root.after(380, lambda: RegionSelector(self._root, self._got_region))

    def _full(self):
        sw,sh = self._root.winfo_screenwidth(), self._root.winfo_screenheight()
        self._got_region({"left":0,"top":0,"width":sw,"height":sh})

    def _got_region(self, region):
        self._root.deiconify()
        if region:
            self.region = region
            self._rlbl.config(
                text=f"{region['width']} x {region['height']}  at ({region['left']},{region['top']})",
                fg=GREEN)
            self._log("info", f"Region: {region['width']}x{region['height']}")
            self._save()
        else:
            self._log("warn","Region selection cancelled.")

    def _on_corner_change(self, _=None):
        c = self._corner_var.get()
        self.cfg["corner"] = c
        if self.cursor: self.cursor.set_corner(c)
        self._save()
        self._log("info", f"Cursor corner set to: {c}")

    def _browse_tess(self):
        p = filedialog.askopenfilename(title="Select tesseract.exe",
                                        filetypes=[("Executable","*.exe"),("All","*.*")])
        if p: self._tess.set(p)

    # ── import / export ───────────────────────────────────────────────────────
    def _export(self):
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                          filetypes=[("JSON","*.json")])
        if p:
            with open(p,"w",encoding="utf-8") as f: json.dump(self.rules,f,indent=2)
            self._log("info",f"Exported {len(self.rules)} rules.")

    def _import_rules(self):
        p = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not p: return
        try:
            with open(p,encoding="utf-8") as f: loaded=json.load(f)
            for r in loaded: r["id"]=str(uuid.uuid4())
            self.rules.extend(loaded); self._refresh(); self._save()
            self._log("info",f"Imported {len(loaded)} rules.")
        except Exception as e:
            messagebox.showerror("Import failed",str(e),parent=self._root)

    # ── start / stop ──────────────────────────────────────────────────────────
    def _toggle(self):
        if self.running: self._stop()
        else:            self._start()

    def _start(self):
        if not self.region:
            messagebox.showwarning("No region","Select a screen region first.",
                                   parent=self._root); return
        if not any(r.get("enabled") for r in self.rules):
            messagebox.showwarning("No rules","Add at least one enabled rule.",
                                   parent=self._root); return
        tp = self._tess.get().strip()
        if tp: pytesseract.pytesseract.tesseract_cmd = tp

        self.cfg.update({"scan_interval":self._intv.get(),
                         "corner":self._corner_var.get(),
                         "tess_path":self._tess.get().strip()})
        self._save()

        # Compute DPI scale: mss captures physical pixels, pyautogui uses logical.
        # On a 150% DPI screen, mss returns 1.5× more pixels per logical unit.
        try:
            with mss.MSS() as _sct:
                _grab = _sct.grab({"left":0,"top":0,"width":100,"height":100})
                self._dpi = _grab.width / 100.0   # e.g. 1.5 on 150% DPI
        except Exception:
            self._dpi = 1.0
        self._log("info", f"DPI scale detected: {self._dpi:.2f}x")

        self.cursor  = FloatingCursor(self._root, self.cfg["corner"])
        self.monitor = ScreenMonitor(self.region, self.rules, self.msg_q,
                                     self.cfg["scan_interval"])
        self.monitor.start()
        self.running = True

        self._sbtn.config(text="Stop", bg=RED, activebackground="#dc2626")
        self._dot.config(bg=GREEN)
        self._slbl.config(text="Running", fg=GREEN)
        n = sum(1 for r in self.rules if r.get("enabled"))
        self._log("info", f"Started — {n} rule(s), cursor at {self.cfg['corner']}")

    def _stop(self):
        if self.monitor: self.monitor.stop(); self.monitor = None
        if self.cursor:  self.cursor.destroy(); self.cursor = None
        self.running = False
        self._sbtn.config(text="Start", bg=GREEN, activebackground="#22c55e")
        self._dot.config(bg=RED)
        self._slbl.config(text="Idle", fg=MUTED)
        self._log("info","Stopped.")

    # ── queue poll ────────────────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                if msg[0] == "log":
                    self._log(msg[1], msg[2])
                elif msg[0] == "click":
                    _, rid, trigger, sx, sy = msg
                    # DPI: mss uses physical pixels, pyautogui uses logical pixels
                    dpi = getattr(self, "_dpi", 1.0)
                    lx  = int(sx / dpi)
                    ly  = int(sy / dpi)
                    self._log("click", f'Targeting "{trigger}" at logical ({lx},{ly})')

                    def _do_click(go_home, lx=lx, ly=ly, trigger=trigger):
                        # IMPORTANT: hide the cursor overlay first — its solid arrow
                        # shape is on top of the target and would intercept the click.
                        cur = self.cursor
                        if cur and cur._alive:
                            try: cur._win.withdraw()
                            except Exception: pass

                        def _fire():
                            try:
                                pyautogui.click(lx, ly)
                                self._log("click", f'Clicked "{trigger}" at ({lx},{ly})')
                            except Exception as e:
                                self._log("error", f"Click failed: {e}")
                            # Restore cursor window, then animate home
                            if cur and cur._alive:
                                try: cur._win.deiconify()
                                except Exception: pass
                            self._root.after(80, go_home)

                        # Brief wait after hiding so window is gone before click
                        self._root.after(60, _fire)

                    def _done(rid=rid):
                        self._log("info", "Cursor back in corner.")
                        if self.monitor: self.monitor.ack()

                    if self.cursor and not self.cursor.busy:
                        self.cursor.wake_and_click(lx, ly, _do_click, _done)
                    else:
                        try:
                            pyautogui.click(lx, ly)
                            self._log("click", f'Direct click "{trigger}" ({lx},{ly})')
                        except Exception as e:
                            self._log("error", f"Direct click failed: {e}")
                        if self.monitor:
                            self.monitor.ack()
        except queue.Empty:
            pass
        self._root.after(80, self._poll)

    # ── log ───────────────────────────────────────────────────────────────────
    def _log(self, kind: str, msg: str):
        self._log_w.config(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_w.insert("end", f"[{ts}]  ", "ts")
        self._log_w.insert("end", msg+"\n", kind)
        self._log_w.see("end")
        self._log_w.config(state="disabled")

    def _clear_log(self):
        self._log_w.config(state="normal")
        self._log_w.delete("1.0","end")
        self._log_w.config(state="disabled")

    # ── save / load ───────────────────────────────────────────────────────────
    def _save(self):
        self.cfg["scan_interval"] = round(float(self._intv.get()), 2)
        self.cfg["tess_path"]     = self._tess.get().strip()
        try:
            with open(SAVE_PATH,"w",encoding="utf-8") as f:
                json.dump({"rules":self.rules,"region":self.region,"cfg":self.cfg},f,indent=2)
        except Exception as e:
            self._log("error",f"Save failed: {e}")

    def _load(self):
        if not os.path.exists(SAVE_PATH):
            self._log("info","No saved data — starting fresh."); return
        try:
            with open(SAVE_PATH,encoding="utf-8") as f: d=json.load(f)
            self.rules  = d.get("rules",[])
            self.region = d.get("region")
            self.cfg.update(d.get("cfg",{}))
            self._intv.set(self.cfg.get("scan_interval",0.8))
            self._tess.set(self.cfg.get("tess_path",""))
            self._corner_var.set(self.cfg.get("corner","bottom-right"))
            if self.region:
                r=self.region
                self._rlbl.config(
                    text=f"{r['width']} x {r['height']}  at ({r['left']},{r['top']})",
                    fg=GREEN)
            self._refresh()
            self._log("info",f"Loaded {len(self.rules)} rule(s).")
        except Exception as e:
            self._log("error",f"Load failed: {e}")

    def _quit(self):
        self._stop(); self._save(); self._root.destroy()

    def run(self):
        self._root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        App().run()
    except Exception as e:
        _crash(e)
