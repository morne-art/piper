"""Piper on screen: hold Ctrl+Alt anywhere, ask about what you see, Piper answers and points.

Everything runs on this PC:
  hotkey      pynput (listen-only, never blocks your keys)
  microphone  sounddevice
  speech→text faster-whisper (small English model, downloaded once)
  screenshot  mss, only the monitor your mouse is on, never saved to disk
  brain       Piper's server → Ollama vision model (qwen2.5vl)
  voice       Piper's own Kokoro voice
  cursor      a transparent, click-through window drawn over everything
Started by start-piper.bat. Turn it off in config.json: "companion": {"enabled": false}
"""
import base64, ctypes, io, json, math, pathlib, queue, threading, time, urllib.request, winsound

ROOT = pathlib.Path(__file__).parent
try: CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
except Exception: CFG = {}
OPT = {"enabled": True, "hotkey": "ctrl+alt", "whisper": "base.en", "show_cursor": "when_active", **CFG.get("companion", {})}
SERVER = f"http://127.0.0.1:{CFG.get('port', 8790)}"
MAX_SIDE = 1288   # screenshots are shrunk to fit this; sizes are multiples of 28, which is what qwen2.5vl works in
user32 = ctypes.windll.user32

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)   # real pixels, so the cursor lands where the model means
except Exception: user32.SetProcessDPIAware()

ui = queue.Queue()   # messages for the overlay: ("state", text) / ("point", x, y, label) / ("level", 0..1) / ("idle",)

# ---------------- screenshot ----------------
def mouse_pos():
    class P(ctypes.Structure): _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(); user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y

def capture():
    """Screenshot of the monitor the mouse is on. Returns (jpeg base64, w, h, monitor, scale)."""
    import mss
    from PIL import Image
    mx, my = mouse_pos()
    with mss.mss() as s:
        mons = s.monitors[1:]
        mon = next((m for m in mons if m["left"] <= mx < m["left"] + m["width"] and m["top"] <= my < m["top"] + m["height"]), mons[0])
        shot = s.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    scale = min(1.0, MAX_SIDE / max(img.width, img.height))
    w = max(28, round(img.width * scale / 28) * 28); h = max(28, round(img.height * scale / 28) * 28)
    img = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode(), w, h, mon, (img.width / mon["width"], img.height / mon["height"])

# ---------------- speech to text ----------------
_whisper = [None]
def whisper():
    if _whisper[0] is None:
        from faster_whisper import WhisperModel
        _whisper[0] = WhisperModel(OPT["whisper"], device="cpu", compute_type="int8")
    return _whisper[0]

class Recorder:
    def __init__(self): self.chunks, self.stream = [], None
    def start(self):
        import sounddevice as sd
        self.chunks = []
        def cb(data, *_):
            self.chunks.append(data.copy())
            ui.put(("level", min(1.0, float(abs(data).mean()) * 25)))
        self.stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=cb); self.stream.start()
    def stop(self):
        import numpy as np
        if self.stream: self.stream.stop(); self.stream.close(); self.stream = None
        return np.concatenate(self.chunks)[:, 0] if self.chunks else None

def transcribe(audio):
    if audio is None or len(audio) < 16000 * 0.3: return ""
    segs, _ = whisper().transcribe(audio, language="en", beam_size=1, vad_filter=True)
    return " ".join(s.text for s in segs).strip()

