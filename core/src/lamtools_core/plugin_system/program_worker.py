"""user:“给我把 2 阶段做完，前端除外”+(程序在独立受管Python进程执行，结果走有限JSON；不是隔离沙箱)。"""
import asyncio
import base64
import inspect
import json
import sys


def main():
    source = base64.b64decode(sys.argv[1]).decode("utf8")
    value = json.loads(base64.b64decode(sys.argv[2]).decode("utf8"))
    marker = sys.argv[3]
    try:
        namespace = {"__name__": "__sunday_program__"}
        exec(compile(source, "<sunday-plugin-program>", "exec"), namespace)
        entry = namespace.get("main")
        if not callable(entry):
            raise ValueError("Program must define main(input)")
        result = entry(value)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        encoded = json.dumps({"status": "completed", "value": result}, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf8")) > 32768:
            raise ValueError("Program result exceeds 32 KiB")
    except BaseException as error:
        encoded = json.dumps({"status": "failed", "error": {"type": type(error).__name__, "message": str(error)[:2000]}}, ensure_ascii=False)
    print("\n" + marker + encoded, flush=True)


if __name__ == "__main__":
    main()
