---
name: signal
description: Use when time-series data, repeated observations, or changing evidence may contain a trend, anomaly, inflection point, or weak early indicator.
---

# Signal

Sage's **analytical Signal** is a supported interpretation of change. It is distinct from a **Core event Signal**, which is only the normalized event envelope that can wake an Arrange.

## Workflow

1. Define the metric or observation, comparison window, baseline, threshold, expected noise, and decision the signal could affect.
2. Check completeness, sampling changes, units, time zones, revisions, seasonality, missing intervals, and outliers before interpreting movement.
3. Record inputs and transformations under `TRACE_MAP_CONTRACT.md`. Separate observed change from causal explanation or forecast.
4. Search for corroboration, counterevidence, and each plausible false positive. Verify whether the apparent change survives alternative baselines and methods.
5. Report `emerging`, `confirmed`, `noise`, or `indeterminate`, with confidence reasons, conflicts, and the next observation that would update the judgment.

## Continuous mode

A one-time analysis needs no scheduler. Continuous Signal work requires a durable Arrange plus a real schedule or event producer/observer that can obtain the source data. Arrange cannot detect an external source by itself. If ingress, history access, credentials, or delivery is absent, return `blocked` with the missing dependency; never report the monitor as active or successful.
