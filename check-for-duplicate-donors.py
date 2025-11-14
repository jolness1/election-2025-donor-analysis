from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Tuple
"""
Finds duplicate donor rows across party CSVs for each candidate.
Avoids counting donors who donate largely to democrats but also donate to nominally
"non-partisan" races that are largely driven by partisan dynamics.
"""

def normalize_fields_union(rows_by_file: Dict[Path, list]) -> list:
    # build a stable ordered list of fields to use for matching (union of all headers)
    fields = []
    seen = set()
    for p, rows in rows_by_file.items():
        # rows may be list of dicts with keyed by fieldnames
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    fields.append(k)
            break
    return fields


def make_match_key(row: dict, match_fields: list) -> Tuple:
    # create tuple of values for all match_fields except 'amount'
    key = tuple((field, (row.get(field) or "").strip()) for field in match_fields if field.lower() != "amount")
    return key


def display_name_from_row(row: dict) -> str:
    first = (row.get("firstName") or "").strip()
    last = (row.get("lastName") or "").strip()
    if first or last:
        return (first + " " + last).strip()
    # fallback to entityName
    ent = (row.get("entityName") or "").strip()
    return ent


def donations_value_from_row(row: dict) -> str:
    v = (row.get("donationsToCampaign") or "").strip()
    if not v:
        return "$0"
    # keep as-is, but normalize formatting to show two decimals if needed
    try:
        f = float("".join(ch for ch in v if (ch.isdigit() or ch in "-.")))
    except Exception:
        return v
    if float(f).is_integer():
        return f"${int(f)}"
    return f"${f:.2f}"


def process_candidate_dir(candidate: str, candidate_dir: Path, out_root: Path) -> None:
    csv_files = sorted(candidate_dir.glob("*.csv"))
    if not csv_files:
        return

    rows_by_file: Dict[Path, list] = {}
    for csv_path in csv_files:
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows_by_file[csv_path] = list(reader)

    match_fields = normalize_fields_union(rows_by_file)

    # map key -> set of files where it appears and representative row
    key_to_files: Dict[Tuple, set] = {}
    key_to_row: Dict[Tuple, dict] = {}

    for csv_path, rows in rows_by_file.items():
        for r in rows:
            key = make_match_key(r, match_fields)
            key_to_files.setdefault(key, set()).add(csv_path.name)
            # keep first seen representative row
            if key not in key_to_row:
                key_to_row[key] = r

    duplicates = []
    for key, files in key_to_files.items():
        if len(files) > 1:
            rep = key_to_row.get(key, {})
            name = display_name_from_row(rep)
            donations = donations_value_from_row(rep)
            # store sorted, basenames without extension for readability
            files_short = sorted([Path(f).stem for f in files])
            files_joined = "/".join(files_short)
            duplicates.append((name, donations, files_joined))

    # write duplicates file under out_root as {candidate}-duplicates.txt
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{candidate}-duplicates.txt"
    with out_path.open("w", encoding="utf-8") as fh:
        for name, donated, files_joined in duplicates:
            fh.write(f"{name} {donated} {files_joined}\n")

    if duplicates:
        print(f"Wrote {out_path} ({len(duplicates)} duplicates)")
    else:
        print(f"No duplicates for {candidate}")


def main() -> None:
    root = Path("by-donor-output")
    if not root.exists():
        print("by-donor-output directory not found")
        raise SystemExit(1)

    # candidate directories are subdirectories; skip files like donors-*.csv in root
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            candidate = entry.name
            process_candidate_dir(candidate, entry, root)


if __name__ == "__main__":
    main()
