#!/usr/bin/env python3
"""Systematic source-shape search for gmMainLib_8015DBF4's first block.

Phase 1: enumerate block shapes x base expressions, compile each with the
official MWCC command, and score by aligned instruction mismatches against
the DOL-original object. Logs incrementally to build/hoplite/block_search.log.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()
SCRATCH = ROOT / "build/hoplite/bs"
LOG = ROOT / "build/hoplite/block_search.log"
SRC_REL = "src/melee/gm/gmmain_lib.c"
SYMBOL = "gmMainLib_8015DBF4"
ORIG_OBJ = "build/GALE01/obj/melee/gm/gmmain_lib.o"

COMPILE = [
    "build/tools/wibo-qemu", "build/tools/sjiswrap.exe",
    "build/compilers/GC/1.2.5n/mwcceppc.exe",
    "-nowraplines", "-cwd", "source", "-Cpp_exceptions", "off",
    "-proc", "gekko", "-fp", "hardware", "-align", "powerpc",
    "-nosyspath", "-fp_contract", "on", "-O4,p", "-multibyte",
    "-enum", "int", "-nodefaults", "-inline", "auto",
    '-pragma', 'cats off', '-pragma', 'warn_notinlined off',
    "-RTTI", "off", "-str", "reuse", "-DBUILD_VERSION=0",
    "-DVERSION_GALE01", "-DMUST_MATCH", "-maxerrors", "1",
    "-msgstyle", "std", "-warn", "off",
    "-i", "src", "-i", "src/MSL", "-i", "src/Runtime",
    "-i", "extern/dolphin/include", "-i", "build/GALE01/include",
    "-i", "src/melee", "-i", "src/melee/ft/chara", "-i", "src/sysdolphin",
    "-lang=c", "-sym", "on", "-c", SRC_REL,
]

LINE_RE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*\t?(.*)$")
BRANCH_RE = re.compile(r"^(b[a-z.]*)\s+(.*)$")


def objdump_lines(path):
    out = subprocess.run(
        ["build/tools/binutils/powerpc-eabi-objdump", "-d", str(path)],
        capture_output=True, text=True, check=True).stdout.splitlines()
    start = None
    body = []
    pat = re.compile(r"^[0-9a-f]+ <(.+)>:")
    for line in out:
        m = pat.match(line)
        if m:
            if start is not None:
                break
            if m.group(1) == SYMBOL:
                start = True
            continue
        if start is not None and line.strip():
            body.append(line.rstrip())
    return body


def normalize(text):
    text = text.split("#")[0].strip()
    text = re.sub(r"<([^>+]+)(\+0x[0-9a-f]+)?>", r"\1", text)
    m = BRANCH_RE.match(text)
    if m and m.group(1) not in ("bctr", "bctrl"):
        mnem, rest = m.group(1), m.group(2)
        sym = re.search(r"<([^>+]+)", rest)
        if sym:
            return f"{mnem} {sym.group(1)}"
        return mnem + " L"
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


def score(built_obj, orig_norm):
    import difflib
    bt = norm_insns(objdump_lines(built_obj))
    sm = difflib.SequenceMatcher(a=orig_norm, b=bt, autojunk=False)
    bad = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            bad += max(i2 - i1, j2 - j1)
    return bad, len(bt)


BASE_GLOBAL = "&gmMainLib_804D3EE0->unk_530.unk_588[0]"
BASE_CAST = "((s8*) gmMainLib_804D3EE0->unk_530.unk_588 + 0)"
BASE_CONFIG = "&config_all->unk_530.unk_588[0]"
BASES = [("g", BASE_GLOBAL), ("c", BASE_CAST), ("k", BASE_CONFIG)]

IF_CACHED = """if (value == (u8) arg0) {{
        *tag_ptr = GM_NAMETAG_NONE;
    }} else if (value > (u8) arg0 && value != GM_NAMETAG_NONE) {{
        *tag_ptr = value - 1;
    }}"""

IF_COND_PTR = """if (*tag_ptr == (u8) arg0) {{
        *tag_ptr = GM_NAMETAG_NONE;
    }} else if (*tag_ptr > (u8) arg0 && *tag_ptr != GM_NAMETAG_NONE) {{
        *tag_ptr = *tag_ptr - 1;
    }}"""

BLOCKS = []
# local pointer + preloaded value, value source variants
for vname, vexpr in [("ptr", "*tag_ptr"), ("cfg", "config->x4"),
                     ("glob", "gmMainLib_804D3EE0->unk_51C.x4")]:
    BLOCKS.append((f"lp_val_{vname}", f"""{{
        u8* tag_ptr = &config->x4;
        u8 value = {vexpr};

        {IF_CACHED}
    }}"""))
    BLOCKS.append((f"lp_cc_val_{vname}", f"""{{
        u8* tag_ptr = (u8*) ((s8*) config + 4);
        u8 value = {vexpr};

        {IF_CACHED}
    }}"""))
# local pointer + load in condition
BLOCKS.append(("lp_cond_ptr", f"""{{
    u8* tag_ptr = &config->x4;

    {IF_COND_PTR}
}}"""))
BLOCKS.append(("lp_cc_cond_ptr", f"""{{
    u8* tag_ptr = (u8*) ((s8*) config + 4);

    {IF_COND_PTR}
}}"""))
# load in condition via global expression, stores via local pointer
BLOCKS.append(("lp_cond_glob", """{
    u8* tag_ptr = &config->x4;

    if (gmMainLib_804D3EE0->unk_51C.x4 == (u8) arg0) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (gmMainLib_804D3EE0->unk_51C.x4 > (u8) arg0 &&
               gmMainLib_804D3EE0->unk_51C.x4 != GM_NAMETAG_NONE) {
        *tag_ptr = gmMainLib_804D3EE0->unk_51C.x4 - 1;
    }
}"""))
# no pointer, direct member stores, value preloaded
for vname, vexpr in [("cfg", "config->x4"),
                     ("glob", "gmMainLib_804D3EE0->unk_51C.x4")]:
    BLOCKS.append((f"np_val_{vname}", f"""{{
        u8 value = {vexpr};

        if (value == (u8) arg0) {{
            config->x4 = GM_NAMETAG_NONE;
        }} else if (value > (u8) arg0 && value != GM_NAMETAG_NONE) {{
            config->x4 = value - 1;
        }}
    }}"""))
# macro shape on various fields
BLOCKS.append(("mac_glob", "    ADJ_NAMETAG_78(gmMainLib_804D3EE0->unk_51C.x4);"))
BLOCKS.append(("mac_cfg", "    ADJ_NAMETAG_78(config->x4);"))
BLOCKS.append(("mac_cfgall",
                "    ADJ_NAMETAG_78(config_all->unk_51C.x4);"))
# helper shapes
HELPER_PTR = """static inline void gmMainLib_AdjustNameTag(u8* tag_ptr, u8 tag)
{
    u8 value = *tag_ptr;

    if (value == tag) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (value > tag && value != GM_NAMETAG_NONE) {
        *tag_ptr = value - 1;
    }
}

