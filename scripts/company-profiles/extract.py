"""Turn an annual-report HTML/text body into Item 1 / Item 4 plain text."""
from __future__ import annotations

import re
from html import unescape

# Bump when the extractor changes so stored stubs and weak fills are retried once.
EXTRACTOR_VERSION = 6

FOOTER_RE = re.compile(
    r"^(Table of Contents|TABLE OF CONTENTS|"
    r".{0,80}\| 20\d{2} Form 10-K \| \d+|"
    r".{0,80}\| 20\d{2} Form 20-F \| \d+|"
    r".{0,80}Form 10-K \| \d+\s*$)$",
    re.I,
)
ITEM1_START = re.compile(
    r"Item\s+1(?:\s|\.|:|–|—|-)+(?:Description of\s+)?Business\b",
    re.I,
)
# Some 10-Ks put a few words or line breaks between "Item 1." and "Business".
ITEM1_LOOSE = re.compile(
    r"Item\s+1(?:\s|\.|:|–|—|-)+.{0,200}?Business\b",
    re.I | re.S,
)
ITEM1A_START = re.compile(r"Item\s+1A(?:\s|\.|:)+Risk Factors\b", re.I)
ITEM1B_START = re.compile(r"Item\s+1B\b", re.I)
ITEM2_START = re.compile(r"Item\s+2(?:\s|\.|:)+(Properties|Unregistered)\b", re.I)
ITEM4_START = re.compile(
    r"Item\s+4(?:\s|\.|:|–|—|-)+(Information on\b|Business(?: and General Information)?)\b",
    re.I,
)
ITEM4A_OR_5 = re.compile(r"Item\s+(4A|5)(?:\s|\.|:)+", re.I)
# Some 20-Fs use "ITEM 4." alone as a heading.
ITEM4_BARE = re.compile(r"Item\s+4\.(?:\s|$)", re.I)
ITEM5_BARE = re.compile(r"Item\s+5\.(?:\s|$)", re.I)

_IX_DROP = re.compile(
    r"(?is)<(?:ix:header|ix:hidden|ix:references|ix:resources|ix:exclude)\b[^>]*>.*?"
    r"</(?:ix:header|ix:hidden|ix:references|ix:resources|ix:exclude)>",
)

# Minimum body length that distinguishes the real item from a table-of-contents stub.
_MIN_BODY = 300


