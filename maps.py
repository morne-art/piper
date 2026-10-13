"""Real distances and directions from OpenStreetMap (free, no key, no account):
  - Nominatim finds where a place is
  - OSRM works out the route by road: distance, driving time, and the turns
Piper answers these questions itself, from real map data, instead of letting the brain guess.
"""
import json, math, pathlib, re, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
UA = {"User-Agent": "Piper-personal-assistant/1.0 (local desktop assistant)"}
_cache = {}
_last = {"t": 0}

def cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception: return {}

def _get(url, timeout=8):
    if "nominatim" in url:   # their rules: at most one request a second
        wait = 1.1 - (time.time() - _last["t"])
        if wait > 0: time.sleep(wait)
        _last["t"] = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def home():
    loc = cfg().get("location") or {}
    return {"name": loc.get("name", "Castletown, Isle of Man"), "lat": loc.get("lat", 54.0738), "lon": loc.get("lon", -4.6531), "country": loc.get("country_code", "im")}

def find(place):
    """Where a place is. Looks near home first (so 'Peel' means Peel on the Isle of Man), then anywhere."""
    key = place.lower().strip()
    if key in ("home", "my house", "my home", "here", "my place"): return home()
    if key in _cache: return _cache[key]
    h = home()
    tries = []
    if h.get("country"): tries.append({"countrycodes": h["country"]})
    tries.append({"viewbox": f"{h['lon']-0.6},{h['lat']+0.4},{h['lon']+0.6},{h['lat']-0.4}", "bounded": 1})
    tries.append({})
    for extra in tries:
        q = {"q": place, "format": "jsonv2", "limit": 1, "addressdetails": 1, **extra}
        r = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(q))
        if r:
            a = r[0]
            out = {"name": a.get("display_name", place).split(",")[0], "full": a.get("display_name", place),
                   "lat": float(a["lat"]), "lon": float(a["lon"]), "type": a.get("type", "")}
            _cache[key] = out; return out
    return None

def route(a, b, mode="driving"):
    url = (f"https://router.project-osrm.org/route/v1/{mode}/{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
           "?overview=false&steps=true")
    r = _get(url)
    if r.get("code") != "Ok" or not r.get("routes"): return None
    rt = r["routes"][0]
    steps = [s for leg in rt["legs"] for s in leg["steps"]]
    return {"metres": rt["distance"], "seconds": rt["duration"], "steps": steps}

def miles(m): return m / 1609.344

def say_dist(m):
    mi = miles(m)
    if mi < 0.2: return f"{round(m / 10) * 10:.0f} metres"
    return f"{mi:.1f} miles" if mi < 10 else f"{mi:.0f} miles"

def say_time(s):
    mins = max(1, round(s / 60))
    if mins < 60: return f"{mins} minute{'s' if mins != 1 else ''}"
    h, m = divmod(mins, 60)
    return f"{h} hour{'s' if h > 1 else ''}" + (f" {m} minutes" if m else "")

def crow(a, b):
    r = 6371000; p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    return 2 * r * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))

def turn_text(s):
    m = s.get("maneuver", {}); kind = m.get("type", ""); mod = m.get("modifier", "")
    road = s.get("name") or s.get("ref") or ""
    road = f"{s.get('ref')} {s.get('name')}".strip() if s.get("ref") and s.get("name") and s.get("ref") not in s.get("name") else road
    on = f" onto {road}" if road else ""
    if kind == "depart": return f"Head {mod or 'off'}{' on ' + road if road else ''}"
    if kind == "arrive": return "you're there"
    if kind in ("roundabout", "rotary", "exit roundabout"): return f"at the roundabout take exit {m.get('exit', '')}{on}".replace("exit  ", "exit ")
    if kind in ("continue", "new name") and road: return f"carry on along {road}"
    if mod and "straight" not in mod: return f"turn {mod}{on}"
    return f"keep going{on}" if road else ""

def directions(steps, n=6):
    keep, last = [], None
    for s in steps:
        t = turn_text(s)
        if not t or t == last: continue
        if s.get("distance", 0) < 60 and s["maneuver"]["type"] not in ("depart", "arrive"): continue  # tiny jinks
        keep.append(t + (f" for {say_dist(s['distance'])}" if s.get("distance", 0) > 400 and s["maneuver"]["type"] != "arrive" else "")); last = t
    if len(keep) > n: keep = keep[: n - 1] + [keep[-1]]
    if len(keep) > 1 and keep[-1] == "you're there": return ", then ".join(keep[:-1]) + ", and you're there."
    return ", then ".join(keep) + "."

