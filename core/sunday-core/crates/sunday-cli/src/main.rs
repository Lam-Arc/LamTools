//! `sunday` — headless entry point for the new core.
//!
//! Three kinds of command:
//!   * inspection (read-only, never writes)
//!   * self-test of the stored guarantees
//!   * an end-to-end turn, so the loop can be exercised without a UI
//!
//! Nothing here touches a user database: every path is given explicitly.

mod scripted;
mod serve;

use std::process::ExitCode;
use std::sync::Mutex;
use sunday_agent::{Approval, Approver, AutoApprove, Env, TurnInput};
use sunday_protocol::{
    CoreError, HostKind, Permission, RunBudget, RunOutcome, ToolCall, ToolSpec, PROTOCOL_VERSION,
};
use sunday_store::Store;
use sunday_tools::file_read::ReadFile;
use sunday_tools::file_write::WriteFile;

fn usage() {
    println!(
        "sunday {}\n\
         protocol {}\n\n\
         inspection (read-only):\n\
           health\n\
           db inspect --db <path>\n\
           journal tail --db <path> --thread <id> [--after <seq>]\n\n\
         self-test:\n\
           store selftest --db <path>\n\n\
         turn:\n\
           turn --db <path> --workspace <dir> --thread <id> --prompt <text> --script <file> [--grant <tool-id>]\n\
           approve --db <path> --workspace <dir> --thread <id> --approval <id> [--script <file>] [--auto-approve]\n\
           steer --db <path> --thread <id> --text <text>\n\
           children --db <path> --parent <id>\n\n\
         The script is a JSON array of model turns. A scripted run uses the real
         loop, store, tools and approval flow; only the paid model call is replaced.",
        env!("CARGO_PKG_VERSION"),
        PROTOCOL_VERSION
    );
}

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn has_flag(args: &[String], flag: &str) -> bool {
    args.iter().any(|a| a == flag)
}

fn fail(err: CoreError) -> ExitCode {
    eprintln!("error: {err}");
    ExitCode::from(err.exit_code() as u8)
}

fn required(args: &[String], flag: &str) -> Result<String, CoreError> {
    arg_value(args, flag).ok_or_else(|| CoreError::invalid(format!("{flag} is required")))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        usage();
        return ExitCode::SUCCESS;
    }

    match args[0].as_str() {
        "health" => {
            println!(
                "ok core={} protocol={}",
                env!("CARGO_PKG_VERSION"),
                PROTOCOL_VERSION
            );
            ExitCode::SUCCESS
        }
        "db" => match args.get(1).map(String::as_str) {
            Some("inspect") => inspect(&args[2..]),
            _ => {
                usage();
                ExitCode::from(18)
            }
        },
        "journal" => match args.get(1).map(String::as_str) {
            Some("tail") => journal_tail(&args[2..]),
            _ => {
                usage();
                ExitCode::from(18)
            }
        },
        "store" => match args.get(1).map(String::as_str) {
            Some("selftest") => self_test(&args[2..]),
            _ => {
                usage();
                ExitCode::from(18)
            }
        },
        "turn" => run_async(turn(&args[1..])),
        "approve" => run_async(approve(&args[1..])),
        "serve" => serve(&args[1..]),
        "steer" => steer(&args[1..]),
        "children" => children(&args[1..]),
        other => {
            eprintln!("unknown command: {other}");
            usage();
            ExitCode::from(18)
        }
    }
}

fn run_async(fut: impl std::future::Future<Output = ExitCode>) -> ExitCode {
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(err) => {
            eprintln!("cannot start a runtime: {err}");
            return ExitCode::from(19);
        }
    };
    runtime.block_on(fut)
}

/// Decides who gets asked. A tool marked `AskUser` always asks; everything that
/// reached the model is either allowed automatically or not offered at all.
struct PolicyApprover;

impl Approver for PolicyApprover {
    fn decide(&self, _call: &ToolCall, spec: &ToolSpec) -> Approval {
        match spec.permission {
            Permission::AskUser => Approval::Ask,
            _ => Approval::Auto,
        }
    }
}

