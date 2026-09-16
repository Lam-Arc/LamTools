"""Bounded, token-aware fitting of compacted context replacements."""

from __future__ import annotations

import logging
from dataclasses import replace

from lamtools_core.llm import ChatMessage
from lamtools_core.tokens import estimate_text_tokens

from .formatting import append_recent_user_messages, truncate_text_to_tokens
from .models import (
    CompactionBudgetExceeded,
    CompactionFitInput,
    CompactionFitResult,
    CompactionTokenEstimator,
)
_logger = logging.getLogger(__name__)
MAX_FIT_ATTEMPTS = 8


class CompactionFitter:
    """Fit the model summary, optional Step tail, and recent-user suffix.

    Program-appended user originals take precedence over model-summary detail;
    if they cannot all fit, their oldest entries are silently removed while
    the newest entry remains the final safety boundary.
    """

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
        if fit_input.recent_user_messages:
            return self._fit_with_recent_user_suffix(
                fit_input,
                prefix=prefix,
                recent=recent,
                summary_content=summary_content,
            )
        required_recent = self._required_recent_messages(recent)
        required_tokens = self._estimate_tokens([*prefix, *required_recent])
        if required_tokens > fit_input.target_tokens:
            raise CompactionBudgetExceeded(
                "required latest turn/user message exceeds target token budget",
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

        # First shrink the generated summary.  These bounded passes preserve
        # as much of the planner-selected tail as the target allows.
        for strategy, shrink in (
            ("compress_summary_once", self._compress_summary),
            ("compress_summary_twice", self._compress_summary),
            ("truncate_summary", self._truncate_summary),
            ("minimal_summary", self._minimal_summary),
        ):
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

        # If the configured union is still too large, remove the oldest
        # selected unit at a time.  A unit is one non-assistant message or an
        # assistant message with all immediately following tool results.  We
        # keep dropping until the exact target is met, while retaining the
        # newest user message as the final safety boundary.  Drops are local
        # deterministic work and do not consume model calls; ``attempts`` is
        # capped for compatibility with the fitter's bounded public contract.
        while current_tokens > fit_input.target_tokens:
            next_content, next_recent = self._drop_oldest_recent_turn(
                summary_content,
                recent,
                prefix=prefix,
                target_tokens=fit_input.target_tokens,
            )
            if len(next_recent) == len(recent):
                break
            summary_content = next_content
            recent = next_recent
            next_messages = candidate(summary_content, recent)
            next_tokens = self._estimate_tokens(next_messages)
            current_messages = next_messages
            current_tokens = next_tokens
            attempts = min(MAX_FIT_ATTEMPTS, attempts + 1)
            if current_tokens <= fit_input.target_tokens:
                return CompactionFitResult(
                    messages=current_messages,
                    estimated_tokens=current_tokens,
                    attempts=attempts,
                    strategy="drop_oldest_recent_unit",
                )

            # Recompute the largest summary that fits after each drop.  This
            # lets us stop at the first feasible tail instead of jumping
            # straight to latest-user-only and losing newer Steps needlessly.
            truncated_content, _ = self._truncate_summary(
                summary_content,
                recent,
                prefix=prefix,
                target_tokens=fit_input.target_tokens,
            )
            truncated_messages = candidate(truncated_content, recent)
            truncated_tokens = self._estimate_tokens(truncated_messages)
            if truncated_tokens < current_tokens:
                summary_content = truncated_content
                current_messages = truncated_messages
                current_tokens = truncated_tokens
            if current_tokens <= fit_input.target_tokens:
                return CompactionFitResult(
                    messages=current_messages,
                    estimated_tokens=current_tokens,
                    attempts=attempts,
                    strategy="drop_oldest_recent_unit",
                )

        # ``_truncate_summary`` can return an empty summary when only the
        # minimum boundary fits.  Check that candidate explicitly before
        # reporting an over-budget failure.
        minimal_messages = candidate("", recent)
        minimal_tokens = self._estimate_tokens(minimal_messages)
        if minimal_tokens <= fit_input.target_tokens:
            return CompactionFitResult(
                messages=minimal_messages,
                estimated_tokens=minimal_tokens,
                attempts=min(MAX_FIT_ATTEMPTS, max(attempts, 1)),
                strategy="minimal_summary",
            )

        raise CompactionBudgetExceeded(
            "required context remains over the compaction target after bounded fitting",
            estimated_tokens=current_tokens,
            target_tokens=fit_input.target_tokens,
        )

    def _fit_with_recent_user_suffix(
        self,
        fit_input: CompactionFitInput,
        *,
        prefix: list[ChatMessage],
        recent: list[ChatMessage],
        summary_content: str,
    ) -> CompactionFitResult:
        """Fit model summary text while preserving a program-owned suffix."""
        user_messages = list(fit_input.recent_user_messages)

        def candidate(
            content: str,
            retained: list[ChatMessage],
            users: list[str],
        ) -> list[ChatMessage]:
            summary = replace(
                fit_input.summary_message,
                content=append_recent_user_messages(content, users),
            )
            return [*prefix, summary, *retained]

        required_messages = candidate("", [], [user_messages[-1]])
        required_tokens = self._estimate_tokens(required_messages)
        if required_tokens > fit_input.target_tokens:
            raise CompactionBudgetExceeded(
                "required latest turn/user message exceeds target token budget",
                estimated_tokens=required_tokens,
                target_tokens=fit_input.target_tokens,
            )

        strategy = "original"
        attempts = 1
        while self._estimate_tokens(candidate("", recent, user_messages)) > fit_input.target_tokens:
            next_recent = self._drop_oldest_recent_turn(
                "",
                recent,
                prefix=prefix,
                target_tokens=fit_input.target_tokens,
            )[1]
            if len(next_recent) < len(recent):
                recent = next_recent
                strategy = "drop_oldest_recent_unit"
            elif len(user_messages) > 1:
                user_messages.pop(0)
                strategy = "drop_oldest_recent_user"
            else:
                break
            attempts = min(MAX_FIT_ATTEMPTS, attempts + 1)

        full_messages = candidate(summary_content, recent, user_messages)
        full_tokens = self._estimate_tokens(full_messages)
        if full_tokens <= fit_input.target_tokens:
            return CompactionFitResult(
                messages=full_messages,
                estimated_tokens=full_tokens,
                attempts=attempts,
                strategy=strategy,
                recent_user_messages=list(user_messages),
            )

        low = 0
        high = estimate_text_tokens(summary_content)
        best_content = ""
        best_messages = candidate(best_content, recent, user_messages)
        best_tokens = self._estimate_tokens(best_messages)
        while low <= high:
            middle = (low + high) // 2
            next_content = truncate_text_to_tokens(summary_content, middle)
            next_messages = candidate(next_content, recent, user_messages)
            next_tokens = self._estimate_tokens(next_messages)
            if next_tokens <= fit_input.target_tokens:
                best_content = next_content
                best_messages = next_messages
                best_tokens = next_tokens
                low = middle + 1
            else:
                high = middle - 1
        return CompactionFitResult(
            messages=best_messages,
            estimated_tokens=best_tokens,
            attempts=min(MAX_FIT_ATTEMPTS, attempts + 1),
            strategy=(
                "truncate_summary"
                if strategy == "original"
                else f"{strategy}_and_truncate_summary"
            ),
            recent_user_messages=list(user_messages),
        )

    @staticmethod
    def _required_recent_messages(recent: list[ChatMessage]) -> list[ChatMessage]:
        latest_user = next(
            (message for message in reversed(recent) if message.role == "user"),
            None,
        )
        return [latest_user] if latest_user is not None else []

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
        _ = prefix, target_tokens
        units = self._retention_units(recent)
        required = self._required_recent_messages(recent)
        for unit in units:
            if any(message is required_message for required_message in required for message in unit):
                continue
            dropped = {id(message) for message in unit}
            return content, [message for message in recent if id(message) not in dropped]
        return content, list(recent)

    @staticmethod
    def _retention_units(recent: list[ChatMessage]) -> list[list[ChatMessage]]:
        """Return source-ordered drop units, keeping assistant/tool pairs."""
        units: list[list[ChatMessage]] = []
        index = 0
        while index < len(recent):
            message = recent[index]
            unit = [message]
            index += 1
            if message.role == "assistant":
                while index < len(recent) and recent[index].role == "tool":
                    unit.append(recent[index])
                    index += 1
            units.append(unit)
        return units

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
