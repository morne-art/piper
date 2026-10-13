"""Piper's Wikipedia brain.

Offline: import downloaded Wikipedia data sets into wiki/wiki.sqlite (full-text search, works with no internet).
  Supported: MediaWiki XML dumps (.xml, .xml.bz2, .xml.gz), JSON / JSON Lines with title + text
  (e.g. Hugging Face / Kaggle exports, .gz ok), CSV with title + text columns,
  and optionally Kiwix .zim (pip install libzim) and .parquet (pip install pyarrow).
Online: looks things up on Wikipedia directly. No API key, no account, nothing to set up.
  Anything looked up online can be saved into the offline wiki, so Piper keeps learning.
"""
import bz2, csv, gzip, html, io, json, pathlib, re, sqlite3, threading, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
DB = ROOT / "wiki" / "wiki.sqlite"
UA = "Piper-personal-assistant/1.0 (local desktop assistant)"
WIKI_EXT = (".xml", ".bz2", ".gz", ".jsonl", ".ndjson", ".zim", ".parquet")
IMPORT_EXT = tuple(e for e in WIKI_EXT if e != ".zim")  # ZIM files are read in place, never imported
progress = {"running": False, "file": "", "done": 0, "error": "", "finished": ""}
_lock = threading.Lock()

def cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception: return {}

def con():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS articles USING fts5(title, body, source UNINDEXED, tokenize='porter unicode61')")
    return c

# ---------- cleaning ----------
def clean_wikitext(t):
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", t, flags=re.S | re.I)
    for _ in range(6):  # nested {{templates}} and {| tables |}
        n = re.sub(r"\{\{[^{}]*\}\}", "", t); n = re.sub(r"\{\|[^{}]*?\|\}", "", n, flags=re.S)
        if n == t: break
        t = n
    t = re.sub(r"\[\[(?:File|Image|Category|Fichier|Datei|Kategorie):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", "", t, flags=re.I)
    t = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", t); t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t); t = re.sub(r"\[https?://\S+\]", "", t)
    t = re.sub(r"'{2,}", "", t); t = re.sub(r"<[^>]+>", "", t); t = html.unescape(t)
    t = re.sub(r"(?m)^[*#:;]+\s*", "", t); t = re.sub(r"(?m)^=+\s*(.*?)\s*=+\s*$", r"\n\1.\n", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()

def opener(p):
    s = str(p).lower()
    if s.endswith(".bz2"): return bz2.open(p, "rb")
    if s.endswith(".gz"): return gzip.open(p, "rb")
    return open(p, "rb")

# ---------- importers (each yields (title, text)) ----------
def from_xml(p):
    import xml.etree.ElementTree as ET
    title = text = None; ns = False
    for ev, el in ET.iterparse(opener(p), events=("end",)):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "title": title = el.text
        elif tag == "ns": ns = (el.text or "0") == "0"
        elif tag == "text": text = el.text or ""
        elif tag == "page":
            if ns and title and text and not text.lstrip().lower().startswith("#redirect"): yield title, clean_wikitext(text)
            title = text = None; el.clear()

def _pick(d):
    t = d.get("title") or d.get("Title") or d.get("name"); x = d.get("text") or d.get("body") or d.get("content") or d.get("abstract") or d.get("summary")
    return (t, x) if t and x else None

def from_json(p):
    with opener(p) as f:
        head = f.read(1); f.seek(0) if hasattr(f, "seek") else None
        if head == b"[":
            for d in json.load(io.TextIOWrapper(f, encoding="utf-8")):
                r = _pick(d)
                if r: yield r
        else:
            for line in io.TextIOWrapper(f, encoding="utf-8", errors="ignore"):
                line = line.strip()
                if not line: continue
                try: r = _pick(json.loads(line))
                except Exception: continue
                if r: yield r

def from_csv(p):
    csv.field_size_limit(50_000_000)
    with opener(p) as f:
        for d in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="ignore")):
            r = _pick(d)
            if r: yield r

def from_parquet(p):
    import pyarrow.parquet as pq
    for batch in pq.ParquetFile(p).iter_batches(batch_size=2000):
        for d in batch.to_pylist():
            r = _pick(d)
            if r: yield r

def from_zim(p):
    from libzim.reader import Archive
    a = Archive(str(p))
    for i in range(a.all_entry_count):
        e = a._get_entry_by_id(i)
        if e.is_redirect or not e.path.startswith(("A/", "")): continue
        try:
            item = e.get_item()
            if "html" not in item.mimetype: continue
            body = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", bytes(item.content).decode("utf-8", "ignore")))
            yield e.title, html.unescape(re.sub(r"\s+", " ", body)).strip()
        except Exception: continue

