//! The first real task, run through the real runner.
//!
//! "Create notes.md with three lines" is the acceptance case for Sunday M. Until now it
//! was only ever checked on a device: build the APK, install, type, look at a screenshot.
//! That answers "does Android work" and nothing about whether the host is correct, and it
//! costs a build every time.
//!
//! Everything here is the production path: `CoreRunner` as `lib.rs` assembles it, the real
//! store, the real turn loop, the real `write_file` tool, the real approval gate, the real
//! journal, and the same `event_json` framing the server uses before the projector sees a
//! frame. The only substitution is the model. A live model answers differently each run,
//! which makes it unable to decide whether the host is right; it belongs in the device
//! acceptance, not here.

use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use sunday_host::app_server::{event_json, BridgeEvent, TurnRunner};
use sunday_host::policy::GrantPolicy;
use sunday_host::runner::{CoreOptions, CoreRunner};
use sunday_protocol::{
    CoreError, HostKind, Model, ModelDelta, ModelRequest, ModelTurn, Prepared, SideEffect, ToolCall,
};
use sunday_store::Store;

use crate::projection::Projector;

const THREAD: &str = "th";
const PROMPT: &str = "Create notes.md with three lines: goal, progress, tomorrow.";

/// Answers with a fixed list of model turns, in order.
struct ScriptedModel {
    turns: Mutex<Vec<ModelTurn>>,
}

impl ScriptedModel {
    fn new(turns: Vec<ModelTurn>) -> Self {
        Self {
            turns: Mutex::new(turns),
        }
    }
}

#[async_trait::async_trait]
impl Model for ScriptedModel {
    async fn stream(
        &self,
        _request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        let turn = self.turns.lock().unwrap().remove(0);
        if let Some(text) = &turn.text {
            sink(ModelDelta::Text(text.clone()));
        }
        Ok(turn)
    }
}

fn write_call(call_id: &str, path: &str, content: &str) -> ModelTurn {
    ModelTurn {
        text: Some("Writing the file.".into()),
        reasoning: None,
        tool_calls: vec![ToolCall {
            id: call_id.into(),
            name: "write_file".into(),
            args: json!({ "path": path, "content": content }),
        }],
        usage: None,
        provider_state: None,
    }
}

fn text_turn(text: &str) -> ModelTurn {
    ModelTurn {
        text: Some(text.into()),
        reasoning: None,
        tool_calls: Vec::new(),
        usage: None,
        provider_state: None,
    }
}

/// Wired the way `lib.rs` wires it, minus the Tauri handle.
fn runner(dir: &std::path::Path, turns: Vec<ModelTurn>) -> CoreRunner {
    let workspace = dir.join("workspace");
    std::fs::create_dir_all(&workspace).unwrap();
    CoreRunner::new(CoreOptions {
        store: Store::open(&dir.join("core.db")).unwrap(),
        model: Arc::new(ScriptedModel::new(turns)),
        model_id: "scripted".into(),
        workspace: workspace.to_string_lossy().into_owned(),
        host_kind: HostKind::Android,
        // The host's default: reads run, anything with a side effect asks. A test that
        // pre-granted the write would skip the half of the loop the user performs.
        policy: GrantPolicy::read_only(),
        system: Some("You are Sunday.".into()),
    })
}

/// Collects the frames the server would have sent to the webview.
fn recorder() -> (Arc<Mutex<Vec<Value>>>, impl Fn(BridgeEvent) + Send + Sync) {
    let frames = Arc::new(Mutex::new(Vec::new()));
    let sink = {
        let frames = Arc::clone(&frames);
        move |event: BridgeEvent| {
            frames.lock().unwrap().push(event_json(THREAD, &event));
        }
    };
    (frames, sink)
}

/// A sink that throws the frames away, for a test that only cares what happened on disk.
fn sink_none() -> impl Fn(BridgeEvent) + Send + Sync {
    |_event: BridgeEvent| {}
}

fn frames_of(frames: &Arc<Mutex<Vec<Value>>>, method: &str) -> Vec<Value> {
    frames
        .lock()
        .unwrap()
        .iter()
        .filter(|frame| frame["method"] == method)
        .cloned()
        .collect()
}

