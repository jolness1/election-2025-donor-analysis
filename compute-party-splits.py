from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict

"""
Computes approximate party donation splits per candidate from by-donor-output files.
"""

def find_amount_field(fieldnames):
    if not fieldnames:
        return None
    for fn in fieldnames:
        if fn and "amount" in fn.lower():
            return fn
    return None


def map_party_stem_to_category(stem: str) -> str:
    s = stem.lower()
    if "republic" in s:
        return "republican"
    if "democ" in s:
        return "democratic"
    if "non" in s or "no-party" in s or "nonpartisan" in s:
        return "nonpartisan"
    # everything else treat as third party / other
    return "thirdParty"


def format_candidate_name(raw: str) -> str:
    """Convert folder-name-style candidate id (e.g. 'jennifer-owen')
    to a human-friendly display name (e.g. 'Jennifer Owen').
    Replaces hyphens/underscores with spaces and title-cases the parts.
    """
    if not raw:
        return raw
    s = raw.replace("-", " ").replace("_", " ")
    # Title-case each word; keep multiple spaces normalized
    parts = [p for p in s.split() if p]
    return " ".join(p.title() for p in parts)


def sum_amounts_in_csv(path: Path) -> float:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        amount_field = find_amount_field(reader.fieldnames)
        if not amount_field:
            return 0.0
        total = 0.0
        for row in reader:
            v = (row.get(amount_field) or "").strip()
            if not v:
                continue
            # strip characters except digits, dot, minus
            clean = "".join(ch for ch in v if (ch.isdigit() or ch in "-.'"))
            # fallback parsing
            try:
                num = float(clean) if clean else 0.0
            except Exception:
                stripped = "".join(ch for ch in v if (ch.isdigit() or ch in "-."))
                try:
                    num = float(stripped) if stripped else 0.0
                except Exception:
                    num = 0.0
            total += num
    return total


def find_donation_field(fieldnames):
    if not fieldnames:
        return None
    for fn in fieldnames:
        if fn and "donat" in fn.lower():
            return fn
    return None


def sum_preferred_amounts_in_csv(path: Path) -> float:
    """Sum `donationsToCampaign` when present, otherwise `amount`."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # prefer donationsToCampaign-like fields
        don_field = find_donation_field(reader.fieldnames)
        amt_field = find_amount_field(reader.fieldnames)
        field = don_field or amt_field
        if not field:
            return 0.0
        total = 0.0
        for row in reader:
            v = (row.get(field) or "").strip()
            if not v:
                continue
            clean = "".join(ch for ch in v if (ch.isdigit() or ch in "-."))
            try:
                num = float(clean) if clean else 0.0
            except Exception:
                # fallback strip non-digit except dot/minus
                stripped = "".join(ch for ch in v if (ch.isdigit() or ch in "-.'"))
                try:
                    num = float(stripped) if stripped else 0.0
                except Exception:
                    num = 0.0
            total += num
    return total


def main() -> None:
    root = Path("by-donor-output")
    if not root.exists():
        print("by-donor-output directory not found")
        raise SystemExit(1)

    out_rows = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        candidate = entry.name
        pretty_candidate = format_candidate_name(candidate)
        # category sums
        sums: Dict[str, float] = {"republican": 0.0, "democratic": 0.0, "thirdParty": 0.0, "nonpartisan": 0.0}
        # iterate csv files
        for csvp in sorted(entry.glob("*.csv")):
            stem = csvp.stem  # e.g. 'republican'
            cat = map_party_stem_to_category(stem)
            # sum using donationsToCampaign when present, otherwise fall back to amount
            amt = sum_preferred_amounts_in_csv(csvp)
            sums[cat] = sums.get(cat, 0.0) + amt

        total = sum(sums.values())
        if total <= 0:
            perc = {k: 0.0 for k in sums}
        else:
            perc = {k: (sums[k] / total) * 100.0 for k in sums}

        out_rows.append((pretty_candidate, perc["republican"], perc["democratic"], perc["thirdParty"], perc["nonpartisan"]))

    out_path = root / "splits.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["candidate", "republican", "democratic", "thirdParty", "nonpartisan"])
        for cand, rep, dem, third, nonp in out_rows:
            writer.writerow([cand, f"{rep:.2f}", f"{dem:.2f}", f"{third:.2f}", f"{nonp:.2f}"])

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
