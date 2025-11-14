from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def detect_delimiter_from_header(header_line: str) -> str:
	if "|" in header_line:
		return "|"
	if "," in header_line:
		return ","
	return ","


def find_amount_field(fieldnames: Iterable[str]) -> str | None:
	for fn in fieldnames:
		if fn and "amount" in fn.lower():
			return fn
	return None


def process_file(path: Path) -> float:
	# return total amount (float)
	with path.open("r", encoding="utf-8", newline="") as fh:
		first = fh.readline()
        
		delimiter = detect_delimiter_from_header(first)
		# rewind to start and use csv.DictReader
		fh.seek(0)
		reader = csv.DictReader(fh, delimiter=delimiter)
		amount_field = find_amount_field(reader.fieldnames or [])
		total = 0.0
		if not amount_field:
			# no amount column found
			return 0.0

		for row in reader:
			v = (row.get(amount_field) or "").strip()
			if not v:
				continue
			# strip non-numeric except dot and minus
			clean = "".join(ch for ch in v if (ch.isdigit() or ch in "-."))
			try:
				total += float(clean) if clean else 0.0
			except ValueError:
				continue

	return total


def main() -> None:
	data_dir = Path("data")
	if not data_dir.is_dir():
		print("data/ directory not found")
		raise SystemExit(1)

	totals = []
	for p in sorted(data_dir.glob("*-contributions.csv")):
		name = p.stem.replace("-contributions", "")
		total = process_file(p)
		totals.append((name, total))

	out_lines = []
	for name, total in totals:
		out_lines.append(f"{name}: ${total:,.0f}")

	txt = "\n".join(out_lines) + "\n"
	with open("totals.txt", "w", encoding="utf-8") as fh:
		fh.write(txt)

	print(txt)


if __name__ == "__main__":
	main()

