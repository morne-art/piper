"""Creates config.json on first run, and adds any new settings from updates without touching existing ones."""
import json, pathlib
ROOT = pathlib.Path(__file__).parent
d = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
p = ROOT / "config.json"
try: c = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
except Exception: c = {}
added = [k for k in d if k not in c]
for k in added: c[k] = d[k]
if added or not p.exists():
    p.write_text(json.dumps(c, indent=2), encoding="utf-8")
    print("settings: added", ", ".join(added) if added else "defaults")
