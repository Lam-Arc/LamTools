//! `serve` — exposes a real core over `core.app_server.v1`.
//!
//! This file is now only assembly. It used to carry a full `TurnRunner`
//! implementation, which the Android host then copied; both drifted. The runner
//! lives in `sunday_host::runner` and both hosts share it.
//!
//! What a host is allowed to do here, and nothing more:
//!
//!   * take the single-writer lock before opening the database
//!   * resolve paths and load or create the connection token
//!   * pick a model
//!   * decide the grant policy
//!   * bind the transport and print where it listens
//!
//! Everything about how a turn runs is below this layer.

use std::path::Path;
use std::sync::Arc;
use sunday_host::app_server::AppServer;
use sunday_host::lock::{LockError, SingleWriterLock};
use sunday_host::policy::GrantPolicy;
use sunday_host::runner::{CoreOptions, CoreRunner};
use sunday_host::token;

/// Blocks a moment for a previous instance to finish dying.
///
/// With an OS lock there is no reclaim window, so this is usually immediate. It
/// exists because a relaunch a few milliseconds after a kill can genuinely race
/// the kernel reaping the old process, and failing there would look like "the app
/// will not open".
fn acquire_with_wait(dir: &Path, owner: &str) -> Result<SingleWriterLock, String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        match SingleWriterLock::acquire(dir, owner) {
            Ok(lock) => return Ok(lock),
            Err(LockError::Busy { .. }) if std::time::Instant::now() < deadline => {
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
}

pub struct Options {
    pub db: String,
    pub workspace: String,
    pub listen: String,
    pub model: Arc<dyn sunday_protocol::Model>,
    pub model_id: String,
    /// Which tools may run without asking. Defaults to reads only.
    pub policy: GrantPolicy,
    /// Print the token path, never the token itself.
    pub announce_token_path: bool,
}

pub fn run(options: Options) -> Result<(), sunday_protocol::CoreError> {
    use sunday_protocol::CoreError;

    let db_path = Path::new(&options.db);
    let dir = db_path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| Path::new(".").to_path_buf());

    // Lock before touching the database.
    let lock = acquire_with_wait(&dir, "sunday-serve").map_err(|reason| CoreError::Rejected {
        reason: format!("{reason}. Close the other core first."),
    })?;

    let store = sunday_store::Store::open(&options.db)?;
    let connection_token = token::load_or_create(&dir)?;
    let token_path = token::path_in(&dir);

    let runner = Arc::new(CoreRunner::new(CoreOptions {
        store,
        model: options.model,
        model_id: options.model_id,
        workspace: options.workspace,
        // The CLI has no projects; one workspace serves every thread.
        workspace_for: None,
        host_kind: sunday_protocol::HostKind::Server,
        policy: options.policy,
        system: Some("You are Sunday. Use the tools you are given.".into()),
    }));

    let server = AppServer::bind_authenticated(&options.listen, runner, connection_token)
        .map_err(|e| CoreError::storage(format!("cannot listen on {}: {e}", options.listen)))?;
    let addr = server
        .local_addr()
        .map_err(|e| CoreError::storage(format!("cannot read the bound address: {e}")))?;

    // The address is printed so a UI can be pointed at it; the token is not, only
    // where to find it. A token in a log is a token in every crash report.
    println!("listening ws://{addr} protocol core.app_server.v1");
    if options.announce_token_path {
        println!("connection token: {}", token_path.display());
    }

    server.serve();
    let _ = lock.release();
    Ok(())
}

/// Everything the command line says about which model to use.
///
/// A struct rather than seven positional arguments, because `--api-key` next to
/// `--model-url` in a signature is exactly the pairing this file exists to make
/// explicit: those two travel together and must be approved together.
pub struct ModelChoice {
    pub script: Option<String>,
    pub base_url: Option<String>,
    pub model_id: Option<String>,
    pub api_key: Option<String>,
    /// `openai`, `anthropic` or `openai-compatible`. Defaults to compatible, which
    /// is what an unlabelled URL most likely is.
    pub provider: Option<String>,
    /// The explicit acknowledgement that lets `http://` to a local host through.
    pub allow_insecure_local: bool,
    /// The user is approving the configured endpoint right now, on this run.
    pub confirm_endpoint: bool,
}

