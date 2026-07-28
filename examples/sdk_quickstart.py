# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# %% [markdown]
# # HipAAsynth SDK quickstart
#
# This file is a **jupytext "percent" notebook** — every `# %%` marks a cell, so
# you can open it directly in Jupyter / VS Code / Colab (via jupytext) *and* run it
# as a plain script: `python examples/sdk_quickstart.py`.
#
# The whole point of `hipaasynth.sdk` is that the common case is a one-liner:
# **generate → export → validate**, with no argparse and no file-path juggling.
# All records are synthetic — there is no PHI anywhere in this notebook.

# %%
import sys
import tempfile
from pathlib import Path

# Let the example run from a checkout without `pip install` (a real install adds
# `hipaasynth` to the path and this line is a harmless no-op).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hipaasynth

print("HipAAsynth engine version:", hipaasynth.ENGINE_VERSION)
print("Decision modules:", ", ".join(hipaasynth.MODULES))
print("Bundled profiles:", ", ".join(hipaasynth.available_profiles()))

# %% [markdown]
# ## 1. Generate a cohort
#
# One call. Same `seed` ⇒ byte-identical cohort every time.

# %%
cohort = hipaasynth.generate(count=25, seed=42, module="stroke")
print(cohort)                 # <Cohort n=25 seed=42 module='stroke'>
print("patients:", len(cohort))

summary = cohort.summary()
print("mean age:", summary["age_mean"], "| sex:", summary["sex_counts"])

# %% [markdown]
# ## 2. Export — every format is a method
#
# Call a `to_*` method with **no path** to get the data back in-memory, or **with a
# path** to write a file (it returns the path). Here we write a few formats to a
# temp directory.

# %%
out = Path(tempfile.mkdtemp(prefix="hipaasynth_quickstart_"))
print("writing to:", out)

json_path = cohort.to_json(out / "cohort.json")
csv_path = cohort.to_csv(out / "cohort.csv")
bundle_path = cohort.to_fhir_bundle(out / "cohort_fhir.json")   # single FHIR Bundle
ndjson_dir = cohort.to_ndjson(out / "cohort_fhir_ndjson")       # FHIR bulk $export
omop_dir = cohort.to_omop(out / "omop_cdm")                     # OMOP CDM 5.4 CSVs

for label, p in [("JSON", json_path), ("CSV", csv_path), ("FHIR bundle", bundle_path),
                 ("FHIR NDJSON", ndjson_dir), ("OMOP CDM", omop_dir)]:
    print(f"  {label:12s} -> {p}")

# In-memory variants (no path) — handy in a notebook:
omop_tables = cohort.to_omop()
print("OMOP tables in-memory:", ", ".join(omop_tables))

# Optional Parquet (needs `pip install 'hipaasynth[parquet]'`):
try:
    parquet_path = cohort.to_parquet(out / "cohort.parquet")
    print("  Parquet      ->", parquet_path)
except RuntimeError as exc:
    print("  Parquet      -> skipped:", exc)

# %% [markdown]
# ## 3. Validate the FHIR output
#
# `cohort.validate()` runs the structural FHIR R5 validator over the cohort's
# resources. **Structural check only — not a substitute for the official HL7 FHIR
# IG validator**; run that before any conformance claim.

# %%
report = cohort.validate()
print("FHIR structural validation:",
      "PASS" if report.ok else f"{len(report.errors)} error(s)")
print("resources checked:", report.total)
for err in report.errors[:10]:
    print("  -", err["message"])

# %% [markdown]
# ## 4. Iterate over patients
#
# A `Cohort` is just an iterable/indexable collection of patient records.

# %%
first = cohort[0]
print("first patient id:", first.demographics.patient_id,
      "| age:", first.demographics.age,
      "| conditions:", [c.name for c in first.conditions])

print("\nDone — generate → export → validate, all synthetic.")
