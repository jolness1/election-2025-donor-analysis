from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple, Optional

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print("Playwright is required. Install with: pip install playwright && playwright install", file=sys.stderr)
    raise

# use aggregated donors to get donation totals by party from followthemoney.org
def parse_float(s: Optional[str]) -> float:
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return 0.0


def run_playwright_for_eid(page, eid: str, timeout: int = 15000) -> dict:
    """Load the entity page for eid and capture the aaengine JSON response.

    Returns the parsed JSON dict or empty dict on failure.
    """
    url = f"https://www.followthemoney.org/entity-details?eid={eid}"
    try:
        with page.expect_response(lambda resp: "/aaengine/aafetch.php" in resp.url, timeout=timeout) as resp_info:
            page.goto(url)
        resp = resp_info.value
        txt = resp.text()
        if not txt:
            return {}
        return json.loads(txt)
    except Exception as e:
        print(f"Playwright fetch failed for eid={eid}: {e}", file=sys.stderr)
        return {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aggregate FTM party totals per donor from eids CSV using Playwright")
    p.add_argument("--in", dest="in_csv", default="output/donors-kisa-davison.csv",
                   help="Input donors CSV (must contain 'eid' and name columns)")
    p.add_argument("--out-dir", dest="out_dir", default="by-donor-output/kisa-davison",
                   help="Output directory for per-party CSVs")
    p.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between requests")
    p.add_argument("--timeout", type=int, default=15000, help="Playwright response wait timeout in ms")
    p.add_argument("--limit", type=int, default=0, help="Limit to N eids (0 = all) for testing")
    p.add_argument("--headful", action="store_true", help="Run browser in headful mode (for debugging)")
    args = p.parse_args(argv)

    in_csv = args.in_csv
    out_dir = args.out_dir
    if not os.path.exists(in_csv):
        print(f"Input CSV not found: {in_csv}", file=sys.stderr)
        return 2

    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # Read donors file and build eid -> set of person tuples
    eid_to_people: Dict[str, set[Tuple[str, str, str]]] = {}
    with open(in_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            eid = (row.get("eid") or "").strip()
            if not eid:
                continue
            entityName = (row.get("entityName") or "").strip()
            first = (row.get("firstName") or "").strip()
            last = (row.get("lastName") or "").strip()
            eid_to_people.setdefault(eid, set()).add((entityName, first, last))

    if not eid_to_people:
        print("No eids found in input CSV.", file=sys.stderr)
        return 0

    # accumulator: party -> (entityName, first, last) -> amount
    party_map: Dict[str, Dict[Tuple[str, str, str], float]] = defaultdict(lambda: defaultdict(float))

    eids = list(eid_to_people.keys())
    if args.limit and args.limit > 0:
        eids = eids[: args.limit]

    with sync_playwright() as pplay:
        browser = pplay.chromium.launch(headless=not args.headful)
        context = browser.new_context()
        page = context.new_page()

        for idx, eid in enumerate(eids, start=1):
            print(f"[{idx}/{len(eids)}] Fetching eid={eid}")
            data = run_playwright_for_eid(page, eid, timeout=args.timeout)
            records = data.get("records") or []
            for rec in records:
                party = rec.get("Party", {}).get("Party")
                amt = parse_float(rec.get("Total_$", {}).get("Total_$"))
                if not party or amt <= 0:
                    continue
                people = eid_to_people.get(eid, set())
                for person in people:
                    party_map[party][person] += amt

            time.sleep(args.sleep)

        browser.close()

    # write per-party files
    for party, person_map in party_map.items():
        safe = party.lower().replace(" ", "-")
        out_path = os.path.join(out_dir, f"{safe}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as outf:
            writer = csv.writer(outf)
            writer.writerow(["entityName", "firstName", "lastName", "amount"])
            for (entityName, first, last), amt in sorted(person_map.items(), key=lambda kv: -kv[1]):
                if float(amt).is_integer():
                    amt_str = str(int(amt))
                else:
                    amt_str = f"{amt:.2f}"
                writer.writerow([entityName, first, last, amt_str])
        print(f"Wrote {out_path} ({len(person_map)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
