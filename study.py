"""Study mode: Piper reads dozens of pages about a topic in the background and keeps them, so it can answer from them later,
even offline. Everything it reads is stored in learned/learned.sqlite as searchable passages, with where it came from.

Sources, in order:
  1. official help sites for everyday tech (Apple, Google, Microsoft support pages) and good how-to guides, via DuckDuckGo
  2. Wikipedia: the main article plus the most related linked articles
  3. offline libraries (ZIM files) when there is no internet
Progress lives in learned/study.json, so a study carries on after a restart.
"""
import urllib.error, html, json, pathlib, re, sqlite3, threading, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
DIR = ROOT / "learned"
DB = DIR / "learned.sqlite"
STATE = DIR / "study.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Piper-personal-assistant/1.0"
SKIP = re.compile(r"youtube\.|youtu\.be|facebook\.|instagram\.|tiktok\.|pinterest\.|(?:^|\.)x\.com|twitter\.|amazon\.|ebay\.|quora\.", re.I)
STOP = set("a an the and or of to in on at for with is are was were be how do does did i my me you your what which who why when where can could "
           "should would will it its this that these those from by about into as if than then so not no yes there their they he she we us "
           "come came out get got go going goes make made want need know tell please much many long ever still just really also some any thing "
           "things way does doing done put set show give see look".split())
DEFAULT_TOPICS = ["Isle of Man", "iPhone and iOS", "Windows 11", "Gmail", "Google Calendar", "Google Drive", "Google Docs", "Google Sheets"]
OFFICIAL = [(r"iphone|ios|ipad|mac|apple|airpods|icloud|facetime|imessage", "support.apple.com"),
            (r"google|gmail|calendar|drive|docs|sheets|slides|workspace|android|chrome|meet|keep", "support.google.com"),
            (r"windows|\bpc\b|laptop|excel|word|outlook|powerpoint|onedrive|teams|microsoft|edge", "support.microsoft.com")]

def cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception: return {}

_lock = threading.RLock()

def stem(w):
    """Tiny English stemmer, so 'sharing' matches 'share' and 'calendars' matches 'calendar'."""
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "ly", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]; break
    return w.rstrip("e")

# ---------- store ----------
def con():
    DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(title, text, topic, source UNINDEXED, url UNINDEXED, tokenize='porter unicode61')")
    c.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, topic TEXT, title TEXT, source TEXT, chars INTEGER, at REAL)")
    return c

def chunks(text, size=900):
    """Split into passages of whole paragraphs, about `size` characters each."""
    out, cur = [], ""
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para: continue
        while len(para) > size * 1.5:   # one huge paragraph: cut at a sentence
            cut = para.rfind(". ", 0, size) + 1 or size
            out.append((cur + " " + para[:cut]).strip()); cur, para = "", para[cut:].strip()
        if len(cur) + len(para) > size and cur: out.append(cur.strip()); cur = ""
        cur += ("\n" if cur else "") + para
    if cur.strip(): out.append(cur.strip())
    return [c for c in out if len(c) > 80]

def store(topic, title, text, source, url):
    """Keep a page. Returns the number of passages saved (0 if already known or too short)."""
    if len(text) < 300: return 0
    with _lock:
        c = con()
        try:
            if c.execute("SELECT 1 FROM pages WHERE url=?", (url,)).fetchone(): return 0
            parts = chunks(text)
            c.executemany("INSERT INTO passages (title, text, topic, source, url) VALUES (?,?,?,?,?)", [(title, p, topic, source, url) for p in parts])
            c.execute("INSERT INTO pages VALUES (?,?,?,?,?,?)", (url, topic, title, source, len(text), time.time()))
            c.commit(); return len(parts)
        finally: c.close()

def words(q):
    return [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in STOP and len(w) > 1]

