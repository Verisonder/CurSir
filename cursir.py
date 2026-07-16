#!/usr/bin/env python3
"""
CurSir — a cursor that does things for you.

Press the hotkey (Ctrl+Win by default). Your cursor gets a glowing ring and a
command box appears. Tell it what you want ("turn on dark mode in Photoshop",
"where is export as PNG"). CurSir screenshots your active screen, asks Gemini
(with live Google Search) where the next thing to click is, moves your cursor
onto it and glows it. Press ENTER to click. Multi-step tasks advance one step
at a time. ESC cancels.

Everything is controlled from the Settings window (system-tray icon → Settings):
API key, hotkey, quality, auto-update, start-with-Windows.

RUN (from source):  python cursir.py
BUILD AN EXE:       see build_windows.bat  ->  dist\\CurSir.exe
KEY:                enter it in Settings, or set GEMINI_API_KEY, or edit
                    ~/.cursir.json  {"gemini_key": "..."}
"""

import os
import sys
import json
import base64
import math
import platform
import subprocess
import webbrowser

from PySide6.QtCore import (Qt, QObject, Signal, QTimer, QPoint,
                            QBuffer, QByteArray, QIODevice)
from PySide6.QtGui import (QGuiApplication, QCursor, QColor, QPainter, QPen,
                           QFont, QIcon, QPixmap, QAction, QPolygon)
from PySide6.QtWidgets import (QApplication, QWidget, QLineEdit, QLabel,
                               QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QCheckBox, QPushButton,
                               QSystemTrayIcon, QMenu, QProgressBar)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

VERSION = "0.2.2"
DEBUG = os.environ.get("CURSIR_DEBUG", "1") not in ("0", "", "false", "False")
LOG_PATH = os.path.join(os.path.expanduser("~"), ".cursir.log")


def log(msg):
    """Print (when a console exists) AND append to ~/.cursir.log, so errors
    are visible even from the windowed .exe which has no console."""
    line = f"[CurSir] {msg}"
    if DEBUG:
        try:
            print(line)
        except Exception:
            pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".cursir.json")
ACCENT = "#379ED6"
REPO_URL = "https://github.com/Verisonder/CurSir"
RAW_VERSION_URL = \
    "https://raw.githubusercontent.com/Verisonder/CurSir/main/VERSION"
RAW_SOURCE_URL = \
    "https://raw.githubusercontent.com/Verisonder/CurSir/main/cursir.py"

# (thinking budget, zoom-refine pass, google-search grounding, screenshot width)
QUALITY = {
    "fast":     (0,   False, False, 1280),
    "balanced": (128, True,  False, 1280),
    "accurate": (512, True,  True,  1600),
}

HOTKEY_PRESETS = ["ctrl+win", "ctrl+alt+space", "ctrl+shift+space",
                  "ctrl+alt+c", "ctrl+shift+c"]

DEFAULTS = {"gemini_key": "", "quality": "balanced",
            "hotkey": "ctrl+win", "auto_update": True,
            "start_with_windows": False, "start_on_launch": False}


def load_cfg():
    cfg = dict(DEFAULTS)
    cfg["gemini_key"] = os.environ.get("GEMINI_API_KEY", "").strip()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULTS:
                if k in data and data[k] != "":
                    cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        keep = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(keep, f, indent=2)
        return True
    except Exception:
        return False


def vtuple(s):
    try:
        return tuple(int(x) for x in str(s).strip().split("."))
    except Exception:
        return (0,)


# --------------------------------------------------------------- updates ----
def fetch_latest_version():
    import urllib.request
    try:
        with urllib.request.urlopen(RAW_VERSION_URL, timeout=10) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def update_available():
    latest = fetch_latest_version()
    if latest and vtuple(latest) > vtuple(VERSION):
        return latest
    return None


def apply_source_update():
    """Only when running from source (a .py). Downloads the latest cursir.py,
    verifies it compiles, replaces this file, and returns True so the caller
    can restart. Frozen .exe builds return False (handled by opening the
    repo instead — exe self-replace is wired when we package)."""
    if getattr(sys, "frozen", False):
        return False
    import urllib.request
    try:
        with urllib.request.urlopen(RAW_SOURCE_URL, timeout=20) as r:
            data = r.read()
        compile(data, "cursir_new.py", "exec")     # trust nothing that won't run
        here = os.path.abspath(__file__)
        tmp = here + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, here)
        return True
    except Exception:
        return False


def restart_app():
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            launcher = pyw if os.path.exists(pyw) else exe
            subprocess.Popen([launcher, os.path.abspath(__file__)])
    except Exception:
        pass
    os._exit(0)


EXE_ASSET_URL = \
    "https://github.com/Verisonder/CurSir/releases/latest/download/CurSir.exe"


