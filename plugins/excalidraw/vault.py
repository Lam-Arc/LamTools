"""Workspace file adapter for the Excalidraw port.

user:“放手去做吧”+(保留原版文件内容并防止已知的外部编辑被静默覆盖)。
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path


class ConflictError(RuntimeError):
    """The file changed since it was read; retain the caller's draft."""


_lock = threading.RLock()


def _path(root: Path | str, name: str) -> Path:
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not isinstance(name, str) or not name:
        raise ValueError('workspace and file path are required')
    target = (root / name).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError('file path is outside the workspace')
    return target


def read_text(root: Path | str, name: str) -> str:
    return _path(root, name).read_bytes().decode('utf-8')


def write_text(root: Path | str, name: str, content: str, original: str | None) -> None:
    if not isinstance(content, str) or (original is not None and not isinstance(original, str)):
        raise ValueError('content and original must be text')
    target = _path(root, name)
    with _lock:
        def ensure_unchanged() -> None:
            try:
                current = target.read_bytes().decode('utf-8')
            except FileNotFoundError:
                current = None
            if current != original:
                raise ConflictError('文件已更改，当前草稿未覆盖原文件')
        ensure_unchanged()
        descriptor, temp_name = tempfile.mkstemp(prefix='.excalidraw-', suffix='.tmp', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            ensure_unchanged()
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

# user:“该修就修，不用停下”+(将原版 Markdown 画图的图片放进工作区附件并按内容去重)。
def put_asset(root: Path | str, data_url: str) -> str:
    import base64
    import hashlib
    import re
    types = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif',
             'image/webp': 'webp', 'image/svg+xml': 'svg'}
    if not isinstance(data_url, str):
        raise ValueError('image data is required')
    match = re.fullmatch(r'data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)', data_url)
    if not match or match.group(1) not in types:
        raise ValueError('unsupported image data')
    raw = base64.b64decode(match.group(2), validate=True)
    if not raw:
        raise ValueError('empty image data')
    directory = _path(root, '.excalidraw-assets')
    directory.mkdir(exist_ok=True)
    name = hashlib.sha256(raw).hexdigest() + '.' + types[match.group(1)]
    target = _path(root, '.excalidraw-assets/' + name)
    with _lock:
        if target.exists():
            if target.read_bytes() != raw:
                raise ConflictError('附件内容与已有文件不一致')
        else:
            descriptor, temp_name = tempfile.mkstemp(prefix='.excalidraw-', suffix='.tmp', dir=directory)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temp_name, target)
                except FileExistsError:
                    if target.read_bytes() != raw:
                        raise ConflictError('附件内容与已有文件不一致')
            finally:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
    return '.excalidraw-assets/' + name


# user:“该修就修，不用停下”+(原版 Markdown 可以读取工作区内的已有图片，路径仍限定在工作区)。
def read_asset(root: Path | str, name: str, drawing_path: str | None = None) -> tuple[str, str]:
    import base64
    import hashlib
    import re
    types = {'png':'image/png', 'jpg':'image/jpeg', 'jpeg':'image/jpeg', 'gif':'image/gif',
             'webp':'image/webp', 'svg':'image/svg+xml'}
    if not isinstance(name, str) or not name or Path(name).is_absolute() or any(x in name for x in ('#', '|', '\x00')):
        raise ValueError('unsupported asset path')
    if Path(name).suffix.lower().lstrip('.') not in types:
        raise ValueError('unsupported image type')
    root_path = Path(root).resolve(strict=True)
    candidates = []
    if '/' in name.replace('\\', '/'):
        candidates.append(root_path / name)
    if drawing_path:
        drawing = _path(root_path, drawing_path)
        candidates.append(drawing.parent / name)
    candidates.append(root_path / name)
    target = None
    for candidate in candidates:
        try:
            resolved = _path(root_path, str(candidate))
        except ValueError:
            continue
        if resolved.is_file():
            target = resolved
            break
    if target is None:
        raise FileNotFoundError('workspace image not found')
    raw = target.read_bytes()
    relative = target.relative_to(root_path).as_posix()
    if re.fullmatch(r'\.excalidraw-assets/[0-9a-f]{64}\.(png|jpg|gif|webp|svg)', relative):
        if hashlib.sha256(raw).hexdigest() != target.stem:
            raise ConflictError('附件内容已改变')
    return ('data:' + types[target.suffix.lower()[1:]] + ';base64,' + base64.b64encode(raw).decode('ascii'), relative)

# user:“该修就修，不用停下”+(原版内部链接解析到当前工作区的实际文件，不允许越出工作区)。
def resolve_link(root: Path | str, name: str, drawing_path: str | None = None) -> str:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or any(x in name for x in ('#', '|', '\x00')):
        raise ValueError('unsupported link path')
    root_path = Path(root).resolve(strict=True)
    candidates = []
    if '/' in name.replace('\\', '/'):
        candidates.append(root_path / name)
    if drawing_path:
        candidates.append(_path(root_path, drawing_path).parent / name)
    candidates.append(root_path / name)
    for candidate in candidates:
        for path in (candidate, candidate.with_name(candidate.name + '.md')) if not candidate.suffix else (candidate,):
            try:
                resolved = _path(root_path, str(path))
            except ValueError:
                continue
            if resolved.is_file():
                return str(resolved)
    # user:“该修就修，不用停下”+(支持原版按文件名查找；多个同名文件时不擅自选一个)。
    if '/' not in name.replace('\\', '/'):
        names = {name.casefold()}
        if not Path(name).suffix:
            names.add((name + '.md').casefold())
        matches: set[Path] = set()
        def on_error(error):
            raise error
        for directory, _dirs, files in os.walk(root_path, followlinks=False, onerror=on_error):
            for filename in files:
                if filename.casefold() not in names:
                    continue
                try:
                    resolved = _path(root_path, str(Path(directory) / filename))
                except ValueError:
                    continue
                if resolved.is_file():
                    matches.add(resolved)
                    if len(matches) > 1:
                        raise ValueError('找到多个同名文件，请使用完整路径')
        if matches:
            return str(next(iter(matches)))
    raise FileNotFoundError('linked workspace file not found')
