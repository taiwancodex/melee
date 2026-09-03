#!/usr/bin/env python3
"""Build the gmregclear permuter base with manual PERM_GENERAL alternatives
for the out-param reads — deterministic coverage of the combos the random
mode never touches."""
import re
import sys
from pathlib import Path

sys.path.insert(0, ".hoplite")
from build_perm_base_lib import find_fn_defs, brace_end  # noqa: E402

SRC = Path("build/hoplite/perm_gmregclear/base_raw.c")
DST = Path("build/hoplite/perm_gmregclear/base.c")
FN = "fn_80180630"
KEEP = {
    FN,
    "fn_80180630_CreateCameraGObj",
    "fn_80180630_LoadLightList",
    "fn_80180630_LoadCameraDesc",
    "fn_80180630_GetModelDesc",
    "fn_80180630_SetupSisLib",
    "fn_80180630_CreateLightAndCamera",
    "fn_80180630_GetX118",
}

INNER = """PERM_GENERAL(
                special_score = special_score_value;
                coins = (u16) coin_count;
                state->x108 = 0x1F4;,
                coins = (u16) coin_count;
                special_score = special_score_value;
                state->x108 = 0x1F4;,
                coins = (u16) coin_count;
                state->x108 = 0x1F4;
                special_score = special_score_value;,
                special_score = special_score_value;
                state->x108 = 0x1F4;
                coins = (u16) coin_count;,
                coins = coin_count & 0xFFFF;
                special_score = special_score_value;
                state->x108 = 0x1F4;,
                special_score = special_score_value;
                coins = coin_count & 0xFFFF;
                state->x108 = 0x1F4;
            )"""


def main():
    text = SRC.read_text(encoding="utf-8")
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
        if name in KEEP:
            out.extend(lines[h_start:end + 1])
            kept.add(name)
        else:
            out.append(header.rstrip() + ";\n")
        pos = end + 1
    out.extend(lines[pos:])
    stripped = "".join(out)
    if kept != KEEP:
        sys.exit(f"missing functions after strip: {KEEP - kept}")

    old = """            grPushOn_80219204(Ground_801C1DD4(), &special_score_value,
                              &coin_count);
            special_score = special_score_value;
            coins = (u16) coin_count;
            state->x108 = 0x1F4;"""
    if old not in stripped:
        sys.exit("case-3 inner block not found")
    new = ("            grPushOn_80219204(Ground_801C1DD4(), "
           "&special_score_value,\n                              &coin_count);\n"
           + INNER)
    stripped = stripped.replace(old, new, 1)

    m = re.search(r"^ *temp = gm_16AE_GetUnkData_0\(\);", stripped, re.M)
    region_start = m.start()
    m2 = re.search(r"\n        \}\n        break;", stripped[region_start:])
    region_end = region_start + m2.end()
    region = stripped[region_start:region_end]
    result = (stripped[:region_start]
              + "PERM_RANDOMIZE(" + region + ")\n        "
              + stripped[region_end:])
    DST.write_text(result, encoding="utf-8")
    print(f"base.c written: {len(result.splitlines())} lines; kept {kept}")


if __name__ == "__main__":
    main()
