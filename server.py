"""Local Piper server. Serves the dashboard and connects the brain, the built-in voice and the knowledge folder.
Start with start-piper.bat (or: python server.py) then open http://localhost:8790"""
import json, os, re, subprocess, threading, http.server, socketserver, pathlib
BUILD = "2026-10-08 build 6 (remembers every conversation, learns what it doesn't know)"
import piper_core, knowledge, wiki, voice, connections, time, brain, atexit
atexit.register(brain.stop)
ROOT = pathlib.Path(__file__).parent; os.chdir(ROOT)
PORT = int(os.environ.get("PORT", json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["port"]))

def _clauses(p, limit=90):
    """Long sentences are voiced in pieces at natural pauses, so the first sound comes sooner."""
    if len(p) <= limit: return [p]
    out, cur = [], ""
    for c in re.split(r"(?<=[,;:\u2014])\s+", p):
        if cur and len(cur) + len(c) > limit: out.append(cur); cur = c
        else: cur = (cur + " " + c).strip()
    if cur: out.append(cur)
    return out

def sentences(text):
    parts = [c for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip() for c in _clauses(p.strip())]
    out, cur = [], ""
    for p in parts:  # join only tiny bits ("Sure." "Done.") so speech flows; never build long pieces
        if cur and (len(cur) >= 30 or len(cur) + len(p) > 90): out.append(cur); cur = p
        else: cur = (cur + " " + p).strip()
    if cur: out.append(cur)
    return out

