"""Bounded, token-aware fitting of compacted context replacements."""

from __future__ import annotations

import logging
from dataclasses import replace

from lamtools_core.llm import ChatMessage
from lamtools_core.tokens import estimate_text_tokens

from .formatting import truncate_text_to_tokens
from .models import (
    CompactionBudgetExceeded,
    CompactionFitInput,
    CompactionFitResult,
    CompactionTokenEstimator,
)
from .planner import _semantic_message_groups


_logger = logging.getLogger(__name__)
MAX_FIT_ATTEMPTS = 8


class CompactionFitter:
    """Fit a summary and recent tail with a bounded deterministic strategy."""

    def __init__(self, estimate_tokens: CompactionTokenEstimator) -> None:
        self._estimate_tokens = estimate_tokens

    def fit(self, fit_input: CompactionFitInput) -> CompactionFitResult:
        if fit_input.target_tokens <= 0:
            raise CompactionBudgetExceeded(
                "required context target must be positive",
                estimated_tokens=self._estimate_tokens(
                    [*fit_input.system_prefix, *fit_input.recent_messages]
                ),
                target_tokens=fit_input.target_tokens,
            )

        prefix = list(fit_input.system_prefix)
        recent = list(fit_input.recent_messages)
        summary_content = str(fit_input.summary_message.content or "")
        required_recent = self._required_recent_messages(recent)
        required_tokens = self._estimate_tokens([*prefix, *required_recent])
        if required_tokens > fit_input.target_tokens:
            raise CompactionBudgetExceeded(
                "required latest turn exceeds target token budget",
                estimated_tokens=required_tokens,
                target_tokens=fit_input.target_tokens,
            )

        def candidate(content: str, retained: list[ChatMessage]) -> list[ChatMessage]:
            summary = replace(fit_input.summary_message, content=content)
            return [*prefix, summary, *retained]

        current_messages = candidate(summary_content, recent)
        current_tokens = self._estimate_tokens(current_messages)
        attempts = 1
        if current_tokens <= fit_input.target_tokens:
            return CompactionFitResult(
                messages=current_messages,
                estimated_tokens=current_tokens,
                attempts=attempts,
                strategy="original",
            )

        strategies = (
            ("compress_summary_once", self._compress_summary),
            ("compress_summary_twice", self._compress_summary),
            ("drop_oldest_recent_turn", self._drop_oldest_recent_turn),
            ("drop_oldest_recent_turn_again", self._drop_oldest_recent_turn),
            ("truncate_summary", self._truncate_summary),
            ("minimal_summary", self._minimal_summary),
            ("latest_user_only", self._latest_user_only),
        )
        for strategy, shrink in strategies:
            if attempts >= MAX_FIT_ATTEMPTS:
                break
            next_content, next_recent = shrink(
                summary_content,
                recent,
                prefix=prefix,
                target_tokens=fit_input.target_tokens,
            )
            next_messages = candidate(next_content, next_recent)
            next_tokens = self._estimate_tokens(next_messages)
            attempts += 1
            if next_tokens >= current_tokens:
                _logger.warning(
                    "compaction fitter strategy did not reduce exact token count "
                    "strategy=%s attempt=%d current=%d next=%d",
                    strategy,
                    attempts,
                    current_tokens,
                    next_tokens,
                )
            else:
                summary_content = next_content
                recent = next_recent
                current_messages = next_messages
                current_tokens = next_tokens
            if current_tokens <= fit_input.target_tokens:
                return CompactionFitResult(
                    messages=current_messages,
                    estimated_tokens=current_tokens,
                    attempts=attempts,
                    strategy=strategy,
                )

        raise CompactionBudgetExceeded(
            "required context remains over the compaction target after bounded fitting",
            estimated_tokens=current_tokens,
            target_tokens=fit_input.target_tokens,
        )

    @staticmethod
    def _required_recent_messages(recent: list[ChatMessage]) -> list[ChatMessage]:
        groups = _semantic_message_groups(recent)
        latest_user = next(
            (message for message in reversed(recent) if message.role == "user"),
            None,
        )
        if latest_user is not None:
            for group in groups:
                if any(message is latest_user for message in group):
                    return list(group)
        return list(groups[-1] if groups else [])

    def _compress_summary(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        base_tokens = self._estimate_tokens(
            [*prefix, ChatMessage(role="system", content=""), *recent]
        )
        current_text_tokens = estimate_text_tokens(content)
        available_tokens = target_tokens - base_tokens
        if available_tokens <= 0 or current_text_tokens <= available_tokens:
            return content, list(recent)
        next_budget = max(1, current_text_tokens - max(1, current_text_tokens // 3))
        next_budget = min(next_budget, available_tokens)
        next_content = truncate_text_to_tokens(content, next_budget)
        return next_content, list(recent)

    def _drop_oldest_recent_turn(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        groups = _semantic_message_groups(recent)
        required = self._required_recent_messages(recent)
        for index, group in enumerate(groups):
            if any(message is required_message for message in required for required_message in group):
                continue
            return content, [message for group in groups[index + 1 :] for message in group]
        return content, list(recent)

    def _truncate_summary(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = self
        high = estimate_text_tokens(content)
        low = 0
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate_content = truncate_text_to_tokens(content, middle)
            candidate = [
                *prefix,
                ChatMessage(role="system", content=candidate_content),
                *recent,
            ]
            if self._estimate_tokens(candidate) <= target_tokens:
                best = candidate_content
                low = middle + 1
            else:
                high = middle - 1
        return best, list(recent)

    @staticmethod
    def _minimal_summary(
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        return "", list(recent)

    def _latest_user_only(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        return "", self._required_recent_messages(recent)


__all__ = [
    "CompactionFitter",
    "MAX_FIT_ATTEMPTS",
    "truncate_text_to_tokens",
]