enum Chosen {
    Auto,
    Policy,
}

struct TurnEnv<'a> {
    store: &'a Mutex<Store>,
    workspace: String,
    thread: String,
}

async fn run_once(
    env: &TurnEnv<'_>,
    approver: Chosen,
    model: std::sync::Arc<dyn sunday_protocol::Model>,
    prompt: &str,
    turn_id: &str,
) -> ExitCode {
    let files = match sunday_platform::LocalFiles::new(&env.workspace) {
        Ok(files) => std::sync::Arc::new(files),
        Err(err) => return fail(err),
    };
    let read = ReadFile::new(files.clone());
    let write = WriteFile::new(files);
    let tools: Vec<&dyn sunday_protocol::Tool> = vec![&read, &write];
    let cancel = sunday_protocol::CancelToken::new();

    let auto = AutoApprove;
    let policy = PolicyApprover;
    let approver_ref: &dyn Approver = match approver {
        Chosen::Auto => &auto,
        Chosen::Policy => &policy,
    };

    let run_env = Env {
        store: env.store,
        model: model.as_ref(),
        tools: &tools,
        approver: approver_ref,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };

    let input = TurnInput {
        thread_id: env.thread.clone(),
        turn_id: turn_id.to_owned(),
        model_id: "scripted".into(),
        system: Some("You are Sunday. Use the tools you are given.".into()),
        prompt: prompt.to_owned(),
    };

    match sunday_agent::run_turn(&run_env, input, RunBudget::default()).await {
        Err(err) => fail(err),
        Ok(RunOutcome::Completed { text }) => {
            println!("completed: {text}");
            ExitCode::SUCCESS
        }
        Ok(RunOutcome::Cancelled) => {
            println!("cancelled");
            ExitCode::SUCCESS
        }
        Ok(RunOutcome::NeedsApproval { approval_id }) => {
            println!("needs_approval: {approval_id}");
            println!("next: sunday approve --db <path> --workspace <dir> --thread <id> --approval {approval_id} --script <remaining script>");
            ExitCode::SUCCESS
        }
        Ok(RunOutcome::WaitingForReconciliation { tool_call_id, hint }) => {
            println!("outcome_unknown: {tool_call_id}");
            println!("{hint}");
            ExitCode::from(15)
        }
        Ok(RunOutcome::BudgetExhausted { reason }) => {
            println!("budget_exhausted: {reason:?}");
            ExitCode::from(11)
        }
    }
}

/// Exposes a real core over `core.app_server.v1` so the existing UI can drive it.
///
/// The single-writer lock is taken inside `serve::run`, before the store is
/// opened, so two hosts can never write the same database.
fn serve(args: &[String]) -> ExitCode {
    let (db, workspace, listen) = match (
        required(args, "--db"),
        required(args, "--workspace"),
        arg_value(args, "--listen"),
    ) {
        (Ok(db), Ok(workspace), listen) => (
            db,
            workspace,
            listen.unwrap_or_else(|| "127.0.0.1:0".into()),
        ),
        (Err(err), ..) | (_, Err(err), ..) => return fail(err),
    };

    let (model, model_id) = match serve::model_from_args(
        arg_value(args, "--script"),
        arg_value(args, "--model-url"),
        arg_value(args, "--model"),
        arg_value(args, "--api-key"),
    ) {
        Ok(pair) => pair,
        Err(err) => return fail(err),
    };

    let options = serve::Options {
        db,
        workspace,
        listen,
        model,
        model_id,
        // Read-only unless the caller names specific tools with --grant.
        policy: serve::policy_from_args(args),
        announce_token_path: true,
    };
    match serve::run(options) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => fail(err),
    }
}

