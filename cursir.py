#!/usr/bin/env python3
"""
CurSir — a cursor that does things for you.

Press the hotkey (Ctrl+Win by default). Your cursor gets a glowing ring and a
little command box appears next to it. Tell it what you want in plain words:

    "turn on dark mode in Photoshop"
    "where is the export as PNG option"
    "open the layer blending settings"

CurSir screenshots your active screen, asks Gemini (with live Google Search)
where the next thing to click is, moves your cursor onto it and glows it, and
shows a one-line instruction. Press ENTER to click it. If the task needs more
steps, CurSir points at the next one, and so on. ESC cancels at any time.

RUN:    python cursir.py
NEEDS:  pip install PySide6 pynput
KEY:    set the GEMINI_API_KEY environment variable, OR create the file
        ~/.cursir.json  with:   {"gemini_key": "YOUR_KEY_HERE"}

v0.1 — first cut. See the notes Claude sent alongside this for the parts that
still need real-machine testing (hotkey behaviour, DPI scaling, click timing).
"""

import os
import sys
import json
import base64
import math
import platform

from PySide6.QtCore import (Qt, QObject, Signal, QTimer, QPoint,
                            QBuffer, QByteArray, QIODevice)
from PySide6.QtGui import (QGuiApplication, QCursor, QColor, QPainter, QPen,
                           QFont)
from PySide6.QtWidgets import (QApplication, QWidget, QLineEdit, QLabel,
                               QVBoxLayout)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".cursir.json")
ACCENT = "#379ED6"          # CurSir blue

# (thinking budget, google-search grounding, screenshot width)
QUALITY = {
    "fast":     (0,   False, 1280),
    "balanced": (128, False, 1280),
    "accurate": (512, True,  1600),
}


def load_cfg():
    cfg = {"gemini_key": os.environ.get("GEMINI_API_KEY", "").strip(),
           "quality": "balanced"}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if v:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


# ---------------------------------------------------------------- Gemini ----
def gemini_locate(key, task, done_list, shot_b64, think, ground):
    """Ask Gemini where the next UI element is. Returns a dict shaped like
    {found, box:[t,l,b,r], label, say, last, done} or {} on failure."""
    import urllib.request
    import urllib.error

    step_no = len(done_list) + 1
    done_txt = ("Steps ALREADY completed by the user: "
                + "; ".join(f"{i+1}) {d}" for i, d in enumerate(done_list))
                if done_list else "This is the FIRST step.")

    persona = (
        "You are CurSir, an on-screen assistant that controls the user's "
        "mouse. The user asked you to do or find something in the app shown "
        "in the screenshot. Work out the ACTUAL correct way to do it using "
        "what you know and Google Search when useful - do NOT guess from the "
        "screenshot alone. Then find the SINGLE next UI element the user must "
        "click, and locate it PRECISELY in the screenshot. Respond with ONLY "
        "minified JSON, no markdown, no code fences, exactly this shape: "
        '{"found":true,"box":[100,200,140,320],"label":"element name",'
        '"say":"short friendly instruction","last":false,"done":false} . '
        "box is the TIGHT bounding box of just that ONE element (not its "
        "whole row, toolbar or panel), in the order top, left, bottom, "
        "right, each normalized 0-1000 of the image height (y) and width "
        "(x). box MUST contain four plain INTEGERS like [112,204,146,318] - "
        "NEVER letters or placeholder words. Hug the element's real edges - "
        "a small button gives a small box. Keep 'say' under 22 words and "
        "make it match how the app actually works. Set \"last\":true when "
        "THIS element is the FINAL step that completes the whole task (a "
        "simple one-click task is last:true on the very first step) - do NOT "
        "set last:true if the user will still need another step after this "
        "one. Set done=true (and make 'say' a short wrap-up) only when the "
        "task is ALREADY fully complete in the screenshot with nothing left "
        "to point at. Set found=false if the needed element isn't on screen "
        "yet (then 'say' explains what to open or click first).")

    contents = [{"role": "user", "parts": [
        {"text": f"Task: {task}\nStep number: {step_no}\n{done_txt}"},
        {"inline_data": {"mime_type": "image/jpeg", "data": shot_b64}}]}]

    models = ("gemini-flash-latest", "gemini-3.5-flash",
              "gemini-3.1-flash-lite", "gemini-flash-lite-latest",
              "gemini-2.5-flash", "gemini-2.5-flash-lite")

    def make_body(model, grounded):
        b = {"contents": contents,
             "systemInstruction": {"parts": [{"text": persona}]},
             "generationConfig": {"maxOutputTokens": 400, "temperature": 0.6}}
        if model.startswith("gemini-2.5"):
            b["generationConfig"]["thinkingConfig"] = {"thinkingBudget": think}
        else:
            tc = {"thinkingBudget": think}
            tc["thinkingLevel"] = ("none" if think == 0
                                   else "low" if think <= 256 else "medium")
            b["generationConfig"]["thinkingConfig"] = tc
        if grounded:
            b["tools"] = [{"google_search": {}}]
        return json.dumps(b).encode()

    def parse(payload):
        raw = ""
        for c in payload.get("candidates", []):
            for pt in c.get("content", {}).get("parts", []):
                raw += pt.get("text", "")
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        if not raw.startswith("{"):
            i, j = raw.find("{"), raw.rfind("}")
            if i != -1 and j != -1 and j > i:
                raw = raw[i:j + 1]
        return json.loads(raw)

    gseq = (True, False) if ground else (False,)
    for m in models:
        url = ("https://generativelanguage.googleapis.com/v1beta/"
               f"models/{m}:generateContent?key={key}")
        for grounded in gseq:
            try:
                req = urllib.request.Request(
                    url, data=make_body(m, grounded),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=35) as r:
                    return parse(json.loads(r.read().decode()))
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue
    return {}


