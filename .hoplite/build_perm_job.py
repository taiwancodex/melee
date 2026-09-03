#!/usr/bin/env python3
"""Generic permuter base builder: strip a TU to one target function plus all
static/inline definitions (the inlinable pool), wrap a region in
PERM_RANDOMIZE.

usage: build_perm_job.py <jobdir> <src.c> <func> <region_start_re> <region_end_re>
The region regexes are searched with re.M; region_end_re's match END closes
the region (use a regex that includes the closing brace).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, ".hoplite")
from build_perm_base_lib import find_fn_defs, brace_end  # noqa: E402


def main():
    (jobdir, src, fn, start_re, end_re) = sys.argv[1:6]
    job = Path(jobdir)
    text = Path(src).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    out = []
    pos = 0
    kept = set()
    for (h_start, h_end, b_line, b_col, name) in list(find_fn_defs(lines)):
        if h_start < pos:
            continue
        out.extend(lines[pos:h_start])
        end = brace_end(lines, b_line, b_col)
        if end is None:
            out.extend(lines[h_start:])
            pos = len(lines)
            break
        header = "".join(lines[h_start:h_end + 1])
        keep = (name == fn or re.match(r"(static|inline)\b", header.strip()))
        if keep:
            out.extend(lines[h_start:end + 1])
            kept.add(name)
        else:
            out.append(header.rstrip() + ";\n")
        pos = end + 1
    out.extend(lines[pos:])
    stripped = "".join(out)
    if fn not in kept:
        sys.exit(f"target function {fn} not found/kept")

    m = re.search(start_re, stripped, re.M)
    if not m:
        sys.exit("region start not found")
    region_start = m.start()
    m2 = re.search(end_re, stripped[region_start:], re.M)
    if not m2:
        sys.exit("region end not found")
    region_end = region_start + m2.end()
    region = stripped[region_start:region_end]
    result = (stripped[:region_start]
              + "PERM_RANDOMIZE(" + region + ")\n    "
              + stripped[region_end:])
    (job / "base.c").write_text(result, encoding="utf-8")
    (job / "base_check.c").write_text(stripped, encoding="utf-8")
    print(f"base.c: {len(result.splitlines())} lines; kept {len(kept)} "
          f"defs incl. target")


if __name__ == "__main__":
    main()
