from __future__ import annotations

import argparse
import csv
import json
import os
import re
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
    p.add_argument("--in-dir", dest="in_dir", default="output",
                   help="Input directory containing donors-*.csv (must contain 'eid' and name columns)")
    p.add_argument("--out-dir", dest="out_dir", default="by-donor-output",
                   help="Output directory for per-party CSVs")
    p.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between requests")
    p.add_argument("--timeout", type=int, default=15000, help="Playwright response wait timeout in ms")
    p.add_argument("--limit", type=int, default=0, help="Limit to N eids (0 = all) for testing")
    p.add_argument("--headful", action="store_true", help="Run browser in headful mode (for debugging)")
    args = p.parse_args(argv)

    in_dir = args.in_dir
    out_dir = args.out_dir
    if not os.path.isdir(in_dir):
        print(f"Input directory not found: {in_dir}", file=sys.stderr)
        return 2

    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # Read all donors-*.csv files in in_dir and build mappings:
    # - eid_to_group: eid -> group_key
    # - group_info: group_key -> representative fields and donationsToCampaign
    eid_to_group: Dict[str, Tuple[str, str, str, str, str, str]] = {}
    group_info: Dict[Tuple[str, str, str, str, str, str], dict] = {}

    csv_paths = sorted([str(p) for p in Path(in_dir).glob("donors-*.csv")])
    if not csv_paths:
        print(f"No donors-*.csv files found in {in_dir}", file=sys.stderr)
        return 0

    with sync_playwright() as pplay:
        browser = pplay.chromium.launch(headless=not args.headful)
        context = browser.new_context()
        page = context.new_page()

        # Process each candidate file independently
        for csv_path in csv_paths:
            base = os.path.basename(csv_path)
            candidate = os.path.splitext(base)[0].replace("donors-", "")
            candidate_out_dir = os.path.join(out_dir, candidate)
            Path(candidate_out_dir).mkdir(parents=True, exist_ok=True)

            # build eid -> group and group info for this file
            eid_to_group: Dict[str, Tuple[str, str, str, str, str, str]] = {}
            group_info: Dict[Tuple[str, str, str, str, str, str], dict] = {}
            with open(csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    eid = (row.get("eid") or "").strip()
                    if not eid:
                        continue
                    entityName = (row.get("entityName") or "").strip()
                    first = (row.get("firstName") or "").strip()
                    middle = (row.get("middleInitial") or "").strip()
                    last = (row.get("lastName") or "").strip()
                    city = (row.get("city") or "").strip()
                    state = (row.get("state") or "").strip()
                    donations_text = (row.get("donationsToCampaign") or "").strip()

                    group_key = (entityName, first, middle, last, city, state)
                    eid_to_group[eid] = group_key
                    if group_key not in group_info:
                        donations_val = 0.0
                        try:
                            donations_val = float(re.sub(r"[^0-9.-]", "", donations_text)) if donations_text else 0.0
                        except Exception:
                            donations_val = 0.0
                        group_info[group_key] = {
                            "entityName": entityName,
                            "first": first,
                            "middle": middle,
                            "last": last,
                            "city": city,
                            "state": state,
                            "donationsToCampaign": donations_val,
                            "eids": set([eid]),
                        }
                    else:
                        group_info[group_key]["eids"].add(eid)

            all_eids = list(eid_to_group.keys())
            if args.limit and args.limit > 0:
                eids = all_eids[: args.limit]
            else:
                eids = all_eids

            # accumulator: party -> group_key -> amount
            party_map: Dict[str, Dict[Tuple[str, str, str, str, str, str], float]] = defaultdict(lambda: defaultdict(float))

            for idx, eid in enumerate(eids, start=1):
                print(f"[{candidate}] [{idx}/{len(eids)}] Fetching eid={eid}")
                data = run_playwright_for_eid(page, eid, timeout=args.timeout)
                records = data.get("records") or []
                for rec in records:
                    party = rec.get("Party", {}).get("Party")
                    amt = parse_float(rec.get("Total_$", {}).get("Total_$"))
                    if not party or amt <= 0:
                        continue
                    group_key = eid_to_group.get(eid)
                    if not group_key:
                        continue
                    party_map[party][group_key] += amt

                time.sleep(args.sleep)

            # write per-party files for this candidate
            for party, person_map in party_map.items():
                safe = party.lower().replace(" ", "-")
                out_path = os.path.join(candidate_out_dir, f"{safe}.csv")
                with open(out_path, "w", newline="", encoding="utf-8") as outf:
                    writer = csv.writer(outf)
                    writer.writerow(["entityName", "firstName", "lastName", "amount", "donationsToCampaign"])
                    for group_key, amt in sorted(person_map.items(), key=lambda kv: -kv[1]):
                        info = group_info.get(group_key, {})
                        entityName = info.get("entityName", "")
                        first = info.get("first", "")
                        last = info.get("last", "")
                        donations_val = info.get("donationsToCampaign", 0.0)
                        if float(amt).is_integer():
                            amt_str = str(int(amt))
                        else:
                            amt_str = f"{amt:.2f}"
                        if float(donations_val).is_integer():
                            donations_str = str(int(donations_val))
                        else:
                            donations_str = f"{donations_val:.2f}"
                        writer.writerow([entityName, first, last, amt_str, donations_str])
                print(f"Wrote {out_path} ({len(person_map)} rows)")

        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
