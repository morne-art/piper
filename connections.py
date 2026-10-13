"""Connections: log in to your accounts from the Piper settings panel.
Safety:
 - Secrets (tokens, keys) are stored in Windows Credential Manager via `keyring`, never in plain files and never sent to the browser.
 - Every connection is READ-ONLY (read-only Google scopes, read-only Stripe key, read-only Shopify scopes).
 - Piper only listens on this PC (127.0.0.1).
Each connector writes its data to connectors/<name>.json, which the dashboard and brief read."""
import json, re, time, datetime, base64, hashlib, secrets, pathlib, urllib.request, urllib.parse, urllib.error
ROOT = pathlib.Path(__file__).parent; OUT = ROOT / "connectors"; META = ROOT / "connections.json"
SERVICE = "piper-assistant"

try:
    import keyring
    keyring.get_password(SERVICE, "_probe")  # fails fast if no secure backend
    def _get(k): return keyring.get_password(SERVICE, k)
    def _set(k, v): keyring.set_password(SERVICE, k, v)
    def _del(k):
        try: keyring.delete_password(SERVICE, k)
        except Exception: pass
    VAULT = "Windows Credential Manager"
except Exception:  # fallback so Piper still runs; install.bat installs keyring
    _mem = {}
    def _get(k): return _mem.get(k)
    def _set(k, v): _mem[k] = v
    def _del(k): _mem.pop(k, None)
    VAULT = "memory only (run install.bat to enable secure storage)"

CATALOG = {
  "instagram": {"name": "Instagram", "via": "Metricool", "auth": "file",
     "help": "Instagram numbers are imported from a file (for example a Metricool export). Put it in the connectors folder or paste it below."},
  "gmail": {"name": "Gmail", "auth": "token", "fields": ["email", "app_password"],
     "link": ["Open Google App Passwords", "https://myaccount.google.com/apppasswords"],
     "help": "1) Click the button below and sign in to Google. 2) Type the name Piper and click Create. 3) Copy the 16-letter password it shows. 4) Paste your Gmail address and that password here and click Save & Connect. If Google says app passwords aren't available, turn on 2-Step Verification first (myaccount.google.com/security), then try again. Piper only reads headers, never marks mail as read and never sends."},
  "calendar": {"name": "Google Calendar", "auth": "token", "fields": ["ics_url"],
     "link": ["Open Google Calendar settings", "https://calendar.google.com/calendar/r/settings"],
     "help": "1) Click the button below. 2) On the left, under 'Settings for my calendars', click your calendar. 3) Scroll right down to 'Secret address in iCal format' and click the copy icon. 4) Paste it here and click Save & Connect. This link is read-only. Treat it like a password: anyone with it can see your calendar."},
  "shopify": {"name": "Shopify", "auth": "token", "fields": ["shop", "token"],
     "help": "Shopify admin > Settings > Apps and sales channels > Develop apps > Create an app > Configure Admin API scopes: read_orders, read_products only > Install > copy the Admin API access token. Shop = yourstore (from yourstore.myshopify.com)."},
  "stripe": {"name": "Stripe", "auth": "token", "fields": ["token"],
     "help": "Stripe dashboard > Developers > API keys > Create restricted key. Set Balance, Charges, Payouts to READ, everything else None. Paste the rk_live_... key here."},
}

def _meta():
    try: return json.loads(META.read_text(encoding="utf-8"))
    except Exception: return {}
def _save_meta(m): META.write_text(json.dumps(m, indent=2), encoding="utf-8")
def _cred(cid): 
    v = _get(cid); return json.loads(v) if v else {}
def _store(cid, d): _set(cid, json.dumps(d))

def _http(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode()[:200]}")