def search(q, k=4):
    """Best passages for a question. Only returns passages that match most of the question's important words."""
    if not DB.exists(): return []
    ws = words(q)
    if not ws: return []
    with _lock:
        c = con()
        try:
            rows = c.execute("SELECT title, text, source, url, bm25(passages, 4.0, 1.0, 2.0) FROM passages WHERE passages MATCH ? ORDER BY 5 LIMIT 30",
                             (" OR ".join(f'"{w}"' for w in ws),)).fetchall()
        except sqlite3.Error: return []
        finally: c.close()
    need = {stem(w) for w in ws}
    out, seen = [], set()
    for title, text, source, url, _ in rows:
        have = {stem(w) for w in re.findall(r"[a-z0-9]+", (title + " " + text).lower())}
        cover = len(need & have) / len(need)
        if cover >= (0.5 if len(need) > 3 else 0.6 if len(need) > 2 else 1.0) and url not in seen:
            seen.add(url); out.append({"title": title, "text": text, "source": source, "url": url, "cover": cover})
        if len(out) >= k: break
    return out

def context(q):
    """Facts block for the brain: passages from things Piper studied."""
    hits = search(q, 2)
    if not hits: return ""
    return ("FROM PIPER'S STUDY NOTES (pages Piper read and saved earlier; answer from these, step by step if it's a how-to, "
            "and name the source in a few words):\n" + "\n".join(f"- [{h['source']}: {h['title']}] {h['text'][:600]}" for h in hits))

def counts():
    if not DB.exists(): return {"pages": 0, "passages": 0}
    with _lock:
        c = con()
        try: return {"pages": c.execute("SELECT count(*) FROM pages").fetchone()[0], "passages": c.execute("SELECT count(*) FROM passages").fetchone()[0]}
        finally: c.close()

# ---------- fetching ----------
def fetch(url, timeout=8, limit=1_500_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"): return ""
        return r.read(limit).decode(r.headers.get_content_charset() or "utf-8", "ignore")

def page_text(h):
    """Readable text of a web page: headings, paragraphs and list items, in order, without menus and footers."""
    h = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|aside|form|button|iframe|template)[^>]*>.*?</\1>", " ", h)
    m = re.search(r"(?is)<(main|article)[^>]*>(.*)</\1>", h)
    if m and len(m.group(2)) > 1500: h = m.group(2)
    out = []
    for tag, inner in re.findall(r"(?is)<(h[1-4]|p|li|dd|td)[^>]*>(.*?)</\1>", h):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if len(t) < 3 or re.search(r"(?i)cookie|sign in|subscribe|privacy policy|all rights reserved", t) and len(t) < 120: continue
        out.append(("## " + t) if tag.lower().startswith("h") else ("• " + t if tag.lower() == "li" else t))
    text = "\n".join(dict.fromkeys(out))
    return re.sub(r"\[\s*\d+\s*\]|\[edit\]", "", text)

def title_of(h, url):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
    t = html.unescape(m.group(1)).strip() if m else url
    return re.split(r"\s+[|\-–—]\s+", t)[0][:120]

def web_results(q, n=5):
    import websearch
    try: return websearch._run(q, n)
    except Exception as e: print("study search:", e); return []

WIKI_UA = "PiperAssistant/1.0 (personal offline study assistant; single user; contact via local install) python-urllib"
_wiki = {"last": 0.0, "cool": 0.0}

