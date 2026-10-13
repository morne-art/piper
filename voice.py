"""Built-in neural voice (Kokoro, runs 100% locally on your PC). Models live in ./models (downloaded once by install.bat)."""
import io, json, hashlib, os, pathlib, threading, re, time
ROOT = pathlib.Path(__file__).parent
MODELS = ROOT / "models"; CACHE = ROOT / "voice_cache"
URLS = {"kokoro-v1.0.int8.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
        "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}
VOICES = {"bm_george": "George (British, deep, butler)", "bm_lewis": "Lewis (British, warm)", "bm_daniel": "Daniel (British, crisp)",
          "bm_fable": "Fable (British, storyteller)", "bf_emma": "Emma (British female)", "bf_isabella": "Isabella (British female)"}
# Fast natural voices (Piper TTS: built for modest processors, about 25x faster than Kokoro on Morne's PC)
FAST_DIR = MODELS / "piper"
FAST_VOICES = {   # id -> (label, gender)
    "en_GB-alan-medium": ("Alan (British male, fast)", "m"),
    "en_GB-northern_english_male-medium": ("Northern English male (fast)", "m"),
    "en_GB-jenny_dioco-medium": ("Jenny (British female, fast)", "f"),
    "en_GB-cori-high": ("Cori (British female, fast)", "f"),
    "en_GB-alba-medium": ("Alba (Scottish female, fast)", "f"),
    "en-gb-alan-low": ("Alan (British male, fast, basic)", "m"),
    "en-gb-southern_english_female-low": ("Southern English female (fast, basic)", "f"),
}
_fast = {}

_lib_cache = {}
def _piper_lib():
    """The real fast-voice library (piper-tts), never a folder that just happens to be called 'piper'.
    Returns (PiperVoice, SynthesisConfig) or None if the engine isn't installed (yet)."""
    import sys, importlib
    if _lib_cache.get("ok"): return _lib_cache["ok"]
    if time.time() - _lib_cache.get("failed", 0) < 30: return None   # checked recently: setup may still be installing it
    def real(): from piper import PiperVoice, SynthesisConfig; return PiperVoice, SynthesisConfig
    try: _lib_cache["ok"] = real(); return _lib_cache["ok"]
    except Exception: pass
    sys.modules.pop("piper", None)   # a plain folder was picked up: look past it
    saved = list(sys.path)
    sys.path[:] = [p for p in sys.path if not (pathlib.Path(p or ".") / "piper").is_dir()
                   or (pathlib.Path(p or ".") / "piper" / "__init__.py").exists()]
    try: importlib.invalidate_caches(); _lib_cache["ok"] = real(); return _lib_cache["ok"]
    except Exception: sys.modules.pop("piper", None); _lib_cache["failed"] = time.time(); return None
    finally: sys.path[:] = saved

def fast_installed():
    """Fast voices present on this PC (both the .onnx and its .json) AND the engine that plays them."""
    if not FAST_DIR.exists(): return []
    if not _piper_lib(): return []
    return [i for i in FAST_VOICES if (FAST_DIR / f"{i}.onnx").exists() and (FAST_DIR / f"{i}.onnx.json").exists()]

def _fast_for(voice):
    """Which fast voice to use: the chosen one, or the same gender as the chosen Kokoro voice."""
    have = fast_installed()
    if not have: return None
    if voice in have: return voice
    g = "f" if (voice or "").startswith(("bf_", "af_")) else "m"
    return next((i for i in have if FAST_VOICES[i][1] == g), have[0])

def _synth_fast(text, vid, speed):
    PiperVoice, SynthesisConfig = _piper_lib()
    import wave
    if vid not in _fast: _fast[vid] = PiperVoice.load(str(FAST_DIR / f"{vid}.onnx"))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        _fast[vid].synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / max(0.5, min(2.0, speed))))
    return buf.getvalue()

_k = None; _lock = threading.Lock(); _err = None

def cfg(): return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

def available():
    return all((MODELS / f).exists() for f in URLS)

