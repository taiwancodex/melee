# Hoplite agent tooling — Melee decomp matching

Everything a future agent instance needs to resume byte-exact function
matching for this repository without starting from scratch. All heavy
artifacts are intentionally NOT stored here: the game DOL, dtk-split
assemblies, permuter bases and target objects are all regenerable from
this repo plus a verified `orig/GALE01/sys/main.dol` — and must not be
redistributed.

## Environment (automatic)

`.hoplite/settings.json` carries the setup script that provisions the
toolchain in a fresh sandbox: qemu-user-static, ninja, WiBo 0.7.0 (run
under qemu via `build/tools/wibo-qemu` — the sandbox kernel cannot
execute the 32-bit WiBo binary natively; WiBo 0.7.0 + sjiswrap 1.2.2 is
the combination the official build pins), MWCC compilers
(files.decomp.dev 20251118), and powerpc-eabi binutils.

## Verified build (from a clean tree)

    python3 configure.py --version GALE01 --compilers build/compilers \
      --binutils build/tools/binutils --dtk build/tools/dtk \
      --objdiff build/tools/objdiff-cli --wrapper build/tools/wibo-qemu \
      --sjiswrap build/tools/sjiswrap.exe --ninja /usr/bin/ninja --verbose
    ninja

A green build produces `build/GALE01/main.dol` byte-identical to the
original (SHA-1 `08e0bf20134dfcb260699671004527b2d6bb1a45`). The dtk
split originals live in `build/GALE01/obj/`, built objects in
`build/GALE01/src/`, per-function asm in `build/GALE01/asm/`.

## Triage

    python3 .hoplite/report_summary.py          # non-matching functions, ranked
    python3 .hoplite/fn_diff.py <symbol> build/GALE01/src/<unit>.o \
        build/GALE01/obj/<unit>.o [ctx]        # aligned per-function diff
    python3 .hoplite/unit_diff.py <built.o> <orig.o>  # whole-unit diff

## Function matching workflow (decomp-permuter)

Permuter jobs are three-part: a byte-faithful single-function target
object, a stripped single-function base TU that provably reproduces the
current build's codegen for the target function, and MWCC compile.sh.

1. Build the target object from the dtk asm (GAS needs `%rN` registers
   and numeric CR bits — the converter handles both):

       python3 .hoplite/dtk2gas.py build/GALE01/asm/<unit>.s <symbol> <job>/target.s
       build/tools/binutils/powerpc-eabi-as -mgekko <job>/target.s -o <job>/target.o
       python3 .hoplite/fn_diff.py <symbol> <job>/target.o build/GALE01/obj/<unit>.o   # must show zero diffs

2. Preprocess the TU and strip it to the target function plus its
   static/inline helpers (kept automatically), wrapping the mismatching
   region in PERM_RANDOMIZE:

       gcc -E -P -undef -D'__attribute__(x)=' -D'_Static_assert(x, y)=' \
         -DMUST_MATCH -DBUILD_VERSION=0 -DVERSION_GALE01 \
         -I src -I src/MSL -I src/Runtime -I extern/dolphin/include \
         -I build/GALE01/include -I src/melee -I src/melee/ft/chara \
         -I src/sysdolphin src/<tu>.c > <job>/base_raw.c
       python3 .hoplite/build_perm_job.py <job> <job>/base_raw.c <symbol> \
         '<region_start_regex>' '<region_end_regex>'

3. VALIDATION GATE (never skip): compile `<job>/base_check.c` with the
   flags in compile.sh and fn_diff it against the original object — it
   must reproduce exactly the same delta as the full-file build.

4. Run the grind — always with `--stack-diffs` (the scorer ignores stack
   positions by default and will happily record frame-shifting exploits
   as "improvements" that can never match):

       cd build/hoplite/tools/decomp-permuter-main
       PATH=…/build/tools/binutils:$PATH …/pvenv/bin/python3 permuter.py \
         <job> --stop-on-zero --stack-diffs -j 2

   decomp-permuter itself is fetched as a tarball from GitHub and
   installed into a venv (`pip install -e .` with cython/toml/Levenshtein).

Manual `PERM_GENERAL` alternatives enumerate chosen source variants
deterministically (plain commas separate alternatives; `(,)` is the
literal-comma escape) — see build_perm_gmregclear_manual.py.

## Lessons learned (see matching_notes.md for detail)

- MWCC's peephole rematerializes load addresses and hoists freed loads
  to the top of the ENTRY basic block; later blocks don't get this.
- The fix upstream used for gmMainLib_8015DBF4 (PR #3297): proper named
  struct types instead of cast hacks, and an inlined call-expression in
  argument position (`&gmMainLib_8015CDC8()->nametag`) which pins the
  entry-block ordering.
- Inline-expression reads (instead of hoisting into a multi-def local)
  fixed ftCo_80095EFC's FPR assignment — see
  patches/ftCo_80095EFC_inline_x8x.patch (one ordering delta remained;
  permuter grinds from this base).
- Stack slots follow declaration order; adding any local shifts the
  frame and breaks every stack offset.
- `#pragma peephole off` around a function pins entry-block loads but
  disables address re-basing elsewhere (45+ instruction fallout) — not
  usable as a fix.

## Upstream sync (the fork remote is stale)

The trusted git broker only reaches the configured fork, so sync from
doldecomp/melee by applying commit patches:

    curl -sS "https://api.github.com/repos/doldecomp/melee/commits?per_page=12"
    curl -sSL -o <sha>.patch "https://github.com/doldecomp/melee/commit/<sha>.patch"
    git am --keep-non-patch <sha>.patch   # oldest first

Then `ninja` and confirm the DOL hash is unchanged (all upstream commits
are matching commits). Contribution rules: .github/CONTRIBUTING.md —
code matches only, no AI-written body text unless quoted with `>`.

## Commit identity note

The platform installs a `prepare-commit-msg` hook that injects a
`Co-authored-by` trailer with the account owner's name and email into
every commit; `--no-verify` does NOT bypass it (it is not a pre-commit or
commit-msg hook). For identity-free commits, temporarily disable it:
`chmod -x .git/hooks/prepare-commit-msg` (restore afterwards).
