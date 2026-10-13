"""Every conversation with Piper, kept forever on this PC (brain/conversations.sqlite) and searchable,
so Piper can refer back: 'last Tuesday you asked about pallet counts'.
Nothing here leaves the PC. Delete the file to wipe it; say 'forget our conversations' to clear it."""
import pathlib, re, sqlite3, threading, time

ROOT = pathlib.Path(__file__).parent
DB = ROOT / "brain" / "conversations.sqlite"
_lock = threading.Lock()
STOP = set("a an the and or of to in on at for with is are was were be how do does did i my me you your what which who why when "
           "where can could would should will it this that there their about from please piper hey hi hello ok okay so just".split())
ACKISH = re.compile(r"^(?:ok(?:ay)?|cool|great|perfect|thanks?|thank you|cheers|got it|no|yes|yeah|yep|nope|nah|hi|hello|hey)[\s,.!]*$", re.I)

def con():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5(user, reply, at UNINDEXED, tokenize='porter unicode61')")
    return c

def add(user, reply, at=None):
    """Keep one exchange. Short pleasantries are kept too (they're part of the record) but never searched."""
    if not (user or "").strip() or not (reply or "").strip(): return
    with _lock:
        c = con()
        try: c.execute("INSERT INTO turns(user, reply, at) VALUES (?,?,?)", (user.strip()[:2000], reply.strip()[:3000], at or time.time())); c.commit()
        finally: c.close()

def import_history(history):
    """First run: bring in the recent exchanges Piper already had."""
    with _lock:
        c = con()
        try:
            if c.execute("SELECT count(*) FROM turns").fetchone()[0]: return 0
            n = 0
            for u, a in zip(history[::2], history[1::2]):
                if u.get("role") == "user" and a.get("role") == "assistant":
                    c.execute("INSERT INTO turns(user, reply, at) VALUES (?,?,?)", (u["content"], a["content"], u.get("at", time.time()))); n += 1
            c.commit(); return n
        finally: c.close()

def count():
    if not DB.exists(): return 0
    with _lock:
        c = con()
        try: return c.execute("SELECT count(*) FROM turns").fetchone()[0]
        finally: c.close()

def when(at):
    """'today', 'yesterday', 'on Tuesday', 'on 3 October'."""
    d = (time.time() - at) / 86400; lt = time.localtime(at)
    if time.strftime("%Y%m%d", lt) == time.strftime("%Y%m%d"): return "earlier today"
    if time.strftime("%Y%m%d", lt) == time.strftime("%Y%m%d", time.localtime(time.time() - 86400)): return "yesterday"
    if d < 7: return "on " + time.strftime("%A", lt)
    return "on " + time.strftime("%d %B", lt).lstrip("0")

def search(q, k=2, skip_recent_s=1800):
    """Past exchanges about the same thing. The last half hour is skipped: the brain already sees that conversation."""
    ws = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in STOP and len(w) > 2]
    if not ws or not DB.exists(): return []
    with _lock:
        c = con()
        try:
            rows = c.execute("SELECT user, reply, at, bm25(turns) FROM turns WHERE turns MATCH ? ORDER BY 4 LIMIT 20",
                             (" OR ".join(f'"{w}"' for w in ws),)).fetchall()
        except sqlite3.Error: return []
        finally: c.close()
    out, cut = [], time.time() - skip_recent_s
    for u, r, at, _ in rows:
        at = float(at)
        if at > cut or ACKISH.match(u.strip()) or u.startswith("("): continue
        have = set(re.findall(r"[a-z0-9]+", (u + " " + r).lower()))
        if sum(1 for w in ws if w in have or any(h.startswith(w[:5]) for h in have if len(w) > 5)) < max(1, (len(ws) + 1) // 2): continue
        out.append({"user": u, "reply": r, "at": at})
        if len(out) >= k: break
    return out

def context(q):
    hits = search(q)
    if not hits: return ""
    return ("FROM EARLIER CONVERSATIONS (real past exchanges; mention them naturally only if they help, e.g. 'like we worked out yesterday'):\n"
            + "\n".join(f"- {when(h['at'])}, Morne said: \"{h['user'][:220]}\" and you replied: \"{h['reply'][:260]}\"" for h in hits))

DAYS = {"today": 0, "yesterday": 1}
RECALL = re.compile(r"\bwhat (?:did|have) we (?:talk(?:ed)? about|discuss(?:ed)?|chat(?:ted)? about|cover(?:ed)?)\s*(?P<d>today|yesterday|this week|last week|on \w+day)?|"
                    r"\bwhat did i (?:ask|tell) you\s*(?P<d2>today|yesterday|this week|last week|on \w+day)?", re.I)

def recall(text):
    """'What did we talk about yesterday?' -> a short honest list from the archive. None if it isn't that question."""
    m = RECALL.search(text)
    if not m: return None
    d = (m.group("d") or m.group("d2") or "today").lower()
    now = time.time(); lt = time.localtime()
    start_today = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    if d == "today": a, b = start_today, now
    elif d == "yesterday": a, b = start_today - 86400, start_today
    elif d == "this week": a, b = start_today - lt.tm_wday * 86400, now
    elif d == "last week": a, b = start_today - (lt.tm_wday + 7) * 86400, start_today - lt.tm_wday * 86400
    else:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        wd = names.index(d.split()[1]) if d.split()[1] in names else lt.tm_wday
        back = (lt.tm_wday - wd) % 7 or 7
        a = start_today - back * 86400; b = a + 86400
    if not DB.exists(): return "I don't have any conversations saved for then."
    with _lock:
        c = con()
        try: rows = c.execute("SELECT user FROM turns WHERE CAST(at AS REAL) >= ? AND CAST(at AS REAL) < ? ORDER BY CAST(at AS REAL)", (a, b)).fetchall()
        finally: c.close()
    asks = [u for (u,) in rows if not ACKISH.match(u.strip()) and len(u.strip()) > 8 and not RECALL.search(u) and not u.startswith("(")]
    label = {"today": "today", "yesterday": "yesterday", "this week": "this week", "last week": "last week"}.get(d, d)
    if not asks: return f"We didn't talk about anything much {label}, as far as my records go."
    topics = [re.sub(r"\s+", " ", u.strip().rstrip("?.!,"))[:70] for u in asks]
    seen, uniq = set(), []
    for t in topics:
        k = t.lower()[:30]
        if k not in seen: seen.add(k); uniq.append(t)
    if len(uniq) <= 5: return f"{label[:1].upper() + label[1:]} you asked me about: " + "; ".join(f"\"{t}\"" for t in uniq) + "."
    return (f"{label[:1].upper() + label[1:]} we covered {len(uniq)} things. Most recently you asked me about: "
            + "; ".join(f"\"{t}\"" for t in uniq[-5:]) + ".")

def forget_all():
    with _lock:
        c = con()
        try: c.execute("DELETE FROM turns"); c.commit()
        finally: c.close()

def backup(dest):
    if not DB.exists(): return
    with _lock:
        s, d = sqlite3.connect(DB), sqlite3.connect(dest)
        try: s.backup(d)
        finally: s.close(); d.close()
