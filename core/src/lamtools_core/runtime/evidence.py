from __future__ import annotations

from typing import Any


def _state_metadata(state: Any) -> dict[str, Any]:
    metadata = getattr(state, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(state, dict):
        raw = state.get("metadata", state)
        if isinstance(raw, dict):
            return raw
    return {}


def remember_evidence(
    state: Any,
    records: Any,
    *,
    run_id: str,
    turn_id: str,
) -> None:
    if not isinstance(records, list):
        return
    metadata = _state_metadata(state)
    provenance = metadata.get("evidence_provenance")
    if not isinstance(provenance, dict):
        provenance = {"evidence": []}
        metadata["evidence_provenance"] = provenance
    evidence = provenance.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
        provenance["evidence"] = evidence

    known_call_ids = {
        str(item.get("call_id") or "").strip()
        for item in evidence
        if isinstance(item, dict) and str(item.get("call_id") or "").strip()
    }
    for item in records:
        if not isinstance(item, dict):
            continue
        if item.get("evidence_scope") == "turn":
            continue
        call_id = str(item.get("call_id") or "").strip()
        if not call_id or call_id in known_call_ids:
            continue
        evidence.append(
            {
                "call_id": call_id,
                "tool": str(item.get("tool") or ""),
                "category": str(item.get("category") or ""),
                "run_id": run_id,
                "turn_id": turn_id,
            }
        )
        known_call_ids.add(call_id)


def prune_turn_scoped_evidence(
    state: Any,
    *,
    tool_names: set[str] | None = None,
) -> None:
    metadata = _state_metadata(state)
    provenance = metadata.get("evidence_provenance")
    if not isinstance(provenance, dict):
        return
    evidence = provenance.get("evidence")
    if not isinstance(evidence, list):
        return
    scoped_tools = {str(item).strip() for item in (tool_names or set()) if str(item).strip()}
    retained = [
        item
        for item in evidence
        if not (
            isinstance(item, dict)
            and (
                item.get("evidence_scope") == "turn"
                or str(item.get("tool") or "").strip() in scoped_tools
            )
        )
    ]
    if retained:
        provenance["evidence"] = retained
    else:
        metadata.pop("evidence_provenance", None)


def known_evidence_call_ids(state: Any) -> list[str]:
    metadata = _state_metadata(state)
    records: list[Any] = []
    provenance = metadata.get("evidence_provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("evidence"), list):
        records.extend(
            item
            for item in provenance["evidence"]
            if not isinstance(item, dict) or item.get("evidence_scope") != "turn"
        )
    current = metadata.get("member_verification")
    if isinstance(current, dict) and isinstance(current.get("evidence"), list):
        records.extend(
            item
            for item in current["evidence"]
            if not isinstance(item, dict) or item.get("evidence_scope") != "turn"
        )

    call_ids: list[str] = []
    seen: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        call_id = str(item.get("call_id") or "").strip()
        if not call_id or call_id in seen:
            continue
        call_ids.append(call_id)
        seen.add(call_id)
    return call_ids


def evidence_context_metadata(state: Any) -> dict[str, Any]:
    return {"known_evidence_call_ids": known_evidence_call_ids(state)}


__all__ = [
    "evidence_context_metadata",
    "known_evidence_call_ids",
    "prune_turn_scoped_evidence",
    "remember_evidence",
]