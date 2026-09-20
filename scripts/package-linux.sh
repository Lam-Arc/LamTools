#!/usr/bin/env bash
# Build the native Linux sidecar and Tauri bundles from Ubuntu/WSL.
#
# This script intentionally runs every toolchain cache from the Linux home (or
# an explicit LAMTOOLS_LINUX_TOOL_ROOT), never from a Windows C: mount.  The
# repository checkout and generated artifacts may remain on /mnt/e.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TOOL_ROOT="${LAMTOOLS_LINUX_TOOL_ROOT:-${XDG_CACHE_HOME:-"$HOME/.cache"}/lamtools-linux}"
NODE_VERSION="${LAMTOOLS_NODE_VERSION:-24.17.0}"
NPM_VERSION="${LAMTOOLS_NPM_VERSION:-11.17.0}"
PYINSTALLER_VERSION="${LAMTOOLS_PYINSTALLER_VERSION:-6.20.0}"
BUILD_ROOT="$TOOL_ROOT/build"
VENV="$BUILD_ROOT/venv"
SOURCE_ROOT="$BUILD_ROOT/source"

die() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

info() {
  printf '[INFO] %s\n' "$*"
}

guard_path() {
  local path
  path="$(realpath -m "$1")"
  case "$path" in
    /mnt/c|/mnt/c/*)
      die "Refusing to use a C: mounted path: $path"
      ;;
  esac
}

remove_tool_path() {
  local target resolved_root resolved_target
  target="$1"
  resolved_root="$(realpath -m "$TOOL_ROOT")"
  resolved_target="$(realpath -m "$target")"
  [[ "$resolved_target" == "$resolved_root"/* ]] \
    || die "Refusing to delete outside the Linux tool root: $resolved_target"
  rm -rf -- "$resolved_target"
}

remove_exact_repo_dir() {
  local target expected
  target="$(realpath -m "$1")"
  expected="$(realpath -m "$2")"
  [[ "$target" == "$expected" ]] \
    || die "Refusing to delete an unexpected repository output: $target"
  rm -rf -- "$target"
}

guard_path "$ROOT"
guard_path "$TOOL_ROOT"
mkdir -p "$TOOL_ROOT/bin" "$BUILD_ROOT"

export PATH="$TOOL_ROOT/bin:$PATH"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$TOOL_ROOT/cache}"
export CARGO_HOME="${CARGO_HOME:-$TOOL_ROOT/cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-$TOOL_ROOT/rustup}"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-$TOOL_ROOT/npm-cache}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$TOOL_ROOT/pip-cache}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$TOOL_ROOT/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$TOOL_ROOT/python}"
for _cache_path in "$XDG_CACHE_HOME" "$CARGO_HOME" "$RUSTUP_HOME" \
  "$NPM_CONFIG_CACHE" "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"; do
  guard_path "$_cache_path"
done

if [[ "$(uname -s)" != "Linux" ]]; then
  die "Linux native packaging must run under Linux/WSL (got $(uname -s))"
fi

if [[ ! -f "$ROOT/core/desktop/src-tauri/tauri.conf.json" ]]; then
  die "repository root not found: $ROOT"
fi

if ! command -v pkg-config >/dev/null 2>&1; then
  die "pkg-config is required; install the Ubuntu build dependencies including libdbus-1-dev"
fi
for _pkg in gtk+-3.0 webkit2gtk-4.1 javascriptcoregtk-4.1 dbus-1; do
  if ! pkg-config --exists "$_pkg"; then
    die "missing native dependency $_pkg; install libgtk-3-dev libwebkit2gtk-4.1-dev libdbus-1-dev"
  fi
done

# Build from the WSL ext4 filesystem rather than the /mnt/e DrvFs checkout.
# This avoids mutating the shared Windows node_modules and keeps Cargo and
# PyInstaller's many small-file operations off the comparatively slow mount.
info "Staging source into the WSL filesystem: $SOURCE_ROOT"
remove_tool_path "$SOURCE_ROOT"
mkdir -p "$SOURCE_ROOT"
tar -C "$ROOT" \
  --exclude='.git' \
  --exclude='*/node_modules' \
  --exclude='core/dist' \
  --exclude='core/desktop/dist' \
  --exclude='core/desktop/src-tauri/target' \
  --exclude='core/build' \
  --exclude='core/.lam' \
  --exclude='core/data' \
  --exclude='core/core.db' \
  --exclude='core/backend.log' \
  --exclude='core/.tmp*' \
  --exclude='core/test-proj' \
  --exclude='core/tests' \
  --exclude='core/docs' \
  --exclude='core/mobile' \
  --exclude='core/remote' \
  --exclude='core/desktop/tauri-dev.log' \
  --exclude='*/__pycache__' \
  --exclude='*/.pytest_cache' \
  -cf - core/desktop core/ui core/src core/config core/skills \
  core/pyproject.toml core/lamtools-core-backend.spec core/desktop_backend.py \
  scripts/package-linux.sh scripts/verify-backend-ws.py \
  | tar -C "$SOURCE_ROOT" -xf -

# The explicit cleanup protects against tar pattern behavior changes and also
# removes generated files left by a previous interrupted build.
for _stale_path in \
  "$SOURCE_ROOT/core/build" \
  "$SOURCE_ROOT/core/dist" \
  "$SOURCE_ROOT/core/desktop/dist" \
  "$SOURCE_ROOT/core/desktop/src-tauri/target"; do
  if [[ -e "$_stale_path" ]]; then
    remove_tool_path "$_stale_path"
  fi
done

# Node is downloaded instead of using /mnt/c/Program Files/nodejs.  This also
# makes the Linux npm optional-dependency selection deterministic.
NODE_ROOT="$TOOL_ROOT/node-v${NODE_VERSION}-linux-x64"
if [[ ! -x "$NODE_ROOT/bin/node" ]]; then
  _node_archive="$TOOL_ROOT/node-v${NODE_VERSION}-linux-x64.tar.xz"
  if [[ ! -f "$_node_archive" ]]; then
    info "Downloading Node.js v${NODE_VERSION} into $TOOL_ROOT"
    curl --fail --location --retry 3 --output "$_node_archive" \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
  fi
  tar -xJf "$_node_archive" -C "$TOOL_ROOT"
fi
export PATH="$NODE_ROOT/bin:$PATH"
if [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
  die "Node 24 is required (found $(node --version))"
fi
if [[ "$(npm --version | cut -d. -f1)" -lt 11 ]]; then
  die "npm 11 is required (found $(npm --version))"
fi
if [[ "$(npm --version)" != "$NPM_VERSION" ]]; then
  info "Selecting npm ${NPM_VERSION} in the E: backed Node installation"
  npm install --global --prefix "$NODE_ROOT" "npm@${NPM_VERSION}"
fi

# Install uv into the Linux tool root if it is not already available there.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv into $TOOL_ROOT/bin"
  curl --fail --location --retry 3 https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR="$TOOL_ROOT/bin" sh -s -- --no-modify-path
fi
command -v uv >/dev/null 2>&1 || die "uv installation did not produce an executable"

# Rustup and Cargo state are explicitly rooted in the WSL filesystem.  Do not
# treat an apt-provided rustc/cargo, or rustup shims with no installed
# toolchain, as a usable build toolchain: Tauri's lockfile requires the current
# stable Cargo rather than Ubuntu 22.04's older package.
RUSTUP_BIN="$CARGO_HOME/bin/rustup"
if [[ ! -x "$RUSTUP_BIN" ]] || ! "$RUSTUP_BIN" --version >/dev/null 2>&1; then
  info "Installing rustup into $TOOL_ROOT"
  curl --proto '=https' --tlsv1.2 --fail --location --retry 3 https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain none --no-modify-path
fi
export PATH="$CARGO_HOME/bin:$PATH"
command -v rustup >/dev/null 2>&1 || die "rustup is unavailable after setup"
rustup --version >/dev/null 2>&1 || die "rustup cannot execute after setup"

# Install/select stable explicitly even when a prior interrupted bootstrap left
# valid rustup shims behind.  RUSTUP_DIST_SERVER and RUSTUP_UPDATE_ROOT remain
# caller-overridable for restricted networks; the default is rustup's official
# distribution service.
if ! rustc --version >/dev/null 2>&1 || ! cargo --version >/dev/null 2>&1; then
  info "Installing the stable Rust toolchain into $TOOL_ROOT"
  rustup toolchain install stable --profile minimal
fi
rustup default stable >/dev/null
rustc --version >/dev/null 2>&1 || die "rustc is unavailable after rustup setup"
cargo --version >/dev/null 2>&1 || die "cargo is unavailable after rustup setup"

info "Using $(node --version), npm $(npm --version), $(uv --version), $(rustc --version)"

# Project policy requires Python >=3.14.  uv's managed interpreter is kept in
# the same E-backed tool root; Ubuntu 22.04's system Python 3.10 is not used.
uv python install 3.14
PYTHON_BIN="$(uv python find 3.14)"
[[ -x "$PYTHON_BIN" ]] || die "uv did not provide a Python 3.14 interpreter"
if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,14) else 1)'; then
  remove_tool_path "$VENV"
  uv venv --python "$PYTHON_BIN" "$VENV"
