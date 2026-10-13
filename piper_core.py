"""Piper core. Reads ./connectors/*.json, builds the brief, writes brief.txt + piper_data.js.
Everything runs on this PC: Ollama or the built-in brain."""
import time, json, os, re, datetime, subprocess, pathlib
ROOT = pathlib.Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
MODE = os.environ.get("PIPER_MODE", "mock")
SOURCES = {"instagram": "Instagram", "gmail": "Gmail", "calendar": "Calendar", "shopify": "Shopify", "stripe": "Stripe"}

def read(key):
    p = ROOT / "connectors" / f"{key}.json"
    if not p.exists(): return {"connector": SOURCES[key], "online": False, "state": "not connected"}
    try: d = json.loads(p.read_text())
    except Exception as e: return {"connector": SOURCES[key], "online": False, "state": f"bad file: {e}"}
    d["online"] = True; d["state"] = "sample data" if d.get("source") == "sample" else ("live" if d.get("source") in (None, "live") else f"live via {d.get('source')}")
    return d

EXAMPLE_PRIORITIES = {"grow the instagram following", "post three times this week, including one reel",
                      "fill the knowledge folder with notes and documents"}   # placeholders from the first version, not Morne's

def priorities():
    p = ROOT / "priorities.md"
    if not p.exists(): return []
    out = [re.sub(r"^\d+\.\s*", "", l).strip() for l in p.read_text(encoding="utf-8").splitlines() if re.match(r"^\d+\.", l)]
    return [x for x in out if x and x.lower().rstrip(". ") not in EXAMPLE_PRIORITIES]

def lc(s): return s[:1].lower() + s[1:] if s else s

DAYS = {"mon":"Monday","tue":"Tuesday","wed":"Wednesday","thu":"Thursday","fri":"Friday","sat":"Saturday","sun":"Sunday"}
def spoken_time(t):
    m = re.match(r"(\w{3})\w*\s+(\d{1,2}):(\d{2})", t or "")
    if not m: return t
    h = int(m.group(2)); part = "in the morning" if h < 12 else "in the afternoon" if h < 17 else "in the evening"
    return f"{DAYS.get(m.group(1).lower(), m.group(1))} at {h % 12 or 12} {part}"

def ig_lines(ig):
    if not ig["online"]: return ["Instagram isn't connected yet, so I've nothing to report there."]
    n = lambda k: ig.get(k) is not None
    first = f"On Instagram, you're at {ig['followers']:,} followers"
    if n("following"): first += f", following {ig['following']:,}"
    if n("posts_total"): first += f", with {ig['posts_total']} posts on your profile"
    if n("followers_7d_ago"):
        g = ig["followers"] - ig["followers_7d_ago"]; first += f". That's {abs(g)} {'more' if g >= 0 else 'fewer'} than last week"
    out = [first + "."]
    if n("reach_7d"):
        out.append(f"Reach came in at {ig['reach_7d']:,} over the past seven days" + (f", with engagement around {ig['engagement_rate_pct']} percent." if n("engagement_rate_pct") else "."))
    top = max(ig["top_posts"], key=lambda p: p.get("reach") or 0) if ig.get("top_posts") else None
    if top: out.append(f"Your strongest post was the {top['caption'].lower()}. It reached {top['reach']:,} people and picked up {top['saves']} saves.")
    if n("profile_visits_7d"): out.append(f"{ig['profile_visits_7d']} people visited your profile, and {ig.get('link_clicks_7d') or 0} of them tapped your link.")
    if ig.get("source") == "sample": out.append("Just so you know, these are still sample figures until Metricool finishes syncing.")
    elif not n("reach_7d"): out.append("Metricool is still building your history, so reach and post stats will appear over the next few days.")
    return out

def other_lines(s):
    out = []; c = s["calendar"]
    if c["online"]:
        ev = c.get("events", [])
        out.append(f"You've got {len(ev)} things on today, starting with {ev[0]['title']} at {ev[0]['time']}." if ev else "Your calendar is clear today.")
    g = s["gmail"]
    if g["online"]:
        unread = [m for m in g.get("messages", []) if m.get("unread")]
        people = [m for m in unread if m.get("personal", True)]
        names = list(dict.fromkeys(m["from"] for m in people))[:2]
        out.append(f"In your inbox, {len(people)} personal unread email{'s' if len(people) != 1 else ''}" + (f", from {' and '.join(names)}" if names else "") +
                   (f", plus {len(unread) - len(people)} newsletters and offers." if len(unread) > len(people) else "."))
    sh = s["shopify"]
    if sh["online"]:
        out.append(f"Your store had {sh['orders_today']} orders today and {sh['orders_7d']} this week, worth {sh['currency']} {sh['sales_7d']:,}." + (f" {sh['unfulfilled']} are waiting to ship." if sh.get("unfulfilled") else ""))
    st = s["stripe"]
    if st["online"]:
        out.append(f"Stripe took {st['currency']} {st['revenue_7d']:,} this week from {st['payments_7d']} payments." + (f" {st['failed_7d']} payments failed, worth a look." if st.get("failed_7d") else ""))
    return out

def prio_line(pr):
    if not pr: return "You haven't set any priorities yet. Add a few to priorities dot m d and I'll keep you on track."
    pr = [re.sub(r"\[.*?\]", "", p).strip() or p for p in pr[:3]]
    if len(pr) == 1: return f"As for today, your main focus is to {lc(pr[0])}."
    return f"As for today, your top priority is to {lc(pr[0])}" + (f", followed by {lc(pr[1])}" if len(pr) > 1 else "") + (f", and then {lc(pr[2])}." if len(pr) > 2 else ".")

BRIEF_STATE = ROOT / "brain" / "brief_state.json"

