# Android runtime

The Linux environment Sunday carries on a phone. The Android app unpacks this archive
once, starts `proot` on it, and the archive's own `start_core.py` starts the **shipping
Python core** — the same `core/src/lamtools_core` the desktop app runs.

Nothing here reimplements a feature. The runtime exists so one business core serves both
platforms.

## Build

```bash
# from a Linux host (WSL is fine); no foreign-architecture code is executed
core/android-runtime/tools/build-runtime.sh x86_64    # emulator
core/android-runtime/tools/build-runtime.sh aarch64   # phones
```

Output, consumed by `core/android-host`:

```
out/<abi>/assets/runtime/manifest.json        versions, hashes, launch argv
out/<abi>/assets/runtime/rootfs-<abi>.tar.gz  Ubuntu base + Python + core + wheels
out/<abi>/jniLibs/<abi>/libproot.so           proot and the libraries it needs
```

`SUNDAY_RT_CACHE` overrides the download cache (`~/.cache/sunday-rt`),
`SUNDAY_RT_OUT` the output directory.

## What is inside, and why

| Piece | Choice | Why |
| --- | --- | --- |
| Userspace | Ubuntu 24.04 base | The core's dependencies are glibc wheels. A musl rootfs would need a source build for PyMuPDF, pillow, cryptography and sqlalchemy — permanent maintenance for no user-visible gain. |
| Isolation | Termux proot 5.1.107.102 | No root, no kernel patches; the same binary dsh-Go ships and Termux maintains. |
| Python | python-build-standalone 3.14.10 | Portable glibc build with SSL, sqlite3, lzma and ctypes intact, for both ABIs. The core declares `requires-python >=3.14`. |
| Dependencies | `build/requirements.txt`, resolved per ABI | Every wheel is `manylinux` aarch64/x86_64; no compiler runs on the phone or in the app. |
| Core | `core/src`, `core/config`, `core/skills` | Copied from the checkout at build time: the runtime cannot drift from the core it is supposed to run. |

Verified on an Android 16 x86_64 emulator: Python 3.14.10 reports glibc 2.39, imports
sqlite3/ssl/lzma/ctypes/multiprocessing/socket, pip reaches PyPI, and the core starts,
migrates its database and answers `GET /api/core/projects` with a bearer token.

## Known limits

* One ABI per APK. The archive carries that ABI's interpreter, so a universal build would
  ship the wrong Python half the time.
* `proot` is userspace emulation-free but still translates paths on every syscall. Startup
  takes seconds; a heavy `run_command` is slower than on desktop.
* No system timezone database in the base image; `TZ` comes from the host environment.
* The runtime is ~200 MB compressed, ~600 MB unpacked. First launch pays for the unpack.
