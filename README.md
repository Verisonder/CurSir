# CurSir

**A cursor that does things for you.** Press a hotkey, tell it what you want in
plain words, and CurSir looks at your screen, figures out where the right
button is, moves your cursor onto it and glows it. You press **Enter** to click.
Multi-step tasks advance one step at a time.

> Cursor, but *Sir*.

CurSir uses Google's Gemini vision (with live Google Search) to locate UI
elements in a screenshot, so it works across apps it has never seen — Photoshop,
your OS settings, a website, whatever is in front of you.

---

## Easiest: run the .exe (no Python)

Download `CurSir.exe`, run it. A tray icon appears — right-click it → **Settings**
to paste your Gemini key and pick your hotkey. That's it.

*(Building the exe yourself: on Windows, run `build_windows.bat`. It produces
`dist\CurSir.exe`, a single standalone file that bundles Python inside.)*

## Or run from source

```
pip install PySide6 pynput
python cursir.py
```

## Settings

Right-click the tray icon → **Settings**. Everything lives here:

- **Gemini API key** — get a free one at Google AI Studio
- **Hotkey** — default `Ctrl+Win`; pick another if it clashes
- **Quality** — `fast` / `balanced` / `accurate` (accurate adds live Google Search)
- **Check for updates automatically**
- **Start CurSir when Windows starts**

Settings are saved to `~/.cursir.json`. You can also set the key via the
`GEMINI_API_KEY` environment variable.

## Use it

1. Press your hotkey — the cursor glows, a command box appears.
2. Type what you want (*"turn on dark mode"*, *"where is export as PNG"*).
3. CurSir moves your cursor onto the right element and glows it.
4. Press **Enter** to click. More steps? It points at the next one. **Esc** stops.

## Updates

CurSir checks this repo for a newer version (tray → **Check for updates**, or
automatically on launch). Running from source, it can update itself and restart.
The self-updating **.exe** path is wired when the exe build is finalized.

---

## Status

**v0.1 — experimental.** Core pipeline ported from a working screen-guide
feature; still needs real-machine testing on:

- the **Ctrl+Win** hotkey (Windows treats the Win key specially — switch it in
  Settings if it misbehaves)
- **DPI scaling** at 125% / 150% (a click may land slightly off)
- **click timing** (a first click occasionally just focusing the target app)

## How it works

Screenshot of the active screen → Gemini with a strict JSON contract asking for
the next element as a tight bounding box (normalized 0–1000) → box mapped to
screen coordinates → cursor moved + glow drawn → **Enter** fires an OS-level
click → repeat until done.
