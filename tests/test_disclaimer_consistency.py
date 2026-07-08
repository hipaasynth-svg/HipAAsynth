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

"""All generators emit one canonical synthetic-data disclaimer (issue #31).

Previously the module generators (oud/chf/copd) carried a different disclaimer
string from the pipeline path. This locks in the consolidation: every generator
stamps records with ``DEFAULT_SYNTHETIC_DISCLAIMER``.
"""

import hipaasynth.modules.chf.chf_generator as chf
import hipaasynth.modules.copd.copd_generator as copd
import hipaasynth.modules.oud.oud_generator as oud
from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.modules.diabetes.population import DiabetesPopulationGenerator
from hipaasynth.modules.dmd.dmd import DMDCohortGenerator
from hipaasynth.modules.fabry.fabry import FabryCohortGenerator
from hipaasynth.modules.sma.sma import SMACohortGenerator
from hipaasynth.pipelines.population_pipeline import generate_patients


def test_module_disclaimer_constants_are_canonical():
    for module in (oud, chf, copd):
        assert module.DISCLAIMER == DEFAULT_SYNTHETIC_DISCLAIMER


def test_every_generator_stamps_the_canonical_disclaimer():
    records = []
    records.append(oud.generate_oud_cohort(seed=1, n=1)[0][0])
    records.append(chf.generate_chf_cohort(seed=1, n=1)[0][0])
    records.append(copd.generate_copd_cohort(seed=1, n=1)[0][0])
    records.append(DMDCohortGenerator(seed=1).generate(1)[0])
    records.append(FabryCohortGenerator(seed=1).generate(1)[0])
    records.append(SMACohortGenerator(seed=1).generate(1)[0])
    records.append(DiabetesPopulationGenerator(n=1, seed=1).generate()[0])
    records.append(generate_patients(GenerationConfig(patient_count=1, seed=1))[0].to_dict())

    for record in records:
        assert record["disclaimer"] == DEFAULT_SYNTHETIC_DISCLAIMER
