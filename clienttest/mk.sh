#!/usr/bin/env bash
# mk.sh <name> : pack ./v/<name>/ (a pkg tree) into ./v/hftest_<name>.vpk
set -e; cd "$(dirname "$0")"
../.venv/bin/python -c 'import sys, vpk; p = vpk.new(sys.argv[1]); p.version = 1; p.save(sys.argv[2])' "v/$1" "v/hftest_$1.vpk"