async fn turn(args: &[String]) -> ExitCode {
    let (db, workspace, thread, prompt, script) = match (
        required(args, "--db"),
        required(args, "--workspace"),
        required(args, "--thread"),
        required(args, "--prompt"),
        required(args, "--script"),
    ) {
        (Ok(db), Ok(workspace), Ok(thread), Ok(prompt), Ok(script)) => {
            (db, workspace, thread, prompt, script)
        }
        (Err(err), ..) | (_, Err(err), ..) | (_, _, Err(err), ..) | (_, _, _, Err(err), _) => {
            return fail(err)
        }
        _ => return fail(CoreError::invalid("--script is required")),
    };

    let model = match std::fs::read_to_string(&script)
        .map_err(|e| CoreError::invalid(format!("cannot read {script}: {e}")))
        .and_then(|text| scripted::ScriptedModel::from_json(&text))
    {
        Ok(model) => std::sync::Arc::new(model) as std::sync::Arc<dyn sunday_protocol::Model>,
        Err(err) => return fail(err),
    };

    let store = match Store::open(&db) {
        Ok(store) => Mutex::new(store),
        Err(err) => return fail(err),
    };
    report_recovery(&store);

    let env = TurnEnv {
        store: &store,
        workspace,
        thread,
    };
    let approver = if has_flag(args, "--auto-approve") {
        Chosen::Auto
    } else {
        Chosen::Policy
    };
    run_once(&env, approver, model, &prompt, "turn-1").await
}

async fn approve(args: &[String]) -> ExitCode {
    let (db, workspace, thread, approval) = match (
        required(args, "--db"),
        required(args, "--workspace"),
        required(args, "--thread"),
        required(args, "--approval"),
    ) {
        (Ok(a), Ok(b), Ok(c), Ok(d)) => (a, b, c, d),
        _ => {
            return fail(CoreError::invalid(
                "--db, --workspace, --thread and --approval are required",
            ))
        }
    };

    let model: std::sync::Arc<dyn sunday_protocol::Model> = match arg_value(args, "--script") {
        Some(path) => match std::fs::read_to_string(&path)
            .map_err(|e| CoreError::invalid(format!("cannot read {path}: {e}")))
            .and_then(|text| scripted::ScriptedModel::from_json(&text))
        {
            Ok(model) => std::sync::Arc::new(model),
            Err(err) => return fail(err),
        },
        None => {
            // Resume still may need a model if the loop continues after the tool.
            return fail(CoreError::invalid(
                "--script is required: the loop asks the model again after the approved call",
            ));
        }
    };

    let store = match Store::open(&db) {
        Ok(store) => Mutex::new(store),
        Err(err) => return fail(err),
    };

    let digest = {
        let store = store.lock().unwrap();
        match store.pending_call(&approval) {
            Ok(Some((_, digest))) => digest,
            Ok(None) => return fail(CoreError::invalid("that approval has no pending call")),
            Err(err) => return fail(err),
        }
    };

    let files = match sunday_platform::LocalFiles::new(&workspace) {
        Ok(files) => std::sync::Arc::new(files),
        Err(err) => return fail(err),
    };
    let read = ReadFile::new(files.clone());
    let write = WriteFile::new(files);
    let tools: Vec<&dyn sunday_protocol::Tool> = vec![&read, &write];
    let cancel = sunday_protocol::CancelToken::new();
    let auto = AutoApprove;
    let policy = PolicyApprover;
    let approver_ref: &dyn Approver = if has_flag(args, "--auto-approve") {
        &auto
    } else {
        &policy
    };

    let env = Env {
        store: &store,
        model: model.as_ref(),
        tools: &tools,
        approver: approver_ref,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };

    match sunday_agent::resume_turn(&env, &thread, &approval, &digest, RunBudget::default()).await {
        Err(err) => fail(err),
        Ok(RunOutcome::Completed { text }) => {
            println!("completed: {text}");
            ExitCode::SUCCESS
        }
        Ok(RunOutcome::NeedsApproval { approval_id }) => {
            println!("needs_approval: {approval_id}");
            ExitCode::SUCCESS
        }
        Ok(RunOutcome::Cancelled) => {
            println!("cancelled");
            ExitCode::SUCCESS
        }
        Ok(other) => {
            println!("stopped: {other:?}");
            ExitCode::SUCCESS
        }
    }
}

