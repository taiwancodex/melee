#!/usr/bin/env python3
"""Auto-detect upstream matches/collisions for active grind targets.

One GitHub compare call covers all commits since our sync base; one files
call per open PR. For each active job (build/hoplite/perm_*/), matches at
FUNCTION level: a collision is reported only when a new commit patch or an
open PR patch has hunks inside the target function's region (hunk header
mentions the function, or hunk body references it). File-level-only touches
are reported as 'file touched, function clear'.

usage: upstream_check.py <sync_base_sha>
"""
import json
import os
import re
import sys
import urllib.request

REPO = "doldecomp/melee"
BH = "build/hoplite"


def gh(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def jobs():
    out = []
    for d in sorted(os.listdir(BH)):
        st, src = f"{BH}/{d}/settings.toml", f"{BH}/{d}/source.txt"
        if d.startswith("perm_") and os.path.exists(st) and os.path.exists(src):
            fn = open(st).read().split("func_name = ")[1].split('"')[1]
            out.append((d, fn, open(src).read().strip()))
    return out


def fn_in_patch(patch, fn):
    """True if any hunk header context or body mentions fn."""
    if not patch:
        return False
    for part in patch.split("@@")[1:]:
        header = part.split("\n")[0]
        if fn in header:
            return True
    return False


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else None
    active = jobs()
    if not active:
        print("UPSTREAM-CHECK: no active jobs")
        return
    by_src = {src: fn for _, fn, src in active}

    cmp_data = {}
    if base:
        try:
            cmp_data = gh(f"compare/{base}...HEAD")
        except Exception as e:
            print(f"UPSTREAM-CHECK: compare failed: {e}")
    new_files = {f["filename"]: f.get("patch", "") for f in cmp_data.get("files", [])}

    pr_files = {}
    for p in gh("pulls?state=open&per_page=30"):
        try:
            for f in gh(f"pulls/{p['number']}/files?per_page=50"):
                pr_files.setdefault(f["filename"], []).append(
                    (p["number"], p["title"], f.get("patch", "")))
        except Exception:
            pass

    for job, fn, srcfile in active:
        verdicts = []
        if srcfile in new_files:
            patch = new_files[srcfile]
            tag = "MATCHED/CLAIMED" if fn_in_patch(patch, fn) else "file-touched"
            verdicts.append(f"new commit: {tag}")
        for num, title, patch in pr_files.get(srcfile, []):
            tag = "CLAIMED" if fn_in_patch(patch, fn) else "file-touched"
            verdicts.append(f"PR #{num} ({title}): {tag}")
        status = " | ".join(verdicts) if verdicts else "clear"
        drop = " -> DROP" if any(t.split(": ")[1].startswith(("MATCHED", "CLAIMED"))
                                 for t in verdicts) else ""
        print(f"{job} {fn}: {status}{drop}")


if __name__ == "__main__":
    main()