/// Builds a model, but only after deciding whether its key may be sent there.
///
/// The order is: validate the endpoint, check the binding, and only then construct
/// a client. A client that exists is a client whose key was cleared, so there is no
/// window in which a request can be made with an unapproved destination.
pub fn model_from_args(
    choice: ModelChoice,
    data_dir: &std::path::Path,
) -> Result<(Arc<dyn sunday_protocol::Model>, String), sunday_protocol::CoreError> {
    use sunday_host::provider::{self, Admission, TransportPolicy, Vendor};
    use sunday_protocol::CoreError;

    if let Some(path) = choice.script {
        let text = std::fs::read_to_string(&path)
            .map_err(|e| CoreError::invalid(format!("cannot read {path}: {e}")))?;
        let model = crate::scripted::ScriptedModel::from_json(&text)?;
        return Ok((Arc::new(model), "scripted".into()));
    }
    let (Some(raw_url), Some(model_id)) = (choice.base_url, choice.model_id) else {
        return Err(CoreError::invalid(
            "pass either --script <file>, or --model-url <url> and --model <id>",
        ));
    };

    let vendor = match choice.provider.as_deref() {
        Some(raw) => Vendor::parse(raw).ok_or_else(|| {
            CoreError::invalid(format!(
                "unknown provider {raw:?}: use openai, anthropic or openai-compatible"
            ))
        })?,
        None => Vendor::Compatible,
    };

    let key = choice.api_key.unwrap_or_default();
    let key_present = !key.trim().is_empty();
    let binding_path = data_dir.join(provider::BINDINGS_FILE);
    let mut book = provider::ProviderBook::load(&binding_path);

    let transport = TransportPolicy {
        allow_insecure_local: choice.allow_insecure_local,
    };
    let admission = provider::admit(vendor, &raw_url, key_present, transport, &book)
        .map_err(|error| CoreError::invalid(error.to_string()))?;

    if let Admission::NeedsApproval { endpoint, .. } = &admission {
        if !choice.confirm_endpoint {
            // Refused, not warned. A warning is something a scripted start never
            // reads, and the whole point is that an edited config cannot carry the
            // key to a new host on its own.
            let prompt = admission
                .prompt(vendor)
                .unwrap_or_else(|| "this endpoint has not been approved".into());
            return Err(CoreError::Rejected {
                reason: format!(
                    "{prompt} Re-run with --confirm-endpoint to approve {} for {}.",
                    endpoint.label(),
                    vendor.display_name()
                ),
            });
        }
        book.approve(vendor, endpoint);
        book.save(&binding_path)?;
    }

    // The normalised form, never the raw flag: `Endpoint::base_url` cannot carry
    // credentials, a query string or stray whitespace into the request URL.
    let base_url = admission.endpoint().base_url();
    let client = match vendor {
        Vendor::Anthropic => {
            sunday_llm::LlmClient::new(sunday_llm::ProviderConfig::anthropic(base_url, key))?
        }
        Vendor::OpenAi | Vendor::Compatible => {
            sunday_llm::LlmClient::new(sunday_llm::ProviderConfig::openai(base_url, key))?
        }
    };
    Ok((Arc::new(client), model_id))
}

/// Parses the grant policy from flags. Default is reads only.
///
/// There is no `--auto-approve` any more. A flag that approves every side effect
/// cannot be made safe by documentation, and it was the default on Android.
pub fn policy_from_args(args: &[String]) -> GrantPolicy {
    let mut policy = GrantPolicy::read_only();
    let mut index = 0;
    while index < args.len() {
        if args[index] == "--grant" {
            if let Some(id) = args.get(index + 1) {
                policy.granted.insert(id.clone());
                index += 1;
            }
        }
        index += 1;
    }
    policy
}
