#!/bin/bash
set -euo pipefail
source_root=$(realpath "$1")
build_root=$(realpath -m "$2")
wrapper=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$build_root"
cd "$build_root"
# Legacy source type mismatches are retained; warnings must be reviewed.
gfortran -O2 -std=legacy -fallow-argument-mismatch -fno-automatic -c \
 "$source_root"/bhw/*.f "$source_root"/ewc/*.f \
 "$source_root"/glib/*.f "$source_root"/interface/*.f
gfortran -O2 -c "$wrapper/driver.f90" -o driver.o
g++ -O2 -std=c++17 -c "$wrapper/rng.cc" -o rng.o
gfortran -o bhwide ./*.o -lstdc++
