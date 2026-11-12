import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'agent_docs/constant-repair/apply-repair.ps1'
SHELL = shutil.which('pwsh') or shutil.which('powershell')


def prepare(tmp_path):
    install, payload = tmp_path / 'installed', tmp_path / 'payload'
    for root in (install, payload):
        (root / 'sunday-backend/_internal').mkdir(parents=True)
    (install / '.lam').mkdir()
    (install / '.lam/core.db').write_bytes(b'user data must survive')
    (install / '.lam/core.db-wal').write_bytes(b'recent changes')
    (install / '.lam/core.db-shm').write_bytes(b'shared memory')
    for name, value in [('Sunday.exe', b'old shell'), ('sunday-backend/sunday-core.exe', b'old backend')]:
        (install / name).write_bytes(value)
    files = []
    for name, value in [('Sunday.exe', b'new shell'), ('sunday-backend/sunday-core.exe', b'new backend'),
                        ('sunday-backend/_internal/dependency.txt', b'verified dependency')]:
        (payload / name).write_bytes(value)
        files.append({'path': name, 'sha256': hashlib.sha256(value).hexdigest()})
    (payload / 'manifest.json').write_text(json.dumps({'files': files}), encoding='utf-8')
    return install, payload


def run(install, payload):
    return subprocess.run([SHELL, '-NoProfile', '-File', str(SCRIPT), '-InstallDir', str(install),
                           '-PayloadDir', str(payload)], capture_output=True, text=True, encoding='utf-8', errors='replace')


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(切换须校验产物、保留旧版及用户数据库，并拒绝覆盖仍在运行的安装)。
def test_repair_switch_preserves_data_and_old_binaries(tmp_path):
    install, payload = prepare(tmp_path)
    result = run(install, payload)
    assert result.returncode == 0, result.stderr
    assert (install / 'Sunday.exe').read_bytes() == b'new shell'
    assert (install / 'sunday-backend/sunday-core.exe').read_bytes() == b'new backend'
    assert (install / '.lam/core.db').read_bytes() == b'user data must survive'
    backups = list((install / '.repair-backups').glob('*/Sunday.exe'))
    assert len(backups) == 1 and backups[0].read_bytes() == b'old shell'
    assert (backups[0].parent / 'sunday-backend/sunday-core.exe').read_bytes() == b'old backend'
    assert (backups[0].parent / 'data/core.db').read_bytes() == b'user data must survive'
    assert (backups[0].parent / 'data/core.db-wal').read_bytes() == b'recent changes'
    assert (backups[0].parent / 'data/core.db-shm').read_bytes() == b'shared memory'


def test_corrupt_payload_never_replaces_installed_files(tmp_path):
    install, payload = prepare(tmp_path)
    (payload / 'Sunday.exe').write_bytes(b'corrupt')
    result = run(install, payload)
    assert result.returncode != 0
    assert 'hash' in result.stderr.lower()
    assert (install / 'Sunday.exe').read_bytes() == b'old shell'
    assert not (install / '.repair-backups').exists()


def test_running_installation_is_not_replaced(tmp_path):
    install, payload = prepare(tmp_path)
    shutil.copyfile(Path('C:/Windows/System32/cmd.exe'), install / 'Sunday.exe')
    process = subprocess.Popen([str(install / 'Sunday.exe'), '/d', '/c', 'set /p repair_wait='],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = run(install, payload)
        assert result.returncode != 0
        assert 'running' in result.stderr.lower()
        assert not (install / '.repair-backups').exists()
    finally:
        process.communicate(input=b'finished\r\n')


def test_failed_backend_move_rolls_back_the_shell(tmp_path):
    import ctypes
    from ctypes import wintypes
    install, payload = prepare(tmp_path)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(install / 'sunday-backend'), 0x80000000, 0, None, 3, 0x02000000, None)
    assert handle != wintypes.HANDLE(-1).value
    try:
        result = run(install, payload)
        assert result.returncode != 0
        assert (install / 'Sunday.exe').read_bytes() == b'old shell'
        assert (install / 'sunday-backend/sunday-core.exe').read_bytes() == b'old backend'
        assert (install / '.lam/core.db').read_bytes() == b'user data must survive'
    finally:
        kernel.CloseHandle(handle)
