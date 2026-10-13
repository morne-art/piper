"""One-time: installs the fast natural voices (Piper TTS). They live in models/piper and never leave this PC."""
import pathlib, subprocess, sys, tarfile, urllib.request, io

ROOT = pathlib.Path(__file__).parent
DEST = ROOT / "models" / "piper"
WANT = ["en_GB-alan-medium", "en_GB-jenny_dioco-medium", "en_GB-northern_english_male-medium"]
FALLBACK = {  # older copies on GitHub, used only if the main voice library can't be reached
    "en-gb-alan-low": "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-gb-alan-low.tar.gz",
    "en-gb-southern_english_female-low": "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-gb-southern_english_female-low.tar.gz",
}

def have(v): return (DEST / f"{v}.onnx").exists() and (DEST / f"{v}.onnx.json").exists()

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    print("Installing the fast voice engine (Piper TTS)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "piper-tts"])
    ok = subprocess.run([sys.executable, "-c", "from piper import PiperVoice"], cwd=str(DEST), capture_output=True, text=True)
    if ok.returncode:   # checked from the voices folder, so a folder named 'piper' can't fool it
        print("The fast voice engine didn't install:", (ok.stderr or ok.stdout).strip()[-400:])
        print("Piper will keep using the Windows voice. Send me piper-check.txt (run check-piper.bat) and I'll sort it.")
        return 1
    for v in WANT:
        if have(v): print("already have", v); continue
        print("Downloading voice", v, "(about 60 MB)...")
        subprocess.run([sys.executable, "-m", "piper.download_voices", v, "--download-dir", str(DEST)], cwd=str(DEST))
    if not any(have(v) for v in WANT):
        print("Main voice library unreachable; using the GitHub copies instead.")
        for v, url in FALLBACK.items():
            if have(v): continue
            try:
                data = urllib.request.urlopen(url, timeout=120).read()
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    for m in t.getmembers():
                        if m.name.endswith((".onnx", ".onnx.json")):
                            m.name = pathlib.Path(m.name).name; t.extract(m, DEST)
            except Exception as e: print("  couldn't get", v, e)
    got = [p.name[:-5] for p in DEST.glob("*.onnx")]
    print("Fast voices ready:", ", ".join(got) if got else "none")
    return 0 if got else 1

if __name__ == "__main__": sys.exit(main())