# ---------------- voice ----------------
class Speaker:
    """Makes the next sentence's audio while the current one plays."""
    def __init__(self):
        self.text_q, self.wav_q = queue.Queue(), queue.Queue()
        threading.Thread(target=self._synth, daemon=True).start()
        threading.Thread(target=self._play, daemon=True).start()
        self.busy = 0
        self.engine = "neural"; self._win = None
    def check_engine(self):
        try:
            with urllib.request.urlopen(SERVER + "/status", timeout=3) as r: self.engine = json.loads(r.read())["voice"].get("engine", "neural")
        except Exception: pass
    def say(self, s): self.busy += 1; self.text_q.put(s)
    def _windows_voice(self, s):
        """Windows' built-in voice: instant, works when the natural voice is too slow on this PC."""
        if self._win is None:
            import pyttsx3
            self._win = pyttsx3.init()
            for v in self._win.getProperty("voices"):
                if any(n in v.name for n in ("George", "Hazel", "Ryan", "Susan")) or "en-gb" in str(v.id).lower(): self._win.setProperty("voice", v.id); break
        self._win.say(s); self._win.runAndWait()
    def _synth(self):
        while True:
            s = self.text_q.get()
            if self.engine == "windows": self.wav_q.put(("say", s)); continue
            try:
                req = urllib.request.Request(SERVER + "/tts", data=json.dumps({"text": s}).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r: self.wav_q.put(r.read())
            except Exception as e: print("voice:", e); self.wav_q.put(None)
    def _play(self):
        while True:
            w = self.wav_q.get()
            try:
                if isinstance(w, tuple): self._windows_voice(w[1])
                elif w: winsound.PlaySound(w, winsound.SND_MEMORY)
            except Exception as e: print("speaking:", e)
            self.busy -= 1
    def wait(self):
        while self.busy > 0: time.sleep(0.05)

speaker = Speaker()

# ---------------- one question ----------------
def handle(audio):
    ui.put(("state", "…")); speaker.check_engine(); text = transcribe(audio)
    if not text: ui.put(("idle",)); return
    print("you:", text); ui.put(("state", "looking…"))
    try: img, w, h, mon, (sx, sy) = capture()
    except Exception as e: print("screenshot:", e); img, w, h, mon, sx, sy = None, 0, 0, None, 1, 1
    point = None
    try:
        req = urllib.request.Request(SERVER + "/see", data=json.dumps({"text": text, "image": img, "w": w, "h": h}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            for line in r:
                d = json.loads(line)
                if "stage" in d: ui.put(("state", d["stage"].lower()))
                if "s" in d: print("piper:", d["s"]); speaker.say(d["s"]); ui.put(("state", ""))
                if d.get("point") and mon:
                    p = d["point"]; point = (mon["left"] + p["x"] / sx, mon["top"] + p["y"] / sy, p["label"])
                    ui.put(("point",) + point)   # fly there while still talking, like a person would
    except Exception as e:
        print("server:", e); speaker.say("I can't reach my main program. Is Piper running?")
    speaker.wait(); time.sleep(2.5 if point else 0.3); ui.put(("idle",))

# ---------------- hotkey ----------------
def listen():
    from pynput import keyboard
    K = keyboard.Key
    mods = {"ctrl": {K.ctrl, K.ctrl_l, K.ctrl_r}, "alt": {K.alt, K.alt_l, K.alt_r, K.alt_gr}, "shift": {K.shift, K.shift_l, K.shift_r}}
    need = [mods[k] for k in OPT["hotkey"].split("+")]
    down, rec, st = set(), Recorder(), {"on": False, "t": 0, "spoiled": False, "busy": False}
    def held(): return all(down & m for m in need)
    def press(k):
        down.add(k)
        if st["on"] and not any(k in m for m in need): st["spoiled"] = True   # Ctrl+Alt+something else: a shortcut, not Piper
        if not st["on"] and held() and not st["busy"]:
            st.update(on=True, t=time.time(), spoiled=False)
            try: rec.start(); ui.put(("state", "listening…"))
            except Exception as e: print("microphone:", e); speaker.say("I can't open the microphone."); st["on"] = False
    def release(k):
        down.discard(k)
        if st["on"] and not held():
            st["on"] = False; audio = rec.stop()
            if st["spoiled"] or time.time() - st["t"] < 0.35: ui.put(("idle",)); return
            st["busy"] = True
            def run():
                try: handle(audio)
                finally: st["busy"] = False
            threading.Thread(target=run, daemon=True).start()
    with keyboard.Listener(on_press=press, on_release=release) as l: l.join()

# ---------------- the cursor overlay ----------------
def overlay():
    import tkinter as tk
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)    # whole desktop, all monitors
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    root = tk.Tk(); root.overrideredirect(True); root.attributes("-topmost", True)
    KEY = "#010203"; root.configure(bg=KEY); root.attributes("-transparentcolor", KEY)
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    cv = tk.Canvas(root, bg=KEY, highlightthickness=0); cv.pack(fill="both", expand=True)
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id())   # click-through, never takes focus, not in the taskbar
    style = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
    BLUE, INK = "#3aa0ff", "#e8f4ff"
    s = {"mode": "idle", "text": "", "level": 0.0, "pos": None, "fly": None, "hold": 0}

    def arrow(x, y):
        pts = [x, y, x + 6, y + 20, x + 10, y + 12, x + 19, y + 10]   # small triangle cursor, tip at (x, y)
        cv.create_polygon(pts, fill=BLUE, outline=INK, width=1.5)

    def bubble(x, y, text):
        t = cv.create_text(x + 26, y + 26, text=text, anchor="nw", fill=INK, font=("Segoe UI", 10))
        b = cv.bbox(t); r = cv.create_rectangle(b[0] - 8, b[1] - 5, b[2] + 8, b[3] + 5, fill="#0b1a2b", outline=BLUE)
        cv.tag_raise(t)

    def tick():
        try:
            while True:
                m = ui.get_nowait()
                if m[0] == "state":
                    s["mode"] = "active"
                    if not s["fly"]: s["text"] = m[1]   # while pointing, keep showing the label
                elif m[0] == "level": s["level"] = s["level"] * 0.6 + m[1] * 0.4
                elif m[0] == "idle": s.update(mode="idle", fly=None, text="")
                elif m[0] == "point":
                    start = s["pos"] or mouse_pos()
                    s.update(mode="active", fly=(start, (m[1] - vx, m[2] - vy), time.time()), text=m[3], hold=time.time() + 6)
        except queue.Empty: pass
        cv.delete("all")
        if s["mode"] == "active" or OPT["show_cursor"] == "always":
            mx, my = mouse_pos(); home = (mx - vx + 18, my - vy + 18)
            if s["fly"]:
                (x0, y0), (x1, y1), t0 = s["fly"]
                k = min(1.0, (time.time() - t0) / 0.7); e = 1 - (1 - k) ** 3        # ease out
                cx, cy = (x0 + x1) / 2, min(y0, y1) - 120                            # curved path, like Clicky
                x = (1 - e) ** 2 * x0 + 2 * (1 - e) * e * cx + e * e * x1
                y = (1 - e) ** 2 * y0 + 2 * (1 - e) * e * cy + e * e * y1
                s["pos"] = (x, y)
                if time.time() > s["hold"]: s["fly"] = None
            else: s["pos"] = home
            x, y = s["pos"]; arrow(x, y)
            if s["text"] == "listening…":
                for i in range(5):   # little level meter while you talk
                    hgt = 3 + s["level"] * 14 * (0.6 + 0.4 * math.sin(time.time() * 9 + i))
                    cv.create_rectangle(x + 28 + i * 5, y + 30 - hgt, x + 31 + i * 5, y + 30, fill=BLUE, width=0)
            elif s["text"]: bubble(x, y, s["text"])
        root.after(16, tick)
    tick(); root.mainloop()

def watch_server():
    """Close together with Piper: if the main program has been gone for a minute, stop listening."""
    gone = 0
    while True:
        time.sleep(15)
        try: urllib.request.urlopen(SERVER + "/version", timeout=3); gone = 0
        except Exception:
            gone += 15
            if gone >= 60: print("Piper has closed, so I'm closing too."); ctypes.windll.kernel32.ExitProcess(0)

if __name__ == "__main__":
    if not OPT["enabled"]: raise SystemExit
    import socket
    _lock = socket.socket()
    try: _lock.bind(("127.0.0.1", CFG.get("port", 8790) + 1))   # only one companion at a time
    except OSError: print("Piper on screen is already running."); raise SystemExit
    threading.Thread(target=watch_server, daemon=True).start()
    threading.Thread(target=lambda: (whisper(), print("speech recognition ready")), daemon=True).start()
    threading.Thread(target=listen, daemon=True).start()
    print(f"Piper on screen: hold {OPT['hotkey'].upper()} and talk.")
    overlay()
