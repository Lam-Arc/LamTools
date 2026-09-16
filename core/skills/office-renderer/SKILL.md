---
name: office-renderer
description: Validate canonical Office data bindings, render DOCX/XLSX/PPTX/PDF files, and report page-level layout conflicts. Use as the deterministic execution companion for data-bearing Office artifacts; do not use for content drafting alone.
metadata:
  version: 0.2.2
  language: en
  target: lamtools-desktop
  status: beta
---

# Office renderer

Use this supporting Skill after an Office authoring Skill has created a final source file and `office-data.json`.

## Direct execution

The documented CLI and JSON reports are the public runtime contract. Use them directly from the task project.

An environment preflight is optional. When readiness is uncertain, run this single command once:

```powershell
py -3.14 -m lamtools_core.cli office check
```

`Office 应用已就绪 · Test Passed 3/3` confirms that Word, Excel, and PowerPoint-format conversion is ready. Continue with the final artifact workflow after that result.

Follow this minimal path directly:

1. Write canonical datasets to the task's single `office-data.json` before creating data-bearing tables or charts.
2. Generate the final Office source file, then add its actual hash and bindings to the manifest.
3. Run `office validate` once against the final source.
4. If validation passes, run `office render` once against the same source and manifest.
5. Use a returned structured error to fix the named source page, object, text, or binding, then restart at validation.

If the normal CLI reports that `lamtools_core` cannot be imported or its `office` command is unavailable, use the bundled script entry point. Report other environment/backend errors from the structured result.

## Commands

The host-stable entry point works from any project directory:

```powershell
py -3.14 -m lamtools_core.cli office validate --source <office-file> --manifest <office-data.json> --report <validate-report.json>
py -3.14 -m lamtools_core.cli office render --source <office-file> --manifest <office-data.json> --output-dir <preview-dir> --backend auto --report <render-report.json>
```

In a standalone Skill checkout where `lamtools_core` is unavailable, run the bundled program directly:

```powershell
py -3.14 <skill-directory>\scripts\office.py validate --source <office-file> --manifest <office-data.json> --report <validate-report.json>
py -3.14 <skill-directory>\scripts\office.py render --source <office-file> --manifest <office-data.json> --output-dir <preview-dir> --backend auto --report <render-report.json>
```

Read [the data and rendering contract](../references/office-renderer-contract.md) before constructing the manifest. Validation failure is a hard stop. Do not render or claim success when the report says data, structure, rendering, or layout validation failed.

After rendering, inspect every generated page/sheet preview image once when the task requires visual review. Inspecting only representative pages is a sampled review and must be reported with the exact pages viewed; it is not a whole-document visual pass. A programmatic `visual=passed` result means only that the renderer's automated rules passed, not that a human or vision-capable model reviewed every preview.

## Bundled program

`scripts/office.py` is the executable entry point. Its `lamtools_office_renderer` package owns manifest validation, Office conversion, PDF/PNG generation, and deterministic overlap diagnostics. Keep command output as JSON so an Agent can report the exact page, object, text, expected value, and actual value.
