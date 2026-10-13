"""Piper's long-term memory: one continuing Piper, across restarts and PCs.

Stored in brain/piper_memory.json (travels with the folder). Kinds of memory are kept apart,
because they mean different things:
  fact        something Morne told Piper about himself, his work or his life
  preference  how Morne likes things done
  lesson      a correction: what Piper got wrong and what is right
History (recent conversation) is kept too, so a restart doesn't wipe the thread.

Saving is staged (idea from Pip): write .pending, read it back to check it, then replace.
A dated backup is kept each day in backups/ (last 14 days).
"""
import json, os, pathlib, re, shutil, threading, time

ROOT = pathlib.Path(__file__).parent
FILE = ROOT / "brain" / "piper_memory.json"
BACKUPS = ROOT / "backups"
_lock = threading.Lock()
_data = None

def _empty(): return {"schema": "piper-memory", "version": 1, "memories": [], "history": [], "sessions": 0}

def safe_write(path, obj):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.stem + ".pending.json")
    pending.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    json.loads(pending.read_text(encoding="utf-8"))  # verify before it becomes the real file
    for i in range(10):   # OneDrive / antivirus can hold the file for a moment on Windows
        try: os.replace(pending, path); return
        except PermissionError: time.sleep(0.2 * (i + 1))
    path.write_text(pending.read_text(encoding="utf-8"), encoding="utf-8")

def load():
    global _data
    with _lock:
        if _data is None:
            try: _data = {**_empty(), **json.loads(FILE.read_text(encoding="utf-8"))}
            except FileNotFoundError: _data = _empty()
            except Exception:  # damaged file: fall back to the newest backup, never crash
                good = sorted(BACKUPS.glob("piper_memory-*.json"))
                _data = {**_empty(), **json.loads(good[-1].read_text(encoding="utf-8"))} if good else _empty()
        return _data

def save():
    d = load()
    with _lock:
        safe_write(FILE, d)
        BACKUPS.mkdir(exist_ok=True)
        today = BACKUPS / f"piper_memory-{time.strftime('%Y%m%d')}.json"
        if not today.exists(): shutil.copy2(FILE, today)
        for old in sorted(BACKUPS.glob("piper_memory-*.json"))[:-14]: old.unlink()
        backup_learning()

def new_session():
    load()["sessions"] += 1; save()

# ---------- remembering ----------
def _words(s): return set(re.findall(r"[a-z0-9']+", s.lower())) - STOP
STOP = {"the", "a", "an", "is", "are", "was", "i", "my", "me", "to", "of", "and", "in", "on", "that", "it", "for", "with", "do", "you", "what", "about", "your"}

def add(text, kind="fact", source="you told me"):
    text = text.strip().rstrip(".") + "."
    d = load(); w = _words(text)
    for m in d["memories"]:  # update instead of duplicating
        mw = _words(m["text"])
        if m["kind"] == kind and w and len(w & mw) / len(w | mw) > 0.7:
            m.update(text=text, updated=time.time()); save(); return m
    m = {"id": f"m{int(time.time() * 1000)}", "kind": kind, "text": text, "source": source,
         "created": time.time(), "updated": time.time(), "uses": 0}
    d["memories"].append(m); save(); return m

def forget(what):
    d = load(); w = _words(what); before = len(d["memories"])
    d["memories"] = [m for m in d["memories"] if not (w and len(w & _words(m["text"])) / len(w) >= 0.6)]
    save(); return before - len(d["memories"])

def relevant(question, k=8):
    """Preferences and lessons always count; facts only when they relate to the question."""
    d = load(); qw = _words(question); out = []
    for m in d["memories"]:
        score = len(qw & _words(m["text"])) + (2 if m["kind"] in ("preference", "lesson") else 0)
        if score: out.append((score, m))
    out.sort(key=lambda x: -x[0]); picked = [m for _, m in out[:k]]
    for m in picked: m["uses"] = m.get("uses", 0) + 1
    return picked

def describe(m): return {"fact": "Fact", "preference": "Preference", "lesson": "Lesson"}.get(m["kind"], "Note") + ": " + m["text"]

