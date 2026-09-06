#!/usr/bin/env python3
"""Autopilot cycle: poll active grinds, relaunch dead ones, run the upstream
collision check periodically. Invoke repeatedly from the keep-alive loop;
all state lives under build/hoplite. A job is active when its directory
contains an autopilot.on flag.

usage: autopilot_cycle.py [--force-upstream]
"""
import os
import subprocess
import sys

WS = "/tmp/hoplite/workspace"
BH = f"{WS}/build/hoplite"
CYCLE_FILE = f"{BH}/autopilot_cycle_count"
UPSTREAM_EVERY = 6


def permuter_running(jobdir):
    out = subprocess.run(
        ["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return f"permuter.py {jobdir} " in out


def main():
    force = "--force-upstream" in sys.argv
    cycle = 0
    if os.path.exists(CYCLE_FILE):
        cycle = int(open(CYCLE_FILE).read().strip() or 0)
    cycle += 1
    open(CYCLE_FILE, "w").write(str(cycle))

    for name in sorted(os.listdir(BH)):
        jdir = f"{BH}/{name}"
        if not (name.startswith("perm_")
                and os.path.exists(f"{jdir}/autopilot.on")):
            continue
        zeros = [f for f in os.listdir(jdir) if f.startswith("output-0-")]
        if zeros:
            print(f"{name}: *** MATCH FOUND ({zeros[0]}) — finish pipeline ***")
            continue
        if permuter_running(jdir):
            log = f"{BH}/permuter_{name}_auto.log"
            if os.path.exists(log):
                it = [l for l in open(log, errors="replace").read()
                      .replace("\r", "\n").split("\n") if "iteration" in l]
                if it:
                    print(f"{name}: {it[-1].strip()}")
                    continue
            print(f"{name}: running (no iterations yet)")
        else:
            subprocess.Popen(
                [f"{BH}/pvenv/bin/python3", "permuter.py", jdir,
                 "--stop-on-zero", "--stack-diffs", "-j", "1"],
                cwd=f"{BH}/tools/decomp-permuter-main",
                stdout=open(f"{BH}/permuter_{name}_auto.log", "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True)
            print(f"{name}: relaunched (was dead)")

    if force or cycle % UPSTREAM_EVERY == 1:
        base = subprocess.run(
            ["git", "-C", WS, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        r = subprocess.run(
            [f"{BH}/pvenv/bin/python3", f"{WS}/.hoplite/upstream_check.py", base],
            capture_output=True, text=True)
        for line in (r.stdout + r.stderr).strip().splitlines():
            print(f"UPSTREAM {line}")


if __name__ == "__main__":
    main()
