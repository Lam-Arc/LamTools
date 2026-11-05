//! Protocol contract tests.
//!
//! These tests speak to the adapter over a real WebSocket with frames copied
//! from what `core/ui/src/appServer/client.ts` and `store.ts` actually send. A
//! test that invents its own field names would pass while the real UI fails.

use std::net::TcpStream;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use sunday_host::app_server::{event_json, iso_utc, AppServer, BridgeEvent, EventSink, TurnRunner};

type Socket = tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<TcpStream>>;

/// A runner that records calls and replays a fixed script, so the test can
/// assert protocol behaviour without a model.
#[derive(Default)]
struct Recorder {
    calls: Mutex<Vec<String>>,
    seq: AtomicU64,
    /// Set by `cancel`; a streaming start_turn watches it.
    cancelled: Mutex<bool>,
}

impl Recorder {
    fn next(&self) -> u64 {
        self.seq.fetch_add(1, Ordering::SeqCst) + 1
    }
    fn calls(&self) -> Vec<String> {
        self.calls.lock().unwrap().clone()
    }
}

fn event(method: &str, seq: u64, payload: serde_json::Value, cmid: Option<&str>) -> BridgeEvent {
    BridgeEvent {
        method: method.into(),
        seq,
        payload,
        client_message_id: cmid.map(str::to_owned),
        created_at_ms: None,
    }
}

impl TurnRunner for Recorder {
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.calls.lock().unwrap().push(format!(
            "start_turn({thread_id},{prompt},{client_message_id})"
        ));
        *self.cancelled.lock().unwrap() = false;
        sink(event(
            "turn/accepted",
            self.next(),
            serde_json::json!({"turn_id": "turn-1"}),
            Some(client_message_id),
        ));
        sink(event(
            "turn/started",
            self.next(),
            serde_json::json!({"turn_id": "turn-1"}),
            Some(client_message_id),
        ));
        sink(event(
            "item/approval_request",
            self.next(),
            serde_json::json!({"request_id": "approval-1", "tool": "write_file"}),
            None,
        ));
        Ok(())
    }

    fn respond(
        &self,
        thread_id: &str,
        request_id: &str,
        decision: &str,
        guidance: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.calls.lock().unwrap().push(format!(
            "respond({thread_id},{request_id},{decision},{guidance})"
        ));
        let seq = self.next();
        sink(event(
            "item/completed",
            seq,
            serde_json::json!({"content": "hello Sunday"}),
            None,
        ));
        Ok(())
    }

    fn cancel(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        self.calls
            .lock()
            .unwrap()
            .push(format!("cancel({thread_id})"));
        *self.cancelled.lock().unwrap() = true;
        let seq = self.next();
        Ok(vec![event(
            "turn/completed",
            seq,
            serde_json::json!({"status": "cancelled"}),
            None,
        )])
    }

    fn events(&self, thread_id: &str, after: u64) -> Result<Vec<BridgeEvent>, String> {
        self.calls
            .lock()
            .unwrap()
            .push(format!("events({thread_id},{after})"));
        Ok(Vec::new())
    }
}

struct Harness {
    addr: std::net::SocketAddr,
    runner: Arc<Recorder>,
}

fn start_with(runner: Arc<Recorder>) -> Harness {
    let server = AppServer::bind("127.0.0.1:0", runner.clone()).expect("bind");
    let addr = server.local_addr().unwrap();
    std::thread::spawn(move || server.serve());
    Harness { addr, runner }
}

fn start() -> Harness {
    start_with(Arc::new(Recorder::default()))
}

/// A real WebSocket client, not a raw socket: the point is to prove the frame
/// shape a browser would produce is accepted.
fn connect(addr: std::net::SocketAddr) -> Socket {
    let stream = TcpStream::connect(addr).expect("connect");
    let (socket, _) = tungstenite::client(
        format!("ws://{addr}"),
        tungstenite::stream::MaybeTlsStream::Plain(stream),
    )
    .expect("handshake");
    socket
}

fn send(socket: &mut Socket, body: serde_json::Value) {
    socket
        .send(tungstenite::Message::Text(body.to_string().into()))
        .expect("send");
}

fn recv(socket: &mut Socket) -> serde_json::Value {
    loop {
        match socket.read().expect("read") {
            tungstenite::Message::Text(text) => {
                return serde_json::from_str(&text).expect("json frame")
            }
            _ => continue,
        }
    }
}