# ---------- noticing things worth remembering ----------
PATTERNS = [  # (regex on Morne's message, kind, how to phrase it)
    (r"^(?:please )?remember(?: that)? (.+)", "fact", "{0}"),
    (r"\bcall me ([A-Z][\w-]+)", "preference", "Morne wants to be called {0}"),
    (r"\bmy (wife|husband|partner|son|daughter|mum|mom|dad|brother|sister|boss|dog|cat|business|company|shop|brand|website|birthday|email)(?:'s name)? is ([^.?!]+)", "fact", "Morne's {0} is {1}"),
    (r"\bi (?:work|am working) (?:at|for|as) ([^.?!]+)", "fact", "Morne works {0}"),
    (r"\bi live in ([^.?!]+)", "fact", "Morne lives in {0}"),
    (r"\bi (?:prefer|like it when|want you to|'d rather) ([^.?!]+)", "preference", "Morne prefers {0}"),
    (r"\b(?:don't|do not|never) ([^.?!]*(?:say|use|call|give|tell|ask)[^.?!]*)", "preference", "Don't {0}"),
    (r"\bi(?:'m| am) allergic to ([^.?!]+)", "fact", "Morne is allergic to {0}"),
]
CORRECTION = re.compile(r"^(?:no[,.!]?\s|nope|wrong|that's (?:not right|wrong|incorrect)|that is (?:not right|wrong)|not quite|actually[,]?\s|i meant\b|you got (?:it|that) wrong)", re.I)
NOT_CORRECTION = re.compile(r"^(?:uh,?\s*|um,?\s*)?(?:no|nope|nah)[,.!]?\s*(?:thanks?|thank you|ta|that'?s,?\s*(?:all|it|fine|ok|okay|perfect|great|good|right|correct|spot on|cool)|perfect|great|all good|i'?m done|nothing|not (?:now|really|yet)|i'?m (?:good|fine|ok)|"
                            r"other|more|keep|carry on|go on|leave it|forget it|never ?mind|it'?s fine|all good|don'?t|stop|i don'?t)\b", re.I)
SAYS_WHAT = re.compile(r"\b(?:it'?s|it is|it was|that'?s|that is|i'?m|i am|my|i said|i meant|should be|isn'?t|wasn'?t|not\b.+\bbut|is called|"
                       r"called|pronounced|actually|\d)", re.I)

def is_correction(user_text, last_reply=None):
    """Is Morne correcting something Piper said? A plain 'no' answer, or 'no thanks', is not a correction."""
    t = user_text.strip()
    if not CORRECTION.match(t) or NOT_CORRECTION.match(t): return False
    explicit = re.match(r"^(?:wrong|that's (?:not right|wrong|incorrect)|that is|you got)", t, re.I)
    if last_reply and last_reply.rstrip().endswith("?") and not explicit: return False   # answering Piper's question
    rest = re.sub(r"^\W*(?:no|nope|actually|not quite|i meant)\W*", "", t, flags=re.I)
    return bool(explicit) or (len(rest.split()) >= 3 and bool(SAYS_WHAT.search(rest)))

SAY_NAME = re.compile(r"(?:my name is |it'?s |you )?(?:pronounced|say(?: my name| it)?(?: as| like)?)\s+[\"']?([A-Za-z][A-Za-z' -]{1,30}?)[\"']?\s*(?:,|\.|!|$|not\b|like\b)", re.I)

def name_pronunciation(user_text):
    m = SAY_NAME.search(user_text.strip())
    if not m or not re.search(r"(?i)\b(pronounc|say my name|my name)", user_text): return None
    return m.group(1).strip().capitalize()

TEACH = re.compile(r"(?:^|[.,;]\s*|\b(?:so |ok,?\s*|okay,?\s*))(?:to teach you|so you know|for future reference|for the future|just so you know|keep in mind|"
                   r"note that|fyi)[,:.]*\s*(.+)", re.I | re.S)
NUMBER_FACT = re.compile(r"\b[\d,]+ \w+ (?:in|per|to) (?:a|an|one|each|every) \w+", re.I)

def taught(user_text):
    """Things Morne deliberately teaches ('to teach you, there are 240 tins in a box'). Returns the fact or None."""
    t = re.sub(r"\s+", " ", user_text.strip())
    m = TEACH.search(t)
    body = m.group(1) if m else (t if len(NUMBER_FACT.findall(t)) >= 2 else "")
    body = re.split(r"[?]|\.\.|\b(?:how many|how much|what is|what's|can you|could you)\b", body, 1, flags=re.I)[0]
    body = re.sub(r"^[,.\s]+|[,.\s]+$", "", body)
    body = re.sub(r"\s*,\s*", ", ", re.sub(r"\s*,?\s*\.+\s*", ", ", body)).strip(", ")
    if len(body) < 8 or not re.search(r"[a-z]", body, re.I): return None
    return body[:1].upper() + body[1:] + "."

