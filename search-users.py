
from __future__ import annotations

import argparse
import glob
import time
import os
import re
import sys
import urllib.parse
from typing import Optional

try:
	import requests
	from bs4 import BeautifulSoup
except Exception:
	print("Missing dependencies. Please run: pip install -r requirements.txt", file=sys.stderr)
	raise

# Searches FollowTheMoney entity search and print positive-dollar contributor hrefs.

def format_name(raw: str) -> str:
	# raw looks like 'NELSON, MIKE' or 'Smith, John'
	if "," in raw:
		last, first = [p.strip() for p in raw.split(",", 1)]
		return f"{first.title()} {last.title()}"
	return raw.title()


def parse_and_print(html: str) -> None:
	soup = BeautifulSoup(html, "html.parser")

	rows = soup.select("tbody tr")
	for tr in rows:
		tds = tr.find_all("td")
		if len(tds) < 3:
			continue

		amount_text = tds[-1].get_text(strip=True)
		# remove non-numeric except dot and minus
		amount_num = re.sub(r"[^0-9.-]", "", amount_text)
		try:
			amount = float(amount_num) if amount_num else 0.0
		except ValueError:
			amount = 0.0

		if amount > 0:
			# second td contains the link and name
			a = tds[1].find("a")
			if not a or not a.get("href"):
				continue
			href = normalize_href(a["href"])
			name_raw = a.get_text(strip=True)
			name = format_name(name_raw)
			print(f"{name} {href}")


def normalize_href(href: str) -> str:
	"""Return an absolute URL for href values; prepend the FTM domain when needed."""
	href = href.strip()
	if href.startswith("/"):
		return urllib.parse.urljoin("https://www.followthemoney.org", href)
	return href


def extract_eid_from_href(href: str) -> str:
	"""Return the numeric eid value extracted from an href like
	'/entity-details?eid=49301129' or 'https://.../?eid=49301129'.
	If not found, fall back to the last group of digits in the href.
	"""
	href = href.strip()
	try:
		parsed = urllib.parse.urlparse(href)
		qs = urllib.parse.parse_qs(parsed.query)
		if "eid" in qs and qs["eid"]:
			val = qs["eid"][0]
			# strip non-digits
			eid = re.sub(r"[^0-9]", "", val)
			if eid:
				return eid
	except Exception:
		pass
	m = re.search(r"(\d+)(?!.*\d)", href)
	return m.group(1) if m else href


def build_url(first: str, last: str) -> str:
	base = "https://www.followthemoney.org/metaselect/full/entitySearch.php"
	# eid expects a leading colon per the sample
	eid_value = f":{first}+{last}"
	params = {
		"navType": "1",
		"noclicky": "1",
		"eid": eid_value,
		"s": "MT",
		"y": "",
		"add-s": "",
	}
	return f"{base}?{urllib.parse.urlencode(params)}"


def build_url_from_query(eid_query: str) -> str:
	"""Build a URL when we already have the eid query string portion (including leading colon).

	eid_query should be like ':Mike+Nelson' or ':Flathead+County+Republican'
	Optionally supply an `add_s` value (typically a state) to include in the `add-s` param.
	"""
	base = "https://www.followthemoney.org/metaselect/full/entitySearch.php"
	params = {
		"navType": "1",
		"noclicky": "1",
		"eid": eid_query,
		"s": "MT",
		"y": "",
		"add-s": "",
	}
	return f"{base}?{urllib.parse.urlencode(params)}"


def build_url_from_query_with_state(eid_query: str, add_s: str | None) -> str:
	"""Like `build_url_from_query` but includes `add-s` when provided."""
	base = "https://www.followthemoney.org/metaselect/full/entitySearch.php"
	params = {
		"navType": "1",
		"noclicky": "1",
		"eid": eid_query,
		"s": "MT",
		"y": "",
		"add-s": add_s or "",
	}
	return f"{base}?{urllib.parse.urlencode(params)}"


