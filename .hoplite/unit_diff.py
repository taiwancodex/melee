#!/usr/bin/env python3
"""Diff every function between a built object and the DOL-original object."""
import re
import subprocess
import sys
from pathlib import Path

OBJD = "build/tools/binutils/powerpc-eabi-objdump"
LINE_RE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*\t?(.*)$")
BRANCH_RE = re.compile(r"^(b[a-z.]*)\s+(.*)$")


def objdump(path):
    return subprocess.run([OBJD, "-d", str(path)], capture_output=True,
                          text=True, check=True).stdout.splitlines()


def functions(lines):
    out = {}
    name = None
    pat = re.compile(r"^[0-9a-f]+ <(.+)>:")
    for line in lines:
        m = pat.match(line)
        if m:
            name = m.group(1)
            out[name] = []
            continue
        if name is not None and line.strip():
            out[name].append(line.rstrip())
    return out


def normalize(text):
    text = text.split("#")[0].strip()
    text = re.sub(r"<([^>+]+)(\+0x[0-9a-f]+)?>", r"\1", text)
    m = BRANCH_RE.match(text)
    if m and m.group(1) not in ("bctr", "bctrl"):
        mnem, rest = m.group(1), m.group(2)
        sym = re.search(r"<([^>+]+)", rest)
        return f"{mnem} {sym.group(1)}" if sym else mnem + " L"
    return text


def norm_insns(lines):
    out = []
    for line in lines:
        m = LINE_RE.match(line)
        if m:
            out.append(normalize(m.group(3)))
        else:
            t = line.strip()
            if t:
                out.append(normalize(t))
    return out


def main():
    built_path, orig_path = sys.argv[1], sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 else None
    built = functions(objdump(built_path))
    orig = functions(objdump(orig_path))
    bad = 0
    total = 0
    import difflib
    for name in orig:
        if only and only not in name:
            continue
        if name not in built:
            print(f"MISSING {name}")
            bad += 1
            continue
        total += 1
        a = norm_insns(orig[name])
        b = norm_insns(built[name])
        if a == b:
            continue
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        score = sum(max(i2 - i1, j2 - j1)
                    for tag, i1, i2, j1, j2 in sm.get_opcodes()
                    if tag != "equal")
        print(f"DIFF {name}: {score} lines, orig {len(a)} built {len(b)}")
        bad += 1
    print(f"\n{total - bad}/{total} functions match")


if __name__ == "__main__":
    main()