fn init(socket: &mut Socket) {
    send(
        socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "lamtools-ui"}, "threadId": "thread-1"}
        }),
    );
    let _ = recv(socket);
}

#[test]
fn initialize_uses_the_camel_case_thread_id_the_client_sends() {
    let harness = start();
    let mut socket = connect(harness.addr);

    // Exactly what CoreAppServerClient.connect sends.
    send(
        &mut socket,
        serde_json::json!({
            "id": "direct-1",
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "lamtools-ui", "version": "0.0.0"},
                "threadId": "thread-42",
                "lastSeenSeq": 7,
            }
        }),
    );
    let reply = recv(&mut socket);

    assert_eq!(reply["id"], "direct-1");
    let capabilities = &reply["result"]["capabilities"];
    assert_eq!(capabilities["protocol"], "core.app_server.v1");
    assert_eq!(capabilities["streaming"], true);
    assert_eq!(capabilities["approval"], true);

    // The resume thread and the replay offset must both reach the runner.
    let calls = harness.runner.calls();
    assert!(
        calls.iter().any(|c| c == "events(thread-42,7)"),
        "adapter dropped threadId or lastSeenSeq: {calls:?}"
    );
}

#[test]
fn initialize_without_a_thread_still_returns_capabilities() {
    let harness = start();
    let mut socket = connect(harness.addr);
    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "lamtools-ui"}}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(
        reply["result"]["capabilities"]["protocol"],
        "core.app_server.v1"
    );
    assert!(harness.runner.calls().is_empty());
}

#[test]
fn turn_start_reads_the_snake_case_params_the_store_sends() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    send(
        &mut socket,
        serde_json::json!({
            "id": "direct-3",
            "method": "turn/start",
            "params": {
                "thread_id": "thread-1",
                "client_message_id": "msg-9",
                "input": [{"type": "text", "text": "write a file"}],
                "work_root": "C:/tmp",
                "include_snapshot": false
            }
        }),
    );
    let reply = recv(&mut socket);
    assert!(reply.get("error").is_none(), "unexpected error: {reply}");
    // Scaffolding must not leak into the result the client parses.
    assert!(
        reply["result"].get("_events").is_none(),
        "internal _events leaked into result: {reply}"
    );

    // Each event arrives as its own notification whose params is the envelope.
    let mut methods = Vec::new();
    for _ in 0..3 {
        let frame = recv(&mut socket);
        let method = frame["method"].as_str().unwrap_or_default().to_owned();
        assert_eq!(
            frame["params"]["method"], method,
            "envelope lost its method"
        );
        assert_eq!(frame["params"]["thread_id"], "thread-1");
        assert_eq!(frame["params"]["protocol_version"], "core.app_server.v1");
        methods.push(method);
    }
    assert_eq!(
        methods,
        vec!["turn/accepted", "turn/started", "item/approval_request"],
        "events must arrive in journal order"
    );

    let calls = harness.runner.calls();
    assert!(
        calls
            .iter()
            .any(|c| c == "start_turn(thread-1,write a file,msg-9)"),
        "turn/start params were not mapped: {calls:?}"
    );
}

#[test]
fn approval_respond_uses_request_id_and_decision_not_approval_id() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    // Exactly what store.respondApproval sends.
    send(
        &mut socket,
        serde_json::json!({
            "id": "direct-4",
            "method": "approval/respond",
            "params": {
                "request_id": "approval-1",
                "thread_id": "thread-1",
                "decision": "approve_once",
                "guidance": ""
            }
        }),
    );
    let reply = recv(&mut socket);
    assert!(reply.get("error").is_none(), "unexpected error: {reply}");
    let event = recv(&mut socket);
    assert_eq!(event["method"], "item/completed");

    let calls = harness.runner.calls();
    assert!(
        calls
            .iter()
            .any(|c| c == "respond(thread-1,approval-1,approve,)"),
        "decision alias was not normalised: {calls:?}"
    );
}

