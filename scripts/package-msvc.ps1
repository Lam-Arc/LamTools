# Package LamCore with MSVC toolchain preloaded.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\package-msvc.ps1
$ErrorActionPreference = "Stop"

# 1) Load MSVC environment (link.exe, cl.exe, SDK libs) — must precede Git's
#    GNU link.exe on PATH so cargo links with the MSVC linker.
$vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) {
    Write-Error "vcvars64.bat not found at $vcvars"
    exit 1
}
cmd /c "`"$vcvars`" && set" | ForEach-Object {
    if ($_ -match "^(.*?)=(.*)$") {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}

# 2) Prepend Rust MSVC toolchain bin (cargo/rustc) — rustup default already
#    points at stable-x86_64-pc-windows-msvc.
$cargoBin = "$env:USERPROFILE\.cargo\bin"
if (Test-Path $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}

# 3) Sanity: ensure the linker that cargo will find is MSVC's link.exe.
$linkPath = (Get-Command link.exe -ErrorAction SilentlyContinue).Source
Write-Host "link.exe -> $linkPath"
if ($linkPath -notmatch "Microsoft Visual Studio") {
    Write-Warning "link.exe is not MSVC's; check PATH ordering"
}

# 4) Run the standard package script.
& "$PSScriptRoot\package.ps1"
exit $LASTEXITCODE
