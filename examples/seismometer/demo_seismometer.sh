#!/usr/bin/env bash
# HipAAsynth → Seismometer one-line demo.
#
#   bash examples/seismometer/demo_seismometer.sh
#
# Runs the adapter on the bundled OUD cohort, executes the Seismometer notebook
# headlessly, and writes a self-contained HTML report with rendered fairness /
# performance plots. Override PATIENTS / RESULTS / MODULE to point at your own cohort.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

PATIENTS="${PATIENTS:-$HERE/sample_data/patients.json}"
RESULTS="${RESULTS:-$HERE/sample_data/results.csv}"
MODULE="${MODULE:-oud}"
OUT="${OUT:-$HERE/build}"
CONFIG_DIR="$OUT/seis_package"

echo "==> [1/3] Adapting HipAAsynth cohort -> Seismometer package"
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  python -m hipaasynth.seismometer_adapter \
    --patients "$PATIENTS" --results "$RESULTS" --module "$MODULE" --out "$CONFIG_DIR"

echo "==> [2/3] Executing Seismometer notebook headlessly"
cp "$HERE/hipaasynth_seismometer_demo.ipynb" "$OUT/run.ipynb"
SEIS_CONFIG_DIR="$CONFIG_DIR" \
  jupyter nbconvert --to html --execute \
    --ExecutePreprocessor.timeout=300 \
    --output "seismometer_demo_report" --output-dir "$OUT" \
    "$OUT/run.ipynb"

echo "==> [3/3] Done"
echo "Report:   $OUT/seismometer_demo_report.html"
echo "Package:  $CONFIG_DIR"