def adaptive_brief(s, ig, pr, now, part, w, loc, commit=True):
    """A brief that changes: it remembers what it told you last time, leads with what's new,
    fits the time of day, and leaves out anything that hasn't changed."""
    import random
    try: last = json.loads(BRIEF_STATE.read_text(encoding="utf-8"))
    except Exception: last = {}
    since_h = (now.timestamp() - last.get("t", 0)) / 3600
    same_day = last.get("day") == now.strftime("%Y-%m-%d")
    pick = lambda *opts: random.choice(opts)
    out = [pick(f"Good {part}, {CFG['owner']}.", f"{part.capitalize()}, {CFG['owner']}.", f"Hello {CFG['owner']}.")]
    news = []

    # weather: full on the first brief of the day, otherwise only if it's turned
    if w:
        now_w = w["now"].split(",")[0]; town = loc["name"].split(",")[0]
        temp = w["now"].split(",")[1].strip().split(" ")[0] if "," in w["now"] else ""
        if not same_day:
            news.append(f"In {town} it's {now_w}, {temp}; " + ("today looks " + w["today"] if part != "evening" else "tomorrow looks " + w.get("tomorrow", w["today"])) + ".")
        elif last.get("weather") != now_w:
            news.append(f"The weather's changed: it's {now_w} now.")
        if part == "evening" and same_day and last.get("tomorrow_told") != now.strftime("%Y-%m-%d") and w.get("tomorrow"):
            news.append("Tomorrow looks " + w["tomorrow"] + "."); last["tomorrow_told"] = now.strftime("%Y-%m-%d")
        rain = re.search(r"(\d+)% chance of rain", w.get("today", ""))
        if part != "evening" and rain and int(rain.group(1)) >= 60 and "rain" not in now_w and "drizzle" not in now_w and last.get("rain_warned") != now.strftime("%Y-%m-%d"):
            news.append("Rain's on the way, so take a coat if you're heading out."); last["rain_warned"] = now.strftime("%Y-%m-%d")

    # calendar: what's next, or tomorrow in the evening
    c = s["calendar"]
    if c["online"]:
        ev = [e for e in c.get("events", []) if e["time"] == "all day" or e["time"] >= now.strftime("%H:%M")]
        def soon(e):
            if e["time"] == "all day": return False
            hh, mm = map(int, e["time"].split(":")); return 0 <= (hh * 60 + mm) - (now.hour * 60 + now.minute) <= 60
        if ev and (not same_day or last.get("next_event") != ev[0]["title"] + ev[0]["time"] or soon(ev[0])):
            e = ev[0]; more = len(ev) - 1
            news.append(pick(f"Next up is {e['title']} at {e['time']}", f"You've got {e['title']} at {e['time']}") +
                        (f", then {more} more after that." if more else "."))
        elif not ev and (not same_day or last.get("events_left", 0)): news.append("Nothing else on your calendar today." if part != "morning" else "Your calendar's clear today.")
        last["events_left"] = len(ev); last["next_event"] = (ev[0]["title"] + ev[0]["time"]) if ev else None

    # email: only what arrived since the last brief
    g = s["gmail"]
    if g["online"]:
        seen = set(last.get("mail_seen", []))
        fresh = [m for m in g.get("messages", []) if m.get("unread") and (m.get("uid") or m["subject"]) not in seen]
        people = [m for m in fresh if m.get("personal", True)]     # real people / Primary tab only
        bulk = len(fresh) - len(people)
        if people:
            names = list(dict.fromkeys(m["from"] for m in people))[:2]
            news.append(f"{len(people)} new email{'s' if len(people) > 1 else ''} worth a look" + (" since I last checked in" if since_h < 20 else "") +
                        f", from {' and '.join(names)}" + (" and others." if len(names) < len(set(m['from'] for m in people)) else "."))
        elif bulk and not same_day:
            news.append(f"No personal email, just {bulk} newsletter{'s' if bulk != 1 else ''} and offer{'s' if bulk != 1 else ''}.")
        last["mail_seen"] = [m.get("uid") or m["subject"] for m in g.get("messages", [])][:50]

    for line in other_lines({**s, "calendar": {"online": False}, "gmail": {"online": False}}): news.append(line)   # shop and payments

    # priorities: real ones only, once a day, and the next one if the first was already mentioned
    if pr and (not same_day or part == "morning"):
        news.append(f"Top of your list today: {lc(pr[0])}.")

    # Instagram: one-line notice, only when it moved; never advice
    if ig["online"]:
        prev = last.get("followers")
        if prev is not None and ig["followers"] != prev:
            d = ig["followers"] - prev; news.append(f"Instagram: {d:+d} follower{'s' if abs(d) != 1 else ''}, you're on {ig['followers']:,}.")
        elif prev is None:
            news.append(f"Instagram: {ig['followers']:,} followers.")
        last["followers"] = ig["followers"]

    if not news: news.append(pick("Nothing's changed since I last checked in.", "All quiet since my last update."))
    out += news + [pick("Anything you'd like me to start on?", "What would you like to do first?", "Shout if you need anything.")]
    last.update(t=now.timestamp(), day=now.strftime("%Y-%m-%d"), weather=(w["now"].split(",")[0] if w else None))
    if commit:   # only once it has actually been said, so you never miss news you didn't hear
        try: BRIEF_STATE.parent.mkdir(exist_ok=True); BRIEF_STATE.write_text(json.dumps(last), encoding="utf-8")
        except Exception as e: print("brief state:", e)
    return out

def _brain_label():
    try:
        import brain; b, m = brain.pick()
        return {"ollama": f"OLLAMA · {m}", "builtin": "BUILT-IN BRAIN"}.get(b, "PATTERN MODE (no brain)")
    except Exception: return "PATTERN MODE"

