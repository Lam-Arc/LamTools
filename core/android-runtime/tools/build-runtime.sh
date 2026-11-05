#!/usr/bin/env bash
# Builds the Linux runtime the Android app carries.
#
#   runtime/build-runtime.sh x86_64    # emulator ABI
#   runtime/build-runtime.sh aarch64   # phones
#
# What lands in the archive: Ubuntu 24.04 base + Python 3.14 (python-build-standalone)
# + the shipping Python core + its wheels, plus a start script. The app unpacks it and
# runs proot on top; nothing is compiled for the target and no foreign-arch code runs
# on the build host, so one x86_64 machine produces both ABIs.
#
# Why Ubuntu base rather than Alpine: the core's dependencies are glibc wheels
# (PyMuPDF, pillow, cryptography, sqlalchemy). A musl rootfs would need source builds
# for every one of them, which is a permanent maintenance cost for no user-visible gain.
#
# Output (consumed by the Android host):
#   out/<abi>/rootfs-<abi>.tar.gz
#   out/<abi>/manifest.json          versions, hashes, launch argv
#   out/<abi>/jniLibs/<abi>/*.so     proot + its loader + talloc + android-shmem
#
# Idempotent: downloads are cached and verified on every run.
set -euo pipefail

ABI="${1:-x86_64}"
case "$ABI" in
  x86_64)  UBUNTU_ARCH=amd64;  TERMUX_ARCH=x86_64;  PBS_ARCH=x86_64;  PY_TAG=manylinux_2_28_x86_64 ;;
  aarch64) UBUNTU_ARCH=arm64;  TERMUX_ARCH=aarch64; PBS_ARCH=aarch64; PY_TAG=manylinux_2_28_aarch64 ;;
  *) echo "usage: $0 {x86_64|aarch64}" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$HERE/../.." && pwd)"          # core/
REPO_DIR="$(cd "$CORE_DIR/.." && pwd)"         # repo root
CACHE="${SUNDAY_RT_CACHE:-$HOME/.cache/sunday-rt}"
OUT="${SUNDAY_RT_OUT:-$HERE/out}"
WORK="$CACHE/work-$ABI"

UBUNTU_VERSION=24.04.5
UBUNTU_SHA_AMD64=e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86
UBUNTU_SHA_ARM64=a91d5a93010193712d346d761372b7c9db6dfcf093893161c64ca107f05914f2
PROOT_VERSION=5.1.107.102
PROOT_SHA_X86_64=2497064226c15971be8131c7facead94a06c225347796326a383c832dca57758
PROOT_SHA_AARCH64=10a394b585c2fc2b2c8502544f4e5f1be581dc8bfff79e8ba62f16207423e030
TALLOC_VERSION=2.5.0
TALLOC_SHA_X86_64=b8c6d95f20075dc1f9ec6573575b2444e8d526e48e0d8d6d5cf4e071e6e06530
TALLOC_SHA_AARCH64=556591f43bb773ad8777e1a29522640866a55f95dab71914418b94a8c58ad5a7
SHMEM_VERSION=0.7
SHMEM_SHA_X86_64=ffa9e4c87467b158b148d0ff92dda796aa038276c2075af3269cdcdb06f25797
SHMEM_SHA_AARCH64=0da3a24d558b93c92bcf8d611e0826a99ff96e396b148e6cdf33b47c47c57ff6

PYTHON_VERSION=3.14.10
PBS_RELEASE=20261026
PBS_SHA_X86_64=4d3c16c59ed0802a3d1d34d8bce504b15ceeaff39d62dadecc6a9fa803412aed
PBS_SHA_AARCH64=90f48337bc3dd4ae6eda81e001e4c981236d403b6b5a07778bbdf94ee423dc00

UBUNTU_BASE_URL="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-cdimage/ubuntu-base/releases/24.04/release"
TERMUX_POOL="https://packages.termux.dev/apt/termux-main/pool/main"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_RELEASE"
PIP_INDEX="${PIP_INDEX_URL:-https://pypi.org/simple}"

RUNTIME_VERSION="1-$(date -u +%Y%m%d)"

log() { printf '\033[1;34m[runtime %s]\033[0m %s\n' "$ABI" "$*" >&2; }
die() { printf '\033[1;31m[runtime %s] error:\033[0m %s\n' "$ABI" "$*" >&2; exit 1; }

for tool in curl tar xz python3; do
  command -v "$tool" >/dev/null || die "missing host tool: $tool"
done
# pip is not installed system-wide on a stock WSL image (get-pip.py --user is enough).
PIP_PYTHON="${PIP_PYTHON:-python3}"
if ! "$PIP_PYTHON" -m pip --version >/dev/null 2>&1; then
  log "pip probe: PIP_PYTHON='$PIP_PYTHON'"
  "$PIP_PYTHON" -m pip --version || true
  die "no pip for '$PIP_PYTHON' (set PIP_PYTHON to an interpreter that has pip)"