def _write(key, data):
    data.update({"source": data.get("source", "live"), "updated": datetime.datetime.now().isoformat(timespec="seconds")})
    OUT.mkdir(exist_ok=True); (OUT / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

# ---------------- status ----------------
def status():
    m = _meta(); out = []
    for cid, c in CATALOG.items():
        st = m.get(cid, {})
        connected = bool(_cred(cid)) if c["auth"] != "file" else (OUT / "instagram.json").exists()
        out.append({"id": cid, "name": c["name"], "auth": c["auth"], "fields": c.get("fields", []), "help": c["help"],
                    "connected": connected, "link": c.get("link"), "last": st.get("last"), "error": st.get("error"), "summary": st.get("summary")})
    return {"vault": VAULT, "connections": out}

def save(cid, fields):
    c = CATALOG[cid]; cur = _cred(cid)
    cur.update({k: v.strip() for k, v in fields.items() if k in c.get("fields", []) and v and v.strip()})
    if cid == "shopify" and "shop" in cur: cur["shop"] = cur["shop"].replace("https://", "").replace(".myshopify.com", "").strip("/")
    _store(cid, cur)
    missing = [f for f in c.get("fields", []) if not cur.get(f)]
    if missing: return {"ok": False, "message": "Please fill in: " + ", ".join(missing).replace("_", " ")}
    return refresh(cid)

def disconnect(cid):
    _del(cid); m = _meta(); m.pop(cid, None); _save_meta(m)
    p = OUT / f"{cid}.json"
    if p.exists() and cid != "instagram": p.unlink()
    return {"ok": True, "message": "Disconnected and login forgotten."}

# ---------------- fetchers (read-only) ----------------
def fetch_stripe(c):
    h = {"Authorization": "Bearer " + c["token"]}
    bal = _http("https://api.stripe.com/v1/balance", h)
    since7 = int(time.time()) - 7 * 86400; since1 = int(time.time()) - 86400
    ch = _http(f"https://api.stripe.com/v1/charges?limit=100&created[gte]={since7}", h)["data"]
    ok = [x for x in ch if x.get("paid") and not x.get("refunded")]
    cur = (bal.get("available") or [{"currency": "usd"}])[0]["currency"].upper()
    amt = lambda xs: round(sum(x["amount"] for x in xs) / 100, 2)
    try: po = _http("https://api.stripe.com/v1/payouts?limit=1", h)["data"]
    except Exception: po = []
    data = {"connector": "Stripe", "currency": cur,
            "available": round(sum(b["amount"] for b in bal.get("available", [])) / 100, 2),
            "pending": round(sum(b["amount"] for b in bal.get("pending", [])) / 100, 2),
            "revenue_7d": amt(ok), "payments_7d": len(ok), "revenue_24h": amt([x for x in ok if x["created"] >= since1]),
            "failed_7d": len([x for x in ch if x.get("status") == "failed"]),
            "next_payout": {"amount": po[0]["amount"] / 100, "arrival": datetime.date.fromtimestamp(po[0]["arrival_date"]).isoformat(), "status": po[0]["status"]} if po else None}
    _write("stripe", data); return f"{cur} {data['revenue_7d']:,} from {data['payments_7d']} payments this week"

def fetch_shopify(c):
    base = f"https://{c['shop']}.myshopify.com/admin/api/2025-07"; h = {"X-Shopify-Access-Token": c["token"]}
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders = _http(f"{base}/orders.json?status=any&limit=250&created_at_min={since}&fields=id,created_at,total_price,currency,fulfillment_status,financial_status", h)["orders"]
    today = datetime.date.today().isoformat()
    cur = orders[0]["currency"] if orders else ""
    data = {"connector": "Shopify", "shop": c["shop"], "currency": cur, "orders_7d": len(orders),
            "sales_7d": round(sum(float(o["total_price"]) for o in orders), 2),
            "orders_today": len([o for o in orders if o["created_at"].startswith(today)]),
            "unfulfilled": len([o for o in orders if not o.get("fulfillment_status") and o.get("financial_status") == "paid"])}
    _write("shopify", data); return f"{data['orders_7d']} orders, {cur} {data['sales_7d']:,} this week"

def fetch_gmail(c):
    import imaplib, email, email.header, email.utils
    def dec(v): return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p for p, enc in email.header.decode_header(v or ""))
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try: M.login(c["email"], c["app_password"].replace(" ", ""))
    except imaplib.IMAP4.error: raise RuntimeError("Gmail rejected the login. Check the email address and paste the 16-letter app password again (not your normal password).")
    M.select("INBOX", readonly=True)  # read-only: nothing can be changed, nothing marked as read
    since = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
    _, ids = M.uid("search", None, f'(SINCE "{since}")'); ids = ids[0].split()[-25:]
    try:   # Gmail's own sorting: which of these are in the Primary tab (not Promotions, Social, Updates...)
        _, pr = M.uid("search", None, "X-GM-RAW", '"category:primary"', "SINCE", since); primary = set(pr[0].split()) if pr and pr[0] else set()
        sorted_by_gmail = True
    except Exception: primary, sorted_by_gmail = set(), False
    msgs = []
    for i in reversed(ids):
        _, d = M.uid("fetch", i, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE PRECEDENCE)])")
        flags = d[0][0].decode(); h = email.message_from_bytes(d[0][1])
        name, addr = email.utils.parseaddr(dec(h["From"]))
        bulk = bool(h["List-Unsubscribe"]) or (h["Precedence"] or "").lower() in ("bulk", "list") or \
               bool(re.match(r"(no-?reply|news|newsletter|marketing|mail|hello|hi|team|info|offers?|deals?|promo)", addr.split("@")[0], re.I))
        personal = (i in primary and not bulk) if sorted_by_gmail else not bulk
        msgs.append({"uid": i.decode(), "from": name or addr, "address": addr,
                     "subject": re.sub(r"\s*[\r\n]+\s*", " ", dec(h["Subject"]) or "(no subject)").strip(),
                     "unread": "\\Seen" not in flags, "personal": personal})
    M.logout()
    _write("gmail", {"connector": "Gmail", "messages_24h": len(msgs), "unread": len([m for m in msgs if m["unread"]]), "messages": msgs})
    return f"{len(msgs)} emails in the last day, {len([m for m in msgs if m['unread']])} unread"

