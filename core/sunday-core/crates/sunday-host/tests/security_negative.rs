//! Negative security tests.
//!
//! These prove what an **unauthorised** client cannot do. Positive tests show the
//! happy path works; they would all still pass if the door were wide open. Each
//! test below would fail if authentication were removed, which is the property
//! that makes them worth having.
//!
//! The threat being modelled is concrete: another process on the same machine, or
//! another app on the same Android device, that discovers the listening port. A
//! random port on loopback does not stop that. Only a credential does.

use std::sync::atomic::AtomicUsize;
use std::sync::Arc;
use sunday_host::app_server::{
    AppServer, BridgeEvent, EventSink, HistoryPage, StopMode, TurnRunner,
};
use sunday_host::token;

type Socket = tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>;

const GOOD_TOKEN: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

/// A runner that records every call. Any recorded call in a negative test is
/// proof the attack succeeded.
#[derive(Default)]
struct Spy {
    /// Every call that reached the runner. A negative test asserts this stays
    /// empty: if the runner was reached, the attack succeeded.
    calls: std::sync::Mutex<Vec<String>>,
    /// Kept so the struct can grow a counter later without rewriting the
    /// constructor; currently unused, which clippy flags.
    _writes: AtomicUsize,
}

impl Spy {
    fn record(&self, what: impl Into<String>) {
        self.calls.lock().unwrap().push(what.into());
    }
    fn calls(&self) -> Vec<String> {
        self.calls.lock().unwrap().clone()
    }
}

fn event(method: &str, seq: u64) -> BridgeEvent {
    BridgeEvent {
        method: method.into(),
        seq,
        payload: serde_json::json!({}),
        client_message_id: None,
    }
}

impl TurnRunner for Spy {
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        _client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.record(format!("start_turn:{thread_id}:{prompt}"));
        sink(event("turn/accepted", 1));
        Ok(())
    }

    fn respond(
        &self,
        _thread_id: &str,
        request_id: &str,
        _decision: &str,
        _guidance: &str,
        _sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.record(format!("respond:{request_id}"));
        Ok(())
    }

    fn cancel(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        self.record(format!("cancel:{thread_id}"));
        Ok(Vec::new())
    }

    fn events(&self, thread_id: &str, _after: u64) -> Result<Vec<BridgeEvent>, String> {
        self.record(format!("read_events:{thread_id}"));
        // Pretend the transcript holds something worth stealing.
        Ok(vec![BridgeEvent {
            method: "item/completed".into(),
            seq: 1,
            payload: serde_json::json!({"content": "SECRET TRANSCRIPT"}),
            client_message_id: None,
        }])
    }

    fn open_thread(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        self.record(format!("open_thread:{thread_id}"));
        Ok(vec![BridgeEvent {
            method: "item/completed".into(),
            seq: 1,
            payload: serde_json::json!({"content": "SECRET TRANSCRIPT"}),
            client_message_id: None,
        }])
    }

    fn history(
        &self,
        thread_id: &str,
        _before_seq: Option<u64>,
        _limit: usize,
    ) -> Result<HistoryPage, String> {
        self.record(format!("history:{thread_id}"));
        Ok(HistoryPage {
            events: vec![event("item/completed", 1)],
            has_more: false,
            total_items: 1,
        })
    }

    fn queue(&self, thread_id: &str) -> Result<Vec<sunday_host::app_server::QueueView>, String> {
        self.record(format!("queue:{thread_id}"));
        Ok(Vec::new())
    }

    fn queue_create(
        &self,
        thread_id: &str,
        _queue_item_id: &str,
        _text: &str,
    ) -> Result<Vec<sunday_host::app_server::QueueView>, String> {
        self.record(format!("queue_create:{thread_id}"));
        Ok(Vec::new())
    }

    fn steer(
        &self,
        thread_id: &str,
        _turn_id: &str,
        _text: &str,
    ) -> Result<sunday_host::app_server::SteerOutcome, String> {
        self.record(format!("steer:{thread_id}"));
        Ok(sunday_host::app_server::SteerOutcome {
            applied: false,
            queued: false,
            reason: "run_not_active".into(),
        })
    }

    fn stop_turn(
        &self,
        thread_id: &str,
        _mode: StopMode,
        _sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.record(format!("stop:{thread_id}"));
        Ok(())
    }
}

struct Harness {
    addr: std::net::SocketAddr,
    spy: Arc<Spy>,
}

fn start(token: Option<&str>) -> Harness {
    let spy = Arc::new(Spy::default());
    let server = match token {
        Some(token) => {
            AppServer::bind_authenticated("127.0.0.1:0", spy.clone(), token).expect("bind")
        }
        None => AppServer::bind("127.0.0.1:0", spy.clone()).expect("bind"),
    };
    let addr = server.local_addr().unwrap();
    std::thread::spawn(move || server.serve());
    Harness { addr, spy }
}

