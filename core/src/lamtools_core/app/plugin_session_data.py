"""user:“给我把 2 阶段做完，前端除外”+(公开真实附件、标题修订和最新会话投影，不复制持久权威或暴露原始元数据)。"""
from pathlib import Path

from lamtools_core.attachment import AttachmentService
from lamtools_core.attachment.store import CoreAttachmentStore
from lamtools_core.plugin_system.filesystem_access import PluginFilesystemAPI
from lamtools_core.plugin_system.session_data import SessionDataError
from lamtools_core.plugin_system.sessions import SessionError
from .persistence_host import RevisionConflictError
from .session_autotitle import is_default_title


class PluginSessionDataService:
    def __init__(self, sessions, data_dir):
        self._sessions, self._data_dir = sessions, data_dir
        self._store = sessions._context().host.session_store

    async def _read(self, session_id, root):
        context = self._sessions._context()
        if context.host.session_store is not self._store:
            raise SessionDataError("session-data/host-changed", "Session store changed")
        result = await self._store.get_readonly_revision(session_id)
        if result is None:
            raise SessionDataError("session-data/not-found", "Session is unknown or unavailable")
        record, revision = result
        project = record.metadata.get("work_root")
        if not project or Path(project).resolve() != Path(root).resolve():
            raise SessionDataError("session-data/not-found", "Session is outside the bound project")
        return context, record, revision

    async def call(self, scope, root, kind, method, session_id, **kwargs):
        mutation = method in {"create", "reference", "set", "put", "delete", "record"}
        try:
            context, record, revision = await self._read(session_id, root)
            scope.check_open()
            if kind in {"message-feedback", "session-feedback"}:
                from .plugin_feedback import feedback_call
                return await feedback_call(self, scope, root, kind, method, session_id, kwargs)
            if kind == "references":
                from .plugin_session_references import reference_call
                return await reference_call(self, scope, root, method, session_id, kwargs)
            if kind == "title":
                if method == "set":
                    if kwargs["expected_revision"] != revision:
                        raise SessionDataError("session-data/conflict", "Session changed; read again")
                    if kwargs["only_if_default"] and not is_default_title(record.title, session_id):
                        return {"session_id": session_id, "title": record.title, "revision": revision, "updated": False}
                    saved = await self._store.patch(session_id, title=kwargs["title"], expected_revision=revision,
                                                   only_if_title_default=kwargs["only_if_default"])
                    if saved is None:
                        raise SessionDataError("session-data/conflict", "Session became unavailable or title was changed")
                    return {"session_id": session_id, "title": saved.title, "revision": revision + 1, "updated": True}
                return {"session_id": session_id, "title": record.title, "revision": revision}
            if kind == "projections":
                if method == "events":
                    return await self._sessions.events(session_id, **kwargs)
                # A fresh database read is the cache-invalidation strategy; no stale second projection store.
                state = await self._sessions.state(session_id)
                return {"session_id": session_id, "title": record.title, "revision": revision,
                        "status": state.status, "running": state.running, "queued_count": state.queued_count,
                        "event_seq": state.last_event_seq}
            if kind != "attachments":
                raise SessionDataError("session-data/unsupported", "Unknown session data contract")
            async with context.session_factory() as db:
                repository = context.host.member_hooks.attachment_repository(db)
                if repository is not None:
                    service = AttachmentService(repository)
                elif self._data_dir is not None:
                    service = CoreAttachmentStore(context.session_factory, Path(self._data_dir))
                else:
                    raise SessionDataError("session-data/unavailable", "Attachment storage is not configured")
                if method == "create":
                    return await service.create(session_id, **kwargs)
                if method == "reference":
                    path = PluginFilesystemAPI(root, scope).resolve(kwargs["path"])
                    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
                        raise SessionDataError("session-data/invalid-path", "Reference an existing project file, at most 50 MiB")
                    return await service.reference(session_id, str(path))
                if method == "list":
                    rows = await service.list(session_id)
                    limit = kwargs["limit"]
                    return {"items": rows[:limit], "truncated": len(rows) > limit}
                item = await service.get(kwargs["attachment_id"])
                if item.session_id != session_id:
                    raise SessionDataError("session-data/not-found", "Attachment is unknown in this session")
                if method == "preview":
                    return await service.preview(item.id)
                return await service.get_response(item.id)
        except RevisionConflictError:
            raise SessionDataError("session-data/conflict", "Session changed during update") from None
        except LookupError:
            raise SessionDataError("session-data/not-found", "Attachment is unknown or unavailable") from None
        except SessionError as error:
            raise SessionDataError("session-data/closed" if error.code == "session/closed" else "session-data/host-changed", "Session host is unavailable") from None
        except SessionDataError:
            raise
        except Exception:
            raise SessionDataError("session-data/operation-failed", "Session data operation failed; inspect current state before retrying", may_have_changed=mutation) from None
