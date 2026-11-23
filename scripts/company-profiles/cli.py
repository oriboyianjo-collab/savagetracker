#!/usr/bin/env python3
"""Fill company-profiles/ from stored annual-report links. SEC rules as in the workflow comment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from extract import extract_profile_text  # noqa: E402
from sec_http import HardStop, SecClient, TransientDefer  # noqa: E402
from inventory import collect, is_current, profile_path  # noqa: E402
from translate import Translator  # noqa: E402

SAFE_SYM = __import__("re").compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def status_path(out_dir: Path) -> Path:
    return out_dir / "status.json"


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--out", default="")
    p.add_argument("--budget-sec", type=int, default=int(os.environ.get("COMPANY_PROFILES_BUDGET_SEC", "1500")))
    p.add_argument("--max-fetch", type=int, default=int(os.environ.get("COMPANY_PROFILES_MAX_FETCH", "250")))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-translate", action="store_true")
    p.add_argument("--symbols", default="", help="Comma-separated symbol list (test/manual)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root)
    out_dir = Path(args.out) if args.out else root / "company-profiles"
    links_dir = root / "report-links-all"
    rank_path = root / "mcap-rank.json"
    status = load_json(status_path(out_dir)) or {}
    report = {
        "filled_this_run": 0,
        "skipped_current": 0,
        "pending_after": 0,
        "hard_stop": False,
        "transient_defer": False,
        "remaining": 0,
        "total_with_link": 0,
        "already_filled": 0,
        "errors": [],
    }

    pause_until = status.get("hard_stop_until") or ""
    if pause_until:
        try:
            until = datetime.strptime(pause_until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < until:
                report["hard_stop"] = True
                report["errors"].append(f"SEC pause until {pause_until}")
                print(json.dumps(report, ensure_ascii=False))
                return 20
        except ValueError:
            pass

    items = collect(links_dir, rank_path)
    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        items = [x for x in items if x["symbol"] in want]
    report["total_with_link"] = len(items)

    todo = []
    filled = 0
    for rec in items:
        if not SAFE_SYM.match(rec["symbol"]):
            continue
        existing = load_json(profile_path(out_dir, rec["symbol"]))
        if is_current(existing, rec):
            filled += 1
            report["skipped_current"] += 1
            continue
        todo.append(rec)
    report["already_filled"] = filled
    report["remaining"] = len(todo)

    if not todo:
        write_json(status_path(out_dir), {
            "updated": now_iso(),
            "filled": filled,
            "pending": 0,
            "hard_stop_until": None,
            "last_error": "",
        })
        print(json.dumps(report, ensure_ascii=False))
        return 0

    translator = None
    if not args.no_translate and not args.dry_run:
        translator = Translator()
        try:
            translator.load()
            print(f"translator={translator.backend}", file=sys.stderr)
        except Exception as e:
            print(f"translator unavailable ({e}); Hebrew will be filled on a later run", file=sys.stderr)
            translator = None

    client = SecClient()
    deadline = time.monotonic() + max(30, args.budget_sec)
    fetched = 0
    exit_code = 0
    body_cache = {}

    def translate_pair(short_en, full_en, existing=None):
        if not translator:
            return (existing or {}).get("short_he") or "", (existing or {}).get("full_he") or ""
        try:
            short_he = translator.translate(short_en) if short_en else ""
            full_he = translator.translate(full_en) if full_en and full_en != short_en else short_he
            return short_he, full_he
        except Exception as e:
            report["errors"].append(f"translate: {e}")
            return (existing or {}).get("short_he") or "", (existing or {}).get("full_he") or ""

    for rec in todo:
        if fetched >= args.max_fetch or time.monotonic() >= deadline:
            break
        existing = load_json(profile_path(out_dir, rec["symbol"]))
        try:
            if rec["url"] in body_cache:
                body = body_cache[rec["url"]]
            else:
                body = client.get(rec["url"])
                body_cache[rec["url"]] = body
        except HardStop as e:
            report["hard_stop"] = True
            report["errors"].append(str(e))
            exit_code = 20
            until = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
            status_update = {
                "updated": now_iso(),
                "filled": filled + report["filled_this_run"],
                "pending": len(todo) - fetched,
                "hard_stop_until": until,
                "last_error": str(e),
            }
            if not args.dry_run:
                write_json(status_path(out_dir), status_update)
            break
        except TransientDefer as e:
            report["transient_defer"] = True
            report["errors"].append(str(e))
            exit_code = 10
            break
        fetched += 1
        try:
            text = extract_profile_text(body, rec["form"])
        except Exception as e:
            report["errors"].append(f"{rec['symbol']} extract: {e}")
            continue
        if not text["short_en"]:
            report["errors"].append(f"{rec['symbol']}: no Item 1/4 text")
            # Record a stub so we don't refetch the same empty doc every run.
            if not args.dry_run:
                write_json(profile_path(out_dir, rec["symbol"]), {
                    "symbol": rec["symbol"],
                    "form": rec["form"],
                    "url": rec["url"],
                    "filing_date": rec["filing_date"],
                    "period_end": rec["period_end"],
                    "doc_sha256": rec["doc_sha256"] or hashlib.sha256(body).hexdigest(),
                    "short_en": "",
                    "full_en": "",
                    "short_he": "",
                    "full_he": "",
                    "empty": True,
                    "extracted_at": now_iso(),
                })
            continue
        sha = rec["doc_sha256"] or hashlib.sha256(body).hexdigest()
        short_he, full_he = translate_pair(text["short_en"], text["full_en"], existing)
        profile = {
            "symbol": rec["symbol"],
            "form": rec["form"],
            "url": rec["url"],
            "filing_date": rec["filing_date"],
            "period_end": rec["period_end"],
            "doc_sha256": sha,
            "short_en": text["short_en"],
            "full_en": text["full_en"],
            "short_he": short_he,
            "full_he": full_he,
            "extracted_at": now_iso(),
        }
        if not args.dry_run:
            write_json(profile_path(out_dir, rec["symbol"]), profile)
        report["filled_this_run"] += 1

    remaining = 0
    for rec in todo:
        existing = load_json(profile_path(out_dir, rec["symbol"]))
        if not is_current(existing, rec):
            remaining += 1
    # also count items not yet reached
    report["remaining"] = remaining
    report["already_filled"] = filled + report["filled_this_run"]
    if not args.dry_run:
        prev_stop = status.get("hard_stop_until") if report["hard_stop"] else None
        write_json(status_path(out_dir), {
            "updated": now_iso(),
            "filled": report["already_filled"],
            "pending": remaining,
            "hard_stop_until": prev_stop if report["hard_stop"] else None,
            "last_error": (report["errors"][-1] if report["errors"] else ""),
            "translator": getattr(translator, "backend", None),
        })
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
