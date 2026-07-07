#!/usr/bin/env bash
# HipAAsynth → Seismometer one-line demo.
#
#   bash examples/seismometer/demo_seismometer.sh
#
# Generates a deterministic OUD cohort from a seed (no committed data),
# adapts it into a Seismometer package, executes the Seismometer notebook
# headlessly, and writes a self-contained HTML report with rendered fairness /
# performance plots.
#
# Bring your own cohort by pointing PATIENTS / RESULTS at existing canonical
# files; otherwise the demo regenerates one via generate_demo_cohort.py. Tune
# the generated cohort with MODULE / N / SEED.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODULE="${MODULE:-oud}"
N="${N:-1000}"
SEED="${SEED:-42}"
OUT="${OUT:-$HERE/build}"
CONFIG_DIR="$OUT/seis_package"
COHORT_DIR="$OUT/cohort"

# If the caller supplied a cohort, use it; otherwise regenerate one from a seed.
if [[ -n "${PATIENTS:-}" && -n "${RESULTS:-}" ]]; then
  echo "==> [1/3] Using provided cohort"
else
  echo "==> [1/3] Generating deterministic $MODULE cohort (n=$N, seed=$SEED)"
  # Capture the exact paths the generator wrote (last two PATIENTS_JSON=/RESULTS_CSV= lines).
  GEN_OUT="$(python "$HERE/generate_demo_cohort.py" \
    --out "$COHORT_DIR" --module "$MODULE" --n "$N" --seed "$SEED")"
  echo "$GEN_OUT"
  PATIENTS="${PATIENTS:-$(echo "$GEN_OUT" | sed -n 's/^PATIENTS_JSON=//p')}"
  RESULTS="${RESULTS:-$(echo "$GEN_OUT" | sed -n 's/^RESULTS_CSV=//p')}"
fi

echo "==> [2/3] Adapting cohort -> Seismometer package, executing notebook headlessly"
python "$HERE/seismometer_adapter.py" \
  --patients "$PATIENTS" --results "$RESULTS" --module "$MODULE" --out "$CONFIG_DIR"

cp "$HERE/hipaasynth_seismometer_demo.ipynb" "$OUT/run.ipynb"
SEIS_CONFIG_DIR="$CONFIG_DIR" \
  jupyter nbconvert --to html --execute \
    --ExecutePreprocessor.timeout=300 \
    --output "seismometer_demo_report" --output-dir "$OUT" \
    "$OUT/run.ipynb"

echo "==> [3/3] Done"
echo "Report:   $OUT/seismometer_demo_report.html"
echo "Package:  $CONFIG_DIR"