def apply_exe_update():
    """Frozen .exe self-update: download the new CurSir.exe, then hand off to
    a tiny batch that waits for us to exit, swaps the file, and relaunches.
    Returns True if the swap was launched (caller must then exit)."""
    if platform.system() != "Windows" or not getattr(sys, "frozen", False):
        return False
    import urllib.request
    import tempfile
    exe = sys.executable
    folder = os.path.dirname(exe)
    newexe = os.path.join(folder, "CurSir.new.exe")
    try:
        with urllib.request.urlopen(EXE_ASSET_URL, timeout=120) as r:
            data = r.read()
        if len(data) < 1_000_000:          # sanity: a real exe is many MB
            return False
        with open(newexe, "wb") as f:
            f.write(data)
    except Exception:
        return False
    bat = os.path.join(tempfile.gettempdir(), "cursir_update.bat")
    script = (
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        ":wait\r\n"
        f'del "{exe}" >nul 2>&1\r\n'
        f'if exist "{exe}" (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'move /y "{newexe}" "{exe}" >nul\r\n'
        f'start "" "{exe}"\r\n'
        'del "%~f0" >nul 2>&1\r\n')
    try:
        with open(bat, "w") as f:
            f.write(script)
        subprocess.Popen(["cmd", "/c", bat],
                         creationflags=0x08000000)   # detached, no window
        return True
    except Exception:
        return False


def set_autostart(enable):
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        run = r"Software\Microsoft\Windows\CurrentVersion\Run"
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run, 0,
                           winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --autostart'
            else:
                base = os.path.dirname(sys.executable)
                pyw = os.path.join(base, "pythonw.exe")
                exe = pyw if os.path.exists(pyw) else sys.executable
                cmd = f'"{exe}" "{os.path.abspath(__file__)}" --autostart'
            winreg.SetValueEx(k, "CurSir", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "CurSir")
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def create_desktop_shortcut():
    """Create (or refresh) a CurSir shortcut on the Desktop via PowerShell's
    WScript.Shell — no extra dependencies. Returns True on success."""
    if platform.system() != "Windows":
        return False
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        lnk = os.path.join(desktop, "CurSir.lnk")
        if getattr(sys, "frozen", False):
            target = sys.executable                 # the CurSir.exe
            args = ""
            icon = sys.executable                   # icon is embedded in exe
        else:
            base = os.path.dirname(sys.executable)
            pyw = os.path.join(base, "pythonw.exe")
            target = pyw if os.path.exists(pyw) else sys.executable
            args = f'"{os.path.abspath(__file__)}"'
            ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "cursir.ico")
            icon = ico if os.path.exists(ico) else target
        ps = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
            f"'{lnk}');$s.TargetPath='{target}';$s.Arguments='{args}';"
            f"$s.IconLocation='{icon}';$s.WorkingDirectory="
            f"'{os.path.dirname(target)}';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                        "-Command", ps], creationflags=0x08000000,
                       timeout=15, check=False)
        return os.path.exists(lnk)
    except Exception:
        return False
def gemini_call_json(key, contents, persona, think, ground, max_tokens=400):
    """POST to Gemini (model fallback, optional grounding). Returns the
    parsed JSON object the model produced, or {} on failure."""
    import urllib.request
    import urllib.error

    models = ("gemini-flash-latest", "gemini-3.5-flash",
              "gemini-3.1-flash-lite", "gemini-flash-lite-latest",
              "gemini-2.5-flash", "gemini-2.5-flash-lite")

    def make_body(model, grounded, use_think=True):
        b = {"contents": contents,
             "systemInstruction": {"parts": [{"text": persona}]},
             "generationConfig": {"maxOutputTokens": max_tokens,
                                  "temperature": 0.6}}
        if use_think:
            if model.startswith("gemini-2.5"):
                b["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": think}
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
    last_err = "no reply"
    for m in models:
        url = ("https://generativelanguage.googleapis.com/v1beta/"
               f"models/{m}:generateContent?key={key}")
        for grounded in gseq:
            for use_think in (True, False):
                # only fall back to the no-thinking body if the thinking one
                # was rejected with a 400 (mirrors SondeR Cat's fallback)
                try:
                    body = make_body(m, grounded, use_think)
                    req = urllib.request.Request(
                        url, data=body,
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=35) as r:
                        return parse(json.loads(r.read().decode()))
                except urllib.error.HTTPError as e:
                    detail = ""
                    try:
                        detail = e.read().decode()[:200]
                    except Exception:
                        pass
                    last_err = f"{m} (grounded={grounded}): HTTP {e.code} {detail}"
                    if e.code == 400 and use_think:
                        continue          # retry this model without thinking
                    break                 # other errors → next grounded/model
                except Exception as e:
                    last_err = f"{m}: {type(e).__name__}: {e}"
                    break
    if DEBUG:
        log(f"gemini call FAILED — last error: {last_err}")
    return {}