#[test]
fn the_first_task_writes_the_file_it_promised() {
    let dir = tempfile::tempdir().unwrap();
    let workspace = dir.path().join("workspace");
    let runner = runner(
        dir.path(),
        vec![
            write_call("call-1", "notes.md", "goal\nprogress\ntomorrow"),
            text_turn("Created notes.md with the three lines."),
        ],
    );
    let (frames, sink) = recorder();

    runner.start_turn(THREAD, PROMPT, "cm-1", &sink).unwrap();

    assert_eq!(
        frames_of(&frames, "turn/accepted").len(),
        1,
        "the instruction never reached the transcript"
    );
    let asking = frames_of(&frames, "item/approval_request");
    assert_eq!(asking.len(), 1, "a write must ask before it happens");
    assert_eq!(
        asking[0]["payload"]["tool_call_id"], "call-1",
        "the card is not attached to the call it is asking about"
    );
    let request_id = asking[0]["payload"]["request_id"]
        .as_str()
        .expect("the card carries no request id")
        .to_owned();
    assert!(
        !workspace.join("notes.md").exists(),
        "the file was written before the user answered"
    );

    // The gate the user's own click goes through, not a shortcut around it.
    runner.check_approval(&request_id).unwrap();
    runner
        .respond(THREAD, &request_id, "approve", "", &sink)
        .unwrap();

    assert_eq!(
        std::fs::read_to_string(workspace.join("notes.md")).unwrap(),
        "goal\nprogress\ntomorrow",
        "approving the card did not produce the file"
    );

    let completed = frames_of(&frames, "item/completed");
    let result = completed
        .iter()
        .find(|frame| frame["payload"]["tool_call_id"] == "call-1")
        .expect("the write never reported a result");
    let reported: Value =
        serde_json::from_str(result["payload"]["content"].as_str().unwrap()).unwrap();
    assert_eq!(reported["ok"], true);
    assert_eq!(reported["path"], "notes.md");
    assert!(
        !frames_of(&frames, "turn/completed").is_empty(),
        "the turn never finished"
    );
}

/// The same stream, read the way the interface reads it.
///
/// The host can emit perfectly good journal events that the screen cannot draw. This is
/// the assertion that ties the two without a device in the middle.
#[test]
fn the_stream_draws_a_card_and_then_a_file() {
    let dir = tempfile::tempdir().unwrap();
    let runner = runner(
        dir.path(),
        vec![
            write_call("call-1", "notes.md", "goal\nprogress\ntomorrow"),
            text_turn("Created notes.md."),
        ],
    );
    let (frames, sink) = recorder();
    runner.start_turn(THREAD, PROMPT, "cm-1", &sink).unwrap();
    let request_id = frames_of(&frames, "item/approval_request")[0]["payload"]["request_id"]
        .as_str()
        .expect("no approval request reached the screen")
        .to_owned();
    runner
        .respond(THREAD, &request_id, "approve", "", &sink)
        .unwrap();

    let mut projector = Projector::new();
    let mut items = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for frame in frames.lock().unwrap().iter() {
        // `respond` replays the journal from the beginning so a reconnecting client can
        // catch up. Identity is what lets the client keep one copy, so this test drops
        // copies by exactly that rule rather than by seq.
        let identity = format!(
            "{}|{}",
            frame["event_id"].as_str().unwrap_or_default(),
            frame["method"]
        );
        if !seen.insert(identity) {
            continue;
        }
        if let Some(item) = projector.project(frame) {
            items.push(item);
        }
    }

    let card = items
        .iter()
        .find(|item| item["payload"]["kind"] == "approval_request")
        .expect("the card did not survive projection");
    assert_eq!(
        card["payload"]["payload"]["request_id"],
        request_id.as_str()
    );
    assert_eq!(
        card["payload"]["payload"]["options"]
            .as_array()
            .map(Vec::len),
        Some(2),
        "a card with no options is a card nobody can answer"
    );

    let file = items
        .iter()
        .find(|item| {
            item["payload"]["kind"] == "tool_result"
                && item["payload"]["artifacts"]
                    .as_array()
                    .map(|artifacts| artifacts.iter().any(|a| a["name"] == "notes.md"))
                    .unwrap_or(false)
        })
        .expect("the written file never became an artifact the screen can open");
    assert_eq!(file["payload"]["status"], "completed");
    assert!(
        file["payload"]["payload"]["artifacts"].is_null(),
        "the artifact is inside the payload, where the client does not look"
    );
}

