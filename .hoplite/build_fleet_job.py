#!/usr/bin/env python3
"""Build a permuter job for one target function end-to-end.

usage: build_fleet_job.py <jobdir> <src.c> <func> <split_unit> <start_regex>

Steps: dtk asm extraction + assembly, fidelity check vs the split object,
system-cpp preprocessing with the three parity fixes (MWERKS/POWERPC defines,
MUST_MATCH for pragma packs, basename __FILE__ in assert strings), TU strip
with callee fixpoint, and base.c/base_check.c emission.
"""
import os
import re
import subprocess
import sys

(jobdir, src, fn, unit, start_re) = sys.argv[1:6]
PY = "build/hoplite/pvenv/bin/python3"
os.makedirs(jobdir, exist_ok=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


run([PY, ".hoplite/dtk2gas.py",
     f"build/hoplite/dol_split/asm/{unit}.s", fn,
     f"{jobdir}/target.s"])
run(["build/tools/binutils/powerpc-eabi-as", "-mgekko",
     f"{jobdir}/target.s", "-o", f"{jobdir}/target.o"])
r = subprocess.run([PY, ".hoplite/fn_diff.py", fn, f"{jobdir}/target.o",
                    f"build/hoplite/dol_split/obj/{unit}.o"],
                   capture_output=True, text=True)
first = (r.stdout.strip().splitlines() or ["<no output>"])[0]
if "built" not in first or "orig" not in first:
    sys.exit(f"target fidelity check failed: {first}")

inc = "src/melee/gr" if unit.startswith("melee/gr") else "src/melee/mn"
cpp = subprocess.run(
    ["cpp", "-P", "-I", "src", "-I", "src/MSL", "-I", "src/Runtime",
     "-I", "extern/dolphin/include", "-I", "build/GALE01/include",
     "-I", "src/melee", "-I", inc, "-I", "src/melee/ft/kinds",
     "-I", "src/sysdolphin", "-D__MWERKS__", "-D__POWERPC__",
     "-DMUST_MATCH", "-U__GNUC__", "-U__clang__", src],
    capture_output=True)
if cpp.returncode != 0:
    sys.exit(f"cpp failed: {cpp.stderr.decode()[:200]}")
out = re.sub(rb'__assert\("[^"]*/', b'__assert("', cpp.stdout)
with open(f"{jobdir}/base_raw.c", "wb") as f:
    f.write(out)

r = subprocess.run([PY, ".hoplite/build_perm_job.py", jobdir,
                    f"{jobdir}/base_raw.c", fn, start_re, r"^\}"],
                   capture_output=True, text=True)
print(f"{jobdir}: {r.stdout.strip() or r.stderr[:200]}")
if r.returncode != 0:
    sys.exit(1)
with open(f"{jobdir}/settings.toml", "w") as f:
    f.write(f'func_name = "{fn}"\ncompiler_type = "mwcc"\n')
if not os.path.exists(f"{jobdir}/compile.sh"):
    os.symlink("/tmp/hoplite/workspace/build/hoplite/perm_gmtou/compile.sh",
               f"{jobdir}/compile.sh")
print(f"{jobdir} ready")
