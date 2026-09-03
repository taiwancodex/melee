#!/bin/sh
IN=$1; OUT=$3
case $IN in /*) ;; *) IN=$PWD/$IN;; esac
case $OUT in /*) ;; *) OUT=$PWD/$OUT;; esac
cd /tmp/hoplite/workspace
exec build/tools/wibo-qemu build/tools/sjiswrap.exe build/compilers/GC/1.2.5n/mwcceppc.exe -nowraplines -Cpp_exceptions off -proc gekko -fp hardware -align powerpc -nosyspath -fp_contract on -O4,p -multibyte -enum int -nodefaults -inline auto "-pragma" "cats off" "-pragma" "warn_notinlined off" -RTTI off -str reuse -DBUILD_VERSION=0 -DVERSION_GALE01 -DMUST_MATCH -maxerrors 1 -msgstyle std -warn off -lang=c -sym off -c -o "$OUT" "$IN"
