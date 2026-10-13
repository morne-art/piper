"""One-time setup of Piper's built-in brain (no Ollama needed).

Downloads:
  engine/cpu/     llama.cpp server for any PC                (~18 MB)
  engine/gpu/     llama.cpp server using the graphics card   (~31 MB, Vulkan: NVIDIA, AMD, Intel)
  models/*.gguf   a language model sized to this PC's memory  (1-5 GB)

Models are chosen for licences that allow free use and sharing:
  under 8 GB RAM   Qwen2.5 1.5B Instruct  (Apache 2.0)  ~1.1 GB  quick, simple chat
  8-15 GB RAM      Phi-3.5 mini Instruct  (MIT)         ~2.4 GB  good all-rounder
  16 GB+ RAM       Qwen2.5 7B Instruct    (Apache 2.0)  ~4.7 GB  best quality
Run:  python setup_brain.py            (auto)
      python setup_brain.py small|medium|large   (choose)
"""
import ctypes, json, os, pathlib, platform, shutil, sys, urllib.request, zipfile

ROOT = pathlib.Path(__file__).parent
UA = {"User-Agent": "Piper-setup"}
MODELS = {
    "small":  ("qwen2.5-1.5b-instruct-q4_k_m.gguf",
               "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf", "1.1 GB"),
    "medium": ("Phi-3.5-mini-instruct-Q4_K_M.gguf",
               "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf", "2.4 GB"),
    "large":  ("Qwen2.5-7B-Instruct-Q4_K_M.gguf",
               "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf", "4.7 GB"),
}

def ram_gb():
    try:
        if os.name == "nt":
            class M(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("t", ctypes.c_ulonglong)] + [(f"x{i}", ctypes.c_ulonglong) for i in range(6)]
            m = M(); m.l = ctypes.sizeof(M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.t / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except Exception: return 8

def pick_size():
    r = ram_gb()
    return ("large" if r >= 15 else "medium" if r >= 7.5 else "small"), r

def download(url, dest, label):
    dest = pathlib.Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000: print(f"  {label}: already downloaded"); return dest
    tmp = dest.with_suffix(dest.suffix + ".part"); have = tmp.stat().st_size if tmp.exists() else 0
    req = urllib.request.Request(url, headers={**UA, **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "ab" if have else "wb") as f:
        total = int(r.headers.get("Content-Length", 0)) + have; done = have
        while chunk := r.read(1 << 20):
            f.write(chunk); done += len(chunk)
            if total: print(f"\r  {label}: {done / 2**20:,.0f} / {total / 2**20:,.0f} MB", end="", flush=True)
    print(); tmp.replace(dest); return dest

def engine():
    if os.name != "nt": print("  engine: Windows only (on other systems use Ollama)"); return
    if platform.machine().lower() in ("arm64", "aarch64"): arch = "arm64"
    else: arch = "x64"
    rel = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=1", headers=UA), timeout=30))[0]
    for kind, key in (("cpu", f"bin-win-cpu-{arch}.zip"), ("gpu", f"bin-win-vulkan-{arch}.zip")):
        out = ROOT / "engine" / kind
        if (out / "llama-server.exe").exists(): print(f"  engine ({kind}): already installed"); continue
        a = next((a for a in rel["assets"] if a["name"].startswith("llama-") and a["name"].endswith(key)), None)
        if not a: print(f"  engine ({kind}): not available for this PC"); continue
        z = download(a["browser_download_url"], ROOT / "engine" / a["name"], f"engine ({kind})")
        with zipfile.ZipFile(z) as f: f.extractall(out)
        for exe in out.rglob("llama-server.exe"):  # flatten if zipped inside a folder
            if exe.parent != out:
                for x in exe.parent.iterdir(): shutil.move(str(x), out / x.name)
        z.unlink()
    (ROOT / "engine" / "VERSION").write_text(rel["tag_name"])

def main():
    size, r = pick_size()
    if len(sys.argv) > 1 and sys.argv[1] in MODELS: size = sys.argv[1]
    name, url, mb = MODELS[size]
    print(f"This PC has {r:.0f} GB of memory, so Piper will use the {size} brain ({mb}).")
    print("Installing the engine...")
    try: engine()
    except Exception as e: print("  engine download failed:", e)
    print("Downloading the language model (one time only, resumes if interrupted)...")
    try: download(url, ROOT / "models" / name, "model")
    except Exception as e: print("  model download failed:", e, "\n  Run install.bat again to resume."); return
    cfg_path = ROOT / "config.json"; c = json.loads(cfg_path.read_text(encoding="utf-8"))
    c["local_model"] = name; cfg_path.write_text(json.dumps(c, indent=2), encoding="utf-8")
    print("Piper's brain is ready.")

if __name__ == "__main__":
    main()