def gemini_locate(key, task, done_list, shot_b64, think, ground):
    """First pass: locate the next UI element in the full screenshot."""
    step_no = len(done_list) + 1
    done_txt = ("Steps ALREADY completed by the user: "
                + "; ".join(f"{i+1}) {d}" for i, d in enumerate(done_list))
                if done_list else "This is the FIRST step.")

    persona = (
        "You are CurSir, a courteous on-screen BUTLER who controls the "
        "user's mouse. The user asked you to do or find something in the app "
        "shown in the screenshot. Work out the ACTUAL correct way to do it "
        "using what you know and Google Search when useful - do NOT guess "
        "from the screenshot alone. Then find the SINGLE next UI element the "
        "user must click, and locate it PRECISELY in the screenshot. Respond "
        "with ONLY minified JSON, no markdown, no code fences, exactly this "
        'shape: {"found":true,"box":[100,200,140,320],"label":"element name",'
        '"say":"instruction","last":false,"done":false,"double":false} . '
        "box is the TIGHT bounding box of just that ONE element (not its "
        "whole row, toolbar or panel), in the order top, left, bottom, "
        "right, each normalized 0-1000 of the image height (y) and width "
        "(x). box MUST contain four plain INTEGERS like [112,204,146,318] - "
        "NEVER letters or placeholder words. Hug the element's real edges. "
        "Set \"double\":true ONLY when the element needs a double-click to "
        "open (a desktop icon, or a file/folder in File Explorer); otherwise "
        "false. Write 'say' in the voice of a polite English butler "
        "addressing the user as 'sir' (e.g. 'Kindly click the Settings icon, "
        "sir.'). Keep it under 22 words, no emoji, and match how the app "
        "actually works. Set \"last\":true when THIS element is the FINAL "
        "step that completes the whole task (a simple one-click task is "
        "last:true on the very first step) - do NOT set last:true if the "
        "user will still need another step after this one. Set done=true "
        "(and make 'say' a short wrap-up) only when the task is ALREADY "
        "fully complete in the screenshot. Set found=false if the needed "
        "element isn't on screen yet (then 'say' explains what to open "
        "or click first).")

    contents = [{"role": "user", "parts": [
        {"text": f"Task: {task}\nStep number: {step_no}\n{done_txt}"},
        {"inline_data": {"mime_type": "image/jpeg", "data": shot_b64}}]}]
    return gemini_call_json(key, contents, persona, think, ground)


