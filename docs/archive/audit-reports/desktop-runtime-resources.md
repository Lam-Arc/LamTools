# Desktop Runtime Resources

The desktop package keeps editable runtime resources outside the backend exe. Electron and Tauri both launch the same packaged Python backend and point it at the same `runtime/` resource tree.

Packaged layout:

```text
resources/
  backend/                  # packaged Python backend runtime
  runtime/
    core/
      skills/               # shared LamTools skills
      prompts/              # reserved for future shared prompts
    members/
      writer/
        prompts/writer/     # Writer system prompt fragments
        llm_adapters/       # Writer provider adapter profiles
        skills/             # Writer-specific skills
```

Build entry points:

- `npm run desktop:build`: Electron installer/portable build. It builds frontend assets, packages the backend, stages `dist/runtime`, and passes it through `electron-builder` as `resources/runtime`.
- `npm run desktop:unpacked`: refreshes `release/win-unpacked` directly and stages runtime resources beside the unpacked Electron backend.
- `npm run tauri:build`: Tauri bundle build. `tauri.conf.json` runs the same frontend/backend/resource staging before building.
- `npm run tauri:portable`: no-bundle Tauri build that copies `lamwriter.exe`, `lamwriter-backend`, and `runtime` into `src-tauri/target/release/LamWriter-portable`.
- `npm run desktop:parity-smoke`: compares the browser and packaged Electron composer path with Playwright. Set `LAMWRITER_PARITY_WEB_URL` or `LAMWRITER_PARITY_EXE` to override defaults.

Runtime environment:

- Electron sets `LAMTOOLS_RUNTIME_ROOT`, `LAMTOOLS_CORE_RESOURCE_DIR`, and `LAMWRITER_MEMBER_RESOURCE_DIR` from `process.resourcesPath/runtime`.
- Tauri sets the same variables from the packaged resource directory, or from an adjacent `runtime/` directory in portable mode.
- Browser/dev mode does not need these variables because backend resource discovery can walk up from the source checkout.

Frontend desktop bridge:

- Electron exposes `window.lamwriterDesktop` from `electron/preload.cjs`.
- Tauri creates the same bridge in `src/main.ts` by calling `get_api_base` and `select_directory`.
- Frontend code should call the shared bridge instead of branching on Electron or Tauri directly.

Source layout:

```text
core/
  skills/                   # shared skills for multiple members
members/
  writer/
    backend/app/prompts/    # Writer prompt source
    backend/app/llm_adapters/
    skills/                 # Writer-only skills
```

Resource ownership:

- Put a skill under `core/skills` only when multiple members can use it without product-specific behavior.
- Put a skill under `members/writer/skills` when it depends on Writer workflows, Writer UI/runtime behavior, or Writer product language.
- Keep prompt Markdown and adapter JSONC files editable. The backend loads external runtime resources before falling back to source/bundled files.

User override order:

- Environment variables such as `LAMWRITER_PROMPT_DIR` and `LAMWRITER_LLM_ADAPTER_DIR`.
- `%APPDATA%/LamWriter/...`.
- Packaged `resources/runtime/...`.
- Source or bundled fallback.

Do not commit generated package output:

- `members/writer/frontend/release/**`
- `members/writer/frontend/src-tauri/gen/**`
- `members/writer/frontend/src-tauri/target/**`
- `members/writer/dist/**`
