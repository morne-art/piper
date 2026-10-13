"""Knowledge folder: point Piper at a folder, it reads every document and answers from it.
Reads .txt .md .csv .json .html .pdf .docx. Everything stays on your PC (knowledge_index.json)."""
import time, json, math, os, re, pathlib, time, sqlite3, zipfile, shutil
ROOT = pathlib.Path(__file__).parent; INDEX = ROOT / "knowledge_index.json"
EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".pdf", ".docx", ".log", ".sql", ".sqlite", ".sqlite3", ".db"}
DBEXT = {".sqlite", ".sqlite3", ".db"}
INSTR = re.compile(r"(readme|instruction|guide|how.?to|notes)", re.I)
MAX_ROWS = 20000  # per table, for search
STOP = set("the a an and or of to in on for is are was were be it this that with as at by from i you my your me we our what which who how when where why do does did can could should would will about have has had not no yes so if any all there their them they he she his her its into than then also just".split())

def tok(t): return [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in STOP and len(w) > 1]

def read_file(p):
    s = p.suffix.lower()
    try:
        if s == ".pdf":
            from pypdf import PdfReader; return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        if s == ".docx":
            import docx; return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
        t = p.read_text(encoding="utf-8", errors="ignore")
        if s == ".md": t = re.sub(r"(?m)^#+\s*(.+?)\s*$", r"\1.", t)
        if s in (".html", ".htm"): t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S); t = re.sub(r"<[^>]+>", " ", t)
        return t
    except Exception as e:
        print("skip", p.name, e); return ""

def is_sqlite(p):
    try:
        with open(p, "rb") as f: return f.read(16) == b"SQLite format 3\x00"
    except Exception: return False

def ro(p):
    """Open a database strictly read-only: Piper can never change your data."""
    return sqlite3.connect(f"file:{pathlib.Path(p).as_posix()}?mode=ro", uri=True)

def db_docs(p, rel):
    """Turn a SQLite database into searchable passages: one schema summary per table, then rows in groups."""
    docs = []; con = ro(p); cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{t}")')]
        n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        docs.append((f"{rel} :: {t}", f"Database table {t} has {n:,} rows. Columns: {', '.join(cols)}."))
        group = []
        for row in cur.execute(f'SELECT * FROM "{t}" LIMIT {MAX_ROWS}'):
            group.append("; ".join(f"{c}={v}" for c, v in zip(cols, row) if v not in (None, "")))
            if len(group) == 15: docs.append((f"{rel} :: {t}", f"Rows from {t}: " + " | ".join(group))); group = []
        if group: docs.append((f"{rel} :: {t}", f"Rows from {t}: " + " | ".join(group)))
    con.close(); return docs

def sql_to_sqlite(src, dest):
    """Try to restore a .sql export into a SQLite copy so it can be queried. Works for SQLite-style exports; MySQL/Postgres dumps are still searched as text."""
    try:
        txt = pathlib.Path(src).read_text(encoding="utf-8", errors="ignore")
        txt = re.sub(r"(?im)^\s*(SET|LOCK|UNLOCK|/\*!|USE )[^;]*;", "", txt)
        txt = re.sub(r"(?i)\s(ENGINE|DEFAULT CHARSET|COLLATE|AUTO_INCREMENT)=\S+", "", txt).replace("`", '"')
        if dest.exists(): dest.unlink()
        con = sqlite3.connect(dest); con.executescript(txt); con.commit(); con.close(); return True
    except Exception as e:
        if dest.exists(): dest.unlink()
        print("sql restore skipped:", src.name, str(e)[:80]); return False

def databases():
    return _cached("databases", _databases)

def _databases():
    f = folder(); return [p for p in f.rglob("*") if p.is_file() and p.suffix.lower() in DBEXT and is_sqlite(p)] if f.exists() else []

