"""Library 全盘文件与统一资产。

搜索复用本机 Everything 索引；资产层只记录用户真正管理过的文件；文件操作
直接作用于原文件。三个能力共用一套文件身份与服务入口。
"""

from .everything import EverythingError, EverythingProvider, SearchSpec, FileHit, SearchPage
from .identity import FileIdentity, identity_for, normalize_path, path_key
from .service import LibraryFileService, kind_of
from .store import FileAssetStore, asset_to_dict, normalize_tags

__all__ = [
    "EverythingError",
    "EverythingProvider",
    "SearchSpec",
    "FileHit",
    "SearchPage",
    "FileIdentity",
    "identity_for",
    "normalize_path",
    "path_key",
    "LibraryFileService",
    "kind_of",
    "FileAssetStore",
    "asset_to_dict",
    "normalize_tags",
]