def prewarm(text):
    if voice.status()["ok"]:
        for s in sentences(text):
            try: voice.synth(s)
            except Exception as e: print("prewarm:", e); break

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")  # always show fresh data
        super().end_headers()
    # ---------- who's asking: this PC, or your phone through Tailscale ----------
    def _remote(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return bool(self.headers.get("Tailscale-User-Login") or self.headers.get("X-Forwarded-For")) or host not in ("localhost", "127.0.0.1", "")
    def _authorised(self):
        if not self._remote(): return True
        r = remote_cfg()
        if not r.get("enabled") or len(str(r.get("pin") or "")) < 6: return False
        c = self.headers.get("Cookie") or ""
        return f"piper_auth={auth_token(r['pin'])}" in c
    def _safe(self):
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        host = self.headers.get("Host") or ""
        return o == "" or o.startswith((f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}", f"https://{host}")) or ".ts.net" in o
    def _redirect(self, url):
        self.send_response(302); self.send_header("Location", url); self.end_headers()
    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", len(body))
        self.end_headers(); self.wfile.write(body)
    def body(self):
        n = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        if not self._authorised():
            if not remote_cfg().get("enabled"): return self._send(b"Piper's phone access is switched off. Run enable-phone.bat on the PC.", "text/plain", 403)
            return self._send(LOGIN_PAGE.encode(), "text/html")
        if self.path in ("/", ""): self.path = "/dashboard.html"
        if self.path == "/brief":
            text, data = piper_core.morning_brief(spoken=True); return self._send({"reply": text, "sentences": sentences(text), "data": data})
        if self.path == "/connections": return self._send(connections.status())
        if self.path == "/schema": return self._send(knowledge.schema())
        if self.path == "/wiki/status": return self._send(wiki.status())
        if self.path == "/brain/status": return self._send(brain.status())
        if self.path == "/version": return self._send({"version": VERSION})
        if self.path == "/brain/script": return self._send({"text": brain.SCRIPT.read_text(encoding="utf-8") if brain.SCRIPT.exists() else ""})
        if self.path == "/wiki/online": return self._send({"online": wiki.online_ok()})
        if self.path == "/status":
            return self._send({"mode": piper_core.MODE, "voice": voice.status(), "knowledge": knowledge.status()})
        if self.path.split("?")[0] not in PUBLIC_FILES:  # never serve memory, settings or anything else in the folder
            return self._send({"error": "not found"}, code=404)
        return super().do_GET()
    def do_POST(self):
        if not self._safe(): return self._send({"error": "blocked"}, code=403)
        if self.path == "/login" and self._remote():
            ip = self.headers.get("X-Forwarded-For", "remote"); now = time.time()
            tries = [t for t in LOGIN_TRIES.get(ip, []) if now - t < 600]
            if len(tries) >= 5: return self._send({"ok": False, "error": "Too many tries. Wait 10 minutes."}, code=429)
            r = remote_cfg(); pin = str(self.body().get("pin", ""))
            import hmac
            if r.get("enabled") and r.get("pin") and hmac.compare_digest(pin, str(r["pin"])):
                LOGIN_TRIES.pop(ip, None)
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"piper_auth={auth_token(r['pin'])}; Max-Age=7776000; Path=/; HttpOnly; Secure; SameSite=Strict")
                body = b'{"ok": true}'; self.send_header("Content-Length", len(body)); self.end_headers(); self.wfile.write(body); return
            LOGIN_TRIES[ip] = tries + [now]; return self._send({"ok": False, "error": "Wrong PIN."}, code=401)
        if not self._authorised(): return self._send({"error": "locked"}, code=401)
        if self.path == "/upload":  # raw file upload (zip, sqlite, pdf, ...) into the knowledge folder
            import re as _re, urllib.parse as up
            name = _re.sub(r"[^\w.-]+", "_", up.unquote(self.headers.get("X-Filename", "upload.bin")))[:120]
            n = int(self.headers.get("Content-Length", 0))
            if n > 60_000_000_000: return self._send({"ok": False, "error": "File too large (60 GB max)."})
            dest = knowledge.folder() / "uploads"; dest.mkdir(parents=True, exist_ok=True); path = dest / name
            with open(path, "wb") as f:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk: break
                    f.write(chunk); left -= len(chunk)
            try:
                if name.lower().endswith(".zim"):  # ZIM library: keep it in the wiki folder, read in place
                    tgt = ROOT / "wiki" / name; tgt.parent.mkdir(exist_ok=True); path.replace(tgt)
                    return self._send({"ok": True, "uploaded": name, "zim": True, "files": 0, "tables": 0, "chunks": 0})
                if wiki.is_wiki_file(path):  # a Wikipedia data set on its own
                    wdir = ROOT / "wiki" / "imports"; wdir.mkdir(parents=True, exist_ok=True); tgt = wdir / name; path.replace(tgt)
                    r = {"ok": True, "uploaded": name, "wiki": wiki.import_async([tgt]), "files": 0, "tables": 0, "chunks": 0}
                    return self._send(r)
                wfiles = []
                if name.lower().endswith(".zip"):
                    d = knowledge.unpack_zip(path); path.unlink()
                    for z in d.rglob("*.zim"): z.replace(ROOT / "wiki" / z.name)
                    wfiles = [x for x in d.rglob("*") if x.is_file() and wiki.is_wiki_file(x)]
                r = knowledge.learn(); r["uploaded"] = name; r["schema"] = knowledge.schema()
                if wfiles: r["wiki"] = wiki.import_async(wfiles)
            except Exception as e: r = {"ok": False, "error": f"Couldn't read {name}: {e}"}
            piper_core.morning_brief(); return self._send(r)
        b = self.body()
        if self.path == "/ask_stream":  # one JSON line per sentence, sent the moment it's ready
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.send_header("Cache-Control", "no-store"); self.end_headers()
            def line(o):
                self.wfile.write((json.dumps(o) + "\n").encode("utf-8")); self.wfile.flush()
            try:
                for s in piper_core.ask_stream(b.get("text", "")):
                    if s.startswith(piper_core.STAGE): line({"stage": s[len(piper_core.STAGE):]}); continue
                    for part in sentences(s):
                        if voice.engine() in ("neural", "fast"): voice.prefetch(part)   # start the voice now, not when the browser asks
                        line({"s": part})
            except (BrokenPipeError, ConnectionResetError): return
            except Exception as e:
                import traceback; tb = traceback.format_exc()
                with open(ROOT / "piper-errors.log", "a", encoding="utf-8") as f: f.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ===\n") + b.get("text", "") + "\n" + tb)
                print(tb); line({"s": f"Sorry, something went wrong inside me: {type(e).__name__}. The details are in piper-errors.log."})
            line({"done": True}); return
        if self.path == "/see":  # screen companion: question + screenshot. Local only, never from the phone.
            if self._remote(): return self._send({"error": "not available remotely"}, code=403)
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.send_header("Cache-Control", "no-store"); self.end_headers()
            def line(o):
                self.wfile.write((json.dumps(o) + "\n").encode("utf-8")); self.wfile.flush()
            try:
                for s in piper_core.screen_stream(b.get("text", ""), b.get("image"), int(b.get("w", 0)), int(b.get("h", 0))):
                    if isinstance(s, dict): line(s); continue
                    if s.startswith(piper_core.STAGE): line({"stage": s[len(piper_core.STAGE):]}); continue
                    for part in sentences(s):
                        if voice.engine() in ("neural", "fast"): voice.prefetch(part)
                        line({"s": part})
            except (BrokenPipeError, ConnectionResetError): return
            except Exception as e:
                import traceback; tb = traceback.format_exc(); print(tb)
                with open(ROOT / "piper-errors.log", "a", encoding="utf-8") as f: f.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S (screen) ===\n") + tb)
                line({"s": f"Sorry, something went wrong while looking: {type(e).__name__}."})
            line({"done": True}); return
        if self.path == "/voice/check":   # ⚙ → VOICE → SPEED CHECK
            try: voice.benchmark()
            except Exception as e: print("voice check:", e)
            return self._send(voice.status())
        if self.path == "/ask":
            try: reply = piper_core.ask(b.get("text", ""))
            except Exception as e:
                import traceback; tb = traceback.format_exc()
                with open(ROOT / "piper-errors.log", "a", encoding="utf-8") as f: f.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ===\n") + b.get("text", "") + "\n" + tb)
                print(tb)
                reply = f"Sorry, something went wrong inside me: {type(e).__name__}: {str(e)[:150]}. The details are in piper-errors.log."
            return self._send({"reply": reply, "sentences": sentences(reply)})
        if self.path == "/tts":
            try: wav = voice.synth(b.get("text", ""), b.get("voice"), b.get("speed"))
            except Exception as e: print("tts error:", e); wav = None
            return self._send(wav, "audio/wav") if wav else self._send({"error": "voice unavailable"}, code=503)
        if self.path == "/wiki/import":  # import from a path on this PC (no copying of huge files)
            import pathlib as pl
            p = pl.Path(b.get("path", "").strip().strip('"'))
            if not p.exists(): return self._send({"ok": False, "error": "I can't find that file or folder."})
            allf = [x for x in (p.rglob("*") if p.is_dir() else [p]) if x.is_file() and wiki.is_wiki_file(x)]
            zims = [x for x in allf if x.suffix.lower() == ".zim"]; files = [x for x in allf if x.suffix.lower() != ".zim"]
            if zims:  # ZIM libraries are read where they are: just remember the location
                c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
                c["wiki_zim_paths"] = sorted(set(c.get("wiki_zim_paths", [])) | {str(p)}); (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
            if not allf: return self._send({"ok": False, "error": "No Wikipedia data files found there."})
            r = wiki.import_async(files) if files else {"ok": True}
            r["zims"] = len(zims); return self._send(r)
        if self.path == "/brain/settings":
            c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            for key in ("brain", "ollama_model"):
                if key in b: c[key] = b[key]
            (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8"); return self._send(brain.status())
        if self.path == "/brain/script":
            brain.SCRIPT.write_text(b.get("text", ""), encoding="utf-8"); return self._send({"ok": True})
        if self.path == "/brain/reset": brain.reset(); return self._send({"ok": True})
        if self.path == "/wiki/settings":
            c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            for key in ("wiki_online", "wiki_save", "wiki_lang"):
                if key in b: c[key] = b[key]
            (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8"); return self._send(wiki.status())
        if self.path == "/query":
            return self._send(knowledge.query(b.get("sql", "")))
        if self.path == "/learn":
            r = knowledge.learn(b.get("folder") or None); piper_core.morning_brief(); return self._send(r)
        if self.path == "/connections/save":
            r = connections.save(b["id"], b.get("fields", {})); piper_core.morning_brief(); return self._send(r)
        if self.path == "/connections/refresh":
            r = connections.refresh_all() if b.get("id") == "all" else connections.refresh(b["id"]); piper_core.morning_brief(); return self._send(r)
        if self.path == "/connections/disconnect":
            r = connections.disconnect(b["id"]); piper_core.morning_brief(); return self._send(r)
        if self.path == "/connections/import":
            try: r = connections.import_instagram(b.get("text", ""))
            except Exception as e: r = {"ok": False, "message": str(e)}
            piper_core.morning_brief(); return self._send(r)
        if self.path == "/settings":
            c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            for k in ("voice", "voice_speed", "voice_engine"):
                if k in b: c[k] = b[k]
            (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8"); return self._send({"ok": True, "config": c})
        self._send({"error": "not found"}, code=404)

def _log_crash(where, exc_type, exc, tb):
    import traceback
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    with open(ROOT / "piper-errors.log", "a", encoding="utf-8") as f: f.write(time.strftime(f"\n=== %Y-%m-%d %H:%M:%S ({where}) ===\n") + text)
    return text

class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    def handle_error(self, request, client_address):
        """A browser closing a page mid-load is normal: ignore it. Anything else is logged, and Piper keeps running."""
        import sys
        et, e, tb = sys.exc_info()
        if isinstance(e, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)): return
        print(f"(a request failed: {type(e).__name__}: {e}. Piper carries on; details in piper-errors.log)")
        _log_crash("request", et, e, tb)
    allow_reuse_address = True; daemon_threads = True

VERSION = "2026-10-07b"

PUBLIC_FILES = {"/dashboard.html", "/piper_data.js", "/manifest.json", "/icon.svg"}
LOGIN_TRIES = {}

def remote_cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("remote") or {}
    except Exception: return {}

def auth_token(pin):
    """A cookie value that proves the PIN was entered, without storing the PIN in the cookie."""
    import hashlib, hmac
    secret_file = ROOT / "brain" / ".remote_secret"
    if not secret_file.exists():
        secret_file.parent.mkdir(exist_ok=True); secret_file.write_text(os.urandom(32).hex())
    return hmac.new(bytes.fromhex(secret_file.read_text().strip()), str(pin).encode(), hashlib.sha256).hexdigest()

LOGIN_PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Piper</title>
<style>body{background:#020a12;color:#5fe3ff;font-family:ui-monospace,Consolas,monospace;display:grid;place-items:center;height:100vh;margin:0}
div{text-align:center;padding:24px}h1{letter-spacing:.4em;font-weight:400}input{background:transparent;border:1px solid #1d5d72;color:#5fe3ff;font:inherit;font-size:28px;
letter-spacing:.4em;text-align:center;width:180px;padding:10px;margin:18px 0}button{background:#5fe3ff;color:#020a12;border:0;font:inherit;padding:12px 30px;letter-spacing:.2em}
p{opacity:.7;font-size:13px}</style></head><body><div><h1>P.I.P.E.R</h1><p>Enter your Piper PIN</p>
<input id="p" type="password" inputmode="numeric" autocomplete="current-password" autofocus><br><button onclick="go()">UNLOCK</button><p id="m"></p></div>
<script>async function go(){const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:document.getElementById('p').value})});
const j=await r.json();if(j.ok)location.href='/';else document.getElementById('m').textContent=j.error}
document.getElementById('p').onkeydown=e=>{if(e.key==='Enter')go()}</script></body></html>"""

def port_free(port):
    """True unless something is actually answering on the port (a closed Piper can leave it 'busy' for a minute)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1)
    try: return s.connect_ex(("127.0.0.1", port)) != 0
    finally: s.close()

if __name__ == "__main__":
    if not port_free(PORT):
        print("\n*** Piper is ALREADY running in another window (port %d is in use). ***" % PORT)
        print("Close ALL black Piper windows, then double-click start-piper.bat once.")
        print("Still stuck? Restart the PC, or run in a command window:  taskkill /f /im python.exe\n")
        input("Press Enter to close..."); raise SystemExit(2)
    knowledge.refresh_if_changed()
    text, _ = piper_core.morning_brief()
    vs = voice.status(); ks = knowledge.status()
    print(f"Piper online at http://localhost:{PORT}")
    print(f"  version:   {BUILD}")
    print(f"  voice:     {'ready (' + vs.get('voice','') + ')' if vs['ok'] else vs['why']}")
    print(f"  knowledge: {ks['files']} files from {ks['folder']}")
    def auto_refresh():
        while True:
            try: connections.refresh_all(); piper_core.morning_brief()
            except Exception as e: print("refresh:", e)
            time.sleep(30 * 60)
    threading.Thread(target=auto_refresh, daemon=True).start()
    threading.Thread(target=brain.warm, daemon=True).start()
    threading.Thread(target=wiki.warm_libraries, daemon=True).start()
    threading.Thread(target=voice.warm, daemon=True).start()
    import memory, awareness; memory.new_session()
    try:
        n = memory.clean_junk()
        if n: print(f"  memory:    removed {n} memories saved by mistake in older versions")
    except Exception as e: print("memory tidy:", e)
    try:
        import conversations
        n = conversations.import_history(memory.load()["history"])
        print(f"  convos:    {conversations.count()} exchanges saved" + (f" ({n} brought in from before)" if n else ""))
    except Exception as e: print("conversation archive:", e)
    import study; study.start()   # studies the everyday topics first, then whatever Morne asks for
    print(f"  study:     {study.counts()['pages']} pages kept" + (f", studying {study.studying_now()['topic']}" if study.studying_now() else ""))
    threading.Thread(target=awareness.idle_learner, daemon=True).start()  # reads one article an hour while idle
    if remote_cfg().get("enabled"): print("  phone:     enabled (PIN protected, via Tailscale)")  # load the model now, not on the first question
    threading.Thread(target=prewarm, args=(text,), daemon=True).start()
    print(f"  secrets:   {connections.VAULT}")
    import sys
    threading.excepthook = lambda a: (print(f"(background task failed: {a.exc_type.__name__}: {a.exc_value})"),
                                      _log_crash("background " + str(getattr(a.thread, "name", "")), a.exc_type, a.exc_value, a.exc_traceback))
    srv = Server(("127.0.0.1", PORT), H)   # this PC only; listening from here on
    if os.environ.get("PIPER_NO_BROWSER") != "1":   # open the page only now that Piper is ready to answer
        import webbrowser
        def _open():
            try: subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"http://localhost:{PORT}"], creationflags=0x08000000) if os.name == "nt" else webbrowser.open(f"http://localhost:{PORT}")
            except Exception: webbrowser.open(f"http://localhost:{PORT}")
        threading.Timer(0.5, _open).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nPiper stopped (Ctrl+C was pressed in this window)."); raise SystemExit(0)
    except BaseException as e:
        _log_crash("Piper stopped", *sys.exc_info())
        print(f"\n*** Piper stopped because of an error: {type(e).__name__}: {e}")
        print("*** The details are saved in piper-errors.log. Piper will restart by itself.")
        raise SystemExit(3)