# ------------------------------------------------------------- overlays ----
class Glow(QWidget):
    """Full-desktop, click-through overlay that pulses a ring at a point."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._pt = QPoint(0, 0)
        self._phase = 0.0
        self._on = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _cover(self):
        vg = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(vg)

    def point_at(self, gx, gy):
        self._cover()
        self._pt = QPoint(int(gx) - self.x(), int(gy) - self.y())
        self._on = True
        if not self._timer.isActive():
            self._timer.start(33)
        self.show()
        self.raise_()
        self.update()

    def stop(self):
        self._on = False
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, _e):
        if not self._on:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = 24 + 8 * (1 + math.sin(self._phase)) / 2
        for i, alpha in enumerate((55, 120, 220)):
            col = QColor(ACCENT)
            col.setAlpha(alpha)
            p.setPen(QPen(col, max(1.0, 3 - i * 0.7)))
            rr = r + (2 - i) * 7
            p.drawEllipse(self._pt, int(rr), int(rr))
        p.end()


class Box(QWidget):
    """Small command / instruction window. Two modes: 'ask' takes a typed
    request; 'step' shows an instruction and waits for Enter to click."""

    submitted = Signal(str)
    confirmed = Signal()          # Enter in step mode = click
    canceled = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._mode = "ask"

        wrap = QWidget(self)
        wrap.setObjectName("wrap")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        self.edit = QLineEdit(wrap)
        self.edit.setPlaceholderText("tell CurSir what to do…")
        self.edit.setMinimumWidth(340)
        self.edit.returnPressed.connect(self._on_return)
        self.status = QLabel("", wrap)
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(340)
        self.status.hide()
        lay.addWidget(self.edit)
        lay.addWidget(self.status)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)

        self.setStyleSheet(f"""
            #wrap {{ background: #0d1117; border: 2px solid {ACCENT};
                     border-radius: 12px; }}
            QLineEdit {{ background: #161b22; color: #e6edf3;
                         border: 1px solid #30363d; border-radius: 7px;
                         padding: 8px 10px; font-size: 14px; }}
            QLabel {{ color: #e6edf3; font-size: 13px; }}
        """)
        self.setFont(QFont("Segoe UI", 10))

    def ask_at(self, gx, gy):
        self._mode = "ask"
        self.edit.show()
        self.edit.clear()
        self.status.setText("")
        self.status.hide()
        self.adjustSize()
        self._place(gx + 20, gy + 20)
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def step_at(self, gx, gy, text):
        """Show an instruction pinned near a screen point, waiting for Enter."""
        self._mode = "step"
        self.edit.hide()
        self.status.setText(f"{text}\n\n⏎ Enter = click     Esc = stop")
        self.status.show()
        self.adjustSize()
        self._place(gx + 26, gy + 26)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def thinking(self, text="looking… 👀"):
        self._mode = "wait"
        self.edit.hide()
        self.status.setText(text)
        self.status.show()
        self.adjustSize()
        self.show()
        self.raise_()

    def _place(self, gx, gy):
        scr = QGuiApplication.screenAt(QPoint(int(gx), int(gy))) \
            or QGuiApplication.primaryScreen()
        a = scr.availableGeometry()
        w, h = self.width(), self.height()
        x = min(max(gx, a.left() + 8), a.right() - w - 8)
        y = min(max(gy, a.top() + 8), a.bottom() - h - 8)
        self.move(int(x), int(y))

    def _on_return(self):
        t = self.edit.text().strip()
        if t:
            self.submitted.emit(t)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.canceled.emit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self._mode == "step":
            self.confirmed.emit()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------- hotkey ----
class Hotkey(QObject):
    """Global Ctrl+Win listener via pynput. Fires once per press-combo."""

    fired = Signal()

    def __init__(self):
        super().__init__()
        self._ctrl = False
        self._win = False
        self._armed = True

    def start(self):
        try:
            from pynput import keyboard
        except Exception:
            print("CurSir: pynput not installed — run: pip install pynput")
            return
        self._K = keyboard
        self._listener = keyboard.Listener(on_press=self._press,
                                           on_release=self._release)
        self._listener.daemon = True
        self._listener.start()

    def _press(self, k):
        K = self._K.Key
        if k in (K.ctrl, K.ctrl_l, K.ctrl_r):
            self._ctrl = True
        elif k in (K.cmd, K.cmd_l, K.cmd_r):
            self._win = True
        if self._ctrl and self._win and self._armed:
            self._armed = False
            self.fired.emit()

    def _release(self, k):
        K = self._K.Key
        if k in (K.ctrl, K.ctrl_l, K.ctrl_r):
            self._ctrl = False
        elif k in (K.cmd, K.cmd_l, K.cmd_r):
            self._win = False
        if not (self._ctrl and self._win):
            self._armed = True


# --------------------------------------------------------------- worker ----
class Vision(QObject):
    """Runs the Gemini call off the UI thread; returns the dict via signal."""

    done = Signal(dict)

    def run(self, key, task, done_list, shot, think, ground):
        import threading

        def work():
            res = gemini_locate(key, task, done_list, shot, think, ground)
            self.done.emit(res or {})

        t = threading.Thread(target=work, daemon=True)
        t.start()


# ----------------------------------------------------------- controller ----
class CurSir(QObject):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.glow = Glow()
        self.box = Box()
        self.hotkey = Hotkey()
        self.vision = Vision()

        self.task = ""
        self.done_list = []
        self.target = None          # (x, y) screen coords of current element
        self.busy = False

        self.box.submitted.connect(self._start_task)
        self.box.confirmed.connect(self._click_and_next)
        self.box.canceled.connect(self._cancel)
        self.vision.done.connect(self._on_vision)
        self.hotkey.fired.connect(self._trigger)

    def start(self):
        self.hotkey.start()
        print("CurSir is running. Press Ctrl+Win anywhere. (Esc cancels.)")
        if not self.cfg.get("gemini_key"):
            print("WARNING: no Gemini key. Set GEMINI_API_KEY or edit "
                  f"{CONFIG_PATH}")

    # -- flow ---------------------------------------------------------------
    def _trigger(self):
        if self.busy:
            return
        pos = QCursor.pos()
        self.glow.point_at(pos.x(), pos.y())
        self.box.ask_at(pos.x(), pos.y())

    def _start_task(self, task):
        self.task = task
        self.done_list = []
        self._run_step(first=True)

    def _run_step(self, first):
        if not self.cfg.get("gemini_key"):
            self.box.thinking("no Gemini key set — see the console 😿")
            return
        self.busy = True
        think, ground, shot_w = QUALITY.get(self.cfg.get("quality"),
                                            QUALITY["balanced"])
        self.box.thinking("looking… 👀" if first else "checking next… 👀")
        # hide our own overlays so they don't photobomb the screenshot
        self.glow.stop()
        QApplication.processEvents()
        shot, geom = self._grab(shot_w)
        self._geom = geom
        if not shot:
            self.box.thinking("couldn't grab the screen 😿")
            self.busy = False
            return
        self.vision.run(self.cfg["gemini_key"], self.task, self.done_list,
                        shot, think, ground)

    def _on_vision(self, res):
        self.busy = False
        if not res or not isinstance(res, dict):
            self.box.thinking("Gemini didn't answer — try again 😿")
            return
        say = str(res.get("say", "")).strip() or "here you go"
        if res.get("done"):
            self.glow.stop()
            self.box.thinking("✅ " + say)
            QTimer.singleShot(2200, self._cancel)
            return
        if not res.get("found") or not res.get("box"):
            self.glow.stop()
            self.box.thinking("ℹ️ " + say)
            return
        try:
            top, left, bottom, right = [float(v) for v in res["box"][:4]]
        except Exception:
            self.box.thinking("got a bad location — try rephrasing 😿")
            return
        g = self._geom
        cx = g.x() + ((left + right) / 2.0 / 1000.0) * g.width()
        cy = g.y() + ((top + bottom) / 2.0 / 1000.0) * g.height()
        self.target = (int(cx), int(cy))
        self._last_label = str(res.get("label", "that")).strip() or "that"
        self._last = bool(res.get("last"))
        QCursor.setPos(self.target[0], self.target[1])
        self.glow.point_at(*self.target)
        self.box.step_at(self.target[0], self.target[1], say)

    def _click_and_next(self):
        if not self.target:
            return
        x, y = self.target
        QCursor.setPos(x, y)
        self._os_click(x, y)
        self.done_list.append(self._last_label)
        if self._last:
            self.glow.stop()
            self.box.thinking("✅ done")
            QTimer.singleShot(1600, self._cancel)
            return
        # give the app a moment to react, then look for the next step
        QTimer.singleShot(700, lambda: self._run_step(first=False))

    def _cancel(self):
        self.busy = False
        self.target = None
        self.glow.stop()
        self.box.hide()

    # -- os helpers ---------------------------------------------------------
    def _grab(self, maxw):
        try:
            scr = None
            if platform.system() == "Windows":
                try:
                    import ctypes
                    from ctypes import wintypes
                    u = ctypes.windll.user32
                    hwnd = u.GetForegroundWindow()
                    rct = wintypes.RECT()
                    if hwnd and u.GetWindowRect(hwnd, ctypes.byref(rct)):
                        mid = QPoint((rct.left + rct.right) // 2,
                                     (rct.top + rct.bottom) // 2)
                        scr = QGuiApplication.screenAt(mid)
                except Exception:
                    scr = None
            if scr is None:
                scr = QGuiApplication.screenAt(QCursor.pos()) \
                    or QGuiApplication.primaryScreen()
            geom = scr.geometry()
            pm = scr.grabWindow(0)
            if pm.width() > maxw:
                pm = pm.scaledToWidth(maxw, Qt.SmoothTransformation)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            pm.save(buf, "JPEG", 88)
            buf.close()
            return base64.b64encode(bytes(ba)).decode(), geom
        except Exception:
            return None, None

    def _os_click(self, x, y):
        # bring our command box out of the way of the click target
        try:
            from pynput.mouse import Button, Controller
            Controller().click(Button.left, 1)
            return
        except Exception:
            pass
        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # down
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # up
            except Exception:
                pass


def main():
    if platform.system() == "Windows":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cur = CurSir(load_cfg())
    cur.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