def main(argv: Optional[list[str]] = None) -> int:
	p = argparse.ArgumentParser(description="Search FollowTheMoney and print positive-dollar entity links")
	p.add_argument("first", nargs="?", help="First name (when not using --file)")
	p.add_argument("last", nargs="?", help="Last name (when not using --file)")
	p.add_argument("--file", "-f", help="Path to local HTML file to parse (testing)")
	p.add_argument("--csv", help="Path to contributions CSV (pipe-delimited). When specified the script will process rows and write output CSV to output/.")
	p.add_argument("--test-html", help="(optional) Path to a local HTML file to use as the search result for every query (useful for testing instead of hitting remote)")
	p.add_argument("--output-dir", default="output", help="Directory to write donors-<base>.csv")
	p.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between HTTP requests (use small value like 1.0)")
	p.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
	args = p.parse_args(argv)

	if args.file:
		path = args.file
		if not os.path.exists(path):
			print(f"File not found: {path}", file=sys.stderr)
			return 2
		with open(path, "r", encoding="utf-8") as fh:
			html = fh.read()
		parse_and_print(html)
		return 0

	# If a CSV is provided, or if none provided, process contributions files
	def process_csv_path(csv_path: str) -> None:
		import csv

		if not os.path.exists(csv_path):
			print(f"CSV not found: {csv_path}", file=sys.stderr)
			return

		# create output dir
		outdir = args.output_dir
		os.makedirs(outdir, exist_ok=True)

		base = os.path.basename(csv_path)
		name_no_ext = os.path.splitext(base)[0]
		name_no_contrib = name_no_ext.replace("contributions", "").rstrip("-_ ")
		out_name = f"donors-{name_no_contrib.lstrip("-_ ")}.csv"
		out_path = os.path.join(outdir, out_name)

		# Read all rows first to compute per-donor totals
		with open(csv_path, newline="", encoding="utf-8") as inf:
			reader = csv.DictReader(inf, delimiter="|")
			rows = list(reader)

		# determine amount field
		amount_field = None
		if rows:
			for fn in rows[0].keys():
				if "amount" in fn.lower():
					amount_field = fn
					break
		if amount_field is None:
			amount_field = "Amount"

		# compute totals per donor key
		totals: dict[tuple, float] = {}
		for row in rows:
			first = (row.get("First Name") or row.get("FirstName") or "").strip()
			middle = (row.get("Middle Initial") or row.get("MiddleInitial") or "").strip()
			last = (row.get("Last Name") or row.get("LastName") or "").strip()
			entity = (row.get("Entity Name") or row.get("EntityName") or "").strip()
			city = (row.get("City") or "").strip()
			state = (row.get("State") or "").strip()

			key = (entity, first, middle, last, city, state)

			amt_text = (row.get(amount_field) or "").strip()
			amt_num = re.sub(r"[^0-9.-]", "", amt_text)
			try:
				amt = float(amt_num) if amt_num else 0.0
			except ValueError:
				amt = 0.0

			totals[key] = totals.get(key, 0.0) + amt

		# Now perform the same scraping/processing but write donationsToCampaign
		with open(out_path, "w", newline="", encoding="utf-8") as outf:
			fieldnames = ["entityName", "firstName", "middleInitial", "lastName", "city", "state", "eid", "donationsToCampaign"]
			writer = csv.DictWriter(outf, fieldnames=fieldnames)
			writer.writeheader()

			# Iterate rows again for queries
			for row in rows:
				first = (row.get("First Name") or row.get("FirstName") or "").strip()
				middle = (row.get("Middle Initial") or row.get("MiddleInitial") or "").strip()
				last = (row.get("Last Name") or row.get("LastName") or "").strip()
				entity = (row.get("Entity Name") or row.get("EntityName") or "").strip()
				city = (row.get("City") or "").strip()
				state = (row.get("State") or "").strip()

				if first and last:
					query_type = "name"
					q_first, q_middle, q_last = first, middle, last
					out_entityName = ""
					out_first, out_middle, out_last = first, middle, last
					out_city, out_state = city, state
				elif entity:
					query_type = "entity"
					q_first = entity
					q_last = ""
					out_entityName = entity
					out_first, out_middle, out_last = "", "", ""
					out_city, out_state = city, state
				else:
					continue

				if args.test_html:
					if not os.path.exists(args.test_html):
						print(f"Test HTML not found: {args.test_html}", file=sys.stderr)
						return
					html = open(args.test_html, encoding="utf-8").read()
				else:
					if query_type == "name":
						if q_middle:
							url = build_url_from_query_with_state(f":{urllib.parse.quote_plus(q_first)}+{urllib.parse.quote_plus(q_middle)}+{urllib.parse.quote_plus(q_last)}", out_state)
						else:
							url = build_url_from_query_with_state(f":{urllib.parse.quote_plus(q_first)}+{urllib.parse.quote_plus(q_last)}", out_state)
					else:
						url = build_url_from_query_with_state(f":{urllib.parse.quote_plus(q_first)}", out_state)

					headers = {"User-Agent": "search-users/1.0 (+https://github.com)"}
					try:
						resp = requests.get(url, headers=headers, timeout=args.timeout)
					except requests.RequestException as e:
						print(f"Request failed for {q_first} {q_last}: {e}", file=sys.stderr)
						# be polite: pause before next request
						time.sleep(args.delay)
						continue
					if resp.status_code != 200:
						print(f"HTTP {resp.status_code} for {url}", file=sys.stderr)
						time.sleep(args.delay)
						continue
					html = resp.text
					# polite pause between requests
					time.sleep(args.delay)

				soup = BeautifulSoup(html, "html.parser")
				rows_html = soup.select("tbody tr")
				for tr in rows_html:
					tds = tr.find_all("td")
					if len(tds) < 3:
						continue
					amount_text = tds[-1].get_text(strip=True)
					amount_num = re.sub(r"[^0-9.-]", "", amount_text)
					try:
						amount = float(amount_num) if amount_num else 0.0
					except ValueError:
						amount = 0.0
					if amount > 0:
						a = tds[1].find("a")
						if not a or not a.get("href"):
							continue
						href = normalize_href(a["href"])
						key = (entity, first, middle, last, city, state)
						donated = totals.get(key, 0.0)
						writer.writerow({
							"entityName": out_entityName,
							"firstName": out_first,
							"middleInitial": out_middle,
							"lastName": out_last,
							"city": out_city,
							"state": out_state,
							"eid": extract_eid_from_href(href),
							"donationsToCampaign": f"{donated:.2f}",
						})

		print(f"Wrote results to: {out_path}")

	# If a single CSV provided via --csv, process that; otherwise iterate data/*-contributions.csv
	if args.csv:
		process_csv_path(args.csv)
		return 0

	# Auto-process files in data/ matching '*-contributions.csv'
	data_glob = os.path.join("data", "*-contributions.csv")
	matched = glob.glob(data_glob)
	if not matched:
		# fallback to original behavior requiring first/last
		if not (args.first and args.last):
			p.print_help()
			return 2

	for csv_path in matched:
		process_csv_path(csv_path)

	# If matched list was empty but first/last provided, continue to default remote fetch
	if not matched:
		# default behavior: require first and last
		url = build_url(args.first, args.last)
		# fetch remote
		headers = {"User-Agent": "search-users/1.0 (+https://github.com)"}
		try:
			resp = requests.get(url, headers=headers, timeout=args.timeout)
		except requests.RequestException as e:
			print(f"Request failed: {e}", file=sys.stderr)
			return 3

		if resp.status_code != 200:
			print(f"HTTP {resp.status_code} when fetching {url}", file=sys.stderr)
			return 4

		parse_and_print(resp.text)
		return 0

	# default behavior: require first and last
	if not (args.first and args.last):
		p.print_help()
		return 2

	url = build_url(args.first, args.last)
	# fetch remote
	headers = {"User-Agent": "search-users/1.0 (+https://github.com)"}
	try:
		resp = requests.get(url, headers=headers, timeout=args.timeout)
	except requests.RequestException as e:
		print(f"Request failed: {e}", file=sys.stderr)
		return 3

	if resp.status_code != 200:
		print(f"HTTP {resp.status_code} when fetching {url}", file=sys.stderr)
		return 4

	parse_and_print(resp.text)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
