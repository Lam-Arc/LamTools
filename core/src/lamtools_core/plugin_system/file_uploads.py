"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(编码文件写入原会话附件存储，不伪造暂存凭证)。"""
import asyncio
import base64
import binascii
from pathlib import Path

from .session_data import PluginAttachmentAPI, SessionDataError

MAX_ENCODED_UPLOAD_BYTES = 512 * 1024


class FileUploadError(ValueError, RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginFileUploadsAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._host = context.require_service("session_data")

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope or self._context.service("session_data") is not self._host
                or Path(self._context.work_root).resolve() != self._root):
            raise FileUploadError("file-upload/host-changed", "Attachment host binding changed")

    def _check_after_write(self):
        try:
            self._check()
        except (RuntimeError, ValueError, OSError):
            raise FileUploadError("file-upload/host-changed", "Attachment was saved but host binding changed", may_have_changed=True) from None

    async def save_encoded(self, session_id, *, filename, content_base64, mime_type=None):
        self._check()
        if type(content_base64) is not str or len(content_base64) > ((MAX_ENCODED_UPLOAD_BYTES + 2) // 3) * 4:
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64")
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64") from None
        if len(raw) > MAX_ENCODED_UPLOAD_BYTES or base64.b64encode(raw).decode("ascii") != content_base64:
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64")
        self._scope.acquire()
        try:
            picker = PluginAttachmentAPI(self._host, self._scope, self._root, "attachments")
            # user:“复用原宿主权威”+(写入后再次经原附件服务核对会话和项目，不能发布失效作用域的结果)。
            try:
                result = await picker.create(session_id, filename=filename, content=raw, mime_type=mime_type)
            except SessionDataError as error:
                if error.code in {"session-data/invalid-id", "session-data/invalid-filename",
                                  "session-data/invalid-content", "session-data/invalid-mime"}:
                    raise
                self._check_after_write()
                # user:“完成真实接口、参数/错误、作用域、取消/清理”+(原写入抛错时文件或索引可能已经保存，不能假定回滚)。
                raise FileUploadError("file-upload/write-uncertain", "Attachment write failed; inspect current state", may_have_changed=True) from None
            except Exception:
                self._check_after_write()
                raise FileUploadError("file-upload/write-uncertain", "Attachment write failed; inspect current state", may_have_changed=True) from None
            self._check_after_write()
            try:
                await picker.get(session_id, result["id"])
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._check_after_write()
                code = "file-upload/host-changed" if getattr(error, "code", "") in {"session-data/host-changed", "session-data/closed"} else "file-upload/session-unavailable"
                raise FileUploadError(code, "Attachment was saved but its session cannot be verified", may_have_changed=True) from None
            self._check_after_write()
            return result
        finally:
            self._scope.release()
