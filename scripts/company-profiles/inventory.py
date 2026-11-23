"""Latest annual-report link per ticker from report-links-all shards."""
from __future__ import annotations

import json
from pathlib import Path

from extract import EXTRACTOR_VERSION

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def infer_form(entry: dict) -> str:
    form = (entry.get("form") or "").upper()
    if form in ANNUAL_FORMS:
        return form
    url = (entry.get("url") or "").lower()
    if "20-f" in url or "form20-f" in url:
        return "20-F/A" if "/a" in form or "20-fa" in url or "20-f_a" in url else "20-F"
    if "40-f" in url or "form40-f" in url:
        return "40-F"
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


def collect(links_dir: Path, rank_path: Path | None = None) -> list[dict]:
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
    if int(existing.get("extractor") or 0) < EXTRACTOR_VERSION:
        return False
    if existing.get("empty"):
        return True
    return bool(existing.get("short_en"))
