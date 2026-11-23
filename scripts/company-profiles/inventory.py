"""Latest annual-report link per ticker from report-links-all shards."""
from __future__ import annotations

import json
import re
from pathlib import Path

from extract import EXTRACTOR_VERSION, is_boilerplate_text

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def infer_form(entry: dict) -> str:
    form = (entry.get("form") or "").upper()
    if form in ANNUAL_FORMS:
        return form
    url = (entry.get("url") or "").lower()
    # Donnelley / issuer names often use 20f without a hyphen: d20f.htm, x20f.htm, form20f_2025.htm
    if re.search(r"20-?f|form20-?f|x20f|_20f|d20f", url):
        return "20-F/A" if re.search(r"20-?f/?a|20fa|20-?f_a|x20fa", url) or form.endswith("/A") else "20-F"
    if re.search(r"40-?f|form40-?f|x40f|_40f|d40f", url):
        return "40-F/A" if re.search(r"40-?f/?a|40fa|x40fa", url) or form.endswith("/A") else "40-F"
    return "10-K"


def is_annual(entry: dict) -> bool:
    if not entry.get("url"):
        return False
    slot = entry.get("slot") or ""
    form = (entry.get("form") or "").upper()
    if form in ANNUAL_FORMS:
        return True
    if slot.endswith("-FY") or slot.endswith("FY"):
        return True
    url = (entry.get("url") or "").lower()
    return any(x in url for x in ("form10-k", "10-k", "form20-f", "20-f", "form40-f", "40-f")) and "10-q" not in url


def latest_annual(ledger: list) -> dict | None:
    fys = [x for x in ledger or [] if is_annual(x)]
    if not fys:
        return None
    return max(fys, key=lambda x: (x.get("filing_date") or "", x.get("period_end") or "", x.get("slot") or ""))


def load_rank_order(path: Path) -> list[str]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    ranked = data.get("ranked") or []
    out = []
    for row in ranked:
        if isinstance(row, (list, tuple)) and row:
            out.append(str(row[0]).upper())
        elif isinstance(row, str):
            out.append(row.upper())
    return out


def _variants(sym: str) -> set[str]:
    s = sym.upper()
    return {s, s.replace("-", "."), s.replace(".", "-")}


def _pass_form(pass_dir: Path | None, symbol: str, annual: dict) -> str:
    """Read the form type from report-pass-state when the links shard omitted it."""
    if not pass_dir or not pass_dir.is_dir():
        return ""
    files = list(pass_dir.glob(f"{symbol}.*.json"))
    if not files:
        return ""
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return ""
    row = data.get("row") or data
    url = (annual.get("url") or "").rstrip("/").lower()
    slot = annual.get("slot") or ""
    for e in row.get("ledger") or []:
        eu = (e.get("url") or "").rstrip("/").lower()
        form = (e.get("form") or "").upper()
        if form and (eu == url or (slot and e.get("slot") == slot)):
            return form
    return ""


def collect(links_dir: Path, rank_path: Path | None = None, pass_dir: Path | None = None) -> list[dict]:
    """Return one record per ticker that has a usable annual URL, market-cap first."""
    by_sym = {}
    for fp in sorted(links_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbols = data.get("symbols") or {}
        if not symbols and "ledger" in data:
            symbols = {data.get("symbol") or fp.name.split(".")[0]: data}
        for sym, rec in symbols.items():
            annual = latest_annual(rec.get("ledger") or [])
            if not annual:
                continue
            key = str(sym).upper()
            if not annual.get("form"):
                pf = _pass_form(pass_dir, key, annual)
                if pf:
                    annual = {**annual, "form": pf}
            by_sym[key] = {
                "symbol": key,
                "cik": (rec.get("cik") or ""),
                "url": annual["url"],
                "filing_date": annual.get("filing_date") or "",
                "period_end": annual.get("period_end") or "",
                "slot": annual.get("slot") or "",
                "form": infer_form(annual),
                "doc_sha256": annual.get("body_sha256") or "",
            }
    order = load_rank_order(rank_path) if rank_path else []
    index = {s: i for i, s in enumerate(order)}
    # Map hyphen/dot variants onto rank positions.
    for i, s in enumerate(order):
        for v in _variants(s):
            index.setdefault(v, i)
    items = list(by_sym.values())
    items.sort(key=lambda r: (index.get(r["symbol"], 10**9), r["symbol"]))
    return items


def profile_path(out_dir: Path, symbol: str) -> Path:
    return out_dir / f"{symbol.upper()}.json"


def _same_filing(existing: dict, rec: dict) -> bool:
    if rec.get("doc_sha256") and existing.get("doc_sha256") == rec["doc_sha256"]:
        return True
    return (
        existing.get("url") == rec.get("url")
        and existing.get("filing_date") == rec.get("filing_date")
        and existing.get("form") == rec.get("form")
    )


def is_current(existing: dict | None, rec: dict) -> bool:
    """True when we already stored this filing with the current extractor.

    Empty stubs and earlier extractor versions are retried once the extractor
    is bumped, so a table-of-contents miss can be filled later. The same
    version of a recorded empty extract is not fetched again.
    """
    if not existing:
        return False
    if not _same_filing(existing, rec):
        return False
    short = (existing.get("short_en") or "").strip()
    # Keep a good description even if the extractor is later bumped.
    if short and not is_boilerplate_text(short):
        return True
    # Retry empty stubs and preamble-only fills when the extractor is newer.
    if existing.get("empty") and int(existing.get("extractor") or 0) >= EXTRACTOR_VERSION:
        return True
    return False
