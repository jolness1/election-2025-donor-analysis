from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime
from typing import List, Tuple, Optional

try:
    from dateutil.parser import parse as parse_dt
except Exception:
    parse_dt = None


def detect_dialect(sample: str) -> csv.Dialect:
    if not sample:
        class _D(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL

        return _D()

    lines = [ln for ln in sample.splitlines() if ln.strip()][:5]
    if not lines:
        chosen = ','
    else:
        counts = {d: sum(line.count(d) for line in lines) for d in [',', '|', '\t', ';']}
        # choose delimiter with max count, but ensure it's >0
        chosen, cnt = max(counts.items(), key=lambda x: x[1])
        if cnt == 0:
            chosen = ','

    class _D(csv.Dialect):
        delimiter = chosen
        quotechar = '"'
        doublequote = True
        skipinitialspace = False
        lineterminator = "\n"
        quoting = csv.QUOTE_MINIMAL

    return _D()


def try_parse_date(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.max

    if parse_dt:
        try:
            return parse_dt(s)
        except Exception:
            pass

    formats = [
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%b %d %Y",
        "%B %d %Y",
    ]
    for f in formats:
        try:
            return datetime.strptime(s, f)
        except Exception:
            continue

    # final fallback: put unparsable at the end
    return datetime.max


def process_file(path: str) -> Tuple[int, int]:
    """Process a single CSV file in place.

    Returns (removed_count, written_rows_count)
    """
    with open(path, "r", newline="", encoding="utf-8") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        dialect = detect_dialect(sample)
        reader = csv.reader(
            fh,
            delimiter=getattr(dialect, "delimiter", ","),
            quotechar=getattr(dialect, "quotechar", '"'),
            skipinitialspace=getattr(dialect, "skipinitialspace", False),
        )
        rows: List[List[str]] = list(reader)

    if not rows:
        print(f"{os.path.basename(path)}: empty file, skipping")
        return 0, 0

    header = rows[0]
    data_rows = rows[1:]

    seen = set()
    unique_rows: List[List[str]] = []
    removed = 0
    for r in data_rows:
        key = tuple(r)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique_rows.append(r)

    # find data paid column (case-insensitive)
    date_col_idx: Optional[int] = None
    lowered = [c.strip().lower() for c in header]
    for idx, name in enumerate(lowered):
        if name == "date paid" or name == "date" or name.startswith("date"):
            date_col_idx = idx
            break

    if date_col_idx is None:
        print(f"{os.path.basename(path)}: 'Date Paid' column not found; will not sort")
        sorted_rows = unique_rows
    else:
        def keyfn(row: List[str]) -> datetime:
            if date_col_idx >= len(row):
                return datetime.max
            return try_parse_date(row[date_col_idx])

        sorted_rows = sorted(unique_rows, key=keyfn)

    # overwrite file with deduped, sorted rows
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(
            fh,
            delimiter=getattr(dialect, "delimiter", ","),
            quotechar=getattr(dialect, "quotechar", '"'),
            doublequote=getattr(dialect, "doublequote", True),
            escapechar="\\",
            lineterminator=getattr(dialect, "lineterminator", "\n"),
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(header)
        writer.writerows(sorted_rows)

    return removed, len(sorted_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Dedupe and reorder CSVs in a directory")
    ap.add_argument("dir", nargs="?", default="data", help="directory containing CSV files")
    args = ap.parse_args()

    data_dir = args.dir
    if not os.path.isdir(data_dir):
        print(f"Error: {data_dir} is not a directory")
        raise SystemExit(1)

    files = sorted(os.listdir(data_dir))
    csv_files = [os.path.join(data_dir, f) for f in files if f.lower().endswith(".csv")]
    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        return

    total_removed = 0
    for p in csv_files:
        removed, written = process_file(p)
        total_removed += removed
        print(f"{os.path.basename(p)}: removed {removed} duplicate rows, wrote {written} rows")

    print(f"Done. Total duplicates removed: {total_removed}")


if __name__ == "__main__":
    main()
