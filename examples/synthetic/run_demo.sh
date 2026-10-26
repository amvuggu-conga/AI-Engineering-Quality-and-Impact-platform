#!/usr/bin/env bash
# Offline end-to-end demo of both use cases on the SYNTHETIC sample (no credentials needed, dry run).
# Usage: bash examples/synthetic/run_demo.sh [output-dir]
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT="${1:-examples/output}"
CFG=examples/synthetic/aiqip.synthetic.yaml
FIX=examples/synthetic/fixtures
unset AIQ_POST

aiqip --config "$CFG" index code --no-git
aiqip --config "$CFG" index tests
aiqip --config "$CFG" index defects --fixtures "$FIX" --jql "labels in (escape_defect, customer_bug)"

aiqip --config "$CFG" pr-quality --repo example-org/clm-api-sample --pr 101 --fixtures "$FIX" --execute \
  --out "$OUT/synthetic-pr-101" > /dev/null
aiqip --config "$CFG" bug-analysis --issue SYNTH-202 --fixtures "$FIX" --out "$OUT/synthetic-bug-SYNTH-202" > /dev/null
echo "Reports written to $OUT/synthetic-pr-101 and $OUT/synthetic-bug-SYNTH-202"
