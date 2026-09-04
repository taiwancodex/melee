# Melee matching status — updated 2026-09-03

Workflow and environment documentation moved to `.hoplite/README.md`.
This file tracks current matching state and per-function root causes.

## Environment

Working end-to-end: WiBo 0.7.0 under qemu (`build/tools/wibo-qemu`),
MWCC 1.2.5n, sjiswrap, ninja; full build produces a byte-identical DOL
(SHA-1 `08e0bf20134dfcb260699671004527b2d6bb1a45`). Setup is embedded in
`.hoplite/settings.json` and provisions fresh sandboxes automatically.

## Resolved

### gmMainLib_8015DBF4 / gmmain_lib — MATCHED UPSTREAM (PR #3297)
Upstream fixed it while our permuter grind ran (2026-09-02 22:09). The
fix: proper named struct types (`gmm_x0_vsdata`/`gmm_x0_vsmodes`)
replacing the cast hacks, `ADJ_NAMETAG_78` macro removed in favor of
direct helper calls, and the pointer passed as an inlined
call-expression argument (`&gmMainLib_8015CDC8()->nametag`) — the
inlined call in argument position is the sequencing barrier that pins
the entry-block ordering. Our branch is synced through that commit
(plus #3294/#3295/#3296/#3298). Our independent root-cause work matched
theirs: MWCC's peephole rematerializes the entry-block load address and
hoists the freed load (`#pragma peephole off` reproduces the exact
target order but breaks 45 other instructions — proof, not a fix).

## Active targets (permuter grinds)

### _Toy_8030E110 — DROPPED (upstream collision)
Open PR #3310 "Work on toy" (2026-09-04) hand-matches _Toy_8030E110 and the
other toy near-misses (decl reorders + `uintptr_t keys` hoists — the same
variant family the permuter explores). Grinding it would duplicate an active
upstream PR; revisit only if #3310 stalls or closes unmatched.

### gm_80182174 (gmregclear) — PARKED, 5-hunk residual
After fixing the base (see TU pipeline notes below), the UNSTRIPPED cpp TU
compiles within 5 hunks of the full-file build: one struct (accessed via a
lis/addi-materialized global) has fields +60 off vs the real build; the r31
-based struct is exact. The stripped TU adds ~14 more. Diagnosis artifacts in
build/hoplite/perm_gmreg2/. Not worth further cycles while other targets are
open; revisit with the fixed pipeline insights.

### _tyDisplay_80319994 (tydisplay) — PARKED, permuter rewriter bug
The job is fully validated (gate 1 exact after the __FILE__ and MUST_MATCH
fixes; 6-hunk real delta vs original), but decomp-permuter's AST rewriter
mis-nests the helper's pointer arithmetic — it rewrites
`(T*) ((size_t) base + pivot * sizeof(T) + K)` into
`sizeof((T) (+K))`, an invalid cast of a literal to a struct, so the base
candidate never compiles and the permuter falls back to the wrong function.
Neither joining the expression to one line nor swapping the multiplication
order avoids the fold. Artifacts in build/hoplite/perm_tydsp/. Needs a
permuter-side fix or a codegen-neutral re-expression; revisit then.

### ftCo_80095EFC (ftCo_ItemThrow) — CLOSE, best live track
Delta was a pure FPR swap: `lfs f1,0x89c` (frame_speed_mul, inside
getItemThrowFsm) and `lfs f0,0x2348` (x8.x) came out f0/f1 swapped.
BREAKTHROUGH: removing the x8.x hoist (it fed the multi-def
`interpolation` variable, whose web got the wrong register) and reading
it inline in the interpolation expression fixes BOTH registers —
`.hoplite/patches/ftCo_80095EFC_inline_x8x.patch`. Remaining delta: one
slot ordering — target `[lfs f0@50, fdivs@51, lwz r3@52]` vs built
`[lwz r3@50, fdivs@51, lfs f0@52]` (the Fighter_804D6550 table-pointer
load vs the x8.x load). Statement reordering does NOT fix it (moving
the interpolation or the table chain reshuffles the whole float
allocation — tested). Grind running from the a3 base with
`--stack-diffs`.

### fn_80180630 (gmregclear) — STUBBORN
One register: `lwz r4,88(r1)` vs our `lwz r3,88(r1)` after
`bl grPushOn_80219204` (coin_count out-param load feeding
`clrlwi r28,rX,16`). Exhausted: all statement orders, cast-vs-mask,
scoped temps (C90-legal), inline-helper truncation, declaration
swaps (slots are declaration-ordered — swapping breaks the addi
offsets), ~4k random permuter iterations, 6 manual PERM_GENERAL
combos (all tie at base score 30). Mechanism still unidentified; the
fix likely needs a source construct outside all of these.

## Permuter hard-won lessons

- TU generation via system cpp needs THREE fixes to match MWCC's own
  preprocessing (each caused silent codegen divergence caught by gate 1):
  1. `-D__MWERKS__ -D__POWERPC__ -U__GNUC__ -U__clang__` so headers take
     the MWCC branch (no `__attribute__`, no `_Static_assert`).
  2. `-DMUST_MATCH` — the project guards `#pragma pack(push,1)` regions with
     it; without the define, packed structs (e.g. TmData) silently unpack and
     every downstream field offset shifts.
  3. `sed -E 's/__assert\("[^"]*\//__assert("/g'` on the cpp output — MWCC's
     `__FILE__` is the bare basename, GCC's is the full path; assert strings
     from inlined header helpers land in the target's string pool, so the
     path form changes pool contents, offsets, and register pressure.
- Functions whose bodies contain assert macros are structurally unmatchable
  by single-function stripping (assert strings live in the whole-TU string
  pool; removing other functions shifts pool offsets). mnStageSw_80236CBC
  was rejected for this reason. Always grep the target body for asserts
  before building a job.
- MWCC's own `-P` .i output cannot be recompiled by MWCC itself (file-scope
  assert-struct expansions rejected); it is only useful as a diff reference.
- ALWAYS run with `--stack-diffs`: the scorer ignores stack offsets by
  default and records frame-shifting candidates (new local → +4 byte
  slot) as "improvements" that can never match.
- Validation gates are mandatory: the stripped single-function base TU
  must reproduce the full-file build's codegen exactly (compile
  base_check.c + fn_diff before trusting any grind result).
- The stripper must keep static/inline definitions (the inlinable
  pool) or inlining changes; it must be SJIS-aware (trail bytes can be
  ASCII braces) — see build_perm_base_lib.py.
- dtk→GAS conversion: `%rN` register names, `crNeq`-style CR operands
  to numeric bits, `@sda21/@ha/@l/rel24` relocs assemble cleanly with
  powerpc-eabi-as -mgekko.
- Turn boundaries kill detached grinds — relaunch and re-check
  `pgrep -f permuter` every session; ninja survives more often.

## Remaining function inventory (as of the 2026-09-03 sync)

Regenerate with `.hoplite/report_summary.py` after a full build.
Upstream has active WIP PRs on hsd_3A94 (#3301) and psdisp (#3250) —
avoid duplicating those.