def zoom_refine(key, label, box, img, think):
    """Second pass: crop ~3x around the first box, zoom in, re-ask
    (image-only, ungrounded) for a tight box in the crop. Returns refined
    (nx, ny) normalized 0-1000 of the FULL image, or None to keep the first
    pass. Runs on the worker thread (QImage ops are thread-safe)."""
    if img is None or img.isNull():
        return None
    W, H = img.width(), img.height()
    bt, bl, bb, br = [float(v) for v in box[:4]]
    x0, x1 = bl / 1000.0 * W, br / 1000.0 * W
    y0, y1 = bt / 1000.0 * H, bb / 1000.0 * H
    bw, bh = max(20.0, x1 - x0), max(16.0, y1 - y0)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rw = min(W, max(bw * 3.0, 260.0))
    rh = min(H, max(bh * 3.0, 200.0))
    rx = max(0, min(int(cx - rw / 2), W - int(rw)))
    ry = max(0, min(int(cy - rh / 2), H - int(rh)))
    rw, rh = int(rw), int(rh)
    crop = img.copy(rx, ry, rw, rh)
    if crop.width() < 640:
        crop = crop.scaledToWidth(640, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    crop.save(buf, "JPEG", 90)
    buf.close()
    b64 = base64.b64encode(bytes(ba)).decode()
    persona2 = (
        "This is a zoomed-in crop of a screenshot. Locate the element "
        f"described as: {label!r}. Respond with ONLY minified JSON: "
        '{"found":true,"box":[112,204,146,318]} where box is the TIGHT '
        "bounding box [top,left,bottom,right], each an INTEGER normalized "
        "0-1000 of THIS image's height/width. If it isn't in this crop, "
        'reply {"found":false}.')
    contents2 = [{"role": "user", "parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}]
    d2 = gemini_call_json(key, contents2, persona2, think, False,
                          max_tokens=768)
    if not d2 or not d2.get("found") or not d2.get("box"):
        return None
    try:
        zt, zl, zb, zr = [float(v) for v in d2["box"][:4]]
    except Exception:
        return None
    czx = (zl + zr) / 2.0 / 1000.0
    czy = (zt + zb) / 2.0 / 1000.0
    fx = (rx + czx * rw) / W * 1000.0
    fy = (ry + czy * rh) / H * 1000.0
    if not (0 <= fx <= 1000 and 0 <= fy <= 1000):
        return None
    return fx, fy


# ------------------------------------------------------------- overlays ----
class Glow(QWidget):
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
        # blue cursor arrow — smaller, precisely centred, glowing
        arrow = [(0, 0), (0, 24), (6, 18), (10, 28), (14, 26),
                 (10, 17), (17, 17)]
        sc = 0.6
        pts = [(ax * sc, ay * sc) for ax, ay in arrow]
        wid = max(x for x, _ in pts)
        hei = max(y for _, y in pts)
        ox = self._pt.x() - wid / 2.0
        oy = self._pt.y() - hei / 2.0 - 5    # nudge up so it centres in ring
        poly = QPolygon([QPoint(round(ox + x), round(oy + y))
                         for x, y in pts])
        halo = int(120 + 80 * (1 + math.sin(self._phase)) / 2)   # breathe
        for pw, a in ((14, halo // 4), (9, halo // 3), (5, halo // 2)):
            gc = QColor(ACCENT)
            gc.setAlpha(min(255, a))
            pen = QPen(gc, pw)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(poly)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawPolygon(poly)
        p.end()


class Box(QWidget):
    submitted = Signal(str)
    confirmed = Signal()
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
        self.edit.setPlaceholderText("How may I assist you, sir?")
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
        self._mode = "step"
        self.edit.hide()
        self.status.setText(f"{text}\n\n⏎ Enter to click     Esc to cancel")
        self.status.show()
        self.adjustSize()
        self._place(gx + 26, gy + 26)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def thinking(self, text="One moment, sir…"):
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
def _canon(key, K):
    if key in (K.ctrl, K.ctrl_l, K.ctrl_r):
        return "ctrl"
    if key in (K.alt, K.alt_l, K.alt_r, getattr(K, "alt_gr", None)):
        return "alt"
    if key in (K.shift, K.shift_l, K.shift_r):
        return "shift"
    if key in (K.cmd, K.cmd_l, K.cmd_r):
        return "win"
    if key == K.space:
        return "space"
    ch = getattr(key, "char", None)
    if ch:
        return ch.lower()
    return None


class Hotkey(QObject):
    fired = Signal()

    def __init__(self, combo="ctrl+win"):
        super().__init__()
        self._pressed = set()
        self._armed = True
        self._listener = None
        self._K = None
        self.set_combo(combo)

    def set_combo(self, combo):
        parts = [p.strip().lower() for p in str(combo).split("+") if p.strip()]
        mods = ("ctrl", "alt", "shift", "win")
        self._mods = {p for p in parts if p in mods}
        mains = [p for p in parts if p not in mods]
        self._main = mains[0] if mains else None

    def start(self):
        try:
            from pynput import keyboard
        except Exception:
            print("CurSir: pynput not installed — run: pip install pynput")
            return
        self._K = keyboard.Key
        self._listener = keyboard.Listener(on_press=self._press,
                                           on_release=self._release)
        self._listener.daemon = True
        self._listener.start()

    def restart(self, combo):
        try:
            if self._listener is not None:
                self._listener.stop()
        except Exception:
            pass
        self._pressed = set()
        self._armed = True
        self.set_combo(combo)
        self.start()

    def stop(self):
        try:
            if self._listener is not None:
                self._listener.stop()
        except Exception:
            pass
        self._listener = None
        self._pressed = set()
        self._armed = True

    def _match(self):
        if not self._mods.issubset(self._pressed):
            return False
        if self._main is None:
            return True
        return self._main in self._pressed

    def _press(self, key):
        tok = _canon(key, self._K)
        if tok is None:
            return
        self._pressed.add(tok)
        if self._match() and self._armed:
            self._armed = False
            self.fired.emit()

    def _release(self, key):
        tok = _canon(key, self._K)
        if tok is None:
            return
        self._pressed.discard(tok)
        if not self._match():
            self._armed = True


# --------------------------------------------------------------- worker ----
class Vision(QObject):
    done = Signal(dict)

    def run(self, key, task, done_list, shot, think, ground, do_zoom, img):
        import threading

        def work():
            res = gemini_locate(key, task, done_list, shot, think, ground)
            res = res or {}
            if DEBUG:
                log(f"first-pass: found={res.get('found')} "
                      f"box={res.get('box')} label={res.get('label')!r} "
                      f"say={res.get('say')!r}")
            # zoom-refine pass — same trick that makes the cat's guide precise
            try:
                if (res.get("found") and not res.get("done")
                        and res.get("box") and do_zoom):
                    bt, bl, bb, br = [float(v) for v in res["box"][:4]]
                    area = max(0.0, bb - bt) * max(0.0, br - bl) / 1e6
                    if 0.0015 <= area <= 0.40:
                        ref = zoom_refine(key, str(res.get("label")
                                          or "the element"),
                                          res["box"], img, think)
                        if DEBUG:
                            log(f"zoom-refine (area={area:.4f}): "
                                  f"{ref}")
                        if ref is not None:
                            res["_center"] = ref     # (nx, ny) 0-1000, refined
                    elif DEBUG:
                        log(f"zoom skipped (area={area:.4f})")
            except Exception as e:
                if DEBUG:
                    log(f"zoom error: {e}")
            self.done.emit(res)

        threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------- settings ----
class Settings(QWidget):
    def __init__(self, ctrl):
        super().__init__(None)
        self.ctrl = ctrl
        self.setWindowTitle("CurSir — Settings")
        self.setMinimumWidth(420)

        form = QFormLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("paste your Gemini API key")

        self.hotkey_edit = QComboBox()
        self.hotkey_edit.setEditable(True)
        self.hotkey_edit.addItems(HOTKEY_PRESETS)

        self.quality_edit = QComboBox()
        self.quality_edit.addItems(["fast", "balanced", "accurate"])

        self.autoupd = QCheckBox("Check for updates automatically")
        self.autostart = QCheckBox("Start CurSir when Windows starts")
        self.startlaunch = QCheckBox("Start CurSir automatically when I open it")

        form.addRow("Gemini API key", self.key_edit)
        form.addRow("Hotkey", self.hotkey_edit)
        form.addRow("Quality", self.quality_edit)
        form.addRow("", self.startlaunch)
        form.addRow("", self.autostart)
        form.addRow("", self.autoupd)

        # big Start/Stop control — this is what actually runs CurSir
        self.state_lbl = QLabel("CurSir is stopped")
        self.toggle_btn = QPushButton("Start CurSir")
        self.toggle_btn.setMinimumHeight(34)
        self.toggle_btn.clicked.connect(self._toggle)

        self.upd_status = QLabel(f"CurSir v{VERSION}")
        # install button: hidden until an update is found
        self.install_btn = QPushButton("Install update")
        self.install_btn.setMinimumHeight(30)
        self.install_btn.clicked.connect(self._install)
        self.install_btn.hide()
        # green install progress bar (hidden until installing)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(16)
        self.progress.setStyleSheet(
            "QProgressBar { border:1px solid #30363d; border-radius:8px; "
            "background:#161b22; } "
            "QProgressBar::chunk { background-color:#2ea043; "
            "border-radius:7px; }")
        self.progress.hide()

        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(self._check)
        self.shortcut_btn = QPushButton("Add desktop shortcut")
        self.shortcut_btn.clicked.connect(self._shortcut)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)          # only when something changes
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.hide)

        row = QHBoxLayout()
        row.addWidget(self.check_btn)
        row.addWidget(self.shortcut_btn)
        row.addStretch(1)
        row.addWidget(self.save_btn)
        row.addWidget(self.close_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(self.state_lbl)
        lay.addWidget(self.toggle_btn)
        lay.addSpacing(6)
        lay.addLayout(form)
        lay.addWidget(self.upd_status)
        lay.addWidget(self.install_btn)
        lay.addWidget(self.progress)
        lay.addLayout(row)

        # mark the form dirty (enable Save) whenever the user edits anything
        self._loading = False
        self.key_edit.textChanged.connect(self._mark_dirty)
        self.hotkey_edit.currentTextChanged.connect(self._mark_dirty)
        self.quality_edit.currentTextChanged.connect(self._mark_dirty)
        self.startlaunch.toggled.connect(self._mark_dirty)
        self.autostart.toggled.connect(self._mark_dirty)
        self.autoupd.toggled.connect(self._mark_dirty)

    def load_from(self, cfg):
        self._loading = True
        self.key_edit.setText(cfg.get("gemini_key", ""))
        self.hotkey_edit.setCurrentText(cfg.get("hotkey", "ctrl+win"))
        self.quality_edit.setCurrentText(cfg.get("quality", "balanced"))
        self.autoupd.setChecked(bool(cfg.get("auto_update", True)))
        self.autostart.setChecked(bool(cfg.get("start_with_windows", False)))
        self.startlaunch.setChecked(bool(cfg.get("start_on_launch", False)))
        self._loading = False
        self.save_btn.setEnabled(False)
        self.refresh_state(getattr(self.ctrl, "armed", False))

    def _mark_dirty(self, *_):
        if not self._loading:
            self.save_btn.setEnabled(True)

    def refresh_state(self, armed):
        self.state_lbl.setText("CurSir is running" if armed
                               else "CurSir is stopped")
        self.toggle_btn.setText("Stop CurSir" if armed else "Start CurSir")

    def _toggle(self):
        self.ctrl.set_armed(not self.ctrl.armed)

    def _save(self):
        self.ctrl.apply_settings(
            key=self.key_edit.text().strip(),
            hotkey=self.hotkey_edit.currentText().strip() or "ctrl+win",
            quality=self.quality_edit.currentText(),
            auto_update=self.autoupd.isChecked(),
            start_with_windows=self.autostart.isChecked(),
            start_on_launch=self.startlaunch.isChecked())
        self.upd_status.setText("Saved ✓")
        self.save_btn.setEnabled(False)

    def _check(self):
        self.upd_status.setText("Checking for updates…")
        self.check_btn.setEnabled(False)
        QApplication.processEvents()
        latest = update_available()
        self.check_btn.setEnabled(True)
        if latest:
            self.show_update(latest)      # offer to install, don't auto-run
        else:
            self.install_btn.hide()
            self.upd_status.setText(f"You're up to date, sir (v{VERSION}).")

    def show_update(self, latest):
        """An update exists — invite the user to install it."""
        self._pending = latest
        self.upd_status.setText(f"Update v{latest} is available, sir.")
        self.install_btn.setText(f"Install v{latest}")
        self.install_btn.setEnabled(True)
        self.install_btn.show()

    def _install(self):
        self.upd_status.setText("Installing…")
        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        QApplication.processEvents()
        self.ctrl.install_update()

    def set_install_status(self, text):
        self.upd_status.setText(text)

    def begin_install(self):
        self.install_btn.hide()
        self.progress.setValue(0)
        self.progress.show()
        self.upd_status.setText("Installing…")

    def set_progress(self, v):
        self.progress.setValue(max(0, min(100, int(v))))

    def end_install(self, ok):
        if not ok:
            self.progress.hide()

    def _shortcut(self):
        ok = create_desktop_shortcut()
        self.upd_status.setText("Desktop shortcut added." if ok
                                else "Couldn't create the shortcut, sir.")


# ----------------------------------------------------------- controller ----
class CurSir(QObject):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.glow = Glow()
        self.box = Box()
        self.hotkey = Hotkey(cfg.get("hotkey", "ctrl+win"))
        self.vision = Vision()
        self.settings = Settings(self)

        self.task = ""
        self.done_list = []
        self.target = None
        self.busy = False
        self._updating = False
        self._pending_update = None
        self._geom = None
        self._last = False
        self._last_label = "that"
        self.armed = False

        self.box.submitted.connect(self._start_task)
        self.box.confirmed.connect(self._click_and_next)
        self.box.canceled.connect(self._cancel)
        self.vision.done.connect(self._on_vision)
        self.hotkey.fired.connect(self._trigger)

        self._build_tray()

    # -- lifecycle ----------------------------------------------------------
    def start(self, autostart=False):
        print(f"CurSir v{VERSION} loaded. Hotkey: {self.cfg.get('hotkey')}.")
        if self.cfg.get("start_with_windows"):
            set_autostart(True)
        if autostart:
            # launched at boot → run silently, no window
            self.set_armed(True)
        else:
            # launched normally (shortcut) → always show Settings, don't arm
            self.open_settings()
            if self.cfg.get("start_on_launch"):
                self.set_armed(True)
        if self.cfg.get("auto_update"):
            QTimer.singleShot(3000, self._bg_update_check)

    def set_armed(self, on):
        """Arm/disarm the global hotkey (i.e. actually 'start' CurSir)."""
        if on and not self.armed:
            self.hotkey.restart(self.cfg.get("hotkey", "ctrl+win"))
            self.armed = True
        elif not on and self.armed:
            self.hotkey.stop()
            self.armed = False
            self._cancel()
        self.tray.setToolTip("CurSir — running" if self.armed
                             else "CurSir — stopped")
        if hasattr(self, "a_toggle"):
            self.a_toggle.setText("Stop CurSir" if self.armed
                                  else "Start CurSir")
        if hasattr(self, "settings"):
            self.settings.refresh_state(self.armed)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip("CurSir — stopped")
        menu = QMenu()
        self.a_toggle = QAction("Start CurSir", self)
        self.a_toggle.triggered.connect(lambda: self.set_armed(not self.armed))
        a_set = QAction("Settings", self)
        a_set.triggered.connect(self.open_settings)
        a_upd = QAction("Check for updates", self)
        a_upd.triggered.connect(self._manual_update_check)
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(QApplication.instance().quit)
        for a in (self.a_toggle, a_set, a_upd):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.open_settings()

    def _make_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(ACCENT), 5))
        p.drawEllipse(12, 12, 40, 40)
        p.setBrush(QColor("#e6edf3"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(27, 27, 10, 10)
        p.end()
        return QIcon(pm)

    def open_settings(self):
        self.settings.load_from(self.cfg)
        if self._pending_update:
            self.settings.show_update(self._pending_update)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def apply_settings(self, key, hotkey, quality, auto_update,
                       start_with_windows, start_on_launch):
        old_hotkey = self.cfg.get("hotkey")
        self.cfg.update({"gemini_key": key, "hotkey": hotkey,
                         "quality": quality, "auto_update": auto_update,
                         "start_with_windows": start_with_windows,
                         "start_on_launch": start_on_launch})
        save_cfg(self.cfg)
        if hotkey != old_hotkey and self.armed:
            self.hotkey.restart(hotkey)     # only if currently running
        set_autostart(start_with_windows)

    # -- updates ------------------------------------------------------------
    def _bg_update_check(self):
        import threading

        def work():
            latest = update_available()
            if latest:
                QTimer.singleShot(0, lambda: self._present_update(latest))
        threading.Thread(target=work, daemon=True).start()

    def _manual_update_check(self):
        latest = update_available()
        if latest:
            self._present_update(latest)
        else:
            self.tray.showMessage("CurSir", f"You're up to date (v{VERSION}).")

    def _present_update(self, latest):
        """Tell the user an update exists and let them choose to install."""
        self._pending_update = latest
        self.tray.showMessage(
            "CurSir", f"Update v{latest} is available, sir — "
            "open CurSir to install it.")
        if self.settings.isVisible():
            self.settings.show_update(latest)

    def install_update(self):
        if self._pending_update:
            self.offer_update(self._pending_update)

    def offer_update(self, latest):
        if self._updating:
            return
        self._updating = True
        self.tray.showMessage("CurSir", f"Installing v{latest}, sir…")
        self.settings.begin_install()
        # smooth progress up to ~90% while the (fast) download/write happens;
        # jumps to 100% the moment it's actually done
        self._prog = 0
        self._prog_timer = QTimer(self)
        self._prog_timer.timeout.connect(self._tick_progress)
        self._prog_timer.start(40)
        import threading

        def work():
            if getattr(sys, "frozen", False):
                ok = apply_exe_update()          # download new exe + swap helper
            else:
                ok = apply_source_update()       # replace cursir.py
            QTimer.singleShot(0, lambda: self._after_update(ok, latest))

        threading.Thread(target=work, daemon=True).start()

    def _tick_progress(self):
        if self._prog < 90:
            self._prog += 3
            self.settings.set_progress(self._prog)

    def _after_update(self, ok, latest):
        try:
            self._prog_timer.stop()
        except Exception:
            pass
        if ok:
            self.settings.set_progress(100)
            self.tray.showMessage("CurSir", "Update installed — restarting…")
            self.settings.set_install_status("Installed — restarting CurSir…")
            # let the full bar show for a beat, then exit so the swap completes
            QTimer.singleShot(1100, lambda: (restart_app()
                                             if not getattr(sys, "frozen", False)
                                             else os._exit(0)))
        else:
            self._updating = False
            self.settings.end_install(False)
            self.settings.set_install_status(
                "Update failed, sir — opening the download page.")
            self.tray.showMessage(
                "CurSir", "Update failed, sir — opening the download page")
            webbrowser.open(REPO_URL + "/releases/latest")

    # -- flow ---------------------------------------------------------------
    def _trigger(self):
        if self.busy:
            return
        if not self.cfg.get("gemini_key"):
            self.open_settings()
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
            self.box.thinking("No API key set, sir — kindly add one in Settings.")
            return
        self.busy = True
        think, do_zoom, ground, shot_w = QUALITY.get(
            self.cfg.get("quality"), QUALITY["balanced"])
        self.box.hide()            # keep OUR box/glow out of the screenshot
        self.glow.stop()
        QApplication.processEvents()
        shot, geom, img = self._grab(shot_w)
        self._geom = geom
        if not shot:
            self.box.thinking("I'm unable to view the screen, sir.")
            self.busy = False
            return
        self.box.thinking("One moment, sir…" if first else "Allow me a moment, sir…")
        self.vision.run(self.cfg["gemini_key"], self.task, self.done_list,
                        shot, think, ground, do_zoom, img)

    def _on_vision(self, res):
        self.busy = False
        if not res or not isinstance(res, dict):
            self.box.thinking("My apologies, sir — I received no reply. Shall we try again?")
            return
        say = str(res.get("say", "")).strip() or "As you wish, sir."
        if res.get("done"):
            self.glow.stop()
            self.box.thinking(say)
            QTimer.singleShot(2200, self._cancel)
            return
        if not res.get("found") or not res.get("box"):
            self.glow.stop()
            self.box.thinking(say)
            return
        try:
            top, left, bottom, right = [float(v) for v in res["box"][:4]]
        except Exception:
            self.box.thinking("I couldn't place that precisely, sir. Might you rephrase?")
            return
        # prefer the zoom-refined centre when the second pass produced one
        if isinstance(res.get("_center"), (list, tuple)) \
                and len(res["_center"]) == 2:
            nx, ny = res["_center"]
        else:
            nx = (left + right) / 2.0
            ny = (top + bottom) / 2.0
        g = self._geom
        cx = g.x() + (nx / 1000.0) * g.width()
        cy = g.y() + (ny / 1000.0) * g.height()
        self.target = (int(cx), int(cy))
        if DEBUG:
            log(f"map: nx={nx:.1f} ny={ny:.1f} | "
                  f"geom=({g.x()},{g.y()},{g.width()}x{g.height()}) | "
                  f"screen=({int(cx)},{int(cy)})")
        self._last_label = str(res.get("label", "that")).strip() or "that"
        self._last = bool(res.get("last"))
        self._double = bool(res.get("double"))
        QCursor.setPos(self.target[0], self.target[1])
        self.glow.point_at(*self.target)
        self.box.step_at(self.target[0], self.target[1], say)

    def _click_and_next(self):
        if not self.target:
            return
        x, y = self.target
        # drop our own window focus + overlays FIRST, so the click lands on
        # the target on the first try instead of just activating our box
        self.box.hide()
        self.glow.stop()
        QApplication.processEvents()
        # let Windows settle focus, then move + click
        QTimer.singleShot(70, self._do_click)

    def _do_click(self):
        if not self.target:
            return
        x, y = self.target
        QCursor.setPos(x, y)
        self._os_click(double=getattr(self, "_double", False))
        self.done_list.append(self._last_label)
        if self._last:
            self.glow.stop()
            self.box.thinking("Very good, sir.")
            QTimer.singleShot(1600, self._cancel)
            return
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
            geom = scr.geometry()          # LOGICAL screen rect (for mapping)
            dpr = scr.devicePixelRatio()   # scale factor, e.g. 1.5 at 150%
            pm = scr.grabWindow(0)
            # capture comes back at PHYSICAL resolution; pin dpr=1 so widths
            # are raw pixels and the fraction math has no hidden scaling
            phys_w, phys_h = pm.width(), pm.height()
            if pm.width() > maxw:
                pm = pm.scaledToWidth(maxw, Qt.SmoothTransformation)
            img = pm.toImage()
            img.setDevicePixelRatio(1.0)
            if DEBUG:
                log(f"screen: geom=({geom.x()},{geom.y()},"
                      f"{geom.width()}x{geom.height()} logical) "
                      f"dpr={dpr} capture={phys_w}x{phys_h} phys "
                      f"sent={img.width()}x{img.height()}")
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            pm.save(buf, "JPEG", 88)
            buf.close()
            return base64.b64encode(bytes(ba)).decode(), geom, img
        except Exception:
            return None, None, None

    def _os_click(self, double=False):
        n = 2 if double else 1
        try:
            from pynput.mouse import Button, Controller
            Controller().click(Button.left, n)
            return
        except Exception:
            pass
        if platform.system() == "Windows":
            try:
                import ctypes
                for _ in range(n):
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            except Exception:
                pass


SINGLETON_NAME = "CurSir-singleton-v1"


class SingleInstance(QObject):
    """Ensures one CurSir runs at a time and lets a second launch tell the
    running one to open Settings, via a local socket."""

    settings_requested = Signal()

    def __init__(self):
        super().__init__()
        self._server = None

    def signal_existing(self):
        """If an instance is already running, tell it to open Settings and
        return True (this process should exit). Otherwise return False."""
        sock = QLocalSocket()
        sock.connectToServer(SINGLETON_NAME)
        if sock.waitForConnected(300):
            sock.write(b"settings")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            return True
        return False

    def start_server(self):
        QLocalServer.removeServer(SINGLETON_NAME)      # clear any stale socket
        self._server = QLocalServer()
        self._server.listen(SINGLETON_NAME)
        self._server.newConnection.connect(self._on_conn)

    def _on_conn(self):
        c = self._server.nextPendingConnection()
        if c is not None and c.waitForReadyRead(200):
            msg = bytes(c.readAll()).decode(errors="ignore")
            if "settings" in msg:
                self.settings_requested.emit()
        if c is not None:
            c.disconnectFromServer()


def main():
    if platform.system() == "Windows":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    si = SingleInstance()
    if si.signal_existing():
        return          # another CurSir is running — it will open Settings

    si.start_server()
    cur = CurSir(load_cfg())
    si.settings_requested.connect(cur.open_settings)
    cur.start(autostart=("--autostart" in sys.argv))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