fi

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

fetch() {  # fetch URL DEST SHA256 [FALLBACK_URL]
  local url="$1" dest="$2" want="$3" fallback="${4:-}"
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && [ "$(sha_of "$dest")" = "$want" ]; then return 0; fi
  log "download $(basename "$dest")"
  # -C - resumes a half-finished download: GitHub drops large release assets often
  # enough that a restart-from-zero policy turns one flaky minute into a failed build.
  if ! curl -fL --retry 5 --retry-delay 3 --retry-all-errors -C - --connect-timeout 20 -sS -o "$dest.part" "$url"; then
    [ -n "$fallback" ] || die "download failed: $url"
    log "primary failed, trying mirror"
    curl -fL --retry 5 --retry-delay 3 --retry-all-errors -C - --connect-timeout 20 -sS -o "$dest.part" "$fallback" \
      || die "download failed: $url (and mirror)"
  fi
  mv "$dest.part" "$dest"
  local got; got="$(sha_of "$dest")"
  [ "$got" = "$want" ] || { rm -f "$dest"; die "sha256 mismatch for $dest: got $got want $want"; }
}

# ---------------------------------------------------------------- downloads
case "$ABI" in
  x86_64)  UBUNTU_SHA=$UBUNTU_SHA_AMD64; PROOT_SHA=$PROOT_SHA_X86_64
           TALLOC_SHA=$TALLOC_SHA_X86_64; SHMEM_SHA=$SHMEM_SHA_X86_64; PBS_SHA=$PBS_SHA_X86_64 ;;
  aarch64) UBUNTU_SHA=$UBUNTU_SHA_ARM64; PROOT_SHA=$PROOT_SHA_AARCH64
           TALLOC_SHA=$TALLOC_SHA_AARCH64; SHMEM_SHA=$SHMEM_SHA_AARCH64; PBS_SHA=$PBS_SHA_AARCH64 ;;
esac

UBUNTU_TAR="$CACHE/ubuntu-base-${UBUNTU_VERSION}-base-${UBUNTU_ARCH}.tar.gz"
fetch "$UBUNTU_BASE_URL/$(basename "$UBUNTU_TAR")" "$UBUNTU_TAR" "$UBUNTU_SHA"

PROOT_DEB="$CACHE/proot_${PROOT_VERSION}_${TERMUX_ARCH}.deb"
TALLOC_DEB="$CACHE/libtalloc_${TALLOC_VERSION}_${TERMUX_ARCH}.deb"
SHMEM_DEB="$CACHE/libandroid-shmem_${SHMEM_VERSION}_${TERMUX_ARCH}.deb"
fetch "$TERMUX_POOL/p/proot/proot_${PROOT_VERSION}_${TERMUX_ARCH}.deb" "$PROOT_DEB" "$PROOT_SHA"
fetch "$TERMUX_POOL/libt/libtalloc/libtalloc_${TALLOC_VERSION}_${TERMUX_ARCH}.deb" "$TALLOC_DEB" "$TALLOC_SHA"
fetch "$TERMUX_POOL/liba/libandroid-shmem/libandroid-shmem_${SHMEM_VERSION}_${TERMUX_ARCH}.deb" "$SHMEM_DEB" "$SHMEM_SHA"

PY_TAR="$CACHE/cpython-${PYTHON_VERSION}-${PBS_ARCH}.tar.gz"
PY_NAME="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${PBS_ARCH}-unknown-linux-gnu-install_only_stripped.tar.gz"
# GitHub drops this asset often enough that a mirror belongs in the default path.
fetch "$PBS_URL/$PY_NAME" "$PY_TAR" "$PBS_SHA" \
  "https://registry.npmmirror.com/-/binary/python-build-standalone/$PBS_RELEASE/$PY_NAME"

# ---------------------------------------------------------------- rootfs
ROOTFS="$WORK/rootfs"
log "unpacking base rootfs"
rm -rf "$ROOTFS"
mkdir -p "$ROOTFS"
tar -xzf "$UBUNTU_TAR" -C "$ROOTFS"

mkdir -p "$ROOTFS"/{opt/sunday,root/.sunday/{data,work},tmp,var/lib/sunday/{empty,shm},etc/ssl/certs}
chmod 1777 "$ROOTFS/tmp"
chmod 700 "$ROOTFS/root"

log "installing python $PYTHON_VERSION"
tar -xzf "$PY_TAR" -C "$WORK"          # -> $WORK/python
rm -rf "$ROOTFS/opt/sunday/python"
mv "$WORK/python" "$ROOTFS/opt/sunday/python"
PYBIN="$ROOTFS/opt/sunday/python/bin/python3.14"
[ -x "$PYBIN" ] || die "python binary missing after unpack"