def reader_for(p):
    s = p.name.lower()
    if ".xml" in s: return from_xml
    if s.endswith(".parquet"): return from_parquet
    if ".csv" in s: return from_csv
    if ".json" in s or s.endswith((".jsonl.gz", ".ndjson")): return from_json
    if s.endswith((".bz2", ".gz")):  # sniff compressed content
        with opener(p) as f: head = f.read(200).lstrip()
        return from_xml if head.startswith(b"<") else from_json
    return None

def is_wiki_file(p):
    s = pathlib.Path(p).name.lower()
    return s.endswith(WIKI_EXT) or ("wiki" in s and s.endswith((".json", ".csv")))

def import_file(path, limit=None):
    p = pathlib.Path(path); fn = reader_for(p)
    if not fn: raise ValueError(f"I don't know how to read {p.name}")
    c = con(); batch = []; n = 0; src = f"offline:{p.name}"
    c.execute("CREATE TABLE IF NOT EXISTS imported(name TEXT PRIMARY KEY, size INTEGER, articles INTEGER)")
    if c.execute("SELECT 1 FROM imported WHERE name=? AND size=?", (p.name, p.stat().st_size)).fetchone():
        c.close(); progress["done"] = 0; return 0  # already imported this exact file
    for title, text in fn(p):
        text = text[:20000]
        if len(text) < 80: continue
        batch.append((title.strip(), text, src)); n += 1
        if len(batch) == 1000:
            c.executemany("INSERT INTO articles(title, body, source) VALUES (?,?,?)", batch); c.commit(); batch = []
            progress["done"] = n
        if limit and n >= limit: break
    if batch: c.executemany("INSERT INTO articles(title, body, source) VALUES (?,?,?)", batch); c.commit()
    c.execute("INSERT OR REPLACE INTO imported VALUES (?,?,?)", (p.name, p.stat().st_size, n)); c.commit()
    progress["done"] = n; c.close(); return n

def import_async(paths):
    """Import one or more files in the background (big dumps can take a while). Watch progress via status()."""
    paths = [pathlib.Path(x) for x in ([paths] if isinstance(paths, (str, pathlib.Path)) else paths)]
    if progress["running"]: return {"ok": False, "error": "An import is already running."}
    def run():
        with _lock:
            progress.update(running=True, error="", done=0, finished="")
            total = 0
            try:
                for p in paths:
                    progress["file"] = p.name; total += import_file(p)
                progress["finished"] = f"Imported {total:,} articles"
            except Exception as e: progress["error"] = f"{progress['file']}: {e}"
            progress["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "started": [p.name for p in paths]}


# ---------- ZIM libraries (Kiwix): read in place, no import, no copy ----------
_zims = {}; _zlock = threading.Lock()
NAMES = [(r"^wikipedia_en-simple", "Simple English Wikipedia", 1), (r"^wikipedia_en_medicine", "Wikipedia's medicine library", 2),
         (r"^wikipedia", "Wikipedia", 1), (r"^nhs\.uk", "the NHS website", 2), (r"medicine", "the medical library", 3),
         (r"^wiktionary", "Wiktionary", 4), (r"^(\w+)\.stackexchange", None, 5), (r"^maps_", None, 99)]

def zim_label(p):
    n = pathlib.Path(p).name.lower()
    for pat, label, pri in NAMES:
        m = re.search(pat, n)
        if m:
            if pat.startswith("^(\\w+)"): return f"{ {'cs': 'Computer Science', 'english': 'English Language'}.get(m.group(1), m.group(1).title())} Stack Exchange", pri
            return label, pri
    return pathlib.Path(p).stem.split("_")[0].replace(".", " ").title(), 6

def zim_paths():
    found = {str(p.resolve()) for p in (ROOT / "wiki").rglob("*.zim")}
    for x in cfg().get("wiki_zim_paths", []):
        q = pathlib.Path(x)
        if q.is_dir(): found |= {str(p.resolve()) for p in q.rglob("*.zim")}
        elif q.suffix.lower() == ".zim" and q.exists(): found.add(str(q.resolve()))
    return sorted(p for p in found if zim_label(p)[1] < 99)  # map tile packs have no text to read

def archive(p):
    with _zlock:
        if p not in _zims:
            from libzim.reader import Archive
            _zims[p] = Archive(p)
        return _zims[p]

def html_text(h, wiktionary=False):
    h = re.sub(r"(?is)<(script|style|table|figure|sup)[^>]*>.*?</\1>", " ", h)
    parts = re.findall(r"(?is)<(?:li|dd)[^>]*>(.*?)</(?:li|dd)>", h)[:4] if wiktionary else []
    parts = parts or re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)) for x in parts) if parts else html.unescape(re.sub(r"<[^>]+>", " ", h))
    txt = re.sub(r"\[\s*\d+\s*\]|\[edit\]", "", txt)
    return re.sub(r"\s+", " ", txt).strip()

