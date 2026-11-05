//! The projection contract, checked against one file both sides read.
//!
//! `core/android-host/contract/android-host.v1.json` is the single place that says how
//! a journal event must look once it reaches the webview. The Rust side of that
//! contract is asserted here; the interface side is asserted in
//! `core/ui/tests/android-host-event-contract.test.ts`, from the same file.
//!
//! That pairing is the point. A projection test written only in Rust can pass while
//! the screen still shows nothing, because the two sides agree on a shape nobody
//! renders. One file, two readers, no room for a private dialect.

use serde_json::Value;

use super::Projector;

/// The contract, compiled in: a fixture that is not there is a build error rather
/// than a test that quietly finds nothing to check.
const FIXTURE: &str = include_str!("../../../contract/android-host.v1.json");

/// `RunItemEvent.to_dict` vocabulary (`event/run_item.py`). A value outside these is a
/// contract violation, not something the client should learn to tolerate.
const KINDS: &[&str] = &[
    "message",
    "thinking",
    "tool_call",
    "tool_result",
    "approval_request",
    "approval_response",
    "artifact",
    "verification",
    "handoff",
    "usage",
    "error",
    "status",
];
const STATUSES: &[&str] = &[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "skipped",
];

fn scenarios() -> Vec<Value> {
    let spec: Value = serde_json::from_str(FIXTURE).expect("the contract fixture is valid JSON");
    spec["scenarios"]
        .as_array()
        .expect("the contract carries scenarios")
        .clone()
}

/// Projects one scenario's journal events, in order, dropping the ones that carry no
/// rendered meaning.
fn project_scenario(scenario: &Value) -> Vec<Value> {
    let mut projector = Projector::new();
    scenario["given"]
        .as_array()
        .expect("a scenario has inputs")
        .iter()
        .filter_map(|envelope| projector.project(envelope))
        .collect()
}

fn is_iso_utc(text: &str) -> bool {
    let bytes = text.as_bytes();
    bytes.len() == 24
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes[10] == b'T'
        && bytes[13] == b':'
        && bytes[16] == b':'
        && bytes[19] == b'.'
        && bytes[23] == b'Z'
        && bytes.iter().enumerate().all(|(index, byte)| {
            matches!(index, 4 | 7 | 10 | 13 | 16 | 19 | 23) || byte.is_ascii_digit()
        })
}

/// Compares an expected subset against what was produced.
///
/// Subset, not equality: the event vocabulary is append-only, so a producer that
/// later adds a field must not fail the contract. Every key the contract names is
/// still pinned, which is what keeps the two readings of the file honest.
fn check(expect: &Value, actual: &Value, path: &str, problems: &mut Vec<String>) {
    match expect {
        Value::Object(map) => {
            let Some(object) = actual.as_object() else {
                problems.push(format!("{path}: expected an object, got {actual}"));
                return;
            };
            for (key, want) in map {
                let child = format!("{path}.{key}");
                if want == &Value::String("$absent".to_owned()) {
                    if let Some(found) = object.get(key) {
                        problems.push(format!("{child}: must be absent, found {found}"));
                    }
                    continue;
                }
                match object.get(key) {
                    Some(got) => check(want, got, &child, problems),
                    None => problems.push(format!("{child}: missing")),
                }
            }
        }
        Value::Array(want_items) => {
            let Some(got_items) = actual.as_array() else {
                problems.push(format!("{path}: expected an array, got {actual}"));
                return;
            };
            if want_items.len() != got_items.len() {
                problems.push(format!(
                    "{path}: expected {} entries, got {} ({actual})",
                    want_items.len(),
                    got_items.len()
                ));
                return;
            }
            for (index, (want, got)) in want_items.iter().zip(got_items).enumerate() {
                check(want, got, &format!("{path}[{index}]"), problems);
            }
        }
        Value::String(marker) => match marker.as_str() {
            "$any" => {
                if actual.is_null() {
                    problems.push(format!("{path}: must carry a value, found null"));
                }
            }
            "$iso" => match actual.as_str() {
                Some(text) if is_iso_utc(text) => {}
                _ => problems.push(format!(
                    "{path}: expected an ISO-8601 UTC timestamp, got {actual}"
                )),
            },
            "$epoch_ms" => {
                let ok = actual
                    .as_u64()
                    .map(|value| value > 1_600_000_000_000)
                    .unwrap_or(false);
                if !ok {
                    problems.push(format!("{path}: expected epoch milliseconds, got {actual}"));
                }
            }
            _ => {
                if actual != expect {
                    problems.push(format!("{path}: expected {expect}, got {actual}"));
                }
            }
        },
        _ => {
            if actual != expect {
                problems.push(format!("{path}: expected {expect}, got {actual}"));
            }
        }
    }
}

