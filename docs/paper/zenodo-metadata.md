# Zenodo metadata handoff

This file is a copy-ready metadata sheet. It contains no credentials or access
tokens. The author order is intentional and must remain unchanged:

1. Yulin Zhang — ORCID `0009-0007-3202-5746`
2. Yiming Zhang — ORCID `0009-0005-5317-0665`

Both authors are listed as equal contributors in the paper. The order remains
Yulin Zhang first and Yiming Zhang second in both records.

## Software record

- Title: `LamTools`
- Version: `v0.2.6`
- Resource type: `Software`
- Upload target: existing public GitHub Release `v0.2.6`
- GitHub release: `https://github.com/Lam-Arc/LamTools/releases/tag/v0.2.6`
- Repository: `https://github.com/Lam-Arc/LamTools`
- Creators: Yulin Zhang, then Yiming Zhang
- Affiliation for each creator: `Independent Researcher`
- License: `MIT`
- Publication date: the actual Zenodo publication date
- Software DOI: `10.5281/zenodo.22039646`
- Description: `LamTools is a local-first AI agent runtime for desktop and command-line use. It combines a model/provider adapter layer, an event-driven agent loop, approval-aware tools, SQLite-backed state, checkpoints, plugins, and a Windows desktop shell. Release v0.2.6 contains the audited runtime baseline documented by the associated technical paper.`

Do not amend or rewrite the historical `v0.2.6` tag. The current repository
`CITATION.cff` is the citation metadata for the repository going forward; the
archived release remains the reproducibility target for this paper.

## Paper record

- Title: `LamTools：具备能力感知委派机制的本地优先 Agent 运行时 / LamTools: A Local-First Agent Runtime with Capability-Aware Delegation`
- Resource type: `Preprint` if that subtype is available; otherwise the accurate `Technical Report` / `Report` subtype
- Creators: Yulin Zhang, then Yiming Zhang
- Affiliation for each creator: `Independent Researcher`
- Proposed paper license: `CC BY 4.0`, subject to both authors' final approval
- Publisher: Zenodo
- Repository: `https://github.com/Lam-Arc/LamTools`
- Software version: `v0.2.6`
- Commit: `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`
- Upload exactly one combined PDF: `output/pdf/lamtools-technical-paper-bilingual-v0.2.6.pdf`
- Optional supplement: `output/supplement/lamtools-paper-supplement-v0.2.6.zip`
- Supplement includes manuscript sources, evidence, raw retrieval reports, figure source, and 300-dpi PNG/vector SVG figures; it contains no credentials or private data
- Language presentation: Chinese-primary version first, followed by the complete English version in the same PDF
- Do not create separate Zenodo records or separate Paper DOIs for the Chinese and English versions
- Optional source files may be added as supplementary files, but the Paper DOI identifies this single bilingual paper record
- Description: copy `docs/paper/zenodo-description.md`, noting that the same record contains the complete English version
- Reserved Paper DOI: `10.5281/zenodo.22040870`

The final paper PDF must be regenerated after the Software DOI is known so that
the DOI appears in the title metadata, the software reference, and the paper's
reproducibility information. The Paper DOI cannot be inserted until Zenodo
reserves it; therefore the final publication sequence is:

1. Archive the existing Software Release `v0.2.6` and record its exact DOI: `10.5281/zenodo.22039646`.
2. Insert that Software DOI into the paper source and rebuild/verify the PDF.
3. Create the Paper draft, upload the rebuilt PDF, and reserve the Paper DOI.
4. Insert the reserved Paper DOI into the final PDF, rebuild, and re-upload it.
5. Both authors perform the final metadata/PDF approval.
6. Publish the Paper record.

No DOI, publication status, affiliation, or author approval should be invented
before the corresponding Zenodo state exists.
