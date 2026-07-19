---
name: discover
description: Use when the user wants open-ended discovery of new, emerging, overlooked, or unexpectedly relevant information without naming every target first.
---

# Discover

Explore an open space for candidates the requester did not already name. Rank findings by novelty, relevance, importance, freshness, and plausible impact—not by search rank or popularity alone.

## Workflow

1. Define the discovery horizon, audience, exclusions, and what would count as useful surprise.
2. Explore across distinct source families and actively look for counterevidence, prior art, and reasons a candidate may be noise.
3. Verify each shortlisted candidate before presenting it. Keep tentative leads separate from supported discoveries and record them with `TRACE_MAP_CONTRACT.md`.
4. Return the shortlist, rejected near-matches, confidence reasons, and the next uncertainty worth reducing.

## One run versus continuing discovery

A one-time discovery finishes in the current run. Continuing discovery requires a durable Core Arrange plus a real schedule or event producer. If the event producer, credentials, history query, or observer is absent, Sage **must not claim** that monitoring is active; report the missing ingress as a blocker.