fi
PYTHON_BIN="$VENV/bin/python"
"$PYTHON_BIN" -c 'import sys; print("Using", sys.executable, sys.version)' \
  || die "Python virtual environment is not runnable"
uv pip install --python "$PYTHON_BIN" --upgrade \
  "pyinstaller==${PYINSTALLER_VERSION}" "$SOURCE_ROOT/core[desktop]"

info "Installing Linux npm dependencies in core/ui and core/desktop"
pushd "$SOURCE_ROOT/core/ui" >/dev/null
npm ci
popd >/dev/null
pushd "$SOURCE_ROOT/core/desktop" >/dev/null
npm ci
info "Building the desktop frontend"
npm run build
popd >/dev/null

info "Building the Linux PyInstaller sidecar"
pushd "$SOURCE_ROOT/core" >/dev/null
"$PYTHON_BIN" -m PyInstaller lamtools-core-backend.spec --clean --noconfirm
popd >/dev/null

SIDECAR="$SOURCE_ROOT/core/dist/LamCore/LamCore"
[[ -f "$SIDECAR" ]] || die "Linux sidecar missing: $SIDECAR"
chmod +x "$SIDECAR"
info "Running packaged backend REST/WebSocket/Study smoke"
SMOKE_PORT="${LAMTOOLS_LINUX_SMOKE_PORT:-$(shuf -i 20000-60000 -n 1)}"
"$PYTHON_BIN" "$ROOT/scripts/verify-backend-ws.py" --exe "$SIDECAR" --port "$SMOKE_PORT"

