#!/usr/bin/env bash
# Arrange CLI full lifecycle test
# Usage: bash scripts/test-arrange-cli.sh [--base-url http://127.0.0.1:5172]
set -euo pipefail

BASE_URL="${LAMTOOLS_CORE_API_URL:-http://127.0.0.1:5172}"
WS_PATH="/api/core/app-server"
CLI="python -m lamtools_core.cli"
PASS=0
FAIL=0

red() { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }

check() {
    local desc="$1" cmd="$2" expect="$3"
    echo -n "  $desc ... "
    local output
    output=$(eval "$cmd" 2>&1) || true
    if echo "$output" | grep -q "$expect"; then
        green "PASS"
        PASS=$((PASS + 1))
        echo "$output" | head -3
    else
        red "FAIL"
        echo "  expected: $expect"
        echo "  got:"
        echo "$output" | head -5
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Arrange CLI Test ==="
echo "Base URL: $BASE_URL"
echo ""

# ---- A1: Create one-time job ----
check "A1 create once" \
    "$CLI arrange new --project-id test-proj --base-url $BASE_URL --ws-path $WS_PATH 'CLI一次性测试' --trigger-once 2099-12-31T08:00 --timezone Asia/Shanghai" \
    "\[arrange\]"

# Capture job ID from A1
JOB1_ID=$($CLI arrange new --project-id test-proj --base-url $BASE_URL --ws-path $WS_PATH 'CLI一次性测试2' --trigger-once 2099-12-31T08:00 2>/dev/null | grep '^\[' | sed 's/\[arrange\] //')
echo "  Job1 ID: $JOB1_ID"

# ---- A2: Create daily job ----
check "A2 create daily" \
    "$CLI arrange new --project-id test-proj --base-url $BASE_URL --ws-path $WS_PATH '每日报告' --trigger-daily 09:00 --title 'CLI日报'" \
    "\[arrange\]"

JOB2_ID=$($CLI arrange new --project-id test-proj --base-url $BASE_URL --ws-path $WS_PATH '每日报告2' --trigger-daily 09:00 --title 'CLI日报2' 2>/dev/null | grep '^\[' | sed 's/\[arrange\] //')
echo "  Job2 ID: $JOB2_ID"

# ---- A3: List all ----
check "A3 list all" \
    "$CLI arrange ls --base-url $BASE_URL --ws-path $WS_PATH" \
    "CLI"

# ---- A4: List by project ----
check "A4 list by project" \
    "$CLI arrange ls --project-id test-proj --base-url $BASE_URL --ws-path $WS_PATH" \
    "CLI"

# ---- A5: Describe ----
check "A5 describe" \
    "$CLI arrange describe $JOB1_ID --base-url $BASE_URL --ws-path $WS_PATH" \
    "once" || check "A5 describe" \
    "$CLI arrange describe $JOB2_ID --base-url $BASE_URL --ws-path $WS_PATH" \
    "daily"

# ---- A6: Pause ----
check "A6 pause" \
    "$CLI arrange set $JOB2_ID --status paused --base-url $BASE_URL --ws-path $WS_PATH" \
    "paused"

# ---- A7: Resume ----
check "A7 resume" \
    "$CLI arrange set $JOB2_ID --status scheduled --base-url $BASE_URL --ws-path $WS_PATH" \
    "scheduled"

# ---- A8: Edit title ----
check "A8 edit title" \
    "$CLI arrange edit $JOB2_ID --title 'CLI新标题' --base-url $BASE_URL --ws-path $WS_PATH" \
    "updated"

# ---- A9: Edit trigger ----
check "A9 edit trigger" \
    "$CLI arrange edit $JOB2_ID --trigger-daily 18:00 --base-url $BASE_URL --ws-path $WS_PATH" \
    "updated"

# ---- A10: Cancel ----
check "A10 cancel" \
    "$CLI arrange set $JOB1_ID --status cancelled --base-url $BASE_URL --ws-path $WS_PATH" \
    "cancelled"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit $FAIL