def morning_brief(write=True, spoken=False):
    import awareness, memory
    s = {k: read(k) for k in SOURCES}; ig = s["instagram"]; pr = priorities(); now = awareness.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    w = awareness.weather(); loc = awareness.location()
    wline = [f"In {loc['name'].split(',')[0]} it's {w['now'].split(',')[0]} and {w['now'].split(',')[1].strip().split(' ')[0]}; today looks {w['today']}."] if w else []
    lines = adaptive_brief(s, ig, pr, now, part, w, loc, commit=spoken)
    log = []
    for k, v in s.items():
        if k == "instagram" and v["online"]:
            log.append(f"IG   {v['state']}: {v['followers']:,} followers, {v.get('posts_total') or len(v.get('top_posts',[]))} posts")
        elif v["online"]:  # only show accounts that are actually connected
            src = v.get("source") or ""
            log.append(f"{v['connector'].upper()} connected" + (f" via {src}" if src and src not in ("live", "sample") else ""))
    log.append(f"PRIO {len(pr)} priorities loaded")
    try:
        import knowledge; ks = knowledge.status()
        log.append(f"KNOW {ks['files']} files, {ks['chunks']} passages learned" if ks["ok"] else "KNOW no folder learned yet")
    except Exception as e: ks = {"ok": False}; log.append("KNOW unavailable")
    g = ig["followers"] - ig["followers_7d_ago"] if ig["online"] and ig.get("followers_7d_ago") is not None else None
    data = {"owner": CFG["owner"], "assistant": CFG["assistant_name"], "subtitle": CFG.get("subtitle", ""), "voice_lang": CFG["voice_lang"],
            "greeting": f"Good {part}, {CFG['owner']}.", "generated": now.strftime("%a %d %b %Y, %H:%M"), "mode": _brain_label(),
            "sample": ig.get("source") == "sample", "knowledge": ks,
            "connectors": [{"name": v["connector"], "online": True, "state": v["state"]} for v in s.values() if v["online"] and v.get("source") != "sample"],
            "log": log, "instagram": {k: ig.get(k) for k in ("account","followers","following","posts_total","reach_7d","impressions_7d","profile_visits_7d","link_clicks_7d","engagement_rate_pct","posts_7d","top_posts","best_time_to_post")} if ig["online"] else {},
            "today": {"location": awareness.location()["name"], "weather": (w or {}).get("now"), "today": (w or {}).get("today"),
                      "unread": s["gmail"].get("unread") if s["gmail"]["online"] else None,
                      "events": len(s["calendar"].get("events", [])) if s["calendar"]["online"] else None,
                      "next_event": next((f"{e['time']} {e['title']}" for e in s["calendar"].get("events", []) if e["time"] == "all day" or e["time"] >= now.strftime("%H:%M")), None) if s["calendar"]["online"] else None,
                      "priority": pr[0] if pr else None, "memories": memory.summary()["total"],
                      "followers": ig.get("followers") if ig["online"] else None},
            "growth_7d": g, "extra": {k: s[k] for k in ("gmail","calendar","shopify","stripe") if s[k]["online"]}, "priorities": pr[:3], "headline": lines[1], "brief": lines, "closer": lines[-1]}
    if write:
        (ROOT / "brief.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (ROOT / "piper_data.js").write_text("// generated by piper_core.py\nwindow.PIPER_DATA = " + json.dumps(data, indent=2) + ";\n", encoding="utf-8")
    return "\n".join(lines), data


# ---------- memory, self-knowledge and self-test (ideas from the Pip design) ----------
STAGE = "\x00stage:"  # a status line for the screen, not something to say out loud

def memory_command(text):
    import memory
    t = text.strip(); tl = t.lower().rstrip("?.! ")
    m = re.match(r"^(?:please )?(?:forget|delete the memory|stop remembering)(?: about| that)? (.+)", tl)
    if m:
        n = memory.forget(m.group(1))
        return f"Done, I've forgotten {n} thing{'s' if n != 1 else ''} about that." if n else "I didn't have anything saved about that."
    if re.match(r"^(?:please )?remember(?: that)? .+", tl):
        saved = memory.notice(t)
        return f"Got it. I'll remember: {saved[0]['text']}" if saved else "Sorry, I didn't catch what to remember."
    if re.search(r"what (?:do|did) you (?:remember|know) about me|what have you (?:learned|remembered) about me|what do you remember\b", tl):
        ms = memory.load()["memories"]
        if not ms: return "I don't have anything saved about you yet, apart from your name. Tell me things like 'remember that my shop is called...' and I'll keep them."
        facts = [x["text"] for x in ms if x["kind"] == "fact"][-6:]; prefs = [x["text"] for x in ms if x["kind"] == "preference"][-4:]
        lessons = [x for x in ms if x["kind"] == "lesson"]
        out = []
        if facts: out.append("Here's what you've told me: " + " ".join(facts))
        if prefs: out.append("How you like things: " + " ".join(prefs))
        if lessons: out.append(f"I've also kept {len(lessons)} correction{'s' if len(lessons) != 1 else ''} so I don't repeat mistakes.")
        return " ".join(out)
    return None

def system_state():
    """What Piper actually is right now, from real state. Used for 'what are you thinking / what do you know'."""
    import brain, knowledge, wiki, memory
    b, model = brain.pick(); st = brain.state; ks = knowledge.status(); mem = memory.summary()
    try: libs = wiki.libraries()
    except Exception: libs = []
    conns = [v["connector"] for v in (read(k) for k in SOURCES) if v.get("online") and v.get("source") != "sample"]
    lines = [f"Thinking with: {({'ollama': 'Ollama ' + str(model), 'builtin': 'the built-in model ' + str(model)}).get(b, 'no language model (pattern answers only)')}.",
             f"Long-term memory: {mem['total']} things saved ({', '.join(f'{v} {k}' + ('s' if v != 1 else '') for k, v in mem['by_kind'].items()) or 'none yet'}), across {mem['sessions']} sessions.",
             f"Recent conversation I'm holding: {mem['history'] // 2} exchanges.",
             f"Files I've learned (your notes plus my built-in pack): {ks.get('files', 0)} files" + (f", plus {ks.get('tables', 0)} database tables" if ks.get('tables') else "") + ".",
             "Built-in knowledge pack (written into me by Claude, mid-2026): iPhone and iOS, Windows PC, Google Workspace "
             "(Gmail, Calendar, Drive, Docs, Sheets, Meet), orders, boxes and everyday maths, the Isle of Man, and my own abilities and limits.",
             "Study notes: " + __import__("study").progress_text(),
             "Maths: done exactly by my calculator, not guessed. Distances and directions: OpenStreetMap, when online.",
             "Reference libraries I can look up (not memorised): " + (", ".join(f"{l['name']} ({l.get('articles', 0):,} articles)" for l in libs) or "none") + ".",
             f"Wikipedia articles saved from online lookups: {wiki.count():,}. Online lookups are {'on' if wiki.cfg().get('wiki_online', True) else 'off'}.",
             "Connected accounts: " + (", ".join(conns) or "none") + ".",
             f"Current topic: {(memory.recent_history(n=2) or [{'content': 'nothing yet'}])[0]['content'][:80]}"]
    if st.get("first_words") is not None: lines.append(f"Last reply started after {st['first_words']} seconds.")
    return "\n".join(lines)

META = re.compile(r"\b(what are you (?:thinking|doing|up to)|what do you know|what can you (?:do|look up)|what have you (?:learned|got)|"
                  r"how do you know|status report|system status|what model|which model|are you online|what'?s in your (?:memory|head|index)|"
                  r"what is your status|self[- ]?model|list (?:your )?(?:sources|libraries))\b", re.I)

def self_test():
    """Quick health check of each part. Returns (spoken summary, details)."""
    import brain, knowledge, wiki, memory, voice
    checks = []
    def chk(name, fn):
        try: ok, note = fn()
        except Exception as e: ok, note = False, str(e)[:80]
        checks.append((name, ok, note))
    def mem():
        memory.save(); json.loads(memory.FILE.read_text(encoding="utf-8")); return True, f"{memory.summary()['total']} memories"
    chk("Memory saves and reads back", mem)
    chk("Emergency safety lines", lambda: (emergency("i broke my leg") == "injury" and emergency("tell me about fire safety laws") is None, "ok"))
    chk("Script and fixed answers", lambda: (bool(brain.fixed_answer("who are you")), f"{len(brain.script()['fixed'])} fixed answers"))
    chk("Language model", lambda: (bool(brain.pick()[0]), brain.pick()[1] or brain.state.get("error") or "none available"))
    chk("Your files", lambda: (knowledge.status().get("ok", False), f"{knowledge.status().get('files', 0)} files"))
    def libs():
        ls = wiki.libraries(); return (bool(ls) and not any(l.get("error") for l in ls), f"{len(ls)} libraries")
    chk("Reference libraries", libs)
    chk("Voice", lambda: (voice.status()["ok"], voice.status().get("voice") or voice.status().get("why", "")))
    ok = [c for c in checks if c[1]]; bad = [c for c in checks if not c[1]]
    say = f"Self-test done: {len(ok)} of {len(checks)} parts are working."
    if bad: say += " Needs attention: " + "; ".join(f"{n} ({note})" for n, _, note in bad) + "."
    else: say += " Everything looks healthy."
    return say, checks

THINKING = re.compile(r"\b(what are you (?:thinking|doing|up to|working on)|what'?s on your mind|penny for your thoughts|any ideas|what should we do|what now|bored)\b", re.I)
GREETING = re.compile(r"^(?:hi|hey|hello|morning|good (?:morning|afternoon|evening)|how are you|you there|evening|yo)\b", re.I)
LEARN = re.compile(r"^(?:(?:go|please|can you|could you)\s+)*(?:learn|read up on|read about|study|find out about)\s*(?:something|anything)?\s*(?:new|random|interesting)?\s*(?:about\s+(.+))?$"
                   r"|^(?:tell me|give me|share) (?:a |an |something )?(?:random|interesting|new|fun) (?:fact|thing)", re.I)
STUDY = re.compile(r"^(?:hey piper[, ]*)?(?:(?:go|please|can you|could you|i want you to|i'd like you to|you need to|start (?:to )?)\s+)*"
                   r"(?:study|learn(?: everything| all| more)?|read up on|research|teach yourself|get to know|start learning|start studying|keep learning)"
                   r"\s+(?:(?:everything|all|more|as much as you can)\s+)?(?:about|on|up on)?\s*(?P<t>.{2,80}?)[?.!]*$", re.I)
STUDY_PROGRESS = re.compile(r"\b(how(?:'s| is| are) (?:the |your )?(?:study|studies|studying|learning|reading)|what are you (?:studying|learning|reading)|"
                            r"how far (?:are you|along|have you got)|(?:are|have) you (?:done|finished) (?:studying|learning|reading)|"
                            r"what have you (?:studied|learned|learnt|read)|what topics|study (?:progress|status|list))\b", re.I)
STUDY_STOP = re.compile(r"^(?:please\s+)?(?:stop studying|forget (?:what you (?:studied|learned|learnt) about|everything about)|don'?t study)\s+(?P<t>.+?)[?.!]*$", re.I)

def _through(n):
    return f"which is {n['done']} of {n['total']} pages through" if n.get("total") else "which I've only just started"

ACK = re.compile(r"^(?:uh,?\s*|um,?\s*|oh,?\s*)?(?:(?:no|nope|nah)[,.!\s]*)?(?:ok(?:ay)?|cool|great|perfect|lovely|nice|brilliant|cheers|thanks?|thank you|ta|"
                 r"that'?s?,?\s*(?:ok(?:ay)?|fine|perfect|great|good|right|correct|all|it|spot on)|(?:it'?s |all )?(?:fine|good)|all good|got it|i'?m (?:good|fine|done)|"
                 r"nothing(?: else)?|no thanks?|not now|that'?s all|that will do|that'?ll do|you don'?t have to[^?]*|no need[^?]*|"
                 r"no,? (?:that'?s|you don'?t)[^?]*)[\s,.!]*(?:thanks?|thank you|cheers|piper|mate)?[\s,.!]*$", re.I)
_ack_n = [0]
def ack_reply(text):
    """'No, that's perfect' / 'ok thanks': a short reply, without asking the brain (which tends to re-explain everything)."""
    t = text.strip()
    if len(t) > 90 or not ACK.match(t): return None
    _ack_n[0] += 1
    if re.search(r"(?i)\bthank|cheers|\bta\b", t) and not re.match(r"(?i)\W*no\b", t): return ("You're welcome.", "Any time.", "No problem.")[_ack_n[0] % 3]
    return ("Okay.", "Great.", "Sure, no problem.", "Got it.")[_ack_n[0] % 4]

DONT_KNOW = re.compile(r"(?i)\b(i don'?t know|i do not know|i'?m not sure|i am not sure|i don'?t have (?:any |that |the )?(?:information|details|data)|"
                       r"i couldn'?t find|i have no (?:information|idea)|not something i know|no information (?:on|about))\b")
OWN = re.compile(r"(?i)\b(my|mine|our|ours|me|i|i'm|i've|we|us)\b|\b(orders?|customers?|sales|invoices?|emails?|inbox|calendar|followers|password)\b")

def learnable(text):
    """Worth going away to learn: a real factual question about the world, not about Morne, his data or Piper itself."""
    t = text.strip()
    return (len(t.split()) >= 3 and ("?" in t or re.match(r"(?i)(what|when|where|who|why|how|which|is|are|does|do|can|tell me)\b", t))
            and not OWN.search(t) and not META.search(t) and not GREETING.search(t))

def answer_learned(q):
    """Called when a question study finishes: the answer from what was read (None if still unknown)."""
    import brain, knowledge
    reply, _ = brain.chat(q, facts_for(q), owner=CFG["owner"], assistant="Piper", has_db=False, remember=False)
    return None if (not reply or DONT_KNOW.search(reply)) else reply

def learned_lines():
    """Answers ready for questions Piper went away to learn."""
    try:
        import study
        return [f"By the way, earlier you asked \"{q.strip().rstrip('?')}?\" I've looked into it now. {a}" for q, a in study.learned_answers()[:2]]
    except Exception as e: print("learned answers:", e); return []

def study_command(text):
    """Real study commands: starting, progress, stopping. Returns the reply or None."""
    import study
    t = text.strip()
    m = STUDY_STOP.match(t)
    if m: return f"Done, I've dropped {m.group('t')} and its notes." if study.forget(m.group("t")) else f"I wasn't studying {m.group('t')}."
    if STUDY_PROGRESS.search(t): return study.progress_text()
    m = STUDY.match(t)
    if not m or re.match(r"(?i)^(?:something|anything)\b", m.group("t")): return None
    if not study.cfg().get("study", True): return "Study mode is switched off in my settings, so I can't study right now. Turn it on in settings under Study."
    now = study.studying_now()
    topic, st = study.add(m.group("t"), front=True)
    if not topic: return None
    if st == "already": return f"I studied {topic} recently, so I already have notes on it. Ask me anything about it."
    if st == "studying": return f"I'm already studying {topic}. " + study.progress_text()
    if st in ("moved", "queued-already"):
        lead = (f"{topic} was already on my study list, so I've moved it to the front." if st == "moved"
                else f"{topic} is already next on my study list.")
        return lead + (f" I'll start it as soon as I finish {now['topic']}, {_through(now)}."
                       if now and now["topic"].lower() != topic.lower() else " I'm starting it now.")
    when = (f"I'll start right after I finish {now['topic']}, {_through(now)}. Then I'll read about {topic}"
            if now and now["topic"].lower() != topic.lower() else f"Starting now. I'll read about {topic}")
    return (f"{when} in the background, around {study.cfg().get('study_pages', 40)} pages, and keep the notes "
            "so I can answer even offline. Ask me how it's going any time, and I'll tell you when I've finished.")

def _register_learning():
    try:
        import study; study.on_question_done = answer_learned
    except Exception as e: print("study hook:", e)

LOCATION = re.compile(r"^(?:i'?m (?:in|at|staying in|visiting)|set (?:my|your) location to|i live in|we'?re in|change (?:my )?location to)\s+(.+?)[.!?]*$", re.I)

def facts_for(text):
    """Everything Piper knows that might help with this question, kept short enough for small models."""
    import knowledge, wiki
    import memory
    f = []
    mems = memory.relevant(text)
    if mems: f.append("Things you remember about Morne (he told you these):\n" + "\n".join(memory.describe(m) for m in mems))
    try:
        import conversations
        cv = conversations.context(text)
        if cv: f.append(cv[:900])
    except Exception as e: print("conversation search:", e)
    if META.search(text): f.append("YOUR REAL CURRENT STATE (answer self-questions only from this):\n" + system_state())
    import awareness, thoughts
    f.append("WHERE AND WHEN:\n" + awareness.situation())
    ig = read("instagram")
    if ig.get("online") and re.search(r"insta|follower|metricool|siberiawhitefox|\breels?\b", text, re.I):
        lines = ig_lines(ig)
        if re.search(r"when (?:should|to) (?:i )?post|best time", text, re.I) and ig.get("best_time_to_post"):
            lines.append(f"His best time to post is {spoken_time(ig['best_time_to_post'])}.")
        f.append("Instagram figures (report them only, no advice unless he asks for it): " + " ".join(lines))
    if THINKING.search(text):
        f.append("YOUR CURRENT THOUGHTS (real items; talk about the 2 or 3 most useful in your own words, like a person sharing what's on their mind, "
                 "then offer ONE thing you could do. If the curiosity item is there and it feels natural, end by asking it):\n- " + "\n- ".join(thoughts.current(text)))
    elif GREETING.search(text):
        nq = thoughts.next_question()
        if nq: f.append(f"GET TO KNOW MORNE: after greeting him, you may ask this one question if it fits: {nq[1]}")
    s2 = {k: read(k) for k in ("gmail", "calendar", "shopify", "stripe")}
    lines = other_lines(s2) if (GREETING.search(text) or THINKING.search(text) or re.search(
        r"(?i)\b(e-?mails?|mail|inbox|unread|calendar|events?|meetings?|appointments?|schedule|today|tomorrow|plans?|busy|plate|orders?|sales|shop|stripe|payments?)\b", text)) else []
    if lines: f.append("Today from connected accounts: " + " ".join(lines))
    pr = priorities()
    if pr: f.append("Morne's priorities: " + prio_line(pr))
    sch = knowledge.schema()
    if sch: f.append("Database tables (SQLite): " + "; ".join(f"{t['table']}({', '.join(t['columns'])}) {t['rows']} rows" for t in sch))
    ins = knowledge.instructions()
    if ins and sch: f.append("Instructions for the data:\n" + ins[:1200])
    d = knowledge.data_answer(text)
    if d: f.append("From the database: " + d)
    k = knowledge.context(text, 2)   # the 2 best passages: less to read = faster first words
    if k: f.append("From Morne's notes and Piper's knowledge pack (piper-pack files were written into Piper by Claude, mid-2026):\n" + k[:1400])
    try:
        import study
        sc = study.context(text)
        if sc: f.append(sc[:1300])
    except Exception as e: print("study notes:", e)
    try:
        import websearch
        kind = websearch.needs_web(text)
        mine = bool(re.search(r"^\[(?!piper-pack/)", k or "", re.M))   # his own files matched (not the built-in pack)
        own = bool(d) or mine or bool(re.search(r"\b(orders?|customers?|sales|invoices?|tables?|rows?|records?|database|my|our|mine)\b", text, re.I))
        if own and kind != "explicit": kind = "own"   # his own data answered (or is the subject): never send it to the web
        if kind in ("explicit", "current"):   # he asked to search, or the answer changes over time: the web first
            web = websearch.context(text)
            if web: f.append(web)
        w = "" if kind in ("explicit", "own") else wiki.context(text)
        if not w and not kind and wiki.needs_lookup(text):   # a knowledge question my libraries can't answer: try the web
            web = websearch.context(text)
            if web: f.append(web); kind = "fallback"
        if not w and not kind and wiki.needs_lookup(text) and wiki.subject_of(text) and wiki.cfg().get("wiki_online", True):
            on = wiki.search_online(wiki.subject_of(text))
            if on and on.get("text"):
                w = f"[Wikipedia online: {on['title']}] {on['text']}"
                if wiki.cfg().get("wiki_save", True): wiki.save(on["title"], on["text"])
        if w: f.append("Reference libraries:\n" + w[:1500])
    except Exception: pass
    return "\n\n".join(f)[:3800]  # shorter = faster: the model reads all of this before it starts

EMERGENCY = re.compile(r"\b(broke|broken|fractur\w*|bleeding|blood everywhere|chest pain|heart attack|can'?t breathe|cannot breathe|not breathing|"
    r"choking|unconscious|passed out|collapsed|overdos\w*|seizure|stroke|burn(?:ed|t)? (?:badly|myself)|fire|car (?:crash|accident)|"
    r"accident|injur\w*|hurt (?:myself|badly)|cut (?:myself|my (?!hair|nails|fringe|beard|grass|lawn)\w+)|deep cut|(?:fell|fallen) (?:down|over|off)|hit my head|"
    r"allergic reaction|anaphyla\w*|swallowed (?:bleach|pills|battery)|suicid\w*|kill myself|emergency|ambulance|poison\w*)\b", re.I)
EMERGENCY_LINE = "If this is serious or getting worse, call 999 now. On the Isle of Man, 112 works too."
CRISIS = re.compile(r"\b(suicid\w*|kill myself|end my life|want to die|self.?harm)\b", re.I)
_emerg = [0.0]  # when the last emergency was mentioned, so "what do I do?" is understood

def emergency(text):
    """'I broke my leg' is an emergency; 'tell me about fire safety laws' is not."""
    t = text.lower()
    if CRISIS.search(t): return "crisis"
    if re.search(r"\b(there'?s|there is|we have|i have|on) (a )?fire\b|\bfire (in|at|on)\b|\bsmell (gas|smoke)\b|\bhouse is on fire\b", t): return "fire"
    if not EMERGENCY.search(t): return None
    personal = re.search(r"\b(i|i'm|im|my|me|we|we're|our|someone|somebody|he|she|they|he's|she's|mum|dad|wife|husband|son|daughter|friend|baby|child|kid)\b", t)
    reference = re.match(r"^(what|tell me about|explain|define|history|who|when|where|how many|look up|search)\b", t)
    if personal and not (reference and not re.search(r"\b(help|now|just|happened|hurt|bleeding|can'?t)\b", t)): return "injury"
    return None

def emergency_followup(text):
    return time.time() - _emerg[0] < 600 and re.match(r"^(what (do|should|can) i do|help|what now|now what|what next|and then|it hurts|please)\b", text.lower().strip())

FIRST_AID = "Keep still and keep warm. Don't move anyone who might have a head, neck or back injury, and don't put weight on an injured leg or arm. Tell me exactly what happened and I'll walk you through it."
CRISIS_LINES = ["I'm really glad you told me. Please call Samaritans now, free, any time, on 116 123. You can also text SHOUT to 85258.",
                "If you're in danger right now, call 999. You don't have to go through this alone."]

SCREEN = re.compile(r"\b(screen|this|that|these|here|there|where|click|button|menu|window|tab|page|error|message|icon|"
                    r"setting|option|field|box|look(?:ing)? at|see|showing|open|find|which one|how do i|how can i|what does)\b", re.I)

def screen_stream(text, image_b64, w, h):
    """The screen companion. Questions about what's on screen go to the vision model; everything else
    (email, memory, emergencies, general chat) goes through the normal brain, so nothing is lost."""
    import brain
    t = text.lower()
    if emergency(text) or MAIL_CMD.search(t) or brain.fixed_answer(text) or not SCREEN.search(t) or not image_b64:
        for s in ask_stream(text): yield s
        yield {"point": None}; return
    yield STAGE + "Looking at your screen…"
    yield from brain.see_stream(text, image_b64, w, h, owner=CFG["owner"], assistant="Piper")

def ask_stream(text):
    """Yields sentences as they're ready. Quick answers come out whole; the brain streams."""
    import brain, knowledge, wiki, memory
    t = text.lower().strip()
    if not emergency(text):
        for line in learned_lines():
            yield line
            try: memory.remember_turn("(an earlier question I went away to learn)", line)
            except Exception: pass
    quick = brain.fixed_answer(text)
    if not quick and any(k in t for k in ("send", "post it", "publish", "delete")) and not t.startswith(("what", "how", "why", "can")):
        quick = "I draft, you approve. I won't send, post or delete anything on my own."
    if not quick and any(k in t for k in ("brief me", "rundown", "morning brief", "what's on my plate", "update me")): quick = morning_brief(spoken=True)[0]
    m = re.match(r"^(?:look up|search|check|find)\s+(.+?)\s+(?:online|on wikipedia|on the internet)\??$", t)
    if not quick and m: quick = wiki.answer(m.group(1), force_online=True) or "I couldn't find anything on Wikipedia for that."
    if not quick: quick = memory_command(text)
    import calc, study
    study.busy()   # studying pauses while I answer, so answers stay quick
    if not quick:
        import conversations
        if re.search(r"(?i)\bforget (?:all )?(?:our|my) (?:conversations|chats)\b", text):
            conversations.forget_all(); memory.clear_history(); quick = "Done. I've wiped our saved conversations. Your saved memories are still there."
        else: quick = conversations.recall(text)
    if not quick: quick = ack_reply(text)
    if not quick: quick = calc.direct(text)
    if not quick: quick = study_command(text)
    if not quick:
        import maps
        if maps.looks_like(text): yield STAGE + "Checking the map…"
        quick = maps.ask(text)
    import awareness, thoughts
    m = LOCATION.match(t) if not quick else None
    if m:
        try:
            loc = awareness.set_location(m.group(1))
            w = awareness.weather()
            quick = f"Got it, you're in {loc['name']}." + (f" It's {w['now']} there right now." if w else "") if loc else f"I couldn't find {m.group(1)} on the map. Try the town and country."
        except Exception: quick = "I couldn't look that place up just now. Am I online?"
    m = LEARN.match(t) if not quick else None
    if m:
        yield STAGE + "Reading…"
        e = awareness.learn_random(m.group(1))
        if e:
            awareness.mark_shared(e["title"])
            quick = f"I just read about {e['title']}, from {e['source']}. {e['summary']}"
        else: quick = "I couldn't reach anything to read just now. Add some ZIM libraries, or check the internet connection."
    if not quick and MAIL_CMD.search(t):
        yield STAGE + "Checking your inbox…"; quick = mail_command(text)
    if not quick and re.search(r"\b(self[- ]?test|run (?:a )?(?:diagnostic|check)|test yourself|health check)\b", t):
        yield STAGE + "Testing each part…"; quick = self_test()[0]
    if quick:
        yield quick
        try: memory.remember_turn(text, quick)   # quick answers are part of the conversation (and the archive) too
        except Exception as e: print("remember:", e)
        return
    kind = emergency(text) or ("injury" if emergency_followup(text) else None)
    if kind:  # guaranteed safety lines, whatever the model does next
        _emerg[0] = time.time()
        if kind == "crisis":
            for s in CRISIS_LINES: yield s
        elif kind == "fire":
            yield "Get everyone out now, close doors behind you, and call 999 from outside. Don't go back in."; return
        else: yield EMERGENCY_LINE
    got = False
    done = study.news()   # tell him once when a study has finished
    if done: yield done
    yield STAGE + ("Checking myself…" if META.search(text) else "Searching the web…" if __import__("websearch").needs_web(text) else "Searching your notes and libraries…")
    _t = time.time(); facts = facts_for(text); brain.state["facts_s"] = round(time.time() - _t, 2)
    yield STAGE + "Thinking…"
    import memory
    last = (memory.recent_history(n=1) or [{}])[-1].get("content") if memory.recent_history(n=1) else None
    try: memory.notice(text, last); thoughts.take_answer(text)
    except Exception as e: print("memory:", e)
    asked_q = (thoughts.next_question(force=bool(THINKING.search(text))) if (THINKING.search(text) or GREETING.search(text)) else None)
    said = []
    for s in brain.chat_stream(text, facts, owner=CFG["owner"], assistant="Piper",
                               has_db=bool(knowledge.schema()), run_sql=lambda q: knowledge.query(q, 50)):
        got = True; said.append(s); yield s
    if asked_q and any(s.rstrip().endswith("?") for s in said[-2:]): thoughts.asked(*asked_q)
    if said and DONT_KNOW.search(" ".join(said)) and learnable(text) and study.cfg().get("study", True):
        if study.add_question(text):
            now = study.studying_now()
            yield ("I'm off to learn about it now" + (f", right after the question I'm already looking into" if now and now.get("question") else "")
                   + ", and I'll tell you what I find.")
    for e in awareness.recent_learning(3, unshared_only=True):
        if e["title"].lower() in " ".join(said).lower(): awareness.mark_shared(e["title"])
    if not got:
        if kind == "injury": yield FIRST_AID
        elif kind != "crisis": yield (system_state().replace("\n", " ") if META.search(text) else ask_simple(text))

_last_mail = [None, 0]  # the email Piper last touched, so "mark it as unread" means that one

MAIL_CMD = re.compile(r"\b(mark|read (?:me |out )?(?:my |the )?(?:latest |last |newest |first )?(?:e-?mail|mail|message))", re.I)

def mail_command(text):
    """Mark emails read/unread, or read one out. Returns a spoken reply, or None if this isn't a mail command."""
    t = text.lower().strip(" .!?")
    if not MAIL_CMD.search(t) or not re.search(r"\b(e-?mails?|mails?|messages?|inbox)\b|\bas (?:un)?read\b", t): return None
    import connections
    if not read("gmail")["online"]: return "Gmail isn't connected, so I can't do that yet. Add it with the plus button."
    who = re.search(r"\bfrom ([\w .@'-]+?)(?: as (?:un)?read|$| about)", t); who = who.group(1).strip() if who else None
    about = re.search(r"\b(?:about|subject|titled|called) ([\w .'-]+?)(?: as (?:un)?read|$)", t); about = about.group(1).strip() if about else None
    try:
        connections.refresh("gmail")  # fresh list, so "the latest one" really is the latest
        if re.search(r"\bmark\b", t):
            unread = re.search(r"\bas unread\b|\bunread\b(?! ones| emails| mails| messages)", t) and "as read" not in t
            pool = connections.gmail_find(who, about, unread_only=not unread)
            if not (who or about) and re.search(r"\b(it|that|this)\b", t) and _last_mail[0] and time.time() - _last_mail[1] < 600:
                pool = [m for m in connections.gmail_messages() if m.get("uid") == _last_mail[0]]
            elif not (who or about or re.search(r"\b(all|every|everything|them|those|these|inbox)\b", t)):
                pool = pool[:1]  # "mark that email as read" means the newest one
            if not pool:
                return "There are no unread emails matching that." if not unread else "I can't find a read email matching that."
            n = connections.gmail_set_read(pool, read=not unread)
            if n == 1: _last_mail[:] = [pool[0]["uid"], time.time()]
            names = ", ".join(dict.fromkeys(m["from"] for m in pool))[:120]
            return f"Done. Marked {n} email{'s' if n != 1 else ''} as {'unread' if unread else 'read'}" + (f", from {names}." if names else ".")
        pool = connections.gmail_find(who, about, unread_only=False)
        unread_pool = [m for m in pool if m.get("unread")]
        msg = (unread_pool or pool or [None])[0] if not re.search(r"\b(latest|last|newest)\b", t) else (pool or [None])[0]
        if not msg: return "I can't find an email matching that in the last day."
        body = connections.gmail_body(msg); _last_mail[:] = [msg["uid"], time.time()]
        return f"From {msg['from']}, subject: {msg['subject']}. " + (body or "It has no text, probably just attachments.") + " I've marked it as read."
    except Exception as e:
        return "I couldn't reach Gmail just now: " + str(e)[:120]

def ask(text):
    import brain, knowledge, wiki
    t = text.lower().strip()
    fx = brain.fixed_answer(text)
    if fx: return fx
    mc = mail_command(text)
    if mc: return mc
    import calc, maps
    for f in (ack_reply, calc.direct, study_command, maps.ask):
        r = f(text)
        if r: return r
    if any(k in t for k in ("send", "post it", "publish", "delete")) and not t.startswith(("what", "how", "why", "can")):
        return "I draft, you approve. I won't send, post or delete anything on my own."
    if any(k in t for k in ("brief me", "rundown", "morning brief", "what's on my plate", "update me")): return morning_brief(spoken=True)[0]
    m = re.match(r"^(?:look up|search|check|find)\s+(.+?)\s+(?:online|on wikipedia|on the internet)\??$", t)
    if m: return wiki.answer(m.group(1), force_online=True) or "I couldn't find anything on Wikipedia for that."
    reply, backend = brain.chat(text, facts_for(text), owner=CFG["owner"], assistant="Piper",
                                has_db=bool(knowledge.schema()), run_sql=lambda q: knowledge.query(q, 50))
    if reply: return reply
    return ask_simple(text)

def ask_simple(text):
    kind = emergency(text)
    if kind == "crisis": return " ".join(CRISIS_LINES)
    if kind == "fire": return "Get everyone out now, close doors behind you, and call 999 from outside. Don't go back in."
    if kind: return EMERGENCY_LINE + " " + FIRST_AID
    import knowledge, wiki
    t = text.lower().strip()
    m = re.match(r"^(?:look up|search|check|find)\s+(.+?)\s+(?:online|on wikipedia|on the internet)\??$", t)
    if m: return wiki.answer(m.group(1), force_online=True) or "I couldn't find anything on Wikipedia for that."
    if any(k in t for k in ("send", "post it", "publish", "delete")): return "I draft, you approve. I won't send, post or delete anything on my own."
    if re.fullmatch(r"(hi|hello|hey)( piper)?[.!]?", t): return f"Hello, {CFG['owner']}. What can I do for you?"
    if any(k in t for k in ("brief", "rundown", "plate", "update me")): return morning_brief(spoken=True)[0]
    s2 = {k: read(k) for k in SOURCES}
    if any(k in t for k in ("email", "inbox", "mail")) and s2["gmail"]["online"] or any(k in t for k in ("calendar", "meeting", "today", "schedule")) and s2["calendar"]["online"] \
       or any(k in t for k in ("store", "shop", "orders", "sales")) and s2["shopify"]["online"] or any(k in t for k in ("stripe", "payment", "revenue", "money")) and s2["stripe"]["online"]:
        keys = [k for k, words in (("gmail", ("email","inbox","mail")), ("calendar", ("calendar","meeting","today","schedule")), ("shopify", ("store","shop","orders","sales")), ("stripe", ("stripe","payment","revenue","money"))) if any(w in t for w in words)]
        lines = other_lines({k: (s2[k] if k in keys else {"online": False}) for k in ("gmail","calendar","shopify","stripe")})
        if lines: return " ".join(lines)
    ig = read("instagram")
    if "best post" in t or "top post" in t:
        if not ig["online"]: return "Instagram isn't connected yet."
        ps = sorted(ig.get("top_posts") or [], key=lambda p: -(p.get("reach") or 0))[:3]
        if not ps: return "Metricool hasn't imported your post stats yet. Give it a day or two and I'll know which posts work best."
        return "Your top three were the " + ", then the ".join(f"{p['caption'].lower()} with {p['reach']:,} reach" for p in ps) + "."
    if "when" in t and "post" in t: return f"Your best window to post is {spoken_time(ig.get('best_time_to_post'))}." if ig.get("best_time_to_post") else "I don't have enough data yet to say."
    if any(k in t for k in ("instagram", "insta", "followers", "how am i doing", "how's it doing", "numbers", "reach", "stats")): return " ".join(ig_lines(ig))
    if "priorit" in t or "first" in t: return prio_line(priorities())
    a = knowledge.data_answer(text)
    if a: return a
    general = wiki.subject_of(text) and not wiki.PERSONAL.search(wiki.subject_of(text) or "")
    a = (wiki.answer(text) or knowledge.answer(text)) if general else (knowledge.answer(text) or wiki.answer(text))
    if a: return a
    return ("I couldn't find that in your notes, your data or Wikipedia. "
            "Try asking 'what is', 'who is' or 'tell me about', or say 'look up something online'.")

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    print(ask(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else morning_brief()[0])

_register_learning()