info "Building AppImage and .deb bundles"
pushd "$SOURCE_ROOT/core/desktop" >/dev/null
BUNDLE_ROOT="$SOURCE_ROOT/core/desktop/src-tauri/target/release/bundle"
_appimage_product_name="$(node -e 'const fs=require("fs"); const config=JSON.parse(fs.readFileSync("src-tauri/tauri.conf.json", "utf8")); process.stdout.write(config.productName);')"
[[ -n "$_appimage_product_name" ]] || die "Tauri productName is empty"
_appimage_version="$(node -e 'const fs=require("fs"); const config=JSON.parse(fs.readFileSync("src-tauri/tauri.conf.json", "utf8")); process.stdout.write(config.version);')"
[[ -n "$_appimage_version" ]] || die "Tauri version is empty"
_appimage_appdir="$BUNDLE_ROOT/appimage/${_appimage_product_name}.AppDir"
_appimage_output="$BUNDLE_ROOT/appimage/${_appimage_product_name}_${_appimage_version}_amd64.AppImage"

# Keep valid helper downloads across builds. Missing or interrupted helpers are
# fetched with retries into a sibling temporary file, then atomically renamed;
# Tauri's one-shot downloader is too fragile for transient GitHub/raw failures.
ensure_tauri_tool() {
  local target="$1" url="$2" refresh="${3:-0}" temp
  if [[ "$refresh" != "1" && -s "$target" ]]; then
    chmod +x "$target"
    return
  fi
  mkdir -p "$(dirname "$target")"
  temp="$(mktemp "${target}.tmp.XXXXXX")"
  if ! curl --fail --location --retry 10 --retry-all-errors \
    --connect-timeout 20 --max-time 600 --output "$temp" "$url"; then
    rm -f -- "$temp"
    die "Could not download Tauri bundle helper: $url"
  fi
  [[ -s "$temp" ]] || {
    rm -f -- "$temp"
    die "Downloaded Tauri bundle helper is empty: $url"
  }
  chmod +x "$temp"
  mv -f -- "$temp" "$target"
}

