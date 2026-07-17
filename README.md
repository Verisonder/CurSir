<p align="center">
  <img src="assets/logo.png" width="128" alt="CurSir logo" />
</p>

<h1 align="center">CurSir</h1>

<p align="center"><em>Cursor, but <strong>Sir</strong>.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.2-379ED6" alt="version" />
  <img src="https://img.shields.io/badge/platform-Windows-379ED6" alt="platform" />
  <img src="https://img.shields.io/badge/python-3.12-379ED6" alt="python" />
  <img src="https://img.shields.io/badge/vision-Gemini-379ED6" alt="gemini" />
</p>

---

CurSir is a Windows desktop assistant that **acts on your behalf**. Press a
hotkey, type a request in plain language, and CurSir screenshots your screen,
sends it to Google's Gemini vision model, and does the work — it moves the
mouse, clicks, double-clicks, types and pastes text, submits forms, launches
apps, opens URLs, scrolls, and drags-and-drops. A courteous butler that
addresses you as **"sir"** and never gets in the way.

Because it reasons over a screenshot rather than hard-coded selectors, it works
across apps it has never seen — your OS settings, Photoshop, a browser, a game
launcher, whatever is in front of you.

> **Guide, or act.** Confirm every step with **Enter**, or switch on **Auto
> mode** and let CurSir perform each step itself. **Esc** stops everything,
> instantly, at any point.

---

## Features

**What it can do**
- **Click** and **double-click** — single clicks for buttons and links, double for desktop / File Explorer icons.
- **Type & paste** — fills fields via the clipboard, with an optional Enter to submit and a short wait for the page to settle.
- **Launch apps** — opens an app directly instead of hunting for its icon. Purpose-based requests resolve against your **installed apps** (a Start-menu scan), so *"make a video"* opens your installed video editor.
- **Open URLs in one step** — jumps straight to a full URL (e.g. a search or a channel) in your preferred browser, skipping the launch-then-type dance.
- **Scroll** — up / down / left / right, then re-screenshots so it can reveal and act on off-screen content.
- **Drag & drop** — presses, moves gradually so the app registers the drag, and releases.
- **Multi-step tasks** — keeps going until the job is done; it knows that opening a browser or app is almost never the last step.

**How it feels**
- **Glow overlay** that follows your live cursor and stays lit through the whole task, landing on the exact target for each step.
- **Focus grab** so the command box takes your keystrokes instantly, even though Windows normally denies focus to windows spawned from a global hotkey.
- **JARVIS-style thinking spinner** while it reasons — choose **wide** (HUD scan-lines) or **compact** (just the reactor).
- **Preferred-browser aware** — browser tasks open *your* default/chosen browser, and the on-screen message names the real browser, not the model's guess.
- **Honest errors** — rate-limit / quota, API-key, rejected-request and network problems are named plainly, so you know what happened. No silent hangs, no endless retries.

**Quality & precision**
- **Zoom-refine pass** — crops in ~3× around the first guess for a tighter, more accurate target.
- **Three quality profiles** — trade speed for precision (see below).
- **Google Search grounding** on the highest profile for tricky, unfamiliar UI.

**Living in your system**
- **System-tray app** — right-click the tray icon for Settings; single-instance so you never get two.
- **Self-updating** — pulls the newest version from this repo and restarts, no reinstall (details below).
- **Start with Windows** and **arm-on-launch** options.
- **Auto mode** for hands-free multi-step tasks.

---

## Install

### The easy way — the installer (no Python needed)