def unpack_zip(zpath, dest_root=None):
    dest_root = dest_root or folder() / "uploads"; name = pathlib.Path(zpath).stem
    dest = dest_root / re.sub(r"[^\w.-]+", "_", name); dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():  # safe extract: no paths outside the folder
            target = (dest / m.filename).resolve()
            if not str(target).startswith(str(dest.resolve())) or m.is_dir(): continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out: shutil.copyfileobj(src, out)
    for sql in list(dest.rglob("*.sql")):  # restore .sql exports if there's no SQLite copy alongside
        if not any(dest.rglob("*.sqlite")) and not any(dest.rglob("*.db")) and not any(dest.rglob("*.sqlite3")):
            sql_to_sqlite(sql, sql.with_suffix(".restored.sqlite"))
    return dest

def query(sql, limit=200):
    """Run a READ-ONLY query (SELECT / WITH / PRAGMA only) against the first database, or 'db_name: SELECT ...'."""
    dbs = databases()
    if not dbs: return {"ok": False, "error": "No database learned yet. Upload your zip in the Knowledge tab."}
    target = dbs[0]; m = re.match(r"^\s*([\w.-]+)\s*:\s*(.+)$", sql, re.S)
    if m and any(d.stem == m.group(1) or d.name == m.group(1) for d in dbs):
        target = next(d for d in dbs if d.stem == m.group(1) or d.name == m.group(1)); sql = m.group(2)
    if not re.match(r"^\s*(select|with|pragma)\b", sql, re.I) or ";" in sql.strip().rstrip(";"):
        return {"ok": False, "error": "Only single read-only SELECT queries are allowed."}
    con = ro(target)
    try:
        cur = con.execute(sql); cols = [d[0] for d in cur.description or []]; rows = cur.fetchmany(limit)
        return {"ok": True, "db": target.name, "columns": cols, "rows": [list(r) for r in rows], "truncated": len(rows) == limit}
    except Exception as e: return {"ok": False, "error": str(e)}
    finally: con.close()

def schema():
    return _cached("schema", _schema)

def _schema():
    out = []
    for d in databases():
        con = ro(d)
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]; n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            out.append({"db": d.name, "table": t, "rows": n, "columns": cols})
        con.close()
    return out

def instructions():
    return _cached("instructions", _instructions)

def _instructions():
    """Text of any README / instructions / guide files, given to the brain as standing context."""
    f = folder(); txt = []
    if f.exists():
        for p in f.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".md", ".txt", ".docx", ".pdf"} and INSTR.search(p.stem):
                txt.append(f"[{p.relative_to(f)}]\n{read_file(p)[:6000]}")
    return "\n\n".join(txt)[:15000]

def chunks(text, size=700):
    paras = [x.strip() for x in re.split(r"\n\s*\n", text) if x.strip()]; out, cur = [], ""
    for para in paras:
        if len(cur) + len(para) > size and cur: out.append(cur); cur = ""
        cur += (" " if cur else "") + re.sub(r"\s+", " ", para)
    if cur: out.append(cur)
    return out

PACK = ROOT / "pack"   # Piper's built-in knowledge pack (always read, wherever your own notes live)
EXAMPLE = "(example, replace with your own notes)"

def folder():
    c = json.loads((ROOT / "config.json").read_text(encoding="utf-8")); f = pathlib.Path(c.get("knowledge_folder") or "knowledge")
    return f if f.is_absolute() else ROOT / f

