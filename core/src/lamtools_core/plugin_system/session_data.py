"""user:“给我把 2 阶段做完，前端除外”+(会话资料门面复用宿主存储，停用撤回且写入等待原事务完成)。"""
from lamtools_core.async_tasks import finish_on_cancel


class SessionDataError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


def identifier(value):
    if type(value) is not str or not value.strip() or len(value) > 256 or "\x00" in value:
        raise SessionDataError("session-data/invalid-id", "Use a bounded nonempty identifier")
    return value


class PluginSessionDataAPI:
    def __init__(self, host, scope, root, kind):
        self._host, self._scope, self._root, self._kind = host, scope, root, kind

    async def _call(self, method, session_id, **kwargs):
        self._scope.acquire()
        try:
            work = self._host.call(self._scope, self._root, self._kind, method, identifier(session_id), **kwargs)
            if method in {"create", "reference", "set", "put", "delete", "record"}:
                return await finish_on_cancel(work, name="plugin-session-data-write")
            return await work
        finally:
            self._scope.release()


class PluginAttachmentAPI(PluginSessionDataAPI):
    async def create(self, session_id, *, filename, content, mime_type=None):
        if type(filename) is not str or not filename.strip() or len(filename) > 256 or "\x00" in filename:
            raise SessionDataError("session-data/invalid-filename", "Use a bounded filename")
        if type(content) is not bytes or len(content) > 50 * 1024 * 1024:
            raise SessionDataError("session-data/invalid-content", "Use bytes, at most 50 MiB")
        if mime_type is not None and (type(mime_type) is not str or len(mime_type) > 256):
            raise SessionDataError("session-data/invalid-mime", "Use a bounded MIME type")
        return await self._call("create", session_id, filename=filename, content=content, mime_type=mime_type)

    async def reference(self, session_id, path):
        return await self._call("reference", session_id, path=path)

    async def list(self, session_id, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise SessionDataError("session-data/invalid-limit", "limit must be 1–1000")
        return await self._call("list", session_id, limit=limit)

    async def get(self, session_id, attachment_id):
        return await self._call("get", session_id, attachment_id=identifier(attachment_id))

    async def preview(self, session_id, attachment_id):
        return await self._call("preview", session_id, attachment_id=identifier(attachment_id))


class PluginTitleAPI(PluginSessionDataAPI):
    async def get(self, session_id):
        return await self._call("get", session_id)

    async def set(self, session_id, title, *, expected_revision, only_if_default=False):
        if type(title) is not str or not title.strip() or len(title) > 256 or any(ord(c) < 32 for c in title):
            raise SessionDataError("session-data/invalid-title", "Use single-line title text, at most 256 characters")
        if type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 1 or type(only_if_default) is not bool:
            raise SessionDataError("session-data/invalid-revision", "Read current revision before setting title")
        return await self._call("set", session_id, title=title, expected_revision=expected_revision, only_if_default=only_if_default)


class PluginProjectionAPI(PluginSessionDataAPI):
    async def get(self, session_id):
        return await self._call("get", session_id)

    async def events(self, session_id, *, after_seq=0, limit=100, max_bytes=1048576):
        return await self._call("events", session_id, after_seq=after_seq, limit=limit, max_bytes=max_bytes)


class PluginFeedbackAPI(PluginSessionDataAPI):
    def _version(self, value):
        if value is not None and (type(value) is not int or not 1 <= value <= 2**63 - 1):
            raise SessionDataError("session-data/invalid-version", "Use the feedback version, or None for first creation")

    def _text(self, value, maximum):
        if type(value) is not str or len(value) > maximum or "\x00" in value:
            raise SessionDataError("session-data/invalid-feedback", "Feedback fields exceed the text limit")
        return value

    async def list(self, session_id):
        return await self._call("list", session_id)

    async def put(self, session_id, message_id, *, rating, if_version, note="", category=""):
        self._version(if_version)
        if rating not in {"positive", "negative"}:
            raise SessionDataError("session-data/invalid-rating", "rating must be positive or negative")
        return await self._call("put", session_id, message_id=identifier(message_id), rating=rating, if_version=if_version,
                                note=self._text(note, 4000), category=self._text(category, 100))

    async def delete(self, session_id, message_id, *, if_version):
        self._version(if_version)
        if if_version is None:
            raise SessionDataError("session-data/invalid-version", "Deletion requires the current feedback version")
        return await self._call("delete", session_id, message_id=identifier(message_id), if_version=if_version)

    async def record(self, session_id, *, text="", category="", request_id):
        return await self._call("record", session_id, text=self._text(text, 4000), category=self._text(category, 100), request_id=identifier(request_id))


class PluginSessionReferencesAPI(PluginSessionDataAPI):
    async def list_candidates(self, session_id, query="", *, limit=50):
        if type(query) is not str or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Use a query up to 200 characters and limit 1–100")
        return await self._call("candidates", session_id, query=query, limit=limit)

    async def prepare(self, session_id, references, *, max_chars=16000):
        if type(references) is not list or not 1 <= len(references) <= 8 or type(max_chars) is not int or not 1 <= max_chars <= 65536:
            raise ValueError("Choose 1–8 session IDs and max_chars 1–65536")
        refs = [identifier(ref) for ref in references]
        if session_id in refs or len(set(refs)) != len(refs):
            raise ValueError("References must be distinct and cannot include the current session")
        return await self._call("prepare", session_id, references=refs, max_chars=max_chars)