def _title_score(subj, title):
    a, b = subj.lower().strip(), (title or "").lower().strip()
    if a == b: return 3.0
    if b.startswith(a) or a.startswith(b): return 2.0
    aw, bw = set(re.findall(r"\w+", a)), set(re.findall(r"\w+", b))
    return 1.5 * len(aw & bw) / max(1, len(aw | bw))

def _search_one(p, subject, prefer, fulltext):
    from libzim.search import Query, Searcher
    from libzim.suggestion import SuggestionSearcher
    a = archive(p); label, pri = zim_label(p)
    if prefer and prefer in p.lower(): pri = 0
    best = None; cands = []
    for path in (subject.replace(" ", "_"), subject.capitalize().replace(" ", "_"), subject.title().replace(" ", "_")):
        if a.has_entry_by_path(path): cands.append(path)
    if not cands: cands = list(SuggestionSearcher(a).suggest(subject).getResults(0, 5))
    for path in dict.fromkeys(cands):
        e = a.get_entry_by_path(path); sc = _title_score(subject, e.title)
        if sc >= 0.6 and (not best or (sc, -pri) > best[0]): best = ((sc, -pri), p, path, e.title, label)
    if not best and fulltext and a.has_fulltext_index:
        for path in Searcher(a).search(Query().set_query(subject)).getResults(0, 1):
            best = ((0.7, -pri), p, path, a.get_entry_by_path(path).title, label)
    return best

_pool = None
def search_zims(subject, prefer=None, budget=1.5, fulltext=False):
    """Best article across all libraries. Every library is searched at the same time; slow ones are skipped after `budget` seconds."""
    global _pool
    import concurrent.futures as cf
    paths = zim_paths()
    if prefer != "wiktionary": paths = [p for p in paths if "wiktionary" not in p.lower()] or paths  # dictionary only for word questions
    if not paths: return None
    if _pool is None: _pool = cf.ThreadPoolExecutor(max_workers=8)
    futs = [_pool.submit(_search_one, p, subject, prefer, fulltext) for p in paths]
    done, _ = cf.wait(futs, timeout=budget)
    results = []
    for f in done:
        try:
            r = f.result()
            if r: results.append(r)
        except Exception as ex: print("zim skip:", ex)
    if not results: return None
    _, p, path, title, label = max(results, key=lambda r: r[0])
    item = archive(p).get_entry_by_path(path).get_item()
    text = html_text(bytes(item.content).decode("utf-8", "ignore"), wiktionary="wiktionary" in p.lower())
    return {"title": title, "text": text, "source": label, "file": pathlib.Path(p).name} if len(text) > 30 else None

def warm_libraries():
    """Open every library once at start-up, so the first question doesn't pay for it."""
    for p in zim_paths():
        try: archive(p).article_count
        except Exception as e: print("library:", pathlib.Path(p).name, e)

def libraries():
    out = []
    for p in zim_paths():
        try: out.append({"name": zim_label(p)[0], "file": pathlib.Path(p).name, "articles": archive(p).article_count})
        except Exception as e: out.append({"name": zim_label(p)[0], "file": pathlib.Path(p).name, "error": str(e)[:80]})
    return out

# ---------- search ----------
def count():
    if not DB.exists(): return 0
    try:
        c = con(); n = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]; c.close(); return n
    except Exception: return 0

def lead(text, n=3):
    para = next((x for x in text.split("\n") if len(x.strip()) > 60), text)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", re.sub(r"\s*\([^()]*\)", "", para).strip())
    return " ".join(sents[:n]).strip()

def search_local(subject, k=3):
    if not DB.exists() or not subject.strip(): return []
    c = con(); words = re.findall(r"\w+", subject)
    if not words: return []
    try:
        exact = c.execute("SELECT title, body, source FROM articles WHERE title = ? COLLATE NOCASE LIMIT 1", (subject.strip(),)).fetchall()
        if not exact:  # fast: title match via FTS, then body match
            q = " ".join(f'"{w}"' for w in words)
            exact = c.execute("SELECT title, body, source FROM articles WHERE articles MATCH ? ORDER BY bm25(articles, 10.0, 1.0) LIMIT ?", (f"title:({q})", k)).fetchall()
        rows = exact or c.execute("SELECT title, body, source FROM articles WHERE articles MATCH ? ORDER BY bm25(articles, 10.0, 1.0) LIMIT ?",
                                  (" ".join(f'"{w}"' for w in words), k)).fetchall()
        return rows
    finally: c.close()

