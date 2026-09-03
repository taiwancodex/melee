#!/usr/bin/env python3
"""Wrap only gmMainLib_8015DBF4's body in PERM_RANDOMIZE for the permuter."""
from pathlib import Path

SRC = Path("build/hoplite/perm_gmmain/base_raw.c")
DST = Path("build/hoplite/perm_gmmain/base.c")
FN = "s32 gmMainLib_8015DBF4(s32 arg0)"

text = SRC.read_text(encoding="utf-8")
start = text.index(FN)
brace = text.index("{", start + len(FN))
# find matching close brace
level = 0
i = brace
while i < len(text):
    if text[i] == "{":
        level += 1
    elif text[i] == "}":
        level -= 1
        if level == 0:
            break
    i += 1
body = text[brace + 1 : i]
out = (text[: brace + 1]
       + "\nPERM_RANDOMIZE(" + body + ")\n"
       + text[i:])
DST.write_text(out, encoding="utf-8")
print(f"wrapped {i - brace - 1} chars of function body")
