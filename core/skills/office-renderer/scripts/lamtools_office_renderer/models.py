from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
import math
from pathlib import Path
from typing import Any, Literal, Mapping


Status = Literal["passed", "failed", "unavailable", "not_run"]


@dataclass(frozen=True, slots=True)
class OfficeIssue:
    code: str
    message: str
    binding: str | None = None
    target: dict[str, Any] | None = None
    page: int | None = None
    location: dict[str, Any] | None = None
    expected: Any = None
    actual: Any = None
    kind: str | None = None
    elements: tuple[str, ...] = ()
    texts: tuple[str, ...] = ()
    bboxes: tuple[tuple[float, float, float, float], ...] = ()
    intersection: tuple[float, float, float, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["elements"] = list(self.elements)
        value["texts"] = list(self.texts)
        value["bboxes"] = [list(box) for box in self.bboxes]
        if self.intersection is not None:
            value["intersection"] = list(self.intersection)
        return _json_value(value)


@dataclass(frozen=True, slots=True)
class BackendInfo:
    name: str
    version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OfficeRenderReport:
    schema_version: int
    input_path: str
    input_sha256: str
    backend: BackendInfo | None
    pdf_path: str | None
    png_paths: list[str]
    data_status: Status
    structure_status: Status
    visual_status: Status
    issues: list[OfficeIssue] = field(default_factory=list)
    text_diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.data_status == "passed"
            and self.structure_status == "passed"
            and self.visual_status in {"passed", "not_run"}
        )

    @property
    def exit_class(self) -> str:
        if self.data_status == "failed":
            return "data_mismatch"
        if self.structure_status == "failed":
            return "structure_invalid"
        if self.visual_status == "unavailable":
            return "visual_unavailable"
        if self.visual_status == "failed":
            return "visual_issue"
        return "success"

    def as_dict(self) -> dict[str, Any]:
        return _json_value({
            "schema_version": self.schema_version,
            "ok": self.ok,
            "exit_class": self.exit_class,
            "input": {"path": self.input_path, "sha256": self.input_sha256},
            "backend": None if self.backend is None else self.backend.as_dict(),
            "outputs": {"pdf": self.pdf_path, "pngs": list(self.png_paths)},
            "statuses": {
                "data": self.data_status,
                "structure": self.structure_status,
                "visual": self.visual_status,
            },
            "issues": [issue.as_dict() for issue in self.issues],
            "text_diagnostics": list(self.text_diagnostics),
        })


class OfficeRendererError(RuntimeError):
    """Base error for process/infrastructure failures."""


class OfficeBackendUnavailable(OfficeRendererError):
    pass


class OfficeRenderTimeout(OfficeRendererError):
    pass


def normalized_path(path: Path) -> str:
    return str(path.resolve())


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)
