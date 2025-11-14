from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, Tuple


def map_party_stem_to_category(stem: str) -> str:
    s = stem.lower()
    if "republic" in s:
        return "republican"
    if "democ" in s:
        return "democratic"
    if "non" in s or "no-party" in s or "nonpartisan" in s:
        return "nonpartisan"
    return "thirdParty"


def normalize_name(s: Optional[str]) -> str:
    if not s:
        return ""
    return " ".join(s.strip().lower().split())


def normalize_donation(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lstrip("$").replace(",", "")
    try:
        f = float(s)
    except Exception:
        return s.lower()
    # format without trailing .0 when integer
    if f.is_integer():
        return str(int(f))
    return str(f)


def make_match_key_from_row(row: dict) -> Optional[Tuple[str, ...]]:
    # prefer entityName when present
    entity = (row.get("entityName") or row.get("EntityName") or "").strip()
    donation = normalize_donation(row.get("donationsToCampaign") or row.get("donationsToCampaign") or row.get("donation") or row.get("amount"))
    if entity:
        return (normalize_name(entity), donation)
    first = (row.get("firstName") or row.get("FirstName") or "").strip()
    last = (row.get("lastName") or row.get("LastName") or "").strip()
    if first or last or donation:
        return (normalize_name(first), normalize_name(last), donation)
    return None


def build_rep_dem_keys(candidate_dir: Path):
    keys = set()
    for stem in ("republican", "democratic"):
        p = candidate_dir / f"{stem}.csv"
        if not p.exists():
            continue
        with p.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                k = make_match_key_from_row(row)
                if k:
                    keys.add(k)
    return keys


def process_candidate(candidate_dir: Path) -> None:
    repdem_keys = build_rep_dem_keys(candidate_dir)
    if not repdem_keys:
        return

    # Find files that map to nonpartisan or thirdParty and rewrite them
    for csvp in sorted(candidate_dir.glob("*.csv")):
        stem = csvp.stem
        cat = map_party_stem_to_category(stem)
        if cat not in ("nonpartisan", "thirdParty"):
            continue

        with csvp.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
            fieldnames = reader.fieldnames or ["entityName", "firstName", "lastName", "amount", "donationsToCampaign"]

        kept = []
        removed = 0
        for row in rows:
            k = make_match_key_from_row(row)
            if k and k in repdem_keys:
                removed += 1
                continue
            kept.append(row)

        if removed > 0:
            # overwrite file with kept rows (preserve header order)
            with csvp.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(kept)
        print(f"{csvp}: removed {removed} rows; kept {len(kept)}")


def main() -> None:
    root = Path("by-donor-output")
    if not root.exists():
        print("by-donor-output not found")
        return

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        print(f"Processing candidate: {entry.name}")
        process_candidate(entry)


if __name__ == "__main__":
    main()
