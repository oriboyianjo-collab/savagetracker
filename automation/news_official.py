#!/usr/bin/env python3
"""
DRAFT v3 FOR ORI'S REVIEW. Not uploaded, not scheduled, uses no token in dry-run.
Official macro releases only: Fed (monetary policy, speeches, testimony), BLS (CPI, jobs, PPI), BEA, EIA.
No general SEC filings. Appends cards to news.json only. Never reports.json, calendar.json or notes.

Default is DRY RUN. A real write needs --write AND APPROVED_BY_ORI=1 AND GITHUB_TOKEN
(the workflow's built-in token). The script commits with the Git Data API (blob, tree, commit,
ref update with force=false), so news.json and the state file land in ONE commit.
"""
import json, os, re, sys, base64, urllib.parse, hashlib, urllib.request, urllib.error
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

REPO = os.environ.get("GITHUB_REPOSITORY", "oriboyianjo-collab/savagetracker")
API = os.environ.get("GITHUB_API", "https://api.github.com")
BRANCH = "main"
NEWS_PATH = "news.json"
STATE_PATH = "automation/news-official-state.json"      # separate file, same commit as the round
LOCAL_STATE, FLAGS_LOG, DRY_REPORT = "state.local.json", "flags_log.jsonl", "dry_run_report.jsonl"
LATE_AFTER_HOURS = 4                                    # Ori 2026-11-22
IL = ZoneInfo("Asia/Jerusalem")
USER_AGENT = "SavageTracker Savtra12@gmail.com"
MAX_TRIES = 5
WORKFLOWS_TO_DISPATCH = ("pages-queued.yml", "push-news.yml")   # names are an assumption, checked at dispatch

SOURCES = [  # (Hebrew name, English name, feed URL, kind)
    ("הפדרל ריזרב", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml", "fed_monetary"),
    ("הפדרל ריזרב", "Federal Reserve", "https://www.federalreserve.gov/feeds/speeches.xml", "fed_speech"),
    ("הפדרל ריזרב", "Federal Reserve", "https://www.federalreserve.gov/feeds/testimony.xml", "fed_testimony"),
    ("לשכת סטטיסטיקת העבודה בארה\"ב", "BLS", "https://www.bls.gov/feed/cpi.rss", "bls_cpi"),
    ("לשכת סטטיסטיקת העבודה בארה\"ב", "BLS", "https://www.bls.gov/feed/empsit.rss", "bls_jobs"),
    ("לשכת סטטיסטיקת העבודה בארה\"ב", "BLS", "https://www.bls.gov/feed/ppi.rss", "bls_ppi"),
    ("לשכת הניתוח הכלכלי בארה\"ב", "BEA", "https://apps.bea.gov/rss/rss.xml", "bea"),
    ("מינהל מידע האנרגיה בארה\"ב", "EIA", "https://www.eia.gov/rss/press_rss.xml", "eia"),
]
KIND_LABEL = {
    "fed_monetary": ("הודעה של הפדרל ריזרב בנושא מדיניות מוניטרית", "הפדרל ריזרב פרסם הודעה בנושא מדיניות מוניטרית."),
    "fed_speech": ("נאום של בכיר בפדרל ריזרב", "פורסם נאום של בכיר בפדרל ריזרב."),
    "fed_testimony": ("עדות של בכיר בפדרל ריזרב", "פורסמה עדות של בכיר בפדרל ריזרב."),
    "bls_cpi": ("מדד המחירים לצרכן (CPI)", "פורסם מדד המחירים לצרכן."),
    "bls_jobs": ("נתוני תעסוקה", "פורסמו נתוני התעסוקה והאבטלה."),
    "bls_ppi": ("מדד המחירים ליצרן (PPI)", "פורסם מדד המחירים ליצרן."),
    "bea": ("פרסום של לשכת הניתוח הכלכלי", "פורסם עדכון מלשכת הניתוח הכלכלי."),
    "eia": ("פרסום של מינהל מידע האנרגיה", "פורסם עדכון ממינהל מידע האנרגיה."),
}
FED_TEMPLATES = [
    (r"FOMC statement", "הודעת ועדת השוק הפתוח (FOMC)", "הפדרל ריזרב פרסם הודעה של ועדת השוק הפתוח בנושא מדיניות הריבית."),
    (r"Minutes of the Federal Open Market Committee", "פרוטוקול ועדת השוק הפתוח (FOMC)", "הפדרל ריזרב פרסם את פרוטוקול דיוני ועדת השוק הפתוח."),
]
MONTHS = {m: h for m, h in zip("January February March April May June July August September October November December".split(),
          "בינואר בפברואר במרץ באפריל במאי ביוני ביולי באוגוסט בספטמבר באוקטובר בנובמבר בדצמבר".split())}
UP = r"(?:increases|rises|advances|moves up|edges up|up)"
DOWN = r"(?:falls|declines|decreases|edges down|down)"

def http(url, headers=None, data=None, method=None):
    h = {"User-Agent": USER_AGENT}; h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=h, data=data, method=method), timeout=120)

