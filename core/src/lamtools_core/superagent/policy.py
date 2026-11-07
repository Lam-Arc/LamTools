"""授权闸门：由宿主配置决定能不能接单，外部文本无权扩权。

user:“Policy 由宿主持有；人类消息/Issue 正文/模型输出无权自行扩权”
+(所以这里只读宿主传入的 PolicyConfig，绝不解析事件正文里的"请给我权限")。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Mandate, SourceEvent

Verdict = Literal["accept", "deny", "ask_human"]


@dataclass(frozen=True)
class PolicyConfig:
    allowed_sources: frozenset[str] = frozenset()
    allowed_event_types: frozenset[str] = frozenset()
    trusted_actors: frozenset[str] = frozenset()
    allowed_repos: frozenset[str] = frozenset()
    allow_push: bool = False
    allow_create_pr: bool = False
    default_base_branch: str = "main"
    allowed_tools: tuple[str, ...] = ()
    version: str = "policy.v1"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyVerdict:
    outcome: Verdict
    reason: str
    mandate: Mandate | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome == "accept"


class PolicyGate:
    """硬闸门。顺序固定：来源 → 身份 → 事件类型 → 仓库 → 高危动作。"""

    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def evaluate(self, event: SourceEvent) -> PolicyVerdict:
        config = self.config
        if not event.source_id:
            return PolicyVerdict("deny", "source-required")
        # 默认拒绝：没有显式授权的来源就不接单，不靠「没配置就放开」。
        if not config.allowed_sources:
            return PolicyVerdict("deny", "no-source-authorized")
        if event.source_id not in config.allowed_sources:
            return PolicyVerdict("deny", f"source-not-allowed:{event.source_id}")
        if event.event_type not in config.allowed_event_types:
            return PolicyVerdict("deny", f"event-type-not-allowed:{event.event_type}")
        actor_key = event.actor.actor_id or event.actor.login
        if not config.trusted_actors:
            return PolicyVerdict("deny", "no-actor-authorized")
        if not event.actor.trusted:
            return PolicyVerdict("deny", f"actor-not-trusted:{actor_key}")
        if actor_key not in config.trusted_actors:
            return PolicyVerdict("deny", f"actor-not-allowed:{actor_key}")
        if not event.repo:
            return PolicyVerdict("deny", "repo-required")
        if event.repo not in config.allowed_repos:
            return PolicyVerdict("deny", f"repo-not-allowed:{event.repo}")

        # 事件正文里出现"推送/开 PR/合并/发布"这类要求时，一律转人工，
        # 不因为模型或 issue 作者写了这句话就放开权限。
        requested = {str(item).lower() for item in (event.payload.get("requested_actions") or ())}
        for high_risk in ("push", "create_pr", "merge", "release"):
            if high_risk in requested:
                return PolicyVerdict("ask_human", f"high-risk-action-requires-approval:{high_risk}")
        if str(event.payload.get("text") or "").lower().find("merge to main") >= 0:
            return PolicyVerdict("ask_human", "high-risk-action-requires-approval:merge")

        mandate = Mandate(
            repo_root=event.repo,
            allowed_paths=tuple(config.extra.get("allowed_paths") or ()),
            allowed_tools=tuple(config.allowed_tools),
            base_branch=str(event.payload.get("base_branch") or config.default_base_branch),
            can_push=bool(config.allow_push),
            can_create_pr=bool(config.allow_create_pr),
            policy_version=config.version,
        )
        return PolicyVerdict("accept", "policy-accepted", mandate)

    @staticmethod
    def within_mandate(mandate: Mandate, *, repo: str, wants_push: bool = False, wants_pr: bool = False) -> bool:
        if mandate.revoked:
            return False
        if not mandate.permits_repo(repo):
            return False
        if wants_push and not mandate.can_push:
            return False
        if wants_pr and not mandate.can_create_pr:
            return False
        return True


__all__ = ["PolicyConfig", "PolicyGate", "PolicyVerdict", "Verdict"]