def wiki_api(params):
    """Wikipedia, politely: identifies itself, one request every 1.5 s, and backs off when asked to slow down."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2, "maxlag": 5})
    for attempt in range(4):
        wait = max(_wiki["last"] + 1.5, _wiki["cool"]) - time.time()
        if wait > 0: time.sleep(min(wait, 120))
        _wiki["last"] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA, "Api-User-Agent": WIKI_UA, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 3: raise
            try: ra = float(e.headers.get("Retry-After") or 0)
            except ValueError: ra = 0
            _wiki["cool"] = time.time() + max(ra, 15 * (2 ** attempt))   # 15 s, 30 s, 60 s
            print(f"study: Wikipedia asked me to slow down, waiting {int(_wiki['cool'] - time.time())} s")

def wiki_article(title):
    d = wiki_api({"action": "query", "prop": "extracts|links", "explaintext": 1, "redirects": 1, "titles": title, "plnamespace": 0, "pllimit": "max"})
    p = (d.get("query", {}).get("pages") or [{}])[0]
    if p.get("missing"): return None
    return {"title": p.get("title", title), "text": p.get("extract", ""), "links": [l["title"] for l in p.get("links", [])]}

def wiki_find(topic):
    d = wiki_api({"action": "opensearch", "search": topic, "limit": 1, "namespace": 0})
    return d[1][0] if len(d) > 1 and d[1] else None

def related(main, links, n, topic=""):
    """Linked articles worth reading too. Tech how-to topics: none (Wikipedia doesn't teach how to use an app; official
    help pages do). Places and general topics: only links the article's opening sections talk about repeatedly."""
    if any(re.search(p, topic, re.I) for p, _ in OFFICIAL): return []
    lead = main[:6000].lower()
    tw = {stem(w) for w in words(topic)}
    def score(t):
        hits = len(re.findall(r"\b" + re.escape(t.lower()) + r"\b", lead))
        return hits + (2 if tw & {stem(w) for w in words(t)} else 0)
    good = [l for l in links if not re.search(r"(?i)^(list of|index of|outline of|category:)|\(disambiguation\)|^\d{3,4}$|university|encryption|\bInc\.?$|Technologies$", l)]
    return [l for l in sorted(good, key=score, reverse=True) if score(l) >= 2][:n]

def queries(topic):
    t = topic
    q = next((v["question"] for v in state()["topics"].values() if v.get("question") and v["topic"] == topic), None)
    if q: return [q, topic, f"{topic} explained"]
    if (state()["topics"].get(topic.lower()) or {}).get("second_pass"):   # second go: different searches
        return [f"{t} how to", f"{t} help guide", f"{t} features explained", f"{t} for beginners", f"{t} tips",
                f"{t} problems solved", f"what can {t} do", f"{t} hidden features"]
    qs = [f"{t} beginner guide", f"how to use {t}", f"{t} tips and tricks", f"{t} settings explained", f"{t} common problems and fixes"]
    for pat, site in OFFICIAL:
        if re.search(pat, t, re.I): qs = [f"site:{site} {t}", f"site:{site} {t} how to", f"site:{site} {t} settings"] + qs
    parts = [x.strip() for x in re.split(r"\s+(?:and|&)\s+|,", t) if x.strip()]
    if len(parts) > 1: qs += [q for p in parts for q in (f"how to use {p}", f"{p} tips and tricks")]
    if not any(re.search(p, t, re.I) for p, _ in OFFICIAL):
        qs = [f"{t} guide", f"{t} facts", f"{t} history", f"things to know about {t}"]
    return qs

# ---------- jobs ----------
def state():
    try: return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: return {"topics": {}, "order": []}

def save_state(s):
    """Save safely. On Windows, OneDrive or antivirus can hold the file for a moment ('Access is denied'), so retry."""
    DIR.mkdir(exist_ok=True)
    data = json.dumps(s, indent=1)
    tmp = STATE.with_suffix(".tmp")
    for i in range(10):
        try:
            tmp.write_text(data, encoding="utf-8"); tmp.replace(STATE); return
        except PermissionError: time.sleep(0.2 * (i + 1))
    try: STATE.write_text(data, encoding="utf-8")   # last resort: write in place
    except Exception as e: print("study: couldn't save the study list:", e)