def log_flag(item_id, flags, note=""):
    with open(FLAGS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": item_id, "flags": flags, "note": note, "at": dt.datetime.now(IL).isoformat()}, ensure_ascii=False) + "\n")

# ---------------- feeds
def parse_feed(xml_bytes, base=""):
    root, out = ET.fromstring(xml_bytes), []
    for it in root.iter():
        if it.tag.split('}')[-1] not in ("item", "entry"): continue
        g = lambda n: next((c.text or "" for c in it if c.tag.split('}')[-1] == n), "").strip()
        link = g("link") or next((c.get("href") for c in it if c.tag.split('}')[-1] == "link"), "")
        when = g("pubDate") or g("published") or g("updated") or g("date")
        try: t = parsedate_to_datetime(when)
        except Exception:
            try: t = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
            except Exception: t = None
        if t and not t.tzinfo: t = t.replace(tzinfo=dt.timezone.utc)
        link = urllib.parse.urljoin(base, link) if link else link      # EIA gives relative links
        out.append({"title": g("title"), "link": link, "time": t})
    return out

def fetch_source(src):
    """None if blocked or broken. On 403 or an HTML block page: stop that source, no workaround."""
    try: body = http(src[2]).read()
    except urllib.error.HTTPError as ex: log_flag("source:" + src[2], ["source_http_%s" % ex.code]); return None
    except Exception as ex: log_flag("source:" + src[2], ["source_error_" + type(ex).__name__]); return None
    if body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")): log_flag("source:" + src[2], ["source_blocked_html"]); return None
    try: return parse_feed(body, src[2])
    except Exception: log_flag("source:" + src[2], ["feed_parse_error"]); return None

# ---------------- Hebrew from the source title (only numbers that are in the title, no interpretation)
def verb_he(v, up_he, down_he):
    if re.fullmatch(UP, v): return up_he
    if re.fullmatch(DOWN, v): return down_he
    return None

def hebrew_headline_part(kind, title):
    """Returns Hebrew gist with numbers copied from the title, or None if the title does not match a known pattern."""
    if kind in ("bls_cpi", "bls_ppi"):
        name = "מדד המחירים לצרכן (CPI)" if kind == "bls_cpi" else "מדד המחירים ליצרן (PPI)"
        m = re.search(rf"for (?:all items|final demand) ({UP}|{DOWN}) ([\d.]+)% in (\w+)", title)
        if m and m.group(3) in MONTHS:
            return f"{name} {verb_he(m.group(1),'עלה','ירד')} {m.group(2)}% {MONTHS[m.group(3)]}"
        m = re.search(r"for final demand unchanged in (\w+)", title)
        if m and m.group(1) in MONTHS: return f"{name} ללא שינוי {MONTHS[m.group(1)]}"
    if kind == "bls_jobs":
        m = re.search(rf"[Pp]ayroll employment (?:{UP}|{DOWN})(?: by)? ([\d,]+) in (\w+);.*?unemployment rate.*?([\d.]+)%", title)
        if m and m.group(2) in MONTHS:
            up = re.search(DOWN, title.split(m.group(1))[0]) is None
            return f"התעסוקה במשק (Payroll) {'עלתה' if up else 'ירדה'} ב-{m.group(1)} {MONTHS[m.group(2)]}; שיעור האבטלה {m.group(3)}%"
        m = re.search(r"payroll employment \(([+\-−])([\d,]+)\) and unemployment rate \(([\d.]+)%\).*? in (\w+)", title, re.I)
        if m and m.group(4) in MONTHS:
            return f"התעסוקה במשק (Payroll) {'עלתה' if m.group(1)=='+' else 'ירדה'} ב-{m.group(2)} {MONTHS[m.group(4)]}; שיעור האבטלה {m.group(3)}%"
    return None

def build_card(src, e, now_il):
    he, en, _, kind = src
    label, expl = KIND_LABEL[kind]
    for rx, lab, ex in (FED_TEMPLATES if kind == "fed_monetary" else []):
        if re.search(rx, e["title"], re.I): label, expl = lab, ex; break
    gist = hebrew_headline_part(kind, e["title"])
    t = e["time"]
    t_src = t.strftime("%Y-%m-%d %H:%M") if t else ""          # source wall clock, kept for the body text only
    t_il = t.astimezone(IL).strftime("%Y-%m-%d %H:%M") if t else ""      # the app reads this field as phone-local (Israel) time
    off = t.utcoffset() if t else None
    zone = "GMT"
    if off:
        mins = int(off.total_seconds() // 60); sign = "+" if mins > 0 else "-"
        zone = "UTC%s%02d:%02d" % (sign, abs(mins) // 60, abs(mins) % 60)
    late = t is not None and (now_il - t).total_seconds() > LATE_AFTER_HOURS * 3600
    if not gist and kind in ("fed_speech", "fed_testimony") and "," in e["title"]:
        gist = f"{label} ({e['title'].split(',', 1)[0].strip()})"          # speaker's name in parentheses, Hebrew first
    elif not gist and kind == "fed_monetary":
        gist = label
    if not gist:                                                        # no Hebrew-only headline possible: skip, log, leave to the bot
        return None
    head_he = f"{he} ({en}): {gist}"
    head_en = f"{en}: {e['title']}"
    if late: head_he, head_en = "פורסם באיחור | " + head_he, "Published late | " + head_en
    body_he = f"{expl} מועד הפרסום במקור: {t_src} ({zone})."
    body_en = f"{en} published: {e['title']}. Source publication time: {t_src} ({zone})."
    return {
        "מזהה": None, "category": "macro", "חברה": "", "חברה_en": "", "symbols": [], "sectors": [], "tags_version": 1,
        "כותרת": head_he, "כותרת_en": head_en, "summary": head_he, "summary_en": head_en,
        "טקסט": body_he, "טקסט_en": body_en, "קישור": e["link"],
        "מקורות": [{"url": e["link"], "label": f"{he}: ההודעה הרשמית", "label_en": f"{en}: official release"}],
        "תאריך": t_il, "הועלה": now_il.strftime("%Y-%m-%d %H:%M"),
        "_translation": {"en": {"schema_version": 1, "source_hash": hashlib.sha256((head_he + body_he).encode()).hexdigest()}},
    }

# ---------------- duplicates: certain = same link only. Similar headline = possible, goes up, flagged in the log
def norm(x): return re.sub(r"\W+", " ", str(x).lower()).strip()
def jacc(a, b):
    a, b = set(a.split()), set(b.split()); return len(a & b) / max(1, len(a | b))

def link_known(link, known_links): return link in known_links
def possible_dups(card, e, news):
    raw = norm(e["title"])
    return [n["מזהה"] for n in news[-1500:] if raw and (raw in norm(n.get("כותרת_en", "")) or jacc(raw, norm(n.get("כותרת_en", ""))) > 0.6)][:3]

def validate_alone(card):
    try:
        json.loads(json.dumps(card, ensure_ascii=False))
        return all(card.get(k) for k in ("כותרת", "טקסט", "קישור", "הועלה", "תאריך"))
    except Exception: return False

# ---------------- GitHub (Git Data API, exact commit, no force)
class GitHub:
    def __init__(self, token): self.token = token
    def _h(self, extra=None):
        h = {"Accept": "application/vnd.github+json"}
        if self.token: h["Authorization"] = f"Bearer {self.token}"
        h.update(extra or {}); return h
    def call(self, method, path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        h = self._h({"Accept": "application/vnd.github.raw+json"} if raw else {})
        if data: h["Content-Type"] = "application/json"
        r = http(f"{API}/repos/{REPO}{path}", h, data, method)
        b = r.read(); return b if raw else json.loads(b)
    def head(self):
        """Exact head commit, its tree, and blob shas of the two files we use."""
        commit_sha = self.call("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
        tree_sha = self.call("GET", f"/git/commits/{commit_sha}")["tree"]["sha"]
        tree = self.call("GET", f"/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"): raise RuntimeError("tree listing truncated, refusing to continue")
        by = {t["path"]: t["sha"] for t in tree["tree"] if t["type"] == "blob"}
        return commit_sha, by
    def blob_bytes(self, sha): return self.call("GET", f"/git/blobs/{sha}", raw=True)    # content for exactly this sha
    def commit_files(self, parent, files, message):
        tree_entries = []
        for path, content in files.items():
            b = self.call("POST", "/git/blobs", {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": b["sha"]})
        base_tree = self.call("GET", f"/git/commits/{parent}")["tree"]["sha"]
        tree = self.call("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_entries})
        c = self.call("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})
        self.call("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": c["sha"], "force": False})   # not a fast-forward => 422
        return c["sha"]
    def dispatch(self, wf):
        try: self.call("POST", f"/actions/workflows/{wf}/dispatches", {"ref": BRANCH}); return "dispatched"
        except urllib.error.HTTPError as ex: return f"skipped (HTTP {ex.code}; check workflow name and actions: write)"

def detect_format(text, obj):
    for kw in ({"ensure_ascii": False, "separators": (",", ":")}, {"ensure_ascii": False}, {"ensure_ascii": False, "indent": 2}, {"ensure_ascii": False, "indent": 1}):
        if json.dumps(obj, **kw) == text.rstrip("\n"): return kw, text.endswith("\n")
    return None

def safety_check(old, new, n_cards):
    """Ori/programmer item 2: nothing the bot published may disappear."""
    old_ids = [n.get("מזהה") for n in old]; new_ids = [n.get("מזהה") for n in new]
    return (set(old_ids) <= set(new_ids) and len(new) == len(old) + n_cards and new[:len(old)] == old
            and len(set(new_ids)) == len(new_ids))

# ---------------- the round
def run_round(write):
    now_il = dt.datetime.now(IL); now_utc = now_il.astimezone(dt.timezone.utc)
    feeds = []                                               # feeds are fetched ONCE; a retry only reloads the repo
    for src in SOURCES:
        es = fetch_source(src)
        if es is not None: feeds.append((src, es))
    # Burden cut (dry run only): with a local state and no feed link that could become a card, skip loading
    # the 21 MB news.json. Same condition as the card loop below (unseen link, has a time, newer than first run).
    if not write and os.path.exists(LOCAL_STATE):
        st = json.load(open(LOCAL_STATE)); seen = set(st.get("seen_links", []))
        start = dt.datetime.fromisoformat(st["first_run_utc"])
        if not any(e["link"] and e["link"] not in seen and e["time"] and e["time"] > start for _, es in feeds for e in es):
            print(f"round: 0 cards would go up (no new feed link; news.json not downloaded; {len(feeds)}/{len(SOURCES)} feeds read)")
            return
    gh = GitHub(os.environ.get("GITHUB_TOKEN"))      # in dry-run the token is used for READS only (rate limit); nothing commits unless write is True
    for attempt in range(MAX_TRIES):
        head, files = gh.head()
        news_text = gh.blob_bytes(files[NEWS_PATH]).decode("utf-8"); news = json.loads(news_text)
        fmt = detect_format(news_text, news)
        if fmt is None: print("news.json format not reproduced exactly, refusing to continue"); return
        if STATE_PATH in files: state = json.loads(gh.blob_bytes(files[STATE_PATH]).decode("utf-8"))
        elif os.path.exists(LOCAL_STATE) and not write: state = json.load(open(LOCAL_STATE))
        else: state = None
        known = {n.get("קישור") for n in news} | {s.get("url") for n in news for s in n.get("מקורות", [])}
        all_feed_links = [e["link"] for _, es in feeds for e in es if e["link"]]
        out_files, cards = {}, []
        state_before = json.dumps(state, sort_keys=True) if state is not None else None
        if state is None:        # first run: register EVERY existing link, publish nothing (items 3 and 5)
            state = {"first_run_utc": now_utc.isoformat(), "seen_links": list(dict.fromkeys(all_feed_links))}
            print(f"first run: {len(state['seen_links'])} existing links registered, nothing published")
        else:
            start = dt.datetime.fromisoformat(state["first_run_utc"]); seen = set(state["seen_links"])
            old_links = list(state["seen_links"])
            nums = [int(m.group(1)) for n in news if (m := re.match(r"n-(\d+)$", str(n.get("מזהה", ""))))]
            nid = max(nums or [0]) + 1                       # ids are assigned only after the reload
            for src, es in feeds:
                for e in es:
                    if not e["link"] or e["link"] in seen or e["link"] in known or not e["time"] or e["time"] <= start: continue
                    card = build_card(src, e, now_il)
                    if card is None: log_flag("no_id", ["skipped_no_hebrew_headline"], e["link"]); continue
                    card["מזהה"] = f"n-{nid}"; nid += 1
                    if not validate_alone(card): log_flag(card["מזהה"], ["invalid_card_set_aside"], e["link"]); continue
                    pd = possible_dups(card, e, news)
                    if pd: log_flag(card["מזהה"], ["possible_duplicate"], ",".join(pd))
                    cards.append((card, e))
            cards.sort(key=lambda p: (now_utc - p[1]["time"].astimezone(dt.timezone.utc)).total_seconds() > 3600)   # live first
            state["seen_links"] = (old_links + [l for l in dict.fromkeys(all_feed_links) if l not in seen])[-5000:]   # insertion order, oldest trimmed first
        new_cards = [c for c, _ in cards]
        print(f"round: {len(new_cards)} cards would go up")
        for c in new_cards: print(" -", c["מזהה"], c["כותרת"][:100])
        if new_cards:
            new_news = news + new_cards
            if not safety_check(news, new_news, len(new_cards)): print("SAFETY CHECK FAILED: an existing id would be lost, not saving"); return
            print(f"preservation check OK: all {len(news)} existing rows kept unchanged, +{len(new_cards)} new")
            kw, nl = fmt; out_files[NEWS_PATH] = (json.dumps(new_news, **kw) + ("\n" if nl else "")).encode("utf-8")
        if not new_cards and state_before == json.dumps(state, sort_keys=True):
            print("nothing new, no commit"); return
        out_files[STATE_PATH] = (json.dumps(state, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        if not write:
            json.dump(state, open(LOCAL_STATE, "w"))
            with open(DRY_REPORT, "a", encoding="utf-8") as f:
                for c in new_cards: f.write(json.dumps({"at": now_il.isoformat(), "id": c["מזהה"], "כותרת": c["כותרת"], "תאריך": c["תאריך"], "קישור": c["קישור"]}, ensure_ascii=False) + "\n")
            print(f"dry run: would commit {len(out_files[NEWS_PATH]) if NEWS_PATH in out_files else 0} bytes of news.json + state file; nothing written")
            return
        try:
            sha = gh.commit_files(head, out_files, f"news-official: {len(new_cards)} cards"); print("committed", sha)
            if new_cards:
                for wf in WORKFLOWS_TO_DISPATCH: print(wf, gh.dispatch(wf))
            return
        except urllib.error.HTTPError as ex:
            if ex.code in (409, 422): print(f"conflict ({ex.code}), reloading repo state (feeds are not fetched again)"); continue
            raise
    print("gave up after repeated conflicts; nothing written")

if __name__ == "__main__":
    write = "--write" in sys.argv
    if write and (os.environ.get("APPROVED_BY_ORI") != "1" or not os.environ.get("GITHUB_TOKEN")):
        sys.exit("refusing to write: needs Ori's approval flag and the workflow token")
    run_round(write)