def learn(path=None):
    if path:
        c = json.loads((ROOT / "config.json").read_text(encoding="utf-8")); c["knowledge_folder"] = str(path)
        (ROOT / "config.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
    f = folder()
    missing = not f.exists()  # still index the built-in pack even if your notes folder is missing
    docs, files = [], 0
    for z in ([] if missing else list(f.rglob("*.zip"))):  # unpack any zip dropped straight into the folder
        if not (f / "uploads" / re.sub(r"[^\w.-]+", "_", z.stem)).exists(): unpack_zip(z)
    for p in ([] if missing else sorted(f.rglob("*"))):
        if not p.is_file(): continue
        rel = str(p.relative_to(f))
        try:
            import wiki
            if wiki.is_wiki_file(p): continue  # Wikipedia data sets go to the wiki brain, not here
        except Exception: pass
        if p.suffix.lower() in DBEXT or (p.suffix.lower() not in EXT and is_sqlite(p)):
            if is_sqlite(p):
                try:
                    for src, text in db_docs(p, rel): docs.append({"file": src, "text": text, "toks": tok(text)})
                    files += 1
                except Exception as e: print("db skip", rel, e)
            continue
        if p.suffix.lower() == ".sql" and any(d for d in databases()): continue  # use the SQLite copy instead of the raw export
        if p.suffix.lower() in EXT and p.stat().st_size < 30_000_000:
            text = read_file(p)
            if not text.strip() or EXAMPLE in text[:300]: continue  # skip untouched example files
            files += 1
            for i, c in enumerate(chunks(text)):
                docs.append({"file": rel, "text": c, "toks": tok(c)})
    if PACK.exists():
        for p in sorted(PACK.glob("*.md")):
            text = read_file(p); files += 1
            for c in chunks(text): docs.append({"file": "piper-pack/" + p.name, "text": c, "toks": tok(c)})
    df = {}
    for d in docs:
        for w in set(d["toks"]): df[w] = df.get(w, 0) + 1
    idx = {"folder": str(f), "built": time.strftime("%Y-%m-%d %H:%M"), "files": files, "chunks": len(docs), "df": df,
           "avgdl": sum(len(d["toks"]) for d in docs) / max(1, len(docs)), "docs": docs, "sig": signature(f)}
    INDEX.write_text(json.dumps(idx), encoding="utf-8")
    _cache.clear()
    return {"ok": True, "folder": str(f), "files": files, "chunks": len(docs), "built": idx["built"], "tables": len(schema())}

def signature(f):
    return _cached(("sig", str(f)), lambda: _signature(f), ttl=30)

def _signature(f):
    try: return sum(int(p.stat().st_mtime) + p.stat().st_size for d in (f, PACK) if d.exists() for p in d.rglob("*") if p.is_file())
    except Exception: return 0

_mem = {"mtime": None, "idx": None, "post": None, "len": None}

def load():
    """The index, kept in memory. Only re-read from disk when the file has actually changed."""
    if not INDEX.exists(): return None
    m = INDEX.stat().st_mtime
    if _mem["mtime"] != m:
        try: idx = json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception: return None
        post = {}  # word -> [(passage number, count)] so a search only touches passages containing the words
        for n, d in enumerate(idx["docs"]):
            tf = {}
            for w in d["toks"]: tf[w] = tf.get(w, 0) + 1
            for w, c in tf.items(): post.setdefault(w, []).append((n, c))
        _mem.update(mtime=m, idx=idx, post=post, len=[len(d["toks"]) for d in idx["docs"]])
    return _mem["idx"]

_cache = {}
def _cached(key, fn, ttl=60):
    """Remember slow answers (folder scans, database schemas) for a minute."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    v = fn(); _cache[key] = (time.time(), v); return v

def status():
    i = load(); f = folder()
    if not i: return {"ok": False, "folder": str(f), "files": 0, "chunks": 0, "stale": True}
    return {"ok": True, "folder": i["folder"], "files": i["files"], "chunks": i["chunks"], "built": i["built"], "stale": signature(f) != i.get("sig"),
            "databases": [d.name for d in databases()], "tables": len(schema()), "instructions": bool(instructions())}

def refresh_if_changed():
    s = status()
    if s["stale"] and folder().exists(): learn()

def search(q, k=4):
    i = load()
    if not i or not i["docs"]: return []
    N = len(i["docs"]); scores = {}; post, dl = _mem["post"], _mem["len"]
    for w in set(tok(q)):
        if w not in post: continue
        idf = math.log(1 + (N - i["df"][w] + .5) / (i["df"][w] + .5))
        for n, f in post[w]:
            scores[n] = scores.get(n, 0) + idf * f * 2.2 / (f + 1.2 * (.25 + .75 * dl[n] / i["avgdl"]))
    best = sorted(scores.items(), key=lambda x: -x[1])[:k]
    return [(sc, i["docs"][n]) for n, sc in best]

def _row_say(r):
    return ", ".join(p.replace("=", " ", 1) for p in r.split("; ") if not re.match(r"^\w*id=", p))

def answer(q):
    """Offline answer: the most relevant lines or database rows from your files, and where they came from."""
    hits = search(q, 6); qt = set(tok(q))
    if not hits or not qt: return None
    need = max(1, (len(qt) + 1) // 2); units = []
    for rank, (sc, d) in enumerate(hits):
        if "::" in d["file"]:
            table = d["file"].split("::")[-1].strip()
            if d["text"].startswith("Database table"):
                structural = re.search(r"\b(table|tables|columns?|fields?|schema|structure)\b", q.lower())
                units.append((len(qt & set(tok(d["text"]))) + sc / 10 + (2 if structural and table in q.lower() else -1), d["text"], table)); continue
            for r in d["text"].split(": ", 1)[-1].split(" | "):
                ov = len(qt & set(tok(r)))
                if ov >= need: units.append((ov + sc / 10, f"{table}: {_row_say(r)}", table))
        else:
            for s2 in re.split(r"(?<=[.!?])\s+|\n+", d["text"]):
                ov = len(qt & set(tok(s2)))
                if ov >= need and 8 < len(s2) < 400: units.append((ov + sc / 10, s2.strip("# ").strip(), pathlib.Path(d["file"]).stem))
    if not units: return None
    units.sort(key=lambda x: -x[0]); best = units[0][0]; pick, seen = [], set()
    for sc, u, src in units:
        if u not in seen and sc >= best - 1.2: pick.append((u, src)); seen.add(u)
        if len(pick) == 3: break
    srcs = list(dict.fromkeys(src.replace("-", " ").replace("_", " ") for _, src in pick))
    return " ".join(u if u.endswith((".", "!", "?")) else u + "." for u, _ in pick) + f" That's from {', '.join(srcs)}."

def data_answer(q):
    """Simple questions answered with real queries: 'what's in the database', 'how many orders', 'how many pending orders'."""
    sc = schema(); ql = q.lower()
    if not sc: return None
    if re.search(r"(what|which) tables|what('s| is) in (the|my) (database|data)|describe (the|my) (database|data)", ql):
        return "Your data has " + ", ".join(f"{t['table']} with {t['rows']:,} rows" for t in sc) + "."
    m = re.search(r"how many ([\w ]+?)(?:\?|$| are| do| have| in| were| did)", ql)
    if m:
        words = m.group(1).split()
        for t in sc:
            name = t["table"].lower(); sing = name.rstrip("s")
            if any(w.rstrip("s") == sing for w in words):
                filt = [w for w in words if w.rstrip("s") != sing]
                for w in filt:  # e.g. "how many pending orders": find a text column holding that value
                    for c in t["columns"]:
                        r = query(f'{t["db"].rsplit(".",1)[0]}: SELECT COUNT(*) FROM "{t["table"]}" WHERE lower("{c}") = \'{w.replace("'", "")}\'')
                        if r["ok"] and r["rows"][0][0]: n = r["rows"][0][0]; return f"There {'is' if n == 1 else 'are'} {n:,} {w} {t['table'].rstrip('s') if n == 1 else t['table']}."
                return f"There are {t['rows']:,} {t['table']} in total."
    return None

def context(q, k=4):
    return "\n\n".join(f"[{d['file']}]\n{d['text']}" for _, d in search(q, k))

if __name__ == "__main__":
    import sys
    print(learn(sys.argv[1] if len(sys.argv) > 1 else None))
