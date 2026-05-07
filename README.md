# ScreenClick Pro

A Python desktop automation tool that watches your screen with OCR and auto-clicks when it finds matching text — guided by an animated anime chibi character that runs to the target, angrily raises a hammer, and **SMASHES** the click.

---

## How It Works

1. You draw a region on your screen to monitor
2. You add rules — text to look for and how to match it
3. Hit **Start** — the chibi character appears in the corner and sleeps
4. When OCR finds a match, the chibi wakes up, runs to the word, raises its hammer, and smashes the click with a **POW!**
5. It returns to the corner and goes back to sleep, waiting for the next match

---

## Features

- **OCR-powered detection** — reads text directly off the screen using Tesseract
- **Animated chibi cursor** — sleeps in corner → runs to target → angry face + hammer raise → SMASH + POW! → returns home
- **Four match types** — `contains`, `exact word`, `starts-with`, `regex`
- **Word-boundary aware clicking** — won't click "network" when you asked for "work"; uses per-word bounding boxes from OCR
- **DPI-aware** — detects your screen scaling (e.g. 150%) and compensates so clicks land on the right pixel
- **Multiple simultaneous rules** — all enabled rules run in parallel
- **Cooldown per rule** — prevents the same rule from firing too fast
- **Click delay** — configurable wait after a match before clicking (lets pages load)
- **Activity log** — timestamped log of every match, click, and error
- **Config persistence** — rules, region, and settings saved to `~/.screenclick_pro.json`
- **Import / Export rules** — share rule sets as JSON files
- **Dark theme UI** — clean dark interface built with tkinter

---

## Chibi Character States

| State | Look | When |
|---|---|---|
| **Sleeping** | Closed eyes, "zzz" floating, soft purple pulse | Idle in corner |
| **Running** | Big anime eyes, rosy cheeks | Moving toward target |
| **Angry** | Angry brows, gritted teeth, "!!" text, hammer raised | Arrived — ~420 ms hold |
| **SMASH** | Hammer slams down, POW! + impact burst | Click fires at this moment |
| **Returning** | Holds smash pose 700 ms, then glides home | After click |

Total time at target: ~1.2–1.4 seconds per click.

---

## Requirements

### Python packages

```
mss>=9.0
Pillow>=10.0
pytesseract>=0.3.10
pyautogui>=0.9.54
```

Install with:

```bash
pip install mss Pillow pytesseract pyautogui
```

### Tesseract OCR engine

ScreenClick Pro uses [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) for reading text off the screen. You must install it separately.