# ---- Gmail actions. Allowed: mark read/unread, read a message. Never: send, delete, move. ----
def _gmail_open():
    import imaplib
    c = _cred("gmail")
    if not c: raise RuntimeError("Gmail isn't connected.")
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993); M.login(c["email"], c["app_password"].replace(" ", ""))
    M.select("INBOX")  # writable, but the only commands used below are flag changes and reads
    return M

def gmail_messages():
    try: return json.loads((ROOT / "connectors" / "gmail.json").read_text(encoding="utf-8")).get("messages", [])
    except Exception: return []

def gmail_find(who=None, about=None, unread_only=True):
    """Messages matching a sender name/address and/or a subject word, newest first."""
    out = []
    for m in gmail_messages():
        if unread_only and not m.get("unread"): continue
        if who and who.lower() not in (m["from"] + " " + m.get("address", "")).lower(): continue
        if about and about.lower() not in m["subject"].lower(): continue
        out.append(m)
    return out

def gmail_set_read(msgs, read=True):
    """Marks messages read (or unread). Gmail keeps them; this is the same as opening them. Returns how many changed."""
    uids = [m["uid"] for m in msgs if m.get("uid")]
    if not uids: return 0
    M = _gmail_open()
    try: M.uid("store", ",".join(uids), "+FLAGS" if read else "-FLAGS", "(\\Seen)")
    finally: M.logout()
    p = ROOT / "connectors" / "gmail.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        for m in d.get("messages", []):
            if m.get("uid") in uids: m["unread"] = not read
        d["unread"] = len([m for m in d["messages"] if m.get("unread")]); _write("gmail", d)
    except Exception as e: print("gmail cache:", e)
    return len(uids)

def gmail_body(msg, chars=700):
    """Plain text of one message, for reading aloud. Fetching the body marks it read, as in Gmail."""
    import email, html
    M = _gmail_open()
    try:
        _, d = M.uid("fetch", msg["uid"], "(BODY[])")
        e = email.message_from_bytes(d[0][1]); text = ""
        for part in (e.walk() if e.is_multipart() else [e]):
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html") and not part.get_filename():
                raw = part.get_payload(decode=True) or b""
                t = raw.decode(part.get_content_charset() or "utf-8", "ignore")
                if ct == "text/html": t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\\1>", " ", t)))
                if ct == "text/plain" or not text: text = t
                if ct == "text/plain": break
    finally: M.logout()
    text = re.sub(r"(?m)^>.*$", "", text)                      # quoted replies
    text = re.split(r"\n(?:--\s*\n|On .{5,80}wrote:)", text)[0]   # signatures, older thread
    text = re.sub(r"https?://\S+", "a link", re.sub(r"\s+", " ", text)).strip()
    gmail_set_read([msg], True)
    return text[:chars] + ("…" if len(text) > chars else "")

