# CurSir

**A cursor that does things for you.** Press a hotkey, tell it what you want in
plain words, and CurSir looks at your screen, figures out where the right
button is, moves your cursor onto it and glows it. You press Enter to click.
If the task needs more steps, it points at the next one.

> Cursor, but *Sir*.

CurSir uses Google's Gemini vision (with live Google Search) to locate UI
elements in a screenshot, so it works across apps it has never seen —
Photoshop, your OS settings, a website, whatever is in front of you.

---

## Install

```
pip install PySide6 pynput
```

## Set your Gemini key

Either set an environment variable:

```
GEMINI_API_KEY=your_key_here
```

…or create a file at `~/.cursir.json`:

```json
{ "gemini_key": "your_key_here", "quality": "balanced" }
```

Get a free key at Google AI Studio.

## Run

```
python cursir.py
```

Then, anywhere:

1. Press **Ctrl + Win** — your cursor glows and a command box appears.
2. Type what you want (e.g. *"turn on dark mode"*, *"where is export as PNG"*).
3. CurSir moves your cursor onto the right element and glows it.
4. Press **Enter** to click it.
5. If there are more steps, it points at the next one. Press **Esc** to stop.

## Quality

Set `"quality"` in `~/.cursir.json`:

| mode | speed | notes |
|------|-------|-------|
| `fast` | fastest | no live web search |
| `balanced` | default | a little reasoning |
| `accurate` | slowest | adds live Google Search — best for "where is X in <app>" |

---

## Status

**v0.1 — experimental.** The core pipeline is ported from a working screen-guide
feature, but this standalone build still needs real-machine testing on:

- the **Ctrl+Win** hotkey (Windows treats the Win key specially — may switch to
  another combo)
- **DPI scaling** on displays at 125% / 150% (click may land slightly off)
- **click timing** (first click occasionally just focusing the target app)

Issues and fixes welcome.

## How it works

Screenshot of the active screen → sent to Gemini with a strict JSON contract
asking for the single next element as a tight bounding box (normalized 0–1000)
→ box mapped to screen coordinates → cursor moved + glow drawn → Enter fires an
OS-level click → repeat until the task is done.