#[test]
fn the_host_projects_the_shared_event_contract() {
    let mut problems = Vec::new();
    for scenario in scenarios() {
        let name = scenario["name"].as_str().unwrap_or("unnamed scenario");
        let produced = project_scenario(&scenario);
        let expected = scenario["expect"]
            .as_array()
            .expect("a scenario says what to expect");
        if produced.len() != expected.len() {
            let seen: Vec<String> = produced
                .iter()
                .map(|item| {
                    format!(
                        "{}:{}",
                        item["payload"]["kind"].as_str().unwrap_or("?"),
                        item["payload"]["item_id"].as_str().unwrap_or("?")
                    )
                })
                .collect();
            problems.push(format!(
                "{name}: expected {} event(s), projected {} [{}]",
                expected.len(),
                produced.len(),
                seen.join(", ")
            ));
            continue;
        }
        for (index, (want, got)) in expected.iter().zip(produced.iter()).enumerate() {
            check(want, got, &format!("{name} → event {index}"), &mut problems);
        }
    }
    assert!(
        problems.is_empty(),
        "the projection broke the shared contract:\n  {}",
        problems.join("\n  ")
    );
}

/// Invariants that hold for every projected item, whatever the scenario.
///
/// These are the ones a fixture is easy to under-specify: a status the client cannot
/// interpret, or a timestamp that parses as 1970, would slip through a scenario that
/// simply did not mention the field.
#[test]
fn every_projected_item_is_domain_valid() {
    let mut problems = Vec::new();
    for scenario in scenarios() {
        let name = scenario["name"].as_str().unwrap_or("unnamed scenario");
        for item in project_scenario(&scenario) {
            let path = name.to_owned();
            if item["method"] != "core/runItem" {
                problems.push(format!("{path}: method must be core/runItem"));
            }
            let kind = item["payload"]["kind"].as_str().unwrap_or("");
            if !KINDS.contains(&kind) {
                problems.push(format!(
                    "{path}: kind {kind:?} is outside the run-item domain"
                ));
            }
            let status = item["payload"]["status"].as_str().unwrap_or("");
            if !STATUSES.contains(&status) {
                problems.push(format!(
                    "{path}: status {status:?} is outside the run-item domain"
                ));
            }
            match item["created_at"].as_str() {
                Some(text) if is_iso_utc(text) => {}
                other => problems.push(format!("{path}: created_at {other:?} is not a timestamp")),
            }
            let created_at_ms = item["payload"]["created_at_ms"].as_u64().unwrap_or(0);
            if created_at_ms <= 1_600_000_000_000 {
                problems.push(format!(
                    "{path}: created_at_ms {created_at_ms} is not a real instant"
                ));
            }
            if item["payload"]["payload"].is_null() {
                problems.push(format!(
                    "{path}: an item without a payload renders as a blank row"
                ));
            }
            // The interface side of this contract lifts identity from the payload onto
            // the envelope. That is only sound while both agree, so it is checked here
            // rather than assumed there.
            for field in ["event_id", "turn_id", "item_id"] {
                if item[field] != item["payload"][field] {
                    problems.push(format!(
                        "{path}: envelope {field} {:?} disagrees with the payload's {:?}",
                        item[field], item["payload"][field]
                    ));
                }
            }
        }
    }
    assert!(
        problems.is_empty(),
        "projected items are outside the contract:\n  {}",
        problems.join("\n  ")
    );
}