**Windows:**
1. Download the installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
2. Run the installer (default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
3. Either add it to your system PATH, or paste the path into the **Tesseract path** field in the app

**macOS:**
```bash
brew install tesseract
```

**Linux:**
```bash
sudo apt install tesseract-ocr
```

---

## Installation

```bash
git clone https://github.com/dkshahzohaib/screenclick-pro.git
cd screenclick-pro
pip install -r requirements.txt
python screenclick.py
```

---

## Usage Guide

### Step 1 — Select a monitoring region

Click **Draw Region** and drag a rectangle over the part of the screen you want to watch.  
Or click **Full Screen** to monitor the entire display.

The region is shown in green once set: `1920 x 1080 at (0, 0)`.

### Step 2 — Add rules

Click **+ Add Rule** and fill in:

| Field | Description |
|---|---|
| **Trigger text** | The word or phrase to look for on screen |
| **Match type** | How to compare (see match types below) |
| **Click delay** | Seconds to wait after a match before clicking (default 0.3s) |
| **Cooldown** | Minimum seconds between clicks for this rule (default 3.0s) |

#### Match types explained

| Type | Behaviour | Example trigger `"work"` |
|---|---|---|
| `contains` | Trigger appears anywhere in the OCR text | Matches "network", "working", "teamwork" |
| `exact word` | Whole word match only | Matches "work" but NOT "network" |
| `starts-with` | Any line starting with the trigger | Matches "working hours: 9am" |
| `regex` | Full Python regex pattern | `work(ing)?` matches "work" and "working" |

### Step 3 — Configure the cursor corner

Use the **Rest corner** dropdown to pick which corner the chibi sleeps in:
- `bottom-right` (default)
- `bottom-left`
- `top-right`
- `top-left`

### Step 4 — Set Tesseract path (if needed)

If Tesseract is not in your system PATH, click **...** next to the Tesseract path field and browse to `tesseract.exe`.

### Step 5 — Start

Click the green **Start** button. The chibi appears in the corner and begins sleeping.

When a rule matches:
- The chibi wakes up and runs to the matched word
- Angry face + hammer raises
- Hammer **SMASHES** down — click fires
- POW! impact burst holds for ~700 ms
- Chibi glides back to the corner and falls asleep

Click **Stop** to end the session.

---

## Rule Management

| Action | How |
|---|---|
| Add rule | Click **+ Add Rule** |
| Edit rule | Double-click a rule in the list, or select and click **Edit** |
| Enable / Disable | Select a rule and click **Toggle** |
| Delete | Select a rule and click **Delete** |
| Export rules | Click **Export rules** — saves to a `.json` file |
| Import rules | Click **Import rules** — loads from a `.json` file |

---

## Settings

| Setting | Description |
|---|---|
| **Scan interval** | How often OCR runs on the region (seconds). Lower = faster response, higher CPU. Default: 0.8s |
| **Click delay** | Per-rule wait after match before clicking |
| **Cooldown** | Per-rule minimum time between repeated clicks |
| **Cursor corner** | Which corner the chibi rests in |
| **Tesseract path** | Path to `tesseract.exe` if not in system PATH |

All settings are saved automatically to `~/.screenclick_pro.json`.

---

## Troubleshooting

**Chibi points to the right word but the click misses**

Check your display scaling. Go to Windows Display Settings and note your scale percentage. The app detects this automatically on start — check the Activity Log for `DPI scale detected: X.XXx`.

**OCR isn't finding text**

- Make sure Tesseract is installed and the path is set correctly
- Try increasing the monitoring region (smaller regions are upscaled automatically but may still miss small text)
- Lower the scan interval so it checks more frequently
- Use `contains` match type first to confirm detection is working

**The app found the text but clicked the wrong word**

Switch the match type from `contains` to `exact word`. The `contains` type matches substrings, so `"work"` will match `"network"`. Exact word uses whole-word boundaries.

**Click fires but nothing happens on screen**

The overlay window briefly hides itself before clicking (so it doesn't intercept the click event), but on some systems the timing may need adjusting. Check the Activity Log — if you see `Clicked "word" at (x, y)` the click fired; the issue is the target app not responding to simulated clicks. Try running ScreenClick Pro as Administrator.

---

## Project Structure

```
screenclick-pro/
├── screenclick.py       # Full application — single file
├── requirements.txt     # Python dependencies
└── README.md
```

The app is intentionally a single file with no external assets. Everything — the UI, the chibi character, OCR logic, and click engine — lives in `screenclick.py`.

### Key classes

| Class | Purpose |
|---|---|
| `FloatingCursor` | The animated chibi overlay window. Handles all states, movement, and hammer animation |
| `ScreenMonitor` | Background thread — grabs screen region, runs OCR, matches rules, sends click messages via queue |
| `RegionSelector` | Fullscreen drag-to-select overlay for picking the monitoring area |
| `RuleDialog` | Modal dialog for creating and editing rules |
| `App` | Main application window, orchestrates everything |

### How the click pipeline works

```
ScreenMonitor thread          Main thread (tkinter)
─────────────────────         ──────────────────────────────
OCR finds match
  └─ puts ("click", ...) ──► _poll() reads queue
       on msg_q                └─ calls cursor.wake_and_click()
                                    └─ chibi glides to target
ScreenMonitor blocks                └─ "angry" state (hammer up)
  on _ack.wait(10s)                 └─ "smash" state (hammer down)
                                    └─ overlay hides (withdraw)
                                    └─ pyautogui.click(x, y)
                                    └─ overlay shows (deiconify)
                                    └─ hold POW! 700ms
monitor.ack() called ◄──────────   └─ chibi returns home
ScreenMonitor unblocks              └─ monitor.ack() sent
  └─ continues scanning
```

---

## Ideas for Future Features

- **Multi-step sequences** — chain rules so step B fires after step A
- **Type text after clicking** — auto-fill forms after a match
- **Image/template matching** — click icons and buttons that have no text
- **Global hotkey** — start/stop without opening the main window
- **System tray icon** — run silently in the background
- **Sound alerts** — beep or TTS when a rule fires
- **Screenshot logging** — save a screenshot every time a click fires
- **Rule profiles** — switch between saved rule sets (work, games, etc.)

---

## License

MIT — do whatever you want with it.