# ---------- online (no key, no account) ----------
def _get(url, timeout=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8"))

def online_ok():
    try: _get(f"https://{cfg().get('wiki_lang', 'en')}.wikipedia.org/api/rest_v1/page/summary/Earth", 3); return True
    except Exception: return False

def search_online(subject):
    lang = cfg().get("wiki_lang", "en")
    r = _get(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page?" + urllib.parse.urlencode({"q": subject, "limit": 1}))
    if not r.get("pages"): return None
    key = r["pages"][0]["key"]
    s = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(key, safe=""))
    if s.get("type") == "disambiguation": return {"title": s.get("title"), "text": "", "disambiguation": True}
    return {"title": s.get("title", key), "text": s.get("extract", ""), "url": s.get("content_urls", {}).get("desktop", {}).get("page", "")}

def save(title, text, src="online"):
    c = con()
    if not c.execute("SELECT 1 FROM articles WHERE title = ? COLLATE NOCASE", (title,)).fetchone():
        c.execute("INSERT INTO articles(title, body, source) VALUES (?,?,?)", (title, text, src)); c.commit()
    c.close()

# ---------- question handling ----------
GENERAL = re.compile(r"^(?:(?:hey |ok )?piper,? )?(?:please )?(?:who|what|where|when)(?: is| was| are| were|'s)\s+(?:a |an |the )?(.+?)\??$"
                     r"|^(?:tell me about|explain|define|look up|search (?:for|wikipedia for|online for)|wiki(?:pedia)?|meaning of)\s+(?:a |an |the )?(.+?)\??$"
                     r"|^what does (?:the word )?(.+?) mean\??$", re.I)
PERSONAL = re.compile(r"\b(my|our|i|me|mine|we|us)\b", re.I)

def subject_of(q):
    m = GENERAL.match(q.strip())
    return next(g for g in m.groups() if g).strip(" ?.!'\"") if m else None

def answer(q, force_online=False):
    """Returns a spoken answer from the offline wiki, or Wikipedia online. None if nothing found."""
    subj = subject_of(q) or (q if force_online else None)
    if not subj or PERSONAL.search(subj): return None
    c = cfg(); online = force_online or c.get("wiki_online", True)
    if not force_online:
        word = re.search(r"\b(mean|meaning|define|definition)\b", q, re.I)
        try: z = search_zims(subj, prefer="wiktionary" if word else None)
        except ImportError: z = None
        if z: return f"{lead(z['text'])} That's from {z['source']}."
        hits = search_local(subj, 1)
        if hits:
            t, body, src = hits[0]
            if set(re.findall(r"\w+", subj.lower())) & set(re.findall(r"\w+", (t + " " + body[:400]).lower())):
                return f"{lead(body)} That's from your offline Wikipedia, under {t}."
    if online:
        try: r = search_online(subj)
        except Exception: return None if not force_online else "I couldn't reach Wikipedia just now. Check the internet connection."
        if r and r.get("disambiguation"): return f"{r['title']} could mean a few different things. Can you be more specific?"
        if r and r.get("text"):
            if c.get("wiki_save", True): save(r["title"], r["text"])
            return f"{lead(r['text'])} That's from Wikipedia."
    return None

def needs_lookup(q):
    """Only questions about the world need the libraries. Greetings, chat and personal questions don't."""
    subj = subject_of(q)
    if subj: return subj if not PERSONAL.search(subj) else None
    t = q.strip().lower()
    if len(t.split()) < 3 or PERSONAL.search(t) or not re.search(r"\?|\b(how|why|when|where|which|history|explain|meaning)\b", t): return None
    return re.sub(r"^(how|why|when|where|which) (does|do|did|is|are|was|were|can) ", "", t).strip(" ?.!")

def context(q, k=2):
    subj = needs_lookup(q)
    if not subj: return ""
    try:
        z = search_zims(subj, prefer="wiktionary" if re.search(r"\b(mean|meaning|define|definition)\b", q, re.I) else None)
        if z: return f"[{z['source']}: {z['title']}] {lead(z['text'], 6)}"
    except Exception: pass
    return "\n".join(f"[Wikipedia: {t}] {lead(b, 5)}" for t, b, _ in search_local(subj, k))

def status():
    try: libs = libraries()
    except ImportError: libs = [{"name": "ZIM reader not installed: run install.bat", "file": "", "error": "missing"}] if zim_paths() else []
    return {"libraries": libs, "articles": count(), "online": cfg().get("wiki_online", True), "save": cfg().get("wiki_save", True),
            "lang": cfg().get("wiki_lang", "en"), **progress}

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "import":
        for f in sys.argv[2:]: print(f, import_file(f), "articles")
    else: print(answer(" ".join(sys.argv[1:]) or "what is the Isle of Man"))