Download **`CurSir-Setup.exe`** from the [Releases](https://github.com/Verisonder/CurSir/releases) page and run it. It installs to `%LOCALAPPDATA%\CurSir`, bundles its own Python runtime, and adds a Start-menu shortcut (a desktop shortcut is an optional checkbox). CurSir launches into **Settings** — paste your Gemini key, pick a hotkey, and press **Start CurSir**.

> The app is unsigned, so Windows SmartScreen / Smart App Control may warn on first run. Choose *More info -> Run anyway* (or disable Smart App Control) to proceed.

### From source

```bash
pip install PySide6 pynput
python cursir.py
```

Requires **Python 3.12+** on Windows.

---

## Settings

Right-click the tray icon -> **Settings**. Everything lives here and saves to `~/.cursir.json`:

| Setting | What it does |
| --- | --- |
| **Gemini API key** | Your key from [Google AI Studio](https://aistudio.google.com/) (a free tier exists). Or set `GEMINI_API_KEY` in your environment. |
| **Hotkey** | Default `Ctrl+Win`. Presets: `Ctrl+Alt+Space`, `Ctrl+Shift+Space`, `Ctrl+Alt+C`, `Ctrl+Shift+C`. |
| **Quality** | `fast` / `balanced` / `accurate`. |
| **Browser** | Which browser URL / web tasks use — *system default* or any installed browser. |
| **Thinking animation** | `wide` or `compact` spinner. |
| **Auto mode** | Perform each step automatically instead of waiting for Enter. |
| **Check for updates automatically** | Self-update on launch. |
| **Start CurSir when Windows starts** | Boot autostart. |

### Quality profiles

| Profile | Speed | Thinking budget | Zoom-refine | Search grounding | Screenshot |
| --- | --- | --- | --- | --- | --- |
| **fast** | fastest, fewest API calls | off | off | off | 1280px |
| **balanced** *(default)* | middle ground | on | on | off | 1280px |
| **accurate** | slowest, most robust | high | on | **on** | 1600px |

> On Gemini's free tier (~5 requests/min), **fast** paces best — richer profiles make several calls per step and can hit the rate limit on longer tasks.

---

## Use it

1. Press your hotkey — the cursor glows and a command box appears with focus.
2. Type what you want — *"turn on dark mode"*, *"open my email and start a new message"*, *"search YouTube for penguinz0"*.
3. CurSir moves your cursor to the right element, glows it, and shows the step.
4. Press **Enter** to perform it (or nothing, in Auto mode). It advances step by step until done.
5. **Esc** cancels the whole task at any moment — even mid-action.

---

## How it works

1. A global hotkey fires the overlay; the command box force-grabs keyboard focus.
2. On your request, CurSir hides its own overlays and screenshots the virtual desktop.
3. The screenshot goes to **Gemini vision** with a strict JSON contract asking for the next element as a tight bounding box (normalized 0-1000) plus the action to take.
4. An optional **zoom-refine** pass crops in around that box for precision.
5. The box maps to real screen coordinates; the cursor moves there and glows.
6. On confirmation, an OS-level action fires — click, type, launch, open-URL, scroll or drag.
7. Repeat until the model marks the task done. **Esc** sets a stop flag every queued step checks, so nothing "comes back to life" after you cancel.

---

## Self-update

CurSir runs from source, so updating is cheap: it downloads the new `cursir.py`
(and refreshes `cursir.ico`) from this repo and restarts — **no multi-hundred-MB
rebuild**. The install is verified before it applies (it confirms the new code
actually propagated, guarding a CDN race), runs off the UI thread with a
watchdog so it can't hard-stick, and flushes the Windows shell icon cache so
shortcut icons pick up a new logo. Fresh installs still come from the Releases
installer.

---

## Status & limitations

- **Windows only** — CurSir leans on Windows-specific behaviour (focus grabbing, the installed-apps / browser registry scan, the shell icon cache).
- **Unsigned build** — SmartScreen / Smart App Control may block it until signed. Code-signing for wide distribution is on the roadmap.
- **Clicks can occasionally land a touch high** on some setups; refinement is ongoing.
- **Free-tier rate limits** are the usual cause of a "no reply" — wait a minute, or use **fast** quality.

---

## Build the installer

Pushing a `v*` tag triggers the GitHub Actions workflow (`.github/workflows/build.yml`, `windows-latest`): it downloads embeddable Python 3.12, installs PySide6 + pynput into the bundle, copies in `cursir.py` + `cursir.ico`, and packages **`CurSir-Setup.exe`** with Inno Setup. The result is attached to the tagged release.

---

<p align="center"><sub>Accent <code>#379ED6</code> &middot; a Verisonder project</sub></p>
