"""Acceptance checks for the unbounded log found in constant Sunday."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from lamtools_core.logging_setup import attach_backend_file_logger


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(日志不能无限增长，轮转须保留可查的近期错误且重复初始化不能重复写入)。
def test_backend_log_is_bounded_and_retains_errors(tmp_path):
    path = attach_backend_file_logger(tmp_path)
    root = logging.getLogger()
    handlers = [h for h in root.handlers if getattr(h, 'baseFilename', '') == str(path)]
    try:
        assert len(handlers) == 1
        handler = handlers[0]
        assert isinstance(handler, RotatingFileHandler)
        assert 0 < handler.maxBytes <= 32 * 1024 * 1024
        assert 1 <= handler.backupCount <= 5
        handler.maxBytes = 300
        handler.backupCount = 2
        for i in range(20):
            handler.handle(logging.LogRecord('constant.acceptance', logging.ERROR, __file__, 1,
                                            f'error-{i:02d} ' + 'x' * 80, (), None))
        handler.flush()
        logs = list(tmp_path.glob('backend.log*'))
        assert len(logs) == 3
        assert all(p.stat().st_size <= 300 for p in logs)
        assert 'error-19' in path.read_text(encoding='utf-8')
        assert attach_backend_file_logger(tmp_path) == path
        assert sum(getattr(h, 'baseFilename', '') == str(path) for h in root.handlers) == 1
    finally:
        for h in handlers:
            root.removeHandler(h)
            h.close()


def test_existing_large_log_is_archived_on_next_write(tmp_path):
    path = tmp_path / 'backend.log'
    path.write_text('historical evidence\n' * 50, encoding='utf-8')
    attach_backend_file_logger(tmp_path)
    root = logging.getLogger()
    handlers = [h for h in root.handlers if getattr(h, 'baseFilename', '') == str(path)]
    try:
        handler = handlers[0]
        assert isinstance(handler, RotatingFileHandler)
        handler.maxBytes = 300
        handler.handle(logging.LogRecord('constant.acceptance', logging.ERROR, __file__, 1,
                                        'new failure', (), None))
        handler.flush()
        assert (tmp_path / 'backend.log.1').read_text(encoding='utf-8').startswith('historical evidence')
        assert 'new failure' in path.read_text(encoding='utf-8')
    finally:
        for h in handlers:
            root.removeHandler(h)
            h.close()
