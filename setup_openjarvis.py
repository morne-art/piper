"""One-time: installs OpenJarvis as Piper's engine room and locks it to private settings.
Piper uses OpenJarvis's tools (web search) directly. OpenJarvis's own server, agents, mining and
command/file tools are never started."""
import os, pathlib, subprocess, sys

def main():
    skip = os.environ.get("PIPER_SKIP_PIP")
    print("Installing web search (DuckDuckGo)...")
    if not skip: subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "ddgs"])   # on its own, so it works even if OpenJarvis can't install
    if sys.version_info >= (3, 14):
        print(f"OpenJarvis supports Python 3.10 to 3.13; this PC has {sys.version.split()[0]}. "
              "Skipping it: Piper searches DuckDuckGo directly instead, which works the same.")
        return 0
    print("Installing OpenJarvis (Stanford's local-first assistant toolkit)...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "openjarvis"]) if not skip else subprocess.CompletedProcess([], 0)
    if r.returncode: print("OpenJarvis didn't install. Piper still works, and searches DuckDuckGo directly."); return 0
    home = pathlib.Path(os.environ.get("OPENJARVIS_HOME") or pathlib.Path.home() / ".openjarvis"); home.mkdir(exist_ok=True)
    cfg = home / "config.toml"
    import tomlkit
    doc = tomlkit.parse(cfg.read_text(encoding="utf-8")) if cfg.exists() else tomlkit.document()
    doc.setdefault("analytics", tomlkit.table())["enabled"] = False          # no usage reports to the OpenJarvis team
    doc.setdefault("engine", tomlkit.table())["default"] = "ollama"           # the brain on this PC
    doc["engine"].setdefault("ollama", tomlkit.table())["host"] = "http://localhost:11434"
    cfg.write_text(tomlkit.dumps(doc), encoding="utf-8")
    print("OpenJarvis settings:", cfg, "(usage reporting off, local brain only)")
    from openjarvis.tools.web_search import WebSearchTool  # proves it imports
    print("OpenJarvis is ready.")
    return 0

if __name__ == "__main__": sys.exit(main())
