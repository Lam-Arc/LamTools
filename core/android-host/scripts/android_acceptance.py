#!/usr/bin/env python3
"""Device acceptance for multi-window, lifecycle and single-instance behaviour.

Every step here is a command an engineer could type by hand; the script exists so the
sequence is the same each time and the result is a table instead of a memory of what
looked right on a screenshot.

The multi-window entry point is the platform's own: freeform support is a documented
developer option, and `am start --windowingMode 5` is the documented way to ask for it.
`--windowingMode 3|4` (split screen) is ignored for a task that already exists on this
build, which is why the earlier phone run could not enter split screen at all. That is
recorded as a limitation with the exact command that failed, not worked around with
guessed coordinates.

Checks are reported as pass, fail or unsupported-with-a-reason. A check that cannot be
run is never reported as a pass.

Exit codes: 0 all supported checks passed, 4 a supported check failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "com.lamtools.sunday.core"
ACTIVITY = f"{PACKAGE}/.MainActivity"
DATA_DIR = f"/data/user/0/{PACKAGE}"
REPORTS = f"{DATA_DIR}/lifecycle.reports.log"

EXIT_OK = 0
EXIT_FAILED = 4


@dataclass
class Check:
    name: str
    status: str = "pending"
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


class Device:
    def __init__(self) -> None:
        root = None
        for candidate in (
            os.environ.get("ANDROID_HOME"),
            os.environ.get("ANDROID_SDK_ROOT"),
            r"E:\Environment\AndroidSDK",
            str(Path.home() / "Android/Sdk"),
        ):
            if candidate and (Path(candidate) / "platform-tools").exists():
                root = Path(candidate)
                break
        if root is None:
            raise SystemExit("no Android SDK: set ANDROID_HOME")
        name = "adb.exe" if os.name == "nt" else "adb"
        self.adb = str(root / "platform-tools" / name)

    def run(self, args: list[str], timeout: int = 120) -> tuple[int, str]:
        env = dict(os.environ)
        # Git Bash rewrites /data/... into C:/Program Files/Git/... without this.
        env["MSYS_NO_PATHCONV"] = "1"
        try:
            done = subprocess.run(
                [self.adb] + args, capture_output=True, text=True, timeout=timeout, env=env
            )
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout}s"
        return done.returncode, done.stdout + done.stderr

    def shell(self, command: str, timeout: int = 120) -> tuple[int, str]:
        return self.run(["shell", command], timeout)

    def out(self, command: str, timeout: int = 120) -> str:
        code, output = self.shell(command, timeout)
        return output.strip() if code == 0 else ""

    def reports(self) -> list[dict]:
        code, output = self.run(["shell", "run-as", PACKAGE, "cat", REPORTS])
        if code != 0:
            return []
        entries = []
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def display_size(self) -> tuple[int, int] | None:
        """The size the app actually sees: the override when one is set.

        `wm size` prints `Physical size:` and `Override size:` on separate lines. Only
        reading the first makes a successful resize look like it was ignored.
        """
        output = self.out("wm size")
        override = re.search(r"Override size: (\d+)x(\d+)", output)
        if override:
            return int(override.group(1)), int(override.group(2))
        physical = re.search(r"Physical size: (\d+)x(\d+)", output)
        if physical:
            return int(physical.group(1)), int(physical.group(2))
        return None

    def windowing_mode(self) -> str:
        output = self.out("dumpsys activity activities")
        # The focused activity's configuration is the one that matters.
        for line in output.splitlines():
            if "mWindowingMode=" in line and "mActivityType=standard" in line:
                match = re.search(r"mWindowingMode=(\w+)", line)
                if match:
                    return match.group(1)
        match = re.search(r"mWindowingMode=(\w+)", output)
        return match.group(1) if match else "unknown"

    def window_bounds(self) -> tuple[int, int] | None:
        output = self.out("dumpsys activity activities")
        for line in output.splitlines():
            if "mBounds=Rect(" in line and "mActivityType=standard" in line:
                match = re.search(
                    r"mBounds=Rect\((-?\d+), (-?\d+) - (-?\d+), (-?\d+)\)", line
                )
                if match:
                    left, top, right, bottom = (int(value) for value in match.groups())
                    return right - left, bottom - top
        return None

    def pids(self) -> list[int]:
        output = self.out(f"pidof {PACKAGE}")
        return [int(part) for part in output.split() if part.isdigit()]

    def core_ready_instances(self) -> list[str]:
        output = self.out("logcat -d -s RustStdoutStderr:I")
        return re.findall(r"sunday core ready over ipc.*instance (\w+)", output)


def wait_for(predicate, timeout: float, interval: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def start_fullscreen(device: Device) -> None:
    device.shell(f"am force-stop {PACKAGE}")
    device.shell(f"am start --windowingMode 1 -n {ACTIVITY}")
    wait_for(lambda: bool(device.pids()), 30)


def start_freeform(device: Device) -> None:
    device.shell(f"am force-stop {PACKAGE}")
    device.shell(f"am start --windowingMode 5 -n {ACTIVITY}")
    wait_for(lambda: device.windowing_mode() == "freeform", 30)
    # The startup resume is written on the Rust side a moment after the window appears.
    # Waiting for it keeps it out of the window of reports a check is about to compare.
    time.sleep(4)


# --------------------------------------------------------------------- checks


def check_multi_window_supported(device: Device, check: Check) -> None:
    answer = device.out("cmd activity supports-split-screen-multi-window").strip()
    check.evidence.append(f"cmd activity supports-split-screen-multi-window -> {answer}")
    if answer == "true":
        check.status = "pass"
        check.detail = "the platform reports multi-window support"
    else:
        check.status = "unsupported"
        check.detail = "this image reports no multi-window support"


def check_freeform_enter(device: Device, check: Check) -> None:
    size = device.display_size()
    start_freeform(device)
    mode = device.windowing_mode()
    bounds = device.window_bounds()
    check.evidence.append(f"am start --windowingMode 5 -> mWindowingMode={mode}, bounds={bounds}")
    if mode != "freeform":
        check.status = "unsupported"
        check.detail = f"the platform ignored the freeform request, mode is {mode}"
        return
    if size and bounds and (bounds[0] >= size[0] or bounds[1] >= size[1]):
        check.status = "fail"
        check.detail = f"freeform window {bounds} is not smaller than the display {size}"
        return
    check.status = "pass"
    check.detail = f"freeform window {bounds} inside display {size}"


def check_freeform_to_fullscreen(device: Device, check: Check) -> None:
    start_freeform(device)
    before = device.windowing_mode()
    device.shell(f"am force-stop {PACKAGE}")
    device.shell(f"am start --windowingMode 1 -n {ACTIVITY}")
    wait_for(lambda: device.windowing_mode() == "fullscreen", 30)
    after = device.windowing_mode()
    size = device.display_size()
    bounds = device.window_bounds()
    check.evidence.append(f"{before} -> {after}, bounds={bounds}, display={size}")
    if after != "fullscreen":
        check.status = "fail"
        check.detail = f"could not return to fullscreen, mode is {after}"
        return
    if size and bounds and bounds != size:
        check.status = "fail"
        check.detail = f"fullscreen window is {bounds}, display is {size}"
        return
    check.status = "pass"
    check.detail = "mode switching keeps the window sized to the display"


def check_display_resize(device: Device, check: Check) -> None:
    original = device.display_size()
    if original is None:
        check.status = "unsupported"
        check.detail = "cannot read the display size"
        return
    try:
        target = (1600, 1000)
        device.shell(f"cmd window size {target[0]}x{target[1]}")
        time.sleep(4)
        pids = device.pids()
        resized = device.display_size()
        reports = device.reports()
        check.evidence.append(
            f"cmd window size {target[0]}x{target[1]} -> display={resized}, app pids={pids}"
        )
        if not pids:
            check.status = "fail"
            check.detail = "the app died when the display was resized"
            return
        if resized != target:
            check.status = "unsupported"
            check.detail = f"the emulator kept the display at {resized}"
            return
        if any(report.get("signal") == "stop" for report in reports[-2:]):
            check.evidence.append("note: a stop was reported during the resize")
        check.status = "pass"
        check.detail = f"display resized to {target[0]}x{target[1]}, the app stayed alive"
    finally:
        device.shell("cmd window size reset")
        time.sleep(3)


def check_launcher_backgrounds_freeform(device: Device, check: Check) -> None:
    """HOME removes a freeform window from the screen, so it is a real background.

    Verified by screenshot: after HOME the window is gone, while the task keeps its
    remembered bounds. That stale bounds value is exactly what made the first version
    of this check believe the app was still visible.
    """
    start_freeform(device)
    before = len(device.reports())
    device.shell("input keyevent KEYCODE_HOME")
    time.sleep(4)
    backgrounded = device.reports()[before:]
    device.shell(f"am start --windowingMode 5 -n {ACTIVITY}")
    time.sleep(5)
    returned = device.reports()[before:]
    signals = [report.get("signal") for report in backgrounded]
    all_signals = [report.get("signal") for report in returned]
    check.evidence.append(f"signals after HOME: {signals}")
    check.evidence.append(f"signals through the round trip: {all_signals}")
    if "stop" not in signals:
        check.status = "fail"
        check.detail = "HOME left a freeform app running with no stop recorded"
        return
    resumed = [report for report in returned if report.get("signal") == "resume"]
    if not resumed or resumed[-1].get("process") != "same":
        check.status = "fail"
        check.detail = "returning from HOME did not resume the same process"
        return
    check.status = "pass"
    check.detail = "HOME backgrounds a freeform app and returning resumes the same process"


def check_covered_by_another_app(device: Device, check: Check) -> None:
    """A fullscreen app on top is a real background transition."""
    start_freeform(device)
    before = len(device.reports())
    device.shell("am start --windowingMode 1 -n com.android.settings/.Settings")
    time.sleep(5)
    covered = device.reports()[before:]
    device.shell(f"am force-stop com.android.settings")
    device.shell(f"am start --windowingMode 5 -n {ACTIVITY}")
    time.sleep(6)
    after = device.reports()[before:]
    signals = [report.get("signal") for report in after]
    check.evidence.append(f"signals with Settings on top: {[r.get('signal') for r in covered]}")
    check.evidence.append(f"signals through the transition: {signals}")
    if "stop" not in [report.get("signal") for report in covered]:
        check.status = "fail"
        check.detail = "covering the app with a fullscreen one recorded no stop"
        return
    resumed = [report for report in after if report.get("signal") == "resume"]
    if not resumed:
        check.status = "fail"
        check.detail = "no resume was recorded on return"
        return
    last = resumed[-1]
    if last.get("process") != "same":
        check.status = "fail"
        check.detail = f"a live process was reported as {last.get('process')}"
        return
    if last.get("auto_resumed_turns") is not False:
        check.status = "fail"
        check.detail = "the resume report did not forbid automatic replay"
        return
    check.status = "pass"
    check.detail = "covered -> stop, return -> resume in the same process, nothing replayed"


def check_rotation_in_freeform(device: Device, check: Check) -> None:
    start_freeform(device)
    before = len(device.reports())
    device.shell("cmd window user-rotation lock 1")
    time.sleep(5)
    rotated = device.reports()[before:]
    device.shell("cmd window user-rotation lock 0")
    time.sleep(4)
    pids = device.pids()
    signals = [report.get("signal") for report in rotated]
    check.evidence.append(f"signals during rotation: {signals}, app pids after: {pids}")
    if not pids:
        check.status = "fail"
        check.detail = "the app died on rotation"
        return
    if "stop" in signals:
        check.status = "fail"
        check.detail = "a rotation was reported as a background transition"
        return
    check.status = "pass"
    check.detail = "rotation produced no background transition"


def check_single_core(device: Device, check: Check) -> None:
    device.shell("logcat -c")
    start_fullscreen(device)
    time.sleep(6)
    device.shell("input keyevent KEYCODE_HOME")
    time.sleep(2)
    device.shell(f"am start -n {ACTIVITY}")
    time.sleep(6)
    # A second launch of an already-running app must reattach, not start a second core.
    device.shell(f"am start -n {ACTIVITY}")
    time.sleep(4)
    instances = device.core_ready_instances()
    pids = device.pids()
    check.evidence.append(f"'sunday core ready' lines: {len(instances)}, instances: {instances}")
    check.evidence.append(f"app pids: {pids}")
    if len(instances) > 1:
        check.status = "fail"
        check.detail = f"the core started {len(instances)} times in one process lifetime"
        return
    if len(pids) != 1:
        check.status = "fail"
        check.detail = f"expected one app process, saw {pids}"
        return
    check.status = "pass"
    check.detail = "one process, one core start across repeated launches"


def ime_shown(device: Device) -> bool:
    """Whether the input method is on screen.

    `mInputShown` is the window manager's own answer, so it covers a keyboard that was
    raised by the webview's text field rather than only by a native EditText.
    """
    state = device.out("dumpsys input_method")
    return "mInputShown=true" in state or "mIsInputViewShown=true" in state


def tap_fraction(device: Device, x: float, y: float) -> bool:
    size = device.display_size()
    if size is None:
        return False
    device.shell(f"input tap {int(size[0] * x)} {int(size[1] * y)}")
    return True


def open_settings(device: Device) -> bool:
    """Opens the settings overlay by tapping its entry point in the app window.

    The button is drawn by the webview, so it has no accessibility node to address. The
    position is derived from the window the app actually occupies rather than a constant:
    the same button sits at the right edge, vertically centred.
    """
    size = device.display_size()
    if size is None:
        return False
    width, height = size
    device.shell(f"input tap {int(width * 0.98)} {int(height * 0.5)}")
    time.sleep(3)
    return True


def check_keyboard_appears(device: Device, check: Check) -> None:
    """Focusing a text field must raise the input method.

    This is the half the app controls: the settings screen has inputs, and the webview
    asks for the keyboard when one is focused.
    """
    start_fullscreen(device)
    # First paint. Tapping before the webview has drawn lands on whatever happens to be
    # there, which is how an earlier version navigated somewhere else entirely.
    time.sleep(10)

    if not tap_fraction(device, 0.98, 0.5):
        check.status = "unsupported"
        check.detail = "could not read the display size to reach the settings screen"
        return
    time.sleep(4)

    # The endpoint field, then a couple of neighbours if the first tap misses. Retrying
    # the field rather than the entry point matters: a second tap on the entry point
    # would close the overlay again.
    shown = False
    for y in (0.148, 0.125, 0.175):
        if not tap_fraction(device, 0.5, y):
            break
        time.sleep(3)
        if ime_shown(device):
            shown = True
            break
    check.evidence.append(f"input method after focusing a field: {shown}")
    check.evidence.append(f"app pids: {device.pids()}")

    if not device.pids():
        check.status = "fail"
        check.detail = "the app died when a text field was focused"
        return
    if not shown:
        check.status = "fail"
        check.detail = "focusing a text field raised no keyboard"
        return

    # Leave the screen through its own button so the next check starts clean.
    for y in (0.5, 0.28, 0.35, 0.2, 0.42):
        tap_fraction(device, 0.98, y)
        time.sleep(2)
        if not ime_shown(device):
            check.evidence.append(f"left the screen with the button at {int(y * 100)}%")
            break

    check.status = "pass"
    check.detail = "focusing a text field raised the keyboard and the app stayed alive"


def check_keyboard_dismissal(device: Device, check: Check) -> None:
    """Not asserted, with the attempts recorded.

    A user closes the keyboard by tapping away or by pressing back. On this image neither
    is observable from adb: `mInputShown` stays true after the field loses focus, `adb
    shell ime` offers no hide, and BACK finishes the activity. Closing the settings
    overlay did clear it once by hand, which is not reproducible enough to assert.
    """
    state = device.out("dumpsys input_method")
    check.evidence.append("dumpsys input_method reports mInputShown=" + str(ime_shown(device)))
    check.evidence.append("the app's own back button cleared it once by hand, not reliably")
    check.evidence.append("`adb shell ime` has no hide subcommand; BACK finishes the activity")
    check.status = "unsupported"
    check.detail = (
        "keyboard dismissal is the platform IME's behaviour and is not observable from "
        "adb on this image; keep it for real-device acceptance"
    )
    _ = state


CHECKS = [
    ("multi-window supported", check_multi_window_supported),
    ("freeform entry", check_freeform_enter),
    ("freeform to fullscreen", check_freeform_to_fullscreen),
    ("display resize", check_display_resize),
    ("launcher backgrounds the freeform window", check_launcher_backgrounds_freeform),
    ("covered by a fullscreen app", check_covered_by_another_app),
    ("rotation in freeform", check_rotation_in_freeform),
    ("single core instance", check_single_core),
    ("keyboard appears for a text field", check_keyboard_appears),
    ("keyboard dismissal", check_keyboard_dismissal),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="run checks whose name contains this")
    parser.add_argument("--report", default="", help="write the results as JSON here")
    args = parser.parse_args(argv)

    device = Device()
    if not device.pids() and not device.out("getprop sys.boot_completed"):
        print("the device is not ready", file=sys.stderr)
        return EXIT_FAILED

    results: list[Check] = []
    failures = 0
    for name, runner in CHECKS:
        if args.only and args.only not in name:
            continue
        check = Check(name=name)
        try:
            runner(device, check)
        except Exception as error:  # a broken check must not hide the others
            check.status = "fail"
            check.detail = f"the check itself raised: {error}"
        if check.status == "fail":
            failures += 1
        results.append(check)
        print(f"{check.status:>11}  {name}: {check.detail}")
        for line in check.evidence:
            print(f"             | {line}")

    print()
    counts = {}
    for check in results:
        counts[check.status] = counts.get(check.status, 0) + 1
    print("  ".join(f"{status}={count}" for status, count in sorted(counts.items())))

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                [
                    {
                        "name": check.name,
                        "status": check.status,
                        "detail": check.detail,
                        "evidence": check.evidence,
                    }
                    for check in results
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return EXIT_OK if failures == 0 else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
