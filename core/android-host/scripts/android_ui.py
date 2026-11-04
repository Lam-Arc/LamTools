#!/usr/bin/env python3
"""Drive the app by its own accessibility tree, not by guessed coordinates.

Guessing pixel positions from a screenshot was the single biggest waste of the previous
rounds: every estimate was off by the screenshot's display scale, and a tap that lands
on the wrong widget looks exactly like a broken feature.

`uiautomator dump` reports every clickable node with its label and exact bounds, so the
whole flow can be driven by text. A webview exposes its DOM through the same tree once
accessibility is active, which means this works for the real UI rather than only for
native widgets.

Commands
    dump                 print every labelled node and its bounds
    tap TEXT             tap the first clickable node whose text contains TEXT
    tap-exact TEXT       tap only on an exact match
    type TEXT            type into whatever has focus
    clear                clear the focused field
    wait TEXT [--timeout] block until a node with TEXT exists
    gone TEXT [--timeout] block until it disappears
    text                 print the visible text of every labelled node, in order
    composer             print what the message box currently holds

Exit codes: 0 ok, 3 the node was not found or did not appear in time, 4 the command failed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_NOT_FOUND = 3
EXIT_FAILED = 4

NODE = re.compile(r'text="((?:[^"\\]|\\.)*)"[^>]*?class="([^"]*)"[^>]*?clickable="(\w+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


@dataclass
class Element:
    text: str
    kind: str
    clickable: bool
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    def __str__(self) -> str:
        box = f"[{self.left},{self.top}][{self.right},{self.bottom}]"
        flag = "*" if self.clickable else " "
        return f"{flag} {self.text!r} <{self.kind.split('.')[-1]}> {box}"


class Ui:
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

    def run(self, args: list[str], timeout: int = 90) -> tuple[int, str]:
        env = dict(os.environ)
        # Git Bash rewrites /sdcard/... into C:/Program Files/Git/... without this.
        env["MSYS_NO_PATHCONV"] = "1"
        try:
            done = subprocess.run(
                [self.adb] + args, capture_output=True, text=True, timeout=timeout, env=env
            )
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout}s"
        return done.returncode, done.stdout + done.stderr

    def shell(self, command: str, timeout: int = 90) -> tuple[int, str]:
        return self.run(["shell", command], timeout)

    def elements(self) -> list[Element]:
        """The live accessibility tree.

        `uiautomator dump` prints "ERROR: could not get idle state" and leaves the
        previous file untouched whenever a webview keeps animating. Reading that stale
        file silently yields last-layout coordinates, so every tap lands where the widget
        used to be and the feature looks broken. Delete first, require the success line,
        and retry a few times before giving up loudly.
        """
        xml = ""
        for attempt in range(4):
            self.shell("rm -f /sdcard/sunday-ui.xml")
            code, output = self.shell("uiautomator dump /sdcard/sunday-ui.xml")
            if code == 0 and "dumped to" in output:
                code, xml = self.shell("cat /sdcard/sunday-ui.xml")
                if code == 0 and "<hierarchy" in xml:
                    break
            xml = ""
            time.sleep(0.6 * (attempt + 1))
        if not xml:
            return []
        found = []
        for match in NODE.finditer(xml):
            text, kind, clickable, left, top, right, bottom = match.groups()
            text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            text = text.replace("&#10;", " ").strip()
            found.append(
                Element(
                    text=text,
                    kind=kind,
                    clickable=clickable == "true",
                    left=int(left),
                    top=int(top),
                    right=int(right),
                    bottom=int(bottom),
                )
            )
        return found

    def find(
        self,
        needle: str,
        exact: bool = False,
        clickable: bool = True,
        min_x: int | None = None,
        max_x: int | None = None,
        index: int = 0,
    ) -> Element | None:
        """The Nth matching node.

        The same label often appears twice: the sidebar and the empty state both offer
        "新建项目". Position filters and an index are what make that unambiguous.
        """
        matches = []
        for element in self.elements():
            if clickable and not element.clickable:
                continue
            if not element.text:
                continue
            if not ((element.text == needle) if exact else (needle in element.text)):
                continue
            center_x = (element.left + element.right) // 2
            if min_x is not None and center_x < min_x:
                continue
            if max_x is not None and center_x > max_x:
                continue
            matches.append(element)
        if not matches:
            return None
        return matches[index] if index < len(matches) else None

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {x} {y}")

    def wait_for(self, needle: str, timeout: float, exact: bool = False, clickable: bool = True) -> Element | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.find(needle, exact=exact, clickable=clickable)
            if found is not None:
                return found
            time.sleep(1)
        return None

    def wait_gone(self, needle: str, timeout: float, exact: bool = False) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.find(needle, exact=exact, clickable=False) is None:
                return True
            time.sleep(1)
        return False

    def fill(self, needle: str, value: str, timeout: float = 10) -> bool:
        """Clears a text field and types into it, checking that it took.

        A blind clear followed by typing leaves the old text in place when the delete
        keys land before focus, and the field then reads as a mangled path that looks
        like a core bug. Verifying the field is empty first is cheaper than debugging
        that twice.
        """
        field = self.find(needle, clickable=True)
        if field is None:
            return False
        x, y = field.center
        for _ in range(3):
            self.tap(x, y)
            time.sleep(0.5)
            self.clear_field()
            time.sleep(0.5)
            current = self.find(needle, clickable=True)
            if current is not None and self.field_text() in ("", needle):
                self.type_text(value)
                time.sleep(0.5)
                return True
        self.type_text(value)
        return False

    def type_text(self, text: str) -> int:
        # `input text` treats spaces as %s and cannot send some punctuation directly.
        escaped = text.replace("%", "\\%").replace(" ", "%s")
        code, output = self.shell(f"input text '{escaped}'")
        return code

    def clear_field(self) -> None:
        """Erase the focused field without one adb round trip per character.

        `input keyevent` accepts a whole list of key codes, so 160 deletions go out in
        two calls. The previous one-call-per-character version spent ten seconds per
        attempt and still left long prompts half-written, which reads as "typing is
        broken" rather than "the helper is slow".
        """
        self.shell("input keyevent KEYCODE_MOVE_END")
        for _ in range(2):
            codes = " ".join(["KEYCODE_DEL"] * 80)
            self.shell(f"input keyevent {codes}")

    def field_text(self) -> str:
        """The composer's current text, as the user sees it.

        A webview textarea reaches the accessibility tree as an empty EditText while the
        real value lives in an overlapping TextView, so reading EditText.text always
        reports empty even when the box is full. Every text node inside the field's
        bounds is the only honest answer to "what is typed right now".
        """
        elements = self.elements()
        fields = [element for element in elements if element.kind.endswith("EditText")]
        if not fields:
            return ""
        # The sidebar search box is also an EditText and comes first in tree order, so
        # "the composer" has to be the largest field rather than the first one.
        element = max(fields, key=lambda field: (field.right - field.left) * (field.bottom - field.top))
        if True:
            for other in elements:
                if other is element or not other.text or other.kind.endswith("EditText"):
                    continue
                if (
                    other.left >= element.left
                    and other.top >= element.top
                    and other.right <= element.right + 4
                    and other.bottom <= element.bottom + 4
                ):
                    return other.text
            return ""
        return ""

    def screenshot(self, path: Path) -> None:
        env = dict(os.environ)
        env["MSYS_NO_PATHCONV"] = "1"
        with open(path, "wb") as handle:
            subprocess.run([self.adb, "exec-out", "screencap", "-p"], stdout=handle, env=env)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["dump", "tap", "tap-exact", "type", "clear", "wait", "gone", "text", "shot", "edit", "fill", "composer"])
    parser.add_argument("argument", nargs="?", default="")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--min-x", type=int, default=None)
    parser.add_argument("--max-x", type=int, default=None)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--shot", default="", help="capture a screenshot after the action")
    args = parser.parse_args(argv)

    ui = Ui()

    if args.command == "dump":
        for element in ui.elements():
            print(element)
        return EXIT_OK

    if args.command == "composer":
        print(ui.field_text())
        return EXIT_OK

    if args.command == "text":
        for element in ui.elements():
            if element.text:
                print(element.text)
        return EXIT_OK

    if args.command in ("tap", "tap-exact"):
        element = ui.find(
            args.argument,
            exact=args.command == "tap-exact",
            min_x=args.min_x,
            max_x=args.max_x,
            index=args.index,
        )
        if element is None:
            print(f"no node matching {args.argument!r}", file=sys.stderr)
            return EXIT_NOT_FOUND
        x, y = element.center
        print(f"tap {element.text!r} at {x},{y}")
        ui.tap(x, y)
        if args.shot:
            time.sleep(2)
            ui.screenshot(Path(args.shot))
        return EXIT_OK

    if args.command in ("edit", "fill"):
        # The nth EditText on screen, since the fields have no accessible label.
        fields = [element for element in ui.elements() if element.kind.endswith("EditText")]
        index = args.index
        if index >= len(fields):
            print(f"only {len(fields)} text fields on screen", file=sys.stderr)
            return EXIT_NOT_FOUND
        field = fields[index]
        x, y = field.center
        if args.command == "edit":
            ui.tap(x, y)
            time.sleep(0.5)
            ui.clear_field()
            ui.type_text(args.argument)
            return EXIT_OK
        # `fill`: clear until the field reads empty, then type and read it back.
        for attempt in range(3):
            ui.tap(x, y)
            time.sleep(0.5)
            ui.clear_field()
            time.sleep(0.5)
            remaining = ui.field_text()
            if remaining in ("", args.argument):
                ui.type_text(args.argument)
                time.sleep(0.5)
                print(f"typed: {ui.field_text()!r}")
                return EXIT_OK
            print(f"attempt {attempt + 1}: field still holds {remaining!r}", file=sys.stderr)
        print(f"field {index} would not clear after 3 attempts", file=sys.stderr)
        return EXIT_FAILED

    if args.command == "type":
        code = ui.type_text(args.argument)
        return EXIT_OK if code == 0 else EXIT_FAILED

    if args.command == "clear":
        ui.clear_field()
        return EXIT_OK

    if args.command == "wait":
        element = ui.wait_for(args.argument, args.timeout)
        if element is None:
            print(f"{args.argument!r} did not appear within {args.timeout}s", file=sys.stderr)
            return EXIT_NOT_FOUND
        print(f"found {element.text!r} at {element.center}")
        return EXIT_OK

    if args.command == "gone":
        if not ui.wait_gone(args.argument, args.timeout):
            print(f"{args.argument!r} was still present after {args.timeout}s", file=sys.stderr)
            return EXIT_NOT_FOUND
        return EXIT_OK

    if args.command == "shot":
        ui.screenshot(Path(args.argument))
        return EXIT_OK

    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
