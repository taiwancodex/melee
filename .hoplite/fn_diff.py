#!/usr/bin/env python3
"""Instruction-level diff of one function between built and original objects.

Normalizes away: raw addresses, unrelocated relocation operands, local branch
targets, and objdump formatting; keeps mnemonics, registers, offsets, and
call target symbols so real differences stand out.
"""
import re
import subprocess
import sys

OBJD = "build/tools/binutils/powerpc-eabi-objdump"
LINE_RE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*\t?(.*)$")
BRANCH_RE = re.compile(r"^(b[a-z.]*)\s+(.*)$")


def objdump(path):
    out = subprocess.run([OBJD, "-d", path], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def extract(lines, symbol):
    start = None
    body = []
    pat = re.compile(r"^[0-9a-f]+ <(.+)>:")
    for line in lines:
        m = pat.match(line)
        if m:
            if start is not None:
                break
            if m.group(1) == symbol:
                start = True
            continue
        if start is not None and line.strip():
            body.append(line.rstrip())
    return body


def clean_sym(text):
    """Keep symbol names without +off, drop raw hex targets."""
    text = text.split("#")[0].strip()
    text = re.sub(r"<([^>+]+)(\+0x[0-9a-f]+)?>", r"\1", text)
    return text


def normalize(text):
    text = clean_sym(text)
    m = BRANCH_RE.match(text)
    if m and m.group(1) not in ("bctr", "bctrl"):
        mnem, rest = m.group(1), m.group(2)
        sym = re.search(r"<([^>+]+)", rest)
        if sym:
            return f"{mnem} {sym.group(1)}"
        return mnem + " L"
    return text


def norm(lines):
    out = []
    for line in lines:
        m = LINE_RE.match(line)
        if m:
            out.append((m.group(1), normalize(m.group(3))))
        else:
            t = line.strip()
            if t:
                out.append(("", normalize(t)))
    return out


def main():
    import difflib

    symbol = sys.argv[1]
    built_path = sys.argv[2]
    orig_path = sys.argv[3]
    context = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    built = norm(extract(objdump(built_path), symbol))
    orig = norm(extract(objdump(orig_path), symbol))
    bt = [x[1] for x in built]
    ot = [x[1] for x in orig]
    print(f"{symbol}: built {len(bt)} insns, orig {len(ot)} insns")
    sm = difflib.SequenceMatcher(a=ot, b=bt, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        print(f"--- {tag}: orig[{i1}:{i2}] vs built[{j1}:{j2}] ---")
        for k in range(max(0, i1 - context), min(len(ot), i2 + context)):
            mark = "!!" if i1 <= k < i2 else "  "
            print(f" {mark} O @{k:4d} {ot[k]}")
        for k in range(max(0, j1 - context), min(len(bt), j2 + context)):
            mark = "!!" if j1 <= k < j2 else "  "
            print(f" {mark} B @{k:4d} {bt[k]}")


if __name__ == "__main__":
    main()