#[test]
fn approval_without_a_thread_is_refused() {
    let harness = start();
    let mut socket = connect(harness.addr);
    // A bare initialize with no thread: nothing bounds the approval to a
    // conversation, so it must be refused rather than guessed.
    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "lamtools-ui"}}
        }),
    );
    let _ = recv(&mut socket);

    send(
        &mut socket,
        serde_json::json!({
            "id": "direct-5",
            "method": "approval/respond",
            "params": {"request_id": "approval-1", "decision": "approve"}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32602, "{reply}");
    assert!(harness
        .runner
        .calls()
        .iter()
        .all(|c| !c.starts_with("respond")));
}

#[test]
fn an_unknown_decision_is_rejected_instead_of_treated_as_deny() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    send(
        &mut socket,
        serde_json::json!({
            "id": 2,
            "method": "approval/respond",
            "params": {"request_id": "approval-1", "thread_id": "thread-1", "decision": "yes-please"}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32602, "{reply}");
    assert!(harness
        .runner
        .calls()
        .iter()
        .all(|c| !c.starts_with("respond")));
}

#[test]
fn turn_start_without_text_is_rejected() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    send(
        &mut socket,
        serde_json::json!({
            "id": 2,
            "method": "turn/start",
            "params": {"thread_id": "thread-1", "input": [], "client_message_id": "m"}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32602, "{reply}");
}

#[test]
fn an_unimplemented_method_says_so_instead_of_returning_an_empty_object() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    send(
        &mut socket,
        serde_json::json!({"id": 2, "method": "artifact/export", "params": {}}),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32601, "{reply}");
}

#[test]
fn turn_cancel_reaches_the_runner() {
    let harness = start();
    let mut socket = connect(harness.addr);
    init(&mut socket);

    send(
        &mut socket,
        serde_json::json!({"id": 2, "method": "turn/cancel", "params": {"thread_id": "thread-1"}}),
    );
    let reply = recv(&mut socket);
    assert!(reply.get("error").is_none(), "{reply}");
    assert!(harness
        .runner
        .calls()
        .iter()
        .any(|c| c == "cancel(thread-1)"));
    let event = recv(&mut socket);
    assert_eq!(event["method"], "turn/completed");
}

#[test]
fn the_initialized_notification_does_not_produce_a_reply() {
    let harness = start();
    let mut socket = connect(harness.addr);
    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "lamtools-ui"}}
        }),
    );
    let _ = recv(&mut socket);

    // A notification has no id; answering it would desynchronise the client.
    send(
        &mut socket,
        serde_json::json!({"method": "initialized", "params": {}}),
    );
    send(
        &mut socket,
        serde_json::json!({"id": 99, "method": "thread/snapshot", "params": {"thread_id": "t"}}),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["id"], 99, "a notification produced a frame: {reply}");
}

#[test]
fn a_client_that_disconnects_does_not_take_the_server_down() {
    let harness = start();
    {
        let mut socket = connect(harness.addr);
        send(
            &mut socket,
            serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "a"}}}),
        );
        let _ = recv(&mut socket);
        // Drop without a close handshake, like a crashed window.
    }
    let mut socket = connect(harness.addr);
    send(
        &mut socket,
        serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "b"}}}),
    );
    let reply = recv(&mut socket);
    assert_eq!(
        reply["result"]["capabilities"]["protocol"],
        "core.app_server.v1"
    );
}

#[test]
fn a_malformed_frame_is_ignored_and_the_connection_survives() {
    let harness = start();
    let mut socket = connect(harness.addr);
    socket
        .send(tungstenite::Message::Text("{not json".into()))
        .unwrap();
    send(
        &mut socket,
        serde_json::json!({"id": 7, "method": "initialize", "params": {"clientInfo": {"name": "a"}}}),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["id"], 7);
}

#[test]
fn events_after_a_sequence_are_replayed_in_order() {
    use sunday_host::app_server::EventBuffer;
    let buffer = EventBuffer::default();
    for seq in 1..=5 {
        buffer.push(
            "thread-1",
            event(
                "item/delta",
                seq,
                serde_json::json!({"text": seq.to_string()}),
                None,
            ),
        );
    }
    let replayed = buffer.after("thread-1", 3);
    assert_eq!(replayed.len(), 2);
    assert_eq!(replayed[0].seq, 4);
    assert!(buffer.after("other-thread", 0).is_empty());
}

