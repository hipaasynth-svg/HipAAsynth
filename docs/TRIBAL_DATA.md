# Tribal data: what we ship and what we never ship

HipAAsynth exists to protect people that clinical AI leaves out, and American
Indian and Alaska Native patients are among them. Tribes govern data about their
own communities ([CARE Principles for Indigenous Data
Governance](https://www.gida-global.org/care)). So:

## The rule

**No file in this repository names, or points to, a specific tribe, reservation,
or tribal community.** That covers names of nations and reservations, and the
counties, towns, service units and state combinations that would point to one.

`tests/test_tribal_data.py` enforces it on every pull request. It checks every
text file against a list kept as SHA-256 hashes, so the list does not put the
names back into the repository.

## The tribal profiles

`tribal_rural_a`, `tribal_rural_a_v2`, `tribal_rural_b`, `tribal_rural_b_v2`
(formerly `nd_tribal_region_*`; the old names still work):

* Rural, AI/AN-majority Indian Health Service service areas in the Northern
  Plains. `state` reads "Northern Plains (US)".
* Their calibration values (ethnicity mix, sex ratio, age bands, lab and vital
  distributions, trends) come from public, aggregate sources: the U.S. Census
  Bureau's American Community Survey, IHS, CDC and published studies. Those
  values were not changed when the place names were removed.
* They contain no data about any person. Every patient they generate is
  synthetic.

Because a profile's patients are seeded from a hash of the whole file, removing
the place names in 1.11.0 gave these four profiles new individual patients drawn
from the same, unchanged distributions. Every other profile is byte-identical.

## Before making a claim about a tribal population

A result such as "this model misses more sepsis in tribal patients" is about
synthetic patients built from public aggregates. Before using it to make a
claim about, or for, a specific tribal community, work with that community's
health leadership (for example a tribal health board or a Tribal Epidemiology
Center) and follow its data and research approval process.

## History

Older releases and the git history still contain two county names in the
profile source notes. Removing them from history means rewriting the published
history, which is a separate decision for the maintainers.
