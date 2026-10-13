"""Web search for Piper, through OpenJarvis's search tool (DuckDuckGo: free, no account, no key).

Only the question itself is sent to DuckDuckGo. Turn it off in config.json: "web_search": false
Piper decides *without* the language model whether a question needs the web, so a web answer still
costs just one model call (OpenJarvis's agent mode would cost several, which is too slow on a home PC).
"""
import json, pathlib, re, time, concurrent.futures as cf

ROOT = pathlib.Path(__file__).parent
_pool = cf.ThreadPoolExecutor(max_workers=2)
_cache = {}   # question -> (time, results); the same question within 15 minutes isn't searched twice
state = {"engine": None, "last_s": None, "error": None}

def cfg():
    try: return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception: return {}

def enabled(): return cfg().get("web_search", True)

# Asked for explicitly, or about things that change (news, prices, scores, opening times...)
EXPLICIT = re.compile(r"\b(search(?: the web| online| for)?|google|look (?:it |that )?up online|on the (?:web|internet)|online)\b", re.I)
CURRENT = re.compile(r"\b(latest|news|today'?s|this week|right now|currently|current|recent(?:ly)?|20[2-9]\d|price of|how much (?:is|are|does)|"
                     r"score|who won|results?|opening (?:hours|times)|open (?:now|today)|release date|when does .* (?:come out|start|open)|"
                     r"stock|exchange rate|vs\.?|versus|review)\b", re.I)
PERSONAL = re.compile(r"\b(my|me|i|our|we|piper|you|your)\b", re.I)

def needs_web(text):
    """'explicit' (he asked to search), 'current' (the answer changes over time), or None."""
    if not enabled(): return None
    t = text.strip()
    if EXPLICIT.search(t): return "explicit"
    if CURRENT.search(t) and not re.search(r"\b(my|our) (calendar|email|mail|inbox|diary|notes?|reminders?)\b", t, re.I): return "current"
    return None

def query_of(text):
    """The question, minus 'can you search for' padding."""
    q = re.sub(r"^(?:hey |ok |okay )?piper[, ]*", "", text.strip(), flags=re.I)
    q = re.sub(r"^(?:can you |could you |please |would you )*(?:search(?: the web| online)?(?: for)?|google|look up(?: online)?|find(?: me)? online)\s*", "", q, flags=re.I)
    return q.strip(" ?.!") or text

def _run(q, n):
    """DuckDuckGo search. Direct first (simple, clean links); OpenJarvis's tool only as a backup,
    called in a way that works with old and new OpenJarvis versions."""
    try:
        from ddgs import DDGS
        res = DDGS().text(q, max_results=n) or []
        state["engine"] = "DuckDuckGo"
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "text": r.get("body", "")} for r in res]
    except ImportError: pass
    from openjarvis.tools.web_search import WebSearchTool
    for kw in ({"max_results": n, "engine": "duckduckgo"}, {"max_results": n}, {}):
        try: tool = WebSearchTool(**kw); break
        except TypeError: continue
    else: raise RuntimeError("OpenJarvis web search couldn't start")
    r = tool.execute(query=q)
    state["engine"] = "OpenJarvis"
    if not getattr(r, "success", True): raise RuntimeError(getattr(r, "content", "search failed"))
    return _parse(getattr(r, "content", str(r)))

def _parse(content):
    out = []
    for block in content.split("\n---\n"):
        t = re.search(r"###\s*(.+)", block); u = re.search(r"Source:\s*(\S+)", block); s = re.search(r"Summary:\s*(.+)", block, re.S)
        if t: out.append({"title": t.group(1).strip(), "url": u.group(1) if u else "", "text": (s.group(1).strip() if s else "")[:400]})
    return out

def search(text, n=4, budget=4.0):
    """Top results for a question, or [] if offline / too slow / switched off. Never blocks longer than `budget`."""
    if not enabled(): return []
    q = query_of(text)
    hit = _cache.get(q.lower())
    if hit and time.time() - hit[0] < 900: return hit[1]
    t0 = time.time()
    try:
        res = _pool.submit(_run, q, n).result(timeout=budget)
        state.update(error=None)
    except cf.TimeoutError: res = []; state["error"] = "web search took too long"
    except Exception as e: res = []; state["error"] = str(e)[:120]; print("web search:", e)
    state["last_s"] = round(time.time() - t0, 2)
    if res: _cache[q.lower()] = (time.time(), res)
    return res

def domain(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or ""); return m.group(1) if m else "the web"

def context(text):
    """Facts block for the brain: short snippets, each with where it came from."""
    res = search(text)
    if not res: return ""
    lines = [f"- {r['title']}: {r['text']} (source: {domain(r['url'])})" for r in res]
    return ("WEB SEARCH RESULTS for \"" + query_of(text) + "\" (DuckDuckGo, just now). Answer from these, "
            "name the source site in a few words, and say if they disagree or don't answer it:\n" + "\n".join(lines))
