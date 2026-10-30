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

"""Anthropometrics generator. All randomness from pipeline-owned rng.

Calibration sources:
  [A1] Fryar CD et al. Anthropometric Reference Data for Children and Adults:
       United States, 2015-2018. National Health Statistics Reports No. 36.
       NCHS, CDC. 2021. DHHS Publication No. 2021-1120.
       https://www.cdc.gov/nchs/data/series/sr_03/sr03-046-508.pdf
       Mean height: men 175.4 cm (SD ~7.2 cm), women 161.8 cm (SD ~7.1 cm).
       Mean BMI: men 29.5, women 30.2 (adults 20+, NHANES 2015-2018).

  [A2] Hales CM et al. Prevalence of Obesity and Severe Obesity Among Adults:
       United States, 2017-2018. NCHS Data Brief No. 360. 2020.
       https://www.cdc.gov/nchs/products/databriefs/db360.htm
       Obesity prevalence 42.4%; overweight 31.1%; combined 73.5% BMI>=25.
       Mean BMI US adults ~29-30, consistent with [A1].

  [A3] Ogden CL et al. Mean Body Weight, Height, Waist Circumference, and Body
       Mass Index Among Adults: United States, 1999-2000 Through 2015-2016.
       National Health Statistics Reports No. 122. NCHS, CDC. 2018.
       https://www.cdc.gov/nchs/data/nhsr/nhsr122.pdf
       Trend data confirming rising mean BMI trajectory; SD ~7-8 kg/m2 in
       adult US population.

  [A4] WHO. BMI Classification. Obesity: preventing and managing the global
       epidemic. WHO Technical Report Series 894. Geneva: WHO; 2000.
       Standard BMI thresholds: <18.5 underweight, 18.5-24.9 normal,
       25-29.9 overweight, 30-34.9 class 1, 35-39.9 class 2, >=40 class 3.

DOCUMENTED LIMITATION:
  BMI mean of 29.0 represents the US national adult average per NHANES
  2015-2018 [A1][A2]. Individual population profiles (e.g., tribal IHS
  populations) may have higher mean BMI; those overrides are applied at
  the profile level, not in this generator.
"""
from hipaasynth.core.schema import Anthropometrics


def _clip(value, lower, upper):
    return min(max(value, lower), upper)


def _bmi_category(bmi):
    """Standard WHO BMI classification for adults [A4]."""
    if bmi < 18.5:
        return "underweight"
    if bmi < 25.0:
        return "normal"
    if bmi < 30.0:
        return "overweight"
    if bmi < 35.0:
        return "obesity_class_1"
    if bmi < 40.0:
        return "obesity_class_2"
    return "obesity_class_3"


def _generate_height_cm(rng, age, sex):
    """Generate height in cm.

    Mean and SD from NHANES 2015-2018 [A1]:
      Men:   mean 175.4 cm, SD ~7.2 cm (modeled as 176 cm, SD 7)
      Women: mean 161.8 cm, SD ~7.1 cm (modeled as 162 cm, SD 7)
    Clamped to physiologically plausible adult range 140-205 cm.
    """
    if sex == "male":
        value = rng.gauss(176.0, 7.0)
    elif sex == "female":
        value = rng.gauss(162.0, 7.0)
    else:
        raise ValueError(f"Unsupported sex: {sex!r}")
    adult_height = round(_clip(value, 140.0, 205.0), 1)
    if age >= 18:
        return adult_height
    # Simple pediatric scaling: newborn ~50 cm, adult height by ~18 y.
    # Keep the same RNG consumption count as the adult branch.
    factor = _clip(0.35 + 0.036 * age, 0.45, 0.97)
    return round(_clip(adult_height * factor, 70.0, adult_height - 1.0), 1)


def _bmi_category_pediatric(bmi):
    # Simplified pediatric categories for engine testing; not clinical growth-chart percentiles.
    if bmi < 14.0:
        return "underweight"
    if bmi < 22.0:
        return "normal"
    if bmi < 25.0:
        return "overweight"
    if bmi < 30.0:
        return "obesity_class_1"
    return "obesity_class_2"


def _generate_bmi(rng, age, sex):
    """Generate BMI.

    Adult mean BMI ~29.0 kg/m2 reflects NHANES 2015-2018 US adults [A1][A2].
    SD ~5.0 kg/m2 is conservative relative to published ~7-8 [A3]; narrowed
    to reduce extreme outlier generation in small cohorts.
    Sex offset +0.3 for women reflects slightly higher mean BMI in women [A1].
    Age adjustments: younger adults (18-24) tend toward lower BMI; older
    adults (65+) show slight decrease due to body composition changes [A3].
    """
    if sex == "female":
        sex_offset = 0.3
    elif sex == "male":
        sex_offset = 0.0
    else:
        raise ValueError(f"Unsupported sex: {sex!r}")

    if age < 18:
        # Pediatric BMI mean rises from ~15 at age 1 to ~22 by age 17.
        mean = 15.0 + 0.39 * age + sex_offset
        bmi = round(_clip(rng.gauss(mean, 2.5), 11.0, 35.0), 1)
        return bmi, _bmi_category_pediatric(bmi)

    mean = 29.0  # NHANES 2015-2018 US adult mean [A1][A2]
    if age < 25:
        mean -= 2.0  # Younger adults trend lower [A3]
    elif age >= 65:
        mean -= 0.5  # Slight decrease in older adults [A3]
    mean += sex_offset
    return round(_clip(rng.gauss(mean, 5.0), 15.0, 60.0), 1), None


def generate_anthropometrics(rng, age, sex):
    height_cm = _generate_height_cm(rng, age, sex)
    bmi, pediatric_category = _generate_bmi(rng, age, sex)
    category = pediatric_category if pediatric_category is not None else _bmi_category(bmi)
    height_m = height_cm / 100.0
    weight_kg = round(bmi * (height_m**2), 1)
    return Anthropometrics(height_cm=height_cm, weight_kg=weight_kg, bmi=bmi, bmi_category=category)
