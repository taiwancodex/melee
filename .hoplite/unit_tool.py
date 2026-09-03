#!/usr/bin/env python3
"""Harness for matching remaining (Linkable) functions in the melee decomp.

Compiles a Linkable unit's C with the exact build flags (mwcc via wibo+qemu)
and diffs the resulting object against the unit's original assembly
(recovered from git history) function by function.

Subcommands:
  list    - enumerate Linkable units and original-asm availability
  build   - compile one unit
  compare - diff compiled object vs original asm, per function
  rank    - build+compare every Linkable unit with recoverable asm
  show    - side-by-side disassembly of one function for manual fixing
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASM_COMMIT = "e5908352e^"  # last commit before the asm/ folder was nuked
QEMU = "qemu-i386-static"
WIBO = ROOT / "build/tools/wibo32"
MWCC = ROOT / "build/compilers/GC/1.2.5n/mwcceppc.exe"
OBJDUMP = ROOT / "build/tools/binutils/powerpc-eabi-objdump"
READELF = ROOT / "build/tools/binutils/powerpc-eabi-readelf"
OUTDIR = ROOT / "build/hoplite"

CFLAGS_BASE = [
    "-c", "-nowraplines", "-cwd", "source", "-Cpp_exceptions", "off",
    "-proc", "gekko", "-fp", "hardware", "-align", "powerpc", "-nosyspath",
    "-fp_contract", "on", "-O4,p", "-multibyte", "-enum", "int",
    "-nodefaults", "-inline", "auto", "-pragma", "cats off", "-pragma",
    "warn_notinlined off", "-RTTI", "off", "-str", "reuse",
    "-DBUILD_VERSION=0", "-DVERSION_GALE01", "-DMUST_MATCH",
    "-maxerrors", "1", "-msgstyle", "std", "-warn", "off", "-sym", "on",
]

MELEE_INCLUDES = [
    "-i", "src", "-i", "src/MSL", "-i", "src/Runtime",
    "-i", "extern/dolphin/include", "-i", "build/GALE01/include",
    "-i", "src/melee", "-i", "src/melee/ft/chara", "-i", "src/sysdolphin",
]

SYSDOLPHIN_INCLUDES = [
    "-i", "src", "-i", "src/MSL", "-i", "src/Runtime",
    "-i", "extern/dolphin/include", "-i", "build/GALE01/include",
    "-i", "src/sysdolphin", "-i", "build/GALE01/sysdolphin",
]

RELOC_KIND = {
    "R_PPC_ADDR16_HA": "ha", "R_PPC_ADDR16_LO": "l", "R_PPC_ADDR16_Hi": "h",
    "R_PPC_EMB_SDA21": "sda21", "R_PPC_REL24": "rel24",
    "R_PPC_REL14": "rel14", "R_PPC_ADDR16": "a16",
}


# ---------------- configure.py / symbols / splits parsing ----------------

def parse_configure():
    text = (ROOT / "configure.py").read_text()
    lib_re = re.compile(
        r'\b(MeleeLib|SysdolphinLib|DolphinLib|RuntimeLib|Libc|TRKLib)\(')
    obj_re = re.compile(
        r'Object\(\s*(Matching|Linkable|Equivalent|True|False'
        r'|MatchingFor\([^)]*\))\s*,\s*"([^"]+)"(.*?)\)',
        re.DOTALL)
    units = []
    starts = [(m.start(), m.group(1)) for m in lib_re.finditer(text)]
    for i, (pos, kind) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        chunk = text[pos:end]
        for m in obj_re.finditer(chunk):
            status, source, tail = m.group(1), m.group(2), m.group(3)
            extra = []
            em = re.search(r'extra_cflags=\[(.*?)\]', tail, re.DOTALL)
            if em:
                extra = re.findall(r'"([^"]+)"', em.group(1))
            units.append((kind, status, source, extra))
    return units


def parse_symbols_text(text):
    """Return (syms, sizes): name -> (section, addr) and name -> size."""
    syms, sizes = {}, {}
    for line in text.splitlines():
        m = re.match(r'^(\S+) = (\.\w+):(0x[0-9A-Fa-f]+);', line)
        if m:
            syms[m.group(1)] = (m.group(2), int(m.group(3), 16))
        ms = re.search(r'size:(0x[0-9A-Fa-f]+)', line)
        if m and ms:
            sizes[m.group(1)] = int(ms.group(1), 16)
    return syms, sizes


def parse_splits():
    splits = {}
    cur_unit, cur = None, None
    for line in (ROOT / "config/GALE01/splits.txt").read_text().splitlines():
        m = re.match(r'^(\S+\.c):\s*$', line)
        if m:
            cur_unit, cur = m.group(1), {}
            splits[cur_unit] = cur
            continue
        m = re.match(
            r'^\s*(\.\w+)\s+start:(0x[0-9A-Fa-f]+) end:(0x[0-9A-Fa-f]+)', line)
        if m and cur_unit:
            cur[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return splits


SYMBOLS = None      # current symbols.txt
SYMBOL_SIZES = None
OLD_SYMBOLS = None  # symbols.txt at ASM_COMMIT (era of the original asm)
SPLITS = None
CURRENT_BY_ADDR = None   # (section, addr) -> current real symbol name
ADDRESS_INDEX = None     # addr -> (section, current real symbol name)
FUNCTION_NAMES = None    # current symbols marked type:function
FUNCTION_ADDRS = None    # addresses of current .text function symbols


def build_indexes():
    by_addr = {}
    current = {}
    for table, use_name in ((SYMBOLS, True), (OLD_SYMBOLS, False)):
        for name, (section, addr) in table.items():
            if name.startswith(("@", ".", "...")):
                continue
            if addr not in by_addr:
                by_addr[addr] = (section, name if use_name else None)
            if use_name:
                current.setdefault((section, addr), name)
    for addr, (section, name) in by_addr.items():
        if name is None:
            cur = current.get((section, addr))
            by_addr[addr] = (section, cur)
    return current, by_addr


def resolve_orig_symbol(name, unit_secs):
    """Resolve an original-asm symbol name to a comparison key.

    Same-unit data symbols compare by (section, offset); everything else
    compares by name. Names from the original-asm era are aliased to the
    current symbol at the same address (via symbol tables or the hex
    address embedded in the name), so renames compare equal.
    """
    section = addr = None
    if name in SYMBOLS:
        section, addr = SYMBOLS[name]
    else:
        if name in OLD_SYMBOLS:
            section, addr = OLD_SYMBOLS[name]
        else:
            # era-renamed symbols usually embed their address in the name
            # (e.g. lb_80433380 -> lbSnap_80433380, fn_8016FAD4 -> ...)
            for m in re.finditer(r'([0-9A-Fa-f]{8})', name):
                cand = int(m.group(1), 16)
                if cand >= 0x80000000 and cand in ADDRESS_INDEX:
                    section, addr = ADDRESS_INDEX[cand][0], cand
                    break
        if section is not None:
            alias = CURRENT_BY_ADDR.get((section, addr))
            if alias:
                name = alias
        else:
            # dolphin-lib renames (e.g. MTXScale -> PSMTXScale)
            if "PS" + name in SYMBOLS:
                return ("name", "PS" + name)
            return ("name", name)
    if section == ".text" or section not in unit_secs:
        return ("name", name)
    s, e = unit_secs[section]
    if s <= addr < e:
        return ("pos", section, addr - s)
    return ("name", name)


def unit_asm_path(source):
    return "asm/" + source[:-2] + ".s"


def git_show(path, commit):
    p = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT,
                       capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


# ---------------- original asm parsing ----------------

INSN_RE = re.compile(
    r'^/\* ([0-9A-Fa-f]{8}) ([0-9A-Fa-f]{8})\s+'
    r'((?:[0-9A-Fa-f]{2} )*[0-9A-Fa-f]{2}) \*/\t(.*)$')
FN_RE = re.compile(r'^\.fn\s+(\S+),\s*(\S+)')
ENDFN_RE = re.compile(r'^\.endfn\s+(\S+)')
ORIG_REL_RE = re.compile(
    r'([A-Za-z_.$@][\w.$]*)\+?(0x[0-9a-fA-F]+)?@(ha|l|h|sda21)\b')
CALL_RE = re.compile(r'^(bl|b)\s+([A-Za-z_.$@][\w.$]*)$')


def label_to_function(label):
    """Map a top-level asm label to the current function name it denotes.

    Old-format splitters write static functions as `.L_<addr>` labels and
    may use era names; resolve via current symbol tables when possible.
    Returns None for labels that are not functions.
    """
    if label in FUNCTION_NAMES:
        return label
    if label.startswith(".L_"):
        rest = label[3:]
        if rest in FUNCTION_NAMES:
            return rest
        if re.fullmatch(r'[0-9A-Fa-f]{8}', rest):
            addr = int(rest, 16)
            if addr in FUNCTION_ADDRS:
                return CURRENT_BY_ADDR.get((".text", addr), rest)
    return None


def parse_orig_asm(asm_text):
    """Return {name: [(offset, bytes, text)]} for functions.

    Handles both splitter generations: newer `.fn NAME, scope` blocks and
    older `.global NAME` + `NAME:` labels inside .text. In the old format
    only labels that denote known functions start a new function; `.L_`
    jump-target labels stay inside the current function.
    """
    funcs = {}
    cur = None
    fn_style = None   # "fn" or "global"
    section = ".text"
    pending_global = None
    for line in asm_text.splitlines():
        m = FN_RE.match(line)
        if m:
            cur, fn_style = m.group(1), "fn"
            funcs[cur] = []
            continue
        if ENDFN_RE.match(line):
            cur, fn_style = None, None
            continue
        m = re.match(r'^\.section\s+(\S+)', line)
        if m:
            section = m.group(1)
            if fn_style == "global":
                cur = None
            continue
        m = re.match(r'^\.global\s+(\S+)', line)
        if m:
            pending_global = m.group(1)
            continue
        m = re.match(r'^([A-Za-z_.$][\w.$]*):$', line)
        if m and section.startswith(".text"):
            label = m.group(1)
            fname = label_to_function(label)
            if fname is None and label == pending_global:
                fname = label  # externally visible but unknown symbol
            if fname is not None:
                cur, fn_style = fname, "global"
                funcs[cur] = []
                pending_global = None
            # otherwise: jump target or data label; stay in current fn
            continue
        if cur is None:
            continue
        m = INSN_RE.match(line)
        if m:
            funcs[cur].append(
                (int(m.group(1), 16), m.group(3).replace(" ", "").lower(),
                 m.group(4)))
    return funcs


def orig_reloc_keys(text, unit_secs, fn_range=None):
    """Extract resolved reloc keys for an original-asm instruction.

    Branches to labels inside the same function are plain branches, not
    relocations, so they are dropped (their bytes encode the target).
    """
    keys = []
    for m in ORIG_REL_RE.finditer(text):
        name, add, kind = m.group(1), m.group(2), m.group(3)
        key = resolve_orig_symbol(name, unit_secs)
        if add and key[0] == "pos":
            key = ("pos", key[1], key[2] + int(add, 16))
        keys.append((kind, key))
    m = CALL_RE.match(text.strip())
    if m and not m.group(2).startswith(".L_"):
        target = m.group(2)
        key = resolve_orig_symbol(target, unit_secs)
        inside = False
        if fn_range:
            if target in SYMBOLS and SYMBOLS[target][0] == ".text":
                taddr = SYMBOLS[target][1]
            else:
                taddr = None
                for mm in re.finditer(r'([0-9A-Fa-f]{8})', target):
                    cand = int(mm.group(1), 16)
                    if cand >= 0x80000000:
                        taddr = cand
                        break
            if taddr is not None and fn_range[0] <= taddr < fn_range[1]:
                inside = True
        if not inside:
            keys.append(("rel24", key))
    return keys


# ---------------- built object parsing ----------------

def run_tool(path, *flags):
    p = subprocess.run([str(path), *flags], cwd=ROOT, capture_output=True,
                       text=True)
    if p.returncode != 0:
        sys.exit(f"{path} failed: {p.stderr}")
    return p.stdout


def parse_objdump_disasm(stdout):
    funcs = {}
    relocs = {}
    cur, section = None, None
    sym_re = re.compile(r'^([0-9a-f]+) <([^>]+)>:$')
    ins_re = re.compile(r'^\s+([0-9a-f]+):\t([0-9a-f ]+?)\t(\S.*)$')
    rel_re = re.compile(r'^\s+([0-9a-f]+): (R_\S+)\s*(.*)$')
    sec_re = re.compile(r'^Disassembly of section (\S+):$')
    for line in stdout.splitlines():
        m = sec_re.match(line)
        if m:
            section = m.group(1)
            continue
        if section != ".text":
            continue
        m = sym_re.match(line)
        if m:
            cur = m.group(2)
            funcs[cur] = []
            relocs[cur] = {}
            continue
        if cur is None:
            continue
        m = rel_re.match(line)
        if m:
            off = int(m.group(1), 16)
            relocs[cur].setdefault(off, []).append(
                (m.group(2), m.group(3).strip()))
            continue
        m = ins_re.match(line)
        if m:
            funcs[cur].append((int(m.group(1), 16),
                               m.group(2).replace(" ", "").lower(),
                               m.group(3).strip()))
    # map field-offset relocs (ADDR16 at insn+2) onto their instruction
    for name, rmap in relocs.items():
        ins_offsets = [i[0] for i in funcs.get(name, [])]
        fixed = {}
        for off, entries in rmap.items():
            owner = next((io for io in ins_offsets if io <= off < io + 4),
                         off)
            fixed.setdefault(owner, []).extend(entries)
        relocs[name] = fixed
    return funcs, relocs


def parse_readelf_syms(obj_path):
    """name -> (section, offset) for defined symbols, via readelf."""
    sections = {}
    for line in run_tool(READELF, "-SW", str(obj_path)).splitlines():
        m = re.match(r'\s*\[\s*(\d+)\]\s+(\S+)\s+(\S+)', line)
        if m:
            sections[int(m.group(1))] = m.group(2)
    syms = {}
    for line in run_tool(READELF, "-sW", str(obj_path)).splitlines():
        m = re.match(
            r'\s*\d+:\s+([0-9a-fA-F]+)\s+\S+\s+\S+\s+\S+\s+\S+'
            r'\s+(\d+|UND)\s+(\S+)$', line)
        if m and m.group(2) != "UND":
            ndx = int(m.group(2))
            if ndx in sections:
                syms[m.group(3)] = (sections[ndx], int(m.group(1), 16))
    return syms


def built_reloc_keys(entries, obj_syms):
    """Resolve objdump reloc entries to comparison keys.

    Data symbols defined in this object compare by (section, offset);
    function symbols and externals compare by name.
    """
    keys = []
    for rtype, target in entries:
        kind = RELOC_KIND.get(rtype, rtype)
        m = re.match(r'^(\S+?)(?:\+0x([0-9a-fA-F]+))?$', target)
        if not m:
            keys.append((kind, ("name", target)))
            continue
        name, add = m.group(1), m.group(2)
        add = int(add, 16) if add else 0
        if name in obj_syms:
            section, off = obj_syms[name]
            if section == ".text":
                keys.append((kind, ("name", name)))
            else:
                keys.append((kind, ("pos", section, off + add)))
        else:
            keys.append((kind, ("name", name)))
    return keys


# ---------------- comparison ----------------

def function_range(name):
    if name in SYMBOL_SIZES and name in SYMBOLS:
        section, addr = SYMBOLS[name]
        if section == ".text":
            return (addr, addr + SYMBOL_SIZES[name])
    return None


def compare_function(oinsns, binsns, breloc, obj_syms, renames, unit_secs,
                     fn_name=None):
    """Return (status, detail). oinsns/binsns: [(off, bytes, text)]."""
    fn_range = function_range(fn_name) if fn_name else None
    if len(oinsns) != len(binsns):
        return ("SIZE", f"orig {len(oinsns)} vs built {len(binsns)} insns")
    for (oa, ob, otext), (ba, bb, btext) in zip(oinsns, binsns):
        okeys = orig_reloc_keys(otext, unit_secs, fn_range)
        bkeys = built_reloc_keys(breloc.get(ba, []), obj_syms)
        bkeys = [(k, renames.get(v, v) if v[0] == "name" else v)
                 for k, v in bkeys]
        # old-era asm bakes final addresses into reloc sites, so compare
        # resolved keys only; bytes are only authoritative for plain
        # instructions
        if bool(okeys) != bool(bkeys):
            return ("DIFF", f"@{oa:#x} reloc mismatch {okeys} vs {bkeys}"
                    f" | orig '{otext}' vs built '{btext}'")
        if not okeys and ob != bb:
            return ("DIFF", f"@{oa:#x} bytes {ob} vs {bb}"
                    f" | orig '{otext}' vs built '{btext}'")
        if sorted(okeys) != sorted(bkeys):
            return ("DIFF", f"@{oa:#x} relocs {okeys} vs {bkeys}"
                    f" | orig '{otext}' vs built '{btext}'")
    return ("MATCH", None)


def compare_unit(orig_asm_text, obj_path, source):
    unit_secs = SPLITS[source]
    ofuncs = parse_orig_asm(orig_asm_text)
    bfuncs, brelocs = parse_objdump_disasm(run_tool(OBJDUMP, "-dr",
                                                    str(obj_path)))
    obj_syms = parse_readelf_syms(obj_path)

    # rename map: current name -> orig name for identical bodies
    renames = {}
    paired = {}  # orig name -> built name
    missing = [n for n in ofuncs if n not in bfuncs]
    extra = [n for n in bfuncs if n not in ofuncs]
    for oname in list(missing):
        for bname in list(extra):
            st, _ = compare_function(ofuncs[oname], bfuncs[bname],
                                     brelocs[bname], obj_syms, {}, unit_secs,
                                     fn_name=oname)
            if st == "MATCH":
                renames[("name", bname)] = ("name", oname)
                paired[oname] = bname
                missing.remove(oname)
                extra.remove(bname)
                break

    report = {}
    for name, insns in ofuncs.items():
        if name in paired:
            report[name] = ("MATCH", len(insns), len(insns),
                            f"renamed to {paired[name]}")
            continue
        if name not in bfuncs:
            report[name] = ("missing", 0, len(insns), "not in object")
            continue
        st, detail = compare_function(insns, bfuncs[name], brelocs[name],
                                      obj_syms, renames, unit_secs,
                                      fn_name=name)
        report[name] = (st, len(bfuncs[name]), len(insns), detail)
    for name in extra:
        report[f"{name} (built-only)"] = ("extra", len(bfuncs[name]), 0,
                                          "not in original")
    return report


# ---------------- build ----------------

def build_unit(source, lib_kind, extra_cflags):
    includes = (SYSDOLPHIN_INCLUDES if lib_kind == "SysdolphinLib"
                else MELEE_INCLUDES)
    flags = list(CFLAGS_BASE)
    if "-Cpp_exceptions on" in extra_cflags:
        idx = flags.index("-Cpp_exceptions")
        flags[idx + 1] = "on"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    obj = OUTDIR / (source.replace("/", "_")[:-2] + ".o")
    srcfile = ("extern/dolphin/src/" if lib_kind == "DolphinLib"
               else "src/") + source
    # the real build converts UTF-8 sources to Shift-JIS via sjiswrap
    # before mwcc sees them; convert into a symlink shadow tree so quoted
    # includes still resolve next to the file
    raw = (ROOT / srcfile).read_bytes()
    if any(b > 0x7F for b in raw):
        shadow = ROOT / "build/hoplite/sjis" / srcfile
        shadow.parent.mkdir(parents=True, exist_ok=True)
        if shadow.is_symlink():
            shadow.unlink()
        shadow.write_bytes(raw.decode("utf-8").encode("cp932"))
        srcfile = str(shadow.relative_to(ROOT))
    cmd = [QEMU, str(WIBO), str(MWCC), *flags, *includes,
           "-o", str(obj), srcfile]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       timeout=1200)
    return obj, p.returncode, (p.stdout + p.stderr).strip()


# ---------------- driver ----------------

def get_unit(selector):
    for kind, status, source, extra in parse_configure():
        if status == "Linkable" and selector in source:
            return kind, source, extra
    sys.exit(f"no Linkable unit matching {selector!r}")


def main():
    global SYMBOLS, SYMBOL_SIZES, OLD_SYMBOLS, SPLITS
    global CURRENT_BY_ADDR, ADDRESS_INDEX, FUNCTION_NAMES, FUNCTION_ADDRS
    symbols_text = (ROOT / "config/GALE01/symbols.txt").read_text()
    SYMBOLS, SYMBOL_SIZES = parse_symbols_text(symbols_text)
    OLD_SYMBOLS, _ = parse_symbols_text(
        git_show("config/GALE01/symbols.txt", ASM_COMMIT) or "")
    SPLITS = parse_splits()
    CURRENT_BY_ADDR, ADDRESS_INDEX = build_indexes()
    FUNCTION_NAMES = {
        m.group(1) for m in
        re.finditer(r'^(\S+) = \.text:[^;]+; // type:function',
                    symbols_text, re.MULTILINE)}
    FUNCTION_ADDRS = {
        SYMBOLS[n][1] for n in FUNCTION_NAMES
        if n in SYMBOLS and SYMBOLS[n][0] == ".text"}
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "build", "compare", "rank",
                                    "show"])
    ap.add_argument("unit", nargs="?")
    ap.add_argument("func", nargs="?")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.cmd == "list":
        for kind, status, source, extra in parse_configure():
            if status != "Linkable":
                continue
            asm = git_show(unit_asm_path(source), ASM_COMMIT)
            print(f"{kind:14s} {source:55s} "
                  f"asm={'yes' if asm else 'NO'} extra={extra}")
        return

    if args.cmd == "rank":
        for kind, status, source, extra in parse_configure():
            if status != "Linkable":
                continue
            asm = git_show(unit_asm_path(source), ASM_COMMIT)
            if not asm:
                print(f"== {source}: no original asm in history, skipping")
                continue
            obj, rc, out = build_unit(source, kind, extra)
            if rc != 0 or not obj.exists():
                print(f"== {source}: COMPILE FAILED\n{out[:1500]}")
                continue
            rep = compare_unit(asm, obj, source)
            bad = {k: v for k, v in rep.items() if v[0] != "MATCH"}
            print(f"== {source}: {len(rep) - len(bad)}/{len(rep)} match")
            for name, (st, bn, on, detail) in sorted(bad.items()):
                print(f"   [{st:7s}] {name} ({on} insns)")
        return

    kind, source, extra = get_unit(args.unit)
    asm = git_show(unit_asm_path(source), ASM_COMMIT)
    if not asm:
        sys.exit(f"no original asm in history for {source}")
    obj, rc, out = build_unit(source, kind, extra)
    if rc != 0 or not obj.exists():
        sys.exit(f"compile failed:\n{out[:3000]}")

    if args.cmd == "build":
        print(f"built {obj}")
        return

    if args.cmd == "compare":
        rep = compare_unit(asm, obj, source)
        bad = {k: v for k, v in rep.items() if v[0] != "MATCH"}
        print(f"== {source}: {len(rep) - len(bad)}/{len(rep)} match")
        for name, (st, bn, on, detail) in sorted(rep.items()):
            mark = "ok " if st == "MATCH" else "BAD"
            print(f"   [{mark}] [{st:7s}] {name} ({on} insns)"
                  + (f" - {detail}" if args.verbose and detail else ""))
        return

    if args.cmd == "show":
        if not args.func:
            sys.exit("show requires a function name")
        unit_secs = SPLITS[source]
        ofuncs = parse_orig_asm(asm)
        bfuncs, brelocs = parse_objdump_disasm(run_tool(OBJDUMP, "-dr",
                                                        str(obj)))
        obj_syms = parse_readelf_syms(obj)
        name = args.func
        if name not in ofuncs:
            name = next((n for n in ofuncs if args.func in n), None)
        bname = None
        if name:
            bname = next((b for b in bfuncs if b == name), None)
        if bname is None:
            bname = next((b for b in bfuncs if args.func in b), None)
        if name is None or bname is None:
            sys.exit(f"function {args.func!r} not found on both sides")
        fn_range = function_range(name)
        oins = ofuncs.get(name, [])
        bins = bfuncs.get(bname, [])
        breloc = brelocs.get(bname, {})
        for i in range(max(len(oins), len(bins))):
            if i < len(oins):
                oa, ob, otext = oins[i]
                ok = orig_reloc_keys(otext, unit_secs, fn_range)
                print(f"O {oa:08x} {ob} {otext}"
                      + (f"   ; {ok}" if ok else ""))
            if i < len(bins):
                ba, bb, btext = bins[i]
                bk = built_reloc_keys(breloc.get(ba, []), obj_syms)
                print(f"B {ba:08x} {bb} {btext}"
                      + (f"   ; {bk}" if bk else ""))
            if i < len(oins) and i < len(bins):
                if oins[i][1] != bins[i][1]:
                    print("   ^^ BYTES DIFFER")


if __name__ == "__main__":
    main()
