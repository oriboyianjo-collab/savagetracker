"""Turn an annual-report HTML/text body into Item 1 / Item 4 plain text."""
from __future__ import annotations

import re
from html import unescape

FOOTER_RE = re.compile(
    r"^(Table of Contents|TABLE OF CONTENTS|"
    r".{0,80}\| 20\d{2} Form 10-K \| \d+|"
    r".{0,80}\| 20\d{2} Form 20-F \| \d+|"
    r".{0,80}Form 10-K \| \d+\s*$)$",
    re.I,
)
ITEM1_START = re.compile(r"Item\s+1(?:\s|\.|:)+Business\b", re.I)
ITEM1A_START = re.compile(r"Item\s+1A(?:\s|\.|:)+Risk Factors\b", re.I)
ITEM1B_START = re.compile(r"Item\s+1B\b", re.I)
ITEM2_START = re.compile(r"Item\s+2(?:\s|\.|:)+(Properties|Unregistered)\b", re.I)
ITEM4_START = re.compile(
    r"Item\s+4(?:\s|\.|:)+(Information on the Company|Business(?: and General Information)?)\b",
    re.I,
)
ITEM4A_OR_5 = re.compile(r"Item\s+(4A|5)(?:\s|\.|:)+", re.I)
# Some 20-Fs use "ITEM 4." alone as a heading.
ITEM4_BARE = re.compile(r"Item\s+4\.(?:\s|$)", re.I)
ITEM5_BARE = re.compile(r"Item\s+5\.(?:\s|$)", re.I)


def html_to_text(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
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


def item_body(text: str, form: str = "10-K") -> str:
    form = (form or "10-K").upper()
    if form.startswith("20-F") or form.startswith("40-F"):
        start = _search(ITEM4_START, text)
        if start < 0:
            start = _search(ITEM4_BARE, text)
        end = -1
        if start >= 0:
            end = _search(ITEM4A_OR_5, text, start + 8)
            if end < 0:
                end = _search(ITEM5_BARE, text, start + 8)
        if start < 0:
            # Fall back to Item 1 Business if a 40-F uses domestic headings.
            start = _search(ITEM1_START, text)
            end = _search(ITEM1A_START, text, start + 8) if start >= 0 else -1
    else:
        start = _search(ITEM1_START, text)
        end = -1
        if start >= 0:
            end = _search(ITEM1A_START, text, start + 8)
            if end < 0:
                end = _search(ITEM1B_START, text, start + 8)
            if end < 0:
                end = _search(ITEM2_START, text, start + 8)
    if start < 0:
        return ""
    chunk = text[start:] if end < 0 else text[start:end]
    return chunk.strip()


_HEADING = re.compile(
    r"^(Item\s+\d+[A-Z]?(?:\s|\.|:).{0,80}|[A-Z]\.\s+\S.{0,80}|"
    r"Company Background|Business Overview|Overview|Our Business|"
    r"History and Development of the Company|Products|Services|"
    r"Segments|Markets and Distribution|Competition|Seasonality|"
    r"Human Capital|Intellectual Property|Available Information|"
    r"Organizational Structure|Property, Plants and Equipment)$",
    re.I,
)


def paragraphs(item_text: str) -> list[str]:
    """Split Item text into body paragraphs, skipping section headings."""
    parts = re.split(r"\n\s*\n", item_text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        p = p.replace("®", "").replace("™", "").replace("℠", "")
        p = re.sub(r"\s+", " ", p).strip()
        if not p or len(p) < 40:
            continue
        if _HEADING.match(p):
            continue
        # Drop leftover "Item 1. Business" prefixes on the first line.
        p = re.sub(r"^Item\s+\d+[A-Z]?(?:\s|\.|:)+\S+(?:\s+\S+){0,6}\s*", "", p, flags=re.I).strip()
        if len(p) < 40:
            continue
        out.append(p)
    return out


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
    short = _cut_sentences(paras[0], short_max)
    # If the opening sentence is very short, add the next paragraph (still capped).
    if len(short) < 180 and len(paras) > 1:
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
    paras = paragraphs(body)
    short, full = short_and_full(paras)
    return {"item_text": body, "paragraphs": paras, "short_en": short, "full_en": full}