/// A second turn must be a second turn.
///
/// Turns were once all named `turn-0`. The journal event id is derived from the turn id,
/// so a later turn's `run_started` arrived with an id the store already held and was
/// dropped as a duplicate: the screen never learned that turn had begun.
#[test]
fn a_second_turn_gets_its_own_identity() {
    let dir = tempfile::tempdir().unwrap();
    let runner = runner(
        dir.path(),
        vec![text_turn("first reply"), text_turn("second reply")],
    );
    let (frames, sink) = recorder();

    runner.start_turn(THREAD, "first", "cm-1", &sink).unwrap();
    runner.start_turn(THREAD, "second", "cm-2", &sink).unwrap();

    let starts = frames_of(&frames, "turn/started");
    assert_eq!(starts.len(), 2, "a turn did not start");
    assert_ne!(
        starts[0]["payload"]["turn_id"], starts[1]["payload"]["turn_id"],
        "two turns share one identity, so the second cannot be told apart"
    );
    assert_eq!(
        frames_of(&frames, "turn/model_completed").len(),
        2,
        "the second reply never reached the stream"
    );
}

/// A replayed fact must be recognisable as the same fact.
///
/// The whole resume path rests on this: the journal is replayed, and the client drops
/// what it has already applied by event id. Two ids for one fact shows it twice; one id
/// for two facts loses one of them.
#[test]
fn replayed_facts_keep_one_identity() {
    let dir = tempfile::tempdir().unwrap();
    let runner = runner(
        dir.path(),
        vec![
            write_call("call-1", "notes.md", "goal\nprogress\ntomorrow"),
            text_turn("Created notes.md."),
        ],
    );
    let (frames, sink) = recorder();
    runner.start_turn(THREAD, PROMPT, "cm-1", &sink).unwrap();
    let request_id = frames_of(&frames, "item/approval_request")[0]["payload"]["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    runner
        .respond(THREAD, &request_id, "approve", "", &sink)
        .unwrap();

    let frames = frames.lock().unwrap().clone();
    // Each (event id, method) pair is one fact. A pair appearing twice is the replay.
    let mut by_identity: std::collections::HashMap<(String, String), Vec<Value>> =
        std::collections::HashMap::new();
    for frame in &frames {
        let identity = (
            frame["event_id"].as_str().unwrap_or_default().to_owned(),
            frame["method"].as_str().unwrap_or_default().to_owned(),
        );
        by_identity.entry(identity).or_default().push(frame.clone());
    }
    assert!(
        by_identity.values().any(|copies| copies.len() > 1),
        "the journal was not replayed, so this test proves nothing about dedupe"
    );
    for ((event_id, method), copies) in &by_identity {
        assert!(!event_id.is_empty(), "{method} carries no event id");
        let first = copies[0]["payload"].to_string();
        for copy in &copies[1..] {
            assert_eq!(
                copy["payload"].to_string(),
                first,
                "one event id describes two different {method} facts"
            );
            // A replay is not when the fact happened. The journal row knows; inventing
            // the projection time instead made last week's message look like it was sent
            // the moment the app was reopened.
            assert_eq!(
                copy["created_at_ms"], copies[0]["created_at_ms"],
                "{method} reports a different time when replayed"
            );
        }
        let stamp = copies[0]["created_at"].as_str().unwrap_or_default();
        assert!(
            stamp.len() == 24 && stamp.ends_with('Z'),
            "{method} carries no real timestamp: {stamp:?}"
        );
    }
}

/// A write that died mid flight must be reported, and must never run again by itself.
///
/// This is the one failure a file-writing agent must not get wrong in either direction.
/// Calling it finished tells the user their file is there when nobody knows; running it
/// again rewrites a file the user may have since changed. The store classifies the call
/// and refuses to prepare it a second time, which every retry path has to go through, so
/// the guarantee is in the data rather than in a caller remembering to check.
#[test]
fn a_write_that_died_mid_flight_is_reported_and_never_redone() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("core.db");
    let workspace = dir.path().join("workspace");
    std::fs::create_dir_all(&workspace).unwrap();

    let call = ToolCall {
        id: "call-crashed".into(),
        name: "write_file".into(),
        args: json!({ "path": "notes.md", "content": "was this written?" }),
    };

    // A process that got as far as the side effect and then died: the intent is durable
    // and the answer never arrived, because nothing had the chance to record one.
    {
        let mut store = Store::open(&db).unwrap();
        assert_eq!(
            store
                .prepare_tool_once(THREAD, &call, SideEffect::NonIdempotent)
                .unwrap(),
            Prepared::Ready
        );
        store.mark_dispatched(&call.id).unwrap();
    }

    // Before anything classifies it, the retry gate already refuses: a dispatched call
    // with a side effect is not "ready", whatever a caller hopes.
    {
        let mut store = Store::open(&db).unwrap();
        assert_eq!(
            store
                .prepare_tool_once(THREAD, &call, SideEffect::NonIdempotent)
                .unwrap(),
            Prepared::MustReconcile,
            "a dispatched write was offered for another run"
        );
    }
    assert!(
        !workspace.join("notes.md").exists(),
        "the crashed write was replayed"
    );

    // The next launch says so instead of guessing either way.
    let runner = runner(
        dir.path(),
        vec![text_turn("I cannot tell whether that file was written.")],
    );
    let plan = runner.recovery().unwrap();
    assert_eq!(
        plan.unknown,
        vec![call.id.clone()],
        "a dispatched write with no answer was reported as fine"
    );

    // The thread is still usable afterwards, and its journal still reads back.
    runner
        .start_turn(THREAD, "what happened to notes.md?", "cm-1", &sink_none())
        .unwrap();
    assert!(
        !workspace.join("notes.md").exists(),
        "starting a new turn re-ran the crashed write"
    );
    assert!(
        !runner.events(THREAD, 0).unwrap().is_empty(),
        "history did not survive the crash"
    );
}