def _load():
    global _k, _err
    if _k or _err: return _k
    try:
        from kokoro_onnx import Kokoro
        _k = None
        if _k is None:   # always the processor: the graphics-card engine crashed Piper on this PC
            os.environ["ONNX_PROVIDER"] = "CPUExecutionProvider"
            try:
                import onnxruntime as ort
                sess = ort.InferenceSession(str(MODELS / "kokoro-v1.0.int8.onnx"), providers=["CPUExecutionProvider"])
                _k = Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))
            except AttributeError:   # older kokoro-onnx without from_session
                _k = Kokoro(str(MODELS / "kokoro-v1.0.int8.onnx"), str(MODELS / "voices-v1.0.bin"))
            state["device"] = "processor"
    except Exception as e:
        _err = str(e); print("voice unavailable:", e)
    return _k

def _remember_cpu():
    """Never try the graphics card again on this PC (it failed once; it will fail again)."""
    try:
        c = cfg(); c["voice_device"] = "cpu"
        (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
    except Exception: pass

def status():
    if not available() and not fast_installed(): return {"ok": False, "why": "voice models not downloaded, run install.bat"}
    try: import kokoro_onnx  # noqa
    except Exception as e:
        if not fast_installed(): return {"ok": False, "why": f"kokoro-onnx not installed ({e})"}
    allv = {**{i: FAST_VOICES[i][0] for i in fast_installed()}, **{k: n + " (slower)" for k, n in VOICES.items()}}
    return {"ok": (_err is None) or bool(fast_installed()), "why": _err or "ready", "voice": cfg().get("voice"), "speed": cfg().get("voice_speed", 1.0), "voices": allv,
            "engine": engine(), "setting": cfg().get("voice_engine", "auto"), "rtf": state.get("rtf"), "device": state.get("device"),
            "verdict": verdict()}

def engine():
    """'fast'    = fast natural voice (Piper TTS): natural and instant, preferred whenever installed
    'neural'  = Kokoro natural voice: lovely, but slower than speech on many PCs
    'windows' = Windows' built-in voice: last resort
    The dashboard treats 'fast' and 'neural' the same: both come from /tts."""
    want = cfg().get("voice_engine", "auto")
    chosen = cfg().get("voice", "")
    if want == "windows": return "windows"
    if chosen in FAST_VOICES and chosen in fast_installed(): return "fast"
    if want == "neural" and available() and not _err: return "neural"
    if fast_installed(): return "fast"
    if _err or not available(): return "windows"
    r = state.get("rtf")
    return "windows" if r is not None and r > 0.6 else "neural"

def verdict():
    if engine() == "fast":
        fv = _fast_for(cfg().get("voice", ""))
        return f"Fast natural voice: {FAST_VOICES[fv][0].split(' (')[0]}. No delay." + (" (Your Kokoro voice is too slow on this PC, so a fast voice of the same kind is used.)" if cfg().get("voice","") not in FAST_VOICES else "")
    r = state.get("rtf")
    if _err or not available(): return "The natural voice isn't installed, so Piper uses the Windows voice."
    if r is None: return "Measuring voice speed…"
    where = state.get("device", "processor")
    if r <= 0.3: return f"Fast: the natural voice is made {1/r:.0f}× quicker than it's spoken (on the {where}). No delay."
    if r <= 0.6: return f"OK: the natural voice is made {1/r:.1f}× quicker than it's spoken (on the {where}). Small delay at the start."
    return (f"Too slow: on this PC's {where} the natural voice takes {r:.1f}s to make each second of speech, which causes the lag. "
            + ("Piper is using the instant Windows voice instead." if cfg().get("voice_engine", "auto") == "auto" else ""))

BENCH = "Good afternoon. Your next event is at three, and it looks like rain later, so take a coat."
def benchmark():
    """Times the natural voice on a typical sentence (not cached), and remembers the result."""
    k = _load()
    if not k: return None
    import time as _t
    with _lock:
        k.create("Ready.", voice=cfg().get("voice", "bm_george"), speed=1.0, lang="en-gb")   # first run is always slower
        t0 = _t.time(); a, sr = k.create(BENCH, voice=cfg().get("voice", "bm_george"), speed=1.0, lang="en-gb"); took = _t.time() - t0
    state["rtf"] = round(took / max(len(a) / sr, 0.1), 2)
    print(f"[voice] speed check on the {state.get('device')}: {took:.2f}s for {len(a)/sr:.1f}s of speech -> {engine()} voice")
    return state["rtf"]

def speakable(t):
    """Make text sound natural when spoken."""
    t = re.sub(r"[\[\]*#_`>]", "", t)
    t = t.replace("&", " and ").replace("%", " percent").replace(" e.g.", " for example")
    t = re.sub(r"@(\w+)", r"\1", t)
    c = cfg()
    if c.get("owner_say") and c.get("owner"):   # say Morne's name the way he pronounces it
        t = re.sub(rf"\b{re.escape(c['owner'])}\b", c["owner_say"], t)
    return re.sub(r"\s+", " ", t).strip()

def synth(text, voice=None, speed=None):
    """Return WAV bytes, cached on disk so repeated lines are instant."""
    c = cfg(); voice = voice or c.get("voice", "bm_george"); speed = float(speed or c.get("voice_speed", 1.0))
    text = speakable(text)
    if not text: return None
    CACHE.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{voice}|{speed}|{text}".encode()).hexdigest()[:20]; f = CACHE / f"{key}.wav"
    if f.exists(): return f.read_bytes()
    fv = voice if voice in FAST_VOICES else (_fast_for(voice) if engine() == "fast" else None)
    if fv and fv in fast_installed():
        with _lock:
            if f.exists(): return f.read_bytes()   # made by the prefetch while we waited: don't make it twice
            t0 = time.time(); data = _synth_fast(text, fv, speed)
            state.update(last_s=round(time.time() - t0, 2)); print(f"[voice] fast ({fv}) {time.time()-t0:.2f}s for {len(text)} chars")
        f.write_bytes(data); return data
    with _lock:
        if f.exists(): return f.read_bytes()   # made by another request while we waited
        t0 = time.time()
        k = _load()
        if not k: return None
        import soundfile as sf
        import numpy as np
        lang = "en-gb" if voice.startswith("b") else "en-us"
        def gen(t):
            for v in (t, t.replace(",", ""), t + " ...", t.rstrip(".!?") + "."):
                a, r = k.create(v, voice=voice, speed=speed, lang=lang)
                if len(a): return a, r
            return np.zeros(0, dtype="float32"), 24000
        samples, sr = gen(text)
        if not len(samples):  # rare model hiccup: fall back to speaking sentence by sentence
            parts = [gen(p) for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
            gap = np.zeros(int(0.18 * 24000), dtype="float32"); sr = 24000
            samples = np.concatenate(sum([[a, gap] for a, _ in parts if len(a)], [])) if any(len(a) for a, _ in parts) else np.zeros(0, dtype="float32")
        if not len(samples): return None
        buf = io.BytesIO(); sf.write(buf, samples, sr, format="WAV"); data = buf.getvalue()
        took = time.time() - t0; secs = len(samples) / sr
        state.update(last_s=round(took, 2), last_audio_s=round(secs, 1))
        print(f"[voice] {took:.2f}s to make {secs:.1f}s of speech ({len(text)} chars)")
    f.write_bytes(data); return data

state = {}
_pre = None
def prefetch(text):
    """Start making the audio for a sentence now, in order, before anyone asks for it."""
    global _pre
    import concurrent.futures as cf
    if _pre is None: _pre = cf.ThreadPoolExecutor(max_workers=1)
    _pre.submit(lambda: synth(text))

def warm():
    """Load the voice engine at start-up (not on the first question) and measure how fast this PC makes speech."""
    try:
        if fast_installed() and engine() == "fast":   # fast voice: no need to time Kokoro (saves several seconds of processor)
            t0 = time.time(); synth("Ready.")
            print(f"voice ready: fast natural voice ({time.time()-t0:.1f}s)"); return
        if available(): benchmark()
    except Exception as e: print("voice warm-up:", e)

def download():
    import urllib.request
    MODELS.mkdir(exist_ok=True)
    for name, url in URLS.items():
        dest = MODELS / name
        if dest.exists(): print("already have", name); continue
        print(f"downloading {name} (one time only)...")
        def hook(n, bs, total):
            if total > 0 and n % 200 == 0: print(f"  {min(100, n*bs*100//total)}%", end="\r")
        urllib.request.urlretrieve(url, dest, hook); print(f"  done: {name}        ")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "download": download()
    else:
        d = synth("Good evening. All systems are online, and everything is running smoothly.")
        open("voice_test.wav", "wb").write(d) if d else print(status()); print("wrote voice_test.wav" if d else "")