fn steer(args: &[String]) -> ExitCode {
    let (db, thread, text) = match (
        required(args, "--db"),
        required(args, "--thread"),
        required(args, "--text"),
    ) {
        (Ok(a), Ok(b), Ok(c)) => (a, b, c),
        _ => return fail(CoreError::invalid("--db, --thread and --text are required")),
    };
    let mut store = match Store::open(&db) {
        Ok(store) => store,
        Err(err) => return fail(err),
    };
    let id = format!(
        "g-{}",
        sunday_protocol::digest_str(&format!("{thread}|{text}"))
    );
    match store.append_guidance(&thread, &id, &text) {
        Ok(true) => {
            println!("queued: {id}");
            ExitCode::SUCCESS
        }
        Ok(false) => {
            println!("already queued: {id}");
            ExitCode::SUCCESS
        }
        Err(err) => fail(err),
    }
}

fn children(args: &[String]) -> ExitCode {
    let (db, parent) = match (required(args, "--db"), required(args, "--parent")) {
        (Ok(a), Ok(b)) => (a, b),
        _ => return fail(CoreError::invalid("--db and --parent are required")),
    };
    let store = match Store::open_read_only(&db) {
        Ok(store) => store,
        Err(err) => return fail(err),
    };
    match store.list_children(&parent) {
        Err(err) => fail(err),
        Ok(children) => {
            if children.is_empty() {
                println!("(no children)");
            }
            for child in children {
                println!(
                    "{} {} model={} tools={:?} result={}",
                    child.child_id,
                    child.status.as_str(),
                    child.model_id,
                    child.granted_tools,
                    child.result.unwrap_or_default()
                );
            }
            ExitCode::SUCCESS
        }
    }
}

fn report_recovery(store: &Mutex<Store>) {
    let plan = match store.lock().unwrap().recover() {
        Ok(plan) => plan,
        Err(err) => {
            eprintln!("recovery failed: {err}");
            return;
        }
    };
    if !plan.unknown.is_empty() {
        println!(
            "recovered: {} tool call(s) have an unknown outcome and will not be retried: {:?}",
            plan.unknown.len(),
            plan.unknown
        );
    }
    if !plan.orphaned_children.is_empty() {
        println!(
            "recovered: {} sub-agent(s) were interrupted: {:?}",
            plan.orphaned_children.len(),
            plan.orphaned_children
        );
    }
    if !plan.abandoned_receipts.is_empty() {
        println!(
            "recovered: {} command(s) were abandoned: {:?}",
            plan.abandoned_receipts.len(),
            plan.abandoned_receipts
        );
    }
}

fn inspect(args: &[String]) -> ExitCode {
    let db = match required(args, "--db") {
        Ok(db) => db,
        Err(err) => return fail(err),
    };
    match Store::open_read_only(&db) {
        Err(err) => fail(err),
        Ok(store) => {
            match store.schema_version() {
                Ok(version) => println!("schema_version {version}"),
                Err(err) => return fail(err),
            }
            match store.table_counts() {
                Err(err) => fail(err),
                Ok(counts) => {
                    for (table, count) in counts {
                        println!("{table} {count}");
                    }
                    println!("read_only true");
                    ExitCode::SUCCESS
                }
            }
        }
    }
}

fn journal_tail(args: &[String]) -> ExitCode {
    let (db, thread) = match (required(args, "--db"), required(args, "--thread")) {
        (Ok(a), Ok(b)) => (a, b),
        _ => return fail(CoreError::invalid("--db and --thread are required")),
    };
    let after = arg_value(args, "--after")
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(0);
    match Store::open_read_only(&db) {
        Err(err) => fail(err),
        Ok(store) => match store.events(&thread, after) {
            Err(err) => fail(err),
            Ok(events) => {
                if events.is_empty() {
                    println!("(no events)");
                }
                for event in events {
                    println!(
                        "{} {} {} {}",
                        event.seq,
                        event.kind.as_str(),
                        event.event_id,
                        event.payload
                    );
                }
                ExitCode::SUCCESS
            }
        },
    }
}