/// The socket must stay writable after a large reply, because a real turn sends
/// many events on the same connection.
#[test]
fn many_events_on_one_connection_stay_ordered() {
    struct Many;
    impl TurnRunner for Many {
        fn start_turn(
            &self,
            _t: &str,
            _p: &str,
            _c: &str,
            sink: EventSink<'_>,
        ) -> Result<(), String> {
            for i in 1..=200 {
                sink(event(
                    "item/delta",
                    i,
                    serde_json::json!({"text": "x"}),
                    None,
                ));
            }
            Ok(())
        }
        fn respond(
            &self,
            _: &str,
            _: &str,
            _: &str,
            _: &str,
            _: EventSink<'_>,
        ) -> Result<(), String> {
            Ok(())
        }
        fn cancel(&self, _: &str) -> Result<Vec<BridgeEvent>, String> {
            Ok(Vec::new())
        }
        fn events(&self, _: &str, _: u64) -> Result<Vec<BridgeEvent>, String> {
            Ok(Vec::new())
        }
    }

    let server = AppServer::bind("127.0.0.1:0", Arc::new(Many)).unwrap();
    let addr = server.local_addr().unwrap();
    std::thread::spawn(move || server.serve());

    let mut socket = connect(addr);
    send(
        &mut socket,
        serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "a"}}}),
    );
    let _ = recv(&mut socket);
    send(
        &mut socket,
        serde_json::json!({
            "id": 2,
            "method": "turn/start",
            "params": {"thread_id": "t", "client_message_id": "m", "input": [{"type": "text", "text": "go"}]}
        }),
    );
    let _ = recv(&mut socket);

    let mut seen = Vec::new();
    for _ in 0..200 {
        let frame = recv(&mut socket);
        seen.push(frame["params"]["seq"].as_u64().unwrap());
    }
    assert_eq!(seen, (1..=200).collect::<Vec<u64>>());
}

#[test]
fn a_large_frame_is_reassembled() {
    // 200KB payload: the smoke reader must handle the 126 and 127 length forms.
    struct Big;
    impl TurnRunner for Big {
        fn start_turn(
            &self,
            t: &str,
            _p: &str,
            _c: &str,
            sink: EventSink<'_>,
        ) -> Result<(), String> {
            sink(event(
                "item/completed",
                1,
                serde_json::json!({"blob": "a".repeat(200_000), "thread": t}),
                None,
            ));
            Ok(())
        }
        fn respond(
            &self,
            _: &str,
            _: &str,
            _: &str,
            _: &str,
            _: EventSink<'_>,
        ) -> Result<(), String> {
            Ok(())
        }
        fn cancel(&self, _: &str) -> Result<Vec<BridgeEvent>, String> {
            Ok(Vec::new())
        }
        fn events(&self, _: &str, _: u64) -> Result<Vec<BridgeEvent>, String> {
            Ok(Vec::new())
        }
    }

    let server = AppServer::bind("127.0.0.1:0", Arc::new(Big)).unwrap();
    let addr = server.local_addr().unwrap();
    std::thread::spawn(move || server.serve());

    let mut socket = connect(addr);
    send(
        &mut socket,
        serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "a"}}}),
    );
    let _ = recv(&mut socket);
    send(
        &mut socket,
        serde_json::json!({
            "id": 2,
            "method": "turn/start",
            "params": {"thread_id": "t", "client_message_id": "m", "input": [{"type": "text", "text": "go"}]}
        }),
    );
    let _ = recv(&mut socket);
    let frame = recv(&mut socket);
    assert_eq!(
        frame["params"]["payload"]["blob"].as_str().unwrap().len(),
        200_000
    );
}