def notice(user_text, last_reply=None):
    """Called after each message. Saves explicit 'remember' requests, clear personal facts and real corrections."""
    saved = []
    say = name_pronunciation(user_text)
    if say:
        saved.append(add(f"Morne's name is pronounced \"{say}\"", "preference"))
        try:   # and the voice says it that way from now on
            p = ROOT / "config.json"; c = json.loads(p.read_text(encoding="utf-8")); c["owner_say"] = say
            safe_write(p, c)
        except Exception as e: print("pronunciation:", e)
        return saved
    t = taught(user_text)
    if t: saved.append(add(f"Morne taught me: {t}", "fact"))
    if is_correction(user_text, last_reply) and last_reply:
        saved.append(add(f"When I said \"{last_reply[:140]}\", Morne corrected me: \"{user_text.strip()[:200]}\"", "lesson", "correction"))
    for rx, kind, fmt in PATTERNS:
        m = re.search(rx, user_text.strip(), re.I)
        if m:
            groups = [g.strip() for g in m.groups()]
            if kind == "fact" and rx.startswith("^(?:please )?remember"):
                saved.append(add(groups[0][:1].upper() + groups[0][1:], "fact")); break
            saved.append(add(fmt.format(*groups), kind))
    return [x for x in saved if x]

def backup_learning():
    """Daily copies of what Piper has learned: the reading journal and study list (small), and the study notes
    database once a week (it can be large, so only the last 2 weekly copies are kept)."""
    try:
        BACKUPS.mkdir(exist_ok=True); day = time.strftime("%Y%m%d")
        for src, name in ((ROOT / "brain" / "learning_journal.json", "learning_journal"), (ROOT / "learned" / "study.json", "study")):
            if src.exists():
                dst = BACKUPS / f"{name}-{day}.json"
                if not dst.exists(): shutil.copy2(src, dst)
                for old in sorted(BACKUPS.glob(f"{name}-*.json"))[:-14]: old.unlink()
        db = ROOT / "learned" / "learned.sqlite"
        if db.exists():
            week = time.strftime("%Y-w%W"); dst = BACKUPS / f"learned-{week}.sqlite"
            if not dst.exists():
                import sqlite3   # a proper online copy, safe even while studying is writing
                s, d = sqlite3.connect(db), sqlite3.connect(dst)
                try: s.backup(d)
                finally: s.close(); d.close()
            for old in sorted(BACKUPS.glob("learned-*.sqlite"))[:-2]: old.unlink()
        import conversations
        dst = BACKUPS / f"conversations-{time.strftime('%Y-w%W')}.sqlite"
        if conversations.DB.exists() and not dst.exists(): conversations.backup(dst)
        for old in sorted(BACKUPS.glob("conversations-*.sqlite"))[:-4]: old.unlink()
    except Exception as e: print("learning backup:", e)

def clean_junk():
    """One-off tidy: remove memories saved by mistake in earlier versions
    (a plain 'no' saved as a correction, or a question saved as the answer to a get-to-know question)."""
    d = load(); before = len(d["memories"]); keep = []
    for m in d["memories"]:
        t = m.get("text", "")
        c = re.search(r'Morne corrected me: "(.*?)"\.?\s*$', t)
        if m.get("kind") == "lesson" and c and not is_correction(c.group(1).rstrip(". ")): continue
        a = re.search(r'^Asked ".*?", Morne said: (.*)$', t)
        if a and looks_like_question(a.group(1)): continue
        keep.append(m)
    if len(keep) != before:
        d["memories"] = keep; save()
    return before - len(keep)

QUESTION = re.compile(r"^(?:what|when|where|who|why|how|which|can|could|would|will|is|are|do|does|did|tell me|go |search|look up|find|study|learn|check|open|play)\b", re.I)
def looks_like_question(t):
    t = t.strip()
    return t.endswith("?") or bool(QUESTION.match(t))

# ---------- conversation history across restarts ----------
def remember_turn(user, reply):
    d = load(); now = time.time()
    d["history"] += [{"role": "user", "content": user, "at": now}, {"role": "assistant", "content": reply, "at": now}]
    d["history"] = d["history"][-40:]; save()
    try:
        import conversations; conversations.add(user, reply, now)   # the permanent, searchable record
    except Exception as e: print("conversation archive:", e)

def recent_history(hours=12, n=8):
    cut = time.time() - hours * 3600
    return [{"role": h["role"], "content": h["content"]} for h in load()["history"] if h["at"] > cut][-n:]

def clear_history():
    load()["history"] = []; save()

def summary():
    d = load(); by = {}
    for m in d["memories"]: by[m["kind"]] = by.get(m["kind"], 0) + 1
    return {"total": len(d["memories"]), "by_kind": by, "sessions": d["sessions"], "history": len(d["history"])}
