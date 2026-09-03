#!/usr/bin/env python3
"""Build the permuter base.c: keep gmMainLib_8015DBF4 + the inline helpers it
needs, prototype every other function, wrap the target body in PERM_RANDOMIZE."""
import re
import sys
from pathlib import Path

SRC = Path("build/hoplite/perm_gmmain/base_raw.c")
DST = Path("build/hoplite/perm_gmmain/base.c")
FN = "gmMainLib_8015DBF4"
KEEP = {FN, "gmMainLib_8015CDC8", "gmMainLib_AdjustNameTags"}


def find_fn_defs(lines):
    """Yield (header_start, header_end_line, brace_line, brace_col, name) for
    each function definition; header_end_line is the line ending in ')'."""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if ("(" in stripped and "=" not in stripped
                and not stripped.startswith("#")
                and not stripped.startswith("/")
                and not stripped.startswith("*")):
            # consume until parens balance
            depth = 0
            j = i
            last_paren_line = None
            while j < n:
                for ch in lines[j]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                if depth == 0:
                    last_paren_line = j
                    break
                j += 1
            if last_paren_line is not None:
                # next non-empty line must be '{' (or the same line ends '{')
                if lines[last_paren_line].rstrip().endswith("{"):
                    brace_line, brace_col = last_paren_line, \
                        lines[last_paren_line].rindex("{")
                elif last_paren_line + 1 < n and \
                        lines[last_paren_line + 1].strip() == "{":
                    brace_line, brace_col = last_paren_line + 1, 0
                else:
                    brace_line = None
                if brace_line is not None:
                    header = "".join(lines[i:last_paren_line + 1])
                    m = re.search(r"(\w+)\s*\(", header)
                    name = m.group(1) if m else None
                    if name and not name.startswith(("if", "for", "while",
                                                     "switch", "return")):
                        yield i, last_paren_line, brace_line, brace_col, name
                        i = brace_line
                        # caller advances past the body
        i += 1


def brace_end(lines, brace_line, brace_col):
    level = 0
    started = False
    for j in range(brace_line, len(lines)):
        start = brace_col if j == brace_line else 0
        for k in range(start, len(lines[j])):
            ch = lines[j][k]
            if ch == "{":
                level += 1
                started = True
            elif ch == "}":
                level -= 1
                if started and level == 0:
                    return j
    return None


def hoist_nested_structs(text):
    """Hoist tagged structs nested inside struct gmm_x0 to file scope.

    The randomizer's typemap misses struct tags defined inside another
    struct's member list (e.g. gmm_x0_528_t), which disables randomization
    passes on statements using those fields. Hoisting is layout- and
    codegen-neutral: the tags are already referenced at file scope.
    """
    for tag in ("gmm_x0_584_t", "EventData", "gmm_x0_528_t"):
        m = re.search(rf"( *)struct {tag} \{{", text, re.M)
        if not m:
            continue
        brace = text.index("{", m.start())
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
        semi = text.index(";", i)
        members = text[i + 1:semi].strip()
        definition = text[m.start():i + 1]
        # replace the nested definition with a plain member declaration
        text = (text[:m.start()]
                + f"struct {tag} {members};"
                + text[semi + 1:])
        # insert the hoisted definition before struct gmm_x0's definition
        g = re.search(r"^struct gmm_x0 \{", text, re.M)
        line_start = text.rfind("\n", 0, g.start()) + 1
        text = (text[:line_start]
                + definition + ";\n\n"
                + text[line_start:])
    return text


def main():
    text = SRC.read_text(encoding="utf-8")
    text = hoist_nested_structs(text)
    lines = text.splitlines(keepends=True)
    out = []
    pos = 0  # line index of next unprocessed line
    kept = set()
    for (h_start, h_end, b_line, b_col,
         name) in list(find_fn_defs(lines)):
        if h_start < pos:
            continue  # inside a previously kept/stripped body
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
            # prototype: header lines, with a ';' instead of the body
            header = "".join(lines[h_start:h_end + 1]).rstrip()
            out.append(header + ";\n")
        pos = end + 1
    out.extend(lines[pos:])
    stripped = "".join(out)

    if kept != KEEP:
        sys.exit(f"missing functions after strip: {KEEP - kept}")

    # wrap ONLY the entry-block region: the randomizer should not waste
    # samples mutating the 900+ already-matching instructions elsewhere.
    m = re.search(r"^s32 gmMainLib_8015DBF4\(s32 arg0\)", stripped, re.M)
    brace = stripped.index("{", m.end() - 1)
    region_start = stripped.index("config = gmMainLib_8015CDC8();", brace)
    # end just before the first expanded ADJ_NAMETAG_78 block (unk_522)
    m2 = re.search(r"do \{ val = \(gmMainLib_804D3EE0->unk_522\.x4\)",
                   stripped)
    if not m2:
        sys.exit("first ADJ block not found")
    region_end = m2.start()
    region = stripped[region_start:region_end]
    result = (stripped[:region_start]
              + "PERM_RANDOMIZE(" + region + ")\n    "
              + stripped[region_end:])
    DST.write_text(result, encoding="utf-8")
    print(f"base.c written: {len(result.splitlines())} lines; kept {kept}")


if __name__ == "__main__":
    main()