# ---------- what Morne might ask ----------
PFX = r"^(?:hey piper[, ]*)?"
FAR = [re.compile(PFX + r"how far (?:away )?(?:is it |is |are we |am i )?(?:from\s+(?P<a>.+?)\s+to\s+(?P<b>.+?)|(?:to\s+)?(?P<c>.+?)(?:\s+from\s+(?P<d>.+?))?)(?:\s+(?:by car|driving|on foot|walking))?\s*[?.!]*$", re.I),
       re.compile(PFX + r"how long (?:does|would|will|did) it take (?:me |us )?to (?:get|drive|walk|go|cycle)\s+(?:from\s+(?P<a>.+?)\s+to\s+(?P<b>.+?)|to\s+(?P<c>.+?)(?:\s+from\s+(?P<d>.+?))?)(?:\s+(?:by car|on foot))?\s*[?.!]*$", re.I),
       re.compile(PFX + r"(?:what(?:'s| is) the )?(?:distance|mileage|drive|driving time) (?:from\s+(?P<a>.+?)\s+to\s+(?P<b>.+?)|to\s+(?P<c>.+?)(?:\s+from\s+(?P<d>.+?))?)\s*[?.!]*$", re.I)]
WAY = re.compile(PFX + r"(?:how (?:do|can|would|should) i get to|(?:give me |get )?directions to|take me to|route to|how to get to|which way (?:is it )?to)\s+"
                 r"(?P<b>.+?)(?:\s+from\s+(?P<a>.+?))?\s*[?.!]*$", re.I)
WHERE = re.compile(PFX + r"where(?:'s| is| are)\s+(?P<b>[A-Z0-9][\w'.-]*(?:\s+(?:[A-Z0-9][\w'.-]*|of|the|upon|on|de))*?)(?:\s+(?:located|exactly))?\s*[?.!]*$")

NOT_PLACE = re.compile(r"(?i)\b(it|that|this|them|him|her|my|order|christmas|weekend|done|finish|ready|charge|load|arrive|deliver|along|you|studying|learning)\b")

def looks_like(text):
    """Would ask() treat this as a map question? (Used for the 'Checking the map' caption.)"""
    t = text.strip()
    m = WAY.match(t) or next((x.match(t) for x in FAR if x.match(t)), None)
    if m:
        g = m.groupdict(); b = g.get("b") or g.get("c") or ""
        return bool(_clean(b)) and not NOT_PLACE.search(_clean(b)) and not NOT_PLACE.search(_clean(g.get("a") or g.get("d") or ""))
    m = WHERE.match(t)
    return bool(m) and len(m.group("b").split()) <= 5

def _clean(p):
    p = re.sub(r"(?i)^(?:to\s+)?(?:walk|drive|cycle|get|go)\s+(?:to\s+)?", "", (p or "").strip())
    p = re.sub(r"(?i)^(?:the\s+(?=[a-z]+ (?:road|street|lane)))|\b(?:on the isle of man|in the isle of man|on the island)\b|\s+(?:by car|driving|on foot|walking)$", "", p)
    return p.strip(" ,?.!")

def ask(text):
    """Answer a distance / directions question from real map data. None if it isn't one."""
    walk = bool(re.search(r"\b(walk|walking|on foot)\b", text, re.I))
    m = WAY.match(text.strip()); want_turns = bool(m)
    if m: a, b = m.group("a"), m.group("b")
    else:
        m = next((x.match(text.strip()) for x in FAR if x.match(text.strip())), None)
        if m: a, b = (m.group("a"), m.group("b")) if m.group("b") else (m.group("d"), m.group("c"))
        else:
            m = WHERE.match(text.strip())
            if not m or len(m.group("b").split()) > 5: return None
            return where(_clean(m.group("b")))
    a, b = _clean(a) or "home", _clean(b)
    if not b or len(b.split()) > 7 or re.search(r"(?i)\b(it|that|this|them|him|her|order|christmas|weekend|done|finish|ready|charge|load|arrive|deliver)\b", b): return None
    if a != "home" and re.search(r"(?i)\b(it|that|this|order)\b", a): return None
    try:
        pa, pb = find(a), find(b)
    except Exception as e:
        return "I need the internet to look at the map, and I can't reach it right now."
    if not pa: return f"I couldn't find {a} on the map."
    if not pb: return f"I couldn't find {b} on the map."
    try: r = route(pa, pb, "foot" if walk else "driving")
    except Exception: r = None
    na = "here" if a == "home" else pa["name"]
    if not r:
        return f"I couldn't work out a route, but {pb['name']} is {say_dist(crow(pa, pb))} from {na} in a straight line."
    how = "on foot" if walk else "by car"
    secs = r["metres"] / 1.35 if walk else r["seconds"]   # the public router only does cars; walking is at about 3 mph
    out = f"{pb['name']} is {say_dist(r['metres'])} from {na} by road, about {say_time(secs)} {how}."
    if want_turns and r["steps"]: out += " " + directions(r["steps"])
    return out + " That's from OpenStreetMap."

def where(place):
    try: p = find(place)
    except Exception: return None
    if not p: return None
    h = home(); d = crow(h, p)
    near = ", right by home" if d < 1000 else f", about {say_dist(d)} from home as the crow flies" if d < 300_000 else ""
    return f"{p['name']} is in {', '.join(p['full'].split(', ')[1:4]) or 'that area'}{near}. That's from OpenStreetMap."
