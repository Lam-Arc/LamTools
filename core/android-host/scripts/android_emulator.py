#!/usr/bin/env python3
"""Create, start and drive the Android emulators this project uses.

Every emulator step during the previous rounds was retyped by hand, and each retype
was a chance to get `MSYS_NO_PATHCONV`, the SDK path or the boot wait wrong. This is
that knowledge written down once.

Commands
    create NAME [--tablet|--phone]   write an AVD config if it does not exist
    start  NAME [--headless]         boot it and wait for `sys.boot_completed`
    wait   [--timeout S]             wait for the boot property
    stop   NAME                      stop it
    install APK                      install and report the package version
    sh     'command'                 run a shell command with path conversion off
    state                            device model, size, density, boot state

Exit codes: 0 ok, 2 environment problem, 3 device not ready, 4 the operation failed.

The `--tablet` profile exists because the phone AVD at 1080x1920 is below the size
where multi-window is comfortable, and the earlier split-screen attempt failed on an
AVD that was 320x480 by default. A tablet profile is a precondition for testing
multi-window at all, not a preference.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_ENV = 2
EXIT_NOT_READY = 3
EXIT_FAILED = 4

PACKAGE = "com.lamtools.sunday.core"
AVD_HOME = Path.home() / ".android" / "avd"

PROFILES = {
    # A phone for the normal lifecycle runs.
    "phone": {
        "width": 1080,
        "height": 1920,
        "density": 420,
        "ram": 2048,
    },
    # A tablet: wide enough that split screen has two usable halves, which is what
    # multi-window testing needs to mean anything.
    "tablet": {
        "width": 2560,
        "height": 1600,
        "density": 240,
        "ram": 4096,
    },
}

BASE_CONFIG = [
    ("AvdId", "{name}"),
    ("avd.ini.displayname", "{name}"),
    ("avd.ini.encoding", "UTF-8"),
    ("abi.type", "x86_64"),
    ("hw.cpu.arch", "x86_64"),
    ("image.sysdir.1", "system-images/android-36/google_apis/x86_64/"),
    ("tag.id", "google_apis"),
    ("tag.display", "Google APIs"),
    ("hw.ramSize", "{ram}"),
    ("hw.lcd.density", "{density}"),
    ("hw.lcd.width", "{width}"),
    ("hw.lcd.height", "{height}"),
    ("skin.name", "{width}x{height}"),
    ("skin.path", "_no_skin"),
    ("disk.dataPartition.size", "6442450944"),
    ("hw.gpu.enabled", "no"),
    ("hw.gpu.mode", "swiftshader_indirect"),
    ("hw.keyboard", "yes"),
    # Multi-window needs a device that reports itself as capable.
    ("hw.multiWindowSupport", "true"),
]


def say(message: str) -> None:
    print(f"[emu] {message}", flush=True)


def fail(code: int, message: str) -> int:
    print(f"[emu] {message}", file=sys.stderr, flush=True)
    return code


def sdk() -> Path | None:
    for candidate in (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        r"E:\Environment\AndroidSDK",
        str(Path.home() / "Android/Sdk"),
        "/usr/local/lib/android/sdk",
    ):
        if candidate and (Path(candidate) / "platform-tools").exists():
            return Path(candidate)
    return None


def adb() -> str:
    root = sdk()
    if root is None:
        raise SystemExit(fail(EXIT_ENV, "no Android SDK: set ANDROID_HOME"))
    name = "adb.exe" if os.name == "nt" else "adb"
    return str(root / "platform-tools" / name)


def emulator_bin() -> str:
    root = sdk()
    if root is None:
        raise SystemExit(fail(EXIT_ENV, "no Android SDK: set ANDROID_HOME"))
    name = "emulator.exe" if os.name == "nt" else "emulator"
    return str(root / "emulator" / name)


def run(command: list[str], timeout: int = 120) -> tuple[int, str]:
    """Run a command with a hard timeout.

    `MSYS_NO_PATHCONV` is set because Git Bash otherwise rewrites `/data/...`
    arguments into `C:/Program Files/Git/...`, which has silently broken more device
    commands in this project than any other single cause.
    """
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(command)}"
    return completed.returncode, completed.stdout + completed.stderr


def shell(command: str, timeout: int = 60) -> tuple[int, str]:
    return run([adb(), "shell", command], timeout)


def create(name: str, profile: str) -> int:
    config = AVD_HOME / f"{name}.avd" / "config.ini"
    if config.exists():
        say(f"{name} already exists at {config}")
        return EXIT_OK
    spec = PROFILES[profile]
    config.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key} = {value.format(name=name, **spec)}" for key, value in BASE_CONFIG]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (AVD_HOME / f"{name}.ini").write_text(
        f"avd.ini.encoding=UTF-8\npath={config.parent}\ntarget=android-36\n",
        encoding="utf-8",
    )
    say(f"created {name} from the {profile} profile: {spec['width']}x{spec['height']} @ {spec['density']}dpi")
    return EXIT_OK


def booted() -> bool:
    code, output = shell("getprop sys.boot_completed")
    return code == 0 and output.strip() == "1"


def wait_for_boot(timeout: int) -> int:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if booted():
            say(f"booted after {time.monotonic() - started:.0f}s")
            return EXIT_OK
        time.sleep(3)
    return fail(EXIT_NOT_READY, f"the device did not finish booting within {timeout}s")


def start(name: str, headless: bool, timeout: int) -> int:
    code, output = run([adb(), "devices"])
    if PACKAGE and "emulator-" in output and code == 0:
        say("an emulator is already attached")
        attached = booted()
        if attached:
            return EXIT_OK

    command = [
        emulator_bin(),
        "-avd",
        name,
        "-no-snapshot-save",
        "-no-boot-anim",
        "-gpu",
        "swiftshader_indirect",
        "-netdelay",
        "none",
        "-netspeed",
        "full",
    ]
    if headless:
        command.append("-no-window")
    # Detached on purpose: the caller waits on the boot property, not on the process.
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    say(f"started {name}, waiting for boot")
    return wait_for_boot(timeout)


def stop(name: str) -> int:
    code, output = run([adb(), "emu", "kill"])
    say(output.strip() or "stop requested")
    return EXIT_OK if code == 0 else EXIT_FAILED


def install(apk: Path) -> int:
    if not apk.exists():
        return fail(EXIT_FAILED, f"{apk} does not exist")
    code, output = run([adb(), "install", "-r", "-t", str(apk)], timeout=600)
    if code != 0:
        return fail(EXIT_FAILED, output.strip()[-800:])
    return EXIT_OK


def state() -> int:
    for command in ("wm size", "wm density", "getprop ro.build.version.sdk", "getprop sys.boot_completed"):
        code, output = shell(command)
        say(f"{command}: {output.strip() if code == 0 else 'failed'}")
    return EXIT_OK


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("name")
    create_parser.add_argument("--tablet", action="store_true")
    create_parser.add_argument("--phone", action="store_true")

    start_parser = sub.add_parser("start")
    start_parser.add_argument("name")
    start_parser.add_argument("--headless", action="store_true")
    start_parser.add_argument("--timeout", type=int, default=300)

    wait_parser = sub.add_parser("wait")
    wait_parser.add_argument("--timeout", type=int, default=300)

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("name", nargs="?", default="")

    install_parser = sub.add_parser("install")
    install_parser.add_argument("apk")

    sh_parser = sub.add_parser("sh")
    # Not `command`: a subparser positional with that name overwrites the subcommand
    # itself, and every `sh` invocation then fails as "unknown command".
    sh_parser.add_argument("words", nargs=argparse.REMAINDER)

    sub.add_parser("state")

    args = parser.parse_args(argv)

    if args.command == "create":
        profile = "tablet" if args.tablet else "phone"
        return create(args.name, profile)
    if args.command == "start":
        return start(args.name, args.headless, args.timeout)
    if args.command == "wait":
        return wait_for_boot(args.timeout)
    if args.command == "stop":
        return stop(args.name)
    if args.command == "install":
        return install(Path(args.apk))
    if args.command == "sh":
        code, output = shell(" ".join(args.words))
        print(output, end="")
        return EXIT_OK if code == 0 else EXIT_FAILED
    if args.command == "state":
        return state()
    return fail(EXIT_ENV, "unknown command")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
