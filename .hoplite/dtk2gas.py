#!/usr/bin/env python3
"""Convert dtk-format asm for one function into GAS-compatible asm."""
import re
import sys
from pathlib import Path

src_path, fn_name, dst_path = sys.argv[1], sys.argv[2], sys.argv[3]

lines = Path(src_path).read_text(encoding="utf-8").splitlines()
out = []
inside = False
for line in lines:
    s = line.strip()
    if s.startswith(".fn ") and fn_name in s:
        inside = True
        out.append(".text")
        out.append(f".globl {fn_name}")
        out.append(f"{fn_name}:")
        continue
    if s.startswith(".endfn"):
        if inside:
            inside = False
            out.append(f".size {fn_name}, .-{fn_name}")
        continue
    if not inside:
        continue
    # strip the leading /* addr offset bytes */ comment, keep the instruction
    if "*/" in s:
        body = s.split("*/", 1)[1].strip()
    else:
        body = s
    if not body or body.startswith("/*"):
        continue
    # GAS wants %rN register names; convert register tokens only
    body = re.sub(r"\b([rf])([0-9]|[12][0-9]|3[01])\b", r"%\1\2", body)
    # condition-register field expressions -> numeric CR bit
    crbits = {"lt": 0, "gt": 1, "eq": 2, "so": 3, "un": 3}
    body = re.sub(r"4\*cr([0-7])\+([a-z]+)",
                  lambda m: str(4 * int(m.group(1))
                                + crbits.get(m.group(2), 0)),
                  body)
    body = re.sub(r"\bcr([0-7])(lt|gt|eq|so|un)\b",
                  lambda m: str(4 * int(m.group(1))
                                + crbits.get(m.group(2), 0)),
                  body)
    out.append(body)

Path(dst_path).write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {len(out)} lines to {dst_path}")