ensure_tauri_tool \
  "$XDG_CACHE_HOME/tauri/linuxdeploy-plugin-gtk.sh" \
  "https://raw.githubusercontent.com/tauri-apps/linuxdeploy-plugin-gtk/9c374854776c37af0b82f32083bc0764d3f19261/linuxdeploy-plugin-gtk.sh" \
  1
ensure_tauri_tool \
  "$XDG_CACHE_HOME/tauri/linuxdeploy-plugin-gstreamer.sh" \
  "https://raw.githubusercontent.com/tauri-apps/linuxdeploy-plugin-gstreamer/master/linuxdeploy-plugin-gstreamer.sh"
ensure_tauri_tool \
  "$XDG_CACHE_HOME/tauri/linuxdeploy-plugin-appimage.AppImage" \
  "https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage"

# The current linuxdeploy AppImage plugin delegates to appimagetool, whose
# runtime download is a separate GitHub request and can fail after linuxdeploy
# itself succeeds.  Keep the runtime in the WSL tool root and pass it through
# the plugin's documented LDAI_RUNTIME_FILE hook so packaging is reproducible.
TAURI_RUNTIME_FILE="$TOOL_ROOT/cache/tauri/runtime-x86_64"
guard_path "$TAURI_RUNTIME_FILE"
if [[ ! -s "$TAURI_RUNTIME_FILE" ]]; then
  info "Downloading the AppImage runtime into $TOOL_ROOT"
  mkdir -p "$(dirname "$TAURI_RUNTIME_FILE")"
  curl --fail --location --retry 3 --output "$TAURI_RUNTIME_FILE" \
    https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64
fi
[[ -s "$TAURI_RUNTIME_FILE" ]] || die "AppImage runtime is unavailable: $TAURI_RUNTIME_FILE"
export LDAI_RUNTIME_FILE="$TAURI_RUNTIME_FILE"

# linuxdeploy mutates the AppDir in place.  Always remove generated bundle
# state before the first attempt and after a failed attempt so a retry cannot
# trip over stale links or partially copied GTK files.
remove_tool_path "$_appimage_appdir"
remove_tool_path "$_appimage_output"
_bundle_built=0
for _bundle_attempt in 1 2 3; do
  if npx tauri build --bundles appimage,deb; then
    _bundle_built=1
    break
  fi
  remove_tool_path "$_appimage_appdir"
  remove_tool_path "$_appimage_output"
  if [[ "$_bundle_attempt" -lt 3 ]]; then
    info "Tauri bundle attempt $_bundle_attempt failed; retrying cached/downloaded bundle tools"
    sleep 2
  fi
done
[[ "$_bundle_built" == 1 ]] || die "Tauri AppImage/.deb bundling failed after 3 attempts"
popd >/dev/null

APPIMAGE="$(find "$BUNDLE_ROOT/appimage" -maxdepth 1 -type f -name '*.AppImage' -print -quit 2>/dev/null || true)"
DEB="$(find "$BUNDLE_ROOT/deb" -maxdepth 1 -type f -name '*.deb' -print -quit 2>/dev/null || true)"
[[ -n "$APPIMAGE" && -f "$APPIMAGE" ]] || die "AppImage artifact was not produced"
[[ -n "$DEB" && -f "$DEB" ]] || die ".deb artifact was not produced"
chmod +x "$APPIMAGE"

info "Checking package formats and embedded sidecar"
file "$APPIMAGE" | grep -Eiq 'ELF|AppImage' || die "AppImage file signature check failed"
dpkg-deb --info "$DEB" >/dev/null || die ".deb metadata check failed"
_deb_contents="$BUILD_ROOT/deb-contents.txt"
dpkg-deb --contents "$DEB" >"$_deb_contents" \
  || die ".deb contents could not be listed"
