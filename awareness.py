"""Piper's awareness of the world around Morne: where, when, the weather, and things it has been reading.

Weather comes from Open-Meteo (free, no account, no key). Location is set in config.json
or by saying "I'm in Cape Town" / "set my location to Douglas".
"""
import datetime, json, pathlib, random, re, threading, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
UA = {"User-Agent": "Piper-personal-assistant/1.0"}
_cache = {}
DEFAULT_LOC = {"name": "Douglas, Isle of Man", "lat": 54.15, "lon": -4.48, "timezone": "Europe/Isle_of_Man"}

def cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception: return {}

def _get(url, timeout=6):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r: return json.loads(r.read().decode())

def location(): return {**DEFAULT_LOC, **(cfg().get("location") or {})}

def set_location(place):
    """Look a place up by name and make it Piper's location."""
    r = _get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": place, "count": 1}))
    if not r.get("results"): return None
    g = r["results"][0]
    loc = {"name": ", ".join(x for x in (g.get("name"), g.get("admin1") if g.get("admin1") != g.get("name") else None, g.get("country")) if x),
           "lat": g["latitude"], "lon": g["longitude"], "timezone": g.get("timezone", "UTC")}
    p = ROOT / "config.json"; c = json.loads(p.read_text(encoding="utf-8")); c["location"] = loc
    p.write_text(json.dumps(c, indent=2), encoding="utf-8"); _cache.pop("weather", None); return loc

def now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(location()["timezone"]))
    except Exception: return datetime.datetime.now()

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
       55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
       73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers", 82: "heavy showers", 85: "snow showers",
       86: "heavy snow showers", 95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}

def weather():
    """Current weather + today/tomorrow, cached for 30 minutes. None when offline."""
    c = _cache.get("weather")
    if c and time.time() - c[0] < 1800: return c[1]
    loc = location()
    try:
        r = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto", "forecast_days": 2, "wind_speed_unit": "mph",
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunset"}))
    except Exception: return c[1] if c else None
    cur, d = r["current"], r["daily"]
    w = {"now": f"{WMO.get(cur['weather_code'], 'unsettled')}, {round(cur['temperature_2m'])}°C (feels like {round(cur['apparent_temperature'])}°C), wind {round(cur['wind_speed_10m'])} mph",
         "today": f"{WMO.get(d['weather_code'][0], 'mixed')}, {round(d['temperature_2m_min'][0])} to {round(d['temperature_2m_max'][0])}°C, {d['precipitation_probability_max'][0]}% chance of rain",
         "tomorrow": f"{WMO.get(d['weather_code'][1], 'mixed')}, {round(d['temperature_2m_min'][1])} to {round(d['temperature_2m_max'][1])}°C, {d['precipitation_probability_max'][1]}% chance of rain",
         "sunset": d["sunset"][0][-5:], "rain_chance": d["precipitation_probability_max"][0]}
    _cache["weather"] = (time.time(), w); return w

def situation():
    """One short block every answer gets: where, when, weather."""
    n = now(); loc = location(); w = weather()
    part = "night" if n.hour < 5 else "morning" if n.hour < 12 else "afternoon" if n.hour < 18 else "evening"
    s = f"Now: {n.strftime('%A %d %B %Y, %H:%M')} ({part}) in {loc['name']}."
    if w: s += f" Weather: {w['now']}. Today: {w['today']}. Tomorrow: {w['tomorrow']}. Sunset {w['sunset']}."
    else: s += " Weather: unavailable (offline)."
    return s

# ---------- learning journal: things Piper read about on its own ----------
JOURNAL = ROOT / "brain" / "learning_journal.json"

def journal():
    try: return json.loads(JOURNAL.read_text(encoding="utf-8"))
    except Exception: return []

def _save_journal(j):
    import memory
    memory.safe_write(JOURNAL, j[-200:])

def learn_random(topic=None, min_len=400):
    """Read one article (offline libraries first, then Wikipedia online) and note it in the journal."""
    import wiki
    found = None
    if topic:
        try: found = wiki.search_zims(topic)
        except Exception: pass
        if found: found = {"title": found["title"], "text": found["text"], "source": found["source"]}
    if not found and not topic:
        try:
            paths = [p for p in wiki.zim_paths() if "wikipedia" in p.lower()] or wiki.zim_paths()
            random.shuffle(paths)
            for p in paths[:2]:
                a = wiki.archive(p)
                for _ in range(15):  # skip stubs, lists and odd pages
                    e = a.get_random_entry()
                    if e.is_redirect or re.match(r"^(List of|Index of|\d{4})", e.title): continue
                    txt = wiki.html_text(bytes(e.get_item().content).decode("utf-8", "ignore"))
                    if len(txt) > min_len: found = {"title": e.title, "text": txt, "source": wiki.zim_label(p)[0]}; break
                if found: break
        except Exception: pass
    if not found:
        try:
            lang = wiki.cfg().get("wiki_lang", "en")
            r = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/" + ("summary/" + urllib.parse.quote(topic) if topic else "random/summary"))
            if r.get("extract"):
                found = {"title": r["title"], "text": r["extract"], "source": "Wikipedia online"}
                if wiki.cfg().get("wiki_save", True): wiki.save(r["title"], r["extract"])
        except Exception: pass
    if not found: return None
    entry = {"at": time.time(), "title": found["title"], "summary": wiki.lead(found["text"], 3), "source": found["source"], "shared": False}
    j = journal(); j.append(entry); _save_journal(j); return entry

def mark_shared(title):
    j = journal()
    for e in j:
        if e["title"] == title: e["shared"] = True
    _save_journal(j)

def recent_learning(n=3, unshared_only=False):
    return [e for e in journal() if not (unshared_only and e.get("shared"))][-n:]

def idle_learner(stop_after_idle=1200, every=3600):
    """While Piper is open and nobody's talking, read one article an hour. Cheap: no language model involved."""
    import memory
    while True:
        time.sleep(300)
        if not cfg().get("idle_learning", True): continue
        if cfg().get("study", True): continue   # study mode reads on purpose; random articles were mostly noise
        hist = memory.load()["history"]; last_talk = hist[-1]["at"] if hist else 0
        last_learn = journal()[-1]["at"] if journal() else 0
        if time.time() - last_talk > stop_after_idle and time.time() - last_learn > every:
            try:
                e = learn_random()
                if e: print(f"[idle learning] read about {e['title']} ({e['source']})")
            except Exception as ex: print("idle learning:", ex)