# python-build-standalone links its own OpenSSL, whose default trust store is
# $PREFIX/ssl/cert.pem; the Ubuntu base has no CA bundle. Ship one so urllib,
# and anything else that does not use certifi, can verify HTTPS.
mkdir -p "$ROOTFS/opt/sunday/python/ssl"
if [ ! -f "$ROOTFS/opt/sunday/python/ssl/cert.pem" ]; then
  curl -fL --retry 3 -sS -o "$ROOTFS/opt/sunday/python/ssl/cert.pem" https://curl.se/ca/cacert.pem \
    || log "warning: CA bundle download failed; certifi still covers httpx clients"
  cp "$ROOTFS/opt/sunday/python/ssl/cert.pem" "$ROOTFS/etc/ssl/certs/ca-certificates.crt" 2>/dev/null || true
fi

log "resolving wheels for $PY_TAG"
PYLIB="$ROOTFS/opt/sunday/pylib"
rm -rf "$PYLIB"; mkdir -p "$PYLIB"
WHEELS="$WORK/wheels"
rm -rf "$WHEELS"; mkdir -p "$WHEELS"
PLATFORMS=(--platform "$PY_TAG" --platform manylinux2014_"${PY_TAG##manylinux_2_28_}" --platform manylinux_2_17_"${PY_TAG##manylinux_2_28_}")
python3 -m pip download --quiet --no-cache-dir --disable-pip-version-check \
  --only-binary=:all: --python-version 3.14 --implementation cp \
  "${PLATFORMS[@]}" --index-url "$PIP_INDEX" -d "$WHEELS" -r "$HERE/requirements.txt" \
  || die "wheel resolution failed"
