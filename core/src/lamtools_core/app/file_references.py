"""Resolve a missing report path against bounded, project-local artifact folders."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

ARTIFACT_FOLDERS = ('.lam/artifacts', '.lam/artifact', 'artifacts', 'artifact')
MAX_REFERENCE_ENTRIES = 5000


class AmbiguousFileReference(ValueError):
    pass


def resolve_file_reference(raw_path: str, work_root: str | Path) -> Path:
    # user:“实际的地址是在 /artifacts 内”+(原地址优先；缺失时仅恢复到项目成果目录中的唯一匹配)。
    root = Path(work_root).resolve()
    value = str(raw_path).strip().replace('\\', '/')
    if value.startswith('workspace://'):
        value = value[len('workspace://'):]
    if value.startswith('file://'):
        value = unquote(value[len('file://'):])
        if re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]
    if not value or '\x00' in value or (re.match(r'^[a-zA-Z][\w+.-]*:', value) and not re.match(r'^[A-Za-z]:/', value)):
        raise FileNotFoundError('原文件不存在')
    alias = value.startswith('/artifacts/') or value.startswith('/artifact/')
    raw = Path(value)
    absolute = raw.is_absolute() and not alias
    candidate = (raw if absolute else root / value.lstrip('/')).resolve()
    if not absolute and not candidate.is_relative_to(root):
        raise FileNotFoundError('原文件不存在')
    if candidate.is_file():
        return candidate
    if not candidate.is_relative_to(root):
        raise FileNotFoundError('原文件不存在')
    bases = [root]
    # A boot workspace may contain a selected project; never inspect another
    # project inferred from a path outside that workspace.
    if candidate.parent.is_dir() and candidate.parent != root:
        bases.append(candidate.parent)
    matches: set[Path] = set()
    visited: set[Path] = set()
    count = 0
    for base in bases:
        for folder in ARTIFACT_FOLDERS:
            artifacts = (base / folder).resolve()
            if not artifacts.is_relative_to(root) or not artifacts.is_dir():
                continue
            for current, dirs, files in os.walk(artifacts, followlinks=False):
                count += 1 + len(dirs)
                if count > MAX_REFERENCE_ENTRIES:
                    raise AmbiguousFileReference('成果目录过大，请使用工具返回的完整路径')
                dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
                for name in sorted(files):
                    path = Path(current) / name
                    if path in visited:
                        continue
                    visited.add(path)
                    count += 1
                    if count > MAX_REFERENCE_ENTRIES:
                        raise AmbiguousFileReference('成果目录过大，请使用工具返回的完整路径')
                    if name == candidate.name:
                        actual = path.resolve()
                        if actual.is_relative_to(root) and actual.is_file():
                            matches.add(actual)
    if len(matches) > 1:
        raise AmbiguousFileReference('存在多个同名成果，请使用完整路径')
    if matches:
        return next(iter(matches))
    raise FileNotFoundError('原文件不存在')
