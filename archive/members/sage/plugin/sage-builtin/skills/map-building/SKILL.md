---
name: map-building
description: Use when research needs durable relationships among documents, entities, concepts, and claims, or when an existing knowledge map needs updating.
---

# Map Building

Build a traceable working map, not a graph-shaped assertion. Read `TRACE_MAP_CONTRACT.md` first and use its document, entity, concept, and claim nodes.

## Workflow

1. Define the map's question and boundary. Reuse stable nodes before creating duplicates.
2. Resolve aliases with identifiers, domains, dates, jurisdiction, or other discriminators. Keep uncertain matches separate.
3. Add evidence-backed edges with evidence IDs and source lineage. A plausible relation without direct support is a `hypothesis`, never a verified edge.
4. Preserve contradictory edges, competing definitions, temporal scope, and unresolved gaps. The map must show disagreement rather than hide it.
5. Validate that every important edge can be followed to an exact source locator and tool call. Return the changed nodes, changed edges, conflicts, and orphaned evidence.

The map helps navigation and synthesis; it does not upgrade the confidence of its own contents.