"""
HELPER_VAL = """static inline void gmMainLib_AdjustNameTag(u8 value, u8* tag_ptr, u8 tag)
{
    if (value == tag) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (value > tag && value != GM_NAMETAG_NONE) {
        *tag_ptr = value - 1;
    }
}

"""
HELPER_COND = """static inline void gmMainLib_AdjustNameTag(u8* tag_ptr, u8 tag)
{
    if (*tag_ptr == tag) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (*tag_ptr > tag && *tag_ptr != GM_NAMETAG_NONE) {
        *tag_ptr = *tag_ptr - 1;
    }
}

"""
HELPER_VMD = """static inline void
gmMainLib_AdjustNameTag(struct gmm_x0_528_t* vmd, u8 tag)
{
    u8* ptr = &vmd->x4;
    u8 value = vmd->x4;

    if (value == tag) {
        *ptr = GM_NAMETAG_NONE;
    } else if (value > tag && value != GM_NAMETAG_NONE) {
        *ptr = value - 1;
    }
}

"""
HELPER_GLOB_LOAD = """static inline void
gmMainLib_AdjustNameTag(struct gmm_x0_528_t* store, u8 tag)
{
    u8* ptr = &store->x4;
    u8 value = gmMainLib_804D3EE0->unk_51C.x4;

    if (value == tag) {
        *ptr = GM_NAMETAG_NONE;
    } else if (value > tag && value != GM_NAMETAG_NONE) {
        *ptr = value - 1;
    }
}

