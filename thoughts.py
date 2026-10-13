"""What Piper is genuinely 'thinking about': real items from Morne's day, Piper's own learning, and its curiosity about him.

Nothing here is scripted text. It gathers the real situation and lets the language model talk about it naturally.
"""
import json, pathlib, random, re, time

ROOT = pathlib.Path(__file__).parent

# Things a good assistant would want to know about the person it works for. Asked one at a time, rarely.
GET_TO_KNOW = [
    ("work", ["work", "job", "business", "company", "role"], "What does a normal working day look like for you, and what takes up most of your time?"),
    ("goals", ["goal", "aim", "this year", "plan"], "What's the one thing you most want to get done in the next few months?"),
    ("routine", ["morning", "routine", "wake", "start the day"], "What time do you usually start your day, and when would a morning briefing be most useful?"),
    ("interests", ["hobby", "enjoy", "interest", "fun", "free time"], "What do you enjoy doing when you're not working?"),
    ("people", ["wife", "husband", "partner", "son", "daughter", "family", "friend", "team"], "Who are the people you work with or talk to most? It'll help me make sense of your emails."),
    ("stress", ["stress", "annoy", "hate", "drain", "worry"], "What's the part of your week you'd most like help with, or rather not have to think about?"),
    ("instagram", ["instagram", "siberiawhitefox", "fox", "content"], "What's your Instagram, siberiawhitefox, really for: a business, a hobby, or something you're building up?"),
    ("food", ["food", "eat", "cook", "vegetarian", "diet"], "Any food likes or dislikes I should know about, in case you ask me for ideas?"),
]

STATE = ROOT / "brain" / "curiosity.json"

def _state():
    try: return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: return {"asked": {}, "pending": None, "last_asked": 0}

def _save(s):
    import memory
    memory.safe_write(STATE, s)

def known(topic_words):
    import memory
    text = " ".join(m["text"].lower() for m in memory.load()["memories"])
    return any(w in text for w in topic_words)

def next_question(force=False):
    """One question to get to know Morne, if it's a good moment (at most every 4 hours)."""
    s = _state()
    if not force and time.time() - s.get("last_asked", 0) < 4 * 3600: return None
    for key, words, q in GET_TO_KNOW:
        if key in s["asked"] or known(words): continue
        return key, q
    return None

def asked(key, question):
    s = _state(); s["asked"][key] = time.time(); s["pending"] = {"key": key, "q": question, "at": time.time()}; s["last_asked"] = time.time(); _save(s)

def take_answer(user_text):
    """If Morne is answering Piper's last get-to-know question, keep his answer as a memory."""
    s = _state(); p = s.get("pending")
    if not p or time.time() - p["at"] > 1800: return None
    s["pending"] = None; _save(s)
    t = user_text.strip()
    if len(t) < 3 or re.match(r"^(no|nah|skip|not now|later|pass|mind your own)\b", t, re.I): return None
    import memory
    if memory.looks_like_question(t): return None   # he moved on to something else instead of answering
    return memory.add(f"Asked \"{p['q']}\", Morne said: {t}", "fact", "get to know you")

def current(question=""):
    """The real material for 'what are you thinking about'."""
    import piper_core, awareness, memory
    items = []
    n = awareness.now()
    w = awareness.weather()
    if w and w.get("rain_chance", 0) >= 60: items.append(f"It's likely to rain today ({w['rain_chance']}%), so if you're heading out, take a coat.")
    cal = piper_core.read("calendar")
    if cal.get("online"):
        upcoming = [e for e in cal.get("events", []) if e["time"] == "all day" or e["time"] >= n.strftime("%H:%M")]
        items.append(f"Next on your calendar: {upcoming[0]['title']} at {upcoming[0]['time']}." if upcoming else "Your calendar's clear for the rest of today.")
    gm = piper_core.read("gmail")
    if gm.get("online"):
        un = [m for m in gm.get("messages", []) if m.get("unread") and m.get("personal", True)]
        if un: items.append(f"{len(un)} personal email{'s' if len(un) != 1 else ''} unread, including {un[0]['from']} about \"{un[0]['subject']}\". I could help you reply.")
    pr = piper_core.priorities()
    if pr: items.append(f"Your top priority is still: {pr[0]}.")
    gaps = [h["content"] for h in memory.load()["history"] if h["role"] == "assistant" and re.search(r"couldn't find|don't know|not sure", h["content"], re.I)][-2:]
    if gaps: items.append("I couldn't answer something you asked recently, so I'd like to learn more about it.")
    learned = awareness.recent_learning(2, unshared_only=True)
    for e in learned: items.append(f"Earlier I read about {e['title']} ({e['source']}): {e['summary']}")
    ig = piper_core.read("instagram")
    if ig.get("online") and ig.get("followers_7d_ago") is not None and ig["followers"] != ig["followers_7d_ago"]:
        items.append(f"Instagram moved from {ig['followers_7d_ago']} to {ig['followers']} followers this week.")
    nq = next_question(force=True)
    if nq: items.append(f"I'd like to know you better. Something I'm curious about: {nq[1]}")
    items.append("Ideas I could act on: read about something new and report back, prepare tomorrow's briefing, or go through your emails with you.")
    return items
