from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import OfficeIssue


SUPPORTED_BINDINGS = {
    "pptx_table",
    "pptx_chart",
    "docx_table",
    "xlsx_range",
    "xlsx_chart",
}


@dataclass(frozen=True, slots=True)
class ManifestValidation:
    manifest: dict[str, Any]
    source_path: Path | None
    source_hash: str | None
    issues: tuple[OfficeIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    path = Path(value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Office manifest root must be a JSON object")
    return payload


def validate_manifest_shape(
    manifest_value: Mapping[str, Any] | str | Path,
    *,
    source_override: str | Path | None = None,
) -> ManifestValidation:
    manifest_base: Path | None = None
    if not isinstance(manifest_value, Mapping):
        manifest_base = Path(manifest_value).expanduser().resolve().parent
    try:
        manifest = load_manifest(manifest_value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ManifestValidation({}, None, None, (_issue("manifest_invalid", str(exc)),))

    issues: list[OfficeIssue] = []
    if manifest.get("schema_version") != 1:
        issues.append(_issue("schema_version_unsupported", "schema_version must be 1", expected=1, actual=manifest.get("schema_version")))

    source = manifest.get("source")
    source_path: Path | None = Path(source_override).resolve() if source_override else None
    expected_hash: str | None = None
    if not isinstance(source, Mapping):
        issues.append(_issue("source_missing", "source must contain path and sha256"))
    else:
        raw_path = source.get("path")
        expected_hash = source.get("sha256")
        if source_path is None and isinstance(raw_path, str) and raw_path.strip():
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute() and manifest_base is not None:
                candidate = manifest_base / candidate
            source_path = candidate.resolve()
        if source_path is None:
            issues.append(_issue("source_path_missing", "source.path is required"))
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_hash):
            issues.append(_issue("source_hash_invalid", "source.sha256 must be a 64-character hexadecimal digest", actual=expected_hash))

    datasets = manifest.get("datasets")
    normalized_datasets: dict[str, Any] = {}
    if isinstance(datasets, Mapping):
        normalized_datasets = {str(key): value for key, value in datasets.items()}
    elif isinstance(datasets, Sequence) and not isinstance(datasets, (str, bytes)):
        for index, item in enumerate(datasets):
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                issues.append(_issue("dataset_invalid", "dataset entries require a string id", location={"dataset_index": index}))
                continue
            normalized_datasets[item["id"]] = item
    else:
        issues.append(_issue("datasets_invalid", "datasets must be an object or array"))
    manifest["datasets"] = normalized_datasets

    for dataset_id, dataset in normalized_datasets.items():
        _validate_dataset(dataset_id, dataset, issues)

    bindings = manifest.get("bindings")
    if not isinstance(bindings, list):
        issues.append(_issue("bindings_invalid", "bindings must be an array"))
        bindings = []
    seen: set[str] = set()
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            issues.append(_issue("binding_invalid", "binding must be an object", location={"binding_index": index}))
            continue
        binding_id = binding.get("id")
        kind = binding.get("type")
        dataset_id = binding.get("dataset")
        target = binding.get("target")
        if not isinstance(binding_id, str) or not binding_id.strip():
            issues.append(_issue("binding_id_missing", "binding.id is required", location={"binding_index": index}))
        elif binding_id in seen:
            issues.append(_issue("binding_id_duplicate", "binding.id must be unique", binding=binding_id))
        else:
            seen.add(binding_id)
        if not isinstance(kind, str) or kind not in SUPPORTED_BINDINGS:
            issues.append(_issue("binding_type_unsupported", "unsupported binding type", binding=_text(binding_id), expected=sorted(SUPPORTED_BINDINGS), actual=kind))
        if not isinstance(dataset_id, str) or dataset_id not in normalized_datasets:
            issues.append(_issue("binding_dataset_missing", "binding references an unknown dataset", binding=_text(binding_id), expected=sorted(normalized_datasets), actual=dataset_id))
        if not isinstance(target, Mapping):
            issues.append(_issue("binding_target_invalid", "binding.target must be an object", binding=_text(binding_id), actual=target))
        tolerance = binding.get("tolerance", manifest.get("tolerance"))
        _validate_tolerance(tolerance, issues, _text(binding_id))

    overlaps = manifest.get("allow_overlaps", [])
    if not isinstance(overlaps, list):
        issues.append(_issue("allow_overlaps_invalid", "allow_overlaps must be an array of scoped target objects", actual=overlaps))
    else:
        for index, scope in enumerate(overlaps):
            valid = (
                isinstance(scope, Mapping)
                and isinstance(scope.get("page"), int)
                and scope["page"] > 0
                and isinstance(scope.get("elements"), list)
                and len(scope["elements"]) == 2
                and all(isinstance(item, str) and item for item in scope["elements"])
            )
            if not valid:
                issues.append(_issue("allow_overlap_scope_invalid", "overlap exceptions require a positive page and exactly two element IDs", location={"allow_overlap_index": index}, actual=scope))
    non_data = manifest.get("non_data_targets", [])
    if not isinstance(non_data, list):
        issues.append(_issue("non_data_targets_invalid", "non_data_targets must be an array of scoped targets", actual=non_data))
    else:
        for index, scope in enumerate(non_data):
            scope_type = scope.get("type") if isinstance(scope, Mapping) else None
            if not isinstance(scope, Mapping) or not isinstance(scope_type, str) or scope_type not in SUPPORTED_BINDINGS or not isinstance(scope.get("target"), Mapping) or not scope["target"]:
                issues.append(_issue("non_data_target_scope_invalid", "non-data declarations require a supported type and non-empty target", location={"non_data_index": index}, actual=scope))

    actual_hash: str | None = None
    if source_path is not None:
        if not source_path.is_file():
            issues.append(_issue("source_not_found", "source file does not exist", actual=str(source_path)))
        else:
            actual_hash = sha256_file(source_path)
            if isinstance(expected_hash, str) and actual_hash.casefold() != expected_hash.casefold():
                issues.append(_issue("source_hash_mismatch", "source file hash differs from manifest", expected=expected_hash.lower(), actual=actual_hash))

    return ManifestValidation(manifest, source_path, actual_hash, tuple(issues))


def _validate_dataset(dataset_id: str, dataset: Any, issues: list[OfficeIssue]) -> None:
    if not isinstance(dataset, Mapping):
        issues.append(_issue("dataset_invalid", "dataset must be an object", location={"dataset": dataset_id}))
        return
    columns = dataset.get("columns")
    rows = dataset.get("rows")
    if not isinstance(columns, list) or not columns:
        issues.append(_issue("dataset_columns_invalid", "dataset.columns must be a non-empty array", location={"dataset": dataset_id}))
        return
    names: list[str] = []
    for index, column in enumerate(columns):
        if isinstance(column, str):
            name = column
        elif isinstance(column, Mapping):
            name = column.get("name")
            declared_type = column.get("type")
            if declared_type is not None and declared_type not in {"string", "number", "integer", "boolean", "date", "datetime", "null", "any"}:
                issues.append(_issue("dataset_column_type_invalid", "unsupported column type", location={"dataset": dataset_id, "column": index}, actual=declared_type))
            unit = column.get("unit")
            if unit is not None and not isinstance(unit, str):
                issues.append(_issue("dataset_column_unit_invalid", "column unit must be a string", location={"dataset": dataset_id, "column": index}, actual=unit))
        else:
            name = None
        if not isinstance(name, str) or not name:
            issues.append(_issue("dataset_column_invalid", "column requires a non-empty name", location={"dataset": dataset_id, "column": index}))
        else:
            names.append(name)
    if len(set(names)) != len(names):
        issues.append(_issue("dataset_columns_duplicate", "column names must be unique", location={"dataset": dataset_id}, actual=names))
    if not isinstance(rows, list):
        issues.append(_issue("dataset_rows_invalid", "dataset.rows must be an array", location={"dataset": dataset_id}))
        return
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            issues.append(_issue("dataset_row_width_mismatch", "row width must equal column count", location={"dataset": dataset_id, "row": row_index}, expected=len(columns), actual=None if not isinstance(row, list) else len(row)))
            continue
        for column_index, value in enumerate(row):
            spec = columns[column_index]
            declared = spec.get("type") if isinstance(spec, Mapping) else None
            if declared and declared != "any" and not _matches_type(value, declared):
                issues.append(_issue("dataset_value_type_mismatch", "dataset value does not match declared type", location={"dataset": dataset_id, "row": row_index, "column": column_index}, expected=declared, actual=type(value).__name__))


def _matches_type(value: Any, declared: str) -> bool:
    if value is None:
        return declared == "null"
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared in {"date", "datetime"}:
        return isinstance(value, str)
    return True


def _validate_tolerance(value: Any, issues: list[OfficeIssue], binding: str | None) -> None:
    if not isinstance(value, Mapping):
        issues.append(_issue("tolerance_invalid", "tolerance must contain absolute and relative", binding=binding, actual=value))
        return
    for key in ("absolute", "relative"):
        number = value.get(key, 0.0)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or not math.isfinite(float(number)) or number < 0:
            issues.append(_issue("tolerance_invalid", f"tolerance.{key} must be a finite non-negative number", binding=binding, actual=number))


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _issue(code: str, message: str, **kwargs: Any) -> OfficeIssue:
    return OfficeIssue(code=code, message=message, **kwargs)