"""
HELPER_CALLS = [
    ("h_ptr", HELPER_PTR,
     "    gmMainLib_AdjustNameTag(&config->x4, (u8) arg0);"),
    ("h_ptr_cc", HELPER_PTR,
     "    gmMainLib_AdjustNameTag((u8*) ((s8*) config + 4), (u8) arg0);"),
    ("h_cond", HELPER_COND,
     "    gmMainLib_AdjustNameTag(&config->x4, (u8) arg0);"),
    ("h_cond_cc", HELPER_COND,
     "    gmMainLib_AdjustNameTag((u8*) ((s8*) config + 4), (u8) arg0);"),
    ("h_val", HELPER_VAL,
     "    gmMainLib_AdjustNameTag(gmMainLib_804D3EE0->unk_51C.x4,"
     " &config->x4, (u8) arg0);"),
    ("h_val_cfg", HELPER_VAL,
     "    gmMainLib_AdjustNameTag(config->x4, &config->x4, (u8) arg0);"),
    ("h_vmd", HELPER_VMD,
     "    gmMainLib_AdjustNameTag(config, (u8) arg0);"),
    ("h_glob", HELPER_GLOB_LOAD,
     "    gmMainLib_AdjustNameTag(config, (u8) arg0);"),
]

UPSTREAM = subprocess.run(
    ["git", "show", f"HEAD:{SRC_REL}"], capture_output=True, text=True,
    check=True, cwd=ROOT).stdout

REGION_RE = re.compile(
    r"    config = gmMainLib_8015CDC8\(\);\n"
    r"    config_all = \(struct gmMainLib_8015DBF4_config\*\) config;\n"
    r"    base = \(struct gmMainLib_8015DBF4_base\*\)"
    r" &config_all->unk_530\.unk_588\[0\];\n"
    r"    gmMainLib_AdjustNameTag\(&config->x4, \(u8\) arg0\);\n")


def build_source(block_text, base_expr, helper=""):
    m = REGION_RE.search(UPSTREAM)
    if not m:
        sys.exit("upstream region not found")
    region = m.group(0)
    new = (f"    config = gmMainLib_8015CDC8();\n"
           f"    config_all = (struct gmMainLib_8015DBF4_config*) config;\n"
           + (f"    base = (struct gmMainLib_8015DBF4_base*) {base_expr};\n"
              if base_expr else "")
           + f"{block_text}\n")
    src = UPSTREAM.replace(region, new, 1)
    if helper:
        # drop upstream's own helper to avoid redeclaration
        old_helper = UPSTREAM[UPSTREAM.index(
            "inline void gmMainLib_AdjustNameTag("):]
        old_helper = old_helper[:old_helper.index("\n}\n") + 3]
        src = src.replace(old_helper + "\n", "", 1)
        anchor = "s32 gmMainLib_8015DBF4(s32 arg0)"
        src = src.replace(anchor, helper + anchor, 1)
    return src


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "1"
    orig_norm = norm_insns(objdump_lines(ROOT / ORIG_OBJ))
    variants = []
    if phase == "1":
        for bname, btext in BLOCKS:
            for basename, bexpr in BASES:
                variants.append((f"{bname}|{basename}", btext, bexpr, ""))
        for hname, helper, call in HELPER_CALLS:
            for basename, bexpr in BASES:
                variants.append((f"{hname}|{basename}", call, bexpr, helper))
    else:
        # Phase 8: full 3D grid of pointer x load x base expressions
        ptrs = {
            "pcc": "(u8*) ((s8*) config + 4)",
            "pcca": "(u8*) ((s8*) config_all + 4)",
            "ppl": "&config->x4",
            "pmem": "(u8*) &config_all->unk_51C.x4",
        }
        conds = {
            "lptr": IF_COND_PTR,
            "lall": """if (config_all->unk_51C.x4 == (u8) arg0) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (config_all->unk_51C.x4 > (u8) arg0 &&
               config_all->unk_51C.x4 != GM_NAMETAG_NONE) {
        *tag_ptr = config_all->unk_51C.x4 - 1;
    }""",
            "lcfg": """if (config->x4 == (u8) arg0) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (config->x4 > (u8) arg0 && config->x4 != GM_NAMETAG_NONE) {
        *tag_ptr = config->x4 - 1;
    }""",
            "lcc": """if (*(u8*) ((s8*) config_all + 4) == (u8) arg0) {
        *tag_ptr = GM_NAMETAG_NONE;
    } else if (*(u8*) ((s8*) config_all + 4) > (u8) arg0 &&
               *(u8*) ((s8*) config_all + 4) != GM_NAMETAG_NONE) {
        *tag_ptr = *(u8*) ((s8*) config_all + 4) - 1;
    }""",
        }
        variants = []
        for pn, pe in ptrs.items():
            for ln, le in conds.items():
                for bn, be in [("g", BASE_GLOBAL), ("c", BASE_CAST)]:
                    variants.append((
                        f"{pn}|{ln}|{bn}",
                        f"{{\n    u8* tag_ptr = {pe};\n\n    {le}\n}}",
                        be, ""))

    SCRATCH.mkdir(parents=True, exist_ok=True)
    results = []
    with LOG.open("w", encoding="utf-8") as log:
        log.write(f"# phase {phase}: {len(variants)} variants\n")
        for idx, (name, btext, bexpr, helper) in enumerate(variants):
            tag = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            src = build_source(btext, bexpr, helper)
            (ROOT / SRC_REL).write_text(src, encoding="utf-8")
            outdir = SCRATCH / f"v{idx:03d}"
            outdir.mkdir(exist_ok=True)
            r = subprocess.run(
                COMPILE + ["-o", str(outdir.relative_to(ROOT))],
                capture_output=True, text=True, cwd=ROOT)
            obj = outdir / "gmmain_lib.o"
            if r.returncode != 0 or not obj.exists():
                log.write(f"[{idx:03d}] {name}: COMPILE FAIL\n")
                log.flush()
                results.append((999, name))
                continue
            bad, n = score(obj, orig_norm)
            log.write(f"[{idx:03d}] {name}: score={bad} insns={n}\n")
            log.flush()
            results.append((bad, name))
        # restore upstream source
        (ROOT / SRC_REL).write_text(UPSTREAM, encoding="utf-8")
        results.sort()
        log.write("\n=== RANKED ===\n")
        for bad, name in results[:15]:
            log.write(f"{bad:4d}  {name}\n")
    for bad, name in results[:15]:
        print(f"{bad:4d}  {name}")


if __name__ == "__main__":
    main()