/// Closing the app and opening it again must restore what was there.
///
/// The transcript is rebuilt from the journal alone, so this is the whole restore path:
/// a second runner over the same database, reading history, then projecting it. What it
/// must not do is leave the answered card answerable or lose the file it reported.
#[test]
fn a_new_process_restores_the_transcript_it_left() {
    let dir = tempfile::tempdir().unwrap();
    {
        let runner = runner(
            dir.path(),
            vec![
                write_call("call-1", "notes.md", "goal\nprogress\ntomorrow"),
                text_turn("Created notes.md."),
            ],
        );
        let (frames, sink) = recorder();
        runner.start_turn(THREAD, PROMPT, "cm-1", &sink).unwrap();
        let request_id = frames_of(&frames, "item/approval_request")[0]["payload"]["request_id"]
            .as_str()
            .unwrap()
            .to_owned();
        runner
            .respond(THREAD, &request_id, "approve", "", &sink)
            .unwrap();
    } // the process ends here

    let restored = runner(dir.path(), Vec::new());
    let page = restored.history(THREAD, None, 100).unwrap();
    assert!(
        page.events.len() >= 5,
        "the journal came back with {} events",
        page.events.len()
    );
    for event in &page.events {
        assert!(
            event.created_at_ms.is_some_and(|ms| ms > 1_600_000_000_000),
            "{} came back without the time it happened",
            event.method
        );
    }
    assert!(
        !restored.has_pending_approval(THREAD).unwrap(),
        "an answered card came back answerable"
    );

    let mut projector = Projector::new();
    let items: Vec<Value> = page
        .events
        .iter()
        .map(|event| event_json(THREAD, event))
        .filter_map(|frame| projector.project(&frame))
        .collect();
    assert!(
        items
            .iter()
            .any(|item| item["payload"]["kind"] == "approval_response"),
        "the restored transcript forgot the card was answered"
    );
    assert!(
        items.iter().any(|item| item["payload"]["artifacts"]
            .as_array()
            .map(|artifacts| artifacts.iter().any(|a| a["name"] == "notes.md"))
            .unwrap_or(false)),
        "the restored transcript lost the file it reported"
    );
}

/// The runner is the same instance for the process lifetime; this only pins that it can
/// be built once and reused, which the host depends on when a turn ends and another starts.
#[test]
fn one_runner_serves_a_second_turn_after_the_first() {
    let dir = tempfile::tempdir().unwrap();
    let runner = runner(
        dir.path(),
        vec![
            write_call("call-1", "notes.md", "one"),
            text_turn("done"),
            text_turn("second answer"),
        ],
    );
    let (frames, sink) = recorder();
    runner.start_turn(THREAD, "first", "cm-1", &sink).unwrap();
    let request_id = frames_of(&frames, "item/approval_request")[0]["payload"]["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    runner
        .respond(THREAD, &request_id, "approve", "", &sink)
        .unwrap();
    assert!(dir.path().join("workspace/notes.md").exists());

    runner.start_turn(THREAD, "second", "cm-2", &sink).unwrap();
    let replies = frames_of(&frames, "turn/model_completed");
    assert!(replies.len() >= 2, "the second turn produced no reply");
}
