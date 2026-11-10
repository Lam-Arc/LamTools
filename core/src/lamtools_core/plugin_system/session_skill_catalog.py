"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(会话技能使用原运行注册表和启用账本，不伪造提供方)。"""
from copy import deepcopy
from pathlib import Path

from .workspace_files import PluginWorkspaceFilesAPI


class SessionSkillError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginSessionSkillCatalog:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._files = PluginWorkspaceFilesAPI(context, scope)
        self._catalog = context.resolved_operation_catalog()
        self._factory = getattr(self._catalog, "command_skill_registry_factory", None)
        self._state_factory = getattr(self._catalog, "command_skill_state_store_factory", None)

    def _check(self):
        self._files._check()
        if (self._context._registration_scope is not self._scope or Path(self._context.work_root).resolve() != self._root
                or self._context.resolved_operation_catalog() is not self._catalog
                or getattr(self._catalog, "command_skill_registry_factory", None) is not self._factory
                or getattr(self._catalog, "command_skill_state_store_factory", None) is not self._state_factory):
            raise SessionSkillError("session-skill/host-changed", "Original skill provider changed")

    async def list(self, session_id, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        self._scope.acquire()
        try:
            self._check()
            if not callable(self._factory) or not callable(self._state_factory):
                raise SessionSkillError("session-skill/unavailable", "Original skill registry or state provider is unavailable")
            fs = await self._files._filesystem(session_id, ".")
            self._check()
            registry, state = self._factory(), self._state_factory()
            if not callable(getattr(registry, "available", None)) or not callable(getattr(state, "snapshot", None)):
                raise SessionSkillError("session-skill/unavailable", "Original skill provider is unavailable")
            # user:“复用原宿主权威”+(复用原注册表和启用账本，只投影可由用户调用的元数据，不返回技能正文)。
            _, entries = state.snapshot()
            entries = deepcopy(entries)
            result = []
            truncated = False
            for skill in registry.available(fs.root):
                status = entries.get(skill.name)
                if not getattr(skill, "user_invocable", True) or isinstance(status, dict) and not bool(status.get("enabled", True)):
                    continue
                if len(result) == limit:
                    truncated = True
                    break
                item = {"name": skill.name, "description": skill.description, "model_invocable": bool(getattr(skill, "model_invocable", True))}
                if skill.location is not None:
                    item["path"] = str(skill.location)
                result.append(item)
            self._check()
            # user:“复用原宿主权威”+(技能发现完成后复核原会话可见性和执行目录，丢弃旧作用域结果)。
            current = await self._files._filesystem(session_id, ".")
            self._check()
            if Path(current.root).resolve() != Path(fs.root).resolve():
                raise SessionSkillError("session-skill/directory-changed", "Session execution directory changed during discovery")
            # user:“复用原宿主权威”+(返回前复核启用账本；等待期间发生变更则拒绝旧技能列表)。
            _, current_entries = state.snapshot()
            self._check()
            if current_entries != entries:
                raise SessionSkillError("session-skill/state-changed", "Skill enablement changed during discovery")
            return {"skills": result, "truncated": truncated}
        finally:
            self._scope.release()