for wheel in "$WHEELS"/*.whl; do python3 -m zipfile -e "$wheel" "$PYLIB"; done
log "pylib: $(du -sh "$PYLIB" | cut -f1) in $(ls "$PYLIB" | wc -l) entries"

# ---------------------------------------------------------------- the core itself
log "copying the core"
APP="$ROOTFS/opt/sunday/app"
rm -rf "$APP"; mkdir -p "$APP"
tar -C "$CORE_DIR" -cf - \
  --exclude='__pycache__' --exclude='*.pyc' \
  src config skills \
  | tar -C "$APP" -xf -
# The config loader resolves bundled defaults as <pkg>/../../../config/resources.
[ -d "$APP/config/resources" ] || die "bundled resources missing from the image"

CORE_VERSION="$(sed -n 's/^version = "\([^"]*\)".*$/\1/p' "$CORE_DIR/pyproject.toml" | head -1 | tr -d '\r')"
[ -n "$CORE_VERSION" ] || die "could not read the core version from pyproject.toml"

# ---------------------------------------------------------------- guest entry
# android-shmem needs the directory proot binds over /dev/shm; both stay inside the
# rootfs so the app can clear the whole tree without touching the device.
mkdir -p "$ROOTFS/var/lib/sunday/shm"
cat > "$ROOTFS/opt/sunday/start_core.py" <<'PY'
"""Guest entry point: start the shipping core on loopback.

The host passes the port; everything else is fixed. LAMTOOLS_CORE_ALLOW_LAN and
LAMTOOLS_CORE_API_TOKEN come from the host environment, so the API demands a bearer
token even from loopback callers — on a phone, "loopback" includes every other app.
"""
import os
import sys
import traceback

# Read the port before argv is replaced: the CLI entry parses sys.argv itself, so the
# launch argument has to survive into a variable first.
port = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUNDAY_CORE_PORT", "5172")
sys.path[:0] = ["/opt/sunday/app/src", "/opt/sunday/pylib"]
sys.argv = ["core"]

def main() -> int:
    from lamtools_core.cli_commands.entry import main as cli_main
    return cli_main([
        "serve",
        "--host", "127.0.0.1",
        "--port", port,
        "--data-dir", "/root/.sunday/data",
        "--work-root", "/root/.sunday/work",
    ])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        raise SystemExit(3)
PY
sed -i 's/\r$//' "$ROOTFS/opt/sunday/start_core.py"

# ---------------------------------------------------------------- proot binaries
JNI="$OUT/$ABI/jniLibs/$ABI"
rm -rf "$OUT/$ABI"
mkdir -p "$JNI" "$OUT/$ABI/assets/runtime"

extract_deb() {  # extract_deb DEB DEST_FILE SOURCE_PATH_IN_DEB
  local deb="$1" dest="$2" inner="$3" tmp; tmp="$(mktemp -d)"
  ar p "$deb" data.tar.xz > "$tmp/data.tar.xz" 2>/dev/null || ar p "$deb" data.tar.gz > "$tmp/data.tar.gz"
  if [ -s "$tmp/data.tar.xz" ]; then tar -xJf "$tmp/data.tar.xz" -C "$tmp"; else tar -xzf "$tmp/data.tar.gz" -C "$tmp"; fi
  cp "$tmp/data/data/com.termux/files/usr/$inner" "$dest"
  chmod 755 "$dest"
  rm -rf "$tmp"
}

command -v ar >/dev/null || die "missing host tool: ar (binutils)"
extract_deb "$PROOT_DEB"  "$JNI/libproot.so"               bin/proot
extract_deb "$PROOT_DEB"  "$JNI/libproot-loader.so"        libexec/proot/loader
extract_deb "$TALLOC_DEB" "$JNI/libtalloc.so.2"            lib/libtalloc.so.2
extract_deb "$SHMEM_DEB"  "$JNI/libandroid-shmem.so"       lib/libandroid-shmem.so

# ---------------------------------------------------------------- archive
log "compressing rootfs"
ROOTFS_NAME="rootfs-$ABI.tar.gz"
UNCOMPRESSED="$(du -sb "$ROOTFS" | cut -f1)"
tar -C "$ROOTFS" -czf "$OUT/$ABI/assets/runtime/$ROOTFS_NAME" --numeric-owner .
ROOTFS_BYTES="$(stat -c %s "$OUT/$ABI/assets/runtime/$ROOTFS_NAME")"
ROOTFS_SHA="$(sha_of "$OUT/$ABI/assets/runtime/$ROOTFS_NAME")"

cat > "$OUT/$ABI/assets/runtime/manifest.json" <<JSON
{
  "runtimeVersion": "$RUNTIME_VERSION",
  "abi": "$ABI",
  "rootfs": "$ROOTFS_NAME",
  "rootfsBytes": $ROOTFS_BYTES,
  "rootfsSha256": "$ROOTFS_SHA",
  "uncompressedBytes": $UNCOMPRESSED,
  "pythonVersion": "$PYTHON_VERSION",
  "coreVersion": "$CORE_VERSION",
  "prootVersion": "$PROOT_VERSION",
  "launch": {
    "argv": [
      "{NATIVE_LIB_DIR}/libproot.so",
      "--kill-on-exit", "--link2symlink", "--sysvipc", "-L", "-0",
      "--rootfs={ROOTFS}", "--cwd=/root",
      "-b", "/dev",
      "-b", "/dev/urandom:/dev/random",
      "-b", "/proc",
      "-b", "/proc/self/fd:/dev/fd",
      "-b", "/proc/self/fd/0:/dev/stdin",
      "-b", "/proc/self/fd/1:/dev/stdout",
      "-b", "/proc/self/fd/2:/dev/stderr",
      "-b", "/sys",
      "-b", "{ROOTFS}/var/lib/sunday/empty:/sys/fs/selinux",
      "-b", "{ROOTFS}/var/lib/sunday/shm:/dev/shm",
      "-b", "/system",
      "-b", "/apex",
      "/usr/bin/env", "-i",
      "HOME=/root", "USER=root", "LOGNAME=root", "SHELL=/bin/sh",
      "LAMTOOLS_HOME=/root/.sunday",
      "PATH=/opt/sunday/python/bin:/usr/local/bin:/usr/bin:/bin",
      "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "TERM=dumb", "TMPDIR=/tmp",
      "PYTHONPATH=/opt/sunday/app/src:/opt/sunday/pylib",
      "PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1",
      "SSL_CERT_FILE=/opt/sunday/pylib/certifi/cacert.pem",
      "LAMTOOLS_CORE_ALLOW_LAN=1",
      "{GUEST_ENV}",
      "/opt/sunday/python/bin/python3.14", "/opt/sunday/start_core.py", "{PORT}"
    ],
    "env": {
      "PROOT_LOADER": "{NATIVE_LIB_DIR}/libproot-loader.so",
      "PROOT_TMP_DIR": "{TMP}",
      "PROOT_L2S_DIR": "{ROOTFS}/root/.l2s",
      "LD_LIBRARY_PATH": "{NATIVE_LIB_DIR}"
    },
    "placeholders": {
      "{NATIVE_LIB_DIR}": "applicationInfo.nativeLibraryDir (libs extracted: useLegacyPackaging=true)",
      "{ROOTFS}": "filesDir/runtime/rootfs",
      "{TMP}": "cacheDir/proot-tmp",
      "{PORT}": "loopback port chosen by the host",
      "{GUEST_ENV}": "standalone element: zero or more KEY=VALUE (LAMTOOLS_CORE_API_TOKEN, TZ)"
    }
  }
}
JSON

log "done: $OUT/$ABI ($(du -sh "$OUT/$ABI" | cut -f1)) rootfs=$ROOTFS_BYTES bytes core=$CORE_VERSION python=$PYTHON_VERSION"