def html_to_text(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = _IX_DROP.sub(" ", raw)
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", raw)
    raw = re.sub(r"(?is)</(?:div|p|tr|h[1-6]|li|table|section|article|br)>", "\n", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = unescape(raw)
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if FOOTER_RE.match(s):
            continue
        lines.append(s)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text


def _search(pattern, text, start=0):
    m = pattern.search(text, start)
    return m.start() if m else -1


def _next_end(text: str, start: int, end_pats: list) -> int:
    end = -1
    for pat in end_pats:
        e = _search(pat, text, start + 8)
        if e >= 0 and (end < 0 or e < end):
            end = e
    return end


def _best_span(text: str, start_pats: list, end_pats: list) -> str:
    """Pick the real item, not the table-of-contents entry.

    TOC rows match the same heading regex but the span to the next item is only a
    few words. The actual section is the longest span that also has a following
    end heading, when one exists.
    """
    starts: list[int] = []
    for pat in start_pats:
        starts.extend(m.start() for m in pat.finditer(text))
    starts = sorted(set(starts))
    if not starts:
        return ""

    scored = []
    for start in starts:
        end = _next_end(text, start, end_pats)
        chunk = text[start:] if end < 0 else text[start:end]
        scored.append((len(chunk), end >= 0, -start, chunk))

    with_end = [s for s in scored if s[1] and s[0] >= _MIN_BODY]
    pool = with_end or [s for s in scored if s[0] >= _MIN_BODY] or scored
    pool.sort(reverse=True)
    return pool[0][3].strip()


def _item1_body(text: str) -> str:
    body = _best_span(text, [ITEM1_START], [ITEM1A_START, ITEM1B_START, ITEM2_START])
    if len(body) >= _MIN_BODY:
        return body
    loose = _best_span(text, [ITEM1_LOOSE], [ITEM1A_START, ITEM1B_START, ITEM2_START])
    return loose if len(loose) > len(body) else body


def _item4_body(text: str) -> str:
    body = _best_span(text, [ITEM4_START, ITEM4_BARE], [ITEM4A_OR_5, ITEM5_BARE])
    return _prefer_business_overview(body) if body else ""


def _prefer_business_overview(body: str) -> str:
    """Start at 'B. Business Overview' / Item 4.B when that subsection exists."""
    m = re.search(
        r"(?im)^(?:item\s+4\.?\s*)?(?:b\.?|4\.b\.?|[b4]\.\s*)\s*business overview\b",
        body,
    )
    if not m:
        m = re.search(
            r"(?im)(?:item\s+4\.?\s*b\b|4\.b\b).{0,80}business overview",
            body,
        )
    if not m:
        m = re.search(r"(?i)(?:^|\n)\s*(?:[b4]\.?\s*)?business overview(?:\s+of the company)?\b", body)
    # Do not start at a later "Overview — Regulation" cross-reference.
    if m and re.search(r"(?i)overview\s+[—\-].*regulation", body[m.start(): m.start() + 80]):
        m = None
    if not m:
        return body
    chunk = body[m.start():].strip()
    end = _next_end(chunk, 0, [
        re.compile(r"(?im)^(?:item\s+4\.?\s*)?(?:c\.?|4\.c\.?|[c4]\.?\s*)\s*organizational structure\b"),
        re.compile(r"(?im)^(?:item\s+4\.?\s*c\b|4\.c\b)\b"),
        re.compile(r"(?im)^(?:item\s+4\.?\s*)?(?:d\.?|[d4]\.?\s*)\s*property, plants and equipment\b"),
        ITEM4A_OR_5,
        ITEM5_BARE,
    ])
    if end > 0:
        chunk = chunk[:end].strip()
    return chunk if len(chunk) >= 80 else body


def item_body(text: str, form: str = "10-K") -> str:
    form = (form or "10-K").upper()
    foreign = form.startswith("20-F") or form.startswith("40-F")
    item1 = _item1_body(text)
    item4 = _item4_body(text)
    if foreign:
        # Prefer a substantial Item 4, otherwise any Item 1 (or the longer of the two).
        if len(item4) >= _MIN_BODY or (item4 and len(item4) >= len(item1)):
            return item4
        return item1
    if len(item1) >= _MIN_BODY or (item1 and len(item1) >= len(item4)):
        return item1
    # Many 20-F / 40-F URLs look like a 10-K (tsm-20251231.htm). If Item 1 is
    # missing, try Item 4 so foreign issuers still get a description.
    return item4


_HEADING = re.compile(
    r"^(Item\s+\d+[A-Z]?(?:\s|\.|:).{0,80}|[A-Z]\.\s+\S.{0,80}|"
    r"Company Background|Business Overview|Overview|Our Business|"
    r"History and Development of the Company|Products|Services|"
    r"Segments|Markets and Distribution|Competition|Seasonality|"
    r"Human Capital|Intellectual Property|Available Information|"
    r"Organizational Structure|Property, Plants and Equipment|"
    r"Information about (?:our|the) Executive Officers.*|"
    r"Human Capital Management.*)$",
    re.I,
)


def _is_noise(p: str) -> bool:
    if _HEADING.match(p):
        return True
    # TOC bullets or heading + page number, e.g. "Intellectual Property 14"
    if not re.search(r"[.?!](?:\s|$)", p) and re.search(r"\s\d{1,3}$", p) and len(p) < 100:
        return True
    if re.match(r"^[•·‣]\s+", p) and not re.search(r"[.?!](?:\s|$)", p):
        return True
    return False


def _is_prose(p: str) -> bool:
    if len(p) < 40 or _is_noise(p):
        return False
    if re.search(r"[.?!](?:\s|$)", p):
        return True
    return len(p) >= 120 and bool(re.search(r"[a-z]{3,}", p))


_BOILER_RE = re.compile(
    r"(?i)("
    r"forward[- ]looking statement"
    r"|private securities litigation reform act"
    r"|documents incorporated herein by reference"
    r"|this annual report on form\s*(?:10-?k|20-?f|40-?f)"
    r"|in this annual report on form\s*(?:10-?k|20-?f|40-?f)"
    r"|throughout this annual report"
    r"|as used (?:herein|in this annual report)"
    r"|unless (?:otherwise expressly stated or )?the context otherwise requires"
    r"|unless the context requires otherwise"
    r"|except as (?:otherwise )?(?:noted by the context|the context otherwise may require)"
    r"|the following description of the business should be read in conjunction"
    r"|amounts reported in this annual report"
    r"|and analysis of financial condition and results of operations"
    r"|cautionary (?:note|statement) regarding forward"
    r"|speak only as of the date (?:hereof|of this)"
    r"|actual results (?:and outcomes )?may differ materially"
    r"|voluntary disclosures in this report"
    r"|may not necessarily be .{0,2}material.{0,2}"
    r"|legal and commercial name is"
    r"|our principal executive office is located"
    r"|information contained on our website is not incorporated"
    r"|methodological considerations"
    r"|not independently verify"
    r"|disclosures based on any standards"
    r"|regulatory inquir(?:y|ies)"
    r"|rectification orders"
    r"|involutionary competition"
    r"|regulations on network data security"
    r"|any information required by this item\s+10"
    r"|section 16\(a\) of the exchange act"
    r"|included under the caption .{0,80}proxy statement"
    r"|for additional information regarding the effects"
    r"|for more details"
    r"|could adversely affect (?:its|the company.?s|our) financial condition"
    r"|taxing authorities"
    r"|global minimum tax"
    r"|all other information required by this item"
    r"|materially and adversely affect our business and results of operations"
    r")"
)

# Opening sentences that only define “we/our/the Company” in this report.
_DEF_RE = re.compile(
    r"(?i)^("
    r"as used (?:herein|in this)"
    r"|unless (?:otherwise|the context)"
    r"|except as the context"
    r"|throughout this annual report"
    r"|the terms? .{0,80} (?:used herein|mean|refer to)"
    r"|when we refer to"
    r"|references (?:herein|in this annual report)"
    r"|the term [\"“]fiscal year[\"”]"
    r"|when used in this report"
    r"|unless we state otherwise"
    r"|references to\b"
    r"|in this (?:annual )?report, the (?:words|terms)"
    r")"
)


def _sentences(text: str) -> list[str]:
    # Do not split on abbreviations such as Inc. or Ltd.
    # Keep the punctuation so joining sentences does not drop periods.
    parts = re.split(r"(?<=[a-z0-9)])([.?!])(?=\s+[A-Z])", text.strip())
    out = []
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        punct = ""
        if i + 1 < len(parts) and parts[i + 1] in ".?!":
            punct = parts[i + 1]
            i += 2
        else:
            i += 1
        if not chunk:
            continue
        if punct and not chunk.endswith(punct):
            chunk += punct
        out.append(chunk)
    return out


_DROPPED_PERIOD = re.compile(
    r"[a-z0-9)] ("
    r"We|Our|In|These|This|It|As|Additionally|Furthermore|Also|"
    r"The (?:Company|Group|Corporation)|"
    r"Information on|Consumers|Sellers"
    r")\b"
)


def _starts_mid_sentence(s: str) -> bool:
    """True for a leftover clause, but not brand names such as eToro or iShares."""
    s = (s or "").lstrip()
    if not s or not s[0].islower():
        return False
    if re.match(r"^[a-z][A-Z]", s):
        return False
    return True


def has_dropped_periods(text: str) -> bool:
    """True when preamble-stripping removed sentence periods (e.g. 'company We are')."""
    s = (text or "").strip()
    if not s:
        return False
    return bool(_DROPPED_PERIOD.search(s))


def _is_boiler_sentence(s: str) -> bool:
    if _BOILER_RE.search(s) or _DEF_RE.search(s):
        return True
    if re.match(r"(?i)^annual report on form\s*(?:10-?k|20-?f)", s):
        return True
    # Leftover clause after a false split on "Inc."
    if re.match(r"(?i)^(?:and its subsidiaries|unless the context (?:otherwise )?(?:indicates|requires|indicates otherwise))", s):
        return True
    if _starts_mid_sentence(s) and re.search(r"(?i)unless the context|subsidiaries", s):
        return True
    # Section cross-references like “Overview — Regulation — …”
    if s.count("—") >= 2 and re.search(r"(?i)regulation|risk factor|item\s+\d", s):
        return True
    if re.search(r"(?i)^our history and structure\b", s) and re.search(r"(?i)legal and commercial name", s):
        return True
    if _starts_mid_sentence(s):
        return True
    if re.search(r"(?i)^(?:any information required by this item|all other information required by this item|10-k for additional information)", s):
        return True
    if re.match(r"(?i)^(?:moreover|further|in addition),", s) and re.search(
        r"(?i)taxing authorities|tax rules|regulatory|inquir|investigation", s
    ):
        return True
    if re.match(r"(?i)^we are required to obtain", s):
        return True
    if re.search(r"(?i)could adversely affect .{0,40}(?:financial condition|operating results)", s) and re.search(r"(?i)laws or regulations", s):
        return True
    return False


def is_boilerplate_text(text: str) -> bool:
    """True when a stored short description is only a preamble / FLS warning."""
    s = (text or "").strip()
    if not s:
        return False
    # Starts mid-sentence or with a preamble: retry even if a later sentence is useful.
    if _starts_mid_sentence(s):
        return True
    if has_dropped_periods(s):
        return True
    sents = _sentences(s) or [s]
    if sents and _is_boiler_sentence(sents[0]):
        return True
    return all(_is_boiler_sentence(x) for x in sents)


def _strip_leading_boilerplate(p: str) -> str:
    sents = _sentences(p)
    if not sents:
        return p
    i = 0
    while i < len(sents) and _is_boiler_sentence(sents[i]):
        i += 1
    return " ".join(sents[i:]).strip()


def paragraphs(item_text: str) -> list[str]:
    """Split Item text into body paragraphs, skipping section headings."""
    # Headings are often on their own line but not separated by a blank line
    # once tags are stripped, which would otherwise glue "Company Background"
    # onto the first sentence.
    isolated = []
    for ln in item_text.splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        if s and (_HEADING.match(s) or _is_noise(s)):
            isolated.append("")
            isolated.append(s)
            isolated.append("")
        elif s and len(s) >= 60 and re.search(r"[.?!]$", s):
            # Filings often put each sentence in its own div, which would
            # otherwise become one long paragraph.
            isolated.append("")
            isolated.append(s)
            isolated.append("")
        else:
            isolated.append(ln)
    item_text = "\n".join(isolated)
    parts = re.split(r"\n\s*\n", item_text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        p = p.replace("®", "").replace("™", "").replace("℠", "")
        p = re.sub(r"\s+", " ", p).strip()
        if not p or len(p) < 40:
            continue
        if _is_noise(p):
            continue
        # Drop leftover "Item 1. Business" prefixes on the first line.
        p = re.sub(r"^Item\s+\d+[A-Z]?(?:\s|\.|:|–|—|-)+\S+(?:\s+\S+){0,6}\s*", "", p, flags=re.I).strip()
        p = re.sub(r"^(?:Our History and Structure|Business Overview(?: of the Company)?)\s+", "", p, flags=re.I).strip()
        p = _strip_leading_boilerplate(p)
        if not _is_prose(p):
            continue
        out.append(p)
    return out



_BUSINESS_LEAD = re.compile(
    r"(?i)^(?:"
    # The company verb must start the sentence, so “in which we operate” does not match.
    r"we (?!are required|may be|could be|will rely)"
    r"(?:are|operate|provide|design|develop|manufacture|offer|sell|make|serve|create|build|focus|combine|believe|seek|have|maintain)"
    r"|the company (?:is|designs|develops|operates|provides|manufactures|offers|sells)"
    r"|.{0,80}?\bis an? (?:leading|global|provider|manufacturer|developer|technology|semiconductor|industry|digital|enterprise|supplier|dedicated)"
    r"|mission is"
    r"|was founded"
    r"|as a .{0,60}, we "
    r")"
)


def _looks_like_business_overview(p: str) -> bool:
    first = (_sentences(p) or [p])[0]
    if _is_boiler_sentence(first):
        return False
    return bool(_BUSINESS_LEAD.search(first))


def _start_at_business(paras: list[str]) -> list[str]:
    """Skip leftover legal/regulatory paragraphs until a business overview."""
    for i, p in enumerate(paras):
        if _looks_like_business_overview(p):
            return paras[i:]
    return paras


def _cut_sentences(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text.strip()
    window = text[: max_chars + 1]
    # Prefer a sentence end in the last third of the window.
    ends = [m.end() for m in re.finditer(r"(?<=[a-z0-9\)\"'])\.(?:\s|$)", window)]
    if ends and ends[-1] >= max_chars * 0.45:
        return window[: ends[-1]].strip()
    space = window.rfind(" ")
    return (window[:space] if space > 0 else window[:max_chars]).strip()


def short_and_full(paras: list[str], short_max=520, full_max=1800) -> tuple[str, str]:
    if not paras:
        return "", ""
    # Prefer a complete opening sentence when it already describes the business.
    # Filings often glue a fiscal-year sentence onto the same div.
    opening = paras[0]
    if re.search(r"(?i)\bfiscal year\b", opening):
        opening = re.split(r"(?i)(?<=[.?!])\s+(?=\S[^.]{0,40}\bfiscal year\b)", opening, maxsplit=1)[0].strip()
    short = _cut_sentences(opening, short_max)
    first_end = [m.end() for m in re.finditer(r"(?<=[a-z0-9\)\"'])\.(?:\s|$)", short)]
    if first_end and first_end[0] >= 120:
        short = short[: first_end[0]].strip()
    elif len(short) < 160 and len(paras) > 1 and not re.search(r"(?i)\bfiscal year\b", paras[1]):
        short = _cut_sentences(short + " " + paras[1], short_max)
    buf = []
    used = 0
    for p in paras:
        if used and used + len(p) + 1 > full_max:
            break
        buf.append(p)
        used += len(p) + 1
        if used >= full_max * 0.85:
            break
    full = " ".join(buf).strip()
    if len(full) > full_max:
        full = _cut_sentences(full, full_max)
    if len(full) < len(short):
        full = short
    return short, full


def extract_profile_text(raw, form="10-K"):
    text = html_to_text(raw)
    body = item_body(text, form)
    paras = _start_at_business(paragraphs(body))
    short, full = short_and_full(paras)
    return {"item_text": body, "paragraphs": paras, "short_en": short, "full_en": full}
