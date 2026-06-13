#!/usr/bin/env python3
"""
scripts/check_cron.py — read-only diagnostic for the all-MLB cron (P0 verify).

Answers the two open P0 cron-verification checkboxes (BACKLOG.md → "Verify next
— all-MLB cron") without touching the live app:

  1. Did the daily 17:00-UTC cron run clean? Dumps the last N days of the
     `cache:cron-summary:{date}` blobs the cron writes to KV and flags each
     against the backlog's health thresholds (mlb.ok / espn.ok / hitter.ok,
     hittersToday ~250–350, nonzero locked + actualsStored).

  2. Is the session-42 proj2h baseline→factor-adjusted upgrade firing? Scans
     `proj2h:` locks for the same days and buckets them into:
       - baseline  : cron all-MLB lock (model.allMlb, empty factor stack) that
                     has NOT yet been upgraded — expected for not-yet-started
                     games; a lingering count on a *past* date means the Hitters
                     page never upgraded those roster locks (the bad case).
       - upgraded  : page upgraded the cron baseline (model.upgradedFrom=allMlb)
                     with a non-empty factor stack — the upgrade fired ✓.
       - native    : a factor-adjusted lock with no allMlb marker (the page won
                     the NX race, e.g. a FA / non-cron hitter).

It is strictly READ-ONLY: only Upstash REST GET / SCAN, never SET.

Usage:
    export KV_REST_API_URL=...           # same creds as api/kv.py
    export KV_REST_API_TOKEN=...
    python scripts/check_cron.py                    # last 7 days
    python scripts/check_cron.py --days 14          # last 14 days
    python scripts/check_cron.py aaron-judge ...    # also drill into slugs
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

import requests

URL = os.environ.get("KV_REST_API_URL", "")
TOKEN = os.environ.get("KV_REST_API_TOKEN", "")

OK = "✓"    # ✓
WARN = "⚠"  # ⚠

# Backlog thresholds for a healthy hitter pass.
HITTERS_MIN, HITTERS_MAX = 250, 350


def _cmd(*args):
    """Run one Upstash REST command (POST [arg, ...]) and return its result."""
    r = requests.post(
        URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=list(args),
        timeout=25,
    )
    r.raise_for_status()
    return r.json().get("result")


def _scan(pattern: str):
    """Yield every key matching pattern via SCAN (cursor-safe, never blocks KV)."""
    cursor = "0"
    while True:
        cursor, keys = _cmd("SCAN", cursor, "MATCH", pattern, "COUNT", 500)
        for k in keys:
            yield k
        if cursor == "0":
            break


def _get_json(key: str):
    """GET a key and parse it as JSON, or None if missing / unparseable."""
    import json
    val = _cmd("GET", key)
    if val is None:
        return None
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return None


def _flag(cond: bool) -> str:
    return OK if cond else WARN


def dump_summaries(dates: list) -> None:
    """Print the cron-summary health line for each date in the window."""
    print(f"\n{'='*72}\ncron-summary (cache:cron-summary:{{date}})\n{'='*72}")
    for date in dates:
        blob = _get_json(f"cache:cron-summary:{date}")
        if blob is None:
            print(f"  {date}  {WARN} (no summary — cron did not run / not written)")
            continue

        mlb = blob.get("mlb") or {}
        espn = blob.get("espn") or {}
        hit = blob.get("hitter") or {}

        overall = _flag(blob.get("ok"))
        print(f"  {date}  {overall} overall")

        # Pitcher + ESPN passes (overall ok is gated on these two).
        print(f"      mlb   {_flag(mlb.get('ok'))} ok={mlb.get('ok')}"
              + (f"  error={mlb.get('error')}" if mlb.get("error") else ""))
        print(f"      espn  {_flag(espn.get('ok'))} ok={espn.get('ok')}"
              + (f"  error={espn.get('error')}" if espn.get("error") else ""))

        # Hitter pass — the heaviest, isolated pass (the one PR #154 broke).
        h_today = hit.get("hittersToday")
        h_locked = hit.get("locked")
        h_actuals = hit.get("actualsStored")
        in_range = isinstance(h_today, int) and HITTERS_MIN <= h_today <= HITTERS_MAX
        print(f"      hit   {_flag(hit.get('ok'))} ok={hit.get('ok')}"
              + (f"  error={hit.get('error')}" if hit.get("error") else ""))
        print(f"            {_flag(in_range)} hittersToday={h_today} "
              f"(expect {HITTERS_MIN}-{HITTERS_MAX})  "
              f"{_flag(bool(h_locked))} locked={h_locked}  "
              f"{_flag(bool(h_actuals))} actualsStored={h_actuals}  "
              f"actualsDates={hit.get('actualsDates')}")


def classify_proj2h(rec: dict) -> str:
    """Bucket a proj2h lock by its upgrade state (see module docstring)."""
    model = rec.get("model") or {}
    factors = rec.get("factors") or []
    if model.get("upgradedFrom") == "allMlb":
        return "upgraded"
    if model.get("allMlb"):
        return "baseline"
    if factors:
        return "native"
    return "other"


def spot_check_proj2h(dates: list) -> None:
    """Tally proj2h lock upgrade-states per date across the whole keyspace."""
    print(f"\n{'='*72}\nproj2h upgrade spot-check (proj2h:*:{{date}})\n{'='*72}")
    print("  baseline = cron lock not yet upgraded | upgraded = page upgraded it "
          f"{OK} | native = page-only lock")
    for date in dates:
        counts = {"baseline": 0, "upgraded": 0, "native": 0, "other": 0}
        total = 0
        for key in _scan(f"proj2h:*:{date}"):
            rec = _get_json(key)
            if rec is None:
                continue
            counts[classify_proj2h(rec)] += 1
            total += 1
        if total == 0:
            print(f"  {date}  (no proj2h locks)")
            continue
        # A lingering baseline count on a past date = upgrade never fired there.
        note = (f"  {WARN} {counts['baseline']} still baseline"
                if counts["baseline"] else "")
        print(f"  {date}  total={total}  upgraded={counts['upgraded']}  "
              f"baseline={counts['baseline']}  native={counts['native']}  "
              f"other={counts['other']}{note}")


def drill_slugs(slugs: list, dates: list) -> None:
    """Print the full proj2h record for specific player slugs across the window."""
    print(f"\n{'='*72}\nproj2h drill-down\n{'='*72}")
    win = set(dates)
    for slug in slugs:
        print(f"  {slug}:")
        found = False
        for key in _scan(f"proj2h:*:{slug}:*"):
            date = key.rsplit(":", 1)[-1]
            if date not in win:
                continue
            rec = _get_json(key)
            if rec is None:
                continue
            found = True
            model = rec.get("model") or {}
            print(f"    {date}  {classify_proj2h(rec)}  fpts={rec.get('fpts')}  "
                  f"base={rec.get('base')}  factors={len(rec.get('factors') or [])}  "
                  f"allMlb={model.get('allMlb')}  upgradedFrom={model.get('upgradedFrom')}")
        if not found:
            print(f"    (no proj2h locks in the last {len(dates)} days)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only all-MLB cron diagnostic.")
    ap.add_argument("--days", type=int, default=7,
                    help="how many days back to inspect (default 7)")
    ap.add_argument("slugs", nargs="*",
                    help="optional player slugs to drill into (e.g. aaron-judge)")
    args = ap.parse_args()

    if not URL or not TOKEN:
        print("ERROR: set KV_REST_API_URL and KV_REST_API_TOKEN "
              "(the same creds api/kv.py uses).", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(args.days)]

    print(f"all-MLB cron diagnostic — last {args.days} days "
          f"(through {dates[0]} UTC), READ-ONLY")
    dump_summaries(dates)
    spot_check_proj2h(dates)
    if args.slugs:
        drill_slugs(args.slugs, dates)
    print(f"\n{'='*72}\nDone. Paste this back and I'll read it against the P0 "
          "thresholds.")


if __name__ == "__main__":
    main()
