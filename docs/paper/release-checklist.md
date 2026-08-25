# LamTools Release and DOI Checklist

This checklist is intentionally short. It records what is already known and
leaves only account-authority and final-publication actions for the authors.

## Fixed software state

- Repository: `https://github.com/Lam-Arc/LamTools`
- Audited commit: `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`
- Software tag: `v0.2.6`
- GitHub Release: already exists and is public
- Release asset: `LamCore_0.2.6_x64-setup.exe`
- No later fetch/pull is part of this workstream

Do not rewrite or amend `v0.2.6`. The paper must cite this exact software state
if it uses the current audit and evaluation evidence. The new `CITATION.cff` and
paper materials are preparation files on the working branch; they do not change
the frozen tag.

## Software DOI gate

1. Both authors verify creator names, order, ORCIDs, affiliations, and equal-
   contribution wording.
2. The authorized depositor connects the GitHub repository to production Zenodo
   and enables `Lam-Arc/LamTools`.
3. Zenodo archives the existing `v0.2.6` GitHub Release; do not create a second
   tag or alter the historical release.
4. Verify the Software DOI record, creator order, version, license, release asset,
   and GitHub relation.

Software DOI completed: `https://doi.org/10.5281/zenodo.22039646`.

## Paper DOI gate

1. Rerun the final selected evaluation on one commit and preserve raw JSON plus
   methodology. The current supplement retains the full Core log, the refreshed
   targeted mechanism log (`63 passed, 1 skipped`) and the isolated timing-sensitive
   rerun log. For the Core suite, set `PYTHONPATH=core/src` and
   `LAMTOOLS_COMMAND_SHELL=pwsh`; a missing local `fastembed` installation only
   blocks the optional local-embedding rerun, not the deterministic Core suite.
2. The current provider smoke test is optional and is not paper evidence until
   the local `LAMTOOLS_OPENAI_API_KEY` is configured and both requests complete
   successfully. If it is included, run
   `docs/paper/provider_smoke.py` with the local `LAMTOOLS_OPENAI_API_KEY`
   environment variable and retain only its sanitized JSON result.
3. Regenerate the retrieval-derived summary after any rerun with
   `docs/paper/derive_retrieval_metrics.py`; keep raw reports, the derived JSON,
   and the methodology together. Do not mix results from different software
   states or silently discard failed cases. The revised analysis harness is
   paper-preparation code outside the frozen `v0.2.6` tag; label it as such in
   the archived paper materials.
4. Generate the final PDF with `docs/paper/build_journal_pdf.py`, inserting the Software DOI,
   GitHub URL, version, tag, and commit SHA.
5. The reproducibility supplement is prepared at
   `output/supplement/lamtools-paper-supplement-v0.2.6.zip`; upload it only if the
   final Paper record accepts supplementary files without changing the paper DOI's
   single-record structure.
6. Create one Zenodo paper draft containing the combined Chinese-primary/English
   PDF as `Preprint` if that subtype is present; otherwise
   use the accurate `Report` subtype.
7. Paper DOI reserved: `https://doi.org/10.5281/zenodo.22040870`. Keep the same
   draft record while replacing the PDF; do not delete the draft or create a new
   upload.
8. Set creators in this order: Yulin Zhang, then Yiming Zhang. State equal
   contribution in the PDF and description if desired.
9. Share the draft for the second author's preview/edit and obtain both authors'
   final approval.
10. Publish only after the PDF preview, metadata, relations, license, and both
   author approvals pass the quality gate.

## After publication

Update the main README and current `CITATION.cff` with the Paper DOI and Software
DOI. Do not back-edit the `v0.2.6` tag or its archived source.
