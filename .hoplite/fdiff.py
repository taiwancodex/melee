"""Structural diff of one function: orig asm vs built object, using the
harness's reloc-aware normalization so only real code differences show."""

import re
import sys
import difflib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import unit_tool as U


def norm_insn(off, text, keys):
    """mnemonic + operand shape with reloc sites folded to markers."""
    t = re.sub(r"<[^>]*>", "", text)
    t = re.sub(r";.*$", "", t).strip()
    # fold orig-style symbol operands: sym@kind / sym+0xN@kind
    for m in U.ORIG_REL_RE.finditer(t):
        t = t.replace(m.group(0), "REL")
    # fold call/tail-jump targets to a marker
    t = re.sub(r"^(bl|b)\s+[A-Za-z_.$@][\w.$]*$", r"\1 REL", t)
    # fold branch targets (labels or offsets): equivalent encodings
    t = re.sub(r"^(b[a-z.]*)\s+\S+$", r"\1 T", t)
    # normalize numbers
    t = re.sub(r"\b0x([0-9a-fA-F]+)\b",
               lambda m: str(int(m.group(1), 16)), t)
    t = re.sub(r"(?<![\w.])(\d+)(?![\w.])",
               lambda m: str(int(m.group(1))), t)
    # sda21 base registers are rewritten by the linker; fold them
    t = re.sub(r"REL\((?:r1[23]|r2|r0|0)\)", "REL", t)
    # built-side reloc placeholders (0 operands) become REL markers
    if keys:
        t = re.sub(r"(?<=[,\s(])0(?=[,\s)(]|$)", "REL", t, count=1)
    t = re.sub(r",\s+", ",", t)
    t = re.sub(r"\s+", " ", t)
    # sda21 base registers are rewritten by the linker; fold them
    t = re.sub(r"REL\([^)]*\)", "REL", t)
    if keys and keys[0][0] == "sda21":
        t = re.sub(r"^(?:li|addi) r\d+(?:,r1[3])?,REL$", "addi REL", t)
    if keys:
        t += " ; " + ",".join(f"{k}:{v}" for k, v in sorted(keys))
    return t


def main():
    symbols_text = (U.ROOT / "config/GALE01/symbols.txt").read_text()
    U.SYMBOLS, U.SYMBOL_SIZES = U.parse_symbols_text(symbols_text)
    U.OLD_SYMBOLS, _ = U.parse_symbols_text(
        U.git_show("config/GALE01/symbols.txt", U.ASM_COMMIT) or "")
    U.SPLITS = U.parse_splits()
    U.CURRENT_BY_ADDR, U.ADDRESS_INDEX = U.build_indexes()
    U.FUNCTION_NAMES = {
        m.group(1) for m in re.finditer(
            r'^(\S+) = \.text:[^;]+; // type:function',
            symbols_text, re.MULTILINE)}
    U.FUNCTION_ADDRS = {U.SYMBOLS[n][1] for n in U.FUNCTION_NAMES
                        if n in U.SYMBOLS and U.SYMBOLS[n][0] == ".text"}

    kind, source, extra = U.get_unit(sys.argv[1])
    asm = U.git_show(U.unit_asm_path(source), U.ASM_COMMIT)
    obj, rc, out = U.build_unit(source, kind, extra)
    if rc != 0:
        sys.exit(out[:2000])
    unit_secs = U.SPLITS[source]
    ofuncs = U.parse_orig_asm(asm)
    bfuncs, brelocs = U.parse_objdump_disasm(U.run_tool(U.OBJDUMP, "-dr",
                                                        str(obj)))
    obj_syms = U.parse_readelf_syms(obj)
    fname = sys.argv[2]
    name = fname if fname in ofuncs else next(
        (n for n in ofuncs if fname in n), None)
    bname = next((b for b in bfuncs if b == name), None) if name else None
    if bname is None:
        bname = next((b for b in bfuncs if fname in b), None)
    fn_range = U.function_range(name)
    oins = ofuncs.get(name, [])
    bins = bfuncs.get(bname, [])
    breloc = brelocs.get(bname, {})
    on = [norm_insn(o, t, U.orig_reloc_keys(t, unit_secs, fn_range))
          for o, b, t in oins]
    bn = [norm_insn(o, t, U.built_reloc_keys(breloc.get(o, []), obj_syms))
          for o, b, t in bins]
    print(f"orig {len(on)} built {len(bn)}  ({name} vs {bname})")
    sm = difflib.SequenceMatcher(None, on, bn, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        print(f"== {tag}: orig[{i1}:{i2}] ({i2-i1}) "
              f"built[{j1}:{j2}] ({j2-j1})")
        for k in range(max(0, i1 - 4), min(i2 + 4, len(on))):
            print(f"  O {oins[k][0]:08x} {on[k]}")
        print("  ---")
        for k in range(max(0, j1 - 4), min(j2 + 4, len(bn))):
            print(f"  B {bins[k][0]:08x} {bn[k]}")


if __name__ == "__main__":
    main()
