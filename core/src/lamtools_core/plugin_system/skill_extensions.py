"""user:“宿主能力补齐和接口完善与文档更新”+(内存技能绑定受管启动代，不创建虚假文件位置或额外文件访问授权)。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lamtools_core.skills import Skill
from .services import RegistrationScope


@dataclass(eq=False)
class _Entry:
    scope: RegistrationScope
    skill: Skill
    live: bool = True


class PluginSkillAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    def register(self, name: str, description: str, content: str, *, model_invocable=True, user_invocable=True):
        self._scope.check_open()
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 128:
            raise ValueError("skill name must be lowercase kebab-case, at most 128 characters")
        if not isinstance(description, str) or not description.strip() or not isinstance(content, str) or not content.strip():
            raise ValueError("skill description and content must be non-empty strings")
        if type(model_invocable) is not bool or type(user_invocable) is not bool:
            raise TypeError("skill invocation policies must be boolean")
        for old in self._host.entries:
            if old.live and old.scope.accepting and old.skill.name == name:
                raise ValueError(f"runtime skill name conflict: {name}")
        skill = Skill(name=name, description=description, location=None, content=content,
                      model_invocable=model_invocable, user_invocable=user_invocable, plugin=self._scope.owner)
        entry = _Entry(self._scope, skill)
        self._host.entries.append(entry)
        def remove():
            entry.live = False
            if entry in self._host.entries:
                self._host.entries.remove(entry)
        self._scope.on_dispose(remove)
        return remove


class SkillExtensionsHost:
    def __init__(self):
        self.entries: list[_Entry] = []

    def for_scope(self, scope):
        scope.check_open()
        return PluginSkillAPI(self, scope)

    def snapshot(self):
        return sorted((entry.skill for entry in self.entries
                       if entry.live and entry.scope.accepting and entry.scope.published), key=lambda skill: skill.name)


def ensure_skill_extensions(context):
    host = context.service("skill_extensions")
    if host is None:
        host = SkillExtensionsHost()
        context.set_service("skill_extensions", host)
    return host