def clean_topic(t):
    t = re.sub(r"(?i)\b(everything|all|more|stuff|things|everything there is to know)\b|\b(?:including|incl|with|and)\s+(?:the\s+)?(?:maps?|everything|all)\b.*$", " ", t)
    t = re.sub(r"(?i)^(?:about|on|up on)\s+|\s+(?:please|for me|now)\s*$|[?.!]+$", "", t.strip())
    t = re.sub(r"(?i)^(?:the|a|an)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip(" ,")

def add(topic, front=False):
    """Queue a topic. Returns (topic, status) where status is 'queued', 'already' or 'studying'."""
    topic = clean_topic(topic)
    if not topic: return None, "empty"
    with _lock:
        s = state(); key = topic.lower()
        cur = s["topics"].get(key)
        if cur and cur["status"] == "studying": return cur["topic"], "studying"
        if cur and cur["status"] == "queued":   # already on the list: move it up if asked
            if front and s["order"] and s["order"][0] != key:
                s["order"] = [key] + [k for k in s["order"] if k != key]; save_state(s); wake.set()
                return cur["topic"], "moved"
            return cur["topic"], "queued-already"
        if cur and cur["status"] == "done" and time.time() - cur.get("finished", 0) < 7 * 86400: return cur["topic"], "already"
        s["topics"][key] = {"topic": topic, "status": "queued", "done": 0, "total": 0, "pages": 0, "added": time.time(), "announced": False}
        s["order"] = [k for k in s["order"] if k != key]
        s["order"].insert(0 if front else len(s["order"]), key)
        save_state(s)
    wake.set()
    return topic, "queued"

def subject_of(q):
    """The searchable core of a question: 'when was the Laxey Wheel built?' -> 'Laxey Wheel built'."""
    t = re.sub(r"(?i)^(?:hey piper[, ]*)?(?:do you know |can you tell me |tell me |what is |what's |what are |who is |who was |when (?:is|was|did) |"
               r"where (?:is|was) |why (?:is|does|do|did) |how (?:do|does|did|can|many|much) (?:i |you )?)", "", q.strip())
    t = re.sub(r"(?i)^(?:the|a|an)\s+", "", re.sub(r"[?!.]+$", "", t).strip())
    return t[:80] or q[:80]

def add_question(q):
    """Piper didn't know: study this exact question soon (short and focused), then answer it."""
    key = "q:" + re.sub(r"[^a-z0-9 ]", "", q.lower())[:80]
    with _lock:
        s = state()
        if key in s["topics"] and s["topics"][key]["status"] in ("queued", "studying"): return False
        s["topics"][key] = {"topic": subject_of(q), "question": q.strip(), "status": "queued", "done": 0, "total": 0, "pages": 0,
                            "added": time.time(), "announced": True, "answered": False}
        s["order"] = [key] + [k for k in s["order"] if k != key]
        save_state(s)
    wake.set(); return True

on_question_done = None   # set by piper_core: writes the answer once the reading is done

def learned_answers():
    """Answers to questions Piper went away to learn, not yet told. Marks them told."""
    with _lock:
        s = state(); out = []
        for v in s["topics"].values():
            if v.get("question") and v.get("answer") and not v.get("answered"):
                out.append((v["question"], v["answer"])); v["answered"] = True
        if out: save_state(s)
    return out

def seed_defaults():
    """First run: start learning the everyday things Morne asked for."""
    with _lock:
        s = state()
        if s.get("seeded"): return
        s["seeded"] = True; save_state(s)
    for t in cfg().get("study_topics", DEFAULT_TOPICS): add(t)

def _update(key, **kw):
    with _lock:
        s = state()
        if key in s["topics"]: s["topics"][key].update(kw); save_state(s)

def plan(topic):
    """List of things to read: ('web', url) / ('wiki', title) / ('zim', title)."""
    is_q = any(v.get("question") and v["topic"] == topic for v in state()["topics"].values())
    n = 12 if is_q else int(cfg().get("study_pages", 40))
    items, seen, per_site = [], set(), {}
    online = True
    for q in queries(topic):
        res = web_results(q, 6)
        if res is None: res = []
        for r in res:
            u = r.get("url", "")
            site = re.sub(r"^https?://(?:www\.)?([^/]+).*", r"\1", u)
            if not u.startswith("http") or SKIP.search(u) or u in seen or per_site.get(site, 0) >= 8: continue
            seen.add(u); per_site[site] = per_site.get(site, 0) + 1; items.append(("web", u))
        time.sleep(0.5)
    try:
        main = wiki_find(topic)
        if main:
            items.insert(0, ("wiki", main))
            art = wiki_article(main)
            if art and not is_q: items += [("wiki", t) for t in related(art["text"], art["links"], max(10, n // 2), topic)]
    except Exception as e:
        print("study wikipedia:", e); online = bool(items)
    if not online or not items:   # no internet: offline libraries instead
        items = [("zim", topic)] + [("zim", t) for t in _zim_related(topic)]
    out = list(dict.fromkeys(items))
    webs = [i for i in out if i[0] == "web"][: n // 2 + 5]
    rest = [i for i in out if i[0] != "web"]
    return (rest[:1] + webs + rest[1:])[:n]

def _zim_related(topic):
    try:
        import wiki
        z = wiki.search_zims(topic, budget=3)
        if not z: return []
        caps = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", z["text"])
        common = {}
        for c in caps:
            if c.lower() not in STOP and c.lower() != topic.lower(): common[c] = common.get(c, 0) + 1
        return [c for c, _ in sorted(common.items(), key=lambda x: -x[1])[:25]]
    except Exception: return []

def known(url):
    if not DB.exists(): return False
    with _lock:
        c = con()
        try: return bool(c.execute("SELECT 1 FROM pages WHERE url=?", (url,)).fetchone())
        finally: c.close()

def question_waiting():
    s = state()
    return any(v.get("question") and v["status"] == "queued" for v in s["topics"].values())

def read_one(topic, kind, ref):
    """Read one item and keep it. Returns passages saved."""
    if kind == "web" and known(ref): return 0   # already read (e.g. before a pause): don't download it again
    if kind == "web":
        h = fetch(ref)
        txt = page_text(h)
        return store(topic, title_of(h, ref), txt, re.sub(r"^https?://(?:www\.)?([^/]+).*", r"\1", ref), ref) if len(txt) > 300 else 0
    if kind == "wiki":
        a = wiki_article(ref)
        if not a or len(a["text"]) < 300: return 0
        txt = re.sub(r"\n==+\s*(See also|References|External links|Notes|Further reading|Bibliography|Sources)\s*==+.*", "", a["text"], flags=re.S)
        txt = re.sub(r"==+\s*(.+?)\s*==+", r"## \1", txt)
        return store(topic, a["title"], txt, "Wikipedia", "https://en.wikipedia.org/wiki/" + urllib.parse.quote(a["title"].replace(" ", "_")))
    if kind == "zim":
        import wiki
        z = wiki.search_zims(ref, budget=3, fulltext=True)
        return store(topic, z["title"], z["text"], z["source"], f"zim:{z['file']}:{z['title']}") if z else 0
    return 0

def study(key):
    s = state(); t = s["topics"][key]; topic = t["topic"]
    _update(key, status="studying", started=time.time(), current="planning what to read")
    try: items = plan(topic)
    except Exception as e: items = []; print("study plan:", e)
    if not items: _update(key, status="failed", error="couldn't find anything to read (no internet and no offline library had it)"); return
    _update(key, total=len(items))
    pages = t.get("pages", 0) if (t.get("second_pass") or t.get("paused_for_question")) else 0   # carry on counting
    for i, (kind, ref) in enumerate(items, 1):
        while paused(): time.sleep(2)
        if not t.get("question") and question_waiting():   # Morne asked something I didn't know: that comes first
            _update(key, status="queued", paused_for_question=True, current="", pages=pages); return
        _update(key, current=ref if kind != "web" else re.sub(r"^https?://(?:www\.)?", "", ref)[:60])
        try:
            if read_one(topic, kind, ref): pages += 1
        except Exception as e: print("study read:", ref, str(e)[:80])
        _update(key, done=i, pages=pages)
        time.sleep(float(cfg().get("study_delay", 1.0)))
    _update(key, status="done" if pages else "failed", finished=time.time(), current="", announced=bool(t.get("question")),
            error="" if pages else "the pages I found couldn't be read")
    if t.get("question"):
        while paused(): time.sleep(2)   # don't write the answer while Morne is talking to me
        ans = None
        try: ans = on_question_done(t["question"]) if (pages and on_question_done) else None
        except Exception as e: print("study answer:", e)
        _update(key, answer=ans or ("I looked into it but couldn't find a clear answer in what I read." if pages
                                     else "I tried to look it up but couldn't reach anything to read."))

_busy = {"t": 0}
def busy():   # Piper is answering: study gently waits
    _busy["t"] = time.time()
def paused(): return time.time() - _busy["t"] < 8

wake = threading.Event()
def worker():
    with _lock:   # a study cut short by closing Piper carries on
        s = state()
        for v in s["topics"].values():
            if v["status"] == "studying": v["status"] = "queued"
            elif v["status"] == "done" and v.get("pages", 0) < 8 and not v.get("second_pass") and not v.get("question"):   # thin result: one more go
                v.update(status="queued", second_pass=True, announced=True)
            elif v["status"] == "failed" and v.get("tries", 0) < 3 and not v.get("question"):   # e.g. no internet last time: try again (3 goes)
                v.update(status="queued", tries=v.get("tries", 0) + 1, error="")
        save_state(s)
    while True:
        s = state()
        nxt = next((k for k in s["order"] if s["topics"].get(k, {}).get("status") == "queued"), None)
        if not nxt:
            wake.clear(); wake.wait(600); continue
        try: study(nxt)
        except Exception as e: print("study:", e); _update(nxt, status="failed", error=str(e)[:100])

def start():
    if cfg().get("study", True):
        seed_defaults()
        threading.Thread(target=worker, daemon=True, name="study").start()

# ---------- telling Morne ----------
def progress_text():
    s = state(); topics = [s["topics"][k] for k in s["order"] if k in s["topics"]]
    if not topics: return "I haven't studied anything yet. Say 'study' and a topic, like 'study Google Calendar', and I'll start reading."
    now = [t for t in topics if t["status"] == "studying"]
    done = [t for t in topics if t["status"] == "done"]
    wait = [t for t in topics if t["status"] == "queued"]
    bits = []
    if now:
        t = now[0]
        if t.get("question"): bits.append(f"Right now I'm looking into your question: \"{t['question'].rstrip('?')}?\"")
        else: bits.append(f"I'm studying {t['topic']} right now, {t['done']} of {t['total']} pages read and {t['pages']} kept." if t.get("total")
                    else f"I've just started studying {t['topic']} and I'm working out what to read.")
    done = [t for t in done if not t.get("question")]
    if done: bits.append("Finished: " + ", ".join(f"{t['topic']} ({_pages(t['pages'])})" for t in done[-8:]) + ".")
    if wait: bits.append(f"Still to do: {', '.join(('your question about ' + t['topic']) if t.get('question') else t['topic'] for t in wait[:6])}{' and more' if len(wait) > 6 else ''}.")
    failed = [t for t in topics if t["status"] == "failed"]
    if failed: bits.append(f"I couldn't study {failed[-1]['topic']}: {failed[-1].get('error', 'no pages')}.")
    c = counts(); bits.append(f"In total I've kept {c['pages']} pages.")
    return " ".join(bits)

def _pages(n): return f"{n} page{'s' if n != 1 else ''}"

def news():
    """Studies finished since Morne was last told, in one short sentence. Marks them told."""
    with _lock:
        s = state(); done = []
        for v in s["topics"].values():
            if v["status"] == "done" and not v.get("announced"):
                done.append(v); v["announced"] = True
        if done: save_state(s)
    if not done: return ""
    if len(done) == 1: return f"I finished studying {done[0]['topic']}, {_pages(done[0]['pages'])} saved."
    total = sum(v["pages"] for v in done)
    top = sorted(done, key=lambda v: -v["pages"])[:2]
    return (f"I finished studying {len(done)} topics, {_pages(total)} saved in all. "
            f"{top[0]['topic']} and {top[1]['topic']} got the most; ask me how it's going for the full list.")

def studying_now():
    s = state()
    return next((v for v in s["topics"].values() if v["status"] == "studying"), None)

def forget(topic):
    key = clean_topic(topic).lower()
    with _lock:
        s = state()
        if key not in s["topics"]: return False
        s["topics"].pop(key); s["order"] = [k for k in s["order"] if k != key]; save_state(s)
        c = con()
        try:
            c.execute("DELETE FROM passages WHERE lower(topic)=?", (key,))
            c.execute("DELETE FROM pages WHERE lower(topic)=?", (key,)); c.commit()
        finally: c.close()
    return True
