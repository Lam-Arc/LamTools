"""创建期原子加入 Job Object（Windows）。

user:“研究 CreateProcessW + STARTUPINFOEXW + PROC_THREAD_ATTRIBUTE_JOB_LIST，
实现进程创建阶段原子加入 Job Object，消除 spawn 后再登记的竞态窗口”
+(标准库 subprocess 的 lpAttributeList 只支持 handle_list，透不出 job 属性，
所以这里直接用 ctypes 走 CreateProcessW，把 job 放进线程属性列表里)。

为什么必须原子：先 spawn 再 AssignProcessToJobObject 之间有一个窗口，
宿主正好在这时被 /F 强杀，子进程就没进 job 也没人管，成了孤儿。
一旦创建时就带上 JOB_LIST，子进程从第一条指令起就在 job 里。

Job 句柄归属：句柄由本进程持有，且**不**给子进程继承（只把它放进 JOB_LIST），
所以 KILL_ON_JOB_CLOSE 会在宿主死亡、句柄关闭时真正生效；
上一轮"把宿主放进 job"失败正是因为子进程继承了句柄，句柄永不归零。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import sys

_logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------- 常量
PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00000200
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INSUFFICIENT_BUFFER = 122
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_ATTRIBUTE_NORMAL = 0x00000080
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
PIPE_BUFFER_SIZE = 1 << 20


if IS_WINDOWS:
    from ctypes import wintypes as wt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wt.DWORD),
            ("lpSecurityDescriptor", wt.LPVOID),
            ("bInheritHandle", wt.BOOL),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("lpReserved", wt.LPWSTR),
            ("lpDesktop", wt.LPWSTR),
            ("lpTitle", wt.LPWSTR),
            ("dwX", wt.DWORD),
            ("dwY", wt.DWORD),
            ("dwXSize", wt.DWORD),
            ("dwYSize", wt.DWORD),
            ("dwXCountChars", wt.DWORD),
            ("dwYCountChars", wt.DWORD),
            ("dwFillAttribute", wt.DWORD),
            ("dwFlags", wt.DWORD),
            ("wShowWindow", wt.WORD),
            ("cbReserved2", wt.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wt.HANDLE),
            ("hStdOutput", wt.HANDLE),
            ("hStdError", wt.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", wt.LPVOID),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wt.HANDLE),
            ("hThread", wt.HANDLE),
            ("dwProcessId", wt.DWORD),
            ("dwThreadId", wt.DWORD),
        ]

    _kernel32.CreateJobObjectW.restype = wt.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wt.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wt.HANDLE,
        ctypes.c_int,
        wt.LPVOID,
        wt.DWORD,
    ]
    _kernel32.CloseHandle.restype = wt.BOOL
    _kernel32.CloseHandle.argtypes = [wt.HANDLE]
    _kernel32.CreatePipe.restype = wt.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wt.HANDLE),
        ctypes.POINTER(wt.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wt.DWORD,
    ]
    _kernel32.SetHandleInformation.restype = wt.BOOL
    _kernel32.SetHandleInformation.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
    _kernel32.InitializeProcThreadAttributeList.restype = wt.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wt.LPVOID,
        wt.DWORD,
        wt.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wt.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wt.LPVOID,
        wt.DWORD,
        ctypes.c_size_t,
        wt.LPVOID,
        ctypes.c_size_t,
        wt.LPVOID,
        wt.LPVOID,
    ]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wt.LPVOID]
    _kernel32.CreateProcessW.restype = wt.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wt.LPCWSTR,
        wt.LPWSTR,
        wt.LPVOID,
        wt.LPVOID,
        wt.BOOL,
        wt.DWORD,
        wt.LPVOID,
        wt.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _kernel32.TerminateJobObject.restype = wt.BOOL
    _kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
    _kernel32.TerminateProcess.restype = wt.BOOL
    _kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    _kernel32.WaitForSingleObject.restype = wt.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    _kernel32.GetExitCodeProcess.restype = wt.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _kernel32.GetCurrentProcess.restype = wt.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.DuplicateHandle.restype = wt.BOOL
    _kernel32.DuplicateHandle.argtypes = [
        wt.HANDLE,
        wt.HANDLE,
        wt.HANDLE,
        ctypes.POINTER(wt.HANDLE),
        wt.DWORD,
        wt.BOOL,
        wt.DWORD,
    ]


def _handle_int(value: object) -> int:
    """ctypes 的 HANDLE 有两种形态：结构体字段读出来是 int，实例是 c_void_p。"""
    if isinstance(value, int):
        return value
    return int(getattr(value, "value", 0) or 0)


class NativeSpawnError(RuntimeError):
    pass


def create_kill_on_close_job() -> int | None:
    """新建一个 job：句柄关闭时杀掉其中所有进程。"""
    if not IS_WINDOWS:
        return None
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise NativeSpawnError(f"CreateJobObject failed: {ctypes.get_last_error()}")
    configured = False
    for size in (168, 144):
        buffer = ctypes.create_string_buffer(size)
        ctypes.memmove(
            ctypes.addressof(buffer) + 40,
            ctypes.byref(ctypes.c_uint(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)),
            4,
        )
        if _kernel32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, buffer, size
        ):
            configured = True
            break
    if not configured:
        _kernel32.CloseHandle(job)
        raise NativeSpawnError("SetInformationJobObject failed")
    return _handle_int(job)


class WinChild:
    """CreateProcessW 起出来的子进程，接口对齐 subprocess.Popen 的常用面。"""

    def __init__(
        self,
        *,
        process_handle: int,
        pid: int,
        job_handle: int,
        stdin: object | None,
        stdout: object | None,
        stderr: object | None,
    ) -> None:
        self._handle = process_handle
        self.pid = pid
        self.job_handle = job_handle
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None
        self._closed = False

    # ------------------------------------------------------------------ 状态
    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        result = _kernel32.WaitForSingleObject(self._handle, 0)
        if result == WAIT_OBJECT_0:
            self.returncode = self._exit_code()
            return self.returncode
        return None

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32.WaitForSingleObject(self._handle, milliseconds)
        if result == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(str(self.pid), timeout)
        self.returncode = self._exit_code()
        return self.returncode

    def _exit_code(self) -> int:
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return -1
        return int(code.value)

    # ------------------------------------------------------------------ 控制
    def kill(self) -> None:
        if self.returncode is None:
            _kernel32.TerminateProcess(self._handle, 1)

    terminate = kill

    def terminate_tree(self) -> bool:
        if self.job_handle:
            return bool(_kernel32.TerminateJobObject(self.job_handle, 1))
        self.kill()
        return True

    def release_job(self) -> None:
        if self.job_handle:
            _kernel32.CloseHandle(self.job_handle)
            self.job_handle = 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for stream in (self.stdin, self.stdout, self.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = 0


def _build_environment_block(env: dict[str, str] | None) -> tuple[ctypes.Array, int] | None:
    if env is None:
        return None
    items = [f"{key}={value}" for key, value in env.items() if key]
    items.sort()
    payload = "\0".join(items) + "\0\0"
    buffer = ctypes.create_unicode_buffer(payload)
    return buffer, ctypes.sizeof(buffer)


def spawn_in_job(
    argv: list[str] | str,
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    pipes: bool = True,
    job_handle: int | None = None,
    creationflags: int = 0,
    shell: bool = False,
) -> WinChild:
    """创建进程并在**创建时**就把它放进 job。

    job_handle 为 None 时自己新建一个（调用方负责 release_job）。
    """
    if not IS_WINDOWS:
        raise NativeSpawnError("spawn_in_job is Windows only")
    owns_job = job_handle is None
    job = job_handle or create_kill_on_close_job()
    if job is None:
        raise NativeSpawnError("cannot create job object")

    if isinstance(argv, str):
        command_line = argv
        application_name = os.environ.get("ComSpec") if shell else None
    else:
        command_line = subprocess.list2cmdline([str(item) for item in argv])
        application_name = str(argv[0]) if argv and not shell else None
        if application_name and not os.path.isabs(application_name):
            # CreateProcess 会用 PATH 搜索，但仍要求第一段可解析；保留原样即可。
            application_name = None

    security = _SECURITY_ATTRIBUTES()
    security.nLength = ctypes.sizeof(security)
    security.bInheritHandle = True
    security.lpSecurityDescriptor = None

    handles: dict[str, int] = {}
    child_ends: dict[str, int] = {}

    def _pipe(name: str, *, parent_reads: bool) -> None:
        read_end = wintypes.HANDLE()
        write_end = wintypes.HANDLE()
        if not _kernel32.CreatePipe(
            ctypes.byref(read_end), ctypes.byref(write_end), ctypes.byref(security), PIPE_BUFFER_SIZE
        ):
            raise NativeSpawnError(f"CreatePipe({name}) failed: {ctypes.get_last_error()}")
        if parent_reads:
            handles[name] = _handle_int(read_end)
            child_ends[name] = _handle_int(write_end)
            _kernel32.SetHandleInformation(read_end, HANDLE_FLAG_INHERIT, 0)
        else:
            handles[name] = _handle_int(write_end)
            child_ends[name] = _handle_int(read_end)
            _kernel32.SetHandleInformation(write_end, HANDLE_FLAG_INHERIT, 0)

    try:
        if pipes:
            _pipe("stdout", parent_reads=True)
            _pipe("stderr", parent_reads=True)
            _pipe("stdin", parent_reads=False)

        attribute_size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attribute_size))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise NativeSpawnError("InitializeProcThreadAttributeList(size) failed")
        attribute_buffer = ctypes.create_string_buffer(attribute_size.value)
        attribute_list = ctypes.cast(attribute_buffer, wintypes.LPVOID)
        if not _kernel32.InitializeProcThreadAttributeList(
            attribute_list, 1, 0, ctypes.byref(attribute_size)
        ):
            raise NativeSpawnError(
                f"InitializeProcThreadAttributeList failed: {ctypes.get_last_error()}"
            )

        job_value = wintypes.HANDLE(job)
        if not _kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            PROC_THREAD_ATTRIBUTE_JOB_LIST,
            ctypes.cast(ctypes.byref(job_value), wintypes.LPVOID),
            ctypes.sizeof(job_value),
            None,
            None,
        ):
            error = ctypes.get_last_error()
            _kernel32.DeleteProcThreadAttributeList(attribute_list)
            raise NativeSpawnError(f"UpdateProcThreadAttribute(JOB_LIST) failed: {error}")

        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        startup.lpAttributeList = attribute_list
        if pipes:
            startup.StartupInfo.dwFlags |= STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = wintypes.HANDLE(child_ends["stdin"])
            startup.StartupInfo.hStdOutput = wintypes.HANDLE(child_ends["stdout"])
            startup.StartupInfo.hStdError = wintypes.HANDLE(child_ends["stderr"])
        else:
            startup.StartupInfo.dwFlags |= STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = _kernel32.GetStdHandle(STD_INPUT_HANDLE)
            startup.StartupInfo.hStdOutput = _kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            startup.StartupInfo.hStdError = _kernel32.GetStdHandle(STD_ERROR_HANDLE)

        process_info = _PROCESS_INFORMATION()
        flags = EXTENDED_STARTUPINFO_PRESENT | creationflags
        env_block = _build_environment_block(env)
        if env_block is not None:
            flags |= CREATE_UNICODE_ENVIRONMENT
        command_buffer = ctypes.create_unicode_buffer(command_line)

        ok = _kernel32.CreateProcessW(
            application_name,
            command_buffer,
            None,
            None,
            bool(pipes),
            flags,
            ctypes.cast(env_block[0], wintypes.LPVOID) if env_block else None,
            str(cwd) if cwd else None,
            ctypes.byref(startup.StartupInfo),
            ctypes.byref(process_info),
        )
        error = ctypes.get_last_error()
        _kernel32.DeleteProcThreadAttributeList(attribute_list)
        if not ok:
            raise NativeSpawnError(f"CreateProcessW failed: {error}")

        _kernel32.CloseHandle(process_info.hThread)
        for handle in child_ends.values():
            _kernel32.CloseHandle(wintypes.HANDLE(handle))

        streams: dict[str, object] = {"stdin": None, "stdout": None, "stderr": None}
        if pipes:
            import msvcrt

            streams["stdout"] = os.fdopen(
                msvcrt.open_osfhandle(handles["stdout"], os.O_RDONLY | os.O_BINARY), "rb", 0
            )
            streams["stderr"] = os.fdopen(
                msvcrt.open_osfhandle(handles["stderr"], os.O_RDONLY | os.O_BINARY), "rb", 0
            )
            streams["stdin"] = os.fdopen(
                msvcrt.open_osfhandle(handles["stdin"], os.O_WRONLY | os.O_BINARY), "wb", 0
            )

        return WinChild(
            process_handle=_handle_int(process_info.hProcess),
            pid=int(process_info.dwProcessId),
            job_handle=job,
            stdin=streams["stdin"],
            stdout=streams["stdout"],
            stderr=streams["stderr"],
        )
    except Exception:
        if owns_job and job:
            _kernel32.CloseHandle(wintypes.HANDLE(job))
        for handle in handles.values():
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(handle))
            except Exception:
                pass
        for handle in child_ends.values():
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(handle))
            except Exception:
                pass
        raise


def terminate_job(job_handle: int) -> bool:
    if not IS_WINDOWS or not job_handle:
        return False
    return bool(_kernel32.TerminateJobObject(wintypes.HANDLE(job_handle), 1))


def close_job(job_handle: int | None) -> None:
    if not IS_WINDOWS or not job_handle:
        return
    _kernel32.CloseHandle(wintypes.HANDLE(job_handle))


__all__ = [
    "IS_WINDOWS",
    "NativeSpawnError",
    "WinChild",
    "close_job",
    "create_kill_on_close_job",
    "spawn_in_job",
    "terminate_job",
]
