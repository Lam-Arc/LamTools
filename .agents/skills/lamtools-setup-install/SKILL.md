---
name: lamtools-setup-install
description: 'After a new Windows Inno Setup build or setup-version update for Sunday Core, locate the installer, install it into an isolated version directory under E:\setuptest, launch it, and verify the application and backend processes. For local packaged-build acceptance only; not for development mode or GitHub Releases.'
---

# Sunday Setup Installation and Launch Verification

Run this skill after every Sunday Windows setup build or setup-version update to smoke-test the locally installed build.

## When to use

- `scripts/package.ps1` or another build process has produced or updated `Sunday_<version>_x64-setup.exe`.
- The user asks to install, launch, and verify a newly built setup version.
- Do not use this for `npm run tauri dev` or `scripts/dev.ps1`, and do not treat it as a substitute for the GitHub Release process.

## Standard procedure

1. Start with the version explicitly provided by the user. If none was provided, let the helper select the newest setup from the Sunday Inno Setup output directory.
2. Use this skill's `scripts/install_setup.ps1`. By default it matches `core/desktop/src-tauri/target/release/bundle/inno/Sunday_<version>_x64-setup.exe` exactly, then checks for the same filename under `dist/` or `dist-plugins/` if needed.
3. Install into `E:\setuptest\<version>` by default. Use a separate directory for each version and do not delete older version directories.
4. After installation, launch `lamcore.exe` from the install directory. Wait for and verify that both the main application and `lamcore-backend\sunday-core.exe` processes run from that version directory.
5. The helper installs with Inno Setup options `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...`; do not fall back to NSIS `/S /D=...`.
6. Report the actual setup path, installation directory, version, and verified process PIDs. Stop at any failure; do not count an old process as a successful launch of the new version.

## Command

For a known version:

```powershell
& .\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -Version <version> -ForceCloseExisting
```

When the version is unknown and the newest build should be used:

```powershell
& .\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -ForceCloseExisting
```

If the setup is outside the default build directory, pass `-SetupPath <absolute path>`. To change the test root, pass `-InstallRoot <directory>`; the default is `E:\setuptest`.

`-ForceCloseExisting` only closes LamTools processes running from the target version's installation directory, for reinstalling that same version. Do not close processes from another directory or a development environment.

## Acceptance and boundaries

- If the setup file is missing, its filename version does not match the requested version, the installer returns a nonzero exit code, `lamcore.exe` is missing, or launch times out, report the failure immediately.
- Operate only on the user-specified setup and the isolated version directory. Do not delete older installations, change version numbers, commit, or push code or tags.
- Use the PowerShell helper's final JSON as evidence. If necessary, verify process paths with `Get-CimInstance Win32_Process`.
