#!/usr/bin/env python3
"""Triage non-matching functions from build/GALE01/report.json.

A unit is non-matching when matched_functions < total_functions.
A function is definitely non-matching when fuzzy_match_percent < 100.
Units whose counts disagree with the fuzzy<100 set are flagged for byte-level
checking (fuzzy 100 is not proof of a byte-perfect match).
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "build/GALE01/report.json"
with open(path, encoding="utf-8") as f:
    report = json.load(f)

rows = []
flagged_units = []
nm_units = 0
for unit in report.get("units", []):
    m = unit.get("measures", {})
    matched = int(m.get("matched_functions", 0))
    total = int(m.get("total_functions", 0))
    if matched >= total:
        continue
    nm_units += 1
    bad = []
    for fn in unit.get("functions", []):
        try:
            fuzzy = float(fn.get("fuzzy_match_percent", 100.0))
        except (TypeError, ValueError):
            fuzzy = -1.0
        if fuzzy < 100.0:
            bad.append((fuzzy, fn.get("name"), int(fn.get("size", 0) or 0)))
    if len(bad) != total - matched:
        flagged_units.append((unit.get("name"), matched, total, len(bad)))
    for fuzzy, name, size in bad:
        rows.append((fuzzy, unit.get("name"), name, size))

rows.sort(key=lambda r: (-r[0], r[1]))
print(f"Non-matching units: {nm_units}")
print(f"Definitely non-matching functions (fuzzy<100): {len(rows)}")
print(f"Units needing byte-level verification: {len(flagged_units)}")
print()
for fuzzy, unit, fn, size in rows:
    print(f"{fuzzy:9.3f}%  {size:6d}  {unit.replace('main/',''):44s}  {fn}")
print()
for name, matched, total, bad in flagged_units:
    print(f"CHECK: {name}: {matched}/{total} matched but only {bad} fuzzy<100")