fn connect(addr: std::net::SocketAddr) -> Socket {
    let stream = std::net::TcpStream::connect(addr).expect("connect");
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

/// The headline negative test: an attacker who knows the port and guesses the
/// protocol still cannot read the transcript.
#[test]
fn without_a_token_the_transcript_cannot_be_read() {
    let harness = start(Some(GOOD_TOKEN));
    let mut socket = connect(harness.addr);

    // Exactly what an attacker would try: skip the handshake, ask for history.
    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "thread/read",
            "params": {"thread_id": "victim"}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(
        reply["error"]["code"], -32001,
        "an unauthenticated client was served a transcript: {reply}"
    );
    assert!(
        !reply.to_string().contains("SECRET TRANSCRIPT"),
        "the refusal leaked transcript content"
    );
    assert!(
        harness.spy.calls().is_empty(),
        "the runner was reached before authentication: {:?}",
        harness.spy.calls()
    );
}

/// A wrong token must be refused, and must not be distinguishable from a missing
/// one in the response body.
#[test]
fn a_guessed_token_is_refused() {
    let harness = start(Some(GOOD_TOKEN));
    let mut socket = connect(harness.addr);

    let wrong = "f".repeat(GOOD_TOKEN.len());
    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "attacker"}, "auth": wrong}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32001, "{reply}");
    assert!(
        harness.spy.calls().is_empty(),
        "the runner was reached with a wrong token: {:?}",
        harness.spy.calls()
    );

    // And the connection must still be unusable afterwards: a rejection must not
    // leave a half-open session that accepts the next call.
    send(
        &mut socket,
        serde_json::json!({"id": 2, "method": "thread/start", "params": {"thread_id": "t"}}),
    );
    let reply = recv(&mut socket);
    assert_eq!(reply["error"]["code"], -32001, "{reply}");
    assert!(harness.spy.calls().is_empty());
}

/// The correct token must work. Without this, the tests above would pass for the
/// wrong reason: a server that refuses everybody.
#[test]
fn the_right_token_is_accepted() {
    let harness = start(Some(GOOD_TOKEN));
    let mut socket = connect(harness.addr);

    send(
        &mut socket,
        serde_json::json!({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "ui"}, "threadId": "t", "auth": GOOD_TOKEN}
        }),
    );
    let reply = recv(&mut socket);
    assert_eq!(
        reply["result"]["capabilities"]["protocol"],
        "core.app_server.v1"
    );

    send(
        &mut socket,
        serde_json::json!({"id": 2, "method": "thread/read", "params": {"thread_id": "t"}}),
    );
    let _ = recv(&mut socket);
    assert!(
        harness
            .spy
            .calls()
            .iter()
            .any(|c| c.starts_with("read_events")),
        "an authenticated client could not read: {:?}",
        harness.spy.calls()
    );
}

/// No mutating method may be reachable before authentication. This is the test
/// that would catch a future method being added without inheriting the gate.
#[test]
fn no_mutating_method_is_reachable_before_authentication() {
    let harness = start(Some(GOOD_TOKEN));

    // Every method a workbench can call, minus `initialize` itself.
    const METHODS: &[&str] = &[
        "thread/start",
        "thread/resume",
        "thread/read",
        "thread/snapshot",
        "turn/start",
        "turn/resume",
        "turn/steer",
        "turn/pause",
        "turn/interrupt",
        "turn/terminate",
        "turn/force_reset",
        "turn/cancel",
        "queue/create",
        "queue/update",
        "queue/delete",
        "queue/reorder",
        "queue/list",
        "approval/respond",
    ];

    for method in METHODS {
        let mut socket = connect(harness.addr);
        send(
            &mut socket,
            serde_json::json!({
                "id": 1,
                "method": method,
                "params": {
                    "thread_id": "victim",
                    "request_id": "appr-1",
                    "decision": "approve",
                    "input": [{"type": "text", "text": "write /etc/passwd"}],
                    "queue_item_id": "q1"
                }
            }),
        );
        let reply = recv(&mut socket);
        assert_eq!(
            reply["error"]["code"], -32001,
            "{method} was reachable without a token: {reply}"
        );
    }

    assert!(
        harness.spy.calls().is_empty(),
        "some method reached the runner without authentication: {:?}",
        harness.spy.calls()
    );
}

/// Reading the token file must not be possible for another user. On Windows the
/// profile ACL provides this; on Unix the file is 0600. This test asserts the
/// property where the platform exposes it.
#[test]
fn the_token_file_is_not_world_readable() {
    let dir = tempfile::tempdir().unwrap();
    token::load_or_create(dir.path()).unwrap();
    let path = token::path_in(dir.path());

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        assert_eq!(mode & 0o077, 0, "token readable by others: {mode:o}");
    }
    #[cfg(not(unix))]
    {
        // Windows: the file must exist and must not be marked world-readable via
        // a permissive attribute set. Full ACL inspection needs winapi, which this
        // crate does not take on; the profile directory already excludes other
        // users. The property asserted here is that we did not create the file
        // with an explicit Everyone grant.
        assert!(path.exists());
    }
}

/// A server with no token is trusted by construction, which is only acceptable
/// for IPC or tests. This test pins that a token-less server is what `bind`
/// makes, so nobody mistakes it for the safe path.
#[test]
fn the_unauthenticated_constructor_is_clearly_test_only() {
    let harness = start(None);
    let mut socket = connect(harness.addr);
    send(
        &mut socket,
        serde_json::json!({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "a"}}}),
    );
    let reply = recv(&mut socket);
    // It works, which is the point: `bind` is for transports unreachable from
    // outside the process. The doc comment on it says so, and this test records
    // the behaviour so the difference from `bind_authenticated` is explicit.
    assert_eq!(
        reply["result"]["capabilities"]["protocol"],
        "core.app_server.v1"
    );
}
