#!/usr/bin/env bash
# Writes the model config where the guest core reads it, then restarts the app.
#
# The first-run screen is the real path for a user; this script exists so the acceptance
# run does not depend on tap coordinates inside a WebView, which uiautomator cannot see.
# What it proves is the part that matters: the core picks up this configuration and can
# run a real turn with it.
set -euo pipefail
ADB="adb -s ${DEVICE:-emulator-5554}"
PKG=com.lamtools.sunday.core
SOURCE_CONFIG="${1:?usage: seed-model.sh <dir with providers/*.jsonc>}"

say() { printf '\n\033[1;34m[seed]\033[0m %s\n' "$*"; }

PROVIDER=$(ls "$SOURCE_CONFIG"/providers/*.jsonc | head -1)
say "reading provider from $PROVIDER"

python - "$PROVIDER" /tmp/sunday-provider.json /tmp/sunday-model.json <<'PY'
import json, re, sys, pathlib

provider_path, provider_out, model_out = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(provider_path).read_text(encoding="utf-8")
text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
raw = json.loads(text)

provider = {
    "id": "android-endpoint",
    "name": "Android endpoint",
    "api_type": raw.get("api_type", "openai"),
    "base_url": raw["base_url"],
    "api_key": raw["api_key"],
    "is_default": True,
    "notes": "",
    "adapter_profile_id": raw.get("adapter_profile_id", "openai-chat"),
}
model = {
    "id": "android-endpoint-deepseek",
    "model_id": "deepseek-v4.1-flash",
    "display_name": "DeepSeek V4.1 Flash",
    "provider": "Android endpoint",
    "context_window": 1000000,
    "max_output_tokens": 131072,
    "temperature": 0.7,
    "thinking": {"supported": True, "budget": 10000},
    "adapter_profile_id": "deepseek-chat",
    "capability": "multimodal",
    "notes": "",
    "is_default": True,
    "provider_id": "android-endpoint",
}
pathlib.Path(provider_out).write_text(json.dumps(provider, indent=2), encoding="utf-8")
pathlib.Path(model_out).write_text(json.dumps(model, indent=2), encoding="utf-8")
print("wrote", provider_out, model_out)
PY

$ADB push /tmp/sunday-provider.json /data/local/tmp/sunday-provider.json >/dev/null
$ADB push /tmp/sunday-model.json /data/local/tmp/sunday-model.json >/dev/null

say "placing the config inside the guest rootfs"
$ADB shell "run-as $PKG sh -c '
  CFG=files/runtime/rootfs/root/.sunday/core/config
  mkdir -p \$CFG/providers \$CFG/models
  rm -f \$CFG/providers/*.jsonc \$CFG/models/*.jsonc
  cp /data/local/tmp/sunday-provider.json \$CFG/providers/android-endpoint.jsonc
  cp /data/local/tmp/sunday-model.json \$CFG/models/android-endpoint.jsonc
  ls -la \$CFG/providers \$CFG/models
'"

say "restarting the app"
$ADB shell am force-stop $PKG
$ADB logcat -c
$ADB shell am start -n "$PKG/.MainActivity" >/dev/null
echo "started; watch the guest at /data/user/0/$PKG/files/runtime/guest.log"