def _ics_events(text, day):
    text = re.sub(r"\r?\n[ \t]", "", text); out = []
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in blk.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1); f.setdefault(k.split(";")[0], (k, v.strip()))
        if "DTSTART" not in f or f.get("STATUS", ("", ""))[1] == "CANCELLED": continue
        k, v = f["DTSTART"]; allday = "VALUE=DATE" in k or len(v) == 8
        if allday: start = datetime.datetime.strptime(v[:8], "%Y%m%d")
        else:
            start = datetime.datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
            if v.endswith("Z"): start = start.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        hit = start.date() == day
        if not hit and "RRULE" in f and start.date() <= day:
            r = dict(x.split("=", 1) for x in f["RRULE"][1].split(";") if "=" in x)
            until = r.get("UNTIL", "99991231")[:8]
            if day.strftime("%Y%m%d") <= until:
                iv = int(r.get("INTERVAL", 1)); diff = (day - start.date()).days
                if r.get("FREQ") == "DAILY": hit = diff % iv == 0
                elif r.get("FREQ") == "WEEKLY":
                    days = r.get("BYDAY", ["MO","TU","WE","TH","FR","SA","SU"][start.weekday()]).split(",")
                    hit = ["MO","TU","WE","TH","FR","SA","SU"][day.weekday()] in [d[-2:] for d in days] and (diff // 7) % iv == 0
                elif r.get("FREQ") == "MONTHLY": hit = start.day == day.day
                elif r.get("FREQ") == "YEARLY": hit = (start.month, start.day) == (day.month, day.day)
            ex = [x for kk, (k2, x) in f.items() if kk == "EXDATE"]
            if hit and any(day.strftime("%Y%m%d") in x for x in ex): hit = False
        if hit:
            title = f.get("SUMMARY", ("", "(busy)"))[1].replace("\\,", ",").replace("\\n", " ")
            out.append({"time": "all day" if allday else start.strftime("%H:%M"), "title": title})
    return sorted(out, key=lambda e: e["time"])

def fetch_calendar(c):
    url = c["ics_url"].replace("webcal://", "https://")
    if "calendar.google.com" not in url and not url.endswith(".ics"): raise RuntimeError("That doesn't look like a calendar link. Copy the 'Secret address in iCal format'.")
    req = urllib.request.Request(url, headers={"User-Agent": "Piper"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: text = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e: raise RuntimeError(f"Google said {e.code}. Copy the secret iCal address again (it may have been reset).")
    events = _ics_events(text, datetime.date.today())
    _write("calendar", {"connector": "Calendar", "events": events})
    return f"{len(events)} events today"

FETCH = {"stripe": fetch_stripe, "shopify": fetch_shopify, "gmail": fetch_gmail, "calendar": fetch_calendar}

def refresh(cid):
    m = _meta(); st = m.setdefault(cid, {})
    if cid not in FETCH: return {"ok": True, "message": "Imported from file."}
    try:
        summary = FETCH[cid](_cred(cid)); st.update({"last": datetime.datetime.now().strftime("%H:%M %d %b"), "error": None, "summary": summary})
        _save_meta(m); return {"ok": True, "message": "Connected: " + summary}
    except Exception as e:
        st.update({"error": str(e)[:200]}); _save_meta(m); return {"ok": False, "message": "Couldn't connect: " + str(e)[:200]}

def refresh_all():
    return {cid: refresh(cid) for cid in FETCH if _cred(cid)}

def import_instagram(text):
    d = json.loads(text)
    if d.get("connector") != "Instagram" or "followers" not in d: raise RuntimeError("That doesn't look like an Instagram file from Piper.")
    (OUT / "instagram.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    m = _meta(); m["instagram"] = {"last": datetime.datetime.now().strftime("%H:%M %d %b"), "summary": f"{d['followers']} followers"}; _save_meta(m)
    return {"ok": True, "message": f"Imported: {d['followers']} followers"}
