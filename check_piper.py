"""Checks why Piper isn't answering and writes everything to piper-check.txt (upload that file)."""
import importlib, io, json, os, pathlib, platform, socket, subprocess, sys, time, traceback, urllib.request

ROOT = pathlib.Path(__file__).parent
out = io.StringIO()
def say(*a):
    line = " ".join(str(x) for x in a); print(line); out.write(line + "\n")

say("=== Piper check", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
say("Python:", sys.version.split()[0], sys.executable)
say("Windows:", platform.platform())
say("Folder:", ROOT)
say("Files present:", ", ".join(sorted(p.name for p in ROOT.iterdir() if p.is_file())[:80]))

# 0. folders that confuse Python, and the fast voice engine
stray = [p for p in (ROOT / "piper", ROOT.parent / "piper") if p.is_dir() and p != ROOT and not (p / "__init__.py").exists()]
say("Stray 'piper' folders:", ", ".join(str(p) for p in stray) or "none")
r = subprocess.run([sys.executable, "-c", "from piper import PiperVoice; import piper; print(piper.__file__)"],
                   cwd=str(ROOT / "models") if (ROOT / "models").exists() else None, capture_output=True, text=True)
say("Fast voice engine (piper-tts):", ("installed at " + r.stdout.strip()) if r.returncode == 0 else "NOT installed: " + (r.stderr.strip().splitlines() or ["?"])[-1])
fv = sorted(p.name for p in (ROOT / "models" / "piper").glob("*.onnx")) if (ROOT / "models" / "piper").exists() else []
say("Fast voices downloaded:", ", ".join(fv) or "none")
for mod in ("ddgs", "openjarvis"):
    try: importlib.import_module(mod); say(f"{mod}: installed")
    except Exception as e: say(f"{mod}: not installed ({type(e).__name__})")
try:
    st = json.loads((ROOT / "learned" / "study.json").read_text(encoding="utf-8"))
    say("Study:", "; ".join(f"{v['topic']}={v['status']} {v.get('pages', 0)}p" + (f" ({v['error']})" if v.get("error") else "") for v in st["topics"].values()))
except Exception as e: say("Study: no study list yet", type(e).__name__)

# 1. settings
try:
    c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    say("config.json: OK, port", c.get("port"), "| brain", c.get("brain"), "| ollama_model", c.get("ollama_model"), "| voice", c.get("voice"))
    port = int(c.get("port", 8790))
except Exception as e:
    say("config.json: PROBLEM:", e); port = 8790

# 2. is something already listening?
s = socket.socket(); s.settimeout(1)
busy = s.connect_ex(("127.0.0.1", port)) == 0; s.close()
say(f"Port {port}:", "something IS answering there" if busy else "nothing running there")
if busy:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=5) as r: say("  /version ->", r.read()[:200])
    except Exception as e: say("  /version failed:", e)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ask_stream", data=b'{"text":"hello"}', headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r: say("  ask 'hello' ->", r.read()[:300])
    except Exception as e: say("  ask failed:", e)
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=20)
        say("  netstat:", [l.strip() for l in r.stdout.splitlines() if f":{port} " in l][:5])
    except Exception as e: say("  netstat failed:", e)

# 3. can every part of Piper load?
for m in ("memory", "awareness", "knowledge", "wiki", "voice", "connections", "brain", "websearch", "thoughts", "piper_core", "server"):
    t0 = time.time()
    try:
        sys.path.insert(0, str(ROOT)); importlib.import_module(m); say(f"load {m}: OK ({time.time()-t0:.1f}s)")
    except BaseException as e:
        say(f"load {m}: FAILED: {type(e).__name__}: {e}"); say(traceback.format_exc())

# 4. Ollama
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
        say("Ollama: running, models:", [m["name"] for m in json.loads(r.read()).get("models", [])])
except Exception as e: say("Ollama: not reachable:", e)

# 5. if nothing was running, start Piper for 40 seconds and record what it says
if not busy:
    say("\n--- starting server.py for 40 seconds ---")
    p = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    t0 = time.time(); up = False
    while time.time() - t0 < 40 and p.poll() is None:
        time.sleep(2)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=2): up = True; break
        except Exception: pass
    say("Server", f"answered after {time.time()-t0:.0f}s" if up else ("STOPPED with code " + str(p.returncode) if p.poll() is not None else "did not answer within 40s"))
    if up:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/ask_stream", data=b'{"text":"hello"}', headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r: say("ask 'hello' ->", r.read()[:300])
        except Exception as e: say("ask failed:", e)
    p.terminate()
    try: say("--- server output ---\n" + (p.communicate(timeout=10)[0] or "")[-4000:])
    except Exception as e: say("output unavailable:", e)

for f in ("piper-errors.log",):
    if (ROOT / f).exists(): say(f"--- {f} (last part) ---\n" + (ROOT / f).read_text(encoding="utf-8", errors="replace")[-3000:])

(ROOT / "piper-check.txt").write_text(out.getvalue(), encoding="utf-8")
print("\nSaved: piper-check.txt  <- upload this file")
