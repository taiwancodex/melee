#!/usr/bin/env python3
"""Build the permuter base.c for fn_80180630 (gmregclear): keep the function,
prototype everything else, wrap the case-3 region in PERM_RANDOMIZE."""
import re
import sys
from pathlib import Path

sys.path.insert(0, "build/hoplite/tools/decomp-permuter-main")
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
        if name in KEEP:
            out.extend(lines[h_start:end + 1])
            kept.add(name)
        else:
            header = "".join(lines[h_start:h_end + 1]).rstrip()
            out.append(header + ";\n")
        pos = end + 1
    out.extend(lines[pos:])
    stripped = "".join(out)
    if kept != KEEP:
        sys.exit(f"missing functions after strip: {KEEP - kept}")

    # wrap the case-3 region (where the 2-line register delta lives)
    m = re.search(r"^ *temp = gm_16AE_GetUnkData_0\(\);", stripped, re.M)
    if not m:
        sys.exit("case-3 region start not found")
    region_start = m.start()
    m2 = re.search(r"state->x108 = 0x1F4;", stripped)
    if not m2 or m2.start() < region_start:
        sys.exit("case-3 region end not found")
    # include the if's closing brace so the region is complete statements
    region_end = stripped.index("}", m2.end()) + 1
    region = stripped[region_start:region_end]
    result = (stripped[:region_start]
              + "PERM_RANDOMIZE(" + region + ")\n        "
              + stripped[region_end:])
    DST.write_text(result, encoding="utf-8")
    # also emit the same TU without the wrapper, for codegen validation
    Path("build/hoplite/perm_gmregclear/base_check.c").write_text(
        stripped, encoding="utf-8")
    print(f"base.c written: {len(result.splitlines())} lines; kept {kept}")


if __name__ == "__main__":
    main()
