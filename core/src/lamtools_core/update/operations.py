"""Operation catalog for the ``update.*`` RPCs (GUI / CLI shared entry points)."""

from __future__ import annotations

from typing import Any

from lamtools_core.app.operation_catalog import (
    OperationCatalog,
    OperationRequest,
    OperationResult,
)
from lamtools_core.update.checker import check_update


def build_update_operation_catalog() -> OperationCatalog:
    """Build an OperationCatalog exposing ``update.check``.

    The result mirrors :func:`lamtools_core.update.checker.check_update`:
    ``status`` is one of ``update_available`` / ``up_to_date`` / ``check_failed``.
    """

    catalog = OperationCatalog()

    async def update_check(request: OperationRequest) -> OperationResult:
        del request  # no payload expected
        payload: dict[str, Any] = check_update()
        return OperationResult(name="update.check", payload=payload)

    catalog.register("update.check", update_check)
    return catalog


__all__ = ["build_update_operation_catalog"]
