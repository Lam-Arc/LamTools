# LamTools v0.2.6 paper supplement

This supplement accompanies the Chinese-primary/English bilingual technical
paper for the audited LamTools `v0.2.6` baseline.

## Reproducibility target

- Git tag: `v0.2.6`
- Commit: `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`
- Software DOI: `https://doi.org/10.5281/zenodo.22039646`
- Repository: `https://github.com/Lam-Arc/LamTools`

## Contents

- Manuscript sources and bibliography
- Figure-generation source and generated figures in both 300-dpi PNG and
  vector SVG forms
- Deterministic paper consistency checks
- Retrieval metric derivation script and stored derived metrics
- Full Core test log used by the paper
- Refreshed targeted mechanism test log and isolated timing-sensitive rerun log
- Retrieval corpus, golden questions and stored raw reports

## Evidence boundary

The supplement preserves recorded evidence and the scripts used to derive the
reported values. It does not contain provider credentials, private configuration,
user data or unreported experiments. The retrieval case study is small and the
full Core run contains one timing-sensitive failure; the isolated rerun and the
refreshed targeted run are retained as separate logs. These limitations remain
part of the paper's stated evidence boundary. The current working-tree retrieval
runner is paper-preparation code and is not silently presented as part of the
frozen `v0.2.6` tag.
