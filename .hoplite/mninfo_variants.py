#!/usr/bin/env python3
"""Compile mninfo.c variants of the Up-branch id declaration and diff each.

Base shape: upstream's hand-written Up loop (only the id register differs
from the target). Variants patch only the id declaration/assignment.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()
BUILD = ROOT / "build/hoplite/mninfo_variants"
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
    "-lang=c", "-sym", "on", "-c",
]

UPSTREAM_BLOCK = """            DECLS
            gobj = mnInfo_804D6C78;
            trophy = &mnInfo_804A0968[data->scroll_idx];
            for (i = 0; i < 4; i++) {
                if (mnInfo_80251A08(*trophy) != 0) {
                    IDDECL

                    mnInfo_80251D58(gobj, i, id, *gmMainLib_8015D804(id));
                    mnInfo_80251F04(gobj, i, id);
                }
                trophy++;
            }"""

STD_DECLS = ("            u8* trophy;\n            s32 i;\n"
             "            mnInfo_GObj* gobj;\n")

CALL_SITE = "        mnInfo_FreeEntries();\n        mnInfo_CreateEntries(data->scroll_idx);"


def make_variant(iddecl: str, decls: str) -> str:
    src = (ROOT / "src/melee/mn/mninfo.c").read_text(encoding="utf-8")
    block = UPSTREAM_BLOCK.replace("IDDECL", iddecl).replace("DECLS", decls)
    body = ("        mnInfo_FreeEntries();\n        {\n" + block
            + "\n        }")
    if CALL_SITE not in src:
        sys.exit("call site not found; source changed")
    return src.replace(CALL_SITE, body, 1)


def ensure_tree() -> Path:
    tree = BUILD / "tree"
    if not (tree / "src").exists():
        tree.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-rs", str(ROOT / "src"), str(tree / "src")],
                       check=True, cwd=BUILD)
    target = tree / "src/melee/mn/mninfo.c"
    if target.is_symlink() or target.exists():
        target.unlink()
    return target


def compile_variant(name: str, text: str) -> int:
    vdir = BUILD / name
    vdir.mkdir(parents=True, exist_ok=True)
    cpath = ensure_tree()
    cpath.write_text(text, encoding="utf-8")
    outdir = vdir / "out"
    outdir.mkdir(exist_ok=True)
    cmd = COMPILE + [str(cpath.relative_to(ROOT)), "-o", str(outdir.relative_to(ROOT))]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print(f"[{name}] COMPILE FAILED:\n{r.stdout}\n{r.stderr}")
        return r.returncode
    d = subprocess.run(
        ["python3", ".hoplite/fn_diff.py", "fn_80251FE4",
         str((outdir / "mninfo.o").relative_to(ROOT)),
         "build/GALE01/obj/melee/mn/mninfo.o"],
        capture_output=True, text=True, cwd=ROOT)
    out = d.stdout
    first = out.splitlines()[0] if out else "no output"
    nmm = sum(1 for l in out.splitlines() if l.startswith("---"))
    print(f"[{name}] {first} | diff-blocks={nmm}")
    for l in out.splitlines():
        if l.startswith(" !!"):
            print("   ", l)
    return 0


VARIANTS = [
    ("u8_inner", "u8 id = *trophy;", STD_DECLS),
    ("u8_inner_reg", "register u8 id = *trophy;", STD_DECLS),
    ("u32_inner", "u32 id = *trophy;", STD_DECLS),
    ("s32_inner", "s32 id = *trophy;", STD_DECLS),
    ("u8_block", "id = *trophy;", "            u8 id;\n" + STD_DECLS),
    ("u8_block_first", "id = *trophy;",
     "            u8 id;\n" + STD_DECLS),
]


def main():
    for name, iddecl, decls in VARIANTS:
        compile_variant(name, make_variant(iddecl, decls))


if __name__ == "__main__":
    main()