/// A slow turn must not block `turn/cancel`: this is why the turn moved to its
/// own thread. Without it the cancel would sit unread until the turn ended,
/// which is precisely when the user no longer needs it.
#[test]
fn a_cancel_is_answered_while_a_slow_turn_is_still_running() {
    struct Slow {
        cancelled: Arc<Mutex<bool>>,
    }
    impl TurnRunner for Slow {
        fn start_turn(
            &self,
            _t: &str,
            _p: &str,
            cmid: &str,
            sink: EventSink<'_>,
        ) -> Result<(), String> {
            sink(event("turn/accepted", 1, serde_json::json!({}), Some(cmid)));
            // Stream for a while, checking the flag, like a real model call.
            for seq in 2..=400u64 {
                if *self.cancelled.lock().unwrap() {
                    sink(event(
                        "turn/completed",
                        seq,
                        serde_json::json!({"status": "cancelled"}),
                        None,
                    ));
                    return Ok(());
                }
                std::thread::sleep(std::time::Duration::from_millis(5));
                sink(event(
                    "item/delta",
                    seq,
                    serde_json::json!({"text": "x"}),
                    None,
                ));
            }
            Ok(())
        }
        fn respond(
            &self,
            _: &str,
            _: &str,
            _: &str,
            _: &str,
            _: EventSink<'_>,
        ) -> Result<(), String> {
            Ok(())
        }
        fn cancel(&self, _: &str) -> Result<Vec<BridgeEvent>, String> {
            *self.cancelled.lock().unwrap() = true;
            Ok(Vec::new())
        }
        fn events(&self, _: &str, _: u64) -> Result<Vec<BridgeEvent>, String> {
            Ok(Vec::new())
        }
    }

    let cancelled = Arc::new(Mutex::new(false));
    let server = AppServer::bind(
        "127.0.0.1:0",
        Arc::new(Slow {
            cancelled: cancelled.clone(),
        }),
    )
    .unwrap();
    let addr = server.local_addr().unwrap();
    std::thread::spawn(move || server.serve());

    let mut socket = connect(addr);
    send(
        &mut socket,
        serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "a"}, "threadId": "t"}}),
    );
    let _ = recv(&mut socket);
    send(
        &mut socket,
        serde_json::json!({
            "id": 2,
            "method": "turn/start",
            "params": {"thread_id": "t", "client_message_id": "m", "input": [{"type": "text", "text": "go"}]}
        }),
    );
    // Read a few deltas so the turn is genuinely mid-flight.
    for _ in 0..5 {
        let _ = recv(&mut socket);
    }
    send(
        &mut socket,
        serde_json::json!({"id": 3, "method": "turn/cancel", "params": {"thread_id": "t"}}),
    );

    // The cancel reply must arrive while the turn would still be streaming.
    // Events already queued before the cancel was read legitimately drain
    // first, so scan past them instead of demanding the reply be the very
    // next frame.
    let mut reply = serde_json::Value::Null;
    let mut highest_before_reply = 0u64;
    for _ in 0..100 {
        let frame = recv(&mut socket);
        if frame.get("method").is_some() {
            if let Some(seq) = frame["params"]["seq"].as_u64() {
                highest_before_reply = highest_before_reply.max(seq);
            }
            continue;
        }
        reply = frame;
        break;
    }
    assert_eq!(reply["id"], 3, "cancel was never answered: {reply}");
    assert!(
        highest_before_reply < 400,
        "the turn finished before the cancel was answered: seq {highest_before_reply}"
    );
    assert!(
        *cancelled.lock().unwrap(),
        "the runner never saw the cancel"
    );

    // And the turn must actually stop rather than run to 400.
    let mut last = 0u64;
    for _ in 0..500 {
        let frame = recv(&mut socket);
        if let Some(seq) = frame["params"]["seq"].as_u64() {
            last = seq;
        }
        if frame["params"]["method"] == "turn/completed" {
            assert!(
                last < 400,
                "the turn ran to the end despite the cancel: seq {last}"
            );
            return;
        }
    }
    panic!("the turn never reported completion after cancel");
}

/// One frame, read the way a host that projects it reads it.
///
/// Two things have to be true here. The display time must be the instant the journal
/// recorded, not the instant the frame was built: a replay is not when the fact
/// happened. And an event with no row behind it must report no time at all, because an
/// empty string is a string to the client, which then formats it and shows an invalid
/// date.
#[test]
fn a_frame_carries_the_instant_the_journal_recorded() {
    let mut recorded = event("turn/started", 7, serde_json::json!({}), None);
    recorded.created_at_ms = Some(1_700_000_000_000);
    let frame = event_json("th", &recorded);
    assert_eq!(frame["created_at"], "2023-11-14T22:13:20.000Z");
    assert_eq!(frame["created_at_ms"], 1_700_000_000_000i64);
    // Identity still comes from the journal position.
    assert_eq!(frame["event_id"], "th:7");

    let mut synthesised = event("turn/completed", 0, serde_json::json!({}), None);
    synthesised.created_at_ms = None;
    let frame = event_json("th", &synthesised);
    assert!(
        frame.get("created_at").is_none(),
        "an unknown time must be absent, never an empty string"
    );
}

/// Hand-written date arithmetic; three known instants catch a wrong era, a wrong month
/// offset and a lost leap day.
#[test]
fn the_formatter_matches_known_instants() {
    assert_eq!(iso_utc(0), "1970-01-01T00:00:00.000Z");
    assert_eq!(iso_utc(1_700_000_000_000), "2023-11-14T22:13:20.000Z");
    assert_eq!(iso_utc(1_709_164_800_123), "2024-02-29T00:00:00.123Z");
}