/// Runs the stored guarantees against a throwaway database and prints a verdict
/// per rule, so a failure is visible without reading the test output.
fn self_test(args: &[String]) -> ExitCode {
    let db = match required(args, "--db") {
        Ok(db) => db,
        Err(err) => return fail(err),
    };
    let dir = match std::path::Path::new(&db).parent() {
        Some(parent) => parent.to_path_buf(),
        None => std::path::PathBuf::from("."),
    };
    if let Err(err) = std::fs::create_dir_all(&dir) {
        eprintln!("cannot create {dir:?}: {err}");
        return ExitCode::from(19);
    }

    let mut failures = 0usize;
    let mut report = |name: &str, ok: bool, detail: String| {
        println!("{} {name}: {detail}", if ok { "PASS" } else { "FAIL" });
        if !ok {
            failures += 1;
        }
    };

    match Store::open(&db) {
        Err(err) => return fail(err),
        Ok(mut store) => {
            let workspace = "selftest".to_owned();

            let envelope = sunday_protocol::CommandEnvelope {
                protocol_version: PROTOCOL_VERSION.into(),
                request_id: "req-1".into(),
                thread_id: "t1".into(),
                expected_revision: None,
                payload: sunday_protocol::Command::TurnStart { text: "hi".into() },
            };
            let first = store.accept_command(&workspace, &envelope);
            let second = store.accept_command(&workspace, &envelope);
            let (ok, detail) = match (&first, &second) {
                (Ok(a), Ok(b)) => (
                    a == b && a.seq == Some(1),
                    format!("seq={:?} tuple_equal={}", a.seq, a == b),
                ),
                _ => (false, format!("{first:?} {second:?}")),
            };
            report("S1 duplicate request", ok, detail);

            let kinds = ["a", "b", "c"];
            let mut seqs = Vec::new();
            for (index, name) in kinds.iter().enumerate() {
                if let Ok(seq) = store.append_event(
                    &workspace,
                    "t1",
                    &format!("evt-{index}"),
                    sunday_protocol::EventKind::ModelStarted,
                    serde_json::json!({"n": name}),
                ) {
                    seqs.push(seq);
                }
            }
            report(
                "S2 seq contiguous",
                seqs == vec![2, 3, 4],
                format!("seqs={seqs:?}"),
            );

            let call = sunday_protocol::ToolCall {
                id: "call-1".into(),
                name: "write_file".into(),
                args: serde_json::json!({"path": "a.txt"}),
            };
            let prepared =
                store.prepare_tool_once("t1", &call, sunday_protocol::SideEffect::NonIdempotent);
            let dispatched = store.mark_dispatched("call-1");
            let plan = store.recover();
            let again =
                store.prepare_tool_once("t1", &call, sunday_protocol::SideEffect::NonIdempotent);
            let (ok, detail) = match (prepared, dispatched, plan, again) {
                (Ok(_), Ok(_), Ok(plan), Ok(again)) => (
                    plan.unknown == vec!["call-1".to_owned()]
                        && again == sunday_protocol::Prepared::MustReconcile,
                    format!("unknown={:?} next={again:?}", plan.unknown),
                ),
                (a, b, c, d) => (false, format!("{a:?} {b:?} {c:?} {d:?}")),
            };
            report("S4 unknown never replayed", ok, detail);

            let live = store.projection("t1");
            let rebuilt = store.rebuild_projection("t1");
            let (ok, detail) = match (live, rebuilt) {
                (Ok(live), Ok(rebuilt)) => (
                    live.last_seq == rebuilt.last_seq && live.counts == rebuilt.counts,
                    format!("last_seq={} rebuild={}", live.last_seq, rebuilt.last_seq),
                ),
                (a, b) => (false, format!("{a:?} {b:?}")),
            };
            report("S8 projection rebuild", ok, detail);
        }
    }

    if failures == 0 {
        println!("selftest ok");
        ExitCode::SUCCESS
    } else {
        eprintln!("selftest failed: {failures} rule(s) broken");
        ExitCode::from(19)
    }
}
