#!/usr/bin/env python3
"""Gate a permuter job: compile base_check.c with MWCC, then fn_diff it
against both the full-file build object (must be identical) and the
original target object (the known delta).

usage: gate_fleet_job.py <jobdir> <func> <full_obj_relpath>
"""
import os
import subprocess
import sys

(jobdir, fn, full_obj) = sys.argv[1:4]
PY = "build/hoplite/pvenv/bin/python3"

cc = ["build/tools/wibo-qemu", "build/tools/sjiswrap.exe",
      "build/compilers/GC/1.2.5n/mwcceppc.exe", "-nowraplines",
      "-Cpp_exceptions", "off", "-proc", "gekko", "-fp", "hardware",
      "-align", "powerpc", "-nosyspath", "-fp_contract", "on",
      "-O4,p", "-multibyte", "-enum", "int", "-nodefaults",
      "-inline", "auto", "-pragma", "cats off", "-pragma",
      "warn_notinlined off", "-RTTI", "off", "-str", "reuse",
      "-DBUILD_VERSION=0", "-DVERSION_GALE01", "-DMUST_MATCH",
      "-maxerrors", "1", "-msgstyle", "std", "-warn", "off",
      "-lang=c", "-sym", "off", "-c"]
r = subprocess.run(cc + ["-o", f"{jobdir}/check.o", f"{jobdir}/base_check.c"],
                   capture_output=True, text=True)
if not os.path.exists(f"{jobdir}/check.o"):
    err = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l]
    sys.exit(f"{jobdir}: COMPILE FAILED: {err[:2]}")


def hunks(a, b):
    r = subprocess.run([PY, ".hoplite/fn_diff.py", fn, a, b],
                       capture_output=True, text=True)
    return r.stdout.count("--- replace") + r.stdout.count("--- insert") + r.stdout.count("--- delete")


g1 = hunks(f"{jobdir}/check.o", full_obj)
g2 = hunks(f"{jobdir}/check.o", f"{jobdir}/target.o")
print(f"{jobdir}: gate1(full-file)={g1} gate2(original)={g2}")
if g1 != 0:
    sys.exit(f"{jobdir}: GATE 1 FAILED — stripped TU diverges from full-file build")
print(f"{jobdir} VALID")