grep -Eq 'lamcore-backend/LamCore([[:space:]]|$)' "$_deb_contents" \
  || die ".deb does not contain lamcore-backend/LamCore"
_appimage_extract_root="$BUILD_ROOT/appimage-extract"
remove_tool_path "$_appimage_extract_root"
mkdir -p "$_appimage_extract_root"
(
  cd "$_appimage_extract_root"
  "$APPIMAGE" --appimage-extract >/dev/null
)
_appimage_sidecar="$(find "$_appimage_extract_root/squashfs-root" -type f \
  -path '*/lamcore-backend/LamCore' -print -quit 2>/dev/null || true)"
[[ -n "$_appimage_sidecar" && -x "$_appimage_sidecar" ]] \
  || die "AppImage does not contain an executable lamcore-backend/LamCore"

if [[ "${LAMTOOLS_SKIP_XVFB_SMOKE:-0}" != "1" ]] && command -v xvfb-run >/dev/null 2>&1; then
  command -v dbus-run-session >/dev/null 2>&1 \
    || die "dbus-run-session is required for the Xvfb WebKitGTK smoke"
  command -v setsid >/dev/null 2>&1 \
    || die "setsid is required for isolated AppImage smoke cleanup"
  info "Starting the AppImage briefly under Xvfb"
  _xvfb_home="$BUILD_ROOT/xvfb-home"
  mkdir -p "$_xvfb_home" "$_xvfb_home/runtime"
  chmod 700 "$_xvfb_home/runtime"
  declare -A _smoke_backend_start_times=()

  _is_descendant_of() {
    local pid="$1" ancestor="$2" parent
    while [[ "$pid" =~ ^[0-9]+$ ]] && (( pid > 1 )); do
      [[ "$pid" == "$ancestor" ]] && return 0
      [[ -r "/proc/$pid/status" ]] || return 1
      parent="$(awk '/^PPid:/ { print $2; exit }' "/proc/$pid/status")"
      [[ "$parent" =~ ^[0-9]+$ && "$parent" != "$pid" ]] || return 1
      pid="$parent"
    done
    return 1
  }

  _record_smoke_backends() {
    local status pid exe start_time
    for status in /proc/[0-9]*/status; do
      [[ -r "$status" ]] || continue
      pid="${status#/proc/}"
      pid="${pid%/status}"
      _is_descendant_of "$pid" "$_smoke_root_pid" || continue
      exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
      [[ "$exe" == */lamcore-backend/LamCore ]] || continue
      start_time="$(awk '{ print $22 }' "/proc/$pid/stat" 2>/dev/null || true)"
      [[ -n "$start_time" ]] && _smoke_backend_start_times["$pid"]="$start_time"
    done
  }

  _same_live_process() {
    local pid="$1" expected_start="$2" state actual_start
    [[ -r "/proc/$pid/stat" ]] || return 1
    state="$(awk '{ print $3 }' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ "$state" != "Z" && -n "$state" ]] || return 1
    actual_start="$(awk '{ print $22 }' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ "$actual_start" == "$expected_start" ]]
  }

  set +e
  # setsid makes timeout the leader of a smoke-only process group. GNU timeout
  # can therefore terminate its wrapper tree without touching unrelated D-Bus,
  # Xvfb, desktop, or backend processes on the build host.
  setsid timeout --kill-after=5s 45s env \
    APPIMAGE_EXTRACT_AND_RUN=1 \
    XDG_DATA_HOME="$_xvfb_home/data" \
    XDG_CONFIG_HOME="$_xvfb_home/config" \
    XDG_CACHE_HOME="$_xvfb_home/cache" \
    XDG_RUNTIME_DIR="$_xvfb_home/runtime" \
    dbus-run-session -- xvfb-run --auto-servernum --server-args='-screen 0 1440x900x24' \
    "$APPIMAGE" >"$_xvfb_home/appimage.log" 2>&1 &
  _smoke_root_pid=$!
  while kill -0 "$_smoke_root_pid" 2>/dev/null; do
    _record_smoke_backends
    sleep 0.25
  done
  wait "$_smoke_root_pid"
  _xvfb_rc=$?
  set -e

  if (( ${#_smoke_backend_start_times[@]} == 0 )); then
    printf '%s\n' '--- AppImage smoke log (last 100 lines) ---' >&2
    tail -n 100 "$_xvfb_home/appimage.log" >&2 || true
    die "Xvfb AppImage smoke never observed the bundled LamCore sidecar"
  fi

  _smoke_cleanup_deadline=$((SECONDS + 5))
  while (( SECONDS < _smoke_cleanup_deadline )); do
    _smoke_survivors=0
    for _smoke_pid in "${!_smoke_backend_start_times[@]}"; do
      if _same_live_process "$_smoke_pid" "${_smoke_backend_start_times[$_smoke_pid]}"; then
        _smoke_survivors=1
        break
      fi
    done
    (( _smoke_survivors == 0 )) && break
    sleep 0.1
  done

  _smoke_survivor_pids=()
  for _smoke_pid in "${!_smoke_backend_start_times[@]}"; do
    if _same_live_process "$_smoke_pid" "${_smoke_backend_start_times[$_smoke_pid]}"; then
      _smoke_survivor_pids+=("$_smoke_pid")
      kill -TERM "$_smoke_pid" 2>/dev/null || true
    fi
  done
  if (( ${#_smoke_survivor_pids[@]} > 0 )); then
    sleep 1
    for _smoke_pid in "${_smoke_survivor_pids[@]}"; do
      if _same_live_process "$_smoke_pid" "${_smoke_backend_start_times[$_smoke_pid]}"; then
        kill -KILL "$_smoke_pid" 2>/dev/null || true
      fi
    done
    die "Xvfb AppImage smoke leaked LamCore PID(s): ${_smoke_survivor_pids[*]}"
  fi

  # A timeout means the GUI stayed alive, which is the expected smoke result.
  if [[ "$_xvfb_rc" == 124 || "$_xvfb_rc" == 137 ]]; then
    info "Xvfb AppImage smoke completed with no LamCore survivor (exit $_xvfb_rc)"
  else
    printf '%s\n' '--- AppImage smoke log (last 100 lines) ---' >&2
    tail -n 100 "$_xvfb_home/appimage.log" >&2 || true
    die "Xvfb AppImage smoke failed (exit $_xvfb_rc)"
  fi
else
  info "Skipping Xvfb smoke (set up xvfb-run to enable it)"
fi

info "Copying Linux artifacts back to the repository checkout"
FINAL_SIDECAR="$ROOT/artifacts/linux-x64/sidecar/LamCore"
FINAL_APPIMAGE="$ROOT/core/desktop/src-tauri/target/release/bundle/appimage/$(basename "$APPIMAGE")"
FINAL_DEB="$ROOT/core/desktop/src-tauri/target/release/bundle/deb/$(basename "$DEB")"

# These are exact generated output locations, not user-selected directories.
# Keep the destructive operations narrow so a Linux build cannot erase an
# unrelated workspace path or the existing Windows sidecar.
remove_exact_repo_dir "$FINAL_SIDECAR" "$ROOT/artifacts/linux-x64/sidecar/LamCore"
mkdir -p "$(dirname "$FINAL_SIDECAR")"
cp -a "$SIDECAR" "$FINAL_SIDECAR"
mkdir -p "$(dirname "$FINAL_APPIMAGE")" "$(dirname "$FINAL_DEB")"
rm -f -- "$FINAL_APPIMAGE" "$FINAL_DEB"
cp -a "$APPIMAGE" "$FINAL_APPIMAGE"
cp -a "$DEB" "$FINAL_DEB"

printf '\nArtifacts:\n'
for _artifact in "$FINAL_SIDECAR" "$FINAL_APPIMAGE" "$FINAL_DEB"; do
  printf '  %s  %s bytes  ' "$_artifact" "$(stat -c '%s' "$_artifact")"
  sha256sum "$_artifact" | cut -d' ' -f1
done
